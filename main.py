"""
Main application module.

Contains responses to URIs.
"""

import configparser
from json import loads as json_loads
from json import dumps as json_dumps
from typing import Union, Literal
from time import time
from os import urandom
import flask
import pymongo
from Cryptodome.PublicKey import RSA
from Cryptodome.Cipher import AES, PKCS1_OAEP


config: configparser.ConfigParser = configparser.ConfigParser()
config.read("main.cfg")
application: flask.Flask = flask.Flask(__name__)
client: pymongo.MongoClient = pymongo.MongoClient(
    config["database"]["host"], int(config["database"]["port"]))
database = client.quest_log
challenge_cache: dict = {}


def fill_template(arguments, file: str) -> dict:
    """
    Given request arguments and JSON template file, complete template with \
        declared data.

    :param arguments: arguments to be applied to template
    :param file: path to JSON template file to be read from for template
    :type file: str
    :return: dictionary representation of JSON template completed with request
        arguments
    :rtype: dict
    """
    with open(file) as template_handler:
        template: dict = json_loads(template_handler.read())
    for field in template:
        try:
            template[field] = arguments[field]
        except KeyError:
            continue
    return template


def fix_challenge(username: str) -> None:
    """
    Given username, check if challenge assigned has expired. If so, replace it.

    Uses database connection to retrieve GPG public key to encrypt a string \
        of random characters, the truth string, which is used to authenticate \
            requests.

    Will also create new challenges if no challenge entry for the username \
        exists.

    :param username: name of user to be referenced
    :type username: str
    """
    if username in challenge_cache:
        if challenge_cache[username]["expiry"] > time():
            return None
        challenge_cache.pop(username)
    solution = urandom(int(config["auth"]["challenge_truth_length"])).hex()
    session = urandom(16)
    cipher = AES.new(session, AES.MODE_EAX)
    final = cipher.encrypt_and_digest(solution.encode("ascii"))  # type: ignore
    challenge_cache.update({username: {
        "solution": solution,
        "challenge": final[0].hex(),
        "session": PKCS1_OAEP.new(RSA.import_key(database["users"].find_one({
            "name": username})["key"].encode("ascii"))).encrypt(session).hex(),
        "nonce": cipher.nonce.hex(),  # type: ignore
        "tag": final[1].hex(),
        "expiry": time() + int(config["auth"]["challenge_expiry_time"])}})


def validate_challenge(username: Union[str, None], solution: str) -> bool:
    """
    Check if solution to challenge is valid for given user.

    :return: True or False for whether or not the solution was correct
    :rtype: bool
    """
    if username is None:
        return False
    fix_challenge(username)
    try:
        return challenge_cache[username]["solution"] == solution
    except KeyError:
        return False


def enforce_types(document, template: str) -> bool:
    """
    Check if dictionary representing JSON document matches key-value pair \
        typing, compared to absolute templates.

    :param document: dictionary to check
    :param template: path to template to read from
    :type template: str
    :return: boolean for whether the dictionary passed or not
    :rtype: bool
    """
    with open(template) as template_handler:
        template_data: dict = json_loads(template_handler.read())
        for key in template_data:
            if key == "endTime":
                if document.get(key) not in [int, None]:
                    return False
                continue
            if document.get(key) and not isinstance(
                    document.get(key), type(template_data[key])):
                return False
    return True


def enforce_keys(document, keys: list) -> bool:
    """
    Check if dictionary representing JSON document is missing keys given.

    :param document: dictionary to check
    :param keys: list of keys to check for
    :type keys: list
    :return: boolean for whether the dictionary passed or not
    :rtype: bool
    """
    for key in keys:
        if key not in document:
            return False
    return True


def update_dict_inline(origin: dict, changes: dict) -> dict:
    """
    Update origin dictionary with changes dictionary.

    Saves having to add extra lines simply for updating dictionaries, as it \
        simplifies:

    data = {}
    data.update({None: None})
    function_using_data(data)

    To:

    function_using_data(update_dict_inline({}, {None: None}))

    :param origin: original dictionary
    :type origin: dict
    :param changes: changes dictionary
    :type changes: dict
    :return: original dictionary updated with changes dictionary
    :rtype: dict
    """
    origin.update(changes)
    return origin


def empty_dict_if_none(data: Union[None, dict]) -> dict:
    """
    If None, return empty dictionary, otherwise return originial dictionary.

    There's totally a better way of expressing this, cleverly, without an \
        if statement.

    :param data: data that might be None, or a populated dictionary
    :type data: Union[None, dict]
    :return: empty dictionary if None, or the original populated dictionary
    :rtype: dict
    """
    if not data:
        return {}
    return data


@application.route("/api/user/<username>",
                   methods=["PUT", "PATCH", "DELETE", "GET"])
def api_user_handle(username: str) -> flask.Response:
    """
    Respond to PUT/PATCH/DELETE/GET requests for user management API.

    :param username: name of user to be processed with request
    :type username: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    user_data: Union[None, dict] = \
        database["users"].find_one({"name": username})
    if not user_data and flask.request.method != "PUT":
        return flask.Response('{"error": "Resource does not exist."}', 404,
                              mimetype="application/json")
    if user_data and flask.request.method == "PUT":
        return flask.Response('{"error": "Resource already exists."}', 409,
                              mimetype="application/json")
    if user_data:
        user_data.pop("_id")
    if flask.request.method == "GET":
        return flask.Response(json_dumps(user_data), 200,
                              mimetype="application/json")
    arguments = empty_dict_if_none(flask.request.get_json())
    if not enforce_types(arguments, "json/user.json"):
        return flask.Response('{"error": "Invalid request argument types."}',
                              422, mimetype="application/json")
    if flask.request.method == "PUT":
        if enforce_keys(arguments, ["key", "email"]):
            try:
                RSA.import_key(arguments["key"].encode("ascii"))
            except ValueError:
                return flask.Response('{"error": "Key is not acceptable as RSA'
                                      ' user public key."}', 422,
                                      mimetype="application/json")
            database["users"].insert_one(update_dict_inline(fill_template(
                arguments, "json/user.json"), {"name": username}))
            return flask.Response("", 201, mimetype="application/json")
        return flask.Response(
            '{"error": "Request missing arguments."}', 422,
            mimetype="application/json")
    # from here, all methods require authentication
    if "solution" not in arguments:
        return flask.Response('{"error": "Request missing arguments."}', 422,
                              mimetype="application/json")
    if validate_challenge(
            username, arguments["solution"]) is not True:
        return flask.Response('{"error": "Unauthorized."}', 401,
                              mimetype="application/json")
    if flask.request.method == "PATCH":
        if not enforce_keys(flask.request.get_json(), ["key", "email"]):
            return flask.Response(
                '{"error": "Request missing arguments."}', 422,
                mimetype="application/json")
        database["users"].update_one(
            {"name": username}, {key: value for key, value in fill_template(
                flask.request.get_json(), "json/user.json").items() if value})
        return flask.Response("", 204, mimetype="application/json")
    if flask.request.method == "DELETE":
        database["users"].delete_one({"name": username})
        return flask.Response("", 204, mimetype="application/json")
    return flask.Response('{"error": "Method not allowed."}', 405,
                          mimetype="application/json")


@application.route("/api/challenge/<username>", methods=["GET"])
def api_user_auth_challenge_handle(username: str) -> flask.Response:
    """
    Respond to GET requests for retrieving GPG auth challenges.

    :param username: name of user to be processed with request
    :type username: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    if database["users"].find_one({"name": username}) is not None:
        fix_challenge(username)
        challenge = challenge_cache[username].copy()
        challenge.pop("solution")
        return flask.Response(json_dumps(challenge), 200,
                              mimetype="application/json")
    return flask.Response('{"error": "Resource does not exist."}', 404,
                          mimetype="application/json")


@application.route("/api/todo/<todo>",
                   methods=["PUT", "PATCH", "DELETE", "GET"])
def api_todo_handle(todo: str) -> flask.Response:
    """
    Respond to PUT/PATCH/DELETE/GET requests for to-do management API.

    :param todo: name of todo to be processed with request
    :type todo: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    todo_data: Union[None, dict] = database["todo"].find_one({"name": todo})
    if not todo_data and flask.request.method != "PUT":
        return flask.Response('{"error": "Resource already exists."}', 409,
                              mimetype="application/json")
    if todo_data and flask.request.method == "PUT":
        return flask.Response('{"error": "Resource does not exist."}', 404,
                              mimetype="application/json")
    if todo_data:
        todo_data.pop("_id")
    if flask.request.method == "GET":
        return flask.Response(json_dumps(todo_data), 200,
                              mimetype="application/json")
    arguments = empty_dict_if_none(flask.request.get_json())
    if not enforce_types(arguments, "json/todo.json"):
        return flask.Response('{"error": "Invalid request argument types."}',
                              422, mimetype="application/json")
    # from here, all methods require authentication
    if not enforce_keys(flask.request.get_json(), ["author", "solution"]):
        return flask.Response('{"error": "Request missing arguments."}', 422,
                              mimetype="application/json")
    if database["user"].find_one(
            {"name": arguments["author"]}) is None:
        return flask.Response('{"error": "Resource linkage to user does not '
                              'exist."}', 422, mimetype="application/json")
    if todo_data and todo_data["author"] != arguments["author"] or \
            validate_challenge(arguments["author"], arguments["solution"]) is \
            not True:
        return flask.Response('{"error": "Unauthorized."}', 401,
                              mimetype="application/json")
    if flask.request.method in ["PUT", "PATCH"]:
        for project in arguments.get("projects", []):
            if database["project"].find_one(project) is None or (
                    arguments["author"] not in database["project"].
                    find_one(project)["contributors"] and flask.request.
                    args["author"] != database["project"]
                    .find_one(project)["author"]):
                return flask.Response(
                    '{"error": "Resource linkage to project is not authorized '
                    'or does not exist."}', 422, mimetype="application/json")
    if flask.request.method == "PUT":
        database["todo"].insert_one(update_dict_inline(
            fill_template(flask.request.get_json(), "json/todo.json"),
            {"name": todo}))
    if flask.request.method == "PATCH":
        database["todo"].update_one(
            {"name": todo}, {key: value for key, value in fill_template(
                flask.request.get_json(), "json/todo.json").items() if value})
        return flask.Response("", 204, mimetype="application/json")
    if flask.request.method == "DELETE":
        database["todo"].delete_one({"name": todo})
        return flask.Response("", 204, mimetype="application/json")
    return flask.Response('{"error": "Method not allowed."}', 405,
                          mimetype="application/json")


@application.route("/api/project/<project>",
                   methods=["PUT", "PATCH", "DELETE", "GET", "POST"])
def api_project_handle(project: str) -> flask.Response:
    """
    Respond to PUT/PATCH/DELETE/GET/POST requests for project management API.

    :param project: name of project to be processed with request
    :type project: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    project_data: Union[None, dict] = \
        database["project"].find_one({"name": project})
    if not project_data and flask.request.method != "PUT":
        return flask.Response('{"error": "Resource does not exist."}', 404,
                              mimetype="application/json")
    if project_data and flask.request.method == "PUT":
        return flask.Response('{"error": "Resource already exists."}', 409,
                              mimetype="application/json")
    if project_data:
        project_data.pop("_id")
    if flask.request.method == "GET":
        return flask.Response(json_dumps(project_data), 200,
                              mimetype="application/json")
    arguments = empty_dict_if_none(flask.request.get_json())
    if not enforce_types(arguments, "json/project.json"):
        return flask.Response('{"error": "Invalid request argument types.',
                              422, mimetype="application/json")
    if database["user"].find_one({"name": arguments.get("author", "")}) is \
            None and database["user"].find_one({"name": arguments.get(
                "contributor", "")}) is None:
        return flask.Response(
            '{"error": "Resource linkage to user does not exist."}', 422,
            mimetype="application/json")
    if flask.request.method == "POST":
        if enforce_keys(arguments, ["solution", "contributor"]):
            if "author" in arguments:
                if validate_challenge(arguments["author"],
                                      arguments["solution"]) is not True:
                    return flask.Response('{"error": "Unauthorized."}', 401,
                                          mimetype="application/json")
                if "remove" in arguments:
                    if project_data and arguments["contributor"] not \
                            in project_data["contributors"]:
                        return flask.Response(
                            '{"error": "User not in contributors."}',
                            404, mimetype="application/json")
                    database["project"].find_one_and_update(
                        {"name": project}, {"$pull": {
                            "contributors": arguments[
                                "contributor"]}})
                elif "cancel" in arguments:
                    if project_data and arguments["contributor"] not \
                            in project_data["invitations"]:
                        return flask.Response(
                            '{"error": "Invitation does not exist."}', 404,
                            mimetype="application/json")
                    database["project"].find_one_and_update(
                        {"name": project}, {"$pull": {
                            "invitations": arguments["contributor"]}})
                else:
                    database["project"].find_one_and_update(
                        {"name": project}, {"$addToSet": {
                            "invitations": arguments["contributor"]}})
                return flask.Response("", 204, mimetype="application/json")
            if validate_challenge(arguments["contributor"],
                                  arguments["solution"]) is not True:
                return flask.Response('{"error": "Unauthorized."}', 401,
                                      mimetype="application/json")
            if project_data and arguments["contributor"] not in \
                    project_data["invitations"]:
                return flask.Response('{"error": "User not in invitations."}',
                                      422, mimetype="application/json")
            database["project"].find_one_and_update(
                {"name": project}, {"$pull": {
                    "invitations": arguments["contributor"]}})
            if "decline" not in arguments:
                database["project"].find_one_and_update(
                    {"name": project}, {"$addToSet": {
                        "contributors": arguments["contributor"]}})
            return flask.Response("", 204, mimetype="application/json")
        return flask.Response('{"error": "Request missing arguments."}',
                              422, mimetype="application/json")
    if "contributors" in arguments or "invitations" in arguments:
        return flask.Response('{"error": "Contributors and invitations '
                              'cannot be modified through PATCH, PUT, or '
                              'DELETE."}', 422, mimetype="application/json")
    if flask.request.method == "PATCH":
        if ("contributor" not in arguments or "author" not in arguments) or \
                "solution" not in arguments:
            return flask.Response('{"error": "Request missing arguments."}',
                                  422, mimetype="application/json")
        if "contributor" in arguments and "author" in arguments:
            return flask.Response(
                '{"error": "Cannot authenticate as both author and ' +
                'contributor."}', 422, mimetype="application/json")
        if project_data and "contributor" in arguments and \
                arguments["contributor"] not in project_data["contributors"]:
            return flask.Response('{"error": "Unauthorized."}', 401,
                                  mimetype="application/json")
        if project_data and "author" in arguments and \
                arguments["author"] != project_data["author"]:
            return flask.Response('{"error": "Unauthorized."}', 401,
                                  mimetype="application/json")
        if validate_challenge(arguments.get("author"), arguments["solution"]) \
                is not True and validate_challenge(
                    arguments.get("contributor"), arguments["solution"]) is \
                not True:
            return flask.Response('{"error": "Unauthorized."}', 401,
                                  mimetype="application/json")
        if project_data is not None:
            database["project"].update_one(
                {"name": project}, {key: value for key, value in fill_template(
                    flask.request.get_json(), "json/project.json").items() if
                                    value})
            return flask.Response("", 204, mimetype="application/json")
        return flask.Response('{"error": "Resource does not exist."}', 404,
                              mimetype="application/json")
    if not enforce_keys(flask.request.get_json(), ["author", "solution"]):
        return flask.Response('{"error": "Request missing arguments."}', 422,
                              mimetype="application/json")
    if validate_challenge(arguments["author"],
                          arguments["solution"]) is not True:
        return flask.Response('{"error": "Unauthorized."}', 401,
                              mimetype="application/json")
    # from here, all methods require AUTHOR authentication
    if flask.request.method == "PUT":
        database["project"].insert_one(update_dict_inline(
            fill_template(flask.request.get_json(), "json/project.json"),
            {"name": project}))
        return flask.Response("", 201, mimetype="application/json")
    if flask.request.method == "DELETE":
        database["project"].delete_one({"name": project})
        return flask.Response("", 204, mimetype="application/json")
    return flask.Response('{"error": "Method not allowed."}', 405,
                          mimetype="application/json")


@application.route("/api/<resource>", methods=["GET"])
def api_user_index_handle(resource: Literal["user", "todo", "project"]) -> \
        flask.Response:
    """
    Respond to GET requests for list of items in resource collection.

    :param resource: name of resource
    :type resource: Literal["user", "todo", "project"]
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    if resource not in ["user", "todo", "project"]:
        return flask.Response('{"error": "Resource type unknown."}')
    return flask.Response(
        '{"resource": "' + resource + '", "items": ' + str(
            database[resource].find({}, {"_id": 0, "name": 1})) + '}', 200,
        mimetype="application/json")


if __name__ == "__main__":
    application.run(debug=True, port=80)

"""
Main application module.

Contains responses to URIs.
"""

import configparser
from json import loads as json_loads
from typing import Union
from time import time
from os import urandom
import flask
import pymongo
import gnupg


config: configparser.ConfigParser = configparser.ConfigParser()
config.read("main.cfg")
application: flask.Flask = flask.Flask(__name__)
database: pymongo.MongoClient = \
    pymongo.MongoClient(config["database"]["host"]).quest_log
challenge_cache: dict = {}


def fill_template(arguments: flask.request.ImmutableMultiDict, file: str) -> \
        dict:
    """
    Given request arguments and JSON template file, complete template with \
        declared data.

    :param arguments: arguments to be applied to template
    :type arguments: flask.request.ImmutableMultiDict
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
    gpg = gnupg.GPG()
    gpg.import_keys(database["users"][username]["key"])
    challenge_cache.update({username: {
        "solution": solution,
        "challenge": gpg.encrypt(solution, ""),
        "expiry": time() + int(config["auth"]["challenge_expiry_time"])
        }})


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


def enforce_types(document: dict, template: str) -> bool:
    """
    Check if dictionary representing JSON document matches key-value pair \
        typing, compared to absolute templates.

    :param document: dictionary to check
    :type document: dict
    :param template: path to template to read from
    :type template: str
    :return: boolean for whether the dictionary passed or not
    :rtype: bool
    """
    with open(template) as template_handler:
        template: dict = json_loads(template_handler.read())
        for key in template:
            if key == "endTime":
                if document.get(key) not in [int, None]:
                    return False
                continue
            if document.get(key) and isinstance(document.get(key),
                                                type(template[key])):
                return False
    return True


def enforce_keys(document: dict, keys: list) -> bool:
    """
    Check if dictionary representing JSON document is missing keys given.

    :param document: dictionary to check
    :type document: dict
    :param keys: list of keys to check for
    :type keys: list
    :return: boolean for whether the dictionary passed or not
    :rtype: bool
    """
    for key in keys:
        if key not in document:
            return False
    return True


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
    if not enforce_types(dict(flask.request.args), "json/user.json"):
        return flask.Response('{"error": "Invalid request argument types."}',
                              422, mimetype="application/json")
    user_data: Union[None, dict] = \
        database["users"].find_one({"name": username})
    if flask.request.method == "PUT":
        if user_data is None:
            if enforce_keys(dict(flask.request.args), ["key", "email"]):
                database["users"].insert_one(
                    fill_template(flask.request.args, "json/user.json") +
                    {"name": username})
                return flask.Response("", 201, mimetype="application/json")
            return flask.Response(
                '{"error": "Request missing arguments."}', 422,
                mimetype="application/json")
        return flask.Response('{"error": "Resource already exists."}', 409,
                                mimetype="application/json")
    # from here, all methods require resource to exist
    if user_data is None:
        return flask.Response('{"error": "Resource does not exist."}', 404,
                              mimetype="application/json")
    if flask.request.method == "GET":
        return flask.Response(user_data, 200, mimetype="application/json")
    # from here, all methods require authentication
    if "solution" not in flask.request.args:
        return flask.Response('{"error": "Request missing arguments."}', 422,
                              mimetype="application/json")
    if validate_challenge(
            username, flask.request.args["solution"]) is not True:
        return flask.Response('{"error": "Unauthorized."}', 401,
                                mimetype="application/json")
    if flask.request.method == "PATCH":
        if not enforce_keys(dict(flask.request.args), ["key", "email"]):
            return flask.Response(
                '{"error": "Request missing arguments."}', 422,
                mimetype="application/json")
        database["users"].update_one(
            {"name": username}, {key: value for key, value in fill_template(
                flask.request.args, "json/user.json").items() if value})
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
        return flask.Response('{"challenge": "' + challenge_cache[username] +
                              '"}', 200, mimetype="application/json")
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
    if not enforce_types(dict(flask.request.args), "json/todo.json"):
        return flask.Response('{"error": "Invalid request argument types.',
                              422, mimetype="application/json")
    todo_data: Union[None, dict] = database["todo"].find_one({"name": todo})
    # from here, all methods require resource to exist, unless method is PUT
    if todo_data is None and flask.request.method != "PUT":
        return flask.Response('{"error": "Resource does not exist."}', 404,
                              mimetype="application/json")
    if flask.request.method == "GET":
        return flask.Response(todo_data, 200, mimetype="application/json")
    # from here, all methods require authentication
    if not enforce_keys(dict(flask.request.args), ["author", "solution"]):
        return flask.Response('{"error": "Request missing arguments."}',
                                422, mimetype="application/json")
    if database["user"].find_one(
            {"name": flask.request.args["author"]}) is None:
        return flask.Response('{"error": "Resource linkage to user does not '
                              'exist."}', 422, mimetype="application/json")
    if todo_data["author"] != flask.request.args["author"] or \
            validate_challenge(flask.request.args["author"],
                                flask.request.args["solution"]) is not True:
        return flask.Response('{"error": "Unauthorized."}', 401,
                                mimetype="application/json")
    if flask.request.method in ["PUT", "PATCH"]:
        for project in flask.request.args.get("projects", []):
            if database["project"].find_one(project) is None or (
                    flask.request.args["author"] not in database["project"].
                    find_one(project)["contributors"] and flask.request.
                    args["author"] != database["project"]
                    .find_one(project)["author"]):
                return flask.Response(
                    '{"error": "Resource linkage to project is not ' +
                    'authorized or does not exist."}', 422,
                    mimetype="application/json")
    if flask.request.method == "PUT":
        if todo_data is None:
            database["todo"].insert_one(fill_template(
                flask.request.args, "json/todo.json") + {"name": todo})
            return flask.Response("", 201, mimetype="application/json")
        return flask.Response('{"error": "Resource already exists."}', 409,
                                mimetype="application/json")
    if flask.request.method == "PATCH":
        database["todo"].update_one(
            {"name": todo}, {key: value for key, value in fill_template(
                flask.request.args, "json/todo.json").items() if value})
        return flask.Response("", 204, mimetype="application/json")
    if flask.request.method == "DELETE":
        database["todo"].delete_one({"name": todo})
        return flask.Response("", 204, mimetype="application/json")

@application.route("/api/project/<project>",
                   methods=["PUT", "PATCH", "DELETE", "GET", "POST"])
def api_project_handle(project: str) -> flask.Response:
    """
    Respond to PUT/PATCH/DELETE/GET/POST requests for project management API.

    FIXME refactor, repeating conditionals and general spaghetti
    FIXME allow contributors to remove themselves from the contributors list
    FIXME check if contributor exists when adding new contributors

    :param project: name of project to be processed with request
    :type project: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    if not enforce_types(dict(flask.request.args), "json/project.json"):
        return flask.Response('{"error": "Invalid request argument types.',
                              422, mimetype="application/json")
    project_data: Union[None, dict] = \
        database["project"].find_one({"name": project})
    if flask.request.method == "GET":
        if project_data is not None:
            return flask.Response(project_data, 200,
                                  mimetype="application/json")
        return flask.Response('{"error": "Resource does not exist."}', 404,
                              mimetype="application/json")
    if "author" in flask.request.args and database["user"].find_one(
            {"name": flask.request.args["author"]}) is None:
        return flask.Response(
            '{"error": "Resource linkage to user does not exist."}', 422,
            mimetype="application/json")
    if "contributor" in flask.request.args and database["user"].find_one(
            {"name": flask.request.args["contributor"]}) is None:
        return flask.Response(
            '{"error": "Resource linkage to user does not exist."}', 422,
            mimetype="application/json")
    if flask.request.method == "POST":
        if project_data is None:
            return flask.Response('{"error": "Resource does not exist."}', 404,
                                  mimetype="application/json")
        if enforce_keys(dict(flask.request.args), ["solution", "contributor"]):
            if "author" in flask.request.args:
                if validate_challenge(flask.request.args["author"],
                                      flask.request.args["solution"]) is not \
                                          True:
                    return flask.Response('{"error": "Unauthorized."}', 401,
                                            mimetype="application/json")
                if "remove" in flask.request.args:
                    if flask.request.args["contributor"] not in \
                            project_data["contributors"]:
                        return flask.Response(
                            '{"error": "User not found to in contributors."}',
                            404, mimetype="application/json")
                    database["project"].find_one_and_update(
                        {"name": project}, {"$pull": {"contributors":
                            flask.request.args["contributor"]}})
                elif "cancel" in flask.request.args:
                    if flask.request.args["contributor"] not in \
                            project_data["invitations"]:
                        return flask.Response(
                            '{"error": "Invitation does not exist."}', 404,
                            mimetype="application/json")
                    database["project"].find_one_and_update(
                        {"name": project}, {"$pull": {"invitations":
                            flask.request.args["contributor"]}})
                else:
                    database["project"].find_one_and_update(
                        {"name": project}, {"$addToSet": {"invitations":
                            flask.request.args["contributor"]}})
                return flask.Response("", 204, mimetype="application/json")
            if validate_challenge(flask.request.args["contributor"],
                                flask.request.args["solution"]) is not True:
                return flask.Response('{"error": "Unauthorized."}', 401,
                                        mimetype="application/json")
            if flask.request.args["contributor"] not in \
                    project_data["invitations"]:
                return flask.Response(
                    '{"error": "User not in invitations for project."}', 422,
                    mimetype="application/json")
            database["project"].find_one_and_update(
                {"name": project}, {"$pull": {"invitations":
                    flask.request.args["contributor"]}})
            if "decline" not in flask.request.args:
                database["project"].find_one_and_update(
                    {"name": project}, {"$addToSet": {"contributors":
                        flask.request.args["contributor"]}})
            return flask.Response("", 204, mimetype="application/json")
        return flask.Response('{"error": "Request missing arguments."}',
                              422, mimetype="application/json")
    if "contributors" in flask.request.args or "invitations" in \
            flask.request.args:
        return flask.Response('{"error": "Contributors and invitations '
                              'cannot be modified through PATCH, PUT, or '
                              'DELETE."}', 422, mimetype="application/json")
    if flask.request.method == "PATCH":
        if project_data is None:
            return flask.Response('{"error": "Resource does not exist."}', 404,
                                  mimetype="application/json")
        if ("contributor" not in flask.request.args or "author" not in
                flask.request.args) or "solution" not in \
                flask.request.args:
            return flask.Response('{"error": "Request missing arguments."}',
                                  422, mimetype="application/json")
        if "contributor" in flask.request.args and "author" in \
                flask.request.args:
            return flask.Response(
                '{"error": "Cannot authenticate as both author and ' +
                'contributor."}', 422, mimetype="application/json")
        if "contributor" in flask.request.args and \
                flask.request.args["contributor"] not in \
                    project_data["contributors"]:
            return flask.Response('{"error": "Unauthorized."}', 401,
                                  mimetype="application/json")
        if "author" in flask.request.args and \
                flask.request.args["author"] != project_data["author"]:
            return flask.Response('{"error": "Unauthorized."}', 401,
                                  mimetype="application/json")
        if validate_challenge(
                flask.request.args.get("author"),
                flask.request.args["solution"]) is not True and \
                    validate_challenge(
                        flask.request.args.get("contributor"),
                        flask.request.args["solution"]) is not True:
            return flask.Response('{"error": "Unauthorized."}', 401,
                                  mimetype="application/json")
        if project_data is not None:
            database["project"].update_one(
                {"name": project}, {key: value for key, value in \
                    fill_template(flask.request.args,
                                    "json/project.json").items() if value})
            return flask.Response("", 204, mimetype="application/json")
        return flask.Response('{"error": "Resource does not exist."}', 404,
                            mimetype="application/json")
    if not enforce_keys(dict(flask.request.args), ["author", "solution"]):
        return flask.Response('{"error": "Request missing arguments."}',
                                422, mimetype="application/json")
    if validate_challenge(flask.request.args["author"],
                            flask.request.args["solution"]) is not True:
        return flask.Response('{"error": "Unauthorized."}', 401,
                                mimetype="application/json")
    if flask.request.method == "PUT":
        if project_data is None:
            database["project"].insert_one(
                fill_template(flask.request.args, "json/project.json") +
                {"name": project})
            return flask.Response("", 201, mimetype="application/json")
        return flask.Response('{"error": "Resource already exists."}', 409,
                                mimetype="application/json")
    if flask.request.method == "DELETE":
        if project_data is not None:
            database["project"].delete_one({"name": project})
            return flask.Response("", 204, mimetype="application/json")
        return flask.Response('{"error": "Resource does not exist."}', 404,
                                mimetype="application/json")
    return flask.Response('{"error": "Method not allowed."}', 405,
                          mimetype="application/json")

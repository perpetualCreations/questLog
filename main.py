"""
Main application module.

Contains responses to URIs.
"""

import configparser
from json import dumps as json_dumps
from json import loads as json_loads
from typing import Union, Literal, Tuple, Dict, List, Optional, Any
from string import Template
from time import time
from os import urandom
from ast import literal_eval
import flask
import pydgraph
from Cryptodome.PublicKey import RSA
from Cryptodome.Cipher import AES, PKCS1_OAEP


# load configuration file.
config: configparser.ConfigParser = configparser.ConfigParser()
config.read("main.cfg")


def graph_connect() -> Tuple[pydgraph.DgraphClientStub, pydgraph.DgraphClient]:
    """Create Dgraph server connection and client."""
    connection: pydgraph.DgraphClientStub = \
        pydgraph.DgraphClientStub(config["database"]["host"])
    return connection, pydgraph.DgraphClient(connection)


# set dgraph database schema.
with open("schema/data.schema") as schema_handler:
    connection, client = graph_connect()
    client.alter(pydgraph.Operation(schema=schema_handler.read()))
    connection.close()
# start flask server.
application: flask.Flask = flask.Flask(__name__)
# create challenge dictionary variable, for storing authentication challenges
challenge_cache: dict = {}


def graph_get(query: Literal["user", "userkey", "uid"],
              parameters: Dict[str, str]) -> List[dict]:
    """
    Handle query to the Dgraph server, given a query name.

    :param query: name of defined query
    :type query: Literal["user", "userkey"]
    :param parameters: dictionary containing query parameters to subsitute into
        template query
    :type parameters: Dict[str, str]
    :return: query data returned from database server
    :rtype: dict
    """
    with open("schema/" + query + ".query") as query_handler:
        connection, client = graph_connect()
        result = json_loads(client.txn(read_only=True).query(
            Template(query_handler.read()).substitute(parameters)).json)
        connection.close()
        if result["data"] is None:
            raise Exception(result["errors"])
        return result["data"][query]


def graph_create(ntype: Literal["user"], parameters: Dict[str, Any]) -> \
        Optional[str]:
    """
    Handle creation mutation to the Dgraph server, given a type.

    :param ntype: name of defined type
    :type ntype: Literal["user"]
    :param parameters: dictionary containing type parameters to subsitute into
        template type
    :type parameters: Dict[str, Any]
    :raises TypeError: type-related exception if supplied parameters have
        incorrect types, passes key with invalid type as exception message
    :return: UID of created node, or None if creation failed
    :rtype: Optional[str]
    """
    with open("schema/" + ntype + ".type") as create_handler:
        connection, client = graph_connect()
        transaction = client.txn()
        try:
            data = literal_eval(create_handler.read())
            for key in data.keys():
                if not isinstance(parameters[key], type(data[key])):
                    raise TypeError(key)
                data[key] = parameters[key]
            data.update({"uid": "_:new", "dgraph.type": ntype.capitalize()})
            response = transaction.mutate(set_obj=data)
            transaction.commit()
            return response.uids["new"]
        finally:
            transaction.discard()


def graph_delete(uid: str) -> None:
    """
    Handle deletion mutation to the Dgraph server, given a UID.

    :param uid: UID of node for deletion
    :type uid: str
    :return: None
    """
    connection, client = graph_connect()
    transaction = client.txn()
    try:
        transaction.mutate(del_obj={"uid": uid})
        transaction.commit()
    finally:
        transaction.discard()


def check_key(key: str) -> Optional[flask.Response]:
    """
    Check if given RSA public key is acceptable.

    :param key: supplied RSA key
    :type key: str
    :return: error response if key is not valid
    :rtype: Optional[flask.Response]
    """
    try:
        RSA.import_key(key.encode("ascii"))
        return None
    except ValueError:
        return flask.Response('{"error": "Key is not acceptable as RSA'
                              ' user public key."}', 422,
                              mimetype="application/json")


def fix_challenge(uid: str) -> Optional[str]:
    """
    Given UID, check if challenge assigned has expired. If so, replace it.

    Uses database connection to retrieve GPG public key to encrypt a string \
        of random characters, the truth string, which is used to authenticate \
            requests.

    Will also create new challenges if no challenge entry for the uid exists.

    :param uid: name of user to be referenced
    :type uid: str
    :return: if key retrieval by UID failed due to a request error, string
        containing the contents of the error message
    :rtype: Optional[str]
    """
    if uid in challenge_cache:
        if challenge_cache[uid]["expiry"] > time():
            return None
        challenge_cache.pop(uid)
    try:
        key = graph_get("userkey", {"uid": uid})[0]["key"]
    except Exception as error:
        return json_dumps(error)
    except IndexError:
        return None
    except KeyError:
        return None
    solution = urandom(int(config["auth"]["challenge_truth_length"])).hex()
    session = urandom(16)
    cipher = AES.new(session, AES.MODE_EAX)
    final = cipher.encrypt_and_digest(solution.encode("ascii"))  # type: ignore
    challenge_cache.update({uid: {
        "solution": solution,
        "challenge": final[0].hex(),
        "session": PKCS1_OAEP.new(RSA.import_key(key.encode("ascii")))
        .encrypt(session).hex(),
        "nonce": cipher.nonce.hex(),  # type: ignore
        "tag": final[1].hex(),
        "expiry": time() + int(config["auth"]["challenge_expiry_time"])}})
    # return statement to make mypy happy.
    return None


def validate_challenge(uid: str, solution: str) -> Union[bool, str]:
    """
    Check if solution to challenge is valid for given user.

    :return: True or False for whether or not the solution was correct
    :rtype: bool
    """
    fix_out = fix_challenge(uid)
    if fix_out:
        return fix_out
    try:
        return challenge_cache[uid]["solution"] == solution
    except KeyError:
        return False


def check_exists(data: list) -> flask.Response:
    """
    If query data is empty, return flask.Response object declaring that the \
        requested resource does not exist. Otherwise, throw exception.

    :param data: query data returned from a graph request
    :type data: list
    :return: error response
    :rtype: flask.Response
    :raises Exception: generic exception if query is not empty
    """
    if data:
        raise Exception("Query is not empty.")
    return flask.Response('{"error": "Resource does not exist."}', 404,
                          mimetype="application/json")


def check_not_exists(data: list) -> flask.Response:
    """
    If query data is not empty, return flask.Response object declaring that \
        the requested resource already exists. Otherwise, throw exception.

    :param data: query data returned from a graph request
    :type data: list
    :return: error response
    :rtype: flask.Response
    :raises Exception: generic exception if query is empty
    """
    if not data:
        raise Exception("Query is empty.")
    return flask.Response('{"error": "Resource already exists."}', 409,
                          mimetype="application/json")


def empty_dict_if_none(data: Union[None, dict]) -> dict:
    """
    If None, return empty dictionary, otherwise return originial dictionary.

    :param data: data that might be None, or a populated dictionary
    :type data: Union[None, dict]
    :return: empty dictionary if None, or the original populated dictionary
    :rtype: dict
    """
    if not data:
        return {}
    return data


@application.route("/api/uid/<name>", methods=["GET"])
def api_uid_handle(name: str) -> flask.Response:
    """
    Respond to GET requests for getting UID of a node by its name.

    :param name: name of node to search for
    :type name: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    return flask.Response(json_dumps({"data": graph_get(
        "uid", {"name": name})}), 200, mimetype="application/json")


@application.route("/api/user/<uid>", methods=["GET"])
def api_user_handle_get(uid: str) -> flask.Response:
    """
    Respond to GET requests for user management API.

    :param uid: UID of user to be processed with request
    :type uid: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    data = graph_get("user", {"uid": uid})
    try:
        return check_exists(data)
    except Exception:
        return flask.Response(
            json_dumps({"data": data}), 200, mimetype="application/json")


@application.route("/api/challenge/<uid>", methods=["GET"])
def api_user_auth_challenge_handle(uid: str) -> flask.Response:
    """
    Respond to GET requests for retrieving authentication challenges.

    :param uid: UID of user to be processed with request
    :type uid: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    data = graph_get("user", {"uid": uid})
    try:
        return check_exists(data)
    except Exception:
        fix_out = fix_challenge(uid)
        if fix_out:
            return flask.Response(json_dumps({"error": fix_out}), 500,
                                  mimetype="application/json")
        challenge = challenge_cache[uid].copy()
        # i hate how the removal of this one line will thwart authentication
        challenge.pop("solution")
        return flask.Response(json_dumps(challenge), 200,
                              mimetype="application/json")


@application.route("/api/user/", methods=["PUT"])
def api_user_handle_put() -> flask.Response:
    """
    Respond to PUT requests for user management API.

    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    arguments = empty_dict_if_none(flask.request.get_json())
    try:
        data = graph_get("uid", {"name": arguments["name"]})
        if config["database"]["fraud"] is False:
            try:
                return check_exists(data)
            except Exception:
                pass
        check_key_result = check_key(arguments["key"])
        if check_key_result:
            return check_key_result
        try:
            uid = graph_create("user", arguments)
            if not uid:
                return flask.Response(
                    '{"error": "Unable to produce UID, creation has likely '
                    'failed."}', 500, mimetype="application/json")
        except TypeError as invalid_key:
            return flask.Response(
                '{"error": "Invalid request argument type(s), exception thrown'
                ' on key ' + str(invalid_key) + '."}', 422,
                mimetype="application/json")
    except KeyError:
        flask.Response('{"error": "Request missing arguments."}', 422,
                       mimetype="application/json")
    # str() call is redundant, to appease the mypy gods.
    return flask.Response('{"uid":"' + str(uid) + '"}', 201,
                          mimetype="application/json")


@application.route("/api/user/<uid>", methods=["PATCH", "DELETE"])
def api_user_handle_patch_and_delete(uid: str) -> flask.Response:
    """
    Respond to PATCH/DELETE requests for user management API.

    :param uid: UID of user to be processed with request
    :type uid: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    data = graph_get("user", {"uid": uid})
    arguments = empty_dict_if_none(flask.request.get_json())
    try:
        return check_exists(data)
    except Exception:
        try:
            if validate_challenge(uid, arguments["solution"]) is False:
                return flask.Response('{"error": "Unauthorized."}', 401,
                                      mimetype="application/json")
            if flask.request.method == "PATCH":
                pass
            elif flask.request.method == "DELETE":
                graph_delete(uid)
        except KeyError:
            flask.Response('{"error": "Request missing arguments."}', 422,
                           mimetype="application/json")
    return flask.Response(status=204)


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

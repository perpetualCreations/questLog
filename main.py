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
        else:
            challenge_cache.pop(username)
    solution = urandom(int(config["auth"]["challenge_truth_length"])).hex()
    gpg = gnupg.GPG()
    gpg.import_keys(database["users"][username]["key"])
    challenge_cache.update({username: {
        "solution": solution,
        "challenge": gpg.encrypt(solution, ""),
        "expiry": time() + int(config["auth"]["challenge_expiry_time"])
        }})


def validate_challenge(username: str, solution: str) -> bool:
    """
    Check if solution to challenge is valid for given user.

    :return: True or False for whether or not the solution was correct
    :rtype: bool
    """
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
            if document.get(key) and isinstance(document.get(key),
                                                type(template[key])):
                return False
    return True


@application.route("/api/user/<username>",
                   methods=["PUT", "PATCH", "DELETE", "GET"])
def api_user_handle(username: str) -> flask.Response:
    """
    Respond to PUT/PATCH/DELETE/GET requests for user management API.

    If handle is given a PUT request, check if user already exists. If so, \
        return code 409. Otherwise, check if request is missing arguments. \
            If so, return code 422. If all checks pass, create user and \
                return code 201.

    If handle is given a PATCH request, check if user doesn't exist. If so \
        return code 404. Otherwise, check if request is missing arguments. \
            If so, return code 422. If all checks pass, apply changes defined \
                in request JSON arguments, and return code 200.

    If handle is given a DELETE request, check if user doesn't exist. If so \
        return code 404. Otherwise, delete user from database.

    If handle is given a GET request, check if user doesn't exist. If so \
        return code 404. Otherwise, return user data.

    If handle is given a request of any other method, returns code 405.

    :param username: name of user to be processed with request
    :type username: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    if not enforce_types(dict(flask.request.args), "json/user.json"):
        return flask.Response('{"error": "Invalid request argument types."}',
                              422, mimetype="application/json")
    user_data: Union[None, dict] = \
        database["users"].find_one({"username": username})
    if flask.request.method in ["PUT", "GET"]:
        if flask.request.method == "PUT":
            if user_data is None:
                if "key" in flask.request.args and "email" in \
                        flask.request.args:
                    database["users"].insert_one(
                        fill_template(flask.request.args, "json/user.json") +
                        {"username": username})
                    return flask.Response("", 201, mimetype="application/json")
                return flask.Response(
                    '{"error": "Request missing arguments."}', 422,
                    mimetype="application/json")
            return flask.Response('{"error": "Resource already exists."}', 409,
                                  mimetype="application/json")
        elif flask.request.method == "GET":
            if user_data is not None:
                return flask.Response(user_data, 200,
                                      mimetype="application/json")
            return flask.Response('{"error": "Resource does not exist."}', 404,
                                  mimetype="application/json")
    else:
        if "solution" not in flask.request.args:
            return flask.Response(
                '{"error": "Request missing arguments."}', 422,
                mimetype="application/json")
        if validate_challenge(
                username, flask.request.args["solution"]) is not True:
            return flask.Response('{"error": "Unauthorized."}', 401,
                                  mimetype="application/json")
        if flask.request.method == "PATCH":
            if user_data is not None:
                if "key" not in flask.request.args and "email" not in \
                        flask.request.args:
                    return flask.Response(
                        '{"error": "Request missing arguments."}', 422,
                        mimetype="application/json")

                database["users"].update_one(
                    {"username": username}, {key: value for key, value in \
                        fill_template(flask.request.args,
                                      "json/user.json").items() if value})
                return flask.Response("", 204, mimetype="application/json")
            return flask.Response('{"error": "Resource does not exist."}', 404,
                                mimetype="application/json")
        elif flask.request.method == "DELETE":
            if user_data is not None:
                database["users"].delete_one({"username": username})
                return flask.Response("", 204, mimetype="application/json")
            return flask.Response('{"error": "Resource does not exist."}', 404,
                                mimetype="application/json")
    return flask.Response('{"error": "Method not allowed."}', 405,
                          mimetype="application/json")


@application.route("/api/challenge/<username>", methods=["GET"])
def api_user_auth_challenge_handle(username: str) -> flask.Response:
    """
    Respond to GET requests for retrieving GPG auth challenges.

    If handle is given a GET request, check if user doesn't exist. If so \
        return code 404. Otherwise, collect challenge string and return \
            response.

    If handle is given a request of any other method, returns code 405.

    :param username: name of user to be processed with request
    :type username: str
    :return: response object with JSON data if applicable, and HTTP status code
    :rtype: flask.Response
    """
    if database["users"].find_one({"username": username}) is not None:
        fix_challenge(username)
        return flask.Response('{"challenge": ' + challenge_cache[username] +
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
    todo_data: Union[None, dict] = \
        database["todo"].find_one({"name": todo})
    if flask.request.method == "GET":
        if todo_data is not None:
            return flask.Response(todo_data, 200, mimetype="application/json")
        return flask.Response('{"error": "Resource does not exist."}', 404,
                                mimetype="application/json")
    else:
        if "author" not in flask.request.args or "solution" not in \
                flask.request.args:
            return flask.Response('{"error": "Request missing arguments."}',
                                  422, mimetype="application/json")
        if database["user"].find_one(
                {"username": flask.request.args["author"]}) is None:
            return flask.Response(
                '{"error": "Resource linkage to user does not exist."}', 422,
                mimetype="application/json")
        if validate_challenge(flask.request.args["author"],
                              flask.request.args["solution"]) is not True:
            return flask.Response('{"error": "Unauthorized."}', 401,
                                  mimetype="application/json")
        if flask.request.method == "PUT":
            if todo_data is None:
                for project in flask.request.args.get("projects", []).copy():
                    if database["project"].find_one(project) is None or \
                            (flask.request.args["author"] not in \
                            database["project"]["contributors"] and \
                            flask.request.args["author"] != \
                            database["project"]["author"]):
                        return flask.Response(
                            '{"error": "Resource linkage to project is not ' +
                            'authorized or does not exist."}', 422,
                            mimetype="application/json")
                database["todo"].insert_one(
                    fill_template(flask.request.args, "json/todo.json") +
                    {"name": todo})
                return flask.Response("", 201, mimetype="application/json")
            return flask.Response('{"error": "Resource already exists."}', 409,
                                  mimetype="application/json")
        if flask.request.method == "PATCH":
            if todo_data is not None:
                database["todo"].update_one(
                    {"name": todo}, {key: value for key, value in \
                        fill_template(flask.request.args,
                                      "json/todo.json").items() if value})
                return flask.Response("", 204, mimetype="application/json")
            return flask.Response('{"error": "Resource does not exist."}', 404,
                                mimetype="application/json")
        if flask.request.method == "DELETE":
            if todo_data is not None:
                database["todo"].delete_one({"name": todo})
                return flask.Response("", 204, mimetype="application/json")
            return flask.Response('{"error": "Resource does not exist."}', 404,
                                    mimetype="application/json")
    return flask.Response('{"error": "Method not allowed."}', 405,
                          mimetype="application/json")

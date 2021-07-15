"""
Main application module.

Contains responses to URIs.
"""

import configparser
from json import loads as json_loads
import flask
import pymongo
import gnupg


config = configparser.ConfigParser()
config.read("main.cfg")
application = flask.Flask(__name__)
database = pymongo.MongoClient(config["database"]["host"]).quest_log


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
        template[field] = arguments[field]
    return template


@application.route("/api/user/<username>", methods=["PUT", "DELETE", "GET"])
def api_user_handle(username):
    """Respond to PUT requests for user management API."""
    user_data = database["users"].find_one({"username": username})
    if flask.request.method == "PUT":
        if user_data is None:
            if "key" in flask.request.args and "email" in flask.request.args:
                database["users"].insert_one(
                    fill_template(flask.request.args, "json/user.json") +
                    {"username": username})
                return flask.Response("", 201, mimetype="application/json")
            else:
                return flask.Response(
                    "{'error': 'Request missing arguments.'}", 422,
                    mimetype="application/json")
        else:
            return flask.Response("{'error': 'Resource already exists.'}", 409,
                                  mimetype="application/json")
    elif flask.request.method == "DELETE":
        if user_data is not None:
            database["users"].delete_one({"username": username})
            return flask.Response("", 204, mimetype="application/json")
        else:
            return flask.Response("{'error': 'Resource does not exist.'}", 404,
                                  mimetype="application/json")
    elif flask.request.method == "GET":
        if user_data is not None:
            return flask.Response(user_data, 200, mimetype="application/json")
        else:
            return flask.Response("{'error': 'Resource does not exist.'}", 404,
                                  mimetype="application/json")
    else:
        return flask.abort(405)

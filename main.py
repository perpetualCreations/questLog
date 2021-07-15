"""
Main application module.

Contains responses to URIs.
"""

import configparser
from json import loads as json_loads
from ast import literal_eval
import flask
import redis


config = configparser.ConfigParser()
config.read("main.cfg")
application = flask.Flask(__name__)
PASSWORD = config["database"]["password"]
if config["database"]["password"].lower() == "none":
    PASSWORD = None
SSL_PARAMETERS = {}
if literal_eval(config["database"]["ssl"]) is True:
    SSL_PARAMETERS = {"ssl_keyfile": config["database"]["ssl_key_path"],
                      "ssl_certfile": config["database"]["ssl_cert_path"],
                      "ssl_cert_reqs": "required",
                      "ssl_ca_certs":
                          config["database"]["ssl_cert_authority_cert_path"]}
database = redis.Redis(config["database"]["hostname"],
                       int(config["database"]["port"]), 0,
                       PASSWORD, **SSL_PARAMETERS)
if database.get("initialized") is not True:
    with open("json/root.json") as template_handler:
        template = json_loads(template_handler.read())
    for key in template:
        database.set(key, template[key])


@application.route("/api/user/<username>", methods=["PUT", "POST", "GET"])
def api_get_handle(username):
    """Respond to PUT requests for user management API."""
    if flask.request.method == "PUT":
        if database.hget("lineages", username) is None:
            if "key" in flask.request.args:
                database.hset("lineages", username, {})
                with open("json/user.json") as template_handler:
                    template = json_loads(template_handler.read())
                for key in template:
                    database.hset("lineages:" + username, key, template[key])
            else:
                return flask.Response(
                    "{'error': 'Request missing arguments.'}", 422,
                    mimetype="application/json")
        else:
            return flask.Response("{'error': 'Resource already exists.'}", 409,
                                  mimetype="application/json")

"""
Main application module.

Contains responses to URIs.
"""

import configparser
import bottle
import redis
from json import loads as json_loads


config = configparser.ConfigParser()
config.read("main.cfg")
PASSWORD = config["database"]["password"]
if config["database"]["password"].lower() == "none":
    PASSWORD = None
database = redis.Redis(config["database"]["hostname"],
                       int(config["database"]["port"]), 0,
                       PASSWORD)
if database.get("initialized") is not True:
    pass


@bottle.hook("after_request")
def cors_enable():
    """Define headers to enable Cross-Origin resource sharing."""
    bottle.response.headers["Access-Control-Allow-Origin"] = "*"
    bottle.response.headers["Access-Control-Allow-Methods"] = \
        "PUT, GET, POST, DELETE, OPTIONS"
    bottle.response.headers["Access-Control-Allow-Headers"] = \
        "Authorization, Origin, Accept, Content-Type, X-Requested With"


@bottle.route("/api/", method="GET")
def api_get_handle():
    """Respond to GET requests for API."""

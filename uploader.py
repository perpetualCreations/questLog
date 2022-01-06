"""Script for uploading schema to target Dgraph server."""
import configparser
from string import Template
from ast import literal_eval
import requests

config = configparser.ConfigParser()
config.read("targets.cfg")

with open("schema.graphql") as schema_handler:
    schema = Template(schema_handler.read())

r = requests.post(literal_eval(config["target"]["host"]), schema.substitute(**{
    "uploader-VerificationKey": config["fill"]["key"],
    "uploader-Header": config["fill"]["header"]
}))

print("Sent POST request for configured schema.")
print("===BEGIN RESPONSE===")
print(r.status_code)
print(r.text)
print("===END OF RESPONSE===")

"""Script for uploading schema to target Dgraph server."""
import configparser
from ast import literal_eval
import requests

config = configparser.ConfigParser()
config.read("targets.cfg")

with open("schema.graphql") as schema_handler:
    schema = schema_handler.read()
    schema = schema.replace("$uploader-VerificationKey", config["fill"]["key"])
    schema = schema.replace("$uploader-Header", config["fill"]["header"])
    schema = schema.replace("$uploader-Namespace", config["fill"]["namespace"])

r = requests.post(literal_eval(config["target"]["host"]), schema)

print("Sent POST request for configured schema.")
print("===BEGIN RESPONSE===")
print(r.status_code)
print(r.text)
print("===END OF RESPONSE===")

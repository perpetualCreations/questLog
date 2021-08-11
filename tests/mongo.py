import pymongo
client: pymongo.MongoClient = pymongo.MongoClient(
    "192.168.1.23", 27017)
print(client.list_database_names())

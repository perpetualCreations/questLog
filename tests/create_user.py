import requests

with open("./Alice_0x99F92780_public.asc") as key_handle:
    key = key_handle.read()

requests.request("PUT", "http://localhost/api/user/alice", data={
    "email": "alice@example.com",
    "key": key
})

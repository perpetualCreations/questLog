import requests

with open("public.pem", "rb") as key_read:
    r = requests.put("http://localhost/api/user/alice", json={
        "email": "alice@example.com",
        "key": key_read.read().decode("utf-8")
    })
    print(r.text)

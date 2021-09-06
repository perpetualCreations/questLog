import requests

a = requests.get("http://localhost/api/challenge/alice")
r = requests.delete("http://localhost/api/user/alice", json={"solution": ""})
print(r.text)

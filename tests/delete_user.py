import requests

r = requests.delete("http://localhost/api/user/alice", json={"solution": ""})
print(r.text)

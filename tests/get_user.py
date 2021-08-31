import requests

r = requests.get("http://localhost/api/user/alice")
print(r.text)

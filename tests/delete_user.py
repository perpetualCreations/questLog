from json import loads
import requests
from Cryptodome.PublicKey import RSA
from Cryptodome.Cipher import AES, PKCS1_OAEP

challenge = loads(requests.get("http://localhost/api/challenge/alice").text)

with open("private.pem", "rb") as private_import:
    cipher_rsa = PKCS1_OAEP.new(RSA.import_key(private_import.read()))

session_key = cipher_rsa.decrypt(bytes.fromhex(challenge["session"]))
solution = AES.new(session_key, AES.MODE_EAX, bytes.fromhex(  # type: ignore
    challenge["nonce"])).decrypt_and_verify(bytes.fromhex(challenge[
        "challenge"]), bytes.fromhex(challenge["tag"])).decode("utf-8")

r = requests.delete("http://localhost/api/user/alice",
                    json={"solution": solution})
print(r.text)

from os import urandom
from Cryptodome.PublicKey import RSA
from Cryptodome.Cipher import AES, PKCS1_OAEP

key = RSA.generate(2048)
private_key = key.export_key()
public_key = key.publickey().export_key()
print(private_key)
print(public_key)

data = urandom(2048).hex()

recipient_key = RSA.import_key(public_key)
session_key = urandom(16)
enc_session_key = PKCS1_OAEP.new(recipient_key).encrypt(session_key)

cipher_aes = AES.new(session_key, AES.MODE_EAX)
ciphertext, tag = cipher_aes.encrypt_and_digest(data.encode("ascii"))

encrypted = [x.hex() for x in (enc_session_key, cipher_aes.nonce, tag,
                               ciphertext)]

print(encrypted)

cipher_rsa = PKCS1_OAEP.new(key)
session_key = cipher_rsa.decrypt(bytes.fromhex(encrypted[0]))

print(AES.new(session_key, AES.MODE_EAX, bytes.fromhex(encrypted[1])).
      decrypt_and_verify(bytes.fromhex(encrypted[3]), bytes.fromhex(encrypted[
          2])).decode("utf-8") == data)

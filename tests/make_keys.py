from Cryptodome.PublicKey import RSA

key = RSA.generate(2048)
with open("private.pem", "wb") as private_export:
    private_export.write(key.export_key())
with open("public.pem", "wb") as public_export:
    public_export.write(key.publickey().export_key())

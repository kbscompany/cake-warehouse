import hashlib

password = "Kbcost@2024"
hashed_password = hashlib.sha256(password.encode()).hexdigest()
print(hashed_password)

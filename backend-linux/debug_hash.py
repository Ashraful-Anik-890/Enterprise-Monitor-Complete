from passlib.context import CryptContext
import logging

logging.basicConfig(level=logging.INFO)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
hash_str = "$2b$12$xhtRRHb0Fio2O2VrjnWaZeF.nnFxewCPDfNWXrvjsfsw0erSxTBpO"
password = "admin123"

print(f"Testing verify with:")
print(f"Password: '{password}' (len={len(password)})")
print(f"Hash: '{hash_str}' (len={len(hash_str)})")

try:
    result = pwd_context.verify(password, hash_str)
    print(f"Verify result: {result}")
except Exception as e:
    print(f"Verify error: {e}")

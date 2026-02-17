from passlib.context import CryptContext
import logging

logging.basicConfig(level=logging.INFO)

# Test with pbkdf2_sha256
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
password = "admin123"

# Generate hash
hash_str = pwd_context.hash(password)
print(f"Generated hash: '{hash_str}'")

try:
    result = pwd_context.verify(password, hash_str)
    print(f"Verify result: {result}")
except Exception as e:
    print(f"Verify error: {e}")

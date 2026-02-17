"""
Authentication Manager
Handles user authentication and JWT token generation/verification

CHANGES (Bug Fix):
- verify_token() now returns None on ANY token failure (expired, invalid, malformed).
  It no longer raises ValueError. This prevents 500 errors — callers check for None.
- ExpiredSignatureError is caught explicitly before the generic JWTError catch,
  because in some python-jose versions it is a standalone exception.
"""

from datetime import datetime, timedelta
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

import logging
from pathlib import Path
import json
import re

logger = logging.getLogger(__name__)

SECRET_KEY = "your-secret-key-change-this-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


class AuthManager:
    def __init__(self):
        self.users_file = Path.home() / "AppData" / "Local" / "EnterpriseMonitor" / "users.json"
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_users()

    def _initialize_users(self):
        if not self.users_file.exists():
            default_users = {"admin": "Admin@123"}
            with open(self.users_file, 'w') as f:
                json.dump(default_users, f)
            logger.info("Initialized default admin user")

    def _load_users(self):
        try:
            with open(self.users_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load users: {e}")
            return {}

    def verify_credentials(self, username: str, password: str) -> bool:
        """Verify username and password. Returns True if valid."""
        users = self._load_users()
        if username not in users:
            return False
        return password == users[username]

    def create_token(self, username: str) -> str:
        """Create a signed JWT access token."""
        expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {"sub": username, "exp": expires}
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    def verify_token(self, token: str) -> dict | None:
        """
        Verify a JWT token and return its payload dict.

        Returns None (never raises) on:
          - Expired token  (ExpiredSignatureError)
          - Invalid token  (JWTError)
          - Any other error

        Callers must check: `if payload is None → 401`
        """
        try:
            return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except ExpiredSignatureError:
            # Token is structurally valid but past its exp claim.
            # Treat as unauthenticated — do NOT crash the server.
            logger.warning("Token has expired — returning None")
            return None
        except JWTError as e:
            logger.warning(f"Token verification failed: {e}")
            return None
        except Exception as e:
            # Catch-all: malformed token, wrong secret, encoding issues
            logger.error(f"Unexpected token error: {e}")
            return None

    def validate_password(self, password: str) -> tuple[bool, str]:
        """Validate password against strength policy."""
        if len(password) < 8 or len(password) > 16:
            return False, "Password must be between 8 and 16 characters"
        if not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter"
        if not re.search(r"[a-z]", password):
            return False, "Password must contain at least one lowercase letter"
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return False, "Password must contain at least one symbol"
        return True, ""

    def change_password(self, username: str, new_password: str):
        """Change password after validating strength."""
        valid, error = self.validate_password(new_password)
        if not valid:
            raise ValueError(error)
        users = self._load_users()
        users[username] = new_password
        with open(self.users_file, 'w') as f:
            json.dump(users, f)
        logger.info(f"Password changed for user: {username}")
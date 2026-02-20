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
        self.security_qa_file = self.users_file.parent / "security_qa.json"
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
    
    def update_credentials(self, old_username: str, new_username: str, new_password: str) -> tuple[bool, str]:
        """
        Change both username and password atomically.

        After success the caller MUST invalidate the current JWT (force re-login)
        because the token sub claim still holds old_username.

        Returns (True, "") on success, (False, error_message) on failure.
        """
        users = self._load_users()

        if old_username not in users:
            return False, "Current username not found"

        # Validate new password strength
        valid, err = self.validate_password(new_password)
        if not valid:
            return False, err

        # Validate new username
        new_username = new_username.strip()
        if not new_username or len(new_username) < 3:
            return False, "Username must be at least 3 characters"
        if not re.match(r'^[a-zA-Z0-9_.\-]+$', new_username):
            return False, "Username may only contain letters, numbers, _ . -"

        # If renaming, ensure new name is not already taken
        if new_username != old_username and new_username in users:
            return False, "Username already exists"

        # Apply: remove old key, insert new
        del users[old_username]
        users[new_username] = new_password

        try:
            with open(self.users_file, 'w') as f:
                json.dump(users, f, indent=2)
            logger.info("Credentials updated: %s → %s", old_username, new_username)

            # Migrate security QA to new username key
            self._migrate_qa_key(old_username, new_username)
            return True, ""
        except Exception as e:
            logger.error("Failed to update credentials: %s", e)
            return False, "Storage error — credentials not changed"

    SECURITY_QUESTIONS = [
        "What was the name of your first pet?",
        "What is your mother's maiden name?",
        "What city were you born in?",
        "What was the name of your primary school?",
        "What is the name of the street you grew up on?",
    ]

    def _load_security_qa(self) -> dict:
        try:
            if self.security_qa_file.exists():
                with open(self.security_qa_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error("Failed to load security QA: %s", e)
        return {}

    def save_security_qa(self, username: str, q1: str, a1: str, q2: str, a2: str):
        """Persist two security Q&A pairs for a user."""
        qa = self._load_security_qa()
        qa[username] = [
            {"question": q1, "answer": a1.strip().lower()},
            {"question": q2, "answer": a2.strip().lower()},
        ]
        try:
            with open(self.security_qa_file, 'w') as f:
                json.dump(qa, f, indent=2)
            logger.info("Security QA saved for user: %s", username)
        except Exception as e:
            logger.error("Failed to save security QA: %s", e)
            raise

    def get_security_questions(self, username: str) -> list[dict]:
        """Return saved Q&A pairs for a user (answers are hidden)."""
        qa = self._load_security_qa()
        pairs = qa.get(username, [])
        return [{"question": p["question"]} for p in pairs]

    def verify_security_answer(self, username: str, question_index: int, answer: str) -> bool:
        """Verify a security answer (case-insensitive, stripped)."""
        qa = self._load_security_qa()
        pairs = qa.get(username, [])
        if question_index >= len(pairs):
            return False
        return pairs[question_index]["answer"] == answer.strip().lower()

    def _migrate_qa_key(self, old_username: str, new_username: str):
        """Move QA data to new username key after a rename."""
        if old_username == new_username:
            return
        qa = self._load_security_qa()
        if old_username in qa:
            qa[new_username] = qa.pop(old_username)
            try:
                with open(self.security_qa_file, 'w') as f:
                    json.dump(qa, f, indent=2)
            except Exception as e:
                logger.error("Failed to migrate QA key: %s", e)


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
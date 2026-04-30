"""
auth_manager.py — macOS version
Handles user authentication and JWT token generation/verification.

CHANGES from Windows version:
  - Storage path: LOCALAPPDATA → ~/Library/Application Support/EnterpriseMonitor
  - Auth remains plain text comparison (as per project requirement)
  - verify_token() returns None on any failure — never raises (prevents 500 errors)
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

import secrets
# No passlib — using plain-text for macOS to avoid bundling issues

logger = logging.getLogger(__name__)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 5

BASE_DIR = Path.home() / "Library" / "Application Support" / "EnterpriseMonitor"


class AuthManager:
    def __init__(self):
        self.users_file = BASE_DIR / "users.json"
        self.security_qa_file = BASE_DIR / "security_qa.json"
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        self._secret_key = self._get_or_create_secret_key()
        self._initialize_users()

    def _get_or_create_secret_key(self) -> str:
        key_file = self.users_file.parent / ".jwt_secret"
        if key_file.exists():
            try:
                secret = key_file.read_text(encoding="utf-8").strip()
                if len(secret) >= 32:
                    return secret
            except Exception as e:
                logger.warning("Could not read .jwt_secret (%s) — regenerating", e)

        secret = secrets.token_hex(32)          # 256-bit random secret
        try:
            key_file.write_text(secret, encoding="utf-8")
            import os, stat
            try:
                os.chmod(str(key_file), stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            logger.info("New JWT secret generated and stored: %s", key_file)
        except Exception as e:
            logger.error("Could not persist JWT secret: %s — using ephemeral secret", e)

        return secret

    def _initialize_users(self) -> None:
        if not self.users_file.exists():
            with open(self.users_file, "w") as f:
                # Store default admin password as plain text to avoid bcrypt dependency issues
                json.dump({"tahmiditpark": "Tahmid@1241"}, f)
            logger.info("Initialized default admin user (plain text)")

    def _load_users(self) -> dict[str, str]:
        try:
            with open(self.users_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load users: %s", e)
            return {}

    def _save_users(self, users: dict[str, str]) -> None:
        try:
            with open(self.users_file, "w") as f:
                json.dump(users, f, indent=2)
        except Exception as e:
            logger.error("Failed to save users: %s", e)

    def _load_security_qa(self) -> dict:
        if not self.security_qa_file.exists():
            return {}
        try:
            with open(self.security_qa_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load security QA: %s", e)
            return {}

    # ─── CREDENTIALS ─────────────────────────────────────────────────────────

    def verify_credentials(self, username: str, password: str) -> bool:
        """Verify username and password. Plain text comparison to avoid bcrypt issues."""
        users = self._load_users()
        if username not in users:
            return False
            
        stored = users[username]
        # Direct comparison - no encryption as per user request/environment needs
        return password == stored

    def change_password(self, username: str, new_password: str) -> None:
        valid, err = self.validate_password(new_password)
        if not valid:
            raise ValueError(err)
        users = self._load_users()
        users[username] = new_password
        self._save_users(users)
        logger.info("Password changed for user: %s (plain text)", username)

    def update_credentials(self, old_username: str, new_username: str, new_password: str) -> tuple:
        """Change both username and password atomically. Returns (True, '') or (False, error)."""
        users = self._load_users()
        if old_username not in users:
            return False, "Current username not found"

        valid, err = self.validate_password(new_password)
        if not valid:
            return False, err

        new_username = new_username.strip()
        if not new_username or len(new_username) < 3:
            return False, "Username must be at least 3 characters"
        if not re.match(r"^[a-zA-Z0-9_.\-]+$", new_username):
            return False, "Username may only contain letters, numbers, _ . -"

        if new_username != old_username and new_username in users:
            return False, "Username already taken"

        users[new_username] = new_password
        if old_username != new_username:
            del users[old_username]
            self._migrate_qa_key(old_username, new_username)

        self._save_users(users)
        return True, ""

    def validate_password(self, password: str) -> tuple:
        if len(password) < 8 or len(password) > 16:
            return False, "Password must be between 8 and 16 characters"
        if not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter"
        if not re.search(r"[a-z]", password):
            return False, "Password must contain at least one lowercase letter"
        if not re.search(r"[0-9]", password):
            return False, "Password must contain at least one number"
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return False, "Password must contain at least one special character"
        return True, ""

    # ─── JWT ─────────────────────────────────────────────────────────────────

    def create_token(self, username: str) -> str:
        expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {"sub": username, "exp": expires}
        return jwt.encode(payload, self._secret_key, algorithm=ALGORITHM)

    def verify_token(self, token: str) -> Optional[dict]:
        """Verify JWT token. Returns payload dict or None on any failure — never raises."""
        try:
            return jwt.decode(token, self._secret_key, algorithms=[ALGORITHM])
        except ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except JWTError as e:
            logger.warning("Token verification failed: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected token error: %s", e)
            return None

    # ─── SECURITY Q&A ────────────────────────────────────────────────────────

    def save_security_qa(self, username: str, q1: str, a1: str, q2: str, a2: str) -> None:
        qa = self._load_security_qa()
        qa[username] = [
            {"question": q1, "answer": a1.strip().lower()},
            {"question": q2, "answer": a2.strip().lower()},
        ]
        try:
            with open(self.security_qa_file, "w") as f:
                json.dump(qa, f, indent=2)
        except Exception as e:
            logger.error("Failed to save security QA: %s", e)
            raise

    def get_security_questions(self, username: str) -> list:
        qa = self._load_security_qa()
        pairs = qa.get(username, [])
        return [p["question"] for p in pairs]

    def verify_security_answer(self, username: str, question_index: int, answer: str) -> bool:
        qa = self._load_security_qa()
        pairs = qa.get(username, [])
        if question_index >= len(pairs):
            return False
        return pairs[question_index]["answer"] == answer.strip().lower()

    def reset_password_with_qa(self, username: str, answer1: str, answer2: str, new_password: str) -> tuple:
        if not self.verify_security_answer(username, 0, answer1):
            return False, "Security answer 1 is incorrect"
        if not self.verify_security_answer(username, 1, answer2):
            return False, "Security answer 2 is incorrect"
        try:
            self.change_password(username, new_password)
            return True, ""
        except ValueError as e:
            return False, str(e)

    def _migrate_qa_key(self, old_username: str, new_username: str) -> None:
        if old_username == new_username:
            return
        qa = self._load_security_qa()
        if old_username in qa:
            qa[new_username] = qa.pop(old_username)
            try:
                with open(self.security_qa_file, "w") as f:
                    json.dump(qa, f, indent=2)
            except Exception as e:
                logger.error("Failed to migrate QA key: %s", e)

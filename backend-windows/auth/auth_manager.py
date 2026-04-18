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
import secrets
from passlib.context import CryptContext

_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 5



class AuthManager:
    def __init__(self):
        self.users_file = Path.home() / "AppData" / "Local" / "EnterpriseMonitor" / "users.json"
        self.security_qa_file = self.users_file.parent / "security_qa.json"
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        self._secret_key = self._get_or_create_secret_key()
        self._initialize_users()

    def _get_or_create_secret_key(self) -> str:
        """
        BUG-02 FIX: Per-installation JWT signing secret.

        Generates a cryptographically random 64-hex-character secret on first run
        and persists it to .jwt_secret in the data directory.  Subsequent runs
        read the same value, so existing tokens remain valid across restarts.

        This means every installation has a unique secret — a token forged on one
        machine is NOT valid on any other machine.
        """
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
            # Restrict permissions on POSIX (macOS/Linux)
            import os, stat
            try:
                os.chmod(str(key_file), stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass                            # Windows — skip chmod
            logger.info("New JWT secret generated and stored: %s", key_file)
        except Exception as e:
            logger.error("Could not persist JWT secret: %s — using ephemeral secret", e)

        return secret

    def _initialize_users(self):
        """
        BUG-01 FIX: Default password is now stored as a bcrypt hash.
        """
        if not self.users_file.exists():
            default_users = {
                "admin": _pwd_context.hash("Admin@123")   # CHANGED — was "Admin@123"
            }
            with open(self.users_file, "w") as f:
                json.dump(default_users, f)
            logger.info("Initialised default admin user (bcrypt hashed)")

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
        users[new_username] = _pwd_context.hash(new_password)

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
        """
        BUG-01 FIX: Verify using bcrypt.  Migrates plain-text legacy entries on
        first successful login so existing deployments upgrade transparently.
        """
        users = self._load_users()
        if username not in users:
            return False

        stored = users[username]

        # ── Detect legacy plain-text entry ───────────────────────────────────────
        # bcrypt hashes always start with "$2b$" or "$2a$".
        # A plain-text password (e.g. "Admin@123") never starts with "$2".
        if not stored.startswith("$2"):
            # Legacy plain-text comparison
            if password != stored:
                return False
            # ── Migrate to bcrypt on first valid login ────────────────────────
            users[username] = _pwd_context.hash(password)
            try:
                with open(self.users_file, "w") as f:
                    json.dump(users, f, indent=2)
                logger.info("Migrated plain-text password to bcrypt for user: %s", username)
            except Exception as e:
                logger.error("Failed to migrate password for %s: %s", username, e)
            return True

        # ── Standard bcrypt verification ─────────────────────────────────────────
        return _pwd_context.verify(password, stored)

    def create_token(self, username: str) -> str:
        """Create a signed JWT access token."""
        expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {"sub": username, "exp": expires}
        return jwt.encode(payload, self._secret_key, algorithm=ALGORITHM)

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
            return jwt.decode(token, self._secret_key, algorithms=[ALGORITHM])
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
        """Change password — always stores as bcrypt hash."""
        valid, error = self.validate_password(new_password)
        if not valid:
            raise ValueError(error)
        users = self._load_users()
        users[username] = _pwd_context.hash(new_password)   # CHANGED — was plain text
        with open(self.users_file, "w") as f:
            json.dump(users, f, indent=2)
        logger.info("Password changed (bcrypt) for user: %s", username)
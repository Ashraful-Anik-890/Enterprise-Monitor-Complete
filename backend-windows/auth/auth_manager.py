"""
Authentication Manager
Handles user authentication and JWT token generation/verification
"""

from datetime import datetime, timedelta
from jose import JWTError, jwt

import logging
from pathlib import Path
import json
import re

logger = logging.getLogger(__name__)

# Secret key for JWT (In production, use environment variable)
SECRET_KEY = "your-secret-key-change-this-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

class AuthManager:
    def __init__(self):
        # WARNING: Using plain text passwords as requested by user
        self.users_file = Path.home() / "AppData" / "Local" / "EnterpriseMonitor" / "users.json"
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_users()
    
    def _initialize_users(self):
        """Initialize default admin user if no users exist"""
        if not self.users_file.exists():
            # Default admin credentials (CHANGE IN PRODUCTION!)
            # Using 'Admin@123' to comply with new strict password policy
            default_users = {
                "admin": "Admin@123"
            }
            with open(self.users_file, 'w') as f:
                json.dump(default_users, f)
            logger.info("Initialized default admin user")
    
    def _load_users(self):
        """Load users from file"""
        try:
            with open(self.users_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load users: {e}")
            return {}
    
    def verify_credentials(self, username: str, password: str) -> bool:
        """Verify username and password"""
        users = self._load_users()
        
        if username not in users:
            return False
        
        # Plain text comparison
        return password == users[username]
    
    def create_token(self, username: str) -> str:
        """Create JWT access token"""
        expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode = {
            "sub": username,
            "exp": expires
        }
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    def verify_token(self, token: str) -> dict:
        """Verify JWT token and return payload"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError as e:
            logger.error(f"Token verification failed: {e}")
            raise ValueError("Invalid token")
    
    def validate_password(self, password: str) -> tuple[bool, str]:
        """
        Validate password strength
        Criteria:
        - 8-16 characters
        - At least 1 uppercase letter
        - At least 1 lowercase letter
        - At least 1 symbol
        """
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
        """Change user password"""
        # Validate password first
        valid, error = self.validate_password(new_password)
        if not valid:
            raise ValueError(error)

        users = self._load_users()
        users[username] = new_password
        
        with open(self.users_file, 'w') as f:
            json.dump(users, f)
        
        logger.info(f"Password changed for user: {username}")

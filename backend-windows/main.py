"""
Enterprise Monitor - Windows Backend Service
Main entry point for the monitoring service
"""

import uvicorn
import logging
from pathlib import Path
import getpass

# Setup logging
log_dir = Path.home() / "AppData" / "Local" / "EnterpriseMonitor" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "backend.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Start the backend API server"""
    logger.info("Starting Enterprise Monitor Backend Service...")
    
    try:
        # Import here to ensure logging is configured first
        from api_server import app
        
        # Start uvicorn server
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=51235,
            log_level="info",
            access_log=True
        )
    except Exception as e:
        logger.error(f"Failed to start backend service: {e}")
        raise

if __name__ == "__main__":
    main()

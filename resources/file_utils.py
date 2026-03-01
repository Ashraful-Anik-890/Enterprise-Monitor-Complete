import os
import platform
import plistlib
from pathlib import Path


MYAPP_FOLDER = "DesktopTrackerApp"

DATABASE_NAME = 'local.db'
SCREENSHOT_FOLDER = "extras"
LOGS_FOLDER = "logs"
LOGS_FILE = "log.txt"
APP_PREFS_PATH = "~/Library/Preferences/com.desktop.trk.app.plist"  # register user token, cloudinary tokens
APP_STORAGE_PATH = '~/Library/Application Support'


def setup_storage_path():
    appdata_path = None
    myapp_appdata_path = None
    # Get the AppData path
    if platform.system() == 'Darwin':  # macOS
        appdata_path = os.path.expanduser('~/Library/Application Support')
    elif platform.system() == 'Windows':
        appdata_path = os.getenv('APPDATA')
    if appdata_path:
        myapp_appdata_path = os.path.join(appdata_path, MYAPP_FOLDER)

    # Create the directory (including any intermediate directories)
    try:
        os.makedirs(myapp_appdata_path, exist_ok=True)  # exist_ok=True prevents error if it already exists
        #print(f"Directory created: {myapp_appdata_path}")
    except Exception as e:
        print(f"Failed to create directory: {e}")
    return myapp_appdata_path

def setup_preference_file():
    expanded_path = Path(os.path.expanduser(APP_PREFS_PATH))

    if not expanded_path.exists():
        # Create parent directories if they don't exist
        expanded_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the new PLIST file
        with expanded_path.open('wb') as f:
            plistlib.dump({}, f)
        print(f"Created new PLIST file")
    else:
        print(f"PLIST file already exists")

    return expanded_path


def get_database_path():
    return os.path.join(setup_storage_path(), DATABASE_NAME)

def get_screenshot_path():

    appdata_path = os.path.expanduser(APP_STORAGE_PATH)
    myapp_appdata_path = os.path.join(appdata_path, MYAPP_FOLDER, SCREENSHOT_FOLDER)

    try:
        os.makedirs(myapp_appdata_path, exist_ok=True)  # exist_ok=True prevents error if it already exists
        #print(f"Directory created: {myapp_appdata_path}")
    except Exception as e:
        print(f"Failed to create directory: {e}")

    return myapp_appdata_path

def get_app_prefs_path():
    return setup_preference_file()

def get_log_file_path():
    appdata_path = os.path.expanduser(APP_STORAGE_PATH)
    myapp_appdata_path = os.path.join(appdata_path, MYAPP_FOLDER, LOGS_FOLDER)

    try:
        os.makedirs(myapp_appdata_path, exist_ok=True)  # exist_ok=True prevents error if it already exists
        #print(f"Directory created: {myapp_appdata_path}")
    except Exception as e:
        print(f"Failed to create directory: {e}")

    return os.path.join(myapp_appdata_path, LOGS_FILE)

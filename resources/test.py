import os
import subprocess
import sys
from dataclasses import fields
from pprint import pprint
import time
import platform
from time import sleep

import json

# from utils import user_info
import plistlib
from pathlib import Path

import gevent
import psutil
import pyperclip

from imessage.fetch_data import FetchIMessageData
from mydb.models import OpenedAppsListModel, IMessageModel, GoogleMessageModel
from mydb.utils import create_tables
from utils import current_user, get_user_token, register_user_token, check_user_token, check_cloudinary_token, \
    get_cloudinary_tokens, check_internet_connection

MYAPP_FOLDER = "DesktopTrackerApp"
SCREENSHOT_FOLDER = "Screenshots"

app_prefs_path = "~/Library/Preferences/com.desktop.trk.app.plist"


def check_preference_file():
    expanded_path = Path(os.path.expanduser(app_prefs_path))
    if not expanded_path.exists():
        # Create parent directories if they don't exist
        expanded_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the new PLIST file
        with expanded_path.open('wb') as f:
            plistlib.dump({}, f)
        print(f"Created new PLIST file at {expanded_path}")
    else:
        print(f"PLIST file already exists at {expanded_path}")

    return expanded_path


def read_plist(plist_path):
    plist_path = Path(os.path.expanduser(plist_path))
    try:
        with open(plist_path, 'rb') as f:
            return plistlib.load(f)
    except Exception as e:
        print(f"Error reading plist: {e}")
        return None


def update_plist(plist_path, new_data, merge_strategy='overwrite'):
    """
    Update a PLIST file with new data without overwriting existing keys

    Args:
        plist_path (str): Path to PLIST file
        new_data (dict): New data to add
        merge_strategy (str):
            'safe' - only add new keys (default)
            'overwrite' - overwrite existing keys
            'deep' - recursive merge for nested dictionaries

    Returns:
        bool: True if update was successful
    """
    plist_path = Path(os.path.expanduser(plist_path))

    try:
        # Read existing data or create empty dict if file doesn't exist
        existing_data = {}
        if plist_path.exists():
            with plist_path.open('rb') as f:
                existing_data = plistlib.load(f)

        # Merge data based on selected strategy
        if merge_strategy == 'safe':
            merged_data = {**new_data, **existing_data}  # New keys take precedence
        elif merge_strategy == 'overwrite':
            merged_data = {**existing_data, **new_data}  # Existing keys take precedence
        elif merge_strategy == 'deep':
            merged_data = deep_merge(existing_data, new_data)
        else:
            raise ValueError(f"Unknown merge strategy: {merge_strategy}")

        # Write back the merged data
        with plist_path.open('wb') as f:
            plistlib.dump(merged_data, f)

        return True

    except Exception as e:
        print(f"Error updating PLIST file: {e}")
        return False


def deep_merge(base_dict, new_dict):
    """Recursively merge dictionaries"""
    result = base_dict.copy()
    for key, value in new_dict.items():
        if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(base_dict[key], value)
        else:
            result[key] = value
    return result


def monitor_directory(path='dist_x86', interval=1):
    """Monitor directory size and contents"""
    try:
        while True:
            # Clear screen (works cross-platform)
            subprocess.run('clear' if sys.platform != 'win32' else 'cls', shell=True)

            # Get and print directory size
            du_total = subprocess.run(
                ['du', '-sh', path],
                capture_output=True,
                text=True
            )
            print(du_total.stdout, end='')

            # Get and print contents sorted by size
            du_contents = subprocess.run(
                ['du', '-sh', f'{path}/*'],
                capture_output=True,
                text=True
            )
            if du_contents.stdout:
                sorted_contents = subprocess.run(
                    ['sort', '-h'],
                    input=du_contents.stdout,
                    capture_output=True,
                    text=True
                )
                print(sorted_contents.stdout)

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped")
def main():
    print("Hello World")

    # pp = pprint.PrettyPrinter(indent=2)
    # pp.pprint(prefs)
    app_list = []
    monitor_directory()
    # while True:
    #     os.system('clear')
    #     os.system('du -sh dist_x86 && du -sh dist_x86/* | sort -h')
    #     time.sleep(1)




if __name__ == "__main__":
    main()

# import gevent
# from gevent.lock import BoundedSemaphore
#
#
# class WorkerTask:
#     def __init__(self, name):
#         self.name = name
#         self.running = True
#         self.lock = BoundedSemaphore(1)  # Protects condition checks
#
#     def run(self):
#         while self.running:
#             try:
#                 with self.lock:  # Auto-releases when block exits
#                     if self.check_condition():
#                         self.handle_condition()
#             except Exception as e:
#                 print(f"{self.name} error: {e}")
#             gevent.sleep(2)  # Polling interval
#
#     def check_condition(self):
#         """Override this with your actual condition check"""
#         return False  # Replace with real condition
#
#     def handle_condition(self):
#         """Override this with your condition handling"""
#         print(f"{self.name} handling condition")
#
#         # Example: Spawn a new independent task
#         new_task = WorkerTask(f"Worker-{gevent.getcurrent()}")
#         gevent.spawn(new_task.run)  # Fire-and-forget
#
#         # No need to track or join this new task
#         # It will run independently until self.running=False
#
#     def stop(self):
#         self.running = False
#
#
# class MainApp:
#     def __init__(self):
#         self.main_task = WorkerTask("MainWorker")
#
#     def run(self):
#         main_greenlet = gevent.spawn(self.main_task.run)
#
#         try:
#             # Main loop can do other work here
#             while True:
#                 gevent.sleep(1)
#         except KeyboardInterrupt:
#             print("Shutting down...")
#             self.main_task.stop()
#             main_greenlet.join(timeout=2)
#
#
# if __name__ == "__main__":
#     app = MainApp()
#     app.run()

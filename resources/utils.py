import json
import getpass
import platform
import plistlib

from uuid import uuid4

import requests
import urllib3

urllib3.disable_warnings()

from file_utils import get_app_prefs_path
from imessage.fetch_data import FetchIMessageData
from my_logger import mylogger
from mydb.models import UserModel, ParamModel, IMessageModel

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pprint import pprint



APP_PREFS_FULL_PATH = get_app_prefs_path()

logger = mylogger(__name__)



session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))



def user_info():
    return {
        'username': getpass.getuser(),
        'system': platform.system(),
        'nodename': platform.node(),
        'version': platform.version(),
        'nickname': 'apple',
    }


def current_user():
    user, created = UserModel.get_or_create(
        username=getpass.getuser(),
        system=platform.system(),
        version=platform.version(),
        nodename=platform.node(),

    )
    if created:
        user.nickname = uuid4().hex
        user.save()

    # print("user created: {}".format(user.username)) if created else print("user exists: {}".format(user.username))
    logger.info("user created: {}".format(user.username)) if created else print("user exists: {}".format(user.username))
    return user


def get_user_token():
    if prefs_data := read_plist():
        return prefs_data.get('utoken', None)
    return None


def register_user_token():
    # print("Registering user token....")
    logger.info("Registering user token....")
    utoken = None

    user = current_user()
    user_data = user.__data__.copy()
    user_data['userName'] = user.username
    user_data.pop('id')
    user_data.pop('username')
    json_data = json.dumps(user_data, indent=4)


    try:
        response = requests.post(url="https://backend.skillersbpo.com/api/createPcUser", data=json_data, timeout=5,
                                 headers={"Content-Type": "application/json"})
        response.raise_for_status()
        if response.status_code == 200:
            json_data = response.json()
            utoken = json_data.get("token", None)
            u_nickname = json_data.get("nickname", None)
            if utoken:
                update_plist({"utoken": utoken})

            if u_nickname:
                user = current_user()
                user.nickname = u_nickname
                user.save()

    except Exception as e:
        # print("Error:", e)
        logger.error("Error:", e)
    return utoken


def check_user_token():
    """
    get user token from prefs.\n
    if not found register user token if internet connection available

    Returns:
        str: user token
    """
    utoken = get_user_token()
    if utoken is None and check_internet_connection():
        utoken = register_user_token()

    return utoken


def check_cloudinary_token():
    utoken = check_user_token()
    if utoken and check_internet_connection():
        data = {
            'param_names': ["cld_nm", "cld_ky", "cld_sk"],
            'token': utoken,
        }
        json_data = json.dumps(data, indent=4)

        try:
            response = requests.post(url="https://backend.skillersbpo.com/api/params", data=json_data, timeout=5,
                                     headers={"Content-Type": "application/json"})
            response.raise_for_status()
            if response.status_code == 200:
                json_data = response.json()
                param_list = json_data.get("data", None)
                param_dict = {item['param_name']: item['param_value'] for item in param_list}

                cloudinary_cloud_name = param_dict.get("cld_nm", None)
                cloudinary_api_key = param_dict.get("cld_ky", None)
                cloudinary_api_secret = param_dict.get("cld_sk", None)

                if cloudinary_cloud_name and cloudinary_api_key and cloudinary_api_secret:
                    new_data = {
                        'cld_nm': cloudinary_cloud_name,
                        'cld_ky': cloudinary_api_key,
                        'cld_sk': cloudinary_api_secret,
                    }
                    update_plist(new_data)

        except Exception as e:
            # print("Error:", e)
            logger.error("Error:", e)


def get_cloudinary_tokens():
    if prefs_data := read_plist():
        return {
            'cloudinary_cloud_name': prefs_data.get('cld_nm', None),
            'cloudinary_api_key': prefs_data.get('cld_ky', None),
            'cloudinary_api_secret': prefs_data.get('cld_sk', None)
        }
    return None


def check_internet_connection():
    try:
        # response = session.get("https://api.github.com", timeout=10,verify=False)
        response = session.get("https://api.github.com", timeout=10)
        return True
    except Exception as e:
        logger.error(f"Internet Connection is failed to reach after retries: {e}")
        return False




def check_imessage_update():
    lastIMessasge = IMessageModel.get_last_or_none()
    imessageData = FetchIMessageData()
    if lastIMessasge:

        new_data_tuple_list = imessageData.get_messages_greater_than_id(lastIMessasge.imessage_id)
        # pprint("new_data_tuple_list")
        # print([d[0] for d in new_data_tuple_list])
        if len(new_data_tuple_list) > 0:
            IMessageModel.insert_many(new_data_tuple_list, fields=[
                IMessageModel.imessage_id,
                IMessageModel.recipient,
                IMessageModel.message,
                IMessageModel.message_time,
                IMessageModel.service_type,
                IMessageModel.account,
                IMessageModel.is_from_me,
                IMessageModel.is_delivered,
                IMessageModel.is_read,
                IMessageModel.is_sent
            ]).execute()

    else:
        last_message_from_app = imessageData.get_last_message()
        # pprint("last_message_from_app")
        # print([d[0] for d in last_message_from_app])
        if len(last_message_from_app) > 0:
            IMessageModel.insert_many(last_message_from_app, fields=[
                IMessageModel.imessage_id,
                IMessageModel.recipient,
                IMessageModel.message,
                IMessageModel.message_time,
                IMessageModel.service_type,
                IMessageModel.account,
                IMessageModel.is_from_me,
                IMessageModel.is_delivered,
                IMessageModel.is_read,
                IMessageModel.is_sent
            ]).execute()


# ------- plist -----------

def read_plist():

    try:
        with open(APP_PREFS_FULL_PATH, 'rb') as f:
            return plistlib.load(f)
    except Exception as e:
        # print(f"Error reading plist: {e}")
        logger.error(f"Error reading plist: {e}")
        return None


def update_plist(new_data, merge_strategy='overwrite'):
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


    try:
        # Read existing data or create empty dict if file doesn't exist
        existing_data = {}
        if APP_PREFS_FULL_PATH.exists():
            with APP_PREFS_FULL_PATH.open('rb') as f:
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
        with APP_PREFS_FULL_PATH.open('wb') as f:
            plistlib.dump(merged_data, f)

        return True

    except Exception as e:
        # print(f"Error updating PLIST file: {e}")
        logger.error(f"Error updating PLIST file: {e}")
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


# ---------------------

if __name__ == "__main__":
    pass

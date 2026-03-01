import json
import os
import uuid

import cloudinary.uploader
import cloudinary.api
import cloudinary
import gevent
import requests
from gevent.lock import BoundedSemaphore
from mss import mss

from file_utils import get_screenshot_path
from my_logger import mylogger
from utils import get_cloudinary_tokens, check_internet_connection, check_user_token, current_user

logger = mylogger("scrn_tsk")

myapp_appdata_path = get_screenshot_path()

class ScreenshotTask:
    def __init__(self):
        self.running = True
        self.lock = BoundedSemaphore(1)
        self.configure_cloudinary()

    def configure_cloudinary(self):
        cloudinary_tokens = get_cloudinary_tokens()
        if cloudinary_tokens:
            config = cloudinary.config(
                secure=True,
                cloud_name=cloudinary_tokens['cloudinary_cloud_name'],
                api_key=cloudinary_tokens['cloudinary_api_key'],
                api_secret=cloudinary_tokens['cloudinary_api_secret']
            )

    def upload_image(self, file_path, user_image_folder, file_name):
        file_name_with_folder = user_image_folder + "/" + file_name
        cloudinary.uploader.upload(file_path, public_id=file_name, folder=user_image_folder, unique_filename=True,
                                   overwrite=False)
        return cloudinary.CloudinaryImage(file_name_with_folder).build_url()

    def remove_image_file(self, file_path):
        if os.path.exists(file_path):
            os.remove(file_path)
            # print("File deleted successfully!")
            logger.info("File deleted successfully: %s", file_path)
        else:
            # print("File not found.")
            logger.error(f"File not found: {file_path}")

    def monitor_screenshot(self):
        while self.running:
            try:
                utoken = check_user_token()
                cloudinary_tokens = get_cloudinary_tokens()

                if utoken and cloudinary_tokens and check_internet_connection():

                    if self.lock.acquire():

                        u_info = current_user()
                        user_image_folder = u_info.nickname
                        file_name = u_info.nickname + "-" + str(uuid.uuid4())
                        public_id_with_folder_name = user_image_folder + "/" + file_name
                        local_file_location = os.path.join(myapp_appdata_path, file_name)
                        # print(f"Taking screenshot: {local_file_location}")
                        logger.info(f"Taking screenshot: {file_name}")

                        sct_img = None
                        with mss() as sct:
                            sct_img = sct.shot(output=local_file_location)

                        if sct_img:
                            delivery_url = self.upload_image(local_file_location, user_image_folder, file_name)

                            # print(f"Delivery URL: {delivery_url}")
                            # logger.info(f"Delivery URL: {delivery_url}")
                            if delivery_url:
                                image_info = cloudinary.api.resource(public_id_with_folder_name)
                                screenshot_url = image_info["url"]
                                # print(f"Uploaded screenshot: {screenshot_url}")
                                logger.info(f"Uploaded screenshot")
                                if screenshot_url:
                                    data = {
                                        'url': screenshot_url,
                                        'token': utoken,
                                    }
                                    json_data = json.dumps(data, indent=4)
                                    try:
                                        response = requests.post("https://backend.skillersbpo.com/api/shot",
                                                                 data=json_data,
                                                                 headers={"Content-Type": "application/json"})

                                        if response.status_code == 200:
                                            logger.info("scrtask data updated.")
                                    except Exception as e:
                                        logger.error(f"Error: {str(e)}")

                            # print(f"Removing screenshot: {local_file_location}")
                            logger.info(f"Removing screenshot")
                            self.remove_image_file(local_file_location)

                        else:
                            # print("Failed to take screenshot")
                            logger.error("Failed to take screenshot")

                        self.lock.release()

            except ValueError as e:
                # print(f"Error while releasing semaphore: {e}")
                logger.error(f"Error while releasing semaphore: {e}")
            gevent.sleep(180)  # Polling every second

    def stop(self):
        self.running = False

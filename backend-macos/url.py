# url.py — macOS
# Central compile-time API configuration
# ─────────────────────────────────────────────────────────────────────────────
#
#  HOW TO SWITCH MODES
#  ───────────────────
#
#  ① STATIC MODE  (enterprise deployment — admin controls all URLs)
#  ────────────────────────────────────────────────────────────────
#    DYNAMIC_API_ENABLED = False
#    BASE_URL = "https://your-server.com"   ← set your real server URL here
#
#    Result:
#      • The "Configure Server APIs" modal is LOCKED in the GUI (no user input).
#      • On every startup, config.json is overwritten with BASE_URL + PATH_*.
#      • Syncing starts immediately without any user action.
#      • To change the server, edit BASE_URL here and recompile.
#
#  ② DYNAMIC MODE  (user / IT admin configures via GUI modal)
#  ──────────────────────────────────────────────────────────
#    DYNAMIC_API_ENABLED = True
#    BASE_URL = "https://your-server.com"   ← used as a first-run seed only
#
#    Result:
#      • The GUI modal is UNLOCKED — user can enter / update URLs.
#      • On first install (all URLs blank in config.json), BASE_URL + PATH_*
#        is seeded into config.json automatically so syncing starts immediately.
#      • After the user saves their own URLs via the GUI, BASE_URL is ignored
#        on subsequent startups — config.json is the source of truth.
#      • To wipe user-set URLs and re-seed, delete config.json and restart.
#
#  ─────────────────────────────────────────────────────────────────────────────
#  IN BOTH MODES: BASE_URL must NOT have a trailing slash.
#  PATH_* constants must NOT be changed unless the server team changes them.
# ─────────────────────────────────────────────────────────────────────────────

# ── Mode switch ───────────────────────────────────────────────────────────────
DYNAMIC_API_ENABLED: bool = False  # True = dynamic GUI modal | False = static/locked

# ── Server base URL ───────────────────────────────────────────────────────────
# Used as source of truth in static mode.
# Used as first-run seed in dynamic mode.
# Must NOT have a trailing slash.
BASE_URL: str = "https://api.company.com"

# ── Branding (shown in GUI when DYNAMIC_API_ENABLED = False) ─────────────────
COMPANY_NAME: str = "Enterprise IT"

# ── URL path suffixes ─────────────────────────────────────────────────────────
# These are appended to BASE_URL to build each full endpoint URL.
# The server MUST implement exactly these paths.
# DO NOT change these unless your server team changes the paths.
PATH_APP_ACTIVITY:        str = "/api/pctracking/appuseage"
PATH_BROWSER:             str = "/api/pctracking/browser"
PATH_CLIPBOARD:           str = "/api/pctracking/clipboard"
PATH_KEYSTROKES:          str = "/api/pctracking/keystrokes"
PATH_SCREENSHOTS:         str = "/api/pctracking/screenshots"
PATH_VIDEOS:              str = "/api/pctracking/videos"
PATH_VIDEO_SETTINGS:      str = "/api/pctracking/video-settings"
PATH_SCREENSHOT_SETTINGS: str = "/api/pctracking/screenshot-settings"
PATH_MONITORING_SETTINGS: str = "/api/pctracking/monitoring-settings"

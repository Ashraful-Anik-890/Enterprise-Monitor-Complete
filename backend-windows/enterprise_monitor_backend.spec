# -*- mode: python ; coding: utf-8 -*-
#
# enterprise_monitor_backend.spec
#
# FIX: console=True (was False)
#   The backend is a server process, not a GUI application. console=False builds
#   the EXE as SUBSYSTEM:WINDOWS — stdout/stderr handles are NULL, all unhandled
#   exceptions and startup errors are completely invisible. Task Scheduler cannot
#   capture output either. console=True keeps the process as SUBSYSTEM:CONSOLE
#   which is correct for a headless backend service. The window is hidden by
#   Task Scheduler anyway (/rl HIGHEST with no interaction flag).
#
# Hidden imports documented:
#   uvicorn.*          : loads loops/protocols via importlib string at runtime
#   anyio.*            : FastAPI/Starlette async backend selected dynamically
#   multipart          : FastAPI form/file upload (python-multipart)
#   pynput.*_win32     : pynput selects Windows platform backend at import time
#   win32*             : pywin32 COM/Win32 modules
#   cv2                : OpenCV (screen_recorder.py)
#   mss + mss.windows  : screen capture + Windows backend
#   numpy.*            : screen_recorder BGRA→BGR array ops
#   passlib.handlers.* : passlib discovers bcrypt handler via plugin registry
#   jose.*             : python-jose JWT; backend selected dynamically
#   uiautomation       : browser_tracker — ships DLLs + XML config

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'anyio',
    'anyio.backends.asyncio',
    'anyio._backends._asyncio',
    'multipart',
    'pynput.keyboard._win32',
    'pynput.mouse._win32',
    'win32api',
    'win32con',
    'win32gui',
    'win32process',
    'cv2',
    'mss',
    'mss.windows',
    'numpy',
    'numpy.core._methods',
    'numpy.lib.format',
    'passlib',
    'passlib.handlers.bcrypt',
    'passlib.handlers.sha2_crypt',
    'jose',
    'jose.jwt',
    'jose.backends',
]

tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('mss')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('uiautomation')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='enterprise_monitor_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # ← FIXED: was False. Backend is a server, not a GUI app.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

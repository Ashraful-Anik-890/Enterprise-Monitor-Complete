# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# Find PyArmor runtime location
pyarmor_runtime_path = None
for p in sys.path:
    candidate = os.path.join(p, 'pyarmor_runtime_000000')  
    if os.path.exists(candidate):
        pyarmor_runtime_path = candidate
        break

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = ['uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'anyio', 'anyio.backends.asyncio', 'anyio._backends._asyncio', 'multipart', 'pynput.keyboard._win32', 'pynput.mouse._win32', 'win32api', 'win32con', 'win32gui', 'win32process', 'cv2', 'mss', 'mss.windows', 'numpy', 'numpy.core._methods', 'numpy.lib.format', 'passlib', 'passlib.handlers.bcrypt', 'passlib.handlers.sha2_crypt', 'jose', 'jose.jwt', 'jose.backends']

# Add PyArmor runtime to datas
if pyarmor_runtime_path:
    datas = [(pyarmor_runtime_path, 'pyarmor_runtime_000000')] + datas
    hiddenimports = ['pyarmor_runtime_000000'] + hiddenimports

# Add internal modules manually (PyArmor hides imports in main.py)
for internal_pkg in ['auth', 'database', 'monitoring', 'services', 'utils']:
    hiddenimports += collect_submodules(internal_pkg)
hiddenimports.extend(['api_server', 'url'])

for pkg in ('cv2', 'mss', 'uiautomation', 'pynput', 'passlib', 'pyperclip', 'PIL', 'psutil', 'requests', 'fastapi', 'pydantic'):
    tmp_ret = collect_all(pkg)
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
    [],
    exclude_binaries=True,
    name='enterprise_monitor_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='enterprise_monitor_backend',
)

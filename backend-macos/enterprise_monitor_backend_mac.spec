# enterprise_monitor_backend_mac.spec
# Build: python -m PyInstaller enterprise_monitor_backend_mac.spec
# Target: Apple Silicon (arm64). Change target_arch for Intel (x86_64) or both (universal2).
#
# RULES:
#   - onedir mode (NOT onefile — --onefile breaks macOS code signing)
#   - UPX = False everywhere (UPX breaks Mach-O code signatures)
#   - No com.apple.security.app-sandbox (blocks osascript and process monitoring)

from PyInstaller.utils.hooks import collect_all, collect_submodules
import os
import sys

# Find PyArmor runtime location
pyarmor_runtime_path = None
for p in sys.path:
    candidate = os.path.join(p, 'pyarmor_runtime_000000')  
    if os.path.exists(candidate):
        pyarmor_runtime_path = candidate
        break

block_cipher = None

datas = []
binaries = []
hiddenimports = [
    # uvicorn internals (not auto-discovered by PyInstaller)
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

    # pynput macOS backend
    'pynput.keyboard._darwin',
    'pynput.mouse._darwin',

    # pyobjc frameworks
    'Quartz',
    'ApplicationServices',

    # passlib / jose — passlib.handlers.* must be listed explicitly because
    # passlib loads them by string name at runtime (PyInstaller static scan misses them)
    'jose',
    'jose.jwt',
    'jose.backends',
    'passlib',
    'passlib.context',
    'passlib.handlers',
    'passlib.handlers.bcrypt',
    'passlib.handlers.sha2_crypt',
    'passlib.handlers.md5_crypt',
    'passlib.handlers.des_crypt',
    'passlib.utils',
    'passlib.utils.binary',
    'passlib.utils.decor',
    'passlib.crypto',
    'passlib.crypto.digest',
    'bcrypt',

    # NumPy / OpenCV internals
    'numpy.core._methods',
    'numpy.lib.format',
    'cv2',
]

# Add PyArmor runtime to datas
if pyarmor_runtime_path:
    datas = [(pyarmor_runtime_path, 'pyarmor_runtime_000000')] + datas
    hiddenimports = ['pyarmor_runtime_000000'] + hiddenimports

# Collect full packages that PyInstaller misses
for pkg in ('cv2', 'mss', 'pynput', 'passlib', 'pyperclip', 'PIL', 'psutil', 'requests', 'fastapi', 'pydantic'):
    tmp = collect_all(pkg)
    datas    += tmp[0]
    binaries += tmp[1]
    hiddenimports += tmp[2]

# Explicitly add internal modules (since main.py is obfuscated, PyInstaller can't see them)
for internal_pkg in ('auth', 'database', 'monitoring', 'services', 'utils'):
    hiddenimports += collect_submodules(internal_pkg)
hiddenimports.extend(['api_server', 'url'])

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas + [
        ('resources/entitlements.plist', 'resources'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Windows-only — must never be imported on macOS
        'pywin32', 'win32api', 'win32gui', 'win32process', 'win32con',
        'uiautomation', 'comtypes', 'winreg',
        # Unused UI toolkits
        'tkinter', 'wx', 'PyQt5', 'PyQt6',
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # onedir — required for macOS code signing
    name='enterprise_monitor_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # NEVER use UPX on macOS — breaks code signing
    console=True,
    argv_emulation=False,
    target_arch='arm64',            # Apple Silicon. Change to 'x86_64' for Intel, 'universal2' for both
    codesign_identity=None,         # Set to Apple Developer ID for notarized builds
    entitlements_file='resources/entitlements.plist',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='enterprise_monitor_backend',
)

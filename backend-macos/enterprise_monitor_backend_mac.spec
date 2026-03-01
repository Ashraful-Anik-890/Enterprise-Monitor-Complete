# enterprise_monitor_backend_mac.spec
# Build: python -m PyInstaller enterprise_monitor_backend_mac.spec
# Target: Apple Silicon (arm64). Change target_arch for Intel (x86_64) or both (universal2).
#
# RULES:
#   - onedir mode (NOT onefile — --onefile breaks macOS code signing)
#   - UPX = False everywhere (UPX breaks Mach-O code signatures)
#   - No com.apple.security.app-sandbox (blocks osascript and process monitoring)

from PyInstaller.utils.hooks import collect_all, collect_submodules

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

    # passlib / jose
    'jose',
    'jose.jwt',
    'jose.backends',

    # NumPy / OpenCV internals
    'numpy.core._methods',
    'numpy.lib.format',
    'cv2',
]

# Collect full packages that PyInstaller misses
for pkg in ('cv2', 'mss', 'pynput'):
    tmp = collect_all(pkg)
    datas    += tmp[0]
    binaries += tmp[1]
    hiddenimports += tmp[2]

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

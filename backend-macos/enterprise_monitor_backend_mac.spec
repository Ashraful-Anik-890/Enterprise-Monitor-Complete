# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Enterprise Monitor Backend — macOS

Build command:
    pyinstaller enterprise_monitor_backend_mac.spec

Output:
    dist/enterprise_monitor_backend/enterprise_monitor_backend  (onedir bundle)

Notes:
  - UPX is disabled (breaks NumPy/OpenCV on macOS with Hardened Runtime)
  - target_arch='arm64' for Apple Silicon. Change to 'x86_64' for Intel Macs.
  - Entitlements plist is referenced for codesigning (see resources/)
  - Hidden imports include pyobjc frameworks that are loaded dynamically
"""
import sys
from pathlib import Path

block_cipher = None

# ── Paths ────────────────────────────────────────────────────────────────────
SPEC_DIR    = Path(SPECPATH)   # directory containing this .spec file
RESOURCES   = SPEC_DIR / 'resources'
ENTITLEMENTS = RESOURCES / 'entitlements.plist'

a = Analysis(
    ['main.py'],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=[
        # Include entitlements for downstream codesigning scripts
        (str(ENTITLEMENTS), 'resources'),
    ],
    hiddenimports=[
        # ── FastAPI / Uvicorn ────────────────────────────────────────────────
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

        # ── Auth ─────────────────────────────────────────────────────────────
        'jose',
        'jose.jwt',
        'passlib',

        # ── macOS pyobjc frameworks ──────────────────────────────────────────
        'Quartz',
        'Quartz.CoreGraphics',
        'ApplicationServices',

        # ── pynput backend ───────────────────────────────────────────────────
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',

        # ── Misc ─────────────────────────────────────────────────────────────
        'pyperclip',
        'zoneinfo',
        'tzdata',

        # ── Our own packages ─────────────────────────────────────────────────
        'auth',
        'auth.auth_manager',
        'database',
        'database.db_manager',
        'monitoring',
        'monitoring.permissions',
        'monitoring.app_tracker',
        'monitoring.browser_tracker',
        'monitoring.keylogger',
        'monitoring.screenshot',
        'monitoring.screen_recorder',
        'monitoring.clipboard',
        'monitoring.data_cleaner',
        'services',
        'services.sync_service',
        'utils',
        'utils.config_manager',
        'utils.autostart_manager',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Windows-only — must NOT be collected
        'win32api', 'win32gui', 'win32process', 'win32con',
        'comtypes', 'uiautomation',
        'pywin32',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='enterprise_monitor_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # CRITICAL: UPX breaks NumPy/OpenCV on macOS
    console=True,
    target_arch='arm64',            # Apple Silicon. Change to 'x86_64' for Intel.
    codesign_identity='',           # Sign with ad-hoc identity (or specify your ID)
    entitlements_file=str(ENTITLEMENTS),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='enterprise_monitor_backend',
)

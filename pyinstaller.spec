# -*- mode: python ; coding: utf-8 -*-
"""Desktop bundle spec.

Windows and Linux release jobs call PyInstaller on ``db_storage_manager/main.py``
and do not use this file. The macOS job runs ``pyinstaller pyinstaller.spec``
with no makespec flags (those are rejected next to a spec) and expects
``dist/DB Storage Manager.app``.
"""

import re
import sys
from pathlib import Path

_init = Path("db_storage_manager/__init__.py").read_text(encoding="utf-8")
_version_match = re.search(
    r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', _init, re.M
)
if _version_match is None:
    raise SystemExit("db_storage_manager/__init__.py has no __version__")
_version = _version_match.group(1)

_icns = Path("db_storage_manager/resources/icons/db-storage-manager.icns")
_ico = "db_storage_manager/resources/icons/db-storage-manager.ico"

a = Analysis(
    ["db_storage_manager/main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("db_storage_manager/resources/icons", "db_storage_manager/resources/icons"),
    ],
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtCharts",
        "db_storage_manager",
        "db_storage_manager.db",
        "db_storage_manager.gui",
        "db_storage_manager.backups",
        "db_storage_manager.security",
        "db_storage_manager.monitoring",
        "db_storage_manager.i18n",
        "db_storage_manager.themes",
        "db_storage_manager.resources",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

if sys.platform == "darwin":
    # Onedir + BUNDLE is the macOS .app PyInstaller builds for --windowed.
    # UPX is left off: it is not installed on the hosted runner and corrupts arm64 slices.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="DB Storage Manager",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
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
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="DB Storage Manager",
    )
    app = BUNDLE(
        coll,
        name="DB Storage Manager.app",
        icon=str(_icns) if _icns.is_file() else None,
        bundle_identifier="com.voxhash.db-storage-manager",
        version=_version,
        info_plist={
            "CFBundleName": "DB Storage Manager",
            "CFBundleDisplayName": "DB Storage Manager",
            "CFBundleShortVersionString": _version,
            "CFBundleVersion": _version,
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="DB_Storage_Manager",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=_ico,
    )

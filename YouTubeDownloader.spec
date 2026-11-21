# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — 目录模式 (onedir)，含 PySide6 WebEngine

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

pyside6_datas, pyside6_binaries, pyside6_hidden = collect_all("PySide6")

a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=list(pyside6_binaries),
    datas=[
        ("app/ui/themes", "app/ui/themes"),
        ("app/ui/styles.qss", "app/ui"),
        ("app/resources", "app/resources"),
        *pyside6_datas,
    ],
    hiddenimports=[
        *pyside6_hidden,
        *collect_submodules("yt_dlp"),
        "app",
        "app.config",
        "app.paths",
        "app.core",
        "app.core.auth",
        "app.core.cookie_import",
        "app.core.cookie_profiles",
        "app.core.cookie_sync",
        "app.core.download_manager",
        "app.core.downloader",
        "app.core.errors",
        "app.core.ui_bridge",
        "app.core.validators",
        "app.ui",
        "app.ui.app_icon",
        "app.ui.login_dialog",
        "app.ui.main_window",
        "app.ui.themes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YouTubeDownloader",
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
    icon="app/resources/app.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="YouTubeDownloader",
)
# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Auto-Citation
# Build: pyinstaller auto_citation.spec  (from project root)

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

citeproc_datas = collect_data_files('citeproc')

a = Analysis(
    ['testing/main.py'],
    pathex=['testing'],
    binaries=[],
    datas=[
        *citeproc_datas,
    ],
    hiddenimports=[
        *collect_submodules('citeproc'),
        *collect_submodules('lxml'),
        *collect_submodules('openpyxl'),
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'IPython', 'jupyter'],
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
    name='AutoCitation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
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
    upx=True,
    upx_exclude=[],
    name='AutoCitation',
)

# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Auto-Citation (Windows .exe)
# Usage:
#   pyinstaller auto_citation.spec
#
# The entry point is testing/main.py.
# The 'testing/' directory is added to pathex so that
#   "from ui.main_window import ..." and "from core.xxx import ..."
#   resolve correctly.

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── paths ──────────────────────────────────────────────────────────────────
SRC = Path('testing')          # project root (contains main.py, core/, ui/)

# ── data files to bundle ───────────────────────────────────────────────────
# citeproc-py ships locale + schema + built-in style XML files.
# Without them the CSL renderer raises FileNotFoundError at runtime.
citeproc_datas = collect_data_files('citeproc')

# openpyxl bundles template xlsx files that are needed at runtime.
openpyxl_datas = collect_data_files('openpyxl')

# Merge all data tuples
all_datas = citeproc_datas + openpyxl_datas

# ── hidden imports ─────────────────────────────────────────────────────────
# PyInstaller cannot detect dynamic imports automatically.
hidden = [
    # application core
    'core.model',
    'core.project',
    'core.ris',
    'core.scan',
    'core.normalize',
    'core.validate',
    'core.corrections',
    'core.formatting',
    'core.exporters',
    'core.style_registry',
    'core.config',
    'core.paths',
    'core.formatters',
    'core.formatters.base',
    'core.formatters.kr_default',
    'core.csl',
    'core.csl.adapter',
    'core.csl.renderer',
    # UI
    'ui.main_window',
    # third-party
    'openpyxl',
    'openpyxl.styles',
    'openpyxl.utils',
    'openpyxl.writer.excel',
    'citeproc',
    'citeproc.source.json',
    'lxml',
    'lxml.etree',
    'six',
    # PySide6 extras sometimes missed
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
]

# ── analysis ───────────────────────────────────────────────────────────────
a = Analysis(
    [str(SRC / 'main.py')],
    pathex=[str(SRC)],          # adds testing/ to sys.path inside the bundle
    binaries=[],
    datas=all_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── single-file executable ─────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AutoCitation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no black console window behind the GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

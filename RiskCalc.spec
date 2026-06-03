# -*- mode: python ; coding: utf-8 -*-
import os

BASE = '/Users/dmitriykiselev/Library/Mobile Documents/com~apple~CloudDocs/Python/RiskCalc'

a = Analysis(
    [os.path.join(BASE, 'run_app.py')],
    pathex=[BASE],
    binaries=[],
    datas=[
        (os.path.join(BASE, 'models'),       'models'),
        (os.path.join(BASE, 'instruments'),  'instruments'),
        (os.path.join(BASE, 'risk'),         'risk'),
        (os.path.join(BASE, 'app'),          'app'),
    ],
    hiddenimports=[
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
        'matplotlib', 'matplotlib.backends.backend_qtagg',
        'scipy', 'scipy.stats', 'scipy.optimize', 'scipy.integrate',
        'numpy', 'app.panels.option_panel', 'app.panels.barrier_panel',
        'app.panels.exotic_panel', 'app.panels.fx_panel',
        'app.panels.rates_panel', 'app.panels.var_panel',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'PyQt6'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='RiskCalc',
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
    exe, a.binaries, a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RiskCalc',
)

app = BUNDLE(
    coll,
    name='RiskCalc.app',
    icon=None,
    bundle_identifier='com.riskcalc.app',
    version='1.0.0',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleDocumentTypes': [],
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHumanReadableCopyright': '© 2025 RiskCalc',
    },
)

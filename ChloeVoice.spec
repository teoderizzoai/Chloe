# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller ChloeVoice.spec
#
# The resulting binary is dist/ChloeVoice.
# It still needs external model files at runtime:
#   - Whisper model  (~3 GB, downloaded automatically by faster-whisper on first run)
#   - Fish Speech checkpoint  (see FISH_SPEECH_DIR / checkpoints/)
# Everything else is bundled.

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

a = Analysis(
    ['voice_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Bundle Chloe images so the portrait works from the binary
        ('chloe/images', 'chloe/images'),
        # Bundle voice sample if present
        *([('voice_sample.wav', '.')] if os.path.exists('voice_sample.wav') else []),
    ],
    hiddenimports=[
        # faster-whisper / ctranslate2
        *collect_submodules('faster_whisper'),
        *collect_submodules('ctranslate2'),
        # sounddevice / soundfile
        'sounddevice', 'soundfile',
        # pynput Linux backends
        'pynput.keyboard._xorg',
        'pynput.mouse._xorg',
        # tkinter
        'tkinter', 'tkinter.font',
        # PIL
        'PIL', 'PIL.Image', 'PIL.ImageTk',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ChloeVoice',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # no terminal window
    icon=None,          # add .png/.ico path here if you have one
)

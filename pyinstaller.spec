# -*- mode: python -*-

from PyInstaller.utils.hooks import collect_data_files


block_cipher = None
pyproj_data = collect_data_files("pyproj")


analysis = Analysis(
    ['./qt_ui/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('resources', 'resources'),
        ('resources/caucasus.p', 'dcs/terrain/'),
        ('resources/nevada.p', 'dcs/terrain/'),
        ('client/build', 'client/build'),
    ] + pyproj_data,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(
    analysis.pure,
    analysis.zipped_data,
    cipher=block_cipher,
)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    icon="resources/icon.ico",
    exclude_binaries=True,
    name='liberation_main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    contents_directory='.',
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=True,
    name='dcs_liberation',
)

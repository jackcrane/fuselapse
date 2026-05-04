from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


project_root = Path.cwd()
ffmpeg_path = os.environ.get("FUSELAPSE_FFMPEG")
if not ffmpeg_path:
    raise SystemExit("FUSELAPSE_FFMPEG must point to the ffmpeg binary to bundle.")

ffmpeg_file = Path(ffmpeg_path)
if not ffmpeg_file.exists():
    raise SystemExit(f"Bundled ffmpeg binary was not found: {ffmpeg_file}")

datas = collect_data_files("cv2")
binaries = collect_dynamic_libs("cv2")
binaries.append((str(ffmpeg_file), "."))


a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["PyQt5.sip"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Deliberately exclude repo sample media and runtime output files.
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Fuselapse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

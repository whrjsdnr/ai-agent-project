# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import runpy
import sys
from importlib.metadata import distribution

root = Path(SPECPATH).resolve().parents[1]
assets = root / "build" / "assets"
assets.mkdir(parents=True, exist_ok=True)
icon = assets / "ai-agent.ico"
icon.write_bytes(runpy.run_path(str(root / "packaging/assets/generate_icon.py"))["icon_bytes"]())
metadata = distribution("ai-agent-project")
# Only the metadata needed for version resolution; never editable direct_url.json.
metadata_path = assets / "ai_agent_project-{}.dist-info".format(metadata.version)
metadata_path.mkdir(exist_ok=True)
(metadata_path / "METADATA").write_text("Metadata-Version: 2.1\nName: ai-agent-project\nVersion: " + metadata.version + "\n", encoding="utf-8")
version_file = assets / "version.txt"
parts = tuple(int(v) for v in metadata.version.split("."))
if len(parts) != 3:
    raise ValueError("Windows distribution requires a three-component numeric version")
version_file.write_text("VSVersionInfo(ffi=FixedFileInfo(filevers=" + repr((*parts, 0)) + ", prodvers=" + repr((*parts, 0)) + ", mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), kids=[StringFileInfo([StringTable('040904B0', [StringStruct('ProductName', 'AI Agent'), StringStruct('FileDescription', 'AI Agent local desktop application'), StringStruct('FileVersion', '" + metadata.version + "'), StringStruct('ProductVersion', '" + metadata.version + "'), StringStruct('OriginalFilename', 'AI-Agent.exe')])]), VarFileInfo([VarStruct('Translation', [1033,1200])])])", encoding="utf-8")
a = Analysis(
    [str(root / "packaging/pyinstaller/entrypoint.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(root / "src/ai_agent_project/desktop_app/assets/ai-agent.svg"), "ai_agent_project/desktop_app/assets"),
           (str(icon), "ai_agent_project/desktop_app/assets"),
           (str(metadata_path / "METADATA"), metadata_path.name)],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "pytest", "fastapi", "starlette", "uvicorn", "uv", "PyInstaller", "ai_agent_project.api", "ai_agent_project.cli", "tkinter", "IPython"],
    noarchive=False,
)
# importlib.metadata analysis can also collect editable-install metadata. Strip
# direct_url.json from every distribution so local checkout paths never ship.
a.datas = [entry for entry in a.datas if Path(entry[0]).name != "direct_url.json"]
# Standard PyInstaller PySide6 hooks collect the imported Qt modules and plugins.
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AI-Agent", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(icon), version=str(version_file) if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AI-Agent")

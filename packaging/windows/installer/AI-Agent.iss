#ifndef AppVersion
  #error AppVersion must be supplied from pyproject.toml by build.ps1
#endif
#ifndef RepoRoot
  #error RepoRoot must be supplied by build.ps1
#endif
[Setup]
AppId={{B248FB75-F743-438B-B36E-E948066C3E99}
AppName=AI Agent
AppVersion={#AppVersion}
AppVerName=AI Agent {#AppVersion}
DefaultDirName={localappdata}\Programs\AI Agent
DefaultGroupName=AI Agent
PrivilegesRequired=lowest
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#RepoRoot}\dist\installer
OutputBaseFilename=AI-Agent-Setup
SetupIconFile={#RepoRoot}\build\assets\ai-agent.ico
UninstallDisplayIcon={app}\AI-Agent.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#RepoRoot}\dist\AI-Agent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AI Agent"; Filename: "{app}\AI-Agent.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\AI Agent"; Filename: "{app}\AI-Agent.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AI-Agent.exe"; Description: "Launch AI Agent"; Flags: nowait postinstall skipifsilent

; No [UninstallDelete] or user-data files: normal uninstall preserves all user state.

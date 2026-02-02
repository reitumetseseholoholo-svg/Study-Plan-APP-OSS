#ifndef AppName
  #define AppName "ACCA Study Assistant"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef Publisher
  #define Publisher "Lereko Seholoholo"
#endif
#define AppExeName "{#AppName}.exe"

[Setup]
AppId={{9A8E2A5C-3A2B-4F68-8B8A-9A6D1B2B6D3C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputBaseFilename=installer
OutputDir=build\windows\Output
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

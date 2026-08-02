[Setup]
#define AppVersion GetStringParameterValue("AppVersion")
AppId={{9A3B7D2E-4C21-4F0A-9D2C-000000000001}
AppName=Insulation Coordination Calculator
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Insulation Coordination Calculator
DefaultGroupName=Insulation Coordination Calculator
PrivilegesRequired=lowest
OutputBaseFilename=insulation-coordination-{#AppVersion}-windows-x86_64-setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\icc\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Insulation Coordination Calculator"; Filename: "{app}\icc.exe"
Name: "{autodesktop}\Insulation Coordination Calculator"; Filename: "{app}\icc.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Registry]
Root: HKCU; Subkey: "Software\Classes\.icproj"; ValueType: string; ValueName: ""; ValueData: "InsulationCoordinationProject"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\InsulationCoordinationProject\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\icc.exe"" ""%1"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.icrules"; ValueType: string; ValueName: ""; ValueData: "InsulationCoordinationRules"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\InsulationCoordinationRules\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\icc.exe"" ""%1"""; Flags: uninsdeletekey

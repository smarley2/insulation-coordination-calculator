[Setup]
AppId={{9A3B7D2E-4C21-4F0A-9D2C-InsulationCoord}
AppName=Insulation Coordination Calculator
AppVersion=0.1.0
DefaultDirName={localappdata}\Insulation Coordination Calculator
DefaultGroupName=Insulation Coordination Calculator
PrivilegesRequired=lowest
OutputBaseFilename=insulation-coordination-setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\icc\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Insulation Coordination Calculator"; Filename: "{app}\icc.exe"

[Registry]
Root: HKCU; Subkey: "Software\Classes\.icproj"; ValueType: string; ValueName: ""; ValueData: "InsulationCoordinationProject"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\InsulationCoordinationProject\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\icc.exe"" ""%1"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.icrules"; ValueType: string; ValueName: ""; ValueData: "InsulationCoordinationRules"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\InsulationCoordinationRules\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\icc.exe"" ""%1"""; Flags: uninsdeletekey

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\icc\rules"
Type: dirifempty; Name: "{userappdata}\icc"

#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif

[Setup]
AppId={{767743B4-24BC-45ED-A91F-7153DFA52DC4}
AppName=OpenBagus
AppVersion=0.6.0
AppPublisher=OpenBagus
DefaultDirName=E:\Projects\OpenBagus\_installed\OpenBagus
DefaultGroupName=OpenBagus
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ReleaseDir}
OutputBaseFilename=OpenBagus-Setup
Compression=lzma2/fast
SolidCompression=yes
CompressionThreads=1
WizardStyle=modern
UninstallDisplayIcon={app}\OpenBagus.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
LicenseFile=THIRD_PARTY_NOTICES.md

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "openbagus.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"

[Icons]
Name: "{userdesktop}\OpenBagus"; Filename: "{app}\OpenBagus.exe"; WorkingDir: "{app}"
Name: "{userprograms}\OpenBagus\OpenBagus"; Filename: "{app}\OpenBagus.exe"; WorkingDir: "{app}"
Name: "{userprograms}\OpenBagus\OpenBagus Diagnostics"; Filename: "{app}\OpenBagus.exe"; Parameters: "--diagnostics"; WorkingDir: "{app}"

[Run]
Filename: "{app}\OpenBagus.exe"; Description: "Jalankan OpenBagus sekarang"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Target: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    Target := Lowercase(RemoveBackslashUnlessRoot(ExpandFileName(WizardDirValue)));
    if (Length(Target) < 5) or DirExists(Target + '\.git') or
       (Target = 'e:\projects') or (Target = 'e:\projects\openbagus') or
       (Pos('e:\projects\openbagus\models', Target) = 1) or
       (Pos('e:\projects\openbagus-3d', Target) = 1) or
       (Pos('e:\projects\openbagus-voice', Target) = 1) or
       (Pos('e:\projects\openbagus-data', Target) = 1) or
       (Target = 'e:\projects\openbagus-chattest') then begin
      MsgBox('Pilih folder aplikasi terpisah, bukan source repository, worktree, atau models.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

; 데이터시트 다운로더 설치 스크립트 (Inno Setup)
; 하나의 Setup.exe로: 코드/데이터 복사 -> 바로가기 생성.
; 최초 실행 시 run_app.bat이 Python/가상환경/패키지/브라우저를 자동 준비하고 API 키를 입력받아요.

#define AppName "데이터시트 다운로더"
#define AppVersion "1.0.0"
#define AppPublisher "leeb8901"
#define ExeLauncher "start.vbs"

[Setup]
AppId={{7F3B2C10-9D4E-4A6B-8C21-DATASHEET0001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; 관리자 권한 없이 사용자 폴더에 설치 (프로그램이 자기 폴더에 venv/로그/다운로드를 쓰기 때문)
PrivilegesRequired=lowest
DefaultDirName={localappdata}\DatasheetDownloader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=데이터시트다운로더_설치
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
UninstallDisplayName={#AppName}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 아이콘:"

[Files]
; 앱 소스/데이터 (스테이징 폴더 전체)
Source: "app\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; 최초 실행 때 Python이 없으면 쓰는 내장 설치기 (설치 성공 후 자동 삭제됨)
Source: "assets\python-3.14.6-amd64.exe"; DestDir: "{app}\_setup"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeLauncher}"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 220
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeLauncher}"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 220; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeLauncher}"; Description: "지금 실행 (최초 준비가 자동으로 진행됩니다)"; WorkingDir: "{app}"; Flags: shellexec postinstall skipifsilent

[UninstallDelete]
; 프로그램이 만든 런타임 산출물까지 정리
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\Download_ datasheets"
Type: filesandordirs; Name: "{app}\_setup"
Type: files; Name: "{app}\.setup_done"
Type: files; Name: "{app}\.env"

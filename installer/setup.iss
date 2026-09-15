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
; PySide6(LGPL) 등 재배포 오픈소스 라이선스 고지 - 사용자가 실제로 볼 수 있게 시작메뉴에 노출
; (2026-09-15 추가, 보안점검_2026-09-11.md §6). 메모장으로 직접 열어서 파일 연결 설정과 무관하게
; 항상 뜨도록 함.
Name: "{group}\오픈소스 라이선스"; Filename: "{win}\notepad.exe"; Parameters: """{app}\THIRD-PARTY-NOTICES.md"""
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeLauncher}"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 220; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeLauncher}"; Description: "지금 실행 (최초 준비가 자동으로 진행됩니다)"; WorkingDir: "{app}"; Flags: shellexec postinstall skipifsilent

[UninstallDelete]
; 프로그램이 만든 런타임 산출물까지 정리 (API 키가 든 User_API\ 는 일부러 안 지움 - {app} 전체가
; 지워지는 표준 제거 과정에서 같이 없어지긴 하지만, 재설치 흐름에서 실수로 먼저 지워지지
; 않도록 여기 목록엔 굳이 안 넣음)
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\Download_ datasheets"
Type: filesandordirs; Name: "{app}\_setup"
Type: files; Name: "{app}\.setup_done"

; 데이터시트 다운로더 Lite 설치 스크립트 (Inno Setup)
; 원본(데이터시트 다운로더)과 다른 점: 데이터시트 자동 다운로드 중 "웹(DuckDuckGo) 검색" 단계가
; 빠져 있음(2026-09-04) - 불특정 다수에게 배포할 때 자동 웹 검색이 IP 차단으로 이어졌던 사고를
; 재현하지 않기 위해서. Mouser 공식 API만 쓰고, 그걸로 못 찾으면 참고 링크만 안내함(자동 접속 없음).
; 하나의 Setup.exe로: 코드/데이터 복사 -> 바로가기 생성.
; 최초 실행 시 run_app.bat이 Python/가상환경/패키지/브라우저를 자동 준비하고 API 키를 입력받아요.

#define AppName "데이터시트 다운로더 Lite"
#define AppVersion "1.1.0"
#define AppPublisher "leeb8901"
#define ExeLauncher "start.vbs"

[Setup]
AppId={{7F3B2C10-9D4E-4A6B-8C21-DATASHEETLIT1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; 관리자 권한 없이 사용자 폴더에 설치 (프로그램이 자기 폴더에 venv/로그/다운로드를 쓰기 때문)
PrivilegesRequired=lowest
DefaultDirName={localappdata}\DatasheetDownloaderLite
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=C:\Users\Root\Desktop\클로드\00. 배포용
OutputBaseFilename=데이터시트다운로더Lite_설치
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
; Mouser API 키를 설치파일에 그대로 담아서, 설치하자마자 바로 쓸 수 있게 함(2026-09-09 갱신 -
; API 키 저장 방식이 .env에서 User_API/ 폴더(파일 하나당 API 하나)로 바뀌어서 그에 맞춤. 본인만
; 쓰는 개인용 배포라 API 키를 설치파일에 포함해도 된다고 확인함 - 다른 사람에게 이 Setup.exe를
; 그대로 넘기면 그 사람도 이 키를 쓸 수 있게 되니 공유 금지). utils/config.py가 찾는 자리
; ({app}\User_API\)에 바로 설치해서 첫 실행부터 정상 동작함.
Source: "user_api_bundle\User_API\*"; DestDir: "{app}\User_API"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeLauncher}"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 220
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

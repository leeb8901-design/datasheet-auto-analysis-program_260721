; 데이터시트 다운로더 Lite 설치 스크립트 (Inno Setup)
; 원본(데이터시트 다운로더)과 다른 점: 데이터시트 자동 다운로드 중 "웹(DuckDuckGo) 검색" 단계가
; 빠져 있음(2026-09-04) - 불특정 다수에게 배포할 때 자동 웹 검색이 IP 차단으로 이어졌던 사고를
; 재현하지 않기 위해서. Mouser 공식 API만 쓰고, 그걸로 못 찾으면 참고 링크만 안내함(자동 접속 없음).
; 하나의 Setup.exe로: 코드/데이터 복사 -> 바로가기 생성.
; 최초 실행 시 run_app.bat이 Python/가상환경/패키지/브라우저를 자동 준비하고 API 키를 입력받아요.

#define AppName "데이터시트 다운로더 Lite"
#define AppVersion "1.0.0"
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
; Mouser API 키(.env)를 설치파일에 그대로 담아서, 설치하자마자 바로 쓸 수 있게 함(2026-09-04 -
; 본인만 쓰는 개인용 배포라 API 키를 설치파일에 포함해도 된다고 확인함 - 다른 사람에게 이
; Setup.exe를 그대로 넘기면 그 사람도 이 키를 쓸 수 있게 되니 공유 금지). utils/config.py가
; 1순위로 찾는 자리(%AppData%\DatasheetDownloader\.env)에 바로 설치해서, launch.ps1의 "키
; 입력 창"이 아예 안 뜨고 첫 실행부터 정상 동작함. onlyifdoesntexist: 이미 그 자리에 .env가
; 있으면(원본 프로그램을 먼저 설치해서 이미 키를 넣어둔 경우 등) 안 덮어씀.
Source: "env_bundle\.env"; DestDir: "{userappdata}\DatasheetDownloader"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeLauncher}"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 220
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeLauncher}"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 220; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeLauncher}"; Description: "지금 실행 (최초 준비가 자동으로 진행됩니다)"; WorkingDir: "{app}"; Flags: shellexec postinstall skipifsilent

[UninstallDelete]
; 프로그램이 만든 런타임 산출물까지 정리 (Mouser API 키가 담긴 %AppData%\DatasheetDownloader\.env는
; 프로그램 설치 폴더 밖에 있어서 여기서 안 지워짐 - 재설치해도 키를 다시 입력할 필요 없게 의도적으로 둠).
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\Download_ datasheets"
Type: filesandordirs; Name: "{app}\_setup"
Type: files; Name: "{app}\.setup_done"
Type: files; Name: "{app}\.env"

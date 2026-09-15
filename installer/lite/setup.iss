; 데이터시트 다운로더 Lite 설치 스크립트 (Inno Setup)
; 원본(데이터시트 다운로더)과 다른 점: 데이터시트 자동 다운로드 중 "웹(DuckDuckGo) 검색" 단계가
; 빠져 있음(2026-09-04) - 불특정 다수에게 배포할 때 자동 웹 검색이 IP 차단으로 이어졌던 사고를
; 재현하지 않기 위해서. Mouser 공식 API만 쓰고, 그걸로 못 찾으면 참고 링크만 안내함(자동 접속 없음).
; 하나의 Setup.exe로: 코드/데이터 복사 -> 바로가기 생성.
; 최초 실행 시 run_app.bat이 Python/가상환경/패키지/브라우저를 자동 준비하고 API 키를 입력받아요.

#define AppName "데이터시트 다운로더 Lite"
#define AppVersion "1.2.0"
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
; Mouser API 키 번들링은 기본적으로 꺼져 있음(안전한 기본값, 2026-09-09 변경) - 공개
; 저장소(GitHub 등)에 올려도 되는 "키 없는" 빌드가 기본이 되도록. 개인용으로 내 실제 키를
; 담은 빌드가 필요할 때만 컴파일 시 "ISCC /DBUNDLE_API_KEY setup.iss"처럼 이 심볼을 정의해서
; 켬(installer/lite/README.md 참고) - 그러면 user_api_bundle\User_API\* 안의 실제 키 파일이
; {app}\User_API\에 그대로 설치돼 첫 실행부터 바로 동작함. 이렇게 만든 결과물은 절대 남에게
; 공유 금지(내 API 키가 그대로 들어있음) - 플래그를 안 켠(기본) 빌드만 남에게 공유/공개 가능.
#ifdef BUNDLE_API_KEY
Source: "user_api_bundle\User_API\*"; DestDir: "{app}\User_API"; Flags: recursesubdirs createallsubdirs ignoreversion
#endif

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeLauncher}"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 220
; PySide6(LGPL) 등 재배포 오픈소스 라이선스 고지 - 사용자가 실제로 볼 수 있게 시작메뉴에 노출
; (2026-09-15 추가, 원본과 동일하게 반영 - ../보안점검_2026-09-11.md §6). 메모장으로 직접 열어서
; 파일 연결 설정과 무관하게 항상 뜨도록 함.
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

# 데이터시트 다운로더 Lite — 빌드 방법

일반 배포판(`../빌드방법.md`)과 **딱 하나만 다릅니다**: 데이터시트 자동 다운로드 중
"웹(DuckDuckGo) 검색으로 보완" 단계가 빠져 있어요. Mouser 공식 API만 쓰고, 그걸로 못 찾으면
자동으로 다른 곳을 뒤지지 않고 Mouser/DigiKey/구글 검색 참고 링크 3개만 남겨서 사람이 직접
찾도록 안내합니다(2026-09-04 도입 — 불특정 다수에게 배포할 때, DuckDuckGo 자동 검색이 실제로
IP 차단으로 이어졌던 사고(원본 `CLAUDE.md` 결정 로그 참고)를 재현하지 않기 위해서예요).

## 이 폴더에 있는 것
- `downloader.py` — `datasheet/downloader.py`를 대체할 파일(웹 검색/스크래핑 관련 코드 전부
  제거: `search_datasheet_urls`/`find_datasheet`/`_try_candidates`/DDG 재시도·차단 로직/
  `BeautifulSoup` 파싱 등). 나머지 로직(Mouser 다운로드, 참고 링크 3개 만들기)은 원본과 동일.
- `requirements.txt` — 원본에서 `beautifulsoup4`만 뺀 버전(DDG HTML 파싱에만 쓰였음).
- `setup.iss` — Inno Setup 스크립트. 원본과 다른 점: `AppName`="데이터시트 다운로더 Lite",
  `AppId` 별도 발급(원본과 동시 설치 가능하게), `DefaultDirName`=`DatasheetDownloaderLite`,
  `OutputBaseFilename`=`데이터시트다운로더Lite_설치`. **Mouser API 키(.env) 저장 위치는
  원본과 동일**(`%AppData%\DatasheetDownloader\.env`, 의도적 - 원본을 이미 쓰고 있는 사람은
  Lite에서 키를 또 입력할 필요 없음). **`.env` 파일 자체를 설치파일 안에 담아서 그 자리에
  바로 깔아줌**(2026-09-04 추가 - `[Files]`의 `env_bundle\.env` 항목,
  `onlyifdoesntexist`라 이미 키가 있으면 안 덮어씀) - launch.ps1이 숨김 프로세스로 도는데
  API 키 입력창(VB InputBox)이 그 숨김 상태에서 사용자에게 안 보이는 문제가 있어서(추정),
  일단 이 방법으로 우회함. **본인만 쓰는 개인용 배포일 때만 이 방식을 쓸 것** - 만든
  Setup.exe 안에 실제 Mouser API 키가 그대로 박혀 있어서, 다른 사람에게 그 파일을 주면 내
  키를 그대로 넘겨주는 셈이 됨. 불특정 다수에게 배포할 땐 `env_bundle/.env`를 빈 채로 두거나
  [Files]에서 이 줄을 빼고, 원래 방식대로(launch.ps1이 처음 실행 때 입력받는 방식) 되돌릴 것.

## 개인용으로 빌드하기 (내 API 키를 설치파일에 담기)
1. 이 폴더에 `env_bundle` 폴더를 만들고, 그 안에 `.env` 파일을 하나 만들어서 실제 키를 적음:
   ```
   MOUSER_API_KEY=여기에_내_실제_키
   ```
   (원본 프로젝트 루트의 `.env` 파일을 그대로 복사해도 됨.)
2. 빌드 작업 폴더의 `env_bundle/.env`도 함께 준비되도록 아래 절차의 1번에 포함시킬 것.
3. **주의**: 이렇게 만든 `Setup.exe`는 절대 다른 사람과 공유하지 말 것(내 API 키가 그대로
   들어있음). 불특정 다수에게 배포할 파일은 `env_bundle` 없이(또는 빈 `.env`로) 따로 빌드할 것.

## 빌드 절차 (원본 `../빌드방법.md`의 3~5단계와 동일한 틀)
1. 빌드 작업 폴더를 만들고:
   ```
   빌드폴더/
     setup.iss                    ← 이 폴더의 setup.iss
     app/
     assets/python-3.14.6-amd64.exe
     output/                      ← 원본과 달리 output/ 대신 setup.iss가 "00. 배포용"으로
                                     바로 뽑아내므로 없어도 됨(OutputDir이 절대경로로 지정돼 있음)
   ```
2. `app/`에 넣을 것 — **원본 빌드 목록(../빌드방법.md 2번)과 완전히 동일**하되, 딱 2개만 이
   폴더의 파일로 바꿔치기:
   - `datasheet/downloader.py` → 이 폴더의 `downloader.py`로 교체
   - `requirements.txt` → 이 폴더의 `requirements.txt`로 교체
   - (`start.vbs`/`launch.ps1`/`progress.ps1`/`setup_env.ps1`/`set_api_key.ps1`은 원본 그대로 —
     이 스크립트들엔 웹 검색 관련 코드가 없어서 안 바꿔도 됨)
3. Python 설치기를 `assets/`에 받기(원본 3번과 동일 명령).
4. 컴파일:
   ```bash
   "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" setup.iss
   ```
   → `C:\Users\Root\Desktop\클로드\00. 배포용\데이터시트다운로더Lite_설치.exe` 생성.

## 참고
- 버전을 올릴 땐 이 폴더의 `setup.iss`와 원본 `../setup.iss`의 `AppVersion`을 각각 따로 관리할 것
  (Lite가 원본보다 항상 늦게 갈라져 나오므로, 원본에 코드 수정이 생기면 이 폴더의 `downloader.py`
  에도 그 수정을 수동으로 반영해야 함 — 자동 동기화 안 됨).
- 원본 `datasheet/downloader.py`를 고칠 때(웹 검색 로직 자체가 아닌 공통 로직 — 예: Mouser
  다운로드 재시도 방식, 참고 링크 만드는 함수 등)는 이 폴더의 `downloader.py`에도 같은 수정을
  반영해줄 것. 두 파일이 공유하는 함수들: `download_pdf`/`_download_once`/
  `_reference_url_with_distributor_fallback`/`_mouser_search_url`/`_digikey_search_url`/
  `_general_search_url`/`resolve_existing_pdf`/`move_to_classified` 등.

# 데이터시트 다운로더 Lite — 빌드 방법

일반 배포판(`../빌드방법.md`)과 **딱 하나만 다릅니다**: 데이터시트 자동 다운로드 중
"웹(DuckDuckGo) 검색으로 보완" 단계가 빠져 있어요. Mouser/DigiKey 공식 API만 쓰고, 그걸로 못
찾으면 자동으로 다른 곳을 뒤지지 않고 Mouser/DigiKey/구글 검색 참고 링크 3개만 남겨서 사람이
직접 찾도록 안내합니다(2026-09-04 도입 — 불특정 다수에게 배포할 때, DuckDuckGo 자동 검색이
실제로 IP 차단으로 이어졌던 사고(원본 `CLAUDE.md` 결정 로그 참고)를 재현하지 않기 위해서예요).
DigiKey는 정식 OAuth2 API 호출이라(DDG처럼 화면을 긁는 게 아님) 이 위험이 없어서, 원본과
동일하게 Lite에도 포함돼 있어요(2026-09-20 추가).

## 이 폴더에 있는 것
- `downloader.py` — `datasheet/downloader.py`를 대체할 파일(웹 검색/스크래핑 관련 코드만 제거:
  `search_datasheet_urls`/`find_datasheet`/`_try_candidates`/DDG 재시도·차단 로직 등). **나머지
  로직은 원본과 100% 동기화 상태로 유지할 것**(2026-09-20 최신화 - DigiKey Product Information
  API v4 경로 추가, 202 Accepted 폴링, Mouser/DigiKey 공용 가벼운 다운로드+헤더, 브라우저 폴백
  재시도 1회 축소, ProductDetailUrl 폴백, Rate Limit 딜레이, PDF 잠금 확인 등 전부 포함됨).
  `datasheet/digikey_search.py`는 원본 파일을 손대지 않고 그대로 써요(정식 API 클라이언트라
  DDG 관련 코드가 아니므로 앱 폴더 전체 복사만으로 자동 포함됨 - 별도 Lite 버전 불필요).
  `BeautifulSoup`은 이제 DDG 파싱이 아니라 ProductDetailUrl 폴백에 쓰여서 **계속
  필요함**(아래 requirements.txt 참고).
- `requirements.txt` — 원본과 거의 동일하지만 `python-dotenv`는 뺌(API 키를 이제 `.env`가 아니라
  `User_API/` 폴더 방식으로 관리해서 더 이상 안 씀 - `utils/config.py` 참고). `beautifulsoup4`는
  위 이유로 **그대로 포함**.
- `setup.iss` — Inno Setup 스크립트. 원본과 다른 점: `AppName`="데이터시트 다운로더 Lite",
  `AppId` 별도 발급(원본과 동시 설치 가능하게), `DefaultDirName`=`DatasheetDownloaderLite`,
  `OutputBaseFilename`=`데이터시트다운로더Lite_설치`. **Mouser API 키 저장 방식은 원본과
  동일**(`{app}\User_API\` 폴더, 파일 하나당 API 하나 - `utils/config.USER_API_DIR`,
  2026-09-09부터 `.env` 방식 폐지).

  **API 키 번들링은 기본적으로 꺼져 있음(2026-09-09부터 안전한 기본값으로 변경)** - GitHub 등
  공개된 곳에 올려도 되는 "키 없는" 빌드가 기본 결과물이 되도록. `[Files]`의 `user_api_bundle\
  User_API\*` 항목이 `#ifdef BUNDLE_API_KEY` ... `#endif`로 감싸져 있어서, 컴파일할 때
  `BUNDLE_API_KEY`를 정의해줘야만(`ISCC /DBUNDLE_API_KEY setup.iss`) 그 자리에 실제 키가
  들어감. **그냥 `ISCC setup.iss`만 실행하면(플래그 없이) 키 없는 버전이 나옴** - 이게 남에게
  공유하거나 GitHub 같은 공개 저장소에 올려도 되는 버전. 아래 두 절차 참고.

## 개인용으로 빌드하기 (내 API 키를 설치파일에 담기)
1. 이 폴더 옆(빌드 작업 폴더)에 `user_api_bundle\User_API\` 폴더를 만들고, 그 안에 텍스트 파일을
   하나 만들어서 실제 키를 적음(파일 이름은 자유 - 프로그램은 내용의 KEY로 찾음):
   ```
   MOUSER_API_KEY=여기에_내_실제_키
   ```
   (원본 프로젝트 루트의 `User_API/*.txt` 파일을 그대로 복사해도 됨.)
2. 빌드 작업 폴더의 `user_api_bundle/User_API/*.txt`도 함께 준비되도록 아래 절차에 포함시킬 것.
3. 컴파일할 때 **반드시 `/DBUNDLE_API_KEY`를 붙일 것** (안 붙이면 키 없는 버전이 나옴 - 아래
   "빌드 절차" 참고).
4. **주의**: 이렇게 만든 `Setup.exe`는 절대 다른 사람과 공유하거나 공개 저장소에 올리지 말 것
   (내 API 키가 그대로 들어있음).

## 공개용(키 없음)으로 빌드하기 — GitHub 등에 올려도 되는 버전
1. `user_api_bundle` 폴더는 아예 없어도 되고, 있어도 상관없음(`/DBUNDLE_API_KEY`를 안 주면 그
   내용이 통째로 무시되므로).
2. 아래 "빌드 절차"에서 **플래그 없이** 컴파일:
   ```bash
   "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" setup.iss
   ```
3. 결과물에 `User_API\` 폴더가 아예 없음 → 첫 실행 시 `set_api_key.ps1`이 자동으로 API 키
   입력창을 띄움(원래 방식). 이 결과물은 GitHub Release 등 공개된 곳에 올려도 안전함.

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
   → 키 없는(공개용) `데이터시트다운로더Lite_설치.exe` 생성. **개인용(키 포함) 버전이
   필요하면** `/DBUNDLE_API_KEY`를 붙이고, 다른 사람과 겹치지 않게 `/F"다른파일명"`으로
   출력 파일명도 따로 줄 것(예: `ISCC /DBUNDLE_API_KEY /F"데이터시트다운로더Lite_설치_개인용"
   setup.iss`) - 안 그러면 방금 만든 공개용 파일을 덮어씀.
   → `C:\Users\Root\Desktop\클로드\00. 배포용\`에 생성됨.

## 참고
- 버전을 올릴 땐 이 폴더의 `setup.iss`와 원본 `../setup.iss`의 `AppVersion`을 각각 따로 관리할 것
  (Lite가 원본보다 항상 늦게 갈라져 나오므로, 원본에 코드 수정이 생기면 이 폴더의 `downloader.py`
  에도 그 수정을 수동으로 반영해야 함 — 자동 동기화 안 됨).
- **원본 `datasheet/downloader.py`를 고칠 때(DDG 웹 검색 로직 자체가 아닌 공통 로직)는 이 폴더의
  `downloader.py`에도 같은 수정을 반영해줄 것.** 두 파일이 공유하는(=DDG 관련이 아닌) 것들:
  `DownloadResult`/`sanitize_filename`/`dest_path_for_part`/`resolve_existing_pdf`/`has_pdf`/
  `is_pdf_locked`/`move_to_classified`/`_register_document_response_capture`/
  `_read_captured_body`/`_download_once`/`download_pdf`/`_header_get`/`_parse_retry_after`/
  `_poll_async_202`(202 폴링)/`MOUSER_PDF_HEADERS`/`_fetch_pdf_direct`/
  `_fetch_datasheet_url_from_product_page`/`_download_via_mouser_url`(Mouser 전용 가벼운
  다운로드+폴백)/`RATE_LIMIT_DELAY_RANGE`(Rate Limit 딜레이)/`_reference_url_with_distributor_fallback`/
  `_mouser_search_url`/`_digikey_search_url`/`_general_search_url`(참고 링크)/
  `download_datasheet_for_part`(①②만 남기고 ③ DDG 단계만 뺌 - 구조는 그대로 따라갈 것).
  DDG 전용이라 Lite에는 없는 것들: `search_datasheet_urls`/`find_datasheet`/`_try_candidates`/
  `_fetch_ddg_html`/`_is_captcha_page`/`_extract_real_url`/`_is_distributor`/
  `_manufacturer_tokens`/`_domain_main_label`/`_looks_official`/DDG 상태·잠금 변수들/
  `DISTRIBUTOR_DOMAINS`/`GENERIC_MFR_WORDS`/`KNOWN_DATASHEET_AGGREGATORS`/`_pick_reference_url`/
  `MAX_CANDIDATES_TO_TRY`.
- 마지막 동기화 확인: 2026-09-20(원본에 DigiKey Product Information API v4 다운로드 경로가
  추가되고, 프로토콜 상대 URL 버그 수정/브라우저 폴백 재시도 1회 축소 등 성능 수정이 반영된 뒤
  이 폴더로 재동기화함 - `HANDOFF_2026-09-20.md`, `CLAUDE.md` 결정 로그의 관련 항목들 참고).
  DigiKey API 키(`DIGIKEY_CLIENT_ID`/`DIGIKEY_CLIENT_SECRET`)는 Mouser와 마찬가지로 필수는
  아님 — 키가 없으면 `ui/main_window.py`가 `digikey_client=None`으로 이 단계를 조용히
  건너뛰고 Mouser → 참고 링크로 그대로 진행함.

# DigiKey API를 두 번째 다운로드 경로로 추가 — 설계 문서

- 날짜: 2026-09-19
- 관련 문서: [`소프트웨어_설계문서.md`](../../../소프트웨어_설계문서.md) §3.2(다운로드), [`CLAUDE.md`](../../../CLAUDE.md)(이 변경과는 무관 — 217F 분석 규칙 문서)
- 상태: 사용자 승인 완료(2026-09-19), 구현 대기

## 1. 배경 / 동기

지금은 데이터시트 다운로드가 ① 이미 있으면 스킵 → ② Mouser API → ③ DuckDuckGo 웹검색(브라우저 자동화) →
④ 참고 링크 3개만 남기고 실패, 순서로 동작한다(`datasheet/downloader.py`의
`download_datasheet_for_part()`). Mouser에 없는 부품은 곧바로 DDG 웹검색으로 넘어가는데, 이 단계는
브라우저를 새로 띄워야 해서 느리고(품번당 3~4초+), 과거 DDG가 이 프로그램의 요청 IP를 차단한 적도
있다(CLAUDE.md/설계문서에 기록된 실제 사고).

사용자가 DigiKey Product Information API v4의 Client ID/Secret을 이미 발급받아(Production 승인
완료) `User_API/JY_DIGIKEY_APT_KEY.txt`에 저장해뒀다. DigiKey는 Mouser와 마찬가지로 정식 유통사
API라 안정적이고, 검색 결과에 데이터시트 URL이 직접 포함되므로, Mouser 실패 시 DDG로 바로 가기 전에
한 단계 더 끼워 넣으면 자동 다운로드 성공률이 올라가고 DDG 의존도(=봇 차단 위험)를 줄일 수 있다.

## 2. DigiKey API 사양 (2026-09-19, 공식 문서/예제로 확인)

- 인증: OAuth2 **client_credentials** 그랜트(2-legged, 사용자 로그인 불필요)
  - `POST https://api.digikey.com/v1/oauth2/token`
  - `Content-Type: application/x-www-form-urlencoded`
  - 바디: `client_id`, `client_secret`, `grant_type=client_credentials`
  - 응답: `access_token`, `token_type=Bearer`, `expires_in`(약 600초 = 10분)
  - 출처: [DigiKey 2-Legged Authorization](https://developer.digikey.com/tutorials-and-resources/oauth-20-2-legged-flow)
- 검색: **Product Information API v4 Keyword Search**
  - `POST https://api.digikey.com/products/v4/search/keyword`
  - 헤더: `Authorization: Bearer <access_token>`, `X-DIGIKEY-Client-Id: <client_id>`,
    `Content-Type: application/json`, `Accept: application/json`
    (`X-DIGIKEY-Locale-Site`/`-Language`/`-Currency`는 선택이나, US/en/USD로 명시해 결과를 안정시킴)
  - 바디: `{"Keywords": "<품번>", "Limit": 10, "Offset": 0}`
  - 응답: `Products[]` 배열, 각 항목에 `ManufacturerProductNumber`, `Manufacturer.Name`
    (구현 중 실제 라이브 호출로 확인 — 사전 조사 문서엔 `Manufacturer.Value`로 나왔었으나 실제
    응답은 `{"Id":.., "Name":..}`), `DatasheetUrl`, `ProductUrl` 필드 포함
  - 출처: [DigiKey KeywordSearch 문서](https://developer.digikey.com/products/product-information-v4/productsearch/keywordsearch),
    실 사용 예제([briankhuu.com](https://briankhuu.com/blog/2024/09/17/playing-around-with-digikey-api/))
- 이 프로젝트에서 쓰는 앱은 **Production 승인 완료**(사용자 확인) → `sandbox-api.digikey.com`이 아니라
  **`api.digikey.com`**(운영 서버)로 요청한다. Sandbox는 고정 더미 데이터만 돌려준다.

## 3. 파일별 변경 사항

### 3.1 `User_API/JY_DIGIKEY_APT_KEY.txt` (데이터 파일, 코드 아님)
현재 `Client ID=...` / `Client Secret=...`로 돼 있는 키 이름을 프로젝트 관례(`MOUSER_API_KEY`처럼
대문자+언더스코어)에 맞춰 `DIGIKEY_CLIENT_ID=...` / `DIGIKEY_CLIENT_SECRET=...`로 바꾼다(사용자
승인, 값 자체는 그대로 유지). `.gitignore`가 이미 `User_API/`를 통째로 제외하므로 커밋되지 않는다.

### 3.2 `utils/config.py`
- `get_digikey_client_id()` / `get_digikey_client_secret()` 추가 — 기존 `get_mouser_api_key()`와
  완전히 같은 패턴(`get_api_key("DIGIKEY_CLIENT_ID")` 등을 감싸는 얇은 함수).
- `STATUS_SUCCESS_DIGIKEY = "성공 (DigiKey)"` 상태 문자열 추가(`STATUS_SUCCESS_MOUSER` 옆에).

### 3.3 `datasheet/digikey_search.py` (신규 파일)
`datasheet/search.py`의 `MouserClient`와 병렬 구조로 만든다.

```python
class DigiKeyClient:
    def __init__(self, client_id=None, client_secret=None):
        # 매번 새로 읽음(User_API 파일을 GUI에서 고치면 다음 배치부터 반영) — MouserClient와 동일 패턴.
        # client_id/client_secret가 없으면 ValueError (호출부가 이 경우 DigiKey 단계 자체를 건너뜀).

    def _ensure_token(self):
        # 캐시된 access_token이 있고 만료 30초 전이 아니면 그대로 재사용.
        # 아니면 POST /v1/oauth2/token 으로 새로 발급받아 (token, 만료시각) 캐시.

    def search_part(self, part_number, manufacturer_hint=None) -> dict | None:
        # 1) _ensure_token()
        # 2) POST /products/v4/search/keyword, Keywords=part_number, Limit=10
        # 3) 실패하면(품번 그대로 매칭 안 됨) Mouser처럼 특수문자 제거한 정규화 품번으로 한 번 더 시도
        # 4) Products[]에서 ManufacturerProductNumber를 정규화 비교해 정확히 일치하는 것만 인정
        #    (manufacturer_hint 있으면 그 제조사와 일치하는 것 우선 — Mouser의 _pick_exact_match와 동일 로직)
        # 5) 반환 shape을 MouserClient.search_part()와 맞춤:
        #    {"manufacturer_part_number", "manufacturer", "datasheet_url", "mouser_part_number": 없음}
```

정확매칭/정규화 로직(`_normalize_part_number`, `_pick_exact_match` 상당)은 `search.py`에 있는
것과 로직이 똑같으므로, 중복 대신 `search.py`의 `_normalize_part_number()`를(이름 앞 언더스코어를
떼서 `normalize_part_number()`로 공개) 그대로 두고 `digikey_search.py`가 import해서 쓴다.
`_pick_exact_match`는 응답 필드 이름이 Mouser(`ManufacturerPartNumber`)와 DigiKey
(`ManufacturerProductNumber`)로 달라서 공용화하지 않고, `digikey_search.py`에 같은 로직을 짧게
다시 구현한다(두 필드 이름 차이를 흡수하는 어댑터를 새로 만드는 것보다 단순 중복이 더 읽기 쉬움).

토큰 캐시는 **모듈 레벨이 아니라 인스턴스 레벨**로 둔다(`DownloadWorker.run()`이 배치 시작 시
`DigiKeyClient()`를 한 번만 만들고 그 인스턴스를 재사용 — `MouserClient`와 동일한 생명주기).

### 3.4 `datasheet/downloader.py`
- `_download_via_mouser_url(url, dest)`을 `_download_via_api_source_url(url, dest, headers=None)`로
  일반화(동작은 동일 — 가벼운 `requests` 시도 먼저, 실패하면 브라우저 `download_pdf()`로 폴백).
  `_download_via_mouser_url`은 이 함수를 `MOUSER_PDF_HEADERS`로 호출하는 얇은 래퍼로 남기거나
  호출부를 직접 바꿔도 됨(구현 시 더 자연스러운 쪽으로).
- `download_datasheet_for_part()` 시그니처에 `digikey_client: DigiKeyClient | None = None` 인자
  추가. Mouser 단계가 전부 실패한 뒤, DDG 웹검색 이전에:
  ```python
  if digikey_client is not None:
      try:
          dk_result = digikey_client.search_part(part_number, manufacturer_hint=manufacturer)
      except Exception as e:
          logger.log(f"  [디버그] DigiKey 검색 오류(건너뜀): {e}")
          dk_result = None
      if dk_result and dk_result.get("manufacturer"):
          manufacturer = dk_result["manufacturer"]
      if dk_result and dk_result.get("datasheet_url"):
          fail_reason = _download_via_api_source_url(dk_result["datasheet_url"], dest)
          if fail_reason is None:
              return DownloadResult(STATUS_SUCCESS_DIGIKEY, dest.name, None, manufacturer)
  ```
  (Mouser의 `product_detail_url` 스크레이핑 폴백 같은 건 안 만든다 — DigiKey keyword search
  응답은 `DatasheetUrl`을 바로 주므로 그 단계 자체가 불필요.)

### 3.5 `ui/main_window.py`
- `SUCCESS_STATUSES`에 `STATUS_SUCCESS_DIGIKEY` 추가(표 색/성공-실패 카운트가 이 상태도 성공으로 셈).
- `DownloadWorker.run()`이 배치 시작 시 `MouserClient()`처럼 `DigiKeyClient()`도 만든다. 단,
  **DigiKey 키가 없어도 배치를 중단하지 않는다** — `try/except ValueError`로 감싸서 실패하면
  `digikey_client = None` + 로그 한 줄("DigiKey API 키가 없어 이 단계는 건너뜁니다")만 남기고
  계속 진행. `_process_row()`가 `download_datasheet_for_part(part, hint, client, digikey_client)`로
  넘겨준다.

### 3.6 문서
`소프트웨어_설계문서.md` §3.2에 DigiKey 단계를 다음 문단으로 추가:
> ② Mouser 검색이 실패하면(품번을 못 찾았거나 DataSheetUrl이 없으면), ②-2 DigiKey Product
> Information API v4(OAuth2 client_credentials)로 같은 품번을 검색한다. DigiKey 키가
> `User_API/`에 없으면 이 단계는 조용히 건너뛴다(Mouser처럼 필수 아님). 그래도 실패하면 기존과
> 동일하게 ③ DDG 웹검색으로 넘어간다.

## 4. 오류 처리 / 우아한 성능저하

| 상황 | 동작 |
|---|---|
| `User_API/`에 DigiKey 키 파일 자체가 없음 | 배치 시작 시 1회 로그, 이후 모든 품번에서 DigiKey 단계 스킵(웹검색으로 바로) |
| 키는 있는데 인증 실패(401 등) | 그 요청만 실패 처리하고 로그, 다음 단계(DDG)로 계속 진행 — 배치 전체를 막지 않음 |
| 토큰 발급 성공, 검색에서 품번 못 찾음 | `search_part()`가 `None` 반환 → DDG로 진행(정상 동작) |
| 검색은 성공했지만 `DatasheetUrl`이 비어있음 | 마찬가지로 DDG로 진행 |
| DigiKey가 데이터시트 URL을 줬는데 다운로드(가벼운 요청+브라우저 폴백) 둘 다 실패 | 그 URL은 포기하고 DDG 웹검색으로 계속 진행(Mouser 실패 처리와 동일 패턴) |

이 설계의 핵심 원칙: **DigiKey는 어디까지나 "있으면 도움되는" 보조 경로**이며, 이 경로의 어떤 실패도
전체 다운로드 파이프라인을 막거나 중단시키지 않는다.

## 5. 테스트 계획

- `DigiKeyClient` 단위 테스트(mock `requests`): 토큰 발급 성공/실패, 토큰 캐시 재사용(두 번째
  호출에서 토큰 엔드포인트를 다시 안 부르는지), 토큰 만료 후 재발급, 키워드 검색 정확매칭/정규화
  재시도/제조사 힌트 우선순위(Mouser 테스트와 대칭 구성).
- `download_datasheet_for_part()`에 `digikey_client=None`을 넘겼을 때 기존 동작(Mouser→DDG)이
  회귀 없이 그대로인지 확인.
- `digikey_client`를 mock으로 넘겨서, Mouser 실패 → DigiKey 성공 시 `STATUS_SUCCESS_DIGIKEY`로
  끝나는지, DigiKey도 실패하면 여전히 DDG 단계로 넘어가는지 확인.
- 실제 키로 라이브 테스트 1건(사용자가 이미 분석해본 품번 중 Mouser에 없던 것으로, 있다면) —
  없으면 임의의 잘 알려진 부품(예: 흔한 저항/커패시터 품번)으로 실제 DigiKey 다운로드 성공까지 확인.

## 6. 범위 밖 (지금 안 함)

- Mouser의 `ProductDetailUrl` 스크레이핑 같은 2차 폴백(DigiKey 검색 응답이 이미 DatasheetUrl을
  직접 주므로 불필요).
- DigiKey API를 Mouser보다 먼저 시도하는 순서 변경(요청받지 않음 — 지금 그대로 Mouser 우선).
- Rate limit/재시도 고급 로직(Mouser도 별도로 없음 — 필요해지면 추후 별도 결정 로그로 추가).

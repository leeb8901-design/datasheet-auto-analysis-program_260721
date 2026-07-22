# 데이터시트 다운로드 실패 후 VBA 재시도 개선 설계

날짜: 2026-07-22

## 배경

전자부품 데이터시트 자동 다운로드 파이프라인은 다음 순서로 동작한다.

1. Mouser API 검색 → 데이터시트 URL 다운로드 시도
2. 실패하면 DuckDuckGo 웹 검색 → 제조사 공식 사이트로 추정되는 PDF 직링크 다운로드 시도
3. 그래도 실패하면 `데이터시트 링크` 컬럼에 참고 URL을 기록하고 `저장 경로`를 함께 남긴다.
4. 사용자는 이 결과가 담긴 Import 양식(`Import_양식.xlsm`)을 Excel에서 열고, 내장된 VBA 매크로
   (`DownloadFailedDatasheets`, `vba/datasheet_helper.bas`)를 실행해서 실패 건을 재시도한다.

이 흐름 자체는 이미 동작한다 (직전 세션에서 `openpyxl.load_workbook`에 `keep_vba=True`가 빠져
매크로가 저장 시 통째로 사라지던 버그를 수정했다 — [excel_writer.py](../../../excel/excel_writer.py)).

이번 설계는 그다음 단계, 즉 **VBA가 재시도해도 실패하는 비율을 낮추는 것**을 다룬다.

## 문제

실제로 `AD8030ARZ` (Analog Devices)로 재현한 결과, Mouser에서 못 찾고 웹 검색으로 공식 PDF
직링크(`analog.com/.../AD8029_8030_8040.pdf`)는 찾았지만, 다운로드 시도 자체가 `HTTP 403`으로
막혔다 (Akamai 봇 차단으로 추정, [downloader.py](../../../datasheet/downloader.py) 주석에도 이미
기록된 케이스). 이때 실패 후 Excel에 남는 링크는 **막혔던 그 PDF 직링크 그대로**라서, VBA가 같은
링크를 다시 열어도 같은 이유로 막힐 가능성이 높다.

## 목표

- 신규 유료 API 도입 없이, 지금 있는 Mouser + DuckDuckGo 검색 결과 안에서 성공률을 개선한다.
- VBA의 재시도 다운로드 요청에 Python 쪽과 동등한 헤더를 갖춘다.
- PDF 직링크가 막혔을 때, 같은 직링크를 반복하는 대신 **제조사 공식 제품/문서 페이지**를 대체
  경로로 제공해서 VBA가 그쪽을 열어보게 한다.
- 100% 자동 다운로드를 보장하지는 않는다 (Akamai 등 강한 봇 차단은 VBA만으로 못 뚫는 경우가
  있음을 사용자와 합의함). 목표는 "성공률 개선"이지 "완전 자동화 보장"이 아니다.

## 범위 밖

- "출력" 버튼이 만드는 최종 산출물 엑셀([output_builder.py](../../../excel/output_builder.py),
  Windchill 217F 매핑 관련)은 건드리지 않는다. VBA 도우미는 Import 양식에서만 동작한다.
- 외부 유료 검색/조회 API(DigiKey API, Google Custom Search 등) 추가는 하지 않는다.
- VBA 밖에서 동작하는 별도 프로그램(Python 브라우저 자동화 등) 호출은 하지 않는다 — 사용자가
  명시적으로 배제함. VBA는 Windows 내장 컴포넌트(WinHttp, ADODB.Stream)만 사용한다.

## 설계

### 1. Python: 랜딩 페이지 탐색 (`datasheet/downloader.py`)

`search_datasheet_urls`가 돌려주는 DuckDuckGo 검색 결과 URL 목록을 지금처럼 유통사 도메인
제외 후, 두 그룹으로 나눈다.

- `pdf_urls`: `.pdf`로 끝나는 링크 (지금과 동일)
- `page_urls`: 그 외 링크 (신규)

`find_datasheet`는 다음을 반환하도록 수정한다.

```
{
  "datasheet_url": <공식 PDF 직링크 또는 첫 PDF 링크 또는 None>,
  "landing_page": <공식 도메인의 첫 페이지 링크 또는 None>,
  "official": <datasheet_url이 공식 도메인인지>,
}
```

`landing_page` 선정은 기존 `_looks_official` / `_manufacturer_tokens` 로직을 `page_urls`에도
그대로 적용한다 (제조사 이름 토큰이 도메인에 포함되는지로 판별). 새 판별 로직을 만들지 않고
기존 함수를 재사용한다.

### 2. Python: 결과 전달 (`DownloadResult`, `download_datasheet_for_part`)

`DownloadResult`에 `landing_url: str | None = None` 필드를 추가한다. `download_datasheet_for_part`가
웹 검색 결과(`web_result`)를 얻은 시점부터는, PDF 다운로드 성공 여부와 무관하게 `web_result`에
`landing_page`가 있으면 항상 `DownloadResult.landing_url`에 채운다 (PDF 다운로드가 성공하면
`landing_url`은 그냥 무시되고 쓰이지 않는다 — 실패한 경우에만 의미가 있다).

### 3. Python: 엑셀 기록

- `utils/config.py`: `COL_LANDING_PAGE = "제품 페이지 링크"`를 추가하고 `RESULT_COLUMNS`에 포함한다.
  기존 `ExcelResultWriter._ensure_result_columns()`가 헤더에 없으면 자동으로 새 컬럼을 만들어주므로
  추가 마이그레이션 코드는 필요 없다.
- `excel/excel_writer.py`: `ExcelResultWriter.write_row(...)`가 `landing_url` 인자를 받아서, 값이 있으면
  `제품 페이지 링크` 셀에 텍스트+하이퍼링크(기존 `_HYPERLINK_FONT` 스타일 재사용)로 기록한다.
- `ui/main_window.py`: `DatasheetWorker.run()`이 `writer.write_row(...)` 호출 시
  `landing_url=result.landing_url`을 같이 넘긴다.
- `vba/Import_양식.xlsm` 마스터 템플릿 1행에도 `제품 페이지 링크` 헤더를 미리 넣어둔다 (지난 세션에
  고친 `keep_vba=True` 방식으로 안전하게 편집).

### 4. VBA: 헤더를 갖춘 재다운로드 (`vba/datasheet_helper.bas`)

`URLDownloadToFileA`(헤더 지정 불가)를 `WinHttp.WinHttpRequest.5.1` 기반 함수로 교체한다. 이 컴포넌트는
Windows 기본 제공이라 추가 설치가 필요 없다.

- 요청 헤더: Python [downloader.py](../../../datasheet/downloader.py)의 `DOWNLOAD_HEADERS`와 동일하게
  User-Agent(Chrome 124 문자열), Accept, Accept-Language, Referer(`scheme://host/`)를 설정한다.
- 응답을 `ADODB.Stream`(바이너리 모드)으로 받아 앞 4바이트가 `%PDF`인지 확인 후 파일로 저장한다
  (기존 `IsRealPdf` 로컬 파일 검사 로직은 그대로 재사용).
- 재시도 정책 (Python의 `download_pdf`와 톤을 맞춤):
  - HTTP 401/403, 또는 200이지만 `%PDF`가 아닌 응답 → 즉시 포기 (재시도 안 함)
  - 타임아웃/연결 오류/5xx/429 → 최대 2회, 2초 → 4초 대기 후 재시도 (`Application.Wait`)

### 5. VBA: 제품 페이지 폴백

직링크 재다운로드가 최종 실패하면:

- `제품 페이지 링크` 컬럼에 값이 있으면 **그 URL**을 `Application.FollowHyperlink`로 연다.
- 없으면 기존처럼 원래 PDF 링크를 연다 (하위 호환 — 이전 버전 Import 파일에도 안전하게 동작).
- 상태 값은 기존 `실패 (브라우저로 확인 필요)`를 그대로 쓴다 (구분이 꼭 필요하면 추후 논의).

## 기대 효과와 한계

- WinHttp 헤더 보강은 헤더 누락만으로 막히던 사이트에는 효과가 있지만, Python이 이미 Chrome
  위장(curl_cffi)으로 시도해서 막힌 경우(예: analog.com의 Akamai 차단)에는 VBA로도 못 뚫을
  가능성이 높다 — 참고용 개선이지 만능 해결책이 아니다.
- 제품 페이지 폴백은 정성적으로 다른 접근이라 성공 가능성이 있지만 100% 보장은 아니다. 최소한
  사람이 열었을 때 "차단된 파일 링크"가 아니라 "정상 제품 페이지"가 열리므로 수동 대응 시 수고가
  줄어드는 효과는 있다.
- 완전 자동화(사람 개입 0)는 이번 설계의 목표가 아니다.

## 테스트 계획

- `AD8030ARZ`로 전체 파이프라인 재실행 → `제품 페이지 링크` 컬럼에 analog.com 제품 페이지 URL이
  채워지는지, 처리 후에도 `Import_양식.xlsm`의 VBA 매크로가 손상 없이 유지되는지 확인한다
  (`zipfile`로 `vbaProject.bin` 존재 여부 확인).
- VBA 매크로의 실제 다운로드 재시도 실행은 Excel UI + 매크로 보안 동의가 필요해서 자동화된
  헤드리스 테스트로는 검증할 수 없다. 구현 후 사용자가 직접 Excel에서 매크로를 실행해 결과를
  확인해야 한다.

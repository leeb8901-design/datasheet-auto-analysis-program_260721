# old_downloader.md — 기존 코드 정리 문서 (리팩터링 참고용)

> **이 문서의 목적**: 지금 코드는 여러 세션(217F 매핑맵 방식 → PSA 방식)을 거치며 산재/레거시가
> 쌓인 상태다. 앞으로 **코딩 규칙을 새로 정하고 그 규칙에 맞게 코드를 재정비**할 때, "지금 뭐가
> 있고 뭘 하는지"를 매번 코드를 다시 훑지 않고 참고할 수 있도록 현재 상태를 스냅샷으로 정리한다.
> 이 문서 자체는 규칙 문서가 아니라 **현황 문서**다 — 무엇을 남기고 무엇을 버릴지는 재정비 시점에
> 결정한다.
>
> 원본 문서: [`CLAUDE.md`](CLAUDE.md)(217F 분석 규칙 — 일부 폐기됨), [`소프트웨어_설계문서.md`](소프트웨어_설계문서.md)
> (구조 설계 — 일부 항목 최신화 안 됨), [`HANDOFF_2026-07-30.md`](HANDOFF_2026-07-30.md),
> [`HANDOFF_2026-07-31.md`](HANDOFF_2026-07-31.md)(가장 최근 변경 이력). 이 문서는 위 4개 + 실제
> 코드를 대조해서 만들었다(2026-08-18 기준, 최신 커밋 `63e8f46`).

---

## 1. 프로그램이 하는 일

품번 리스트가 적힌 엑셀 하나("작업지" = `Data_list_217F.xlsx`)를 입력받아:

1. 품번+제조사로 데이터시트 PDF를 인터넷에서 검색·다운로드
2. PDF 텍스트를 규칙(키워드/정규식) 기반으로 분석해 MIL-HDBK-217F 대분류/소분류와 신뢰도 파라미터 값을 추출
3. GUI에서 사람이 검토·수정
4. 같은 작업지 엑셀의 `PSA 입력 파라미터` 시트에 결과를 기록

AI(LLM)는 실행 중 전혀 개입하지 않는다 — 전부 정규식/키워드 매칭 + 참고표(`data/*.json`) 기반이다.

---

## 2. 파이프라인 (엔드투엔드)

```
[작업지 엑셀 로딩]  excel/excel_reader.py
        ↓
[품번마다: 다운로드]  datasheet/downloader.py (+ datasheet/search.py: Mouser API)
        ↓  (성공 시)
[PDF 분석]  ai/pdf_parser.py → ai/pdf_text.py + ai/classifier.py + ai/field_extractor.py + ai/reference.py
        ↓
[결과를 표에 표시 + 엑셀에 즉시 기록]  ui/main_window.py:DatasheetWorker → excel/excel_writer.py
        ↓
[사람이 "검토" 버튼으로 확인/수정]  ui/analysis_dialog.py
        ↓
[PSA 시트에 파라미터 기록]  excel/psa_writer.py (excel_writer.write_part_params 경유)
```

병렬화: `ui/main_window.py`의 `DatasheetWorker`가 `ThreadPoolExecutor(max_workers=3)`로 품번을
동시 처리한다. 다운로드 1건당 브라우저(Chromium)를 새로 띄우므로 3개가 적정 균형점으로 정해짐.
같은 워크북 객체에 쓰는 부분만 `threading.Lock`으로 직렬화.

---

## 3. 파일별 상세 인벤토리

### 3.1 진입점

| 파일 | 줄수 | 역할 |
|---|---|---|
| `main.py` | 13 | `QApplication` 생성, `MainWindow` 실행. 로직 없음. |

### 3.2 `ui/` — 화면

| 파일 | 핵심 클래스/함수 | 역할 | 비고 |
|---|---|---|---|
| `ui/main_window.py` | `DatasheetWorker(QObject)` | 백그라운드 `QThread`에서 실행. `run()` → `ThreadPoolExecutor`로 `_process_row()` 병렬 실행 → 다운로드+분석+엑셀쓰기까지 전부 이 안에서 처리 | **가장 비대한 파일. UI 조립 + 워커 오케스트레이션 + 다운로드/분석 결과 매핑까지 한 파일에 혼재** |
| | `MainWindow(QMainWindow)` | 창 조립(`_build_ui`), 엑셀 로딩, 드래그앤드롭, 진행률/로그 표시, PDF 열기 | `_build_top_bar`/`_build_table`/`_build_progress_row`/`_build_log_panel`로 위젯 조립은 잘 쪼개져 있음 |
| `ui/analysis_dialog.py` | `AnalysisReviewDialog(QDialog)` | 분석 결과 검토창. 대분류/소분류 재지정, 필드값 편집, 확인 체크박스, 행 색(빨강/노랑/초록) | 검토 상태 색(RED/YELLOW/GREEN)은 `excel/mapping_colors.py`의 4색 규칙과 **이름은 겹치지만 완전히 다른 개념**(주의: 헷갈리기 쉬움) |
| `ui/dialogs.py` | `SheetColumnDialog(QDialog)` | 시트/컬럼 자동인식 실패 시 수동 선택 팝업 | `excel_reader`의 헤더 자동감지 로직과 함께 봐야 함 |

**스레드 안전성 패턴** (지켜지고 있음, 규칙화할 가치 있음): 백그라운드 스레드에서 Qt 위젯 메서드를
직접 호출하면 크래시 위험 — `logger.add_callback`에는 항상 `Signal.emit`만 연결하고, 위젯 메서드를
콜백으로 직접 등록하지 않는다 (`MainWindow.log_received` 참고).

### 3.3 `datasheet/` — 검색·다운로드

| 파일 | 핵심 함수 | 역할 |
|---|---|---|
| `datasheet/search.py` | `MouserClient.search_part()` | Mouser API로 제조사/데이터시트 URL 조회. 품번 정확 일치만 인정 |
| `datasheet/downloader.py` | `download_datasheet_for_part()` (전체 진입점) | ①기존 파일 스킵 → ②Mouser → ③DuckDuckGo 웹검색(`find_datasheet`) → ④실패 시 참고링크(`_pick_reference_url`) |
| | `_download_once()` | Playwright `page.route()`로 실제 응답 바이트 가로채기, `%PDF` 매직바이트로만 검증(헤더 불신) |
| | `download_pdf()` | 401/403은 즉시 포기, 5xx/429/타임아웃은 지수백오프 재시도(최대 `MAX_RETRY_DELAY=30초`) |
| | `search_datasheet_urls()` / `find_datasheet()` | DuckDuckGo HTML 스크레이핑 + 우선순위 정렬(공식도메인+pdf > 공식도메인 > mouser/digikey pdf > 나머지 pdf > 그 외 > 알려진 차단 도메인) |
| | 폴더 정리 | `staging_dest_path`(미분류) → 분석 후 `move_to_classified`(대분류/소분류 폴더로 이동) |

**부품 판매 사이트/데이터시트 애그리게이터 판정용 상수** (전부 `downloader.py` 안에 하드코딩):
`DISTRIBUTOR_DOMAINS`, `PREFERRED_DISTRIBUTOR_DOMAINS`, `KNOWN_BLOCKED_DOMAINS`,
`KNOWN_DATASHEET_AGGREGATORS`, `GENERIC_MFR_WORDS` — 전부 리스트/집합 상수로 파일 상단에 흩어져
있음. 도메인 판정 로직(`_is_distributor`, `_looks_official`, `_manufacturer_tokens`,
`_domain_main_label`)도 전부 이 한 파일 안에 있어 **재사용/테스트 단위로 분리되어 있지 않음**.

브라우저 자동화는 `scrapling.StealthyFetcher` 사용, `real_chrome=True`가 기본(시스템 Chrome 사용 —
Windows에서 번들 Chromium이 side-by-side 오류로 실행 안 되는 문제 회피).

### 3.4 `ai/` — 규칙 기반 분석

| 파일 | 핵심 함수 | 역할 |
|---|---|---|
| `ai/pdf_text.py` | `extract_text()` | `pdfplumber`로 앞 4페이지만 텍스트 추출 |
| `ai/classifier.py` | `classify()` | 대분류(`classify_category`)+소분류(`classify_subcategory`) 키워드 가중치 매칭. 대분류 키워드는 `CATEGORY_KEYWORDS` 딕셔너리(정규식+가중치), 소분류는 카테고리별로 다른 전략(`IC_SUBCATEGORY_KEYWORDS`/`OPTICAL_SUBCATEGORY_KEYWORDS`/`SEMICONDUCTOR_SUBCATEGORY_KEYWORDS` 하드코딩 + 나머지는 `subcat_params.json` 이름 매칭으로 폴백) |
| `ai/field_extractor.py` | `extract_field_values()` | "동의어 근처 40자 이내 숫자+단위" 정규식 매칭. `FIELD_SYNONYMS` 딕셔너리에 없는 필드는 아예 시도 안 함(글자값 필드는 이 방식으로 못 찾음 — 예: Package Type, Quality Level) |
| `ai/reference.py` | `parse_temp_range`, `classify_temp_range`, `resolve_quality_level`, `find_package_in_text`, `resolve_thermal_resistance`, `env_factor`/`temp_factor`/`convert_mtbf` | `data/*.json` 참고표 기반 판정. **온도 파싱이 이 파일에서 가장 복잡한 로직**(품번 숫자 오검출 방지용 정규식 앵커링) |
| `ai/pdf_parser.py` | `analyze_pdf()` | 위 4개를 묶는 오케스트레이터. `_apply_reference()`가 "빈 값일 때만" 참고표로 보완 |
| `ai/prompt.py` | `load_headers`, `load_subcat_params`, `get_fields_for_subcategory` | `data/*.json` 로더 + PTC자동/데이터시트불가 필드 집합(`PTC_AUTO_DETERMINED_FIELDS`, `UNKNOWN_FROM_DATASHEET_FIELDS`) 정의. **AI 프롬프트 템플릿(`PDF_ANALYSIS_PROMPT_TEMPLATE`)이 남아있지만 실제로는 어디서도 안 씀** (LLM 미개입 원칙과 모순되는 죽은 코드) |
| `ai/analysis_state.py` | `PartAnalysis`(dataclass) | 분석 결과 상자. `unresolved_field_names`/`unresolved_summary`/`is_fully_confirmed` |

`data/*.json` 로딩은 `ai/prompt.py`와 `ai/reference.py`에 **각자 따로** `DATA_DIR`/`_load` 캐시 로직이
있음(둘 다 `Path(__file__).resolve().parent.parent / "data"` 패턴을 중복 구현 — `ai/reference.py`는
`lru_cache`, `ai/prompt.py`는 매번 파일 오픈). **통합 후보.**

### 3.5 `excel/` — 엑셀 입출력 (⚠️ 레거시와 신규가 섞여있는 핵심 영역)

| 파일 | 상태 | 역할 |
|---|---|---|
| `excel/excel_reader.py` | **사용 중** | `read_part_list_sheet()`, `find_header_row()`(헤더가 1행이 아닐 수 있어 앞 15행 스캔), `read_custom_sheet()`(수동 선택용) |
| `excel/excel_writer.py` | **사용 중** | `ExcelResultWriter` — 작업지에 결과 기록(`WORKSHEET_RESULT_COLUMN_MAP`으로 매핑) + `write_part_params()`로 PSA 시트 기록 위임. `.xlsm`이면 `keep_vba=True` 필수(안 그러면 VBA 매크로 소실) |
| `excel/psa_writer.py` | **사용 중 (신규, 2026-07-31)** | PSA 시트 부품 행 추가. **색상 비교(`color_key`)로 "이 칸이 데이터시트값 대상인지"를 판정** — 셀 텍스트가 아니라 정의행의 채우기색이 범례의 "Datasheet" 스와치 색과 같은지로 판단하는 독특한 방식. `HEADER_ROW=9`, `SD_START=11(K열)` 등 매직넘버가 하드코딩됨 |
| `excel/mapping_colors.py` | **레거시 (폐기됐지만 파일 존속)** | 옛 4색 규칙(흰/회/보라/분홍) 상수. `diagnostics/self_check.py`가 아직 참조해서 못 지움 |
| `excel/mapping_template_builder.py` | **레거시** | 옛 "매핑맵" 시트(154개 서브카테고리 × 127컬럼) 생성 로직. `diagnostics/self_check.py`만 참조 |
| `excel/mapping_writer.py` | **레거시 — 사실상 죽은 코드** | 옛 매핑맵에 부품 값 쓰기(`MappingMapWriter`). **어디서도 import 안 됨** (grep 결과 self_check조차 안 씀) — HANDOFF 문서엔 "self_check가 참조 중"이라 적혀 있지만 실제로 `mapping_writer.py` 자체를 참조하는 곳은 없음, `mapping_template_builder`/`mapping_colors`만 참조됨. **삭제 후보 1순위.** |
| (삭제됨) `excel/output_builder.py`, `datasheet/annotator.py` | 파일 자체가 저장소에서 삭제됨(git 이력에는 있음) | 예전엔 별도 "출력지"(매핑맵 워크북) + PDF 스티키노트 주석을 만들었으나 2026-07-31 개편으로 폐지 |

**같은 "헤더 행 자동 감지" 로직이 `excel_reader._detect... (find_header_row)`와
`excel_writer._detect_header_row`에 거의 동일하게 두 번 구현되어 있음** — 미묘하게 다름
(reader는 `find_column(headers, PART_NUMBER_KEYWORDS)`로 헤더 문자열 전체를 비교, writer는
셀 값에 `any(k in ... )`로 부분 매칭). **통합 후보, 지금은 두 로직이 미묘히 달라 리팩터링 시 동작
차이에 주의.**

### 3.6 `tools/`, `diagnostics/`

| 파일 | 역할 |
|---|---|
| `tools/build_reference.py` | 엑셀(정본) → `data/*.json`(생성물) 변환. 엑셀 시트 안의 "앵커 텍스트"(예: `"구분"`, `"Package Type"`, `"To Environment"`)를 찾아 그 옆/아래 표를 파싱하는 방식 — **엑셀 레이아웃이 조금만 바뀌어도 깨지기 쉬운 파싱**(합의된 계약이 코드 주석 말고는 없음) |
| `diagnostics/self_check.py` | 개발자용 내부 점검 4종. **옛 매핑맵 색상 규칙(`mapping_colors`/`mapping_template_builder`)을 검증 대상으로 삼고 있어, 지금 실제로 쓰는 PSA 방식은 전혀 검증 안 함** — HANDOFF 문서의 TODO 3번("4색 규칙 잔재 정리")이 이 부분. GUI 미연동, 사용자 기능 아님. |

### 3.7 `utils/` — 공용 설정

| 파일 | 역할 |
|---|---|
| `utils/config.py` | 경로(`APP_DIR`, `DOWNLOAD_DIR`, `LOG_DIR`, `MAPPING_TEMPLATE_PATH`-레거시, `IMPORT_TEMPLATE_PATH`), 시트/컬럼 인식 키워드, 결과 컬럼명, 작업지 컬럼 매핑(`WORKSHEET_RESULT_COLUMN_MAP`), 상태 문자열 상수 전부가 한 파일에 혼재 |
| `utils/logger.py` | `Logger` 싱글턴(`logger = Logger()`). 파일 기록 + 콜백(GUI) 동시 전달. `threading.Lock`으로 파일쓰기 직렬화 |

`utils/config.py`에는 **더 이상 안 쓰는 레거시 상수도 섞여 있음** — 예: `MAPPING_TEMPLATE_PATH`
(옛 출력지 마스터 파일 경로, `output_builder.py` 삭제로 사용처 없음), `COL_ANALYSIS_STATUS`/
`COL_ERROR_MESSAGE`/`COL_UNRESOLVED_FIELDS`는 GUI 표시용으로는 쓰이지만
`WORKSHEET_RESULT_COLUMN_MAP`에는 빠져 있어(주석에 "여기 없는 결과는 작업지에 쓰지 않음"이라고
명시) 작업지에는 기록 안 되고 화면 표에만 표시됨 — **의도된 동작이지만 이름만 봐서는 헷갈리기 쉬움.**

### 3.8 `data/*.json` (생성물, 손으로 편집 금지)

`build_reference.py`가 `Data_list_217F.xlsx`에서 생성: `quality_by_temp.json`,
`thermal_resistance.json`, `env_conversion.json`, `temp_conversion.json`, `quality_allowed.json`,
`subcat_params.json`(97개 서브카테고리), `headers.json`(93컬럼, subcat_params에서 파생).

옛 154개 서브카테고리 체계의 흔적(`data/mapping_map_snapshot.json`, `data/parts_list_snapshot.json`,
`data/params124.json` 등 CLAUDE.md가 언급하는 파일들)은 **현재 `data/` 폴더 실물에는 없음** —
CLAUDE.md 자체가 최신화되지 않은 문서라는 뜻.

### 3.9 기타

- `vba/datasheet_helper.bas` — 자동 다운로드 막힌 부품을 위한 엑셀 매크로 백업 경로. **CP949 인코딩
  필수**(UTF-8로 저장하면 한글 깨짐), Excel에서 수동 재 임포트 필요(openpyxl로 매크로 소스 자체를
  안전하게 새로 쓸 방법 없음).
- `초기설정.ps1` / `초기설정.bat` / `프로그램_실행.bat` — 환경 셋업/실행 스크립트.
- `old/` — 과거 산출물(정리 후보로 보임, 내용 미검토).

---

## 4. 문서-코드 불일치 (재정비 시 "어느 쪽이 진실인지" 미리 알아둘 것)

| 항목 | 문서(CLAUDE.md/설계문서)가 말하는 것 | 실제 코드 |
|---|---|---|
| 색상 규칙 | 흰/회/보라/분홍 4색이 핵심 원칙 | **PSA 방식으로 대체됨.** 이제는 정의행 색이 "Datasheet 스와치 색과 같은가"만 이진 판정(`psa_writer.color_key`). 4색 코드는 `self_check`에만 남음 |
| 출력지 | 배치마다 새 엑셀(부품리스트+매핑맵) 생성 | **폐지.** 입력지=산출물, 같은 파일에 직접 씀 |
| PDF 주석 | `datasheet/annotator.py`가 스티키노트 삽입 | **파일 삭제됨.** 기능 자체가 없음 |
| 서브카테고리 수 | 154개(CLAUDE.md), `subcat_params.json` | **97개**(현재 `data/subcat_params.json`, PSA 시트 기준으로 재생성됨) |
| `data/params124.json`, `mapping_map_snapshot.json` 등 | CLAUDE.md 4번이 "반드시 재사용" 지시 | **`data/` 폴더에 실물 없음** |

**결론: 새 코딩 규칙 문서를 쓸 때 CLAUDE.md/소프트웨어_설계문서.md를 그대로 정본으로 삼지 말고,
이 문서 3번(실제 코드 인벤토리)과 대조해서 최신 상태만 반영할 것.**

---

## 5. 산재/중복 포인트 요약 (규칙화·리팩터링 우선순위 후보)

1. **레거시 매핑맵 3파일** (`mapping_colors.py`, `mapping_template_builder.py`, `mapping_writer.py`) —
   `mapping_writer.py`는 완전히 죽은 코드로 보임(사용처 없음, 재확인 후 삭제). 나머지 둘은
   `self_check.py`가 검증 로직으로만 씀 → self_check를 PSA 방식으로 다시 짜면 셋 다 삭제 가능.
2. **헤더 행 자동 감지 로직 중복** — `excel_reader.py`와 `excel_writer.py`에 각각 구현, 미묘하게
   다른 매칭 방식. 공용 유틸로 합칠 것.
3. **`data/*.json` 로더 중복** — `ai/prompt.py`와 `ai/reference.py`가 각자 `DATA_DIR`+로딩 로직을
   따로 구현. 하나로 통합 가능(예: `ai/data_store.py` 같은 공용 모듈).
4. **`ui/main_window.py`의 `DatasheetWorker`가 너무 많은 책임을 짐** — 다운로드 호출, 분석 호출,
   엑셀 쓰기 호출, 상태 문자열 조합, 폴더 이동까지 한 클래스/메서드(`_process_row`)에 몰려있음.
   재정비 시 "다운로드→분석→기록"을 별도 서비스 계층으로 뽑아내면 GUI와 완전히 독립적으로
   테스트 가능해짐(현재는 GUI 없이 배치 처리하는 CLI/테스트 경로가 없음).
5. **죽은 AI 프롬프트 템플릿** (`ai/prompt.py`의 `PDF_ANALYSIS_PROMPT_TEMPLATE`) — "AI는 실행 중
   개입하지 않는다"는 원칙과 모순되는 잔재. 실제 LLM 연동 계획이 없다면 삭제 후보.
6. **`utils/config.py`가 만능 서랍** — 경로/키워드/컬럼명/상태문자열 등 성격이 다른 설정이 전부 한
   파일. 레거시 상수(`MAPPING_TEMPLATE_PATH`)도 안 지워지고 남아있음.
7. **매직 넘버 하드코딩** — `psa_writer.py`의 `HEADER_ROW=9`, `SD_START=11` / `build_reference.py`의
   시트 이름·앵커 텍스트 문자열들이 코드 곳곳에 리터럴로 박혀 있음. 엑셀 레이아웃이 바뀌면 조용히
   깨질 수 있는 지점들.
8. **도메인/사이트 판정 로직이 `downloader.py` 한 파일에 집중** — 유통사/애그리게이터/차단도메인
   목록과 판정 함수가 전부 이 파일 안에서만 쓰이고 재사용 경계가 없음. 데이터시트 소스 우선순위
   정책을 바꾸고 싶을 때 이 파일 전체를 이해해야 함.
9. **한/영 혼용 네이밍** — 함수/변수는 영어, 엑셀 컬럼명/상태문자열/시트명은 한국어 리터럴로
   코드 안에 직접 박혀 있음(`utils/config.py`에 모아두긴 했으나, `psa_writer.py`의
   `PSA_SHEET_NAME = "PSA 입력 파라미터"`처럼 config를 거치지 않고 파일 자체에 리터럴을 또 선언한
   경우도 있음).

---

## 6. 알려진 버그/주의사항 (반드시 유지해야 하는 동작)

- **LibreOffice/recalc 재저장 절대 금지** — 과거 셀 색상이 통째로 사라진 사고 이력(여러 문서에서
  반복 경고). `openpyxl`로 값/서식만 쓰고 그대로 저장.
- `.xlsm` 저장 시 `keep_vba=True` 필수 — 안 그러면 VBA 매크로(`datasheet_helper.bas`) 소실.
- `IC_SUBCATEGORY_KEYWORDS`의 `and`/`or`/`nor` 단독 단어는 절대 매칭 패턴에 넣지 않음(법적 고지문
  등에 흔해서 오분류 유발 이력 있음) — `classifier.py` 주석 참고.
- PDF 다운로드 검증은 HTTP 헤더(`content-type`)를 신뢰하지 않고 `%PDF` 매직바이트로만 판단(Chrome
  내장 뷰어가 가짜 HTML 래퍼를 정직한 `application/pdf` 헤더로 감싸는 사고 이력).
- Playwright 동기 API를 이벤트 콜백(`page.on(...)`) 안에서 바로 부르면 앱이 멈출 수 있음 —
  콜백에선 참조만 저장하고 실제 대기 호출은 일반 흐름(`page_action`)에서.
- 백그라운드 스레드에서 Qt 위젯 메서드 직접 호출 금지(Signal/Slot만 사용) — 과거 트레이스백 없는
  크래시 이력.
- PSA 재분석 시 같은 부품이 중복 행으로 추가됨(dedupe 로직 없음, HANDOFF TODO).
- θJC/θJA 선택이 Temperature Rise 계산까지 일관되게 반영되는지 미검증(HANDOFF TODO).

---

## 7. 실행 환경

- `pip install -r requirements.txt`(`requests`, `python-dotenv`, `openpyxl`, `beautifulsoup4`,
  `PySide6`, `pdfplumber`, `pymupdf`, `scrapling[fetchers]`)
- `.env`에 `MOUSER_API_KEY` 필요(git 미포함)
- 다운로드는 시스템에 설치된 **실제 Google Chrome** 사용(`SCRAPLING_REAL_CHROME=0`으로 번들
  브라우저 강제 가능)
- `data/*.json` 재생성: `python tools/build_reference.py`(입력 엑셀 수정 후 매번)
- 실행: `프로그램_실행.bat` 또는 `python main.py`

---

## 8. 이 문서를 쓸 때 참고한 방법

`git log`가 아니라 **각 `.md` 인계 문서 + 실제 소스 전체(`ai/`, `excel/`, `ui/`, `datasheet/`,
`utils/`, `tools/`, `diagnostics/`, `main.py`)를 직접 읽고 대조**해서 작성했다. 코드가 실제로 하는
일과 문서가 말하는 것이 다를 때는 **코드를 우선**했고, 문서-코드 불일치는 4번 표에 별도로 남겼다.

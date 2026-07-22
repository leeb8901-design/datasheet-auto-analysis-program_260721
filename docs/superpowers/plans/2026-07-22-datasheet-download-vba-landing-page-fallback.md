# 데이터시트 다운로드 VBA 폴백 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자동 다운로드가 실패했을 때 Excel에 남기는 정보를 개선해서, VBA 도우미 매크로가 (a) Python과 동등한 헤더로 직링크를 재시도하고 (b) 그래도 막히면 막혔던 PDF 직링크 대신 제조사 "제품 페이지"를 열도록 만든다.

**Architecture:** Python 쪽(`datasheet/downloader.py`)의 웹 검색 결과에서 PDF 직링크와는 별도로 "제품/문서 페이지" 링크를 추출해 `DownloadResult.landing_url`로 흘려보내고, 이를 새 Excel 컬럼(`제품 페이지 링크`)에 기록한다. VBA 매크로(`vba/datasheet_helper.bas`)는 `URLDownloadToFileA` 대신 헤더를 붙일 수 있는 `WinHttp.WinHttpRequest.5.1`로 재다운로드를 시도하고, 실패 시 새 컬럼의 제품 페이지를 브라우저로 연다.

**Tech Stack:** Python 3.14 (`.venv`), openpyxl, PySide6, pytest 9.1.1 (이미 `.venv`에 설치됨), VBA (Windows 내장 WinHttp/ADODB COM 컴포넌트).

## Global Constraints

- 신규 유료/외부 API 추가 금지 (Mouser API, DuckDuckGo 웹 검색만 사용).
- VBA 다운로드 로직은 Windows 내장 컴포넌트(WinHttp, ADODB.Stream)만 사용 — 외부 프로그램(Python 스크립트 등) 호출 금지. 사용자가 이전 대화에서 명시적으로 요구한 제약.
- `excel/output_builder.py`(최종 Windchill 매핑 산출물)는 이번 작업 범위 밖 — 수정하지 않는다.
- 구버전 Import 파일(신규 "제품 페이지 링크" 컬럼이 없는 파일)에서도 VBA 매크로가 에러 없이 동작해야 한다 (하위 호환).
- `.xlsm` 파일을 Python으로 열고 저장할 때는 반드시 `keep_vba=True`를 써야 한다 (이미 `excel/excel_writer.py`에 적용된 규칙 — 빠뜨리면 VBA 매크로가 저장 시 사라짐).
- 100% 자동 다운로드는 목표가 아니다. Akamai급 봇 차단은 이 개선으로도 못 뚫을 수 있음을 사용자와 합의함.

---

### Task 1: `find_datasheet`가 PDF 직링크와 "제품 페이지"를 구분해서 반환

**Files:**
- Create: `tests/test_downloader.py`
- Modify: `datasheet/downloader.py:229-244` (`find_datasheet` 함수)
- Create (setup): `.gitignore` 에 `.pytest_cache/` 한 줄 추가

**Interfaces:**
- Produces: `find_datasheet(part_number, manufacturer=None, max_results=10) -> dict | None`.
  반환 dict는 이제 `{"datasheet_url": str | None, "landing_page": str | None, "official": bool}` 형태
  (기존 `"source_page"` 키는 제거되고 `"landing_page"`로 대체됨 — 이 함수의 리턴값은 `datasheet/downloader.py`
  내부(`download_datasheet_for_part`)에서만 소비되므로 다른 파일은 영향받지 않음).

- [ ] **Step 1: `.gitignore`에 pytest 캐시 제외 추가**

`.gitignore` 파일에서 `.vscode/` 줄 다음에 아래 줄을 추가한다:

```
.pytest_cache/
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_downloader.py` 파일을 새로 만든다:

```python
from datasheet import downloader


def test_find_datasheet_returns_distinct_landing_page(monkeypatch):
    urls = [
        "https://www.analog.com/media/en/technical-documentation/data-sheets/AD8029_8030_8040.pdf",
        "https://www.analog.com/en/products/ad8030.html",
        "https://someblog.example.com/ad8030-review",
    ]
    monkeypatch.setattr(downloader, "search_datasheet_urls", lambda *a, **k: urls)

    result = downloader.find_datasheet("AD8030ARZ", manufacturer="Analog Devices")

    assert result["datasheet_url"] == urls[0]
    assert result["landing_page"] == "https://www.analog.com/en/products/ad8030.html"
    assert result["official"] is True


def test_find_datasheet_no_pdf_found_falls_back_to_first_page(monkeypatch):
    urls = ["https://www.ti.com/product/TL072", "https://example.com/other"]
    monkeypatch.setattr(downloader, "search_datasheet_urls", lambda *a, **k: urls)

    result = downloader.find_datasheet("TL072", manufacturer="Texas Instruments")

    assert result["datasheet_url"] is None
    assert result["landing_page"] == "https://www.ti.com/product/TL072"
    assert result["official"] is False


def test_find_datasheet_no_official_landing_page_falls_back_to_first_page_url(monkeypatch):
    urls = ["https://unofficial-blog.example.com/x.pdf", "https://unofficial-blog.example.com/x"]
    monkeypatch.setattr(downloader, "search_datasheet_urls", lambda *a, **k: urls)

    result = downloader.find_datasheet("X123", manufacturer="Analog Devices")

    assert result["datasheet_url"] == urls[0]
    assert result["landing_page"] == "https://unofficial-blog.example.com/x"
    assert result["official"] is False


def test_find_datasheet_no_search_results_returns_none(monkeypatch):
    monkeypatch.setattr(downloader, "search_datasheet_urls", lambda *a, **k: [])

    assert downloader.find_datasheet("XYZ999") is None
```

- [ ] **Step 3: 테스트 실행해서 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_downloader.py -v`
Expected: FAIL — `KeyError: 'landing_page'` (아직 함수가 이 키를 안 돌려주므로)

- [ ] **Step 4: `find_datasheet` 구현 수정**

`datasheet/downloader.py`의 기존 `find_datasheet` 함수(228~244행)를 아래로 통째로 교체한다:

```python
def find_datasheet(part_number, manufacturer=None, max_results=10):
    urls = search_datasheet_urls(part_number, manufacturer, max_results=max_results)
    if not urls:
        return None

    tokens = _manufacturer_tokens(manufacturer)
    pdf_urls = [u for u in urls if u.lower().endswith(".pdf")]
    page_urls = [u for u in urls if not u.lower().endswith(".pdf")]

    official_pdf = next((u for u in pdf_urls if _looks_official(u, tokens)), None)
    datasheet_url = official_pdf or (pdf_urls[0] if pdf_urls else None)

    # 막힌 PDF 직링크 대신 열어볼 "제품/문서 페이지" - 같은 제조사 도메인을 우선하고,
    # 없으면 검색 결과 중 PDF가 아닌 첫 링크로 대체해요.
    official_page = next((u for u in page_urls if _looks_official(u, tokens)), None)
    landing_page = official_page or (page_urls[0] if page_urls else None)

    return {
        "datasheet_url": datasheet_url,
        "landing_page": landing_page,
        "official": official_pdf is not None,
    }
```

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_downloader.py -v`
Expected: 4 개 테스트 모두 PASS

- [ ] **Step 6: 커밋**

```bash
git add .gitignore tests/test_downloader.py datasheet/downloader.py
git commit -m "feat: find_datasheet가 PDF 직링크와 제품 페이지를 구분해서 반환"
```

---

### Task 2: `DownloadResult.landing_url`을 `download_datasheet_for_part`에서 채우기

**Files:**
- Modify: `datasheet/downloader.py:62-70` (`DownloadResult` dataclass)
- Modify: `datasheet/downloader.py:250-303` (`download_datasheet_for_part` 함수)
- Modify: `tests/test_downloader.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 1의 `find_datasheet(...) -> {"datasheet_url", "landing_page", "official"}`.
- Produces: `DownloadResult` dataclass에 `landing_url: str | None = None` 필드 추가 (6번째 필드, 기존
  `reference_url` 다음). Task 3/4가 `result.landing_url`로 이 값을 읽는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_downloader.py` 파일 끝에 아래 테스트들을 추가한다:

```python
class _StubMouser:
    def __init__(self, result=None):
        self._result = result

    def search_part(self, part_number, manufacturer_hint=None):
        return self._result


def test_download_datasheet_for_part_sets_landing_url_on_web_download_failure(monkeypatch, tmp_path):
    downloader.set_download_dir(tmp_path)
    monkeypatch.setattr(downloader, "download_pdf", lambda url, dest, max_retries=3: "HTTP 403")
    monkeypatch.setattr(
        downloader,
        "find_datasheet",
        lambda part, manufacturer=None, max_results=10: {
            "datasheet_url": "https://www.analog.com/blocked.pdf",
            "landing_page": "https://www.analog.com/en/products/ad8030.html",
            "official": True,
        },
    )

    result = downloader.download_datasheet_for_part("AD8030ARZ", None, _StubMouser())

    assert result.status == downloader.STATUS_FAILED
    assert result.reference_url == "https://www.analog.com/blocked.pdf"
    assert result.landing_url == "https://www.analog.com/en/products/ad8030.html"


def test_download_datasheet_for_part_falls_back_to_landing_page_when_no_pdf_found(monkeypatch, tmp_path):
    downloader.set_download_dir(tmp_path)
    monkeypatch.setattr(
        downloader,
        "find_datasheet",
        lambda part, manufacturer=None, max_results=10: {
            "datasheet_url": None,
            "landing_page": "https://www.ti.com/product/TL072",
            "official": False,
        },
    )

    result = downloader.download_datasheet_for_part("TL072", "Texas Instruments", _StubMouser())

    assert result.status == downloader.STATUS_FAILED
    assert result.error == "PDF 직링크를 찾지 못함"
    assert result.reference_url == "https://www.ti.com/product/TL072"
    assert result.landing_url == "https://www.ti.com/product/TL072"


def test_download_datasheet_for_part_mouser_success_has_no_landing_url(monkeypatch, tmp_path):
    downloader.set_download_dir(tmp_path)
    monkeypatch.setattr(downloader, "download_pdf", lambda url, dest, max_retries=3: None)

    result = downloader.download_datasheet_for_part(
        "NL27WZ08USG-Q",
        None,
        _StubMouser(result={"manufacturer": "onsemi", "datasheet_url": "https://www.onsemi.com/x.pdf"}),
    )

    assert result.status == downloader.STATUS_SUCCESS_MOUSER
    assert result.landing_url is None
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_downloader.py -v`
Expected: 새 3개 테스트 FAIL — `TypeError: __init__() got an unexpected keyword argument` 또는
`AttributeError: 'DownloadResult' object has no attribute 'landing_url'`

- [ ] **Step 3: `DownloadResult`에 필드 추가**

`datasheet/downloader.py`의 `DownloadResult` dataclass(62~70행)를 아래로 교체한다:

```python
@dataclass
class DownloadResult:
    # 부품 하나를 처리한 결과를 담는 상자예요.
    status: str  # utils.config의 STATUS_* 값 중 하나
    filename: str | None  # 저장된 파일 이름 (성공/이미있음일 때)
    error: str | None  # 실패 사유 (실패했을 때)
    manufacturer: str | None  # 확인된 제조사 이름
    reference_url: str | None = None  # 자동 다운로드는 실패했지만 참고할 만한 링크
    landing_url: str | None = None  # 실패했을 때, 막힌 직링크 대신 열어볼 만한 제조사 제품/문서 페이지
```

- [ ] **Step 4: `download_datasheet_for_part`가 `landing_url`을 채우도록 수정**

`datasheet/downloader.py`의 `download_datasheet_for_part` 함수(250~303행) 중, `# ③ 웹(DuckDuckGo)
검색으로 보완` 주석 아래 부분(283행부터 끝까지)을 아래로 교체한다:

```python
    # ③ 웹(DuckDuckGo) 검색으로 보완
    try:
        web_result = find_datasheet(part_number, manufacturer)
    except Exception as e:
        return DownloadResult(STATUS_FAILED, None, f"웹 검색 오류: {e}", manufacturer)

    landing_url = web_result.get("landing_page") if web_result else None

    if web_result and web_result.get("datasheet_url"):
        fail_reason = download_pdf(web_result["datasheet_url"], dest)
        if fail_reason is None:
            return DownloadResult(STATUS_SUCCESS_WEB, dest.name, None, manufacturer)
        return DownloadResult(
            STATUS_FAILED,
            None,
            f"웹 다운로드 실패: {fail_reason}",
            manufacturer,
            web_result["datasheet_url"],
            landing_url,
        )

    if landing_url:
        return DownloadResult(
            STATUS_FAILED, None, "PDF 직링크를 찾지 못함", manufacturer, landing_url, landing_url
        )

    reason = mouser_error or "Mouser/웹 모두에서 찾지 못함"
    return DownloadResult(STATUS_FAILED, None, reason, manufacturer)
```

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_downloader.py -v`
Expected: 7개 테스트 모두 PASS

- [ ] **Step 6: 커밋**

```bash
git add datasheet/downloader.py tests/test_downloader.py
git commit -m "feat: DownloadResult에 landing_url 추가하고 실패 경로에서 채움"
```

---

### Task 3: 새 Excel 컬럼 `제품 페이지 링크` 추가 (config + writer)

**Files:**
- Modify: `utils/config.py:39-55`
- Modify: `excel/excel_writer.py` (전체 파일, 현재 86줄)
- Create: `tests/test_excel_writer.py`

**Interfaces:**
- Consumes: Task 2의 `DownloadResult.landing_url`.
- Produces: `utils.config.COL_LANDING_PAGE = "제품 페이지 링크"` (Task 4가 이 이름으로 값을 씀).
  `ExcelResultWriter.write_row(row_index, values, link_path=None, reference_url=None, landing_url=None)`
  — `landing_url`이 있으면 `COL_LANDING_PAGE` 셀에 텍스트+하이퍼링크로 기록.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_excel_writer.py` 파일을 새로 만든다:

```python
import openpyxl

from excel.excel_writer import ExcelResultWriter
from utils.config import COL_DATASHEET_LINK, COL_DOWNLOAD_STATUS, COL_LANDING_PAGE


def _make_input_workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "부품리스트"
    ws.append(["No.", "품번", "제조사"])
    ws.append([1, "AD8030ARZ", ""])
    wb.save(path)
    wb.close()


def test_write_row_sets_landing_page_hyperlink(tmp_path):
    path = tmp_path / "import.xlsx"
    _make_input_workbook(path)

    writer = ExcelResultWriter(str(path), "부품리스트")
    writer.write_row(
        2,
        {
            COL_DOWNLOAD_STATUS: "실패",
            COL_DATASHEET_LINK: "https://www.analog.com/blocked.pdf",
            COL_LANDING_PAGE: "https://www.analog.com/en/products/ad8030.html",
        },
        reference_url="https://www.analog.com/blocked.pdf",
        landing_url="https://www.analog.com/en/products/ad8030.html",
    )
    writer.save()
    writer.close()

    wb = openpyxl.load_workbook(path)
    ws = wb["부품리스트"]
    col = writer.column_map[COL_LANDING_PAGE]
    cell = ws.cell(row=2, column=col)
    assert cell.value == "https://www.analog.com/en/products/ad8030.html"
    assert cell.hyperlink.target == "https://www.analog.com/en/products/ad8030.html"
    wb.close()


def test_write_row_skips_landing_hyperlink_when_no_landing_url(tmp_path):
    path = tmp_path / "import.xlsx"
    _make_input_workbook(path)

    writer = ExcelResultWriter(str(path), "부품리스트")
    writer.write_row(2, {COL_LANDING_PAGE: ""}, landing_url=None)
    writer.save()
    writer.close()

    wb = openpyxl.load_workbook(path)
    ws = wb["부품리스트"]
    col = writer.column_map[COL_LANDING_PAGE]
    cell = ws.cell(row=2, column=col)
    assert cell.hyperlink is None
    wb.close()
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_excel_writer.py -v`
Expected: FAIL — `ImportError: cannot import name 'COL_LANDING_PAGE'`

- [ ] **Step 3: `utils/config.py`에 컬럼 상수 추가**

`utils/config.py`의 42~55행(`COL_SAVE_PATH`와 `RESULT_COLUMNS` 정의 부분)을 아래로 교체한다:

```python
COL_SAVE_PATH = "저장 경로"  # 이 부품의 PDF가 저장되어야 할 정확한 경로 (VBA 도우미가 이 칸에 저장해요).
# 실패 시, 막힌 PDF 직링크 대신 열어볼 만한 제조사 제품/문서 페이지. VBA 도우미가 직링크 재시도에
# 실패하면 이 칸을 읽어서 브라우저로 열어요 (직링크를 반복하는 것보다 통과할 가능성이 더 커요).
COL_LANDING_PAGE = "제품 페이지 링크"
RESULT_COLUMNS = [
    COL_DOWNLOAD_STATUS,
    COL_ANALYSIS_STATUS,
    COL_DATASHEET_LINK,
    COL_ERROR_MESSAGE,
    COL_UNRESOLVED_FIELDS,
    COL_SAVE_PATH,
    COL_LANDING_PAGE,
]
```

- [ ] **Step 4: `excel/excel_writer.py`의 `write_row` 수정**

`excel/excel_writer.py` 전체를 아래로 교체한다:

```python
# 처리 결과(다운로드 상태, 분석 상태 등)를 원본 엑셀 파일에 다시 써넣는 파일이에요.

from pathlib import Path

import openpyxl
from openpyxl.styles import Font

from utils.config import COL_DATASHEET_LINK, COL_LANDING_PAGE, RESULT_COLUMNS

# 엑셀에서 링크처럼 보이도록 파란색 밑줄 글씨체를 만들어둬요.
_HYPERLINK_FONT = Font(color="0563C1", underline="single")


class ExcelResultWriter:
    """엑셀 파일을 한 번 열어두고, 행마다 결과를 채워 넣은 뒤 저장하는 역할을 해요."""

    def __init__(self, path: str, sheet_name: str):
        self.path = path
        self.sheet_name = sheet_name
        # read_only가 아니라 진짜로 "쓰기"가 가능한 모드로 열어요.
        # .xlsm(매크로 포함) 파일은 keep_vba=True로 열어야 해요. 이거 없이 열고 저장하면
        # openpyxl이 VBA 프로젝트(datasheet_helper.bas 매크로)를 통째로 지워버려서, 나중에
        # Import 양식에서 다운로드 도우미 매크로를 실행하려 해도 매크로 자체가 사라져 있는
        # 문제가 있었어요.
        keep_vba = str(path).lower().endswith(".xlsm")
        self.wb = openpyxl.load_workbook(path, keep_vba=keep_vba)
        self.ws = self.wb[sheet_name]
        self.column_map = self._ensure_result_columns()

    def _ensure_result_columns(self) -> dict[str, int]:
        # 제목 줄(1행)에 이미 있는 컬럼 이름과 번호를 읽어와요.
        header_row = 1
        headers: dict[str, int] = {}
        max_col = self.ws.max_column
        for col in range(1, max_col + 1):
            value = self.ws.cell(row=header_row, column=col).value
            if value:
                headers[str(value).strip()] = col

        # 결과 컬럼(다운로드 상태 등)이 없으면 새로 만들어요.
        next_col = max_col + 1
        for name in RESULT_COLUMNS:
            if name not in headers:
                self.ws.cell(row=header_row, column=next_col, value=name)
                headers[name] = next_col
                next_col += 1

        self.wb.save(self.path)
        return headers

    def write_row(
        self,
        row_index: int,
        values: dict[str, str],
        link_path: Path | None = None,
        reference_url: str | None = None,
        landing_url: str | None = None,
    ):
        # values 예: {"다운로드 상태": "성공 (Mouser)", "데이터시트 링크": "AD8030ARZ.pdf"}
        # link_path를 같이 주면, "데이터시트 링크" 칸이 그 로컬 파일을 여는 클릭 가능한 링크가 돼요.
        # (다운로드 성공 시) link_path가 없고 reference_url이 있으면, 같은 "데이터시트 링크" 칸이
        # 대신 그 웹 페이지를 여는 링크가 돼요. landing_url이 있으면 "제품 페이지 링크" 칸이 그
        # 제조사 제품/문서 페이지를 여는 링크가 돼요 (VBA 도우미가 직링크 재시도 실패 시 이 칸을
        # 읽어서 대신 열어요 — datasheet_helper.bas 참고).
        for key, value in values.items():
            col = self.column_map.get(key)
            if not col:
                continue
            cell = self.ws.cell(row=row_index, column=col, value=value)
            if key == COL_DATASHEET_LINK:
                if link_path is not None:
                    # 일반 윈도우 경로(C:\...) 형태로 넣어야 엑셀에서 클릭했을 때 바로 열려요.
                    # file:/// 형태(URI)로 넣으면 경로에 한글이 있을 때 인코딩이 깨져서 "파일을 열 수
                    # 없다"는 오류가 나는 경우가 있어서, 그냥 실제 경로 문자열을 그대로 써요.
                    cell.hyperlink = str(link_path.resolve())
                    cell.font = _HYPERLINK_FONT
                elif reference_url:
                    cell.hyperlink = reference_url
                    cell.font = _HYPERLINK_FONT
            elif key == COL_LANDING_PAGE and landing_url:
                cell.hyperlink = landing_url
                cell.font = _HYPERLINK_FONT

    def save(self):
        # 지금까지의 변경사항을 실제 파일에 저장해요. (Excel 자동 저장 요구사항)
        self.wb.save(self.path)

    def close(self):
        self.wb.close()
```

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_excel_writer.py -v`
Expected: 2개 테스트 모두 PASS

- [ ] **Step 6: 커밋**

```bash
git add utils/config.py excel/excel_writer.py tests/test_excel_writer.py
git commit -m "feat: 제품 페이지 링크 컬럼을 Excel 결과 기록에 추가"
```

---

### Task 4: `DatasheetWorker`가 `landing_url`을 엑셀에 전달하도록 연결

**Files:**
- Modify: `ui/main_window.py:118-131`
- Create: `tests/test_main_window_worker.py`

**Interfaces:**
- Consumes: Task 2의 `DownloadResult.landing_url`, Task 3의 `ExcelResultWriter.write_row(..., landing_url=...)`,
  `utils.config.COL_LANDING_PAGE`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_main_window_worker.py` 파일을 새로 만든다:

```python
import openpyxl

import ui.main_window as main_window_module
from datasheet.downloader import DownloadResult
from ui.main_window import DatasheetWorker
from utils.config import COL_LANDING_PAGE, STATUS_FAILED


class _StubMouserClient:
    def __init__(self, *args, **kwargs):
        pass


def _make_input_workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "부품리스트"
    ws.append(["No.", "품번", "제조사"])
    ws.append([1, "AD8030ARZ", ""])
    wb.save(path)
    wb.close()


def test_worker_writes_landing_url_to_excel(tmp_path, monkeypatch):
    excel_path = tmp_path / "import.xlsx"
    _make_input_workbook(excel_path)

    monkeypatch.setattr(main_window_module, "MouserClient", _StubMouserClient)
    monkeypatch.setattr(
        main_window_module,
        "download_datasheet_for_part",
        lambda part, hint, client: DownloadResult(
            STATUS_FAILED,
            None,
            "웹 다운로드 실패: HTTP 403",
            "Analog Devices",
            "https://www.analog.com/blocked.pdf",
            "https://www.analog.com/en/products/ad8030.html",
        ),
    )

    rows = [{"row": 2, "part_number": "AD8030ARZ", "manufacturer": None}]
    worker = DatasheetWorker(rows, str(excel_path), "부품리스트")
    worker.run()

    wb = openpyxl.load_workbook(excel_path)
    ws = wb["부품리스트"]
    header_row = [c.value for c in ws[1]]
    col_idx = header_row.index(COL_LANDING_PAGE) + 1
    assert ws.cell(row=2, column=col_idx).value == "https://www.analog.com/en/products/ad8030.html"
    wb.close()
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_main_window_worker.py -v`
Expected: FAIL — `제품 페이지 링크` 컬럼 값이 빈 문자열이라 `assert ... == "https://www.analog.com/en/products/ad8030.html"` 실패

- [ ] **Step 3: `DatasheetWorker.run()` 수정**

`ui/main_window.py`의 118~131행(`writer.write_row(...)` 호출부)을 아래로 교체한다:

```python
            writer.write_row(
                row["row"],
                {
                    COL_DOWNLOAD_STATUS: result.status,
                    COL_ANALYSIS_STATUS: analysis_status,
                    # 성공하면 파일명, 실패했는데 참고 링크가 있으면 그 URL을 같은 칸에 보여줘요.
                    COL_DATASHEET_LINK: result.filename or result.reference_url or "",
                    COL_ERROR_MESSAGE: result.error or "",
                    COL_UNRESOLVED_FIELDS: unresolved_text,
                    COL_SAVE_PATH: str(dest_path),
                    COL_LANDING_PAGE: result.landing_url or "",
                },
                link_path=link_path,
                reference_url=result.reference_url,
                landing_url=result.landing_url,
            )
```

그리고 파일 상단 import 목록(43~61행)의 `from utils.config import (...)` 블록에 `COL_LANDING_PAGE`를
`COL_ERROR_MESSAGE` 다음 줄에 추가한다:

```python
from utils.config import (
    ANALYSIS_DONE,
    ANALYSIS_FAILED,
    ANALYSIS_NEEDS_REVIEW,
    ANALYSIS_PENDING,
    COL_ANALYSIS_STATUS,
    COL_DATASHEET_LINK,
    COL_DOWNLOAD_STATUS,
    COL_ERROR_MESSAGE,
    COL_LANDING_PAGE,
    COL_SAVE_PATH,
    COL_UNRESOLVED_FIELDS,
    IMPORT_TEMPLATE_PATH,
    MAPPING_TEMPLATE_PATH,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SKIPPED_EXISTING,
    STATUS_SUCCESS_MOUSER,
    STATUS_SUCCESS_WEB,
)
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_main_window_worker.py -v`
Expected: PASS

- [ ] **Step 5: 전체 Python 테스트 스위트 재실행 (회귀 확인)**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 지금까지 만든 테스트(Task 1~4, 총 13개) 모두 PASS

- [ ] **Step 6: 커밋**

```bash
git add ui/main_window.py tests/test_main_window_worker.py
git commit -m "feat: DatasheetWorker가 landing_url을 제품 페이지 링크 컬럼에 기록"
```

---

### Task 5: VBA 매크로가 헤더를 갖춘 재다운로드 + 제품 페이지 폴백을 하도록 재작성

**Files:**
- Modify: `vba/datasheet_helper.bas` (전체 파일 교체)

**Interfaces:**
- Consumes: Task 3에서 정의한 컬럼 이름 `"제품 페이지 링크"` (없어도 동작해야 함 — 하위 호환).
- 이 태스크는 VBA 코드라 pytest로 테스트할 수 없다. Excel 매크로 보안 동의가 필요한 UI 상호작용이라
  자동화된 헤드리스 테스트가 불가능함 — 실제 실행 검증은 Task 6의 마지막 단계에서 사용자가 직접 한다.

- [ ] **Step 1: `vba/datasheet_helper.bas` 전체 교체**

파일 전체를 아래 내용으로 교체한다:

```vb
Attribute VB_Name = "datasheet_helper"
Option Explicit

' ============================================================
' 데이터시트 다운로드 도우미 (datasheet_helper.bas)
'
' 파이썬 프로그램이 자동으로 못 받은 부품(부품리스트 시트의 "다운로드 상태" = "실패")을
' 대상으로, "데이터시트 링크" 칸의 URL을 "저장 경로" 칸이 가리키는 자리에 직접 받아옵니다.
'
' 동작 순서:
'   1) WinHttp로 Python 다운로더(datasheet/downloader.py)와 같은 헤더(User-Agent/Referer/Accept)를
'      붙여서 직접 받아봐요. 401/403이거나 받은 내용이 진짜 PDF가 아니면(맨 앞 4바이트가 "%PDF"가
'      아니면) 곧바로 포기하고, 타임아웃/5xx/429처럼 일시적으로 보이는 오류는 잠깐 기다렸다가
'      최대 2번 더 시도해요 (파이썬 다운로더의 재시도 정책과 같은 톤).
'   2) 그래도 실패하면, "제품 페이지 링크" 칸에 값이 있으면 그 페이지를(제조사 제품/문서 페이지 -
'      막혔던 PDF 직링크를 그대로 다시 여는 것보다 사람이 직접 열었을 때 통과할 가능성이 더 커요)
'      열고, 없으면(구버전 Import 파일) 원래 데이터시트 링크를 기본 브라우저로 열어서 사람이 직접
'      "다른 이름으로 저장"할 수 있게 해줘요.
'
' 사용법:
'   1) 출력지 엑셀 파일을 엽니다.
'   2) Alt+F11 -> 메뉴 삽입(Insert) -> 모듈(Module) -> 이 파일 내용을 통째로 붙여넣습니다.
'      (또는 삽입 -> 파일 가져오기로 이 .bas 파일을 바로 import 해도 됩니다. 기존 datasheet_helper
'      모듈이 이미 있다면 먼저 지우고 새로 import 하세요.)
'   3) 커서를 DownloadFailedDatasheets 프로시저 안에 두고 F5를 누릅니다.
'   4) 매크로 보안 경고가 뜨면 "콘텐츠 사용/매크로 사용"을 눌러주세요.
'
' 이 파일은 WinHttp/ADODB(Windows 기본 제공 COM 컴포넌트)만 사용해요 - 별도 설치 필요 없어요.
' ============================================================

Private Const SHEET_NAME As String = "부품리스트"
Private Const STATUS_FAILED As String = "실패"
Private Const STATUS_SUCCESS_VBA As String = "성공 (VBA)"
Private Const STATUS_NEEDS_MANUAL As String = "실패 (브라우저로 확인 필요)"

Private Const MAX_RETRY As Long = 2
Private Const RETRY_DELAY_SECONDS As Long = 2
Private Const DOWNLOAD_USER_AGENT As String = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

Sub DownloadFailedDatasheets()
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Sheets(SHEET_NAME)
    On Error GoTo 0
    If ws Is Nothing Then
        MsgBox "'" & SHEET_NAME & "' 시트를 찾을 수 없습니다.", vbExclamation
        Exit Sub
    End If

    Dim colPart As Long, colStatus As Long, colLink As Long, colSavePath As Long, colLanding As Long
    colPart = FindColumn(ws, "품번")
    colStatus = FindColumn(ws, "다운로드 상태")
    colLink = FindColumn(ws, "데이터시트 링크")
    colSavePath = FindColumn(ws, "저장 경로")
    colLanding = FindColumn(ws, "제품 페이지 링크")  ' 구버전 Import 파일엔 없을 수 있어요 - 0이면 그냥 안 씀.

    If colPart = 0 Or colStatus = 0 Or colLink = 0 Or colSavePath = 0 Then
        MsgBox "'" & SHEET_NAME & "' 시트에서 필요한 컬럼(품번/다운로드 상태/데이터시트 링크/저장 경로)을 " & _
               "찾지 못했습니다. 이 프로그램이 만든 출력지 엑셀이 맞는지 확인해주세요.", vbExclamation
        Exit Sub
    End If

    Dim lastRow As Long
    lastRow = ws.Cells(ws.Rows.Count, colPart).End(xlUp).Row

    Dim successCount As Long, manualCount As Long, skipCount As Long
    Dim r As Long
    Dim status As String, refUrl As String, savePath As String, landingUrl As String

    For r = 2 To lastRow
        status = Trim(ws.Cells(r, colStatus).Value)
        refUrl = Trim(ws.Cells(r, colLink).Value)
        savePath = Trim(ws.Cells(r, colSavePath).Value)
        landingUrl = ""
        If colLanding > 0 Then landingUrl = Trim(ws.Cells(r, colLanding).Value)

        If status <> STATUS_FAILED Or refUrl = "" Or savePath = "" Then
            skipCount = skipCount + 1
            GoTo NextRow
        End If

        EnsureFolderExists FolderOf(savePath)

        If TryDownload(refUrl, savePath) Then
            ws.Cells(r, colStatus).Value = STATUS_SUCCESS_VBA
            successCount = successCount + 1
        Else
            If Dir(savePath) <> "" Then Kill savePath
            ws.Cells(r, colStatus).Value = STATUS_NEEDS_MANUAL
            If landingUrl <> "" Then
                Application.FollowHyperlink landingUrl, NewWindow:=True
            Else
                Application.FollowHyperlink refUrl, NewWindow:=True
            End If
            manualCount = manualCount + 1
        End If

NextRow:
    Next r

    ThisWorkbook.Save
    MsgBox "완료." & vbCrLf & _
           "직접 다운로드 성공: " & successCount & "건" & vbCrLf & _
           "브라우저로 열어서 확인 필요: " & manualCount & "건" & vbCrLf & _
           "대상 아님(건너뜀): " & skipCount & "건", vbInformation
End Sub

' url을 최대 MAX_RETRY+1번까지 시도해서 savePath에 받아요. 성공하면 True.
Private Function TryDownload(url As String, savePath As String) As Boolean
    Dim attempt As Long, delaySec As Long, outcome As String
    delaySec = RETRY_DELAY_SECONDS

    For attempt = 0 To MAX_RETRY
        If attempt > 0 Then
            Application.Wait Now + TimeSerial(0, 0, delaySec)
            delaySec = delaySec * 2
        End If

        outcome = DownloadOnce(url, savePath)
        If outcome = "OK" Then
            TryDownload = True
            Exit Function
        ElseIf outcome = "STOP" Then
            TryDownload = False
            Exit Function
        End If
        ' outcome = "RETRY" -> 다음 시도로 넘어가요.
    Next attempt

    TryDownload = False
End Function

' 한 번 요청해봐요. "OK"(성공) / "STOP"(다시 해봐야 소용없음) / "RETRY"(일시적 오류로 보임) 중 하나를 돌려줘요.
Private Function DownloadOnce(url As String, savePath As String) As String
    On Error GoTo Fail

    Dim http As Object
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.Open "GET", url, False
    http.SetRequestHeader "User-Agent", DOWNLOAD_USER_AGENT
    http.SetRequestHeader "Accept", "application/pdf,*/*;q=0.8"
    http.SetRequestHeader "Accept-Language", "ko-KR,ko;q=0.9,en;q=0.8"
    http.SetRequestHeader "Referer", RefererOf(url)
    http.Send

    Dim status As Long
    status = http.status

    If status = 401 Or status = 403 Then
        DownloadOnce = "STOP"
        Exit Function
    End If
    If status = 429 Or status >= 500 Then
        DownloadOnce = "RETRY"
        Exit Function
    End If
    If status <> 200 Then
        DownloadOnce = "STOP"
        Exit Function
    End If

    Dim body() As Byte
    body = http.responseBody

    If Not IsRealPdfBytes(body) Then
        DownloadOnce = "STOP"
        Exit Function
    End If

    SaveBytesToFile body, savePath
    DownloadOnce = "OK"
    Exit Function

Fail:
    ' 연결 실패/타임아웃 등은 일시적일 수 있으니 재시도해봐요.
    DownloadOnce = "RETRY"
End Function

' "https://host/path/file.pdf" -> "https://host/" (Python downloader.py의 Referer 규칙과 동일해요)
Private Function RefererOf(url As String) As String
    Dim posProtocol As Long, posSlash As Long, host As String
    posProtocol = InStr(url, "://")
    If posProtocol = 0 Then
        RefererOf = url
        Exit Function
    End If
    posSlash = InStr(posProtocol + 3, url, "/")
    If posSlash = 0 Then
        host = Mid(url, posProtocol + 3)
    Else
        host = Mid(url, posProtocol + 3, posSlash - posProtocol - 3)
    End If
    RefererOf = Left(url, posProtocol + 2) & host & "/"
End Function

Private Function IsRealPdfBytes(data() As Byte) As Boolean
    On Error GoTo NotPdf
    If (UBound(data) - LBound(data) + 1) < 4 Then GoTo NotPdf
    IsRealPdfBytes = (Chr(data(LBound(data))) = "%" And Chr(data(LBound(data) + 1)) = "P" And _
                       Chr(data(LBound(data) + 2)) = "D" And Chr(data(LBound(data) + 3)) = "F")
    Exit Function
NotPdf:
    IsRealPdfBytes = False
End Function

Private Sub SaveBytesToFile(data() As Byte, destPath As String)
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 1 ' adTypeBinary
    stream.Open
    stream.Write data
    stream.SaveToFile destPath, 2 ' adSaveCreateOverWrite
    stream.Close
End Sub

Private Function FindColumn(ws As Worksheet, headerName As String) As Long
    Dim c As Long
    Dim lastCol As Long
    lastCol = ws.Cells(1, ws.Columns.Count).End(xlToLeft).Column
    For c = 1 To lastCol
        If Trim(ws.Cells(1, c).Value) = headerName Then
            FindColumn = c
            Exit Function
        End If
    Next c
    FindColumn = 0
End Function

Private Function FolderOf(filePath As String) As String
    FolderOf = Left(filePath, InStrRev(filePath, "\"))
End Function

Private Sub EnsureFolderExists(folderPath As String)
    Dim parts() As String
    Dim built As String
    Dim i As Long

    If folderPath = "" Then Exit Sub
    If Right(folderPath, 1) = "\" Then folderPath = Left(folderPath, Len(folderPath) - 1)

    parts = Split(folderPath, "\")
    built = parts(0) & "\"  ' 드라이브 문자(예: C:)부터 시작해요.
    For i = 1 To UBound(parts)
        built = built & parts(i) & "\"
        If Dir(built, vbDirectory) = "" Then
            MkDir built
        End If
    Next i
End Sub
```

(이전 버전에 있던 `URLDownloadToFileA` 선언과 파일 기반 `IsRealPdf(filePath)` 함수는 제거했다 —
이제 다운로드 응답 바이트를 저장하기 전에 `IsRealPdfBytes`로 먼저 검증하므로 저장 후 다시 파일을
읽어 검사할 필요가 없다.)

- [ ] **Step 2: 커밋**

```bash
git add vba/datasheet_helper.bas
git commit -m "feat: VBA 도우미가 WinHttp 헤더 재시도 + 제품 페이지 폴백을 사용하도록 재작성"
```

---

### Task 6: Import 양식 헤더 갱신 + 통합 재검증

**Files:**
- Modify: `vba/Import_양식.xlsm` (마스터 템플릿, 헤더 행만)
- Modify: `Import_양식.xlsm` (프로젝트 루트의 사용자 테스트 파일, 헤더 행만)
- 매크로 모듈 자체는 Excel에서 수동으로 재설치해야 함 (아래 Step 3 참고 — Python으로 안전하게 자동화할
  방법이 없음: openpyxl은 `keep_vba=True`로 기존 vbaProject.bin을 통째로 보존만 할 뿐, 그 안의 개별
  모듈 소스 코드를 교체하는 기능은 제공하지 않음)

**Interfaces:**
- 이 태스크는 Task 1~5에서 만든 모든 코드를 실제 파일에 적용하고 검증하는 마무리 단계.

- [ ] **Step 1: 두 `.xlsm` 파일의 헤더 행에 "제품 페이지 링크" 추가**

아래 스크립트를 실행한다 (직전 세션에 고친 `keep_vba=True` 방식으로 안전하게 헤더 셀만 수정):

```bash
.venv/Scripts/python.exe -c "
import openpyxl

for path in ['vba/Import_양식.xlsm', 'Import_양식.xlsm']:
    wb = openpyxl.load_workbook(path, keep_vba=True)
    ws = wb['부품리스트']
    last_col = ws.max_column
    headers = [ws.cell(row=1, column=c).value for c in range(1, last_col + 1)]
    if '제품 페이지 링크' not in headers:
        ws.cell(row=1, column=last_col + 1, value='제품 페이지 링크')
    wb.save(path)
    wb.close()
    print(path, 'done')
"
```

Expected 출력: 두 파일 모두 `done` 출력, 에러 없음.

- [ ] **Step 2: VBA 매크로가 여전히 살아있는지 확인**

```bash
.venv/Scripts/python.exe -c "
import zipfile
for path in ['vba/Import_양식.xlsm', 'Import_양식.xlsm']:
    z = zipfile.ZipFile(path)
    has_vba = any('vbaProject' in n for n in z.namelist())
    print(path, 'vba preserved:', has_vba)
"
```

Expected: 두 파일 모두 `vba preserved: True`.

- [ ] **Step 3: (사용자 수동 작업) Excel에서 매크로 모듈 재설치**

이 단계는 Claude Code가 대신 실행할 수 없다 — Excel UI와 매크로 보안 동의가 필요하다. 사용자에게
아래 절차를 안내한다:

1. `vba/Import_양식.xlsm`을 Excel에서 연다.
2. `Alt+F11`로 VBA 편집기를 연다.
3. 왼쪽 프로젝트 트리에서 기존 `datasheet_helper` 모듈을 찾아 마우스 오른쪽 클릭 → "Remove datasheet_helper" (제거 시 "내보내기" 여부를 물으면 "아니오").
4. 메뉴 `삽입(Insert) → 파일 가져오기(File...)`로 이번에 수정한 `vba/datasheet_helper.bas`를 다시 가져온다.
5. 저장 (`Ctrl+S`, 매크로 사용 통합 문서 형식 유지).
6. 같은 절차를 프로젝트 루트의 `Import_양식.xlsm`에도 반복한다.

- [ ] **Step 4: Python 파이프라인 통합 재검증 (AD8030ARZ)**

Task 1~4가 실제로 맞물려 동작하는지, 루트의 `Import_양식.xlsm`(사용자가 넣어둔 테스트 품번
AD8030ARZ가 있는 파일)로 전체 파이프라인을 다시 돌려서 확인한다:

```bash
.venv/Scripts/python.exe -c "
from excel.excel_reader import read_part_list_sheet
from excel.excel_writer import ExcelResultWriter
from datasheet.downloader import download_datasheet_for_part, build_dest_path
from datasheet.search import MouserClient
from utils.config import (
    COL_DOWNLOAD_STATUS, COL_ANALYSIS_STATUS, COL_DATASHEET_LINK,
    COL_ERROR_MESSAGE, COL_UNRESOLVED_FIELDS, COL_SAVE_PATH, COL_LANDING_PAGE,
    ANALYSIS_PENDING,
)

path = 'Import_양식.xlsm'
rows = read_part_list_sheet(path)
client = MouserClient()
writer = ExcelResultWriter(path, '부품리스트')

for row in rows:
    result = download_datasheet_for_part(row['part_number'], row['manufacturer'], client)
    dest_path = build_dest_path(row['part_number'], result.manufacturer or row['manufacturer'])
    link_path = dest_path if result.filename else None
    writer.write_row(
        row['row'],
        {
            COL_DOWNLOAD_STATUS: result.status,
            COL_ANALYSIS_STATUS: ANALYSIS_PENDING,
            COL_DATASHEET_LINK: result.filename or result.reference_url or '',
            COL_ERROR_MESSAGE: result.error or '',
            COL_UNRESOLVED_FIELDS: '',
            COL_SAVE_PATH: str(dest_path),
            COL_LANDING_PAGE: result.landing_url or '',
        },
        link_path=link_path,
        reference_url=result.reference_url,
        landing_url=result.landing_url,
    )
    writer.save()
    print(row['part_number'], '->', result.status, '| landing:', result.landing_url)
writer.close()
"
```

Expected: `AD8030ARZ -> 실패 | landing: <analog.com 제품 페이지 URL>` 형태의 출력 (지난 세션과 같은
HTTP 403 실패지만, 이번엔 `landing` 값이 채워져 있어야 한다). 이어서 Step 2와 같은 방식으로
`vba preserved: True`인지 다시 확인한다.

- [ ] **Step 5: 사용자 최종 확인 요청**

사용자에게 아래를 요청한다: `Import_양식.xlsm`을 Excel에서 열고 매크로 보안 경고에서 "콘텐츠 사용"을
누른 뒤 `DownloadFailedDatasheets`를 실행해서, AD8030ARZ 행이 "성공 (VBA)"로 바뀌는지 또는 (Akamai
차단이 여전하다면) 브라우저가 막힌 PDF 직링크가 아니라 `analog.com` 제품 페이지로 열리는지 확인해달라고
요청한다.

- [ ] **Step 6: 커밋**

```bash
git add vba/Import_양식.xlsm Import_양식.xlsm
git commit -m "chore: Import 양식에 제품 페이지 링크 헤더 추가"
```

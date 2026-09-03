# 프로그램의 메인 화면(창)이에요. 상단 도구모음 + 표 + 진행상황 + 로그창으로 이뤄져 있어요.
#
# 처리 단계가 세 개로 분리돼 있어요 (버튼도 따로):
#   ① '데이터시트 다운로드' - 품번마다 PDF를 찾아 Download_ datasheets 폴더에 평평하게(분류 없이)
#      저장만 해요. 분석은 안 하고, 결과는 창(표)에만 반영돼요 - 아직 어떤 엑셀 파일도 건드리지 않아요.
#   ② '신뢰도 분석' - Download_ datasheets 폴더에 이미 있는 PDF(자동 다운로드든, 실패해서 사용자가
#      직접 받아 넣은 것이든)를 읽어서 분류/파라미터 추출을 해요. 이 결과도 창에만 쌓여요.
#   ③ '출력지 저장' - 지금까지 창에 쌓인 결과(다운로드 상태, 분석 결과, 창에서 고친 품번/제조사)를
#      실제 엑셀 파일로 만들어요. 이때 비로소 "어디에 저장할지" 묻는 대화상자가 뜨고, 입력지를
#      복사해서 그 위에 결과를 채워 넣어요. 입력지 자체는 이 과정에서도 절대 수정하지 않아요.

import html
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ai.analysis_state import PartAnalysis
from ai.pdf_parser import analyze_pdf
from datasheet.annotator import annotate_pdf
from datasheet.downloader import (
    DownloadResult,
    dest_path_for_part,
    download_datasheet_for_part,
    get_download_dir,
    move_to_classified,
    resolve_existing_pdf,
    set_download_dir,
)
from datasheet.search import MouserClient
from excel.excel_reader import find_input_columns, get_sheet_names, read_part_list_sheet
from excel.excel_writer import ExcelResultWriter
from ui.analysis_dialog import AnalysisReviewDialog
from ui.dialogs import SheetColumnDialog
from utils.config import (
    ANALYSIS_DONE,
    ANALYSIS_FAILED,
    ANALYSIS_NEEDS_REVIEW,
    ANALYSIS_PENDING,
    COL_ANALYSIS_STATUS,
    COL_DATASHEET_LINK,
    COL_DOWNLOAD_STATUS,
    COL_ERROR_MESSAGE,
    COL_SAVE_PATH,
    COL_UNRESOLVED_FIELDS,
    EXPORT_DEFAULT_DIR,
    IMPORT_TEMPLATE_PATH,
    OUTPUT_DEFAULT_NAME,
    PART_LIST_SHEET_NAME,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SKIPPED_EXISTING,
    STATUS_SUCCESS_MANUAL,
    STATUS_SUCCESS_MOUSER,
    STATUS_SUCCESS_WEB,
)
from utils.logger import logger

# 표에 보여줄 컬럼들 (요구사항의 "가운데 표" 컬럼 예시와 맞췄어요)
# "PDF 열기"는 2026-09-03에 "데이터시트 파일명" 바로 옆에 새로 추가된 컬럼이에요 - 파일명 칸은
# 이제 파일명 텍스트만 보여주고, 여는 동작(성공 시 "열기" 버튼 / 실패했지만 참고 링크가 있으면
# 클릭 가능한 링크)은 전부 이 컬럼에서 처리해요(_set_datasheet_cell 참고).
TABLE_HEADERS = [
    "No.", "품번", "제조사", "다운로드 상태", "분석 상태", "데이터시트 파일명", "PDF 열기",
    "오류내용", "미확인 항목", "검토",
]
COL_PART_NUMBER = 1
COL_MANUFACTURER = 2
COL_DATASHEET_FILE = 5
COL_PDF_OPEN = 6
COL_ERROR = 7
COL_UNRESOLVED = 8
COL_REVIEW_BUTTON = 9
# 입력지에서 온 값이라 창에서 엑셀처럼 바로 고칠 수 있는 컬럼들이에요 (품번/제조사).
EDITABLE_INPUT_COLUMNS = (COL_PART_NUMBER, COL_MANUFACTURER)
SUCCESS_STATUSES = (STATUS_SUCCESS_MOUSER, STATUS_SUCCESS_WEB, STATUS_SKIPPED_EXISTING, STATUS_SUCCESS_MANUAL)

# "데이터시트 파일명" 칸 내용 좌우에 추가로 주는 여백이에요(2026-09-03 사용자 요청: "양 옆으로
# 5pt 늘려줘"). Qt의 컬럼 폭은 픽셀 단위라 5pt를 픽셀 5px로 봤어요(그래서 양쪽 합쳐 10px) -
# 원하시는 크기와 다르면 이 숫자만 바꾸면 돼요.
_DATASHEET_COL_PADDING_PX = 10

# 표 컬럼의 시작 폭이에요(픽셀) - 시작값만 이거고, 이후엔 사용자가 드래그해서 바꾼 폭을 Qt가
# 그대로 유지해요(2026-09-03, "엑셀처럼 폭 조절" 요청). COL_DATASHEET_FILE은 내용에 따라 필요할
# 때 코드가 더 넓혀주기도 해요(_set_datasheet_cell 참고) - 그래도 시작 폭은 있어야 해서 여기 둠.
_DEFAULT_COLUMN_WIDTHS = {
    0: 40,    # No.
    COL_PART_NUMBER: 140,
    COL_MANUFACTURER: 110,
    3: 100,   # 다운로드 상태
    4: 90,    # 분석 상태
    COL_DATASHEET_FILE: 140,
    COL_PDF_OPEN: 70,
    COL_ERROR: 160,
    COL_UNRESOLVED: 160,
    COL_REVIEW_BUTTON: 60,
}

# 열저항 기준 선택지 (표시이름, 내부값). θJC=Case(접합-케이스), θJA=Ambient(접합-주위).
# Thermal Resistance 자동 폴백과 근거 노트에 반영돼요 (ai/pdf_parser.analyze_pdf 참고).
THERMAL_MODE_OPTIONS = [("Case (θJC)", "case"), ("Ambient (θJA)", "ambient")]

# 품번을 몇 개까지 동시에 처리할지. 다운로드는 하나 처리할 때마다 브라우저(Chromium)를 띄우기
# 때문에, 너무 늘리면 메모리/CPU 부담이 커져요. 이 정도가 속도와 리소스 사이의 적당한 균형이에요.
MAX_CONCURRENT_DOWNLOADS = 3


def _blank_result() -> dict:
    # 행 하나의 처리 결과를 담는 상자예요. 다운로드/분석 도중에는 이 값들이 메모리(MainWindow)에만
    # 쌓이고, '출력지 저장'을 눌러야 비로소 엑셀에 반영돼요(MainWindow._write_output_to 참고).
    return {
        "download_status": STATUS_PENDING,
        "filename": "",
        "reference_url": "",
        "error": "",
        "save_path": "",
        "analysis_status": ANALYSIS_PENDING,
        "unresolved": "",
        "analysis": None,
    }


class DownloadWorker(QObject):
    """데이터시트 '다운로드'만 담당해요 (분석은 안 함 - '신뢰도 분석' 버튼에서 따로 해요).

    품번 여러 개를 ThreadPoolExecutor로 동시에 처리해요(다운로드는 대부분 서버 응답을 "기다리는"
    시간이라, 여러 개를 동시에 기다리면 전체 배치 시간이 크게 줄어요). 결과는 신호로만 넘기고
    어떤 엑셀 파일도 열지 않아요 - 실제 저장은 사용자가 '출력지 저장'을 누른 순간에만 해요.

    받은 PDF는 전부 대분류/소분류 구분 없이 Download_ datasheets 폴더에 "품번.pdf"로 평평하게
    저장돼요 - 분류는 분석 단계에서만 의미가 있어서, 다운로드 단계에서는 아예 안 해요.
    """

    log_message = Signal(str)
    row_updated = Signal(int, dict)
    progress_updated = Signal(int, int)
    # 끝나면 실패한 (품번, 참고링크 또는 빈 문자열) 목록을 같이 넘겨줘요 - 사용자 안내용.
    finished = Signal(list)

    def __init__(self, rows: list[dict]):
        super().__init__()
        self.rows = rows

    def run(self):
        try:
            client = MouserClient()
        except ValueError as e:
            self.log_message.emit(f"! 설정 오류: {e}")
            self.finished.emit([])
            return

        total = len(self.rows)
        success = 0
        fail = 0
        completed = 0
        failed_rows: list[tuple[str, str]] = []

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
            futures = [executor.submit(self._process_row, i, row, client) for i, row in enumerate(self.rows)]
            # as_completed는 끝나는 순서대로 돌려줘요 - 동시 처리라 행 순서(1,2,3...)와 다를 수 있지만,
            # row_updated가 행 번호(i)를 같이 넘기니 화면 갱신은 문제없어요.
            for future in as_completed(futures):
                i, values = future.result()
                completed += 1

                if values["download_status"] in SUCCESS_STATUSES:
                    success += 1
                else:
                    fail += 1
                    failed_rows.append((self.rows[i]["part_number"], values["reference_url"]))

                self.row_updated.emit(i, values)
                self.progress_updated.emit(completed, total)

        self.log_message.emit(f"=== 다운로드 완료: 성공 {success}건 / 실패 {fail}건 ===")
        self.finished.emit(failed_rows)

    def _process_row(self, i: int, row: dict, client: MouserClient) -> tuple[int, dict]:
        # 품번 하나를 처리해요. ThreadPoolExecutor가 이 메서드를 여러 스레드에서 동시에 호출해요.
        total = len(self.rows)
        part = row["part_number"]
        manufacturer_hint = row["manufacturer"]
        self.log_message.emit(f"[{i + 1}/{total}] {part} 다운로드 중...")

        try:
            result = download_datasheet_for_part(part, manufacturer_hint, client)
        except Exception as e:
            result = DownloadResult(STATUS_FAILED, None, str(e), manufacturer_hint)

        # dest_path는 항상 "이 부품의 PDF가 있는(또는 있어야 할) 자리"예요(분류 없이 평평한 경로).
        # 다운로드가 실패했으면, 사용자가 수동으로 받아서 저장해야 할 정확한 자리를 알려주는
        # 역할도 해요 (엑셀의 "저장 경로" 칸 -> VBA 도우미도 이 칸을 봐요).
        dest_path = dest_path_for_part(part)

        if result.status in SUCCESS_STATUSES:
            self.log_message.emit(f"  [OK] {result.status}: {result.filename}")
        else:
            detail = f" ({result.error})" if result.error else ""
            self.log_message.emit(f"  [실패]{detail}")

        values = {
            "manufacturer": result.manufacturer or manufacturer_hint or "",
            "download_status": result.status,
            "filename": result.filename or "",
            "reference_url": result.reference_url or "",
            "save_path": str(dest_path),
            "error": result.error or "",
        }
        return i, values


class AnalysisWorker(QObject):
    """'신뢰도 분석'만 담당해요 (다운로드는 안 함).

    Download_ datasheets 폴더에 이미 있는 PDF(자동으로 받아졌든, 실패해서 사용자가 직접 넣었든
    상관없이)를 읽어서 규칙 기반 분석(ai/pdf_parser.analyze_pdf)을 돌려요. 결과는 신호로만
    넘기고 어떤 엑셀 파일도 열지 않아요 - 실제 저장은 사용자가 '출력지 저장'을 누른 순간에만
    ExcelResultWriter/psa_writer로 한 번에 써요.
    """

    log_message = Signal(str)
    row_updated = Signal(int, dict)
    progress_updated = Signal(int, int)
    finished = Signal()

    def __init__(self, rows: list[dict], thermal_mode: str = "case"):
        super().__init__()
        self.rows = rows
        self.thermal_mode = thermal_mode  # "case"=θJC / "ambient"=θJA (analyze_pdf에 전달)

    def run(self):
        total = len(self.rows)
        done = 0
        failed = 0
        skipped = 0
        completed = 0

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
            futures = [executor.submit(self._process_row, i, row) for i, row in enumerate(self.rows)]
            for future in as_completed(futures):
                i, values = future.result()
                completed += 1

                status = values["analysis_status"]
                if status == ANALYSIS_FAILED:
                    failed += 1
                elif status == ANALYSIS_PENDING:
                    skipped += 1  # 데이터시트가 없어서 건너뜀
                else:
                    done += 1

                self.row_updated.emit(i, values)
                self.progress_updated.emit(completed, total)

        self.log_message.emit(
            f"=== 신뢰도 분석 완료: {done}건 / 분류불가 {failed}건 / 데이터시트 없어서 건너뜀 {skipped}건 ==="
        )
        self.finished.emit()

    def _process_row(self, i: int, row: dict) -> tuple[int, dict]:
        total = len(self.rows)
        part = row["part_number"]

        pdf_path = resolve_existing_pdf(part)
        if pdf_path is None:
            self.log_message.emit(f"[{i + 1}/{total}] {part} - 데이터시트가 없어서 건너뜁니다.")
            analysis, analysis_status, final_path = None, ANALYSIS_PENDING, None
        else:
            self.log_message.emit(f"[{i + 1}/{total}] {part} 분석 중...")
            analysis, analysis_status, final_path = self._analyze(part, pdf_path)

        unresolved_text = analysis.unresolved_summary() if analysis else ""

        if analysis_status == ANALYSIS_FAILED:
            self.log_message.emit("  [분류불가] 대분류/소분류를 판별하지 못했습니다.")
        elif analysis_status == ANALYSIS_NEEDS_REVIEW:
            self.log_message.emit(f"  [OK] {analysis.category} / {analysis.subcategory} -> {final_path}")

        values = {
            "analysis_status": analysis_status,
            "unresolved": unresolved_text,
            "analysis": analysis,
            "save_path": str(final_path) if final_path is not None else "",
        }
        return i, values

    def _analyze(self, part: str, pdf_path: Path) -> tuple[PartAnalysis | None, str, Path]:
        """규칙 기반 분석(ai/pdf_parser.analyze_pdf)을 돌려요. 대분류/소분류가 밝혀지면 PDF를
        <대분류>/<소분류> 폴더로 옮기고(move_to_classified) 그 경로를 같이 돌려줘요. 대분류/소분류
        자체를 못 판별하면 '분류불가'로 남기고 파일은 옮기지 않아요. 필드값이 다 채워졌어도 아직
        사람이 확인하지 않았으니 항상 '검토필요'로 시작해요(검토 다이얼로그에서 확인해야
        '확인완료'가 돼요)."""
        try:
            raw = analyze_pdf(pdf_path, thermal_mode=self.thermal_mode, part_number=part)
        except Exception as e:
            self.log_message.emit(f"  [분석 오류] {e}")
            return None, ANALYSIS_FAILED, pdf_path

        if not raw["category"] or not raw["subcategory"]:
            return None, ANALYSIS_FAILED, pdf_path

        final_path = move_to_classified(part, raw["category"], raw["subcategory"], pdf_path)

        # 분석 결과를 PDF 위에도 하이라이트로 표시해요(2026-09-03 도입, datasheet/annotator.py
        # 참고 - "클로드분석" 세션에서 손으로 만들어봤던 걸 모든 부품에 자동 적용한 버전). 이건
        # 보너스 기능이라 실패해도(PDF가 잠겨 있거나 예상 못 한 오류 등) 분석 자체는 그대로
        # 유효해요 - 그래서 예외를 여기서 잡고 로그만 남겨요.
        try:
            annotate_pdf(final_path, raw["category"], raw["subcategory"], raw["fields"], raw["evidence"])
        except Exception as e:
            self.log_message.emit(f"  [주석] PDF 표시 중 예상 못 한 오류: {e}")

        analysis = PartAnalysis(
            category=raw["category"],
            category_confidence=raw["category_confidence"],
            subcategory=raw["subcategory"],
            subcategory_confidence=raw["subcategory_confidence"],
            fields=raw["fields"],
            reference_notes=raw["reference_notes"],
        )
        return analysis, ANALYSIS_NEEDS_REVIEW, final_path


class MainWindow(QMainWindow):
    # logger.log(...)는 백그라운드 스레드(DownloadWorker/AnalysisWorker)에서도 직접 호출돼요. Qt
    # 위젯 메서드를 스레드에서 바로 부르면(appendPlainText를 콜백으로 직접 등록) 앱이 예고 없이
    # 죽을 수 있어서(Qt는 GUI를 메인 스레드에서만 건드려야 해요), Signal을 하나 거쳐서 항상 메인
    # 스레드 큐를 통해 안전하게 전달되게 해요.
    log_received = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("전자부품 데이터시트 수집 프로그램")
        self.resize(1150, 720)

        # 입력지: 사용자가 품번을 채워 넣은 원본 - 프로그램은 이 파일을 읽기만 하고 절대 쓰지 않아요.
        self.input_path: str | None = None
        # 출력지: '출력지 저장'을 누른 뒤에만 값이 생겨요(그 전까지는 아직 어떤 파일도 안 만들어요).
        self.output_path: str | None = None
        self.rows: list[dict] = []  # excel_reader가 준 원본 [{"row":.., "part_number":.., "manufacturer":..}]
        self.analysis: list[PartAnalysis | None] = []  # self.rows와 같은 순서로, 행마다의 분석 결과를 담아둬요.
        self.save_paths: list[str] = []  # 이 부품의 PDF가 있어야(또는 있을 예정인) 정확한 경로.
        # 행마다의 처리 결과(다운로드/분석)를 담아둬요 - '출력지 저장'을 누르는 순간 이 값들로
        # 엑셀을 한 번에 채워요. self.rows와 같은 순서로 나란히 대응돼요.
        self.results: list[dict] = []
        # 품번/제조사가 원본 엑셀에서 실제로 몇 번째 컬럼인지(1-indexed) - 출력지를 저장할 때
        # 이 위치에 그대로 되써넣어요. 자동/수동 인식 모두 실패하면 None(그 컬럼은 편집 비활성화).
        self._input_part_col: int | None = None
        self._input_mfr_col: int | None = None
        self.thread: QThread | None = None
        self.worker: DownloadWorker | AnalysisWorker | None = None
        self._success_count = 0
        self._fail_count = 0

        self._build_ui()
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.log_received.connect(self.log_box.appendPlainText)
        logger.add_callback(self.log_received.emit)
        self.setAcceptDrops(True)  # 엑셀 파일을 창 위로 끌어다 놓을 수 있게 해줘요.

    # ---------------- 화면 만들기 ----------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_top_bar())
        self.table = self._build_table()
        root.addWidget(self.table)
        root.addLayout(self._build_progress_row())
        self.log_box = self._build_log_panel()
        root.addWidget(self.log_box)

    def _build_top_bar(self) -> QVBoxLayout:
        # 두 줄로 나눴어요: 1줄=입력지(읽기 전용) 선택, 2줄=출력지 저장 + 저장 폴더 + 실행 버튼.
        # 입력지/출력지가 서로 다른 파일이라는 걸 화면에서도 분명히 보여주기 위해서예요.
        container = QVBoxLayout()

        row1 = QHBoxLayout()
        self.excel_label = QLabel("선택된 입력지 없음 (여기로 끌어다 놓아도 됩니다)")
        pick_excel_btn = QPushButton("입력지 선택")
        pick_excel_btn.setToolTip("품번을 채워 넣은 원본 엑셀을 선택해요. 이 파일은 절대 수정하지 않아요.")
        pick_excel_btn.clicked.connect(self._pick_excel)

        self.sheet_combo = QComboBox()
        self.sheet_combo.setMinimumWidth(140)

        # 열저항 기준(Case=θJC / Ambient=θJA) 선택. 분석 시 Thermal Resistance 폴백에 적용돼요.
        self.thermal_combo = QComboBox()
        for label, value in THERMAL_MODE_OPTIONS:
            self.thermal_combo.addItem(label, value)
        self.thermal_combo.setToolTip(
            "데이터시트에 열저항이 없을 때의 기준을 골라요.\n"
            "Case(θJC): 접합-케이스, 패키지별 217F 기본값으로 폴백.\n"
            "Ambient(θJA): 접합-주위, 데이터시트 값만 사용(폴백 없음)."
        )

        import_template_btn = QPushButton("입력지 양식")
        import_template_btn.clicked.connect(self._export_import_template)

        row1.addWidget(pick_excel_btn)
        row1.addWidget(self.excel_label, 1)
        row1.addWidget(QLabel("Sheet:"))
        row1.addWidget(self.sheet_combo)
        row1.addWidget(QLabel("열저항:"))
        row1.addWidget(self.thermal_combo)
        row1.addWidget(import_template_btn)

        row2 = QHBoxLayout()
        self.output_label = QLabel("아직 저장하지 않음")
        self.output_label.setToolTip("'출력지 저장'을 누르면 지금까지의 처리 결과가 이 자리에 저장돼요.")

        self.folder_label = QLabel(str(get_download_dir()))
        pick_folder_btn = QPushButton("저장 폴더 선택")
        pick_folder_btn.clicked.connect(self._pick_folder)

        # 단계 ① 다운로드: 품번마다 PDF를 찾아 Download_ datasheets 폴더에 분류 없이 저장만 해요.
        self.download_btn = QPushButton("데이터시트 다운로드")
        self.download_btn.clicked.connect(self._start_download)
        self.download_btn.setEnabled(False)

        # 단계 ② 분석: Download_ datasheets 폴더에 이미 있는 PDF를 읽어서 신뢰도 분석을 해요.
        # (자동 다운로드로 받았든, 실패해서 사용자가 직접 넣었든 상관없어요.)
        self.analysis_btn = QPushButton("신뢰도 분석")
        self.analysis_btn.clicked.connect(self._start_analysis)
        self.analysis_btn.setEnabled(False)

        # Download_ datasheets 폴더 상태를 다시 확인해서 화면(다운로드 상태)을 맞춰요
        # (2026-09-03 도입, 09-03 두 번째 요청으로 양방향 확인으로 확장):
        #   ① 실패로 남은 품번인데 사용자가 데이터시트를 직접 넣어둔 경우 -> "성공 (수동)"으로 승격
        #   ② 성공으로 표시돼 있는데 사용자가 실수로 파일을 지운 경우 -> "대기"로 되돌려서 다음
        #      '데이터시트 다운로드' 실행 때 자동으로 다시 받아오게 함
        # 신뢰도 분석 자체는 이미 매번 폴더를 새로 스캔해서 쓰지만(①의 경우는 새로고침 없이도
        # 분석은 되지만), 화면에서 "됐다/없어졌다"를 미리 눈으로 확인하고 싶다는 요청으로 추가함.
        self.refresh_btn = QPushButton("새로고침")
        self.refresh_btn.setToolTip(
            "Download_ datasheets 폴더를 다시 확인해요.\n"
            "· 실패한 품번에 사용자가 직접 넣은 파일이 있으면 '성공'으로 갱신\n"
            "· 성공했던 품번의 파일이 없어졌으면 '대기'로 되돌려서 다시 받을 수 있게 함"
        )
        self.refresh_btn.clicked.connect(self._refresh_datasheet_folder)
        self.refresh_btn.setEnabled(False)

        # 단계 ③ 저장: 지금까지 창에 쌓인 결과를 실제 엑셀 파일로 만들어요. 이때 처음으로
        # "어디에 저장할지" 물어봐요.
        self.save_output_btn = QPushButton("출력지 저장")
        self.save_output_btn.clicked.connect(self._save_output)
        self.save_output_btn.setEnabled(False)

        row2.addWidget(QLabel("출력지:"))
        row2.addWidget(self.output_label, 1)
        row2.addWidget(pick_folder_btn)
        row2.addWidget(self.folder_label, 1)
        row2.addWidget(self.download_btn)
        row2.addWidget(self.refresh_btn)
        row2.addWidget(self.analysis_btn)
        row2.addWidget(self.save_output_btn)

        container.addLayout(row1)
        container.addLayout(row2)
        return container

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(TABLE_HEADERS))
        table.setHorizontalHeaderLabels(TABLE_HEADERS)

        # 컬럼 너비: 예전엔 전부 Stretch라 "데이터시트 파일명" 칸(링크 여러 개 들어가는 자리)의
        # 글씨가 잘려 보이고, 사용자가 폭을 마음대로 못 늘렸어요(사용자 피드백, 2026-09-03). 전부
        # Interactive로 바꿔서 엑셀처럼 사용자가 경계선을 드래그해 마음대로 조절할 수 있어요.
        # "데이터시트 파일명"만 처음엔 ResizeToContents를 썼는데, 그 모드는 Qt가 폭을 계속 자동
        # 관리해서 사용자가 손으로 못 늘려요 - 그래서 이것도 Interactive로 바꾸고, 대신
        # _set_datasheet_cell에서 내용이 바뀔 때마다 "필요한 만큼보다 좁으면" 직접 넓혀줘요
        # (좌우 여백 5pt 포함, 2026-09-03 사용자 요청) - 사용자가 그보다 더 넓게 늘려놨으면 안
        # 건드리고, 새 내용이 그보다 넓을 때만 다시 넓어져요.
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, width in _DEFAULT_COLUMN_WIDTHS.items():
            table.setColumnWidth(col, width)
        # 엑셀처럼 컬럼 경계선을 더블클릭하면 그 칸 내용에 맞춰 폭이 한 번 자동으로 맞춰져요.
        # Qt 기본 resizeColumnToContents 대신 직접 만든 함수를 써요 - 이 표는 버튼/링크 같은
        # 커스텀 위젯이 든 칸이 많은데, Qt 기본 함수가 그 위젯 크기를 항상 안정적으로 반영하지는
        # 않는 걸 확인해서(2026-09-03), 각 행을 직접 재서 계산해요.
        header.sectionHandleDoubleClicked.connect(self._resize_column_to_fit)

        # Qt가 맨 왼쪽에 자동으로 붙여주는 행 번호(세로 헤더, 1/2/3...)를 꺼요 - 이미 TABLE_HEADERS
        # 첫 컬럼이 "No."라서 번호가 두 번 나오는 것처럼 보였어요(사용자 피드백, 2026-09-02).
        table.verticalHeader().setVisible(False)
        # 편집 자체는 셀마다 Qt.ItemIsEditable 플래그로 제어해요(_fill_row) - 여기서는 어떤
        # 동작으로 편집을 "시작"할지만 정해요(더블클릭하거나 바로 타이핑하면 엑셀처럼 편집).
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        return table

    def _build_progress_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.current_label = QLabel("대기 중")
        self.progress_bar = QProgressBar()
        self.count_label = QLabel("성공 0 / 실패 0")

        # 예전엔 여기 "PDF 열기" 버튼도 있었는데, 표의 "PDF 열기" 컬럼(행마다 바로 누르는 버튼)이
        # 생기면서 기능이 겹쳐 뺐어요(2026-09-03 사용자 요청) - 행을 먼저 선택해야 했던 이 버튼보다
        # 표에서 바로 누르는 쪽이 더 빠름.
        open_folder_btn = QPushButton("저장 위치 열기")
        open_folder_btn.clicked.connect(self._open_selected_folder)

        row.addWidget(self.current_label)
        row.addWidget(self.progress_bar, 1)
        row.addWidget(self.count_label)
        row.addWidget(open_folder_btn)
        return row

    def _build_log_panel(self) -> QPlainTextEdit:
        log_box = QPlainTextEdit()
        log_box.setReadOnly(True)
        log_box.setMaximumBlockCount(2000)
        log_box.setFixedHeight(160)
        return log_box

    # ---------------- 엑셀 불러오기 ----------------
    def _pick_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "입력지 선택", "", "Excel 파일 (*.xlsx *.xlsm)")
        if not path:
            return
        self.input_path = path
        self.excel_label.setText(Path(path).name)
        self._load_excel(path)

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "데이터시트 저장 폴더 선택", str(get_download_dir()))
        if not folder:
            return
        set_download_dir(folder)
        self.folder_label.setText(folder)

    def _load_excel(self, path: str):
        try:
            rows = read_part_list_sheet(path)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"엑셀을 여는 중 오류가 발생했습니다:\n{e}")
            return

        if rows is not None:
            # '부품리스트' 시트를 자동으로 찾은 경우
            self.sheet_combo.clear()
            self.sheet_combo.addItem("부품리스트")
            columns = find_input_columns(path, PART_LIST_SHEET_NAME)
            self._input_part_col = columns["part_col"] if columns else None
            self._input_mfr_col = columns.get("mfr_col") if columns else None
            self._apply_rows(rows)
            return

        # 자동 인식이 안 되면, 사용자가 직접 시트/컬럼을 고르는 팝업을 띄워요.
        sheet_names = get_sheet_names(path)
        dialog = SheetColumnDialog(path, sheet_names, self)
        if dialog.exec() and dialog.result_rows is not None:
            self.sheet_combo.clear()
            self.sheet_combo.addItem(dialog.sheet_combo.currentText())
            self._input_part_col = dialog.part_col
            self._input_mfr_col = dialog.mfr_col
            self._apply_rows(dialog.result_rows)

    def _apply_rows(self, rows: list[dict]):
        self.rows = rows
        self.analysis = [None] * len(rows)
        self.save_paths = [""] * len(rows)
        self.results = [_blank_result() for _ in rows]
        # 새 입력지를 불러왔으니, 이전 입력지로 저장했던 출력지 경로는 더 이상 유효하지 않아요.
        self.output_path = None
        self.output_label.setText("아직 저장하지 않음")
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            # 재로딩 때 이전 행의 "열기" 버튼/링크가 남지 않도록 두 컬럼 다 정리해요.
            self.table.removeCellWidget(i, COL_DATASHEET_FILE)
            self.table.removeCellWidget(i, COL_PDF_OPEN)
            self._fill_row(
                i,
                [
                    str(i + 1),
                    row["part_number"],
                    row.get("manufacturer") or "",
                    STATUS_PENDING,
                    ANALYSIS_PENDING,
                    "",
                    "",
                    "",
                    "",
                ],
            )
            self._set_review_button(i)
        has_rows = len(rows) > 0
        self.download_btn.setEnabled(has_rows)
        self.refresh_btn.setEnabled(has_rows)
        self.analysis_btn.setEnabled(has_rows)
        self.save_output_btn.setEnabled(has_rows)
        self._log(f"엑셀에서 {len(rows)}개 품번을 불러왔습니다.")

    def _fill_row(self, i: int, values: list[str]):
        # 초기 채우기는 사용자 입력이 아니라 프로그램이 하는 거라, itemChanged가 잘못 반응해서
        # 방금 채운 값을 다시 "수정"으로 받아들이지 않도록 신호를 잠가요.
        self.table.blockSignals(True)
        try:
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                # QTableWidgetItem은 기본적으로 편집 가능해서, 품번/제조사가 아닌 칸은 명시적으로
                # 편집 불가로 꺼둬요(다운로드/분석 상태 등은 프로그램이 채우는 값이라서요).
                if self._is_input_column_editable(col):
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, col, item)
        finally:
            self.table.blockSignals(False)

    def _is_input_column_editable(self, col: int) -> bool:
        if col == COL_PART_NUMBER:
            return self._input_part_col is not None
        if col == COL_MANUFACTURER:
            return self._input_mfr_col is not None
        return False

    def _set_input_editable(self, editable: bool):
        # 다운로드/분석이 도는 동안은 품번/제조사를 못 고치게 잠가요 - 안 그러면 백그라운드
        # 스레드가 예전 품번으로 작업을 이어가는 동안 표에는 새 품번이 보이는 혼란이 생겨요.
        self.table.blockSignals(True)
        try:
            for i in range(self.table.rowCount()):
                for col in EDITABLE_INPUT_COLUMNS:
                    item = self.table.item(i, col)
                    if item is None or not self._is_input_column_editable(col):
                        continue
                    if editable:
                        item.setFlags(item.flags() | Qt.ItemIsEditable)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        finally:
            self.table.blockSignals(False)

    def _on_table_item_changed(self, item: QTableWidgetItem):
        # 표에서 품번/제조사 칸을 엑셀처럼 직접 고쳤을 때 호출돼요(프로그램이 setItem으로 채울
        # 때는 신호를 잠가두므로 여기 안 들어와요). 파일에는 바로 안 쓰고 메모리(self.rows)에만
        # 반영해뒀다가, '출력지 저장'을 누르는 순간 한꺼번에 엑셀에 써요.
        col = item.column()
        if col not in EDITABLE_INPUT_COLUMNS:
            return
        i = item.row()
        if i >= len(self.rows):
            return

        new_value = item.text().strip()
        row = self.rows[i]
        field = "part_number" if col == COL_PART_NUMBER else "manufacturer"
        old_value = row.get(field) or ""

        if field == "part_number" and not new_value:
            # 품번은 비워둘 수 없어요 - 원래 값으로 되돌려요.
            self.table.blockSignals(True)
            item.setText(old_value)
            self.table.blockSignals(False)
            QMessageBox.warning(self, "알림", "품번은 비워둘 수 없습니다.")
            return

        if new_value == old_value:
            return

        row[field] = new_value or None
        field_label = "품번" if col == COL_PART_NUMBER else "제조사"
        self._log(f"{i + 1}행 {field_label}을(를) '{old_value}' -> '{new_value}'로 수정했습니다. (출력지 저장 시 반영)")

        if col == COL_PART_NUMBER:
            # 품번이 바뀌면 예전 다운로드/분석 결과는 더 이상 이 부품 것이 아니에요 - 다시 받아야
            # 한다는 걸 알 수 있도록 그 행의 상태를 초기화해요.
            self._reset_row_progress(i)

    def _reset_row_progress(self, i: int):
        self.analysis[i] = None
        if i < len(self.save_paths):
            self.save_paths[i] = ""
        if i < len(self.results):
            self.results[i] = _blank_result()
        self.table.blockSignals(True)
        try:
            self.table.setItem(i, 3, QTableWidgetItem(STATUS_PENDING))
            self.table.setItem(i, 4, QTableWidgetItem(ANALYSIS_PENDING))
            self.table.removeCellWidget(i, COL_DATASHEET_FILE)
            self.table.setItem(i, COL_DATASHEET_FILE, QTableWidgetItem(""))
            self.table.removeCellWidget(i, COL_PDF_OPEN)
            self.table.setItem(i, COL_PDF_OPEN, QTableWidgetItem(""))
            self.table.setItem(i, COL_ERROR, QTableWidgetItem(""))
            self.table.setItem(i, COL_UNRESOLVED, QTableWidgetItem(""))
        finally:
            self.table.blockSignals(False)
        self._set_review_button(i)

    def _set_review_button(self, i: int):
        # "검토" 버튼은 분석 결과가 있을 때만 눌러서 열 수 있어요.
        btn = QPushButton("검토")
        btn.setEnabled(self.analysis[i] is not None)
        btn.clicked.connect(lambda _checked=False, row=i: self._open_review_dialog(row))
        self.table.setCellWidget(i, COL_REVIEW_BUTTON, btn)

    @staticmethod
    def _link_label(url: str) -> str:
        # 참고 링크가 여러 개일 때(2026-09-03), 각 링크가 어느 사이트인지 도메인으로 구분해서
        # 보여줘요. 모르는 도메인이면 그냥 "링크"라고만 표시해요.
        netloc = urlparse(url).netloc.lower()
        if "mouser." in netloc:
            return "Mouser"
        if "digikey." in netloc:
            return "DigiKey"
        if "google." in netloc:
            return "구글 검색"
        if "duckduckgo." in netloc:
            return "DDG 검색"
        return "링크"

    def _set_datasheet_cell(self, i: int, download_status: str, filename: str, reference_url: str):
        # 성공했으면 "데이터시트 파일명" 칸에 파일명 텍스트를, "PDF 열기" 칸에 "열기" 버튼(로컬
        # 파일을 바로 염)을 넣어요. 실패했지만 참고 링크가 있으면, 그 링크를 "데이터시트 파일명"
        # 칸에 클릭 가능한 링크로 넣어요(2026-09-03 사용자 요청 - 처음엔 "PDF 열기" 칸에 넣었는데,
        # 사용자가 "데이터시트 파일명" 칸에서 찾고 있어서 그쪽으로 옮김. 성공 전까지는 "PDF 열기"
        # 칸이 비어있다가, 새로고침 등으로 파일을 찾으면 그때 위 성공 분기로 자연스럽게 넘어가요).
        self.table.removeCellWidget(i, COL_DATASHEET_FILE)
        self.table.removeCellWidget(i, COL_PDF_OPEN)
        is_success = download_status in SUCCESS_STATUSES

        if is_success:
            self.table.setItem(i, COL_DATASHEET_FILE, QTableWidgetItem(filename))
            open_btn = QPushButton("열기")
            open_btn.clicked.connect(lambda _checked=False, row=i: self._open_pdf_for_row(row))
            self.table.setCellWidget(i, COL_PDF_OPEN, open_btn)
        elif reference_url:
            # 링크가 여러 개일 수 있어요(줄바꿈으로 구분 - 예: Mouser에 없는 품번은 DigiKey에는
            # 있을 수 있어서 둘 다 줌, 2026-09-03 사용자 요청). 도메인으로 표시 이름을 붙여서
            # 한 줄에 나란히 보여줘요.
            urls = [u for u in reference_url.split("\n") if u]
            html_parts = [f'<a href="{html.escape(u, quote=True)}">{self._link_label(u)}</a>' for u in urls]
            link = QLabel(" · ".join(html_parts))
            link.setToolTip(reference_url)
            link.setOpenExternalLinks(True)  # 클릭하면 QDesktopServices로 기본 브라우저에서 열어요.
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            self.table.setCellWidget(i, COL_DATASHEET_FILE, link)
            self.table.setItem(i, COL_PDF_OPEN, QTableWidgetItem(""))
        else:
            self.table.setItem(i, COL_DATASHEET_FILE, QTableWidgetItem(""))
            self.table.setItem(i, COL_PDF_OPEN, QTableWidgetItem(""))

        self._ensure_datasheet_column_fits(i)

    def _ensure_datasheet_column_fits(self, i: int):
        # "데이터시트 파일명" 칸은 Interactive라 사용자가 자유롭게 폭을 조절할 수 있어야 해서
        # (2026-09-03 사용자 요청), ResizeToContents는 안 써요 - 그 모드는 Qt가 폭을 계속 자동으로
        # 관리해서 사용자가 손으로 못 늘려요. 대신 여기서 이번에 넣은 내용이 필요로 하는 폭을
        # 직접 계산해서, **지금 폭보다 좁을 때만** 늘려줘요(사용자가 이미 더 넓게 늘려놨으면 안
        # 건드림 - 자동으로 좁혀버리면 사용자 조절을 무시하는 셈이라). 양옆 여백 5pt씩(총 10px,
        # 사용자 요청)을 더해요.
        widget = self.table.cellWidget(i, COL_DATASHEET_FILE)
        if widget is not None:
            needed = widget.sizeHint().width()
        else:
            item = self.table.item(i, COL_DATASHEET_FILE)
            text = item.text() if item else ""
            needed = self.table.fontMetrics().horizontalAdvance(text)
        needed += _DATASHEET_COL_PADDING_PX  # 좌우 5pt씩.
        if needed > self.table.columnWidth(COL_DATASHEET_FILE):
            self.table.setColumnWidth(COL_DATASHEET_FILE, needed)

    def _resize_column_to_fit(self, col: int):
        # 엑셀의 "열 너비 자동 맞춤"과 같은 동작이에요 - 컬럼 경계선을 더블클릭하면 호출돼요.
        # 이 표는 버튼/링크 같은 커스텀 위젯이 든 칸이 많아서("열기" 버튼, 참고 링크 등), 그 행
        # 하나만이 아니라 **모든 행**을 훑어서 가장 넓은 걸 기준으로 맞춰요.
        needed = self.table.fontMetrics().horizontalAdvance(TABLE_HEADERS[col])  # 헤더 글자도 포함.
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, col)
            if widget is not None:
                needed = max(needed, widget.sizeHint().width())
                continue
            item = self.table.item(row, col)
            if item is not None:
                needed = max(needed, self.table.fontMetrics().horizontalAdvance(item.text()))
        padding = _DATASHEET_COL_PADDING_PX if col == COL_DATASHEET_FILE else 16
        self.table.setColumnWidth(col, needed + padding)

    # ---------------- 단계 ① 데이터시트 다운로드 ----------------
    def _start_download(self):
        if not self.rows:
            return
        self.download_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.analysis_btn.setEnabled(False)
        self._set_input_editable(False)
        self.progress_bar.setMaximum(len(self.rows))
        self.progress_bar.setValue(0)
        self._success_count = 0
        self._fail_count = 0
        self.count_label.setText("성공 0 / 실패 0")
        for result in self.results:
            result.update(
                {"download_status": STATUS_PENDING, "filename": "", "reference_url": "", "error": "", "save_path": ""}
            )
        self.save_paths = [""] * len(self.rows)

        self.thread = QThread()
        self.worker = DownloadWorker(self.rows)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.log_message.connect(self._log)
        self.worker.row_updated.connect(self._on_download_row_updated)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.finished.connect(self._on_download_finished)
        self.worker.finished.connect(self.thread.quit)

        self.thread.start()

    def _on_download_row_updated(self, i: int, values: dict):
        self.save_paths[i] = values["save_path"]
        self.results[i].update(
            {
                "download_status": values["download_status"],
                "filename": values["filename"],
                "reference_url": values["reference_url"],
                "error": values["error"],
                "save_path": values["save_path"],
            }
        )

        # 프로그램이 채우는 값이라 itemChanged가 "사용자가 고쳤다"고 착각하지 않도록 신호를 잠가요.
        self.table.blockSignals(True)
        self.table.setItem(i, COL_MANUFACTURER, QTableWidgetItem(values["manufacturer"]))
        self.table.setItem(i, 3, QTableWidgetItem(values["download_status"]))
        self._set_datasheet_cell(i, values["download_status"], values["filename"], values["reference_url"])
        self.table.setItem(i, COL_ERROR, QTableWidgetItem(values["error"]))
        self.table.blockSignals(False)

        if values["download_status"] in SUCCESS_STATUSES:
            self._success_count += 1
        else:
            self._fail_count += 1
        self.count_label.setText(f"성공 {self._success_count} / 실패 {self._fail_count}")
        self.current_label.setText(f"{self.table.item(i, 1).text()} 다운로드 완료")

    def _on_download_finished(self, failed_rows: list[tuple[str, str]]):
        self.download_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.analysis_btn.setEnabled(True)
        self._set_input_editable(True)
        self.current_label.setText("다운로드 완료")

        summary = f"다운로드가 끝났습니다.\n성공 {self._success_count}건 / 실패 {self._fail_count}건"
        if not failed_rows:
            QMessageBox.information(self, "완료", summary)
            return

        # 실패한 품번은 사용자가 직접 받아서 Download_ datasheets 폴더에 넣도록 안내해요.
        lines = [
            summary,
            "",
            f"아래 품번은 자동으로 받지 못했습니다. 데이터시트를 직접 받아서",
            f"'{get_download_dir()}' 폴더에 아래 파일명 그대로 저장해주세요:",
            "",
        ]
        for part, reference_url in failed_rows:
            filename = dest_path_for_part(part).name
            if reference_url:
                # reference_url이 줄바꿈으로 링크 여러 개를 담고 있을 수 있어요(예: Mouser+DigiKey
                # 검색 링크, 2026-09-03) - 이 요약 팝업에서는 한 줄에 ", "로 이어서 보여줘요.
                links = ", ".join(reference_url.split("\n"))
                lines.append(f"· {part}  ->  {filename}\n   (참고 링크: {links})")
            else:
                lines.append(f"· {part}  ->  {filename}")
        lines.append("")
        lines.append("전부 채워 넣은 뒤 '신뢰도 분석' 버튼을 누르면 이어서 분석할 수 있습니다.")
        QMessageBox.warning(self, "다운로드 실패 안내", "\n".join(lines))

    def _refresh_datasheet_folder(self):
        """Download_ datasheets 폴더의 실제 파일 상태를 화면과 다시 맞춰요. 양방향으로 확인해요
        (2026-09-03, 두 번째 요청으로 확장):

        ① 실패로 남은 품번인데 사용자가 데이터시트를 직접 넣어둔 게 있으면 -> "성공 (수동)"으로
           승격해요. ('신뢰도 분석' 버튼 자체는 이미 매번 폴더를 새로 스캔해서 자동으로 찾아 쓰지만
           (_process_row의 resolve_existing_pdf 참고), 분석을 돌리기 전에 화면에서 먼저 확인하고
           싶다는 요청으로 만든 기능이에요.)
        ② 성공으로 표시돼 있는데 그 파일이 실제로는 없어졌으면(사용자가 실수로 지운 경우 등) ->
           "대기"로 되돌려요. `download_datasheet_for_part`는 매번 파일 존재 여부를 새로 확인하고
           없으면 다시 받아오므로(datasheet/downloader.py 참고), 상태만 "대기"로 되돌려두면 다음
           '데이터시트 다운로드' 실행 때 자동으로 재다운로드돼요 - 화면에 "지워진 파일이 성공으로
           남아있는" 착시가 없게 하는 목적."""
        if not self.rows:
            return
        found = 0
        missing_again = 0
        for i, row in enumerate(self.rows):
            part = row["part_number"]
            pdf_path = resolve_existing_pdf(part)
            status = self.results[i]["download_status"]

            if status in SUCCESS_STATUSES:
                if pdf_path is not None:
                    continue  # 성공했고 파일도 그대로 있어요 - 손댈 게 없어요.
                # 성공했다고 표시돼 있지만 파일이 실제로 없어졌어요 - 다시 받을 수 있게 되돌려요.
                self.results[i].update({"download_status": STATUS_PENDING, "filename": ""})
                self.table.setItem(i, 3, QTableWidgetItem(STATUS_PENDING))
                self._set_datasheet_cell(i, STATUS_PENDING, "", "")
                self._log(f"{part}: 저장돼 있던 데이터시트가 없어져서 '대기'로 되돌렸습니다.")
                missing_again += 1
                continue

            if pdf_path is not None:
                self.results[i].update({"download_status": STATUS_SUCCESS_MANUAL, "filename": pdf_path.name})
                self.table.setItem(i, 3, QTableWidgetItem(STATUS_SUCCESS_MANUAL))
                self._set_datasheet_cell(i, STATUS_SUCCESS_MANUAL, pdf_path.name, "")
                self._log(f"{part}: 사용자가 넣은 데이터시트를 찾았습니다 -> {pdf_path.name}")
                found += 1

        lines = []
        if found:
            lines.append(f"{found}개 품번에서 새 데이터시트를 찾았습니다.")
        if missing_again:
            lines.append(f"{missing_again}개 품번은 저장돼 있던 데이터시트가 없어져서 '대기'로 되돌렸습니다.")
            lines.append("'데이터시트 다운로드'를 다시 누르면 자동으로 재시도합니다.")
        if not lines:
            lines.append("달라진 게 없습니다.")
        QMessageBox.information(self, "새로고침 완료", "\n".join(lines))

    # ---------------- 단계 ② 신뢰도 분석 ----------------
    def _missing_pdf_rows(self) -> list[tuple[str, Path]]:
        # Download_ datasheets 폴더(평평한 자리든, 이미 분류된 폴더든)에 아직 PDF가 없는 품번들을
        # 찾아요.
        missing = []
        for row in self.rows:
            part = row["part_number"]
            if resolve_existing_pdf(part) is None:
                missing.append((part, dest_path_for_part(part)))
        return missing

    def _start_analysis(self):
        if not self.rows:
            return

        # 데이터시트가 없는 품번이 있어도 막지 않아요 - 안내 문구만 보여주고, 있는 품번은 그대로
        # 분석을 진행해요. 없는 품번은 AnalysisWorker가 개별적으로 건너뛰고 '대기' 상태로 남겨요.
        missing = self._missing_pdf_rows()
        if missing:
            lines = [
                f"{len(missing)}개 품번은 아직 '{get_download_dir()}' 폴더에 데이터시트가 없어서",
                "이번 분석에서는 건너뜁니다:",
                "",
            ]
            lines += [f"· {part}  ->  {path.name}" for part, path in missing]
            lines.append("")
            lines.append("나중에 파일을 채워 넣은 뒤 '신뢰도 분석'을 다시 누르면 그 품번만 이어서 분석됩니다.")
            QMessageBox.information(self, "일부 데이터시트 없음", "\n".join(lines))

        self.download_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.analysis_btn.setEnabled(False)
        self._set_input_editable(False)
        self.progress_bar.setMaximum(len(self.rows))
        self.progress_bar.setValue(0)
        self.analysis = [None] * len(self.rows)
        for result in self.results:
            result.update({"analysis_status": ANALYSIS_PENDING, "unresolved": "", "analysis": None})

        thermal_mode = self.thermal_combo.currentData()
        self._log(f"신뢰도 분석을 시작합니다. 열저항 기준: {self.thermal_combo.currentText()}")
        self.thread = QThread()
        self.worker = AnalysisWorker(self.rows, thermal_mode)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.log_message.connect(self._log)
        self.worker.row_updated.connect(self._on_analysis_row_updated)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.finished.connect(self._on_analysis_finished)
        self.worker.finished.connect(self.thread.quit)

        self.thread.start()

    def _on_analysis_row_updated(self, i: int, values: dict):
        self.analysis[i] = values["analysis"]
        self.results[i].update(
            {
                "analysis_status": values["analysis_status"],
                "unresolved": values["unresolved"],
                "analysis": values["analysis"],
            }
        )
        if values.get("save_path"):
            # 분류 폴더로 옮겨졌으면(대분류/소분류가 밝혀졌으면), "PDF 열기"/"저장 위치 열기"가
            # 새 위치를 보도록 갱신해요.
            self.save_paths[i] = values["save_path"]
            self.results[i]["save_path"] = values["save_path"]
        self.table.blockSignals(True)
        self.table.setItem(i, 4, QTableWidgetItem(values["analysis_status"]))
        self.table.setItem(i, COL_UNRESOLVED, QTableWidgetItem(values["unresolved"]))
        self.table.blockSignals(False)
        self._set_review_button(i)
        self.current_label.setText(f"{self.table.item(i, 1).text()} 분석 완료")

    def _on_analysis_finished(self):
        self.download_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.analysis_btn.setEnabled(True)
        self._set_input_editable(True)
        self.current_label.setText("분석 완료")
        QMessageBox.information(self, "완료", "신뢰도 분석이 끝났습니다.\n표의 '검토' 버튼으로 결과를 확인하세요.")

    def _open_review_dialog(self, i: int):
        analysis = self.analysis[i]
        if analysis is None:
            QMessageBox.information(self, "알림", "아직 분석 결과가 없습니다. 먼저 '신뢰도 분석'을 실행하세요.")
            return

        part = self.rows[i]["part_number"]
        dialog = AnalysisReviewDialog(part, analysis, self)
        if not dialog.exec():
            return

        unresolved = analysis.unresolved_summary()
        status = ANALYSIS_DONE if analysis.is_fully_confirmed() else ANALYSIS_NEEDS_REVIEW
        self.table.setItem(i, 4, QTableWidgetItem(status))
        self.table.setItem(i, COL_UNRESOLVED, QTableWidgetItem(unresolved))
        self.results[i]["analysis_status"] = status
        self.results[i]["unresolved"] = unresolved
        self._log(f"{part} 분석 결과를 검토했습니다. ({status})")

    def _on_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)

    # ---------------- 단계 ③ 출력지 저장 ----------------
    def _save_output(self):
        if not self.input_path:
            QMessageBox.information(self, "알림", "먼저 입력지를 선택하세요.")
            return
        if not self.rows:
            QMessageBox.information(self, "알림", "저장할 내용이 없습니다.")
            return

        input_path = Path(self.input_path)
        default_path = str(EXPORT_DEFAULT_DIR / f"{OUTPUT_DEFAULT_NAME}{input_path.suffix}")
        save_path, _ = QFileDialog.getSaveFileName(
            self, "출력지 저장", default_path, "Excel 파일 (*.xlsx *.xlsm)"
        )
        if not save_path:
            return

        try:
            self._write_output_to(save_path)
        except PermissionError:
            QMessageBox.critical(
                self,
                "저장 오류",
                f"'{save_path}'에 저장할 수 없습니다.\n"
                "Excel 등 다른 프로그램에서 이 파일을 열어두지 않았는지 확인하고 닫은 뒤 다시 시도하세요.",
            )
            return
        except Exception as e:
            QMessageBox.critical(self, "저장 오류", f"출력지를 저장하는 중 오류가 발생했습니다:\n{e}")
            return

        self.output_path = save_path
        self.output_label.setText(Path(save_path).name)
        self._log(f"출력지를 저장했습니다: {save_path}")
        QMessageBox.information(self, "완료", f"출력지를 저장했습니다.\n{save_path}")

    def _write_output_to(self, save_path: str):
        # 입력지를 통째로 복사해서 시작해요(같은 시트/서식/매크로) - 그 사본 위에만 결과를 써요.
        # 매번 입력지에서 새로 복사하기 때문에, 여러 번 눌러도 이전 저장의 중복 흔적이 안 남아요.
        shutil.copy(self.input_path, save_path)

        sheet_name = self.sheet_combo.currentText()
        writer = ExcelResultWriter(save_path, sheet_name)
        try:
            for i, row in enumerate(self.rows):
                # 창에서 고친 품번/제조사를 반영해요(복사본은 아직 입력지 당시 값 그대로라서요).
                if self._input_part_col is not None:
                    writer.ws.cell(row=row["row"], column=self._input_part_col, value=row["part_number"])
                if self._input_mfr_col is not None:
                    writer.ws.cell(row=row["row"], column=self._input_mfr_col, value=row.get("manufacturer") or "")

                result = self.results[i]
                link_path = Path(result["save_path"]) if result["filename"] and result["save_path"] else None
                # reference_url이 줄바꿈으로 링크 여러 개를 담고 있을 수 있어요(Mouser+DigiKey,
                # 2026-09-03) - 엑셀 칸 텍스트는 첫 번째(우선순위 높은) 링크만 보여줘요. 실제
                # 하이퍼링크도 write_row 안에서 똑같이 첫 번째 것만 걸려서(excel_writer.py 참고),
                # 칸에 보이는 글자와 실제로 눌렸을 때 열리는 주소가 서로 다르지 않게 맞춘 거예요.
                first_reference_url = (result["reference_url"] or "").split("\n", 1)[0]
                writer.write_row(
                    row["row"],
                    {
                        COL_DOWNLOAD_STATUS: result["download_status"],
                        COL_DATASHEET_LINK: result["filename"] or first_reference_url,
                        COL_ERROR_MESSAGE: result["error"],
                        COL_SAVE_PATH: result["save_path"],
                        COL_ANALYSIS_STATUS: result["analysis_status"],
                        COL_UNRESOLVED_FIELDS: result["unresolved"],
                    },
                    link_path=link_path,
                    reference_url=result["reference_url"] or None,
                )

                analysis = result["analysis"]
                if analysis and analysis.category and analysis.subcategory:
                    writer.write_part_params(
                        analysis.category, analysis.subcategory, row["part_number"], row.get("part_name"), analysis.fields
                    )
            writer.save()
        finally:
            writer.close()

    def _export_import_template(self):
        # "입력지 양식" 버튼(2026-09-03 이름 변경, 예전엔 "Import 양식"): 입력지 마스터 파일
        # (vba/Import_User.xlsx, config의 IMPORT_TEMPLATE_PATH)을 그대로 복사해서 내보내요.
        # 사용자가 이 파일을 받아 품번을 채워 넣고 다시 입력지로 쓰면 돼요.
        if not IMPORT_TEMPLATE_PATH.exists():
            QMessageBox.critical(
                self, "오류", f"입력지 양식 파일을 찾을 수 없습니다:\n{IMPORT_TEMPLATE_PATH}"
            )
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "입력지 양식 저장", IMPORT_TEMPLATE_PATH.name, "Excel 파일 (*.xlsx)"
        )
        if not save_path:
            return

        try:
            shutil.copy(IMPORT_TEMPLATE_PATH, save_path)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"입력지 양식을 복사하는 중 오류가 발생했습니다:\n{e}")
            return

        self._log(f"입력지 양식을 만들었습니다: {save_path}")
        QMessageBox.information(self, "완료", f"입력지 양식을 만들었습니다.\n{save_path}")

    # ---------------- PDF 열기 ----------------
    def _selected_row(self) -> int | None:
        items = self.table.selectedItems()
        if not items:
            return None
        return items[0].row()

    def _pdf_path_for_row(self, i: int) -> Path:
        saved = self.save_paths[i] if i < len(self.save_paths) else ""
        if saved:
            return Path(saved)
        part = self.rows[i]["part_number"]
        return resolve_existing_pdf(part) or dest_path_for_part(part)

    def _open_pdf_for_row(self, i: int):
        # "데이터시트 파일명" 칸의 "열기" 버튼이 행 번호를 직접 넘겨서 호출해요 - 표에서 행을
        # 먼저 선택할 필요 없이 바로 그 PDF를 열어요(2026-09-03 사용자 요청).
        if i >= len(self.rows):
            return
        dest = self._pdf_path_for_row(i)
        if not dest.exists():
            QMessageBox.warning(self, "알림", "아직 다운로드된 파일이 없습니다.")
            return
        os.startfile(dest)

    def _open_selected_folder(self):
        i = self._selected_row()
        if i is None or i >= len(self.rows):
            folder = get_download_dir()
            folder.mkdir(exist_ok=True)
            os.startfile(folder)
            return
        dest = self._pdf_path_for_row(i)
        if dest.exists():
            subprocess.run(["explorer", f"/select,{dest}"])
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.startfile(dest.parent)

    # ---------------- 로그 ----------------
    def _log(self, message: str):
        # 파일에 기록 + (add_callback으로 등록해둔) 로그창에도 자동으로 표시돼요.
        logger.log(message)

    # ---------------- 드래그 앤 드롭 (엑셀 파일을 끌어다 놓기) ----------------
    def dragEnterEvent(self, event):
        # 끌고 오는 게 엑셀 파일이면 받아들이겠다고 표시해줘요.
        if self._excel_path_from_drop(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self._excel_path_from_drop(event)
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.input_path = path
        self.excel_label.setText(Path(path).name)
        self._load_excel(path)

    @staticmethod
    def _excel_path_from_drop(event) -> str | None:
        # 끌어다 놓은 것 중에 .xlsx/.xlsm 파일이 있으면 그 경로를 돌려주고, 없으면 None을 돌려줘요.
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            path = url.toLocalFile()
            if path.lower().endswith((".xlsx", ".xlsm")):
                return path
        return None

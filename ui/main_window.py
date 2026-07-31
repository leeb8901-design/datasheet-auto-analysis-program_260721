# 프로그램의 메인 화면(창)이에요. 상단 도구모음 + 표 + 진행상황 + 로그창으로 이뤄져 있어요.

import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
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
from datasheet.downloader import (
    DownloadResult,
    download_datasheet_for_part,
    get_download_dir,
    move_to_classified,
    resolve_pdf_path,
    set_download_dir,
)
from datasheet.search import MouserClient
from excel.excel_reader import get_sheet_names, read_part_list_sheet
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
    IMPORT_TEMPLATE_PATH,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SKIPPED_EXISTING,
    STATUS_SUCCESS_MOUSER,
    STATUS_SUCCESS_WEB,
)
from utils.logger import logger

# 표에 보여줄 컬럼들 (요구사항의 "가운데 표" 컬럼 예시와 맞췄어요)
TABLE_HEADERS = [
    "No.", "품번", "제조사", "다운로드 상태", "분석 상태", "데이터시트 파일명", "오류내용", "미확인 항목", "검토",
]
COL_REVIEW_BUTTON = 8
SUCCESS_STATUSES = (STATUS_SUCCESS_MOUSER, STATUS_SUCCESS_WEB, STATUS_SKIPPED_EXISTING)

# 열저항 기준 선택지 (표시이름, 내부값). θJC=Case(접합-케이스), θJA=Ambient(접합-주위).
# Thermal Resistance 자동 폴백과 근거 노트에 반영돼요 (ai/pdf_parser.analyze_pdf 참고).
THERMAL_MODE_OPTIONS = [("Case (θJC)", "case"), ("Ambient (θJA)", "ambient")]

# 품번을 몇 개까지 동시에 처리할지. 하나 처리할 때마다 브라우저(Chromium)를 띄우기 때문에,
# 너무 늘리면 메모리/CPU 부담이 커져요. 이 정도가 속도와 리소스 사이의 적당한 균형이에요.
MAX_CONCURRENT_DOWNLOADS = 3


class DatasheetWorker(QObject):
    """진짜 심부름(검색+다운로드)을 도는 일꾼이에요. 화면이 얼어붙지 않도록 별도 스레드에서 돌아가요.

    품번 여러 개를 ThreadPoolExecutor로 동시에 처리해요(다운로드는 대부분 서버 응답을 "기다리는"
    시간이라, 여러 개를 동시에 기다리면 전체 배치 시간이 크게 줄어요). 다운로드/분석 자체는 각
    스레드에서 독립적으로 실행되고, 같은 엑셀 파일(workbook)에 쓰는 부분만 write_lock으로 순서를
    지켜요 - openpyxl 객체 하나를 여러 스레드가 동시에 건드리면 안전하지 않아서예요.
    """

    log_message = Signal(str)
    row_updated = Signal(int, dict)
    progress_updated = Signal(int, int)
    finished = Signal()

    def __init__(self, rows: list[dict], excel_path: str, sheet_name: str, thermal_mode: str = "case"):
        super().__init__()
        self.rows = rows
        self.excel_path = excel_path
        self.sheet_name = sheet_name
        self.thermal_mode = thermal_mode  # "case"=θJC / "ambient"=θJA (analyze_pdf에 전달)

    def run(self):
        try:
            client = MouserClient()
        except ValueError as e:
            self.log_message.emit(f"! 설정 오류: {e}")
            self.finished.emit()
            return

        writer = ExcelResultWriter(self.excel_path, self.sheet_name)
        write_lock = threading.Lock()
        total = len(self.rows)
        success = 0
        fail = 0
        completed = 0

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
            futures = [
                executor.submit(self._process_row, i, row, client, writer, write_lock)
                for i, row in enumerate(self.rows)
            ]
            # as_completed는 끝나는 순서대로 돌려줘요 - 동시 처리라 행 순서(1,2,3...)와 다를 수 있지만,
            # row_updated가 행 번호(i)를 같이 넘기니 화면 갱신은 문제없어요.
            for future in as_completed(futures):
                i, values = future.result()
                completed += 1

                if values["download_status"] in SUCCESS_STATUSES:
                    success += 1
                else:
                    fail += 1

                self.row_updated.emit(i, values)
                self.progress_updated.emit(completed, total)

        writer.close()
        self.log_message.emit(f"=== 완료: 성공 {success}건 / 실패 {fail}건 ===")
        self.finished.emit()

    def _process_row(
        self, i: int, row: dict, client: MouserClient, writer: ExcelResultWriter, write_lock: threading.Lock
    ) -> tuple[int, dict]:
        # 품번 하나를 처리해요. ThreadPoolExecutor가 이 메서드를 여러 스레드에서 동시에 호출해요.
        total = len(self.rows)
        part = row["part_number"]
        manufacturer_hint = row["manufacturer"]
        self.log_message.emit(f"[{i + 1}/{total}] {part} 처리 중...")

        try:
            result = download_datasheet_for_part(part, manufacturer_hint, client)
        except Exception as e:
            result = DownloadResult(STATUS_FAILED, None, str(e), manufacturer_hint)

        # 분석까지 끝나면(대분류/소분류가 밝혀지면) 파일이 미분류 폴더에서 그 폴더로 옮겨져요 -
        # dest_path는 항상 "지금 이 부품의 PDF가 있는(또는 있을 예정인) 자리"예요. 다운로드가
        # 실패했으면 VBA 도우미가 나중에 저장할 자리(미분류)를 미리 알려주는 역할도 해요
        # (엑셀의 "저장 경로" 칸 -> datasheet_helper.bas 참고).
        analysis, analysis_status, dest_path = self._analyze_if_downloaded(part, result)
        unresolved_text = analysis.unresolved_summary() if analysis else ""

        link_path = dest_path if result.filename else None

        with write_lock:
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
                },
                link_path=link_path,
                reference_url=result.reference_url,
            )
            # 분석이 되면(대분류/소분류가 밝혀지면) 파라미터도 'PSA 입력 파라미터' 시트에 써넣어요.
            if analysis and analysis.category and analysis.subcategory:
                writer.write_part_params(
                    analysis.category, analysis.subcategory, part, row.get("part_name"), analysis.fields
                )
            writer.save()  # 한 행 끝날 때마다 바로바로 엑셀에 저장해요 (중간에 꺼져도 안전하게).

        if result.status in SUCCESS_STATUSES:
            self.log_message.emit(f"  [OK] {result.status}: {result.filename}")
        else:
            detail = f" ({result.error})" if result.error else ""
            self.log_message.emit(f"  [실패]{detail}")

        values = {
            "manufacturer": result.manufacturer or manufacturer_hint or "",
            "download_status": result.status,
            "analysis_status": analysis_status,
            "filename": result.filename or "",
            "reference_url": result.reference_url or "",
            "save_path": str(dest_path),
            "error": result.error or "",
            "unresolved": unresolved_text,
            "analysis": analysis,
        }
        return i, values

    def _analyze_if_downloaded(
        self, part: str, result: DownloadResult
    ) -> tuple[PartAnalysis | None, str, Path]:
        """다운로드가 성공했을 때만 규칙 기반 분석(ai/pdf_parser.analyze_pdf)을 돌려요.
        대분류/소분류 자체를 못 판별하면 '분류불가'로 남기고 파일은 미분류 폴더에 그대로 두고,
        판별되면 파일을 <대분류>/<소분류> 폴더로 옮겨요. 필드값이 다 채워졌어도 아직 사람이
        확인하지 않았으니 항상 '검토필요'로 시작해요 (검토 다이얼로그에서 확인해야 '확인완료'가 돼요).

        돌려주는 경로(세 번째 값)는 항상 "지금 이 부품의 PDF가 있는(또는 있을 예정인) 자리"예요.
        """
        current_path = resolve_pdf_path(part)

        if result.status not in SUCCESS_STATUSES:
            return None, ANALYSIS_PENDING, current_path

        try:
            raw = analyze_pdf(current_path, thermal_mode=self.thermal_mode)
        except Exception as e:
            self.log_message.emit(f"  [분석 오류] {e}")
            return None, ANALYSIS_FAILED, current_path

        if not raw["category"] or not raw["subcategory"]:
            return None, ANALYSIS_FAILED, current_path

        dest_path = move_to_classified(part, raw["category"], raw["subcategory"], current_path)

        analysis = PartAnalysis(
            category=raw["category"],
            category_confidence=raw["category_confidence"],
            subcategory=raw["subcategory"],
            subcategory_confidence=raw["subcategory_confidence"],
            fields=raw["fields"],
            reference_notes=raw["reference_notes"],
        )
        return analysis, ANALYSIS_NEEDS_REVIEW, dest_path


class MainWindow(QMainWindow):
    # logger.log(...)는 백그라운드 스레드(DatasheetWorker)에서도 직접 호출돼요. Qt 위젯 메서드를
    # 스레드에서 바로 부르면(appendPlainText를 콜백으로 직접 등록) 앱이 예고 없이 죽을 수 있어서
    # (Qt는 GUI를 메인 스레드에서만 건드려야 해요), Signal을 하나 거쳐서 항상 메인 스레드 큐를
    # 통해 안전하게 전달되게 해요.
    log_received = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("전자부품 데이터시트 수집 프로그램")
        self.resize(1150, 720)

        self.excel_path: str | None = None
        self.rows: list[dict] = []  # excel_reader가 준 원본 [{"row":.., "part_number":.., "manufacturer":..}]
        self.analysis: list[PartAnalysis | None] = []  # self.rows와 같은 순서로, 행마다의 분석 결과를 담아둬요.
        self.reference_urls: list[str] = []  # 자동 다운로드는 실패했지만 찾아낸 웹 링크 (VBA 도우미용).
        self.save_paths: list[str] = []  # 이 부품의 PDF가 있어야(또는 있을 예정인) 정확한 경로.
        self.thread: QThread | None = None
        self.worker: DatasheetWorker | None = None
        self._success_count = 0
        self._fail_count = 0

        self._build_ui()
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

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        self.excel_label = QLabel("선택된 엑셀 파일 없음 (여기로 끌어다 놓아도 됩니다)")
        pick_excel_btn = QPushButton("Excel 파일 선택")
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

        self.folder_label = QLabel(str(get_download_dir()))
        pick_folder_btn = QPushButton("저장 폴더 선택")
        pick_folder_btn.clicked.connect(self._pick_folder)

        import_template_btn = QPushButton("Import 양식")
        import_template_btn.clicked.connect(self._export_import_template)

        self.start_btn = QPushButton("처리 시작")
        self.start_btn.clicked.connect(self._start_processing)
        self.start_btn.setEnabled(False)

        bar.addWidget(pick_excel_btn)
        bar.addWidget(self.excel_label, 1)
        bar.addWidget(QLabel("Sheet:"))
        bar.addWidget(self.sheet_combo)
        bar.addWidget(QLabel("열저항:"))
        bar.addWidget(self.thermal_combo)
        bar.addWidget(pick_folder_btn)
        bar.addWidget(self.folder_label, 1)
        bar.addWidget(import_template_btn)
        bar.addWidget(self.start_btn)
        return bar

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(TABLE_HEADERS))
        table.setHorizontalHeaderLabels(TABLE_HEADERS)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        return table

    def _build_progress_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.current_label = QLabel("대기 중")
        self.progress_bar = QProgressBar()
        self.count_label = QLabel("성공 0 / 실패 0")

        open_pdf_btn = QPushButton("PDF 열기")
        open_pdf_btn.clicked.connect(self._open_selected_pdf)
        open_folder_btn = QPushButton("저장 위치 열기")
        open_folder_btn.clicked.connect(self._open_selected_folder)

        row.addWidget(self.current_label)
        row.addWidget(self.progress_bar, 1)
        row.addWidget(self.count_label)
        row.addWidget(open_pdf_btn)
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
        path, _ = QFileDialog.getOpenFileName(self, "엑셀 파일 선택", "", "Excel 파일 (*.xlsx *.xlsm)")
        if not path:
            return
        self.excel_path = path
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
            self._apply_rows(rows)
            return

        # 자동 인식이 안 되면, 사용자가 직접 시트/컬럼을 고르는 팝업을 띄워요.
        sheet_names = get_sheet_names(path)
        dialog = SheetColumnDialog(path, sheet_names, self)
        if dialog.exec() and dialog.result_rows is not None:
            self.sheet_combo.clear()
            self.sheet_combo.addItem(dialog.sheet_combo.currentText())
            self._apply_rows(dialog.result_rows)

    def _apply_rows(self, rows: list[dict]):
        self.rows = rows
        self.analysis = [None] * len(rows)
        self.reference_urls = [""] * len(rows)
        self.save_paths = [""] * len(rows)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
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
                ],
            )
            self._set_review_button(i)
        self.start_btn.setEnabled(len(rows) > 0)
        self._log(f"엑셀에서 {len(rows)}개 품번을 불러왔습니다.")

    def _fill_row(self, i: int, values: list[str]):
        for col, value in enumerate(values):
            self.table.setItem(i, col, QTableWidgetItem(value))

    def _set_review_button(self, i: int):
        # "검토" 버튼은 분석 결과가 있을 때만 눌러서 열 수 있어요.
        btn = QPushButton("검토")
        btn.setEnabled(self.analysis[i] is not None)
        btn.clicked.connect(lambda _checked=False, row=i: self._open_review_dialog(row))
        self.table.setCellWidget(i, COL_REVIEW_BUTTON, btn)

    # ---------------- 처리 시작 ----------------
    def _start_processing(self):
        if not self.rows or not self.excel_path:
            return
        self.start_btn.setEnabled(False)
        self.progress_bar.setMaximum(len(self.rows))
        self.progress_bar.setValue(0)
        self._success_count = 0
        self._fail_count = 0
        self.count_label.setText("성공 0 / 실패 0")
        self.analysis = [None] * len(self.rows)
        self.reference_urls = [""] * len(self.rows)
        self.save_paths = [""] * len(self.rows)

        sheet_name = self.sheet_combo.currentText()
        thermal_mode = self.thermal_combo.currentData()
        self._log(f"열저항 기준: {self.thermal_combo.currentText()}")
        self.thread = QThread()
        self.worker = DatasheetWorker(self.rows, self.excel_path, sheet_name, thermal_mode)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.log_message.connect(self._log)
        self.worker.row_updated.connect(self._on_row_updated)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)

        self.thread.start()

    def _on_row_updated(self, i: int, values: dict):
        self.analysis[i] = values["analysis"]
        self.reference_urls[i] = values["reference_url"]
        self.save_paths[i] = values["save_path"]

        self.table.setItem(i, 2, QTableWidgetItem(values["manufacturer"]))
        self.table.setItem(i, 3, QTableWidgetItem(values["download_status"]))
        self.table.setItem(i, 4, QTableWidgetItem(values["analysis_status"]))
        self.table.setItem(i, 5, QTableWidgetItem(values["filename"]))
        self.table.setItem(i, 6, QTableWidgetItem(values["error"]))
        self.table.setItem(i, 7, QTableWidgetItem(values["unresolved"]))
        self._set_review_button(i)

        if values["download_status"] in SUCCESS_STATUSES:
            self._success_count += 1
        else:
            self._fail_count += 1
        self.count_label.setText(f"성공 {self._success_count} / 실패 {self._fail_count}")
        self.current_label.setText(f"{self.table.item(i, 1).text()} 처리 완료")

    def _open_review_dialog(self, i: int):
        analysis = self.analysis[i]
        if analysis is None:
            QMessageBox.information(self, "알림", "아직 분석 결과가 없습니다. 먼저 '처리 시작'을 실행하세요.")
            return

        part = self.rows[i]["part_number"]
        dialog = AnalysisReviewDialog(part, analysis, self)
        if not dialog.exec():
            return

        unresolved = analysis.unresolved_summary()
        status = ANALYSIS_DONE if analysis.is_fully_confirmed() else ANALYSIS_NEEDS_REVIEW
        self.table.setItem(i, 4, QTableWidgetItem(status))
        self.table.setItem(i, 7, QTableWidgetItem(unresolved))
        self._log(f"{part} 분석 결과를 검토했습니다. ({status})")

    def _on_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)

    def _on_finished(self):
        self.start_btn.setEnabled(True)
        self.current_label.setText("완료")
        QMessageBox.information(
            self, "완료", f"처리가 끝났습니다.\n성공 {self._success_count}건 / 실패 {self._fail_count}건"
        )

    def _export_import_template(self):
        # "Import 양식" 버튼: 입력지 마스터 파일(Data_list_217F.xlsx, config의 IMPORT_TEMPLATE_PATH)을
        # 그대로 복사해서 내보내요. 사용자가 이 파일을 받아 품번을 채워 넣고 다시 입력지로 쓰면 돼요.
        if not IMPORT_TEMPLATE_PATH.exists():
            QMessageBox.critical(
                self, "오류", f"Import 양식 파일을 찾을 수 없습니다:\n{IMPORT_TEMPLATE_PATH}"
            )
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Import 양식 저장", IMPORT_TEMPLATE_PATH.name, "Excel 파일 (*.xlsx)"
        )
        if not save_path:
            return

        try:
            shutil.copy(IMPORT_TEMPLATE_PATH, save_path)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"Import 양식을 복사하는 중 오류가 발생했습니다:\n{e}")
            return

        self._log(f"Import 양식을 만들었습니다: {save_path}")
        QMessageBox.information(self, "완료", f"Import 양식을 만들었습니다.\n{save_path}")

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
        return resolve_pdf_path(self.rows[i]["part_number"])

    def _open_selected_pdf(self):
        i = self._selected_row()
        if i is None or i >= len(self.rows):
            QMessageBox.information(self, "알림", "먼저 표에서 행을 선택하세요.")
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
        self.excel_path = path
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

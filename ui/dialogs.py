# '부품리스트' 시트 자동 인식이 안 될 때, 사용자가 직접 시트/컬럼을 고르는 팝업창이에요.

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QVBoxLayout,
)

from excel.excel_reader import get_headers, guess_part_number_column, read_custom_sheet


class SheetColumnDialog(QDialog):
    """엑셀 파일에서 시트와 "부품번호"/"제조사" 컬럼을 직접 고르는 창이에요."""

    def __init__(self, path: str, sheet_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("시트/컬럼 선택")
        self.path = path
        self.result_rows: list[dict] | None = None  # 최종적으로 골라진 (품번, 제조사) 목록

        self.sheet_combo = QComboBox()
        self.sheet_combo.addItems(sheet_names)
        self.sheet_combo.currentTextChanged.connect(self._refresh_columns)

        self.part_col_combo = QComboBox()
        self.mfr_col_combo = QComboBox()
        self.mfr_col_combo.addItem("(없음)", None)

        self.header_checkbox = QCheckBox("첫 행은 제목(헤더)입니다")
        self.header_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow("시트:", self.sheet_combo)
        form.addRow("품번 컬럼:", self.part_col_combo)
        form.addRow("제조사 컬럼:", self.mfr_col_combo)
        form.addRow("", self.header_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_confirm)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._refresh_columns(sheet_names[0] if sheet_names else "")

    def _refresh_columns(self, sheet_name: str):
        if not sheet_name:
            return
        headers = get_headers(self.path, sheet_name)
        labeled = [f"{i + 1}열: {h or '(제목없음)'}" for i, h in enumerate(headers)]

        self.part_col_combo.clear()
        self.part_col_combo.addItems(labeled)
        guess = guess_part_number_column(headers)
        if labeled:
            self.part_col_combo.setCurrentIndex(guess)

        self.mfr_col_combo.clear()
        self.mfr_col_combo.addItem("(없음)", None)
        for i, label in enumerate(labeled):
            self.mfr_col_combo.addItem(label, i)

    def _on_confirm(self):
        sheet_name = self.sheet_combo.currentText()
        part_col = self.part_col_combo.currentIndex()
        if part_col < 0:
            QMessageBox.warning(self, "알림", "품번 컬럼을 선택하세요.")
            return
        mfr_col = self.mfr_col_combo.currentData()  # None이거나 정수 인덱스
        has_header = self.header_checkbox.isChecked()

        self.result_rows = read_custom_sheet(self.path, sheet_name, part_col, mfr_col, has_header)
        # 창에서 셀을 직접 고쳤을 때 원본 엑셀의 같은 칸에 되써넣을 수 있도록(1-indexed로 변환),
        # 사용자가 고른 컬럼 위치를 기억해둬요.
        self.header_row = 2 if has_header else 1
        self.part_col = part_col + 1
        self.mfr_col = (mfr_col + 1) if mfr_col is not None else None
        self.accept()

# 규칙 기반 분석 결과(대분류/소분류/파라미터 값)를 사람이 눈으로 대조하고 고치는 창이에요.
#
# 색 규칙(매핑맵 시트의 흰/회/보라/분홍과는 다른, 이 창 전용 "검토 상태" 색이에요):
#   빨강 = 값을 못 찾음(빈 칸)  /  노랑 = 자동 추출됐지만 아직 사람이 확인 안 함  /  초록 = 확인(또는 수정) 완료

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ai.analysis_state import PartAnalysis
from ai.prompt import get_fields_for_subcategory, load_subcat_params

COL_FIELD = 0
COL_VALUE = 1
COL_CONFIRM = 2

RED = QColor("#ffc7ce")
YELLOW = QColor("#ffeb9c")
GREEN = QColor("#c6efce")


class AnalysisReviewDialog(QDialog):
    """검토 창: 대분류/소분류를 고치고, 파라미터 값을 확인/수정한 뒤 체크박스로 확정해요."""

    def __init__(self, part_number: str, analysis: PartAnalysis, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"분석 결과 검토 - {part_number}")
        self.resize(560, 480)
        self.analysis = analysis

        self._subcats_by_category: dict[str, list[str]] = {}
        for entry in load_subcat_params():
            self._subcats_by_category.setdefault(entry["category"], []).append(entry["subcategory"])

        self.category_combo = QComboBox()
        self.category_combo.addItems(sorted(self._subcats_by_category.keys()))
        self.subcategory_combo = QComboBox()

        form = QFormLayout()
        form.addRow("대분류:", self.category_combo)
        form.addRow("소분류:", self.subcategory_combo)

        confidence_label = QLabel(
            f"분류 확신도 - 대분류: {analysis.category_confidence} / 소분류: {analysis.subcategory_confidence}"
            " (규칙 기반 추정값이라 낮아도 정상입니다. 아래 값을 데이터시트 원문과 직접 대조해 확인하세요.)"
        )
        confidence_label.setWordWrap(True)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["파라미터", "값", "확인"])
        self.table.itemChanged.connect(self._on_value_changed)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_confirm)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(confidence_label)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

        self.category_combo.currentTextChanged.connect(lambda _t: self._refresh_subcategory_combo())
        self.subcategory_combo.currentTextChanged.connect(lambda _t: self._refresh_table())

        # 초기값: 규칙 기반으로 판별된 대분류/소분류로 시작해요.
        if analysis.category in self._subcats_by_category:
            self.category_combo.setCurrentText(analysis.category)
        self._refresh_subcategory_combo(keep_selection=analysis.subcategory)

    def _refresh_subcategory_combo(self, keep_selection: str | None = None):
        category = self.category_combo.currentText()
        subcats = sorted(self._subcats_by_category.get(category, []))
        self.subcategory_combo.blockSignals(True)
        self.subcategory_combo.clear()
        self.subcategory_combo.addItems(subcats)
        if keep_selection and keep_selection in subcats:
            self.subcategory_combo.setCurrentText(keep_selection)
        self.subcategory_combo.blockSignals(False)
        self._refresh_table()

    def _refresh_table(self):
        category = self.category_combo.currentText()
        subcategory = self.subcategory_combo.currentText()
        self.table.blockSignals(True)
        if not category or not subcategory:
            self.table.setRowCount(0)
            self.table.blockSignals(False)
            return

        fields = get_fields_for_subcategory(category, subcategory)
        self.table.setRowCount(len(fields))
        for row, name in enumerate(fields):
            value = self.analysis.fields.get(name)
            confirmed = name in self.analysis.confirmed_fields

            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COL_FIELD, name_item)
            self.table.setItem(row, COL_VALUE, QTableWidgetItem(value or ""))

            check = QCheckBox()
            check.setChecked(confirmed)
            check.stateChanged.connect(lambda _state, r=row: self._recolor_row(r))
            self.table.setCellWidget(row, COL_CONFIRM, check)

            self._color_row(row, value, confirmed)
        self.table.blockSignals(False)

    def _on_value_changed(self, item: QTableWidgetItem):
        if item.column() == COL_VALUE:
            self._recolor_row(item.row())

    def _recolor_row(self, row: int):
        value_item = self.table.item(row, COL_VALUE)
        check = self.table.cellWidget(row, COL_CONFIRM)
        self._color_row(row, value_item.text() if value_item else None, check.isChecked() if check else False)

    def _color_row(self, row: int, value: str | None, confirmed: bool):
        color = GREEN if confirmed else (YELLOW if value else RED)
        for col in (COL_FIELD, COL_VALUE):
            item = self.table.item(row, col)
            if item:
                item.setBackground(color)

    def _on_confirm(self):
        fields: dict[str, str | None] = {}
        confirmed_fields: set[str] = set()
        for row in range(self.table.rowCount()):
            name = self.table.item(row, COL_FIELD).text()
            value = (self.table.item(row, COL_VALUE).text() or "").strip() or None
            fields[name] = value
            check = self.table.cellWidget(row, COL_CONFIRM)
            if check and check.isChecked():
                confirmed_fields.add(name)

        self.analysis.category = self.category_combo.currentText()
        self.analysis.subcategory = self.subcategory_combo.currentText()
        self.analysis.fields = fields
        self.analysis.confirmed_fields = confirmed_fields
        self.accept()

# API 키를 관리하는 창이에요(2026-09-04 도입 - .env 대신 이 방식으로 바꿈).
# User_API/ 폴더 안의 파일들을 목록으로 보여주고, 내용을 보거나 고칠 수 있어요.
# 파일 하나 = API 하나(예: JY_MOUSER_API_KEY.txt, 내용은 "MOUSER_API_KEY=실제키값") - 어떤
# API인지는 파일 "내용"의 KEY로 프로그램이 알아내므로(utils/config.get_api_key 참고), 파일
# 이름 자체는 사람이 알아보기 위한 이름표일 뿐 자유롭게 지어도 돼요.

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from utils.config import USER_API_DIR, read_user_api_files


class ApiManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 키 관리")
        self.resize(600, 400)

        self._current_filename: str | None = None

        root = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(QLabel("등록된 API 키 파일"))
        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._on_select)
        left.addWidget(self.file_list, 1)

        list_btn_row = QHBoxLayout()
        add_btn = QPushButton("추가")
        add_btn.clicked.connect(self._add_file)
        delete_btn = QPushButton("삭제")
        delete_btn.clicked.connect(self._delete_file)
        list_btn_row.addWidget(add_btn)
        list_btn_row.addWidget(delete_btn)
        left.addLayout(list_btn_row)

        right = QVBoxLayout()
        self.detail_label = QLabel("왼쪽에서 파일을 선택하세요.")
        right.addWidget(self.detail_label)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("예: MOUSER_API_KEY=여기에_실제_키")
        right.addWidget(self.editor, 1)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("저장")
        save_btn.clicked.connect(self._save_current)
        save_row.addWidget(save_btn)
        right.addLayout(save_row)

        hint = QLabel(
            f"파일은 {USER_API_DIR} 폴더에 저장돼요.\n형식: KEY=VALUE (한 줄에 하나씩, 예: MOUSER_API_KEY=실제_키값)"
        )
        hint.setStyleSheet("color: gray;")
        hint.setWordWrap(True)
        right.addWidget(hint)

        root.addLayout(left, 1)
        root.addLayout(right, 2)

        self._reload_list()

    def _reload_list(self, select: str | None = None):
        self.file_list.blockSignals(True)
        self.file_list.clear()
        entries = read_user_api_files()
        for filename in sorted(entries.keys()):
            self.file_list.addItem(QListWidgetItem(filename))
        self.file_list.blockSignals(False)

        if select:
            matches = self.file_list.findItems(select, Qt.MatchFlag.MatchExactly)
            if matches:
                self.file_list.setCurrentItem(matches[0])
                return
        if self.file_list.count():
            self.file_list.setCurrentRow(0)
        else:
            self._current_filename = None
            self.editor.clear()
            self.detail_label.setText("등록된 API 키 파일이 없습니다. '추가' 버튼으로 만들어보세요.")

    def _on_select(self, current, _previous):
        if current is None:
            return
        filename = current.text()
        self._current_filename = filename
        path = USER_API_DIR / filename
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            content = ""
            QMessageBox.warning(self, "읽기 오류", f"{filename}을 읽을 수 없습니다: {e}")
        self.editor.setPlainText(content)
        self.detail_label.setText(f"파일: {filename}")

    def _add_file(self):
        name, ok = QInputDialog.getText(self, "API 키 파일 추가", "파일 이름 (예: JY_MOUSER_API_KEY):")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not name.lower().endswith(".txt"):
            name += ".txt"
        if any(c in name for c in '\\/:*?"<>|'):
            QMessageBox.warning(self, "이름 오류", '파일 이름에 \\ / : * ? " < > | 문자는 쓸 수 없습니다.')
            return

        USER_API_DIR.mkdir(parents=True, exist_ok=True)
        path = USER_API_DIR / name
        if path.exists():
            QMessageBox.warning(self, "이미 있음", f"'{name}' 파일이 이미 있습니다.")
            return
        path.write_text("KEY=VALUE\n", encoding="utf-8")
        self._reload_list(select=name)

    def _delete_file(self):
        if not self._current_filename:
            return
        reply = QMessageBox.question(self, "삭제 확인", f"'{self._current_filename}' 파일을 정말 삭제할까요?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        path = USER_API_DIR / self._current_filename
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "삭제 실패", str(e))
            return
        self._current_filename = None
        self._reload_list()

    def _save_current(self):
        if not self._current_filename:
            QMessageBox.information(self, "안내", "먼저 왼쪽에서 파일을 선택하거나 '추가'로 새로 만들어주세요.")
            return
        path = USER_API_DIR / self._current_filename
        try:
            USER_API_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "저장 실패", str(e))
            return
        QMessageBox.information(self, "저장됨", f"'{self._current_filename}'에 저장했습니다.")

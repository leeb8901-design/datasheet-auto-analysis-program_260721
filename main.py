# 프로그램의 시작점이에요. 창(QApplication)을 만들고 메인 화면을 띄워요.

import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

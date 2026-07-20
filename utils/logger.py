# 로그 메시지를 파일에 기록하고, 동시에 화면(GUI)에도 전달해주는 파일이에요.

import datetime

from utils.config import LOG_DIR


class Logger:
    """"이런 일이 있었어요"를 파일에 남기고, 등록된 콜백(예: GUI 로그창)에도 전달해요."""

    def __init__(self):
        LOG_DIR.mkdir(exist_ok=True)
        today = datetime.date.today().isoformat()
        self.log_path = LOG_DIR / f"{today}.log"
        self._callbacks = []  # "로그 생기면 나도 알려줘"라고 등록한 함수들이에요.

    def add_callback(self, callback):
        # GUI 등에서 이 함수를 불러서 자기 자신을 등록해요.
        self._callbacks.append(callback)

    def log(self, message: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        for callback in self._callbacks:
            callback(line)


# 프로그램 전체가 이 하나의 로거를 같이 써요 (로그 파일이 여러 개로 쪼개지지 않게).
logger = Logger()

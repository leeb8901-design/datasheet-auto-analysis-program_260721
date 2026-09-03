# 프로그램 전체에서 같이 쓰는 설정값(경로, 열쇠 카드, 힌트 단어 등)을 모아둔 파일이에요.

import os
from pathlib import Path

from dotenv import load_dotenv

# 이 파일(utils/config.py)의 부모의 부모 폴더가 곧 프로그램 폴더예요.
APP_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = APP_DIR / "Download_ datasheets"  # 다운받은 PDF를 저장할 폴더
LOG_DIR = APP_DIR / "logs"  # 로그 파일을 저장할 폴더
# 매핑맵의 '사용가이드라인' 시트를 그대로 복사해 올 마스터 파일이에요. 출력지를 만들 때 읽기만 하고,
# 절대 저장(수정)하지 않아요 — 마스터의 데이터/서식을 항상 그대로 보존하기 위해서예요.
#
# 주의: "Windchill_217F_Mapping_Template.xlsx"(복사본이 아닌 원본 파일명)는 자가진단으로 확인해보니
# 이미 색상이 전부 사라진 상태였어요(CLAUDE.md가 경고하는 "LibreOffice 재저장으로 색이 통째로
# 사라진 사고"와 정확히 같은 증상 — 사용가이드라인 시트의 칠해진 칸이 12개에서 0개로 줄어있었고,
# 매핑맵에 있던 6개 부품 데이터도 사라져 있었어요). 그래서 색과 데이터가 온전히 남아있는 백업
# 파일("- 복사본")을 마스터로 사용해요.
MAPPING_TEMPLATE_PATH = APP_DIR / "Windchill_217F_Mapping_Template - 복사본.xlsx"

# "입력지 양식" 버튼(2026-09-03 이전 이름 "Import 양식")이 그대로 복사해서 내보내는 마스터
# 파일이에요. vba/Import_User.xlsx를 내보내요(2026-09-02 사용자 확정 - 처음엔 입력지
# Data_list_217F.xlsx를 내보냈다가, 같은 날 Import_User.xlsx로 바꿨고, 실제 파일 위치를 vba/
# 폴더로 옮기면서 경로도 그에 맞춤). 사용자가 이 파일을 받아 품번을 채워 넣고 다시 입력지로
# 쓰는 흐름이에요. 프로그램은 이 파일을 읽기만 하고(복사만) 절대 수정하지 않아요.
IMPORT_TEMPLATE_PATH = APP_DIR / "vba" / "Import_User.xlsx"

# .env 파일(MOUSER_API_KEY 등)을 찾는 순서예요. 예전엔 APP_DIR(프로그램이 설치된 폴더) 안에서만
# 찾았는데, 설치파일(Setup.exe)로 배포한 뒤 프로그램 폴더를 옮기거나 다른 위치에 다시 설치하면
# 그 안에 있던 .env가 새 위치로 안 따라와서 Mouser API 키를 매번 다시 입력해야 하는 문제가
# 있었어요(사용자 확정, 2026-09-04 - "설치파일로 배포했을 때만" 재현됨: installer/set_api_key.ps1
# 이 예전엔 프로그램 폴더 안에 .env를 만들었는데, 그 폴더가 재설치/이동으로 바뀌면 예전 .env는
# 새 프로그램과 물리적으로 분리돼 버림).
#
# 그래서 프로그램 설치 위치와 완전히 분리된, OS 표준 사용자별 설정 폴더(%APPDATA%, 로밍 - 앱을
# 어디에 설치하든/재설치하든 안 바뀌는 사람별 고정 자리)를 1순위로 보고, 예전 방식(APP_DIR/.env,
# 이 저장소를 직접 열어 개발할 때 편하게 쓰던 자리)은 2순위로 남겨둬요.
USER_CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "DatasheetDownloader"
USER_ENV_PATH = USER_CONFIG_DIR / ".env"
LEGACY_ENV_PATH = APP_DIR / ".env"
ENV_SEARCH_PATHS = [USER_ENV_PATH, LEGACY_ENV_PATH]  # diagnostics/self_check.py가 안내 메시지에 씀

_env_path_used = next((p for p in ENV_SEARCH_PATHS if p.exists()), None)
load_dotenv(dotenv_path=_env_path_used or USER_ENV_PATH)

# .env가 예전 자리(프로그램 폴더 안)에만 있으면, 새 표준 위치로 한 부 복사해둬요(이미 있으면
# 안 건드림) - 그래야 다음에 프로그램 폴더를 옮기거나 재설치해도 API 키가 안 사라져요.
if _env_path_used == LEGACY_ENV_PATH and not USER_ENV_PATH.exists():
    try:
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        USER_ENV_PATH.write_text(LEGACY_ENV_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass  # 마이그레이션이 안 돼도 프로그램 동작엔 지장 없어요(다음 실행 때 다시 시도됨)

MOUSER_API_KEY = os.environ.get("MOUSER_API_KEY")

# 입력지(사용자가 품번을 채워 넣은 원본)와 출력지(프로그램이 처리 결과를 써넣는 사본)를 분리해요.
# 입력지는 절대 수정하지 않아요. "출력지 저장" 버튼을 눌러야 그 시점에 저장 위치를 물어보는데,
# 이 폴더/이름을 그 저장 대화상자에 기본으로 채워줘요. 폴더는 "입력지 양식"(IMPORT_TEMPLATE_PATH)
# 파일이 있는 곳과 항상 같게 유지해요(2026-09-03 사용자 확정 - 하드코딩된 별도 경로 대신
# IMPORT_TEMPLATE_PATH.parent를 그대로 가져다 써서, 나중에 입력지 양식 위치가 바뀌어도 둘이
# 저절로 같이 따라가게 함). 이름은 "Export_Root"로 고정(2026-09-02 사용자 확정).
EXPORT_DEFAULT_DIR = IMPORT_TEMPLATE_PATH.parent
OUTPUT_DEFAULT_NAME = "Export_Root"

# 엑셀을 불러올 때 우선적으로 찾는 시트 이름이에요.
PART_LIST_SHEET_NAME = "부품리스트"
# "이게 부품번호 칸이구나!"를 알아내기 위한 힌트 단어들이에요.
PART_NUMBER_KEYWORDS = ["품번", "part number", "part no", "partnumber", "pn", "mpn"]
# "이게 제조사 칸이구나!"를 알아내기 위한 힌트 단어들이에요.
MANUFACTURER_KEYWORDS = ["제조사", "manufacturer", "mfr", "mfg"]
# "이게 품명 칸이구나!"를 알아내기 위한 힌트 단어들이에요 (PSA 시트 부품 행에 품명을 같이 적어요).
PART_NAME_KEYWORDS = ["품명", "품 명", "part name", "description"]

# 프로그램이 엑셀에 자동으로 채워 넣는 결과 컬럼들의 이름이에요.
COL_DOWNLOAD_STATUS = "다운로드 상태"
COL_ANALYSIS_STATUS = "분석 상태"
# 클릭하면 열리는 링크로 채워져요 - 다운로드 성공이면 받아둔 PDF 파일, 실패했으면 웹검색으로
# 찾아낸 참고 URL(VBA 도우미가 이 칸을 읽어서 대신 받아와요). 한 칸에서 둘 다 처리해요.
COL_DATASHEET_LINK = "데이터시트 링크"
COL_ERROR_MESSAGE = "오류내용"
COL_UNRESOLVED_FIELDS = "미확인 항목"  # 확신도가 낮거나 값을 못 찾은 필드 이름들을 적어두는 칸이에요.
COL_SAVE_PATH = "저장 경로"  # 이 부품의 PDF가 저장되어야 할 정확한 경로 (VBA 도우미가 이 칸에 저장해요).
RESULT_COLUMNS = [
    COL_DOWNLOAD_STATUS,
    COL_ANALYSIS_STATUS,
    COL_DATASHEET_LINK,
    COL_ERROR_MESSAGE,
    COL_UNRESOLVED_FIELDS,
    COL_SAVE_PATH,
]

# '작업지'(입력지 Data_list_217F.xlsx)에 분석 결과를 되쓸 때, 앱 내부 결과 컬럼 -> 작업지의 실제
# 컬럼(헤더 이름) 매핑이에요. 사용자가 정한 규칙(2026-07-31):
#   다운로드 상태 -> '상태' / 데이터시트 링크 -> '데이터시트 다운로드 링크' / 저장 경로 -> '분석된 데이터시트 링크'
# 여기 없는 결과(분석 상태/오류내용/미확인 항목)는 작업지에 쓰지 않아요.
# ExcelResultWriter가 이 매핑으로 결과를 해당 컬럼에 써넣어요.
WORKSHEET_RESULT_COLUMN_MAP = {
    COL_DOWNLOAD_STATUS: "상태",
    COL_DATASHEET_LINK: "데이터시트 다운로드 링크",
    COL_SAVE_PATH: "분석된 데이터시트 링크",
}

# 다운로드 상태로 쓰는 값들이에요. 여러 곳에서 같은 글자를 쓰도록 여기 모아뒀어요.
STATUS_PENDING = "대기"
STATUS_SKIPPED_EXISTING = "이미 있음"
STATUS_DOWNLOADING = "다운로드 중"
STATUS_SUCCESS_MOUSER = "성공 (Mouser)"
STATUS_SUCCESS_WEB = "성공 (웹)"
STATUS_SUCCESS_VBA = "성공 (VBA)"  # 엑셀의 VBA 도우미 매크로가 직접 받아온 경우 (datasheet_helper.bas 참고).
# 자동 다운로드가 실패한 뒤, 사용자가 데이터시트를 직접 받아 Download_ datasheets 폴더에 넣고
# "새로고침" 버튼으로 찾아낸 경우(2026-09-03 도입). ui/main_window.py의 _refresh_datasheet_folder 참고.
STATUS_SUCCESS_MANUAL = "성공 (수동)"
STATUS_FAILED = "실패"

# 분석 상태로 쓰는 값들이에요.
ANALYSIS_PENDING = "대기"  # 아직 분석을 시도하지 않음 (다운로드 실패 등)
ANALYSIS_NEEDS_REVIEW = "검토필요"  # 분류/추출은 됐지만 확신도 낮은 칸이 남아있음
ANALYSIS_DONE = "확인완료"  # 채워야 할 칸을 모두 사람이 확인함
ANALYSIS_FAILED = "분류불가"  # 대분류/소분류 자체를 판별하지 못함

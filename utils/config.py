# 프로그램 전체에서 같이 쓰는 설정값(경로, 열쇠 카드, 힌트 단어 등)을 모아둔 파일이에요.

from pathlib import Path

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

# API 키 관리 (2026-09-04부터 — .env 대신 "메모장" 파일 방식으로 교체)
# ------------------------------------------------------------------------------------------
# 예전엔 .env 파일 하나에 KEY=VALUE를 몰아넣었는데, 이제는 API마다 텍스트 파일 하나씩으로
# 나눠서 관리해요. User_API/ 폴더 안에 파일을 하나 두면(예: JY_MOUSER_API_KEY.txt, 내용은
# "MOUSER_API_KEY=실제키값") 그게 그대로 하나의 API 항목이 돼요. 파일명은 사람이 보기 위한
# 이름표일 뿐이고, 프로그램이 실제로 쓰는 건 파일 "내용"의 KEY=VALUE예요 — 그래서 파일명은
# 자유롭게 지어도 되고(예: "회사키_MOUSER_API_KEY.txt"), 내용의 KEY(예: MOUSER_API_KEY)만
# 맞으면 프로그램이 알아서 찾아요. GUI(ui/api_manager_dialog.py, "API 키 관리" 버튼)로
# 파일 목록 확인/내용 수정/추가/삭제를 할 수 있어요.
USER_API_DIR = APP_DIR / "User_API"


def _parse_key_value_lines(text: str) -> dict[str, str]:
    """"KEY=VALUE" 줄들을 딕셔너리로 바꿔요. 빈 줄/#으로 시작하는 줄은 무시해요."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def read_user_api_files() -> dict[str, dict]:
    """User_API/ 폴더 안의 파일들을 전부 읽어요. 매번 새로 읽어서, GUI에서 방금 고친 값이
    프로그램 재시작 없이 바로 반영돼요. {파일명: {"path": Path, "content": 원문, "values": {KEY: VALUE}}}
    """
    entries: dict[str, dict] = {}
    if not USER_API_DIR.is_dir():
        return entries
    for path in sorted(USER_API_DIR.iterdir()):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        entries[path.name] = {"path": path, "content": content, "values": _parse_key_value_lines(content)}
    return entries


def get_api_key(name: str) -> str | None:
    """User_API/ 안의 모든 파일을 통틀어, KEY 이름이 name(대소문자 무시)과 일치하는 값을 찾아요."""
    target = name.strip().lower()
    for entry in read_user_api_files().values():
        for key, value in entry["values"].items():
            if key.strip().lower() == target and value:
                return value
    return None


def get_mouser_api_key() -> str | None:
    return get_api_key("MOUSER_API_KEY")

# 입력지(사용자가 품번을 채워 넣은 원본)와 출력지(프로그램이 처리 결과를 써넣는 사본)를 분리해요.
# 입력지는 절대 수정하지 않아요. "출력지 저장" 버튼을 눌러야 그 시점에 저장 위치를 물어보는데,
# 이 이름을 그 저장 대화상자에 기본 파일명으로 채워줘요. 폴더는 더 이상 여기서 지정하지 않고
# "입력지 양식" 버튼과 똑같이 파일명만 넘겨서 Qt가 마지막으로 연 폴더를 기본으로 보여주게 함
# (2026-09-05 사용자 확정 - 두 저장 대화상자의 기본 위치가 항상 같게 동작해야 함). 이름은
# "Export_Root"로 고정(2026-09-02 사용자 확정).
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

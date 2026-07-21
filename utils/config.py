# 프로그램 전체에서 같이 쓰는 설정값(경로, 열쇠 카드, 힌트 단어 등)을 모아둔 파일이에요.

import os
from pathlib import Path

from dotenv import load_dotenv

# 이 파일(utils/config.py)의 부모의 부모 폴더가 곧 프로그램 폴더예요.
APP_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = APP_DIR / "datasheets"  # 다운받은 PDF를 저장할 폴더
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

# "Import 양식" 버튼이 그대로 복사해서 내보내는 마스터 파일이에요. VBA 다운로드 도우미 매크로
# (vba/datasheet_helper.bas)가 이미 내장되어 있고, 부품리스트 시트 헤더도 output_builder.py가
# 만드는 구조와 똑같이 맞춰뒀어요. 프로그램은 이 파일을 읽기만 하고 절대 수정하지 않아요.
IMPORT_TEMPLATE_PATH = APP_DIR / "vba" / "Import_양식.xlsm"

# .env 파일에 적어둔 값(예: MOUSER_API_KEY)을 읽어와요.
load_dotenv(dotenv_path=APP_DIR / ".env")

MOUSER_API_KEY = os.environ.get("MOUSER_API_KEY")

# 엑셀을 불러올 때 우선적으로 찾는 시트 이름이에요.
PART_LIST_SHEET_NAME = "부품리스트"
# "이게 부품번호 칸이구나!"를 알아내기 위한 힌트 단어들이에요.
PART_NUMBER_KEYWORDS = ["품번", "part number", "part no", "partnumber", "pn", "mpn"]
# "이게 제조사 칸이구나!"를 알아내기 위한 힌트 단어들이에요.
MANUFACTURER_KEYWORDS = ["제조사", "manufacturer", "mfr", "mfg"]

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

# 다운로드 상태로 쓰는 값들이에요. 여러 곳에서 같은 글자를 쓰도록 여기 모아뒀어요.
STATUS_PENDING = "대기"
STATUS_SKIPPED_EXISTING = "이미 있음"
STATUS_DOWNLOADING = "다운로드 중"
STATUS_SUCCESS_MOUSER = "성공 (Mouser)"
STATUS_SUCCESS_WEB = "성공 (웹)"
STATUS_SUCCESS_VBA = "성공 (VBA)"  # 엑셀의 VBA 도우미 매크로가 직접 받아온 경우 (datasheet_helper.bas 참고).
STATUS_FAILED = "실패"

# 분석 상태로 쓰는 값들이에요.
ANALYSIS_PENDING = "대기"  # 아직 분석을 시도하지 않음 (다운로드 실패 등)
ANALYSIS_NEEDS_REVIEW = "검토필요"  # 분류/추출은 됐지만 확신도 낮은 칸이 남아있음
ANALYSIS_DONE = "확인완료"  # 채워야 할 칸을 모두 사람이 확인함
ANALYSIS_FAILED = "분류불가"  # 대분류/소분류 자체를 판별하지 못함

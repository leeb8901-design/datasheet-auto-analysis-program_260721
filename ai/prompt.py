# AI에게 데이터시트 PDF에서 뽑아달라고 요청할 항목/규칙을 정의하는 파일이에요.
# 실제 분석 규칙(색상 규칙, 대분류/소분류 판별 기준, 단위 규칙 등)의 전체 내용은
# 프로젝트 루트의 CLAUDE.md에 있으니, 분석 로직을 만들 때는 그 문서를 꼭 같이 참고하세요.
# 여기 있는 값들은 CLAUDE.md가 가리키는 data/ 폴더의 진짜 데이터를 그대로 불러오는 역할만 해요
# (숫자나 이름을 새로 지어내지 않고, 검증된 원본 파일을 재사용하기 위해서예요).

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 데이터시트로는 절대 못 채우는(=사람이 값을 넣으면 안 되는) 칸들이에요. 참고로 실제 엑셀에서
# 이 칸들이 "데이터시트" 색이 아닌지는 PSA 시트 정의행 색이 최종 결정권을 가져요(psa_writer.py가
# 색으로 한 번 더 걸러줌) - 이 목록은 그 전에 애초에 추출 시도조차 안 하기 위한 1차 필터예요.
# CLAUDE.md 4번 참고.
PTC_AUTO_DETERMINED_FIELDS = {
    "Pi Q Value",
    "Case Temp Override",
    "Junction Temp Override",
    "Frame Temp Override",
    "Hot Spot Temperature",
}
# "Years in Production"은 여기 있었으나 2026-08-27에 뺐어요 - Revision History의 양산/최초
# 출시 연도로 추정 가능하다고 판단해서(ai/reference.py의 resolve_years_in_production 참고),
# 이제 시도는 하고 못 찾으면 기본값(">=2.0")을 씀. CLAUDE.md 7번 결정 로그 참고.
UNKNOWN_FROM_DATASHEET_FIELDS = {
    "Initial Temp Rise",
}


def load_headers() -> list[str]:
    # 매핑맵 컬럼 헤더(품번, Part Category, Part Subcategory + PSA 파라미터들)를 그대로 불러와요.
    # headers.json은 build_reference.py가 새 입력지에서 subcat_params와 함께 생성해요(어휘 일치 보장).
    with open(DATA_DIR / "headers.json", encoding="utf-8") as f:
        return json.load(f)


def load_subcat_params() -> list[dict]:
    # 서브카테고리마다 어떤 파라미터 컬럼이 적용되는지 정리된 목록이에요(새 입력지 PSA 기준).
    # 각 항목: {"category": ..., "subcategory": ..., "params": [해당 서브카테고리에 적용되는 헤더 이름들]}
    with open(DATA_DIR / "subcat_params.json", encoding="utf-8") as f:
        return json.load(f)


def get_fields_for_subcategory(category: str, subcategory: str) -> list[str]:
    # 특정 대분류/소분류에 실제로 값을 채워야 하는(흰색) 파라미터만 골라줘요.
    # (보라/분홍 규칙 컬럼은 여기서 자동으로 빠져요 — 데이터시트로 채우면 안 되는 칸이니까요.)
    for entry in load_subcat_params():
        if entry["category"] == category and entry["subcategory"] == subcategory:
            skip = PTC_AUTO_DETERMINED_FIELDS | UNKNOWN_FROM_DATASHEET_FIELDS
            return [p for p in entry["params"] if p not in skip]
    return []


# AI에게 실제로 보낼 질문 틀이에요. {part_number}, {fields} 자리에 실제 값이 채워져요.
# 나중에 진짜 AI를 연결할 때는 이 문장만 다듬으면 되고, 다른 코드는 안 건드려도 돼요.
PDF_ANALYSIS_PROMPT_TEMPLATE = """다음은 전자부품 데이터시트 PDF입니다.
General Description/Features 문단을 근거로 MIL-HDBK-217F Notice 2 기준 대분류(Part Category)와
소분류(Part Subcategory)를 판별한 뒤, 아래 파라미터 값을 데이터시트에서 찾아 JSON으로 반환해주세요.
값을 찾을 수 없는 항목은 null로 표시해주세요.

부품번호: {part_number}

추출할 파라미터:
{fields}

JSON 형식으로만 답변해주세요.
"""

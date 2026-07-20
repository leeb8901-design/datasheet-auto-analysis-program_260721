# PDF 데이터시트를 실제로 분석해서 필요한 정보를 뽑아내는 파일이에요.
# 순서: ① PDF에서 글자 뽑기 -> ② 대분류/소분류 판별 -> ③ 그 소분류에 필요한 파라미터만 골라서
# 값 찾기. 규칙은 전부 프로젝트 루트의 CLAUDE.md와 '사용가이드라인' 시트를 코드로 옮긴 거예요.
#
# 이건 사람이 데이터시트를 읽고 판단하는 걸 흉내 내는 best-effort 분석이라서, 확신이 낮은
# 항목("confidence"가 낮거나 값이 None인 항목)은 반드시 사람이 데이터시트 원문과 대조해서
# 확인해야 해요 — CLAUDE.md의 "미확인 항목" 칸이 바로 이 확인이 필요한 항목들이에요.

from pathlib import Path

from ai.classifier import classify
from ai.field_extractor import extract_field_values
from ai.pdf_text import extract_text
from ai.prompt import get_fields_for_subcategory, load_headers


def analyze_pdf(pdf_path: Path, fields: list[str] | None = None) -> dict:
    """PDF 파일을 분석해서 분류 결과 + 필드값을 돌려줘요.

    반환값:
        {
            "category": 대분류 이름 또는 None,
            "category_confidence": 대분류 확신 점수(0이면 근거를 못 찾음),
            "subcategory": 소분류 이름 또는 None,
            "subcategory_confidence": 소분류 확신 점수,
            "fields": {필드이름: 값(문자열) 또는 None, ...},
            "unmatched_fields": 값을 못 찾은 필드 이름 리스트,
        }

    fields를 직접 안 주면, 판별된 소분류에 맞는 필드 목록을 자동으로 골라요
    (get_fields_for_subcategory 사용 — 보라/분홍 규칙 컬럼은 자동으로 제외됨).
    """
    text = extract_text(pdf_path)

    result = classify(text)
    category = result["category"]
    subcategory = result["subcategory"]

    if fields is None:
        fields = get_fields_for_subcategory(category, subcategory) if category and subcategory else []

    field_values = extract_field_values(text, fields)
    unmatched = [name for name, value in field_values.items() if value is None]

    return {
        "category": category,
        "category_confidence": result["category_score"],
        "subcategory": subcategory,
        "subcategory_confidence": result["subcategory_score"],
        "fields": field_values,
        "unmatched_fields": unmatched,
    }


def get_extraction_fields() -> list[str]:
    # 매핑맵의 127개 컬럼 헤더(품번, Part Category, Part Subcategory + 파라미터 124개)를 그대로 알려줘요.
    return load_headers()

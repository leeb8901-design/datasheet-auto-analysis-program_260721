# PDF 데이터시트를 실제로 분석해서 필요한 정보를 뽑아내는 파일이에요.
# 순서: ① PDF에서 글자 뽑기 -> ② 대분류/소분류 판별 -> ③ 그 소분류에 필요한 파라미터만 골라서
# 값 찾기. 규칙은 전부 프로젝트 루트의 CLAUDE.md와 '사용가이드라인' 시트를 코드로 옮긴 거예요.
#
# 이건 사람이 데이터시트를 읽고 판단하는 걸 흉내 내는 best-effort 분석이라서, 확신이 낮은
# 항목("confidence"가 낮거나 값이 None인 항목)은 반드시 사람이 데이터시트 원문과 대조해서
# 확인해야 해요 — CLAUDE.md의 "미확인 항목" 칸이 바로 이 확인이 필요한 항목들이에요.

from pathlib import Path

from ai import reference
from ai.classifier import classify
from ai.field_extractor import extract_field_values
from ai.pdf_text import extract_text
from ai.prompt import get_fields_for_subcategory, load_headers


def analyze_pdf(pdf_path: Path, fields: list[str] | None = None, thermal_mode: str = "case") -> dict:
    """PDF 파일을 분석해서 분류 결과 + 필드값을 돌려줘요.

    thermal_mode: 열저항 기준. "case"=θJC(접합-케이스, 217F 표 폴백), "ambient"=θJA(접합-주위,
    데이터시트 값만). GUI에서 사용자가 골라요.

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

    # 참고자료(data/*.json) 기반 자동 판정 — 규칙 기반 추출로 비어 있는 값만 채워요
    # (기존 추출값은 절대 덮어쓰지 않아요). 참고표로 자동 판정한 값은 확신도가 낮으니
    # reference_notes에 근거를 남겨 사람이 데이터시트 원문과 대조하게 해요.
    reference_notes: dict[str, str] = {}
    if category and subcategory:
        _apply_reference(text, category, subcategory, field_values, reference_notes, thermal_mode)

    unmatched = [name for name, value in field_values.items() if value is None]

    return {
        "category": category,
        "category_confidence": result["category_score"],
        "subcategory": subcategory,
        "subcategory_confidence": result["subcategory_score"],
        "fields": field_values,
        "unmatched_fields": unmatched,
        "reference_notes": reference_notes,
    }


def _apply_reference(text, category, subcategory, field_values, notes, thermal_mode="case"):
    """data/*.json 참고표로 Quality Level·Thermal Resistance를 채워요(빈 값일 때만).

    thermal_mode: "case"=θJC(패키지별 217F 표 폴백) / "ambient"=θJA(데이터시트 값만)."""
    # Quality Level: 동작 온도 범위 -> 등급 (서브카테고리가 미허용이면 Commercial 고정)
    if "Quality Level" in field_values and not field_values["Quality Level"]:
        # 'Operating Temperature'는 현 입력지 정본의 파라미터 목록에 없어 field로는 안 잡혀요.
        # 그래서 추출된 필드값이 있으면 그걸, 없으면 PDF 원문 전체에서 동작온도 범위를 파싱해요.
        temp_source = field_values.get("Operating Temperature") or text
        lo, hi = reference.parse_temp_range(temp_source)
        bucket = reference.classify_temp_range(lo, hi)
        grade, fixed = reference.resolve_quality_level(category, subcategory, bucket)
        if grade:
            field_values["Quality Level"] = grade
            notes["Quality Level"] = (
                f"온도범위({bucket}) 기반 자동판정"
                + (" · Commercial 고정(미허용)" if fixed else "")
            )

    # Thermal Resistance: 데이터시트에 없으면 사용자가 고른 기준(θJC/θJA)으로 폴백
    if "Thermal Resistance" in field_values and not field_values["Thermal Resistance"]:
        # case 모드에서만 본문에서 패키지를 찾아 θJC 표를 조회해요(ambient는 표를 안 씀).
        pkg = reference.find_package_in_text(category, text) if thermal_mode == "case" else None
        val, src = reference.resolve_thermal_resistance(category, pkg, mode=thermal_mode)
        if val is not None:
            field_values["Thermal Resistance"] = str(val)
            notes["Thermal Resistance"] = src + (f" ({pkg})" if pkg else "")
        else:
            notes["Thermal Resistance"] = src


def get_extraction_fields() -> list[str]:
    # 매핑맵 컬럼 헤더(품번, Part Category, Part Subcategory + PSA 파라미터들)를 그대로 알려줘요.
    return load_headers()

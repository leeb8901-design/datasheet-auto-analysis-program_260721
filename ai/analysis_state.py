# 부품 하나의 분석 결과(대분류/소분류/필드값 + 사람이 확인했는지 여부)를 담는 상자예요.
# ui(검토 다이얼로그)와 excel/pdf 출력 단계가 모두 이 모양을 그대로 주고받아요.

from dataclasses import dataclass, field


@dataclass
class PartAnalysis:
    category: str | None
    category_confidence: int
    subcategory: str | None
    subcategory_confidence: int
    fields: dict[str, str | None]
    # 사람이 화면에서 값을 확인(또는 수정)한 필드 이름들. 여기 없는 필드는 값이 있어도 "검토 전"이에요.
    confirmed_fields: set[str] = field(default_factory=set)
    # 참고표(data/*.json)로 자동 판정한 필드의 근거 문구예요 {필드이름: 근거}. analyze_pdf가 채워요.
    # 사람이 데이터시트 원문과 대조할 때 "이 값이 왜 이렇게 정해졌는지"를 알려주는 용도라, 값 자체는
    # fields에 들어가고 근거만 여기 따로 남겨요 (unresolved_summary가 "미확인 항목" 칸에 붙여줘요).
    reference_notes: dict[str, str] = field(default_factory=dict)

    def unresolved_field_names(self) -> list[str]:
        """아직 사람이 확인 안 한 필드 이름들 (값이 없거나, 값은 있지만 미확인인 것 모두 포함)."""
        return [name for name in self.fields if name not in self.confirmed_fields]

    def unresolved_summary(self) -> str:
        """'미확인 항목' 칸에 넣을 문자열이에요. 아직 확인 안 한 필드 이름을 나열하되,
        참고표로 자동 판정된 필드는 근거(reference_notes)를 함께 붙여서 사람이 왜 그 값이
        됐는지 알고 대조하게 해요. 예) 'Quality Level: 온도범위(-40~85) 기반 자동판정, Pins'."""
        parts: list[str] = []
        for name in self.unresolved_field_names():
            note = self.reference_notes.get(name)
            parts.append(f"{name}: {note}" if note else name)
        return ", ".join(parts)

    def is_fully_confirmed(self) -> bool:
        return len(self.unresolved_field_names()) == 0

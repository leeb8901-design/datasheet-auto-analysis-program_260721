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

    def unresolved_field_names(self) -> list[str]:
        """아직 사람이 확인 안 한 필드 이름들 (값이 없거나, 값은 있지만 미확인인 것 모두 포함)."""
        return [name for name in self.fields if name not in self.confirmed_fields]

    def is_fully_confirmed(self) -> bool:
        return len(self.unresolved_field_names()) == 0

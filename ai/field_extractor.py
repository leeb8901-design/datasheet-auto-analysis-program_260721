# 데이터시트 본문 글자에서, 필요한 파라미터 값을 최선을 다해(best-effort) 찾아내는 파일이에요.
#
# 데이터시트마다 표 형식이 천차만별이라, 완벽하게 찾을 수는 없어요. 여기서는 "파라미터 이름
# 근처에 숫자+단위가 있으면 그게 값일 것이다"라는 단순한 방식으로 찾습니다. 그래서 여기서
# 찾은 값은 참고용이고, 최종적으로는 사람이 데이터시트 원문과 대조해서 확인해야 해요
# (CLAUDE.md의 "미확인 항목" 개념과 같아요 — 자신 없는 값은 그대로 두고 사람이 채우게 해요).
#
# Temperature Rise처럼 다른 값들을 계산해서 만들어야 하는 파라미터(Operating Power ×
# Thermal Resistance)는 여기서 자동 계산하지 않아요. 단위를 잘못 다루면 조용히 틀린 값이
# 들어갈 위험이 커서(CLAUDE.md 7번 항목에서 실제로 문제가 됐던 부분), 그런 계산은 사람이
# 직접 하도록 남겨둡니다.

import re

# 필드 이름 -> 데이터시트에 흔히 쓰이는 동의어/기호들이에요. 여기 없는 필드는 아예 검색을
# 시도하지 않고 None으로 남겨요 (억지로 아무 숫자나 주워오지 않기 위해서).
#
# 이 사전엔 "숫자+단위"로 표현되는 값만 넣었어요. "Package Type"(SOIC-8 등), "Type",
# "Quality Level", "Application" 같은 글자값(카테고리) 필드는 숫자 패턴으로 찾을 수 없어서
# 여기서는 다루지 않고, 항상 None으로 남아 사람이 직접 채우게 돼요.
FIELD_SYNONYMS: dict[str, list[str]] = {
    "Operating Voltage": ["operating voltage", "supply voltage", r"\bvcc\b", r"\bvdd\b"],
    "Rated Voltage": ["rated voltage", "maximum voltage", r"\bvrrm\b", "breakdown voltage"],
    "Operating Current": ["operating current", "supply current", "quiescent current", r"\biq\b"],
    "Rated Current": ["rated current", "maximum current", "forward current"],
    "Operating Power": ["power dissipation", "operating power"],
    "Power Rating": ["power rating", "rated power"],
    "Thermal Resistance": ["thermal resistance", r"theta\s*ja", r"\brthja\b", r"θja"],
    "Pins": ["number of pins", "pin count", r"\bpins?\b"],
    "Frequency": ["frequency", "clock frequency", "operating frequency"],
    "Capacitance": ["capacitance"],
    "Resistance": ["resistance"],
    "# of Bits": ["bits", "bit width", "word length"],
    "Max Junction Temp": [r"tj\s*\(?max\)?", "maximum junction temperature"],
    "Operating Temperature": ["operating temperature"],
    "Applied DC Voltage": ["applied dc voltage", "dc voltage rating"],
    "AC RMS Voltage": ["ac rms voltage", "rms voltage"],
}

# "숫자(소수점/콤마 가능) + 선택적 단위 글자" 패턴이에요. 예: "3.3V", "150 mW", "10kΩ", "1 to 5V"
# 줄바꿈은 절대 안 건너뛰어요 — 안 그러면 다음 줄에 있는 엉뚱한 필드 값을 잘못 주워올 수 있어요.
_NUMBER_UNIT = r"[-+]?\d[\d,]*\.?\d*[ \t]*(?:to[ \t]*[-+]?\d[\d,]*\.?\d*)?[ \t]*[a-zA-Zµμ°%/Ω]{0,6}"


def extract_field_values(text: str, fields: list[str]) -> dict[str, str | None]:
    """필드 이름별로 값을 찾아 {필드이름: 값 또는 None} 형태로 돌려줘요."""
    values: dict[str, str | None] = {}
    for field in fields:
        synonyms = FIELD_SYNONYMS.get(field)
        values[field] = _find_value_near(text, synonyms) if synonyms else None
    return values


def _find_value_near(text: str, synonyms: list[str]) -> str | None:
    # 동의어 바로 뒤(같은 줄, 40글자 이내)에 숫자+단위가 있으면 그 값을 가져와요.
    for synonym in synonyms:
        pattern = rf"{synonym}[^\n]{{0,40}}?({_NUMBER_UNIT})"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None

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
    "Operating Current": [
        "operating current", "supply current", "quiescent current",
        r"quiescent\s+power\s+supply\s+current",  # 예: "Quiescent power supply current" (Icc)
        r"\biq\b", r"\bicc\b",
    ],
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

# "동의어 근처 40글자 안의 숫자"라는 규칙만으로는 전혀 무관한 숫자를 주워오는 사고가 실제로
# 있었어요 - 예: "Package thermal resistance... (4-layer standard test PCB..."에서 "4"를,
# "Voltage at any input pin -0.3V..."에서 "-0.3V"를 각각 열저항/핀개수로 잘못 채운 사례.
# 이 필드들은 값의 "모양"이 명확히 정해져 있으니(열저항=항상 °C/W 단위, 핀개수=항상 순수
# 숫자), 찾은 값 전체가 이 모양과 정확히 일치할 때만 인정해요 - 안 맞으면 그 자리는 버리고
# (re.finditer로) 다음 후보를 계속 찾다가, 끝내 못 찾으면 None으로 남겨서 사람이 채우게 해요.
FIELD_VALUE_PATTERNS: dict[str, str] = {
    "Thermal Resistance": r"[-+]?\d[\d,]*\.?\d*\s*(?:°|º)?\s*C\s*/\s*W",
    "Pins": r"[-+]?\d[\d,]*",
    # "Power Rating (50 VDC max.)"처럼 라벨 바로 뒤에 전압 상한을 괄호로 병기한 경우, 그 전압을
    # 전력값으로 잘못 주운 사고가 있었음(2026-09-03, TC33X-2-102E: "50 VDC"를 Power Rating으로
    # 잘못 채움 - 진짜 값은 다음 줄의 "0.15 watt"). Power Rating은 항상 W(att) 단위라, 단위가
    # W/watt가 아닌 후보는 버려요(ai/reference.py의 find_power_rating_watts()가 줄바꿈을 넘어
    # 진짜 값을 대신 찾아요).
    "Power Rating": r"[-+]?\d[\d,]*\.?\d*\s*[mM]?[wW](?:att)?s?",
    # "Power Dissipation (Note 7) ... 500 mW"처럼 각주 번호가 라벨 바로 옆에 있으면, 그 각주
    # 번호를 전력값으로 잘못 주운 사고가 있었음(2026-09-03, BZT52C8V2-7: "(Note 7)"의 "7"을
    # Operating Power로 잘못 채움 - 단위 없는 맨 숫자였음). Power Rating과 같은 이유로
    # W(att)/mW 단위가 확실한 후보만 인정해요.
    "Operating Power": r"[-+]?\d[\d,]*\.?\d*\s*[mM]?[wW](?:att)?s?",
}


def extract_field_values(text: str, fields: list[str]) -> dict[str, str | None]:
    """필드 이름별로 값을 찾아 {필드이름: 값 또는 None} 형태로 돌려줘요."""
    values: dict[str, str | None] = {}
    for field in fields:
        synonyms = FIELD_SYNONYMS.get(field)
        values[field] = _find_value_near(text, field, synonyms) if synonyms else None
    return values


def _find_value_near(text: str, field: str, synonyms: list[str]) -> str | None:
    # 동의어 뒤(같은 줄, 40글자 이내)에 숫자+단위가 있으면 그 값을 가져와요. 그 필드의 값
    # "모양"이 정해져 있으면(FIELD_VALUE_PATTERNS) 모양이 맞는 후보를 찾을 때까지 계속 찾아요.
    value_pattern = FIELD_VALUE_PATTERNS.get(field)
    for synonym in synonyms:
        pattern = rf"{synonym}[^\n]{{0,40}}?({_NUMBER_UNIT})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1).strip()
            if not value:
                continue
            if value_pattern and not re.fullmatch(value_pattern, value, re.IGNORECASE):
                continue
            return value
    return None

# 데이터시트 글 안에서 "이 부품이 대분류/소분류로 뭐에 해당하나"를 골라내는 파일이에요.
# 규칙은 Windchill_217F_Mapping_Template.xlsx의 '사용가이드라인' 시트에 적힌 판별 문구를
# 그대로 코드로 옮긴 거예요 (CLAUDE.md 5번 항목과 같은 내용).
#
# 완전히 정확할 순 없어요 — 사람(또는 AI)이 문단을 읽고 판단하는 걸 키워드 매칭으로
# 흉내 내는 거라서, 애매한 경우도 있습니다. 그래서 결과에 confidence(확신도)를 같이
# 돌려줘서, 낮으면 사람이 다시 확인하도록 해요.

import re

from ai.prompt import load_subcat_params

# 대분류를 찾는 힌트 단어들이에요. 값은 (핵심단어 리스트, 가중치)예요 — 가중치가 높을수록
# 그 단어가 나오면 더 확실한 증거로 쳐줘요.
CATEGORY_KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "Relay": [(r"\brelay\b", 3), (r"coil voltage", 1), (r"contact rating", 1)],
    "Optical Device": [
        (r"\bled\b", 3), (r"light[- ]emitting diode", 3), (r"photodiode", 3),
        (r"phototransistor", 3), (r"optocoupler", 3), (r"opto-?isolator", 3),
        (r"laser diode", 3),
    ],
    "Rotating Device": [(r"\bmotor\b", 3)],
    "Switching Device": [
        (r"toggle switch", 3), (r"pushbutton switch", 3), (r"tactile switch", 3),
        (r"tact switch", 3), (r"rocker switch", 3), (r"slide switch", 3),
        (r"dip switch", 3), (r"rotary switch", 3),
    ],
    "Connection": [(r"\bconnector\b", 3), (r"\bsocket\b", 2), (r"\bheader\b", 1)],
    "Resistor": [(r"\bresistor\b", 3), (r"resistance", 1), (r"power rating", 1), (r"\bohm", 1)],
    "Capacitor": [(r"\bcapacitor\b", 3), (r"capacitance", 1), (r"\bwvdc\b", 1)],
    "Inductor": [(r"\binductor\b", 3), (r"\bcoil\b", 1), (r"\btransformer\b", 2), (r"inductance", 1)],
    "Semiconductor": [
        (r"\bdiode\b", 2), (r"\brectifier\b", 2), (r"\btransistor\b", 1),
        (r"\bbjt\b", 2), (r"\bfet\b", 2), (r"\bmosfet\b", 2), (r"\bthyristor\b", 3),
    ],
    "Miscellaneous": [
        (r"\bfuse\b", 3), (r"crystal resonator", 3), (r"\bbattery\b", 3),
        (r"\bfilter\b", 2), (r"\bantenna\b", 3), (r"\boscillator\b", 2),
        (r"\bgyroscope\b", 3), (r"loudspeaker", 3), (r"\bmicrophone\b", 3),
    ],
    "Integrated Circuit": [
        (r"integrated circuit", 3), (r"\bic\b", 1), (r"\bdip\b", 1), (r"\bsoic\b", 1),
        (r"\btssop\b", 1), (r"\bqfn\b", 1), (r"operational amplifier", 2), (r"\bop amp\b", 2),
        (r"\bcomparator\b", 2), (r"voltage regulator", 2), (r"\bldo\b", 2),
        (r"voltage reference", 2), (r"\blogic gate\b", 2), (r"microcontroller", 2), (r"\bmcu\b", 2),
        (r"\bnand\b", 3), (r"\bnor\b", 3), (r"flip-?flop", 3), (r"\bdecoder\b", 2),
        (r"\bmultiplexer\b", 2), (r"\bmux\b", 2), (r"\bregister\b", 1),
    ],
}

# Integrated Circuit 소분류 판별 규칙이에요 (사용가이드라인 27~34번 예시를 그대로 옮김).
IC_SUBCATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Logic, CGA or ASIC": [
        # "\band\b"/"\bor\b"/"\bnor\b" 단독은 절대 쓰지 않아요 — 논리 게이트를 뜻하는 게 아니라 그냥
        # 흔한 영어 단어(접속사 and/or, 법적 고지문의 "...nor for any infringements...")에도 걸려서,
        # 아무 데이터시트나 "Logic"으로 잘못 분류시키는 사고가 실제로 있었어요.
        r"\bgate\b", r"\bnand\b", r"\bnor gate\b", r"\band gate\b", r"\bor gate\b", r"\bxor\b",
        r"\bdecoder\b", r"flip-?flop", r"\bbuffer\b", r"\binverter\b", r"logic gate",
    ],
    "Linear": [
        r"operational amplifier", r"\bop amp\b", r"\bcomparator\b", r"voltage regulator",
        r"\bldo\b", r"voltage reference",
    ],
    "Memory": [r"\bsram\b", r"\bdram\b", r"\bflash\b", r"\beeprom\b", r"\brom\b"],
    "Microprocessor": [r"\bcpu\b", r"\bmcu\b", r"microcontroller", r"processor core"],
    "GaAs Digital": [r"\bgaas\b.*digital", r"gallium arsenide.*digital"],
    "GaAs MMIC": [r"\bmmic\b", r"\bgaas\b"],
    # 'Custom' 소분류는 새 입력지(97개 정본)에 없어서 뽑아도 매핑맵에서 누락되므로 제거함.
    "Bubble Memory": [r"bubble memory"],
    "EEPROM": [r"\beeprom\b"],
    "PAL, PLA": [r"\bpal\b", r"\bpla\b"],
    "SAW - Surface Acoustic Wave": [r"surface acoustic wave", r"\bsaw filter\b"],
    "VHSIC/VLSI CMOS": [r"\bvhsic\b", r"\bvlsi\b"],
}

# subcat_params.json의 소분류 이름 자체로는 못 찾는 경우를 위한 보충 규칙이에요.
# 예: "Detector, Isolator, Emitter" 소분류는 본문에 "LED"라고만 적혀있어도 뜻이 통해요.
OPTICAL_SUBCATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Detector, Isolator, Emitter": [
        r"\bled\b", r"light[- ]emitting diode", r"photodiode", r"phototransistor",
        r"optocoupler", r"opto-?isolator",
    ],
    "Laser Diode": [r"laser diode"],
}

# Semiconductor 대분류 안에서도, 짧은 소분류 이름("Transistor" 등)은 서로 겹치는 단어가 많아서
# (예: "Power"라는 단어 하나로 엉뚱한 소분류가 골라짐) 대표적인 것들은 따로 규칙을 둬요.
SEMICONDUCTOR_SUBCATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Diode": [r"\bdiode\b", r"\brectifier\b", r"\bzener\b", r"\btvs\b", r"transient voltage suppressor"],
    "Si FET": [r"\bmosfet\b", r"\bfet\b"],
    "Transistor": [r"\bbjt\b", r"bipolar transistor", r"\bnpn\b", r"\bpnp\b"],
    "Thyristor": [r"\bthyristor\b", r"\bscr\b", r"\btriac\b"],
    "Unijunction Transistor": [r"unijunction"],
}


def _score_and_hits(text: str, keyword_weights: list[tuple[str, int]]) -> tuple[int, int]:
    hits = [weight for pattern, weight in keyword_weights if re.search(pattern, text, re.IGNORECASE)]
    return sum(hits), len(hits)


def classify_category(text: str) -> tuple[str | None, int]:
    """텍스트를 보고 대분류를 골라요. (대분류 이름 또는 None, 확신 점수)를 돌려줘요.

    확신 점수가 0이면 아무 단서도 못 찾은 거라서 Miscellaneous로 보되, 사람이 확인해야 해요.

    가중치 합(점수)이 동점인 카테고리가 여러 개면, 서로 다른 근거가 더 많이 맞은(hit 개수가 많은)
    쪽을 우선해요. 예: "TSSOP"+"LDO" 2개 근거로 맞은 Integrated Circuit이, 응용회로 설명 중 우연히
    한 번 언급된 "resistor" 1개 근거만으로 같은 점수를 낸 Resistor보다 더 신뢰할 만해요. (실제로 LDO
    레귤레이터 데이터시트가 이 동점 상황 때문에 Resistor로 잘못 분류된 사례를 확인해서 고쳤어요.)
    """
    scored = {category: _score_and_hits(text, keywords) for category, keywords in CATEGORY_KEYWORDS.items()}
    best_score = max(score for score, _ in scored.values())
    if best_score == 0:
        return "Miscellaneous", 0

    tied = [category for category, (score, _) in scored.items() if score == best_score]
    best_category = max(tied, key=lambda category: scored[category][1])
    return best_category, best_score


def classify_subcategory_generic(text: str, category: str) -> tuple[str | None, int]:
    """IC 이외의 대분류에서, subcat_params.json에 있는 소분류 이름 자체를 힌트로 찾아봐요.

    예: "Diode" 소분류는 이름 자체가 "diode"라서, 본문에 "diode"가 있으면 매칭돼요.
    소분류 이름의 괄호 부분(예: "(RB, RBR)")은 산업 코드라서 이름만으로 비교해요.
    """
    entries = [e for e in load_subcat_params() if e["category"] == category]
    scores = {}
    for entry in entries:
        subcategory = entry["subcategory"]
        # 괄호 앞부분만 이름으로 써요. 예: "Composition (RC, RCR)" -> "Composition"
        name = re.sub(r"\s*\(.*?\)\s*", " ", subcategory).strip()
        words = [w for w in re.split(r"[,/ ]+", name) if len(w) >= 3]
        # \b(단어 경계)를 꼭 써야 해요. 안 그러면 "FET"가 "MOSFET" 안에서도 매칭돼버려서
        # (부분 문자열 매칭 사고), 엉뚱한 소분류가 골라질 수 있어요.
        score = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE))
        scores[subcategory] = score
    if not scores:
        return None, 0
    best_subcategory = max(scores, key=scores.get)
    best_score = scores[best_subcategory]
    if best_score == 0:
        return None, 0
    return best_subcategory, best_score


def _classify_with_keyword_dict(text: str, keyword_dict: dict[str, list[str]]) -> tuple[str | None, int]:
    scores = {sub: sum(1 for p in patterns if re.search(p, text, re.IGNORECASE)) for sub, patterns in keyword_dict.items()}
    best_subcategory = max(scores, key=scores.get)
    best_score = scores[best_subcategory]
    if best_score == 0:
        return None, 0
    return best_subcategory, best_score


def classify_subcategory(text: str, category: str) -> tuple[str | None, int]:
    if category == "Integrated Circuit":
        subcategory, score = _classify_with_keyword_dict(text, IC_SUBCATEGORY_KEYWORDS)
        if subcategory:
            return subcategory, score
        return classify_subcategory_generic(text, category)
    if category == "Optical Device":
        subcategory, score = _classify_with_keyword_dict(text, OPTICAL_SUBCATEGORY_KEYWORDS)
        if subcategory:
            return subcategory, score
        return classify_subcategory_generic(text, category)
    if category == "Semiconductor":
        subcategory, score = _classify_with_keyword_dict(text, SEMICONDUCTOR_SUBCATEGORY_KEYWORDS)
        if subcategory:
            return subcategory, score
        return classify_subcategory_generic(text, category)
    return classify_subcategory_generic(text, category)


def classify(text: str) -> dict:
    """전체 분류 결과를 한 번에 돌려줘요: 대분류, 소분류, 각각의 확신 점수."""
    category, category_score = classify_category(text)
    subcategory, subcategory_score = (None, 0)
    if category:
        subcategory, subcategory_score = classify_subcategory(text, category)
    return {
        "category": category,
        "category_score": category_score,
        "subcategory": subcategory,
        "subcategory_score": subcategory_score,
    }

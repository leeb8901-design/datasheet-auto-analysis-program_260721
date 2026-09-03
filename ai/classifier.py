# 데이터시트 글 안에서 "이 부품이 대분류/소분류로 뭐에 해당하나"를 골라내는 파일이에요.
# 규칙은 Windchill_217F_Mapping_Template.xlsx의 '사용가이드라인' 시트에 적힌 판별 문구를
# 그대로 코드로 옮긴 거예요 (CLAUDE.md 5번 항목과 같은 내용).
#
# 완전히 정확할 순 없어요 — 사람(또는 AI)이 문단을 읽고 판단하는 걸 키워드 매칭으로
# 흉내 내는 거라서, 애매한 경우도 있습니다. 그래서 결과에 confidence(확신도)를 같이
# 돌려줘서, 낮으면 사람이 다시 확인하도록 해요.

import re

from ai.prompt import load_subcat_params

# 데이터시트 첫머리(보통 제목이 있는 자리)만 잘라내는 길이예요. extract_text()가 페이지를
# 그냥 개행으로 이어붙여서 정확한 "1페이지 끝"은 몰라도, 300자면 제목/부제 정도는 항상 포함돼요.
_TITLE_CHARS = 300


def _extract_title(text: str) -> str:
    return (text or "")[:_TITLE_CHARS]


# 제목에 "Oscillator"가 있으면 대분류/소분류를 한 번에 확정하는 특수 규칙이에요(2026-09-03
# 도입, DSC8123CI5 실전 분석에서 확정). 발진기(오실레이터)는 MIL-HDBK-217F에서 수정 진동자
# (Quartz Crystal) 모델로 신뢰도를 계산하는 게 표준 관례예요. 대분류(classify_category)를
# 통째로 제목 우선으로 바꾸는 건 위험하다고 이미 확인됐지만(IS31FL3296이 제목의 "LED" 때문에
# Optical Device로 잘못 판정되는 회귀가 있었음), "oscillator"처럼 오탐 위험이 낮고 제품명
# 자체에만 쓰이는 특정 단어 하나는 예외로 둬요 - MCU 등 다른 IC가 "내장 오실레이터" 기능을
# 본문에서 설명하는 것과 구분하려고 제목(첫머리)만 봐요.
_OSCILLATOR_TITLE_RE = re.compile(r"\bOscillator\b")  # 대소문자까지 그대로 - 진짜 제목 우선용
_OSCILLATOR_TITLE_RE_LOOSE = re.compile(r"\boscillators?\b", re.IGNORECASE)  # 못 찾으면 이걸로
# 표지가 2단(컬럼) 레이아웃이면(ai/pdf_text.py의 2단 분리 로직), 제목 배너가 좌/우로 쪼개져서
# 왼쪽 절반 텍스트(General Description 등 본문)를 다 뽑은 "다음에" 오른쪽 절반의 나머지 제목
# 글자가 나오는 경우가 있어요(실측 확인, DSC8123CI5: "Oscillator"가 300자가 아니라 1200자
# 부근에서야 나타남). 그래서 이 규칙의 창은 일반 _extract_title(300자)보다 넉넉하게 둬요.
_OSCILLATOR_WINDOW_CHARS = 1500
OSCILLATOR_CATEGORY = "Miscellaneous"
OSCILLATOR_SUBCATEGORY = "Quartz Crystal"


def find_oscillator_title_evidence(text: str) -> str | None:
    """제목 부근에서 "Oscillator" 문구를 원문 그대로 찾아 돌려줘요(PDF 주석 근거용 + 이 특수
    규칙을 적용할지 말지 결정하는 게이트). 대문자로 시작하는 정확한 "Oscillator"(제품명에
    쓰이는 진짜 제목 표기)를 먼저 찾고, 없으면 소문자/복수형("oscillators")도 인정해요.
    없으면 None."""
    window = (text or "")[:_OSCILLATOR_WINDOW_CHARS]
    m = _OSCILLATOR_TITLE_RE.search(window)
    if m:
        return m.group(0)
    m = _OSCILLATOR_TITLE_RE_LOOSE.search(window)
    return m.group(0) if m else None


# 제목에 "Transistor"가 있으면 대분류를 Semiconductor로 확정하는 특수 규칙이에요(2026-09-04
# 도입, 2SB1260T100R 실전 분석에서 확정). 이 트랜지스터 데이터시트가 응용 예시("Applications:
# Motor driver, LED driver")에 "LED"를 한 번 언급했다는 이유만으로, CATEGORY_KEYWORDS의
# "\bled\b"(weight 3)가 "\btransistor\b"(weight 1)를 이겨서 Optical Device로 잘못 분류된 걸
# 확인함 - 대분류를 통째로 제목 우선으로 바꾸는 건 위험하다고 이미 확인됐지만(IS31FL3296
# 회귀), "oscillator"와 마찬가지로 "transistor"도 제목에 있을 때 오탐 위험이 낮은 단어라
# 예외로 둠.
_TRANSISTOR_TITLE_RE = re.compile(r"\btransistor\b", re.IGNORECASE)
_TRANSISTOR_WINDOW_CHARS = 500
TRANSISTOR_CATEGORY = "Semiconductor"


def find_transistor_title_evidence(text: str) -> str | None:
    """제목(첫머리)에서 "Transistor" 문구를 원문 그대로 찾아 돌려줘요(이 특수 규칙을 적용할지
    말지 결정하는 게이트). 없으면 None."""
    window = (text or "")[:_TRANSISTOR_WINDOW_CHARS]
    m = _TRANSISTOR_TITLE_RE.search(window)
    return m.group(0) if m else None


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
    "Inductor": [
        (r"\binductor\b", 3), (r"\bcoil\b", 1), (r"\btransformer\b", 2), (r"inductance", 1),
        # 페라이트 비드(2026-09-03 도입, BLM21PG121SN1D 사례) - 본문에 저항/임피던스(Ω) 스펙이
        # 같이 나와서 Resistor로 잘못 분류된 사고가 있었음(다른 카테고리 후보가 없어서 약한
        # 근거만으로 Resistor가 이겨버림). "ferrite bead"는 이 부품군을 정확히 가리키는 구라
        # 오탐 위험이 낮아 weight 3.
        (r"ferrite bead", 3),
    ],
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
        # "\bnor\b" 단독은 절대 쓰지 않아요 — 법적 고지문("...nor the rights of others...")의
        # 접속사 "nor"에도 걸려서, 아무 데이터시트나 Integrated Circuit으로 잘못 분류시키는
        # 사고가 실제로 있었어요(아래 IC_SUBCATEGORY_KEYWORDS의 "\bnor gate\b"와 같은 이유).
        (r"\bnand\b", 3), (r"\bnor gate\b", 3), (r"flip-?flop", 3), (r"\bdecoder\b", 2),
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
        # "Driver"(LED 드라이버, 모터 드라이버 등)는 항상 Linear로 분류하기로 확정됨(사용자 결정,
        # IS31FL3296 LED 드라이버 사례). 아날로그 전류/전압을 연속적으로 구동하는 IC라서
        # Logic이나 Microprocessor보다 Linear에 가깝다고 봄.
        r"\bdriver\b",
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

# Capacitor 탄탈럼 소분류 판별 규칙이에요 (2026-09-03 도입, T322D106K035AT 사례로 시작 ->
# 2026-09-04, T495C107K010ATE100 사례로 수정). 소분류 이름 자체에 "Tant"라는 줄임말이 들어있어서
# (예: "Solid, Elec, Tant (CSR)"), 제네릭 매칭(classify_subcategory_generic - 소분류 이름의
# 단어를 단어 경계(\b)로 그대로 찾음)이 본문의 "Tantalum"과 절대 못 맞음 - "Tant"는 "Tantalum"의
# 앞부분일 뿐 독립된 단어가 아니라서(\bTant\b가 "Tantalum" 안에서 매칭 안 됨). 실제로 이것
# 때문에 탄탈럼 축방향(Through-Hole) 커패시터가 "Feed Through, Paper"로 잘못 분류된 사고가
# 있었음(본문에 있던 "Through-Hole"의 "Through"가 그 소분류 이름과 우연히 겹쳐서 매칭됨).
#
# 처음엔 실장 방식(through-hole/molded 대 chip/SMD/surface mount 대 wet)으로 CSR/CWR/CLR 3종을
# 구분했는데, "Tantalum Surface Mount Capacitors"(T495 시리즈)가 표면실장인데도 CSR이 맞다는
# 걸 확인해서(사용자 확정) "surface mount/chip/SMD"는 CWR을 가리키는 신뢰할 수 있는 신호가
# 아니라고 판단, CWR 판별 자체를 뺐음 - **탄탈럼은 습식(wet/non-solid)이라는 명시가 없는 한
# 항상 CSR(고체) 기본값**으로 단순화함(classify_tantalum_subcategory 참고, 아래).
_TANTALUM_WET_RE = re.compile(r"tantalum.{0,30}(wet|non-?solid)|(wet|non-?solid).{0,30}tantalum", re.IGNORECASE)
_TANTALUM_RE = re.compile(r"\btantalum\b", re.IGNORECASE)
TANTALUM_SOLID_SUBCATEGORY = "Solid, Elec, Tant (CSR)"
TANTALUM_NONSOLID_SUBCATEGORY = "Nonsolid, Elec, Tant (CL, CLR, CRL)"


def classify_tantalum_subcategory(text: str) -> tuple[str | None, str | None]:
    """탄탈럼 커패시터를 CSR(고체)/CLR(습식) 중에서 골라요. (소분류, 근거문구) 튜플 - 탄탈럼
    자체가 없으면 (None, None). wet/non-solid 명시가 있으면 CLR, 그 외(대부분)는 기본값 CSR."""
    if not text:
        return None, None
    m = _TANTALUM_WET_RE.search(text)
    if m:
        return TANTALUM_NONSOLID_SUBCATEGORY, m.group(0)
    m = _TANTALUM_RE.search(text)
    if m:
        return TANTALUM_SOLID_SUBCATEGORY, m.group(0)
    return None, None

# Inductor 소분류 판별 규칙이에요 (2026-09-03 도입, BLM21PG121SN1D 실전 분석에서 확정).
# 페라이트 비드(EMI 노이즈 억제용 수동 부품)는 소분류 이름 "Coil"과 본문 표현이 안 겹쳐서
# (데이터시트가 "coil"이라고 안 부르고 "ferrite bead"라고만 부름) 제네릭 매칭이 못 찾음 -
# 그래서 전용 사전을 둠. 앞으로 분석되는 모든 페라이트 비드 부품에 공통 적용.
INDUCTOR_SUBCATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Coil": [r"ferrite bead", r"\bchoke\b"],
    "Transformer": [r"\btransformer\b", r"pulse transformer"],
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
    "Diode": [
        # 제목에 자주 나오는 온전한 구(phrase)를 먼저 둬요(2026-09-03 도입, BZT52C8V2-7 사례) -
        # find_subcategory_evidence는 이 리스트를 순서대로 훑어 "처음 매칭된 패턴"의 문구를
        # PDF 주석 근거로 쓰는데, 뒤에 있는 \bdiode\b/\bzener\b 같은 낱말 하나짜리 패턴이 먼저
        # 걸리면 "SURFACE MOUNT ZENER DIODE"라는 제목 전체가 아니라 "DIODE" 한 단어만 하이라이트
        # 됨 - 사용자가 제목 전체에 표시해달라고 확정해서 온전한 구를 우선함.
        r"surface mount zener diode",
        r"zener diode",
        r"\bdiode\b", r"\brectifier\b", r"\bzener\b", r"\btvs\b", r"transient voltage suppressor",
    ],
    "Si FET": [r"\bmosfet\b", r"\bfet\b"],
    "Transistor": [
        # Diode와 같은 이유로(2026-09-04 도입, 2SB1260T100R 사례) 제목에 자주 나오는 온전한
        # 구를 낱말 패턴보다 먼저 둬요 - "PNP" 한 단어가 아니라 "Middle Power Transistor"
        # 전체가 PDF 주석 근거로 잡히게.
        r"middle power transistor", r"power transistor",
        r"\bbjt\b", r"bipolar transistor", r"\bnpn\b", r"\bpnp\b",
    ],
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

    (2026-09-03: 대분류도 제목 우선으로 바꿔봤다가 되돌림 - IS31FL3296-UTLS4-TR("LED 드라이버"
    IC)의 제목에 "LED"가 크게 들어있어서 제목만 보면 Optical Device로 잘못 판정되는 회귀가
    실측 확인됨. 소분류(아래 classify_subcategory_generic)는 제목 우선이 안전했지만, 대분류는
    전체 본문 가중치 합산 방식을 그대로 유지함 - 이미 검증된 판정이 title 힌트 하나 때문에
    뒤집히면 안 되니까. 단, "oscillator"/"transistor"(제목에 있을 때만)는 예외 - 아래 참고.)
    """
    if find_oscillator_title_evidence(text):
        return OSCILLATOR_CATEGORY, 3
    if find_transistor_title_evidence(text):
        return TRANSISTOR_CATEGORY, 3

    scored = {category: _score_and_hits(text, keywords) for category, keywords in CATEGORY_KEYWORDS.items()}
    best_score = max(score for score, _ in scored.values())
    if best_score == 0:
        return "Miscellaneous", 0

    tied = [category for category, (score, _) in scored.items() if score == best_score]
    best_category = max(tied, key=lambda category: scored[category][1])
    return best_category, best_score


def _score_generic_names(haystack: str, entries: list[dict]) -> dict[str, int]:
    scores = {}
    for entry in entries:
        subcategory = entry["subcategory"]
        # 괄호 앞부분만 이름으로 써요. 예: "Composition (RC, RCR)" -> "Composition"
        name = re.sub(r"\s*\(.*?\)\s*", " ", subcategory).strip()
        words = [w for w in re.split(r"[,/ ]+", name) if len(w) >= 3]
        # \b(단어 경계)를 꼭 써야 해요. 안 그러면 "FET"가 "MOSFET" 안에서도 매칭돼버려서
        # (부분 문자열 매칭 사고), 엉뚱한 소분류가 골라질 수 있어요.
        score = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", haystack, re.IGNORECASE))
        scores[subcategory] = score
    return scores


def classify_subcategory_generic(text: str, category: str) -> tuple[str | None, int]:
    """IC 이외의 대분류에서, subcat_params.json에 있는 소분류 이름 자체를 힌트로 찾아봐요.

    예: "Diode" 소분류는 이름 자체가 "diode"라서, 본문에 "diode"가 있으면 매칭돼요.
    소분류 이름의 괄호 부분(예: "(RB, RBR)")은 산업 코드라서 이름만으로 비교해요.

    제목(첫머리)을 먼저 보고, 거기서 하나라도 걸리면 그 결과를 써요(2026-09-03 도입) - 본문
    어딘가에 스쳐 지나가는 단어 하나 때문에 엉뚱한 소분류로 잘못 판정되는 사고를 막기 위해서.
    실제 사고: 탄탈럼 "Through-Hole" 커패시터가, 본문 다른 곳의 "Through-Hole"의 "Through"가
    "Feed Through, Paper" 소분류 이름과 우연히 겹쳐서 잘못 분류됨 - 제목("Tantalum Through-Hole
    Capacitors")만 봤다면 애초에 "Through" 매칭이 아니라(탄탈럼은 전용 사전으로 따로 처리,
    CAPACITOR_SUBCATEGORY_KEYWORDS 참고) 다른 소분류가 골라졌을 상황.
    """
    entries = [e for e in load_subcat_params() if e["category"] == category]

    title_scores = _score_generic_names(_extract_title(text), entries)
    if title_scores:
        best_title = max(title_scores, key=title_scores.get)
        if title_scores[best_title] > 0:
            return best_title, title_scores[best_title]

    scores = _score_generic_names(text, entries)
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
    if category == OSCILLATOR_CATEGORY and find_oscillator_title_evidence(text):
        return OSCILLATOR_SUBCATEGORY, 3
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
    if category == "Capacitor":
        # 제목을 먼저 보고(2026-09-03, T322D106K035AT 사례), 안 걸리면 본문 전체에서 찾아요.
        subcategory, _ = classify_tantalum_subcategory(_extract_title(text))
        if not subcategory:
            subcategory, _ = classify_tantalum_subcategory(text)
        if subcategory:
            return subcategory, 1
        return classify_subcategory_generic(text, category)
    if category == "Inductor":
        # 제목을 먼저 보고(2026-09-03, BLM21PG121SN1D 사례), 안 걸리면 본문 전체에서 찾아요.
        subcategory, score = _classify_with_keyword_dict(_extract_title(text), INDUCTOR_SUBCATEGORY_KEYWORDS)
        if not subcategory:
            subcategory, score = _classify_with_keyword_dict(text, INDUCTOR_SUBCATEGORY_KEYWORDS)
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


# ---------------------------------------------------------------------------
# 판정 근거 문구 찾기 (PDF 주석용, 2026-09-03 도입)
# ---------------------------------------------------------------------------
# 프로그램(신뢰도 분석 버튼)이 분류/추출한 값을 데이터시트 PDF 위에 하이라이트로 표시해주는
# 기능을 만들면서(datasheet/annotator.py), "이 값을 왜 골랐는지" 원문 속 정확한 문구가
# 필요해졌어요. 위 classify_category/classify_subcategory는 점수만 돌려주지 실제로 어떤
# 키워드가 맞았는지는 안 알려줘서, 같은 키워드 목록을 다시 훑어 "실제로 매칭된 문구 그대로"를
# 찾아주는 함수를 따로 뒀어요(판정 로직 자체는 절대 안 건드림 - 그냥 사후에 "왜"를 설명하는
# 용도라 분리함).
def find_category_evidence(text: str, category: str) -> str | None:
    """이 대분류를 고르는 데 가장 크게 기여한(가중치가 가장 높은) 키워드가 실제로 매칭된
    문구를 원문 그대로 돌려줘요. 못 찾으면 None."""
    if category == OSCILLATOR_CATEGORY:
        ev = find_oscillator_title_evidence(text)
        if ev:
            return ev
    best_text, best_weight = None, -1
    for pattern, weight in CATEGORY_KEYWORDS.get(category, []):
        m = re.search(pattern, text, re.IGNORECASE)
        if m and weight > best_weight:
            best_text, best_weight = m.group(0), weight
    return best_text


def find_subcategory_evidence(text: str, category: str, subcategory: str) -> str | None:
    """이 소분류를 고르는 데 쓰인 키워드가 실제로 매칭된 문구를 원문 그대로 돌려줘요.
    classify_subcategory와 같은 순서(전용 사전 -> 제네릭)로 찾아요. 못 찾으면 None."""
    if category == OSCILLATOR_CATEGORY and subcategory == OSCILLATOR_SUBCATEGORY:
        ev = find_oscillator_title_evidence(text)
        if ev:
            return ev
    if category == "Capacitor" and subcategory in (TANTALUM_SOLID_SUBCATEGORY, TANTALUM_NONSOLID_SUBCATEGORY):
        _, ev = classify_tantalum_subcategory(_extract_title(text))
        if not ev:
            _, ev = classify_tantalum_subcategory(text)
        if ev:
            return ev
    keyword_dict = {
        "Integrated Circuit": IC_SUBCATEGORY_KEYWORDS,
        "Optical Device": OPTICAL_SUBCATEGORY_KEYWORDS,
        "Semiconductor": SEMICONDUCTOR_SUBCATEGORY_KEYWORDS,
        "Inductor": INDUCTOR_SUBCATEGORY_KEYWORDS,
    }.get(category)
    if keyword_dict and subcategory in keyword_dict:
        for pattern in keyword_dict[subcategory]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(0)
        return None

    # 제네릭 매칭(classify_subcategory_generic)과 같은 방식: 소분류 이름 자체의 단어들로 찾아요.
    name = re.sub(r"\s*\(.*?\)\s*", " ", subcategory).strip()
    words = [w for w in re.split(r"[,/ ]+", name) if len(w) >= 3]
    for w in words:
        m = re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None

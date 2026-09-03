# 엑셀에서 생성된 data/*.json 참고파일을 읽어, 분석 시 품질등급/열저항/MTBF 변환을 판정하는 파일이에요.
# 이 파일은 tools/build_reference.py 가 만든 JSON만 읽고, 값을 새로 지어내지 않아요.
# (엑셀=원본, JSON=생성물. 엑셀을 고치면 build_reference.py를 다시 돌려 JSON을 갱신하면 돼요.)
#
# 규칙 출처: '217F 분석기준' / '유효성 목록' 시트 (Data_list_217F 입력지). CLAUDE.md도 함께 참고.

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=None)
def _load(name: str):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 온도 범위 -> 품질등급 (운용 온도별 품질등급 + 서브카테고리 허용여부)
# ---------------------------------------------------------------------------
# 온도 범위 파싱용 패턴. 핵심: "숫자 <범위기호> 숫자" 형태만 후보로 보고(품번/패키지코드의
# 낱개 숫자를 온도로 오검출하지 않도록), 그 범위가 온도 단위(℃/°C) 또는 온도 문맥(operating/
# junction/storage 등) 옆에 있을 때만 채택해요. 동작온도가 있으면 저장온도보다 우선해요.
#
# 부호 문자에 아스키 하이픈(-)뿐 아니라 en dash(–, U+2013) 등 타이포그래피 대시도 포함해요.
# PDF마다 음수 부호를 en dash로 쓰는 경우가 실제로 있어서("Temperature range: –40 to +85 °C",
# Skyworks 데이터시트에서 발견) 아스키 하이픈만 인식하면 "-40"의 부호를 통째로 놓쳐서 40으로
# 잘못 읽고, 그 결과 품질등급 버킷이 더 좁은(불리한) 쪽으로 잘못 판정되는 사고가 있었음.
_TR_SIGN = r"[-+‐-―−]"  # ascii -/+ , 각종 하이픈/대시(U+2010~2015), 진짜 마이너스(U+2212)
_TR_NUM = rf"{_TR_SIGN}?\d{{1,3}}"
_TR_CONN = r"(?:to|~|∼|…|\.\.\.|–|—)"
# 단위가 두 번째 숫자 뒤에만 한 번 오는 표기("-55 to 125 C")뿐 아니라, 숫자마다 단위가 반복되는
# 표기("-40°C to +125°C")도 있어요 - 후자를 놓치면 범위 자체를 통째로 못 찾게 돼요(실제로
# 이 패턴 때문에 동작온도 파싱이 통째로 실패한 사례가 있었음). 그래서 첫 번째 숫자 뒤에도
# 단위가 선택적으로 올 수 있게 허용해요.
_TR_UNIT_INLINE = r"(?:°|º)\s*[CF]\b|℃|℉"
_TR_RANGE_RE = re.compile(
    rf"(?P<a>{_TR_NUM})\s*(?P<u1>{_TR_UNIT_INLINE})?\s*{_TR_CONN}\s*(?P<b>{_TR_NUM})", re.IGNORECASE
)
_TR_UNIT_AFTER = re.compile(rf"\s*(?:{_TR_UNIT_INLINE})", re.IGNORECASE)


def _to_int(raw: str) -> int:
    # int()는 아스키 '-'/'+'만 부호로 인정해요. en dash 등 타이포그래피 대시로 잡힌 부호는
    # (전부 마이너스 의미) int() 앞에서 아스키 '-'로 정규화해야 해요 - 안 그러면 ValueError가 나요.
    if raw and raw[0] not in "-+" and raw[0].isdigit() is False:
        raw = "-" + raw[1:]
    return int(raw)
_TR_OP_KW = re.compile(r"operat|ambient|junction|\bT[aj]\b|\bTopr?\b", re.IGNORECASE)
_TR_STG_KW = re.compile(r"storage|\bTstg\b|\bTstrg\b", re.IGNORECASE)
_TR_TEMP_KW = re.compile(r"temperatur|operat|ambient|junction|storage|\bT[ajs]\b|\bTstg\b|\bTopr?\b", re.IGNORECASE)


def parse_temp_range(text: str | None):
    """'-40 to +85°C', '-55 ~ +125', 'operating junction temperature -55 to 150 C' 같은 문구에서
    동작 온도 범위의 최저/최고(℃)를 뽑아요. 실패하면 (None, None).

    - "숫자 to/~/… 숫자" 범위 형태만 후보로 봐요(품번 'LT1963'의 196 같은 낱개 숫자 오검출 방지).
    - 그 범위가 온도 단위(℃/C)나 온도 문맥 옆에 있을 때만 채택해요.
    - 동작온도(operating/junction/ambient)가 잡히면 저장온도(storage)보다 우선해요.
    - 앵커가 없으면, 이미 추출된 짧은 필드값(예: '-55 to 125 C')만 예외적으로 신뢰해요."""
    if not text:
        return None, None
    s = str(text)
    op_ranges, temp_ranges, any_ranges = [], [], []
    for m in _TR_RANGE_RE.finditer(s):
        a, b = _to_int(m.group("a")), _to_int(m.group("b"))
        lo, hi = min(a, b), max(a, b)
        if not (-100 <= lo <= 300 and -100 <= hi <= 300):
            continue
        any_ranges.append((lo, hi))
        after = s[m.end():m.end() + 5]
        before = s[max(0, m.start() - 35):m.start()]
        # 단위가 첫 번째 숫자 뒤에 바로 왔으면(-40°C to ...) u1에 잡히고, 두 번째 숫자 뒤에
        # 왔으면(... to 125°C) after에서 잡혀요 - 둘 중 하나만 있어도 단위가 있는 걸로 봐요.
        has_unit = bool(m.group("u1")) or bool(_TR_UNIT_AFTER.match(after))
        if not (has_unit or _TR_TEMP_KW.search(before)):
            continue
        temp_ranges.append((lo, hi))
        # 저장온도만 명시된 범위는 동작온도 우선순위에서 빼요.
        if _TR_OP_KW.search(before) or (has_unit and not _TR_STG_KW.search(before)):
            op_ranges.append((lo, hi))
    pool = op_ranges or temp_ranges
    if not pool:
        if len(s.strip()) <= 25 and len(any_ranges) == 1:
            return any_ranges[0]
        return None, None
    return min(l for l, _ in pool), max(h for _, h in pool)


def find_temp_range_evidence(text: str | None) -> str | None:
    """parse_temp_range와 같은 우선순위(동작온도 문맥 > 그냥 단위 있는 범위)로, 실제로 채택될
    첫 번째 온도범위 문구를 원문 그대로 돌려줘요(PDF 주석 근거용, 2026-09-03 도입). 판정 로직
    자체(parse_temp_range)는 안 건드리고, "왜 이 버킷을 골랐는지" 보여주는 용도라 별도 함수로
    분리했어요. 못 찾으면 None."""
    if not text:
        return None
    s = str(text)
    op_match, temp_match = None, None
    for m in _TR_RANGE_RE.finditer(s):
        a, b = _to_int(m.group("a")), _to_int(m.group("b"))
        lo, hi = min(a, b), max(a, b)
        if not (-100 <= lo <= 300 and -100 <= hi <= 300):
            continue
        after = s[m.end():m.end() + 5]
        before = s[max(0, m.start() - 35):m.start()]
        has_unit = bool(m.group("u1")) or bool(_TR_UNIT_AFTER.match(after))
        if not (has_unit or _TR_TEMP_KW.search(before)):
            continue
        if temp_match is None:
            temp_match = m.group(0)
        if _TR_OP_KW.search(before) or (has_unit and not _TR_STG_KW.search(before)):
            if op_match is None:
                op_match = m.group(0)
    return op_match or temp_match


def classify_temp_range(min_c, max_c) -> str:
    """동작 온도 최저/최고(℃)를 quality_by_temp 버킷명으로 바꿔요.

    양쪽 끝(최저·최고)이 그 버킷의 기준을 "동시에" 만족해야 그 버킷으로 인정해요(AND 조건).
    예: -40~125℃는 최고가 125℃까지 닿긴 하지만 최저가 -55℃가 아니라 -40℃라서 가장 넓은
    -55~125℃ 버킷 자격이 안 돼요 - 한쪽만 극단이어도 넓은 버킷을 인정해주면(OR 조건) 실제
    온도범위보다 후하게 등급이 매겨지는 사고가 있어서, 더 보수적인 AND 조건으로 확정함
    (사용자 결정, IS31FL3296 사례: -40~125℃는 B가 아니라 B-1이어야 함)."""
    if min_c is None or max_c is None:
        return "No Data"
    if min_c <= -55 and max_c >= 125:
        return "-55℃ ~ 125℃"
    if min_c <= -40 and max_c >= 85:
        return "-40℃ ~ 85℃"
    return "0℃ ~ 70℃"


def _quality_key(category: str, subcategory: str) -> str:
    # quality_by_temp 는 Inductor를 Coil/Transformer로 나눠 정의해요.
    if category == "Inductor":
        s = (subcategory or "").lower()
        if "transformer" in s or "pulse" in s:
            return "Inductor - Transformer"
        return "Inductor - Coil"
    return category


def resolve_quality_level(category: str, subcategory: str, temp_bucket: str):
    """(등급, commercial_fixed여부)를 돌려줘요.
    온도 기반 등급이 해당 서브카테고리에서 허용되지 않으면 Commercial로 고정해요(규칙2)."""
    mapping = _load("quality_by_temp.json")["mapping"]
    row = mapping.get(_quality_key(category, subcategory))
    if not row:
        return None, False
    grade = row.get(temp_bucket)
    if not grade:
        return None, False

    if grade != "Commercial":
        allowed = (
            _load("quality_allowed.json")["by_category"]
            .get(category, {})
            .get(subcategory, {})
            .get("allowed_tokens")
        )
        if allowed is not None and grade not in allowed:
            return "Commercial", True  # 미허용 -> Commercial 고정
    return grade, False


# ---------------------------------------------------------------------------
# Years in Production - 현재 연도 기준으로 이 부품이 몇 년째 양산 중인지 판정
# (사용자 확정, 2026-08-27: 예전엔 "데이터시트로 알 수 없음"으로 분류해 아예 시도조차
# 안 했지만, Revision History의 양산/최초 출시 연도로 추정 가능하다고 판단해 규칙을 새로 만듦)
# ---------------------------------------------------------------------------
_YEAR_PATTERN = r"(?:19|20)\d{2}"
# 값 목록(2.0/1.5/1/0.5/0.1)이 전 서브카테고리에서 동일 - MIL-HDBK-217F 표준 5단계 구간으로 보임
# (data/valid_values.json으로 9개 서브카테고리 전수 확인함). 실제 경과 연수보다 큰 구간을 고르지
# 않도록(과대평가 방지) 내림(floor) 방식으로 매핑함 - 정확한 보간 규칙이 따로 없어서 취한 임시
# 해석이니, 다르게 판단해야 할 사례가 나오면 이 표를 조정할 것.
_YIP_ANCHORS = [(2.0, ">=2.0"), (1.5, "1.5"), (1.0, "1"), (0.5, "0.5")]
_YIP_FLOOR_LABEL = "<=0.1"


def find_production_year(text: str | None) -> tuple[int | None, str | None, str | None]:
    """데이터시트 텍스트에서 이 부품이 언제부터 만들어졌는지 추정할 연도를 찾아요. 우선순위:
    ① Revision History의 'mass production'(양산 출시) 근처 연도 - 가장 정확
    ② 'initial release'(최초 출시) 근처 연도
    ③ 그 외 'Rev. X, ...' 개정 날짜들 중 가장 이른 연도(근사치 - 문서 최초 개정일일 뿐 실제
       양산 시작일과는 다를 수 있음)
    아무것도 못 찾으면 (None, None, None) - 이 경우 resolve_years_in_production이 기본값을 씀.
    참고: 분석에 쓰는 텍스트는 앞쪽 페이지 위주(ai/pdf_text.DEFAULT_MAX_PAGES)라, Revision
    History가 문서 맨 뒤에 있는 데이터시트는 못 찾는 경우가 흔함 - 그래서 기본값이 필요함.

    세 번째 반환값(evidence)은 실제로 매칭된 문구 원문이에요(PDF 주석 근거용, 2026-09-03
    도입) - PDF에서 이 문구를 그대로 찾아 하이라이트해요."""
    if not text:
        return None, None, None
    m = re.search(rf"mass production[^\n]{{0,80}}?({_YEAR_PATTERN})", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), "양산 출시(mass production) 기록 기준", m.group(0)
    m = re.search(rf"initial release[^\n]{{0,80}}?({_YEAR_PATTERN})", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), "최초 출시(initial release) 기록 기준", m.group(0)
    rev_matches = list(
        re.finditer(rf"rev(?:ision)?\.?\s*[a-z0-9]+[,\s].{{0,20}}?({_YEAR_PATTERN})", text, re.IGNORECASE)
    )
    if rev_matches:
        # 여러 개정 날짜 중 "연도가 가장 이른" 것을 골라요 - 근거 문구도 그 매치 자체의 원문으로
        # 맞춰서, 돌려주는 연도와 하이라이트될 문구가 서로 다른 매치를 가리키지 않게 해요.
        earliest = min(rev_matches, key=lambda m: int(m.group(1)))
        return (
            int(earliest.group(1)),
            "개정(Rev.) 날짜 중 가장 이른 연도 기준(근사치 - 실제 양산 시작일과 다를 수 있음)",
            earliest.group(0),
        )
    return None, None, None


def classify_years_in_production(years_elapsed: float) -> str:
    """경과 연수를 유효성 목록 5단계 버킷 중 하나로 내림(floor) 매핑해요."""
    for threshold, label in _YIP_ANCHORS:
        if years_elapsed >= threshold:
            return label
    return _YIP_FLOOR_LABEL


def resolve_years_in_production(text: str | None, current_year: int | None = None) -> tuple[str, str, str | None]:
    """(버킷값, 근거설명, 근거문구)를 돌려줘요. 제작연도를 못 찾으면 사용자 확정 기본값
    `>=2.0`을 씀(신제품보다는 이미 시장에 나와 있는 부품을 다루는 경우가 대부분이라는 전제,
    2026-08-27 확정) - 이 경우 근거문구는 None(PDF에서 하이라이트할 특정 문구가 없다는 뜻,
    2026-09-03 도입)."""
    if current_year is None:
        current_year = date.today().year
    year, basis, evidence = find_production_year(text)
    if year is None:
        return ">=2.0", "제작연도를 찾지 못해 기본값 적용(사용자 확정, 2026-08-27)", None
    years_elapsed = current_year - year
    bucket = classify_years_in_production(years_elapsed)
    return bucket, f"{basis}: {year}년 → 현재({current_year})까지 {years_elapsed}년 경과", evidence


# ---------------------------------------------------------------------------
# 패키지 판별 - ① 발주번호(Ordering Information) 매칭(정확) ② 본문 키워드 검색(보조)
# ---------------------------------------------------------------------------
# 발주번호 뒤 이 글자 수 이내(같은 줄)에서 패키지명을 찾아요.
_ORDER_ROW_WINDOW = 80
# 패키지명처럼 생겼지만 패키지가 아닌 대문자 토큰들(테이프&릴 표기 등) - 오탐 방지용.
_ORDER_NON_PACKAGE_TOKENS = {"TR", "TU", "RL", "REEL", "TAPE", "ROHS", "MOQ", "QTY"}
_PACKAGE_TOKEN_RE = re.compile(r"\b([A-Z]{2,10}(?:-\d{1,3})?)\b")


def find_ordering_package(part_number: str, text: str) -> str | None:
    """'Ordering Information' 같은 발주번호↔패키지 대응표에서, 지금 분석 중인 정확한 품번과
    일치하는 줄을 찾아 그 옆의 패키지명을 돌려줘요. 데이터시트 하나에 여러 패키지가 함께
    실려 있을 때(예: QFN-20/UTQFN-12) 본문 전체 키워드 검색보다 훨씬 정확해요 - 그 부품이
    실제로 어느 패키지로 나가는지는 발주번호 자체가 답이니까요. 못 찾으면 None."""
    if not part_number or not text:
        return None
    idx = text.find(part_number)
    if idx == -1:
        idx = text.lower().find(part_number.lower())
    if idx == -1:
        return None

    window = text[idx + len(part_number) : idx + len(part_number) + _ORDER_ROW_WINDOW]
    window = window.split("\n")[0]  # 같은 줄까지만 봐요.
    for m in _PACKAGE_TOKEN_RE.finditer(window):
        token = m.group(1)
        if token.upper() not in _ORDER_NON_PACKAGE_TOKENS:
            return token
    return None


# ---------------------------------------------------------------------------
# Package Type 파라미터 값 - 실제 물리적 패키지명(예: "UTQFN-12")이 아니라, 217F가 정한
# 표준 분류값(예: "Nonhermetic: DIPs, PGA, SMT")이 PSA 시트의 정답이에요. 서브카테고리마다
# 허용되는 값 목록이 달라요(package_type_allowed.json, 유효성 목록 시트 드롭다운과 동일).
# ---------------------------------------------------------------------------
def get_package_type_allowed(category: str, subcategory: str) -> list[str] | None:
    """이 서브카테고리에서 Package Type이 가질 수 있는 217F 표준 분류값 목록을 돌려줘요.
    이 서브카테고리에 Package Type 파라미터 자체가 없으면 None."""
    return _load("package_type_allowed.json")["by_category"].get(category, {}).get(subcategory)


# 물리적 패키지명(발주번호/본문에서 확인) -> 217F 표준 분류. 순서가 중요해요(위에서부터
# 먼저 매칭되는 걸 써요) - 더 구체적인 규칙(세라믹 밀봉 등)을 일반 규칙보다 앞에 둬요.
_PACKAGE_TYPE_RULES: list[tuple[str, str]] = [
    (r"cerdip|c-?dip\b|glass\s*seal", "DIP, Glass Seal"),
    (r"flat\s*-?pack|\bcfp\b", "Flatpack"),
    (r"\bclcc\b|\bcpga\b|ceramic.*(lcc|pga|chip carrier|grid array)|hermetic", "Hermetic: DIPs, PGA, SMT"),
    (r"\bpga\b|pin grid array", "Pin Grid Array"),  # VHSIC/VLSI CMOS 전용 3분류
    (r"\blcc\b|chip carrier|\bplcc\b", "Chip Carrier"),  # VHSIC/VLSI CMOS 전용 3분류
    (r"\bcan\b|^to-?\d", "Can"),
    (r"\bdip\b", "DIP"),  # VHSIC/VLSI CMOS 전용 3분류(위 DIP, Glass Seal에 안 걸린 나머지)
]
# 위 규칙 어디에도 안 걸리면(=밀봉 방식을 특정할 단서가 없으면) 이걸 기본값으로 써요 - 오늘날
# 상용 부품 패키지(QFN/SOIC/TSSOP/BGA/SOT/PDIP/PLCC 등)의 압도적 다수가 비밀봉 플라스틱이에요.
_DEFAULT_PACKAGE_TYPE = "Nonhermetic: DIPs, PGA, SMT"


def classify_package_type(package: str | None, allowed: list[str] | None) -> str | None:
    """물리적 패키지명(예: 'UTQFN-12', 'TO-220', 'CERDIP-8')을 이 서브카테고리에서 허용되는
    217F 표준 분류값으로 바꿔요. allowed에 없는 값으로는 절대 매핑하지 않아요(잘못 우겨넣는
    대신 사람이 확인하도록 None을 돌려줌). allowed 자체가 없으면(이 서브카테고리엔 Package
    Type이 없음) 그냥 규칙만으로 판단해요.

    package가 아예 None이어도(발주정보/본문 어디서도 물리 패키지명을 못 찾음) 기본값으로
    떨어져요 - 오늘날 상용 부품 패키지 압도적 다수가 비밀봉 플라스틱(SMT)이라는 전제(사용자
    확정, 2026-08-30). 이 기본값이 그 서브카테고리에서 애초에 허용 안 되면(allowed에 없으면)
    그때는 정말 못 정하는 거라 None을 돌려줘요."""
    if package:
        text = package.lower()
        for pattern, label in _PACKAGE_TYPE_RULES:
            if re.search(pattern, text) and (allowed is None or label in allowed):
                return label
    if allowed is None or _DEFAULT_PACKAGE_TYPE in allowed:
        return _DEFAULT_PACKAGE_TYPE
    return None


def find_package_in_text(category: str, text: str) -> str | None:
    """본문 전체에서 217F 열저항 표에 있는 패키지명을 찾아요(긴 이름 우선). 발주번호 매칭
    (find_ordering_package)이 안 될 때만 쓰는 보조 수단이에요.

    대소문자를 구분해서 찾아요(원문 그대로 비교) - 소문자로 통일해서 찾으면 "Can"(217F
    패키지명) 같은 흔한 영어 단어와 겹치는 패키지명이 본문의 평범한 문장(예: "...current
    can be adjusted")에 오탐되는 사고가 실제로 있었어요."""
    table = _load("thermal_resistance.json")["by_category"].get(category, {})
    if not text:
        return None
    for pkg in sorted(table.keys(), key=len, reverse=True):
        if re.search(r"(?<![\w-])" + re.escape(pkg) + r"(?![\w-])", text):
            return pkg
    return None


# ---------------------------------------------------------------------------
# 패키지별로 여러 값이 병기된 열저항 스펙값 선택 (예: "56.6°C/W (QFN)" / "126.1°C/W (UTQFN)")
# ---------------------------------------------------------------------------
_THERMAL_VALUE_RE = re.compile(r"([\d.]+)\s*°?C\s*/\s*W\s*\(([^)]+)\)", re.IGNORECASE)
_AMBIENT_CONTEXT_KEYWORDS = ("junction to ambient", "junction-to-ambient", "θja", "theta ja", "rthja")
_CASE_CONTEXT_KEYWORDS = ("junction to case", "junction-to-case", "θjc", "theta jc", "rthjc")
_THERMAL_CONTEXT_WINDOW = 150


def find_package_specific_thermal_value(package: str, text: str, mode: str = "case") -> float | None:
    """데이터시트 본문에 패키지별로 여러 열저항 값이 나란히 적힌 경우, 확정된 패키지와
    같은 값만 찾아요(예: 이 부품이 UTQFN이면 "126.1°C/W (UTQFN)"만 인정, QFN용 56.6은 무시).
    값 앞쪽 문맥에 mode에 맞는 표현(θJA=ambient, θJC=case)이 있을 때만 인정해요 - 안 그러면
    θJA 표를 θJC로 착각해서 잘못된 값을 채울 위험이 있어요. 못 찾으면 None."""
    if not package or not text:
        return None
    pkg_key = re.split(r"[-\s]", package)[0].lower()
    if not pkg_key:
        return None
    keywords = _AMBIENT_CONTEXT_KEYWORDS if mode == "ambient" else _CASE_CONTEXT_KEYWORDS
    for m in _THERMAL_VALUE_RE.finditer(text):
        label = m.group(2).strip().lower()
        if pkg_key not in label:
            continue
        context = text[max(0, m.start() - _THERMAL_CONTEXT_WINDOW) : m.start()].lower()
        if any(k in context for k in keywords):
            return float(m.group(1))
    return None


def resolve_thermal_resistance(package: str | None, spec_value=None, mode: str = "case"):
    """(열저항 값, 근거설명)을 돌려줘요. 데이터시트에 값이 명시돼 있을 때만 채우고, 없으면
    억지로 추정하지 않고 공란 + '확인 필요'로 남겨요(사용자 결정) - 217F 패키지 표 기본값이나
    반도체 기본값(70) 같은 걸로 슬쩍 채우면, 실제로는 미확인인 값이 확인된 것처럼 보이는
    위험이 있어서 폐지했어요.

    mode = "case"    -> θJC(접합-케이스). TJ = TC + θJC x P.
    mode = "ambient" -> θJA(접합-주위). TJ = TA + θJA x P.
    (사용자가 GUI에서 Case/Ambient를 골라요 — 어느 기준온도로 온도상승/접합온도를 계산할지 결정.)"""
    label = "θJC" if mode == "case" else "θJA"
    if spec_value is not None:
        return spec_value, f"{label} 스펙값" + (f" ({package})" if package else "")
    return None, f"{label} 확인 필요(데이터시트에 명시된 값 없음)"


# ---------------------------------------------------------------------------
# Operating Power 자동 계산 (데이터시트에 명시된 소비전력이 없을 때, 전압 x 전류로 계산)
# ---------------------------------------------------------------------------
_VALUE_UNIT_RE = re.compile(r"([-+]?\d[\d,]*\.?\d*)\s*([a-zA-Zµμ]*)")
_VOLTAGE_UNIT_TO_V = {"v": 1.0, "kv": 1000.0, "mv": 0.001}
_CURRENT_UNIT_TO_MA = {"a": 1000.0, "ma": 1.0, "ua": 0.001, "µa": 0.001, "μa": 0.001, "na": 1e-6}


def _parse_number_unit(raw: str | None):
    if not raw:
        return None, ""
    m = _VALUE_UNIT_RE.match(raw.strip())
    if not m:
        return None, ""
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None, ""
    return value, (m.group(2) or "").strip().lower()


def compute_operating_power_mw(voltage_raw: str | None, current_raw: str | None) -> float | None:
    """전압(V)과 전류(mA/µA/A 등)를 곱해서 소비전력을 mW 단위로 계산해요(기존 관례대로
    Operating Power는 mW 숫자를 그대로 저장함, CLAUDE.md 7번 참고). 값이나 단위를 못 알아보면
    None - 사람이 직접 계산/확인해야 해요."""
    v, vunit = _parse_number_unit(voltage_raw)
    i, iunit = _parse_number_unit(current_raw)
    if v is None or i is None:
        return None
    if vunit and vunit not in _VOLTAGE_UNIT_TO_V:
        return None
    if iunit and iunit not in _CURRENT_UNIT_TO_MA:
        return None
    v_factor = _VOLTAGE_UNIT_TO_V.get(vunit, 1.0)
    i_factor = _CURRENT_UNIT_TO_MA.get(iunit, 1.0)
    return round(v * v_factor * i * i_factor, 6)


# ---------------------------------------------------------------------------
# 유효성 목록 전체 검증 (CLAUDE.md 0번 원칙, 2026-08-27 확정: 유효성 목록 시트에 허용값이
# 있는 파라미터는 반드시 그 값 중에서만 골라야 함). valid_values.json은 build_reference.py가
# '유효성 목록' 시트의 모든 파라미터 칸(287개, Quality Level/Package Type 포함)을 그대로 뽑은 것.
# ---------------------------------------------------------------------------
def _normalize_value(v) -> str:
    return re.sub(r"\s+", " ", str(v).strip()).lower()


def get_allowed_values(category: str, subcategory: str, param: str) -> list[str] | None:
    """이 (카테고리, 서브카테고리, 파라미터)에 유효성 목록 허용값이 정의돼 있으면 그 리스트를,
    아니면(=이 규칙 대상이 아닌 파라미터, 예: 전압/전류 같은 연속 측정값) None을 돌려줘요."""
    return _load("valid_values.json")["by_category"].get(category, {}).get(subcategory, {}).get(param)


def is_allowed_value(category: str, subcategory: str, param: str, value) -> bool:
    """value가 유효성 목록 허용값 중 하나와 일치하는지(공백/대소문자 무시) 확인해요.
    이 파라미터에 애초에 허용값 목록이 없으면(get_allowed_values가 None) 규칙 대상이 아니므로
    항상 True(제한 없음)."""
    allowed = get_allowed_values(category, subcategory, param)
    if allowed is None:
        return True
    if value is None or str(value).strip() == "":
        return False
    target = _normalize_value(value)
    return any(target == _normalize_value(a) for a in allowed)


# ---------------------------------------------------------------------------
# 커패시터 발주정보(Ordering Information) 품번 코드 해독 (2026-09-03 도입,
# T322D106K035AT 실전 분석에서 확정) - 커패시터 데이터시트 본문에는 보통 그 "시리즈 전체"의
# 커패시턴스/전압 범위만 적혀 있어서(예: "Rated Capacitance Range 0.1 – 330 μF", "Voltage
# rating of 2 – 50 VDC"), field_extractor의 "라벨 근처 숫자" 방식으로는 이 범위 문구를 이
# 부품 하나의 실제 값으로 잘못 주워버려요(실제 사고: T322D106K035AT의 Capacitance가
# "0.1 to 330 μF"로, Rated Voltage가 "2"로 잘못 채워짐). 실제 값은 발주정보 표에서 품번의
# 각 자리 코드를 해독해야 나와요. 페이지 번호는 안 봐요(부품마다 다름) - Ordering Information
# 표가 "Capacitance Code (pF)"/"significant figures"처럼 EIA 코드 방식을 쓴다고 스스로 설명하고
# 있는지만 확인해서, 그 설명이 있을 때만 시도해요(다른 방식의 커패시터 표에는 잘못 적용 안 함).
# ---------------------------------------------------------------------------
# EIA 3자리 커패시턴스 코드는 곧바로 뒤에 공차 문자(J=±5%/K=±10%/M=±20%/Z 등)가 붙는 게 업계
# 관례예요(발주정보 표의 "Capacitance Tolerance" 칸이 바로 그 문자) - 이 조합으로 품번 안에서
# 정확한 자리를 찾아요(케이스 크기 숫자 등 다른 3자리 숫자와 안 헷갈림, 그런 자리엔 보통
# 문자 하나가 아니라 다른 게 옴).
_EIA_CAP_CODE_RE = re.compile(r"(\d{3})\s*[JKMZ]")
_CODE_VALUE_PAIR_RE = re.compile(r"\b(\d{3})\s*=\s*(\d{1,3})\b")


def decode_eia_capacitance_code(code: str) -> float | None:
    """3자리 EIA 커패시턴스 코드(예: '106')를 pF로 해독해요 - 앞 두 자리는 유효숫자, 세 번째
    자리는 그 뒤에 붙는 0의 개수(10의 거듭제곱)예요. 특정 제조사 규칙이 아니라 업계 표준
    표기법이라(이 데이터시트도 정확히 이렇게 설명함) 다른 커패시터에도 그대로 적용돼요."""
    if not code or len(code) != 3 or not code.isdigit():
        return None
    significant = int(code[:2])
    multiplier = int(code[2])
    return significant * (10**multiplier)


def format_capacitance_from_pf(pf_value: float) -> tuple[str, str]:
    """pF 값을 µF 단위로 바꿔서 (값 문자열, 단위) 튜플을 돌려줘요 - 탄탈럼/전해 커패시터는
    보통 µF로 표기하는 관례를 따름(사용자 확정, T322D106K035AT 사례: 10,000,000pF -> "10"/
    "uF"). 소수점 뒤 불필요한 0은 잘라내요."""
    uf = pf_value / 1_000_000
    if uf == int(uf):
        value_str = str(int(uf))
    else:
        value_str = f"{uf:.6f}".rstrip("0").rstrip(".")
    return value_str, "uF"


def find_capacitance_code(part_number: str, text: str) -> str | None:
    """발주정보 표가 EIA 3자리 코드 방식을 쓴다고 스스로 설명하고 있을 때만("Capacitance Code"
    + "significant figures" 문구가 있을 때) 품번에서 그 3자리 코드를 찾아요. 못 찾거나 이
    방식이 아니면 None - 억지로 추정하지 않아요."""
    if not part_number or not text:
        return None
    # "significant"(유효숫자)와 "Capacitance" 표제가 정확히 붙어 있으리라("Capacitance Code")
    # 기대하지 않아요 - Ordering Information 표는 다열(多列) 레이아웃이라, 페이지의 좌/우 절반을
    # 나눠 뽑는 pdf_text.py의 2단 분리 로직을 거치면 표 칸들이 원래 순서에서 멀리 떨어지거나
    # ("Capacitance"와 "Code (pF)"가 아예 다른 줄로 갈라짐, T495C107K010ATE100에서 실측 확인)
    # 다른 칸 텍스트가 그 사이에 끼어들 수 있어요(T322D106K035AT에서 실측 확인, 58자 떨어짐).
    # 그래서 정확한 구가 아니라, "capacitance"라는 단어가 나온 자리마다 그 뒤 800자 안에
    # "significant"가 있는지 봐요(여러 번 나오는 "capacitance" 중 아무 자리에서나 걸리면 충분).
    found = False
    for cap_m in re.finditer(r"\bcapacitance\b", text, re.IGNORECASE):
        window = text[cap_m.end() : cap_m.end() + 800]
        if re.search(r"significant", window, re.IGNORECASE):
            found = True
            break
    if not found:
        return None
    m = _EIA_CAP_CODE_RE.search(part_number)
    return m.group(1) if m else None


def find_rated_voltage_code(part_number: str, text: str) -> tuple[str | None, int | None, str | None]:
    """커패시턴스 코드 바로 뒤(공차 문자 다음)에 오는 자리가 발주정보 표의 Rated Voltage
    코드예요(업계 관례 - Capacitance Code(pF)/Tolerance/Rated Voltage(VDC) 순서로 이어짐).
    'Rated Voltage' 표제 근처에 있는 '코드 = 값' 쌍(예: "035 = 35")을 찾아 그 코드와 실제로
    대조해요 - 이 데이터시트가 실제로 그렇게 표기하고 있다는 걸 확인한 뒤에만 쓰는 거라
    안전해요. (코드문자열, 전압값, 실제로 매칭된 원문 그대로의 "코드 = 값" 문구)를 돌려줘요
    - 세 번째 값은 PDF 주석 근거용(2026-09-03 도입, 사용자가 정확히 이 문구에 표시해달라고
    확정함). 못 찾으면 (None, None, None)."""
    if not part_number or not text:
        return None, None, None
    m = _EIA_CAP_CODE_RE.search(part_number)
    if not m:
        return None, None, None
    after = part_number[m.end():]
    vm = re.match(r"(\d{2,3})", after)
    if not vm:
        return None, None, None
    code = vm.group(1)

    # "Rated Voltage"와 "(VDC)"는 표 헤더가 여러 줄로 접혀 나오면서(pdfplumber가 다열 표를
    # 위-아래 순서로만 뽑아서) 실제로는 서로 멀리 떨어져 나오는 경우가 있어(발주정보 표 실측
    # 확인, T322D106K035AT) "(VDC)"까지 붙여서 찾지 않고 "Rated Voltage" 문구만 앵커로 써요.
    heading = re.search(r"rated voltage", text, re.IGNORECASE)
    if not heading:
        return None, None, None
    window = text[heading.end() : heading.end() + 600]
    pairs = list(_CODE_VALUE_PAIR_RE.finditer(window))
    table = {mm.group(1): mm.group(0) for mm in pairs}  # 코드 -> 실제 매칭 원문("035 = 35")
    if not table:
        return None, None, None
    if code in table:
        return code, int(dict((mm.group(1), mm.group(2)) for mm in pairs)[code]), table[code]
    # 표에 이 코드가 정확히 없어도, 표에 있는 다른 코드들이 전부 "코드=코드값 그대로"(앞자리
    # 0만 다름) 규칙이면 이 코드도 같은 규칙일 가능성이 높아요 - 다만 이 경우 원문에 그 코드
    # 자체가 없다는 뜻이라 근거 문구는 못 줘요.
    values = {mm.group(1): int(mm.group(2)) for mm in pairs}
    if all(int(k) == v for k, v in values.items()):
        return code, int(code), None
    return None, None, None


# ---------------------------------------------------------------------------
# 탄탈럼 커패시터 Series Resistance(ESR) - 발주정보 품번의 "E" + 3자리 코드가 밀리옴(mΩ) 값을
# 그대로 나타내요(2026-09-04 도입, T495C107K010ATE100 실전 분석에서 확정 - "E100" = 100mΩ,
# 사용자가 직접 데이터시트 발주정보 표와 대조해 확인함). Capacitance/Rated Voltage 코드처럼
# 유효숫자+배수 공식이 아니라 그대로 읽는 방식이라("E045" = 45mΩ) 훨씬 단순해요. mΩ 값을
# Ω으로 바꾼 뒤, 유효성 목록의 5단계 버킷(Years in Production과 같은 내림(floor) 방식)으로
# 매핑해요.
# ---------------------------------------------------------------------------
_TANTALUM_ESR_CODE_RE = re.compile(r"E(\d{3})")
_ESR_BUCKET_ANCHORS = [(0.8, ">0.8"), (0.6, ">0.6 to 0.8"), (0.4, ">0.4 to 0.6"), (0.2, ">0.2 to 0.4"), (0.1, ">0.1 to 0.2")]
_ESR_FLOOR_LABEL = "0 to 0.1"


def find_tantalum_esr_milliohms(part_number: str, text: str) -> tuple[str | None, str | None]:
    """발주정보 표가 "ESR을 mΩ 코드로 그대로 표기한다"고 설명하고 있을 때만("ESR" 근처에
    "mΩ" 언급이 있을 때) 품번에서 "E" + 3자리 코드를 찾아요. (코드문자열, 근거 원문) 튜플 -
    이 방식이 아니거나 못 찾으면 (None, None)."""
    if not part_number or not text:
        return None, None
    found_gate = False
    for m in re.finditer(r"\besr\b", text, re.IGNORECASE):
        window = text[m.end() : m.end() + 400]
        if re.search(r"m\s*Ω|milliohm", window, re.IGNORECASE):
            found_gate = True
            break
    if not found_gate:
        return None, None
    m = _TANTALUM_ESR_CODE_RE.search(part_number)
    if not m:
        return None, None
    return m.group(1), m.group(0)


def classify_series_resistance(ohms: float) -> str:
    """저항값(Ω)을 유효성 목록 5단계 버킷 중 하나로 내림(floor) 매핑해요(Years in Production
    과 같은 방식 - 실제 값보다 큰 구간을 고르지 않도록)."""
    for threshold, label in _ESR_BUCKET_ANCHORS:
        if ohms > threshold:
            return label
    return _ESR_FLOOR_LABEL


# ---------------------------------------------------------------------------
# 페라이트 비드(Ferrite Bead) -> Inductor/Coil의 Type 고정값 (2026-09-03 도입,
# BLM21PG121SN1D 실전 분석에서 확정). 페라이트 비드는 노이즈 억제용 수동 EMI 필터 부품이라,
# 유효성 목록의 Type 허용값(Load/Power Filter/RF, Fixed or Molded/RF, Variable) 중 항상
# "Power Filter"가 맞음(사용자 확정). 앞으로 분석되는 모든 페라이트 비드 부품에 공통 적용.
# ---------------------------------------------------------------------------
_FERRITE_BEAD_RE = re.compile(r"chip ferrite bead|ferrite bead", re.IGNORECASE)
FERRITE_BEAD_TYPE = "Power Filter"


def find_ferrite_bead_evidence(text: str | None) -> str | None:
    """제목/본문에 '(chip) ferrite bead' 문구가 있으면 원문 그대로 돌려줘요(PDF 주석 근거용 +
    이 규칙을 적용할지 말지 결정하는 게이트). 없으면 None."""
    if not text:
        return None
    m = _FERRITE_BEAD_RE.search(text)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# 오실레이터(Quartz Crystal)의 Frequency (2026-09-03 도입, DSC8123CI5 실전 분석에서 확정).
# 필드-프로그래머블(field-programmable) 오실레이터는 품번에 주파수가 고정돼 있지 않아서
# (발주 후 현장에서 원하는 주파수로 프로그래밍하는 방식) 딱 "이 부품의" 주파수라는 게 없어요.
# 대신 데이터시트가 위상잡음(Phase Noise) 등 스펙 조건에 예시/측정 기준으로 병기한 주파수
# (예: "200kHz to 20MHz @156.25MHz")를 대신 써요(사용자 확정) - 이 값이 데이터시트 안에서
# 유일하게 구체적인 소수점 단위 주파수로 나오는 자리라서.
# ---------------------------------------------------------------------------
_OSC_FREQ_CONDITION_RE = re.compile(r"@\s*([\d.]+)\s*mhz", re.IGNORECASE)


def find_oscillator_frequency(text: str | None) -> tuple[str | None, str | None]:
    """'@156.25MHz'처럼 스펙 조건에 병기된 주파수를 찾아요. (값 문자열, 근거 원문) 튜플을
    돌려줘요 - 못 찾으면 (None, None)."""
    if not text:
        return None, None
    m = _OSC_FREQ_CONDITION_RE.search(text)
    if not m:
        return None, None
    return m.group(1), m.group(0)


# ---------------------------------------------------------------------------
# TE Connectivity "SM Series" 표면실장 권선형 전력저항의 Power Rating (2026-09-03 도입,
# SMW3100RJT 실전 분석에서 확정). 품번이 "SM" 뒤에 타입(W=Wire/F=Metal Film)과 사이즈 숫자
# (2/3/5/7)를 이어 써요(예: SMW3100RJT = SMW형 사이즈 3). "Characteristics – Electrical" 항목에
# 사이즈별 Power Rating이 "Power Rating @ 20°C SM_<사이즈>: X.0 Watts"로 직접 표로 나와 있어서,
# 그 사이즈 숫자로 대조하면 정확한 값을 찾을 수 있어요.
# ---------------------------------------------------------------------------
_SM_SERIES_PART_RE = re.compile(r"SM[WF](\d)", re.IGNORECASE)
_SM_POWER_RATING_PAIR_RE = re.compile(
    r"power rating\s*@\s*20\s*(?:°|º)?\s*c\s*sm[_\s]?(\d)\s*:?\s*([\d.]+)\s*watts?", re.IGNORECASE
)


def find_sm_series_power_rating(part_number: str, text: str) -> tuple[str | None, str | None]:
    """SM Series 품번(SMW3100RJT 등)의 사이즈 숫자로 Power Rating을 찾아요. (값 문자열, 근거
    원문) 튜플을 돌려줘요 - 이 시리즈가 아니거나 못 찾으면 (None, None)."""
    if not part_number or not text:
        return None, None
    m = _SM_SERIES_PART_RE.match(part_number)
    if not m:
        return None, None
    size = m.group(1)
    for pm in _SM_POWER_RATING_PAIR_RE.finditer(text):
        if pm.group(1) == size:
            value = float(pm.group(2))
            value_str = str(int(value)) if value == int(value) else str(value)
            return value_str, pm.group(0)
    return None, None


# ---------------------------------------------------------------------------
# Power Rating - "Power Rating" 라벨 바로 뒤가 아니라 몇 줄 아래(온도 조건 옆)에 실제 W(att)
# 값이 나오는 표 레이아웃 보완 (2026-09-03 도입, TC33X-2-102E 실전 분석에서 확정: "Power
# Rating (50 VDC max.)\n70 °C ... 0.15 watt"처럼 라벨 줄엔 전압 상한만 있고, 진짜 전력값은
# 다음 줄의 온도 조건 옆에 있음). field_extractor는 같은 줄 안에서만 찾아서(다른 필드의 값을
# 잘못 줍는 사고를 막으려고 줄바꿈을 안 건너뜀) 이런 레이아웃은 못 찾음 - 이 함수는 W(att)
# 단위가 확실할 때만 몇 줄 아래까지 봐요.
# ---------------------------------------------------------------------------
_POWER_RATING_WATT_RE = re.compile(r"power rating.{0,150}?([\d.]+)\s*watts?", re.IGNORECASE | re.DOTALL)


def find_power_rating_watts(text: str | None) -> tuple[str | None, str | None]:
    """'Power Rating' 근처(몇 줄 아래까지)에서 W(att) 단위 값을 찾아요. (값 문자열, 근거 원문)
    튜플을 돌려줘요 - 못 찾으면 (None, None). 근거 문구는 "숫자 watt(s)" 부분만 잘라서 돌려줘요
    (전체 매치 구간을 그대로 쓰면 "Power Rating"부터 값 사이에 낀, 2단 레이아웃 때문에 순서가
    뒤섞인 다른 칸의 글자까지 포함돼서 - 실제 확인, TC33X-2-102E - PDF에서 그 문구를 그대로
    찾지 못해 주석이 안 붙는 문제가 있었음)."""
    if not text:
        return None, None
    m = _POWER_RATING_WATT_RE.search(text)
    if not m:
        return None, None
    return m.group(1), text[m.start(1) : m.end()]


# ---------------------------------------------------------------------------
# Semiconductor/Diode의 Diode Type / Construction Type (2026-09-03 도입,
# BZT52C8V2-7 실전 분석에서 확정).
# ---------------------------------------------------------------------------
_ZENER_RE = re.compile(r"\bzener\b", re.IGNORECASE)
ZENER_DIODE_TYPE = "Voltage Regulator, Ref, Zener"
# 유효성 목록의 Construction Type 허용값은 딱 둘뿐이에요: "Metallurgically"(합금/확산 등으로
# 영구 접합된 방식 - 오늘날 실리콘 다이오드의 절대다수)와 "Non-Metallurgically/Spring
# Loaded"(점접촉/스프링 압착 방식 - 구식 고전력 정류기 등 극히 일부 특수 용도). 데이터시트가
# 점접촉/스프링 방식이라고 명시하지 않는 한 기본값으로 이걸 써요(Package Type의 기본값
# 규칙과 같은 패턴).
_SPRING_LOADED_RE = re.compile(r"point[- ]contact|spring[- ]loaded|pressure[- ]contact", re.IGNORECASE)
DIODE_CONSTRUCTION_METALLURGICAL = "Metallurgically"
DIODE_CONSTRUCTION_SPRING_LOADED = "Non-Metallurgically/Spring Loaded"


def find_zener_diode_type(text: str | None) -> str | None:
    """본문에 'zener'가 있으면 유효성 목록의 Diode Type 값을 돌려줘요(제너 다이오드는 전압
    기준/레귤레이터 용도라 이 값이 맞음). 없으면 None."""
    if text and _ZENER_RE.search(text):
        return ZENER_DIODE_TYPE
    return None


def resolve_diode_construction_type(text: str | None) -> str:
    """점접촉/스프링 로디드 방식이라고 명시돼 있지 않으면 기본값(Metallurgically)을 써요."""
    if text and _SPRING_LOADED_RE.search(text):
        return DIODE_CONSTRUCTION_SPRING_LOADED
    return DIODE_CONSTRUCTION_METALLURGICAL


# ---------------------------------------------------------------------------
# Semiconductor/Transistor의 Operating Voltage(Vceo)/Application (2026-09-04 도입,
# 2SB1260T100R 실전 분석에서 확정). 유효성 목록엔 "Rated Voltage"라는 이름의 파라미터가 이
# 소분류엔 없고 "Operating Voltage"만 있어요(data/subcat_params.json 확인) - 사용자가 말한
# "Rated Voltage"는 이 필드를 가리키는 걸로 보고 여기에 채워요.
# ---------------------------------------------------------------------------
# VCEO(콜렉터-이미터 항복전압)는 거의 모든 바이폴라 트랜지스터 데이터시트에 "V ... CEO"처럼
# 아래첨자 "CEO"가 값 바로 다음 줄에 오는 흔한 표기라(폰트 베이스라인 차이로 추출 시 줄이
# 나뉨), 이 패턴으로 찾아요 - 특정 제조사에 한정되지 않는 업계 공통 표기.
# CEO 아래첨자는 lookahead로만 확인하고(진짜 VCEO가 맞는지 문맥 확인용) 매치/근거 문구에는
# 안 넣어요 - 포함시켰다가, 아래첨자가 값과 다른 줄로 추출되는 경우(폰트 베이스라인 차이)
# PDF에서 그 문구를 그대로 못 찾아 주석이 통째로 안 붙는 문제가 실제로 있었음(2SB1260T100R).
# 앞의 "V" 기호(물리량 문자, 폰트가 따로 스타일링돼 있어 검색이 잘 안 됨)도 근거에서 빼고,
# "숫자+단위"만 남겨요 - 이건 실제로 page.search_for()로 잘 찾힘을 확인함.
_VCEO_RE = re.compile(r"V\s*(-?[\d.]+)(\s*V)(?=\s*\n?\s*CEO)", re.IGNORECASE)
# "Switching"/"Linear" 어느 쪽인지 본문에 그 단어 그대로 적혀 있는 경우는 드물어서, 용도
# 설명으로 판단해요: 모터/LED 드라이버처럼 부하를 켜고 끄는 용도("driver")면 스위칭,
# 증폭기("amplifier")/선형("linear") 용도면 리니어. 둘 다(또는 둘 다 아님) 나오면 애매하니
# 사람이 판단하게 비워둬요.
_TRANSISTOR_SWITCHING_RE = re.compile(r"\bswitching\b|\bdriver\b", re.IGNORECASE)
_TRANSISTOR_LINEAR_RE = re.compile(r"\blinear\b|\bamplifier\b|\bamplification\b", re.IGNORECASE)


def find_transistor_vceo(text: str | None) -> tuple[str | None, str | None]:
    """VCEO 값을 찾아 절댓값 문자열로 돌려줘요. (값 문자열, 근거 원문) 튜플 - 못 찾으면
    (None, None)."""
    if not text:
        return None, None
    m = _VCEO_RE.search(text)
    if not m:
        return None, None
    value = abs(float(m.group(1)))
    value_str = str(int(value)) if value == int(value) else str(value)
    return value_str, m.group(1) + m.group(2)


def resolve_transistor_application(text: str | None) -> tuple[str | None, str | None]:
    """'Application' 값을 Linear/Switching 중에서 판단해요. (값, 근거 원문) - 애매하면
    (None, None)."""
    if not text:
        return None, None
    switching_m = _TRANSISTOR_SWITCHING_RE.search(text)
    linear_m = _TRANSISTOR_LINEAR_RE.search(text)
    if switching_m and not linear_m:
        return "Switching", switching_m.group(0)
    if linear_m and not switching_m:
        return "Linear", linear_m.group(0)
    return None, None


# ---------------------------------------------------------------------------
# MTBF 환경/온도 변환 (제조사 MTBF 제공 시)
# ---------------------------------------------------------------------------
def env_factor(from_env: str, to_env: str):
    row = _load("env_conversion.json")["matrix"].get(str(from_env))
    return row.get(str(to_env)) if row else None


def _nearest_temp(t):
    # 표에 없는 온도는 가장 가까운 칸으로 반올림하되, 동점이면 높은 쪽으로(엑셀 예시: 25 -> 30).
    temps = [int(x) for x in _load("temp_conversion.json")["temperatures"]]
    return min(temps, key=lambda x: (abs(x - t), -x))


def temp_factor(from_temp, to_temp):
    row = _load("temp_conversion.json")["matrix"].get(str(_nearest_temp(from_temp)))
    return row.get(str(_nearest_temp(to_temp))) if row else None


def convert_mtbf(mtbf, from_env, to_env, from_temp, to_temp):
    """적용 MTBF = 데이터시트 MTBF x 환경변환팩터 x 온도변환팩터."""
    ef = env_factor(from_env, to_env)
    tf = temp_factor(from_temp, to_temp)
    ef = 1 if ef is None else ef
    tf = 1 if tf is None else tf
    return mtbf * ef * tf

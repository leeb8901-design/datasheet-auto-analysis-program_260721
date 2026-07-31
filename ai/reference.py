# 엑셀에서 생성된 data/*.json 참고파일을 읽어, 분석 시 품질등급/열저항/MTBF 변환을 판정하는 파일이에요.
# 이 파일은 tools/build_reference.py 가 만든 JSON만 읽고, 값을 새로 지어내지 않아요.
# (엑셀=원본, JSON=생성물. 엑셀을 고치면 build_reference.py를 다시 돌려 JSON을 갱신하면 돼요.)
#
# 규칙 출처: '217F 분석기준' / '유효성 목록' 시트 (Data_list_217F 입력지). CLAUDE.md도 함께 참고.

import json
import re
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
_TR_NUM = r"[-+]?\d{1,3}"
_TR_CONN = r"(?:to|~|∼|…|\.\.\.|–|—)"
_TR_RANGE_RE = re.compile(rf"({_TR_NUM})\s*{_TR_CONN}\s*({_TR_NUM})", re.IGNORECASE)
_TR_UNIT_AFTER = re.compile(r"\s*(?:°|º)?\s*[CF]\b|\s*℃|\s*℉", re.IGNORECASE)
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
        a, b = int(m.group(1)), int(m.group(2))
        lo, hi = min(a, b), max(a, b)
        if not (-100 <= lo <= 300 and -100 <= hi <= 300):
            continue
        any_ranges.append((lo, hi))
        after = s[m.end():m.end() + 5]
        before = s[max(0, m.start() - 35):m.start()]
        has_unit = bool(_TR_UNIT_AFTER.match(after))
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


def classify_temp_range(min_c, max_c) -> str:
    """동작 온도 최저/최고(℃)를 quality_by_temp 버킷명으로 바꿔요."""
    if min_c is None or max_c is None:
        return "No Data"
    if min_c <= -55 or max_c >= 125:
        return "-55℃ ~ 125℃"
    if min_c <= -40 or max_c >= 85:
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
# 열저항 θJC (데이터시트에 없을 때의 217F 기본값 폴백)
# ---------------------------------------------------------------------------
def find_package_in_text(category: str, text: str) -> str | None:
    """본문에서 θJC 표에 있는 패키지명을 찾아요(긴 이름 우선)."""
    table = _load("thermal_resistance.json")["by_category"].get(category, {})
    if not text:
        return None
    low = str(text).lower()
    for pkg in sorted(table.keys(), key=len, reverse=True):
        if re.search(r"(?<![\w-])" + re.escape(pkg.lower()) + r"(?![\w-])", low):
            return pkg
    return None


def resolve_thermal_resistance(category: str, package: str | None, spec_value=None, mode: str = "case"):
    """(열저항 값, 근거설명)을 돌려줘요.

    mode = "case"   -> θJC(접합-케이스): 217F 패키지별 기본값 표로 폴백. TJ = TC + θJC x P.
    mode = "ambient"-> θJA(접합-주위): 패키지로 유추 불가(217F 표는 θJC 전용)라, 데이터시트
                       스펙값(θJA)만 사용하고 없으면 '확인 필요'로 둬요. TJ = TA + θJA x P.

    (사용자가 GUI에서 Case/Ambient를 골라요 — 어느 기준온도로 온도상승/접합온도를 계산할지 결정.)
    - case: 스펙값과 표값 중 큰 쪽을 써요. 표에 없는 패키지면 자동입력하지 않고 확인이 필요하다고 알려줘요.
      아무것도 없으면 반도체는 기본 70을 써요.
    - ambient: θJA는 표가 없으므로 스펙값만, 없으면 None."""
    label = "θJC" if mode == "case" else "θJA"

    if mode == "ambient":
        # θJA는 217F 패키지 표(θJC 전용)로 유추할 수 없어요. 데이터시트 스펙값만 사용해요.
        if spec_value is not None:
            return spec_value, f"{label} 스펙값"
        return None, f"{label} 미확인(데이터시트 값 필요)"

    table = _load("thermal_resistance.json")["by_category"].get(category, {})
    table_val = table.get(package) if package else None

    if package and table_val is None:
        note = f"'{package}'는 217F {label} 표에 없음 - {label} 확인 필요"
        return (spec_value, note) if spec_value is not None else (None, note)
    if table_val is not None and spec_value is not None:
        return max(table_val, spec_value), f"{label} 스펙/표 중 큰 값"
    if table_val is not None:
        return table_val, f"217F {label} 기본값"
    if spec_value is not None:
        return spec_value, f"{label} 스펙값"
    if category == "Semiconductor":
        return 70, f"기본값 70({label} 미확인)"
    return None, f"{label} 미확인"


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

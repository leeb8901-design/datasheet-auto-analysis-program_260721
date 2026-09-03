# PDF 데이터시트를 실제로 분석해서 필요한 정보를 뽑아내는 파일이에요.
# 순서: ① PDF에서 글자 뽑기 -> ② 대분류/소분류 판별 -> ③ 그 소분류에 필요한 파라미터만 골라서
# 값 찾기. 규칙은 전부 프로젝트 루트의 CLAUDE.md와 '사용가이드라인' 시트를 코드로 옮긴 거예요.
#
# 이건 사람이 데이터시트를 읽고 판단하는 걸 흉내 내는 best-effort 분석이라서, 확신이 낮은
# 항목("confidence"가 낮거나 값이 None인 항목)은 반드시 사람이 데이터시트 원문과 대조해서
# 확인해야 해요 — CLAUDE.md의 "미확인 항목" 칸이 바로 이 확인이 필요한 항목들이에요.

from pathlib import Path

from ai import reference
from ai.classifier import (
    OSCILLATOR_CATEGORY,
    OSCILLATOR_SUBCATEGORY,
    classify,
    find_category_evidence,
    find_subcategory_evidence,
)
from ai.field_extractor import extract_field_values
from ai.pdf_text import extract_text
from ai.prompt import get_fields_for_subcategory, load_headers


def analyze_pdf(
    pdf_path: Path, fields: list[str] | None = None, thermal_mode: str = "case", part_number: str | None = None
) -> dict:
    """PDF 파일을 분석해서 분류 결과 + 필드값을 돌려줘요.

    thermal_mode: 열저항 기준. "case"=θJC(접합-케이스), "ambient"=θJA(접합-주위) — 둘 다
    데이터시트에 명시된 스펙값만 씀(217F 표 폴백 없음, reference.resolve_thermal_resistance 참고).
    GUI에서 사용자가 골라요.
    part_number: 지금 분석 중인 정확한 품번. 있으면 'Ordering Information' 표에서 이 품번과
    일치하는 줄의 패키지를 찾아 써요(한 데이터시트에 패키지가 여러 개 실려 있을 때 본문
    키워드 검색보다 훨씬 정확해요). 없으면 본문 키워드 검색만 해요.

    반환값:
        {
            "category": 대분류 이름 또는 None,
            "category_confidence": 대분류 확신 점수(0이면 근거를 못 찾음),
            "subcategory": 소분류 이름 또는 None,
            "subcategory_confidence": 소분류 확신 점수,
            "fields": {필드이름: 값(문자열) 또는 None, ...},
            "unmatched_fields": 값을 못 찾은 필드 이름 리스트,
            "reference_notes": {필드이름: 판정 근거 설명, ...},
            "evidence": {필드이름 또는 "__category__"/"__subcategory__": 원문 속 근거 문구, ...}
                (PDF 주석용, 2026-09-03 도입 - datasheet/annotator.py가 이 문구를 PDF에서
                찾아 하이라이트해요. 근거 문구를 못 찾은 값은 이 딕셔너리에 아예 안 들어있어요 -
                annotator는 그런 값을 "확인 필요"로 보고 표시하지 않아요).
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
    # field_extractor로 찾은 값은 원문 그대로의 부분 문자열이라(예: "3.3V"), 그 자체가 이미 PDF
    # 안에서 검색할 수 있는 근거 문구예요 - 그대로 evidence로 써요(2026-09-03 도입).
    evidence: dict[str, str] = {name: value for name, value in field_values.items() if value}

    if category:
        cat_evidence = find_category_evidence(text, category)
        if cat_evidence:
            evidence["__category__"] = cat_evidence
    if category and subcategory:
        sub_evidence = find_subcategory_evidence(text, category, subcategory)
        if sub_evidence:
            evidence["__subcategory__"] = sub_evidence

    # 참고자료(data/*.json) 기반 자동 판정 — 규칙 기반 추출로 비어 있는 값만 채워요
    # (기존 추출값은 절대 덮어쓰지 않아요). 참고표로 자동 판정한 값은 확신도가 낮으니
    # reference_notes에 근거를 남겨 사람이 데이터시트 원문과 대조하게 해요.
    reference_notes: dict[str, str] = {}
    if category and subcategory:
        _apply_reference(
            text, category, subcategory, field_values, reference_notes, evidence, thermal_mode, part_number
        )
        _enforce_valid_values(category, subcategory, field_values, reference_notes)
        # 유효성 검증에서 값이 비워진 필드는 evidence에도 남아있으면 안 돼요(값도 없는데 PDF에
        # 하이라이트만 남는 모순이 생기니까).
        evidence = {k: v for k, v in evidence.items() if k in ("__category__", "__subcategory__") or field_values.get(k)}

    unmatched = [name for name, value in field_values.items() if value is None]

    return {
        "category": category,
        "category_confidence": result["category_score"],
        "subcategory": subcategory,
        "subcategory_confidence": result["subcategory_score"],
        "fields": field_values,
        "unmatched_fields": unmatched,
        "reference_notes": reference_notes,
        "evidence": evidence,
    }


def _apply_reference(text, category, subcategory, field_values, notes, evidence, thermal_mode="case", part_number=None):
    """data/*.json 참고표로 Quality Level·Years in Production·Package Type·Thermal Resistance·
    Operating Power를 채워요(빈 값일 때만). Thermal Resistance는 데이터시트에 명시된 값만 쓰고
    (추정 금지), Operating Power는 명시값이 없으면 전압x전류로 계산해요.

    evidence: PDF 주석용 근거 문구 모음(2026-09-03 도입) - 채운 값에 원문 속 정확한 근거 문구가
    있으면 여기 같이 남겨요. 근거 문구가 없는 값(예: 물리 패키지를 못 찾아 기본값으로 확정한
    Package Type)은 evidence에 안 남기고 값만 채워요 - datasheet/annotator.py가 이 차이를 보고
    "근거 문구 있는 값은 그 자리에 하이라이트, 근거 없이 확정된 값은 대분류/소분류와 한데 묶어
    요약으로, 아예 못 채운 값은 표시 안 함"으로 나눠 처리해요.

    thermal_mode: "case"=θJC(접합-케이스) / "ambient"=θJA(접합-주위)."""
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
            temp_evidence = reference.find_temp_range_evidence(temp_source)
            if temp_evidence:
                evidence["Quality Level"] = temp_evidence
            notes["Quality Level"] = (
                f"온도범위({bucket}) 기반 자동판정"
                + (" · Commercial 고정(미허용)" if fixed else "")
            )

    # Years in Production: Revision History의 양산/최초 출시 연도 -> 현재까지 경과 연수를
    # 유효성 목록 5단계 버킷으로 판정해요(사용자 확정, 2026-08-27). 못 찾으면 기본값 '>=2.0'.
    if "Years in Production" in field_values and not field_values["Years in Production"]:
        grade, note, yip_evidence = reference.resolve_years_in_production(text)
        field_values["Years in Production"] = grade
        notes["Years in Production"] = note
        if yip_evidence:
            evidence["Years in Production"] = yip_evidence

    # 패키지 판별: ① 발주번호(Ordering Information) 매칭이 훨씬 정확하니 먼저 시도하고,
    # 못 찾을 때만(발주정보 표가 없거나 품번이 안 걸릴 때) 본문 키워드 검색으로 보완해요.
    confirmed_pkg = reference.find_ordering_package(part_number, text) if part_number else None
    pkg = confirmed_pkg or reference.find_package_in_text(category, text)

    # Package Type: 실제 물리적 패키지명(UTQFN-12 등)이 아니라 217F 표준 분류값(예:
    # "Nonhermetic: DIPs, PGA, SMT")이 정답이라, 확정된 패키지를 그 분류로 매핑해요. 이
    # 서브카테고리에서 허용되는 값 목록에 없으면(또는 애매하면) 잘못 우겨넣지 않고 비워둬요.
    # 물리 패키지명 자체를 못 찾아도(pkg=None) classify_package_type이 기본값으로
    # 떨어지니 그대로 시도해요(사용자 확정, 2026-08-30) - 이 경우 근거를 다르게 남겨요.
    if "Package Type" in field_values and not field_values["Package Type"]:
        allowed = reference.get_package_type_allowed(category, subcategory)
        classified = reference.classify_package_type(pkg, allowed)
        if classified:
            field_values["Package Type"] = classified
            if pkg:
                source = "발주정보(Ordering Information) 표" if confirmed_pkg else "본문 키워드 검색"
                notes["Package Type"] = f"{source}에서 확인한 패키지({pkg}) → 217F 분류 자동 매핑, 확인 권장"
                if confirmed_pkg and part_number:
                    # 발주정보 표에서 확인한 경우, PDF 근거 문구는 pkg(예: "UTQFN-12") 대신
                    # part_number 그대로를 써요. pkg만 쓰면 표지의 요약 스펙 표처럼 본문 다른
                    # 곳에 있는 같은 패키지명 언급에 먼저 걸려버려서, 실제로 이 판정에 쓰인
                    # 발주정보 표의 그 줄(정확한 품번이 있는 자리)이 아니라 엉뚱한 자리가
                    # 하이라이트되는 문제가 있었음 (IS31FL3296-UTLS4-TR에서 확인, 2026-09-03).
                    # part_number는 find_ordering_package가 이 문구로 본문에서 실제로 그 줄을
                    # 찾은 것이므로, PDF에서도 이 문구를 찾으면 같은 자리(발주정보 표)에 붙어요.
                    evidence["Package Type"] = part_number
                else:
                    # pkg 자체가 원문에서 찾은 물리 패키지명 그대로라(예: "UTQFN-12"), PDF에서 이
                    # 문자열을 그대로 검색해 하이라이트할 수 있어요.
                    evidence["Package Type"] = pkg
            else:
                notes["Package Type"] = "물리 패키지명을 특정하지 못해 기본값 적용(사용자 확정, 2026-08-30)"

    # Thermal Resistance: 데이터시트에 명시된 θJC/θJA 값만 채워요(없으면 공란 - 217F 표
    # 기본값이나 반도체 기본값으로 추정해서 채우지 않기로 확정함, 사용자 결정).
    if "Thermal Resistance" in field_values and not field_values["Thermal Resistance"]:
        # 확정된 패키지가 있으면, 패키지별로 여러 값이 병기된 경우(예: QFN/UTQFN 각각 다른
        # θJA) 그중 이 부품 패키지에 해당하는 값만 스펙값으로 써요.
        spec_value = reference.find_package_specific_thermal_value(pkg, text, mode=thermal_mode) if pkg else None
        val, src = reference.resolve_thermal_resistance(pkg, spec_value=spec_value, mode=thermal_mode)
        if val is not None:
            field_values["Thermal Resistance"] = str(val)
            if pkg:
                # spec_value가 있었다는 건 원문에서 이 숫자를 그대로 찾았다는 뜻이라(패키지별
                # 병기값 매칭), 그 숫자 문자열 자체가 PDF에서 찾을 근거 문구예요.
                evidence["Thermal Resistance"] = str(val)
            # Junction-: 이 값이 접합-케이스(θJC)인지 접합-주위(θJA)인지 표시해요 - GUI에서
            # 고른 열저항 기준(Case/Ambient) 그대로예요. "유효성 목록" 시트를 전수 확인해보니
            # 이 필드가 있는 모든 서브카테고리에서 허용값이 정확히 "Case"/"Ambient" 둘뿐이라
            # 별도 참고표 없이 thermal_mode를 그대로 옮기면 돼요. 값이 없을 땐(위에서 못 찾은
            # 경우) 기준만 적어두면 오해를 부르니 같이 비워둬요.
            if "Junction-" in field_values and not field_values["Junction-"]:
                field_values["Junction-"] = "Case" if thermal_mode == "case" else "Ambient"
        notes["Thermal Resistance"] = src

    # 커패시터 Capacitance/Rated Voltage: 발주정보(Ordering Information)의 품번 코드를
    # 해독해서 채워요(사용자 확정, 2026-09-03, T322D106K035AT 실전 분석). 데이터시트 본문에는
    # 그 "시리즈 전체"의 범위만 적혀 있어서(예: "0.1 to 330 μF") field_extractor가 그 범위
    # 문구를 이 부품 하나의 값으로 잘못 주웠을 수 있어요 - 이 방식이 성공하면 무조건 그걸로
    # 덮어써요(참고표 자동판정이 "빈 값만 채운다"는 일반 원칙의 예외 - 커패시터는 본문 근접
    # 매칭 자체가 이 필드에서 신뢰할 수 없다고 확인됐음).
    if category == "Capacitor" and part_number:
        cap_code = reference.find_capacitance_code(part_number, text)
        if cap_code:
            pf = reference.decode_eia_capacitance_code(cap_code)
            if pf is not None and "Capacitance" in field_values:
                value_str, unit = reference.format_capacitance_from_pf(pf)
                field_values["Capacitance"] = value_str
                if "Units" in field_values:
                    field_values["Units"] = unit
                notes["Capacitance"] = (
                    f"발주정보(Ordering Information) 품번 코드({cap_code}) 해독: "
                    f"{cap_code[:2]}×10^{cap_code[2]}pF = {value_str}{unit}"
                )
                # 근거는 발주정보 표의 "Capacitance Code (pF)" 칸 자체로 표시해요(사용자
                # 확정, 2026-09-03) - 실제 품번 코드 문자열("106" 등)은 발주정보 예시가 보통
                # 진짜 품번이 아니라 "T 32X A 105 M 035 A T" 같은 예시 코드라 문서에 그대로
                # 안 나오는 경우가 많아서, 대신 "이 칸을 보고 해독했다"는 그 칸 자체를 가리켜요.
                evidence["Capacitance"] = "Capacitance Code"

        volt_code, volt_value, volt_evidence = reference.find_rated_voltage_code(part_number, text)
        if volt_value is not None and "Rated Voltage" in field_values:
            field_values["Rated Voltage"] = str(volt_value)
            notes["Rated Voltage"] = f"발주정보(Ordering Information) 품번 코드({volt_code}) 해독: {volt_value}V"
            # 근거는 발주정보 표에서 실제로 대조한 "코드 = 값" 문구 그대로(예: "035 = 35") -
            # find_rated_voltage_code가 이미 원문에서 이 문구를 찾아 확인한 것이므로 정확해요.
            if volt_evidence:
                evidence["Rated Voltage"] = volt_evidence
            else:
                evidence.pop("Rated Voltage", None)

        # Series Resistance(ESR): 발주정보 품번의 "E"+3자리 코드가 mΩ 값을 그대로 나타내요
        # (사용자 확정, 2026-09-04, T495C107K010ATE100 사례: "E100"=100mΩ=0.1Ω → 유효성 목록
        # 버킷 "0 to 0.1"). Capacitance/Rated Voltage와 같은 이유로 무조건 덮어써요.
        esr_code, esr_evidence = reference.find_tantalum_esr_milliohms(part_number, text)
        if esr_code and "Series Resistance" in field_values:
            ohms = int(esr_code) / 1000
            bucket = reference.classify_series_resistance(ohms)
            field_values["Series Resistance"] = bucket
            notes["Series Resistance"] = f"발주정보(Ordering Information) 품번 코드({esr_evidence}) 해독: {int(esr_code)}mΩ = {ohms}Ω → {bucket}"
            # 품번 코드 문자열 자체는 발주정보 예시가 보통 진짜 품번이 아니라서 원문에 그대로
            # 안 나오는 경우가 많아요(Capacitance Code와 같은 이유) - 근거 문구 없이 값만
            # 확정된 걸로 남겨서 Category/Subcategory 요약에 함께 표시돼요.
            evidence.pop("Series Resistance", None)

    # Inductor/Coil의 Type: 페라이트 비드는 항상 "Power Filter"로 고정해요(사용자 확정,
    # 2026-09-03, BLM21PG121SN1D 사례) - 노이즈 억제용 수동 EMI 필터 부품이라 유효성 목록
    # 4개 허용값 중 Power Filter가 맞음. 앞으로 분석되는 모든 페라이트 비드 부품에 공통 적용.
    if category == "Inductor" and subcategory == "Coil" and "Type" in field_values and not field_values["Type"]:
        bead_evidence = reference.find_ferrite_bead_evidence(text)
        if bead_evidence:
            field_values["Type"] = reference.FERRITE_BEAD_TYPE
            notes["Type"] = "제목의 'ferrite bead' 문구 기준 자동 확정(페라이트 비드는 항상 Power Filter)"
            evidence["Type"] = bead_evidence

    # Miscellaneous/Quartz Crystal의 Frequency: 필드-프로그래머블 오실레이터는 품번에 주파수가
    # 고정돼 있지 않아서, 본문의 "Frequency f0 ... 10 460 MHz"처럼 그 시리즈 전체의 범위(Min)를
    # field_extractor가 잘못 주울 수 있어요(실제 확인: DSC8123CI5에서 "10"을 잘못 주움) - 그래서
    # 무조건 덮어써요(참고표 자동판정이 "빈 값만 채운다"는 일반 원칙의 예외, 커패시터 Capacitance/
    # Rated Voltage와 같은 이유). 데이터시트가 위상잡음 등 스펙 조건에 병기한 주파수(예:
    # "@156.25MHz")를 대신 씀(사용자 확정, 2026-09-03, DSC8123CI5 사례). 앞으로 분석되는 모든
    # "제목에 Oscillator가 있는" 부품에 공통 적용.
    if category == OSCILLATOR_CATEGORY and subcategory == OSCILLATOR_SUBCATEGORY and "Frequency" in field_values:
        freq_value, freq_evidence = reference.find_oscillator_frequency(text)
        if freq_value:
            field_values["Frequency"] = freq_value
            notes["Frequency"] = f"위상잡음 등 스펙 조건에 병기된 주파수 사용: {freq_evidence}"
            evidence["Frequency"] = freq_evidence

    # Resistor "SM Series"(TE Connectivity, SMW=Wire/SMF=Metal Film 표면실장 전력저항)의
    # Power Rating: 품번의 'SM' 뒤 사이즈 숫자로 "Characteristics – Electrical" 표의
    # "Power Rating @ 20°C SM_n" 값을 찾아 채워요(사용자 확정, 2026-09-03, SMW3100RJT 사례) -
    # field_extractor가 "Power Rating" 라벨 바로 뒤의 "@ 20°C"를 숫자+단위로 착각해서 잘못
    # 채우는 문제가 실제로 있었음 - 그래서 무조건 덮어써요.
    if category == "Resistor" and part_number:
        sm_value, sm_evidence = reference.find_sm_series_power_rating(part_number, text)
        if sm_value and "Power Rating" in field_values:
            field_values["Power Rating"] = sm_value
            notes["Power Rating"] = f"SM Series 품번 사이즈 코드 기준 확인: {sm_evidence}"
            evidence["Power Rating"] = sm_evidence

    # Power Rating: "Power Rating (50 VDC max.)\n70°C ... 0.15 watt"처럼 라벨 줄엔 전압 상한만
    # 있고 진짜 W(att) 값은 몇 줄 아래에 있는 표 레이아웃 보완(사용자 확정, 2026-09-03,
    # TC33X-2-102E 실전 분석) - field_extractor는 같은 줄만 봐서 못 찾은 경우에만 보충해요.
    if "Power Rating" in field_values and not field_values["Power Rating"]:
        pr_value, pr_evidence = reference.find_power_rating_watts(text)
        if pr_value:
            field_values["Power Rating"] = pr_value
            notes["Power Rating"] = f"라벨 근처 W(att) 값 확인(줄바꿈 너머): {pr_evidence}"
            evidence["Power Rating"] = pr_evidence

    # Semiconductor/Diode의 Diode Type/Construction Type (사용자 확정, 2026-09-03,
    # BZT52C8V2-7 실전 분석): 제너 다이오드는 Diode Type이 항상 "Voltage Regulator, Ref,
    # Zener"(유효성 목록 값)이고, Construction Type은 점접촉/스프링 로디드라는 명시가 없는 한
    # 항상 "Metallurgically"(오늘날 실리콘 다이오드 절대다수의 접합 방식 - Package Type
    # 기본값과 같은 패턴). 근거 문구가 없는 값이라(유효성 목록 문구 자체가 원문에 그대로 안
    # 나옴) evidence는 안 남기고 값만 채워요 - Category/Subcategory 요약에 함께 표시됨.
    if category == "Semiconductor" and subcategory == "Diode":
        if "Diode Type" in field_values and not field_values["Diode Type"]:
            diode_type = reference.find_zener_diode_type(text)
            if diode_type:
                field_values["Diode Type"] = diode_type
                notes["Diode Type"] = "제목/본문의 'zener' 문구 기준 자동 확정(제너 다이오드는 항상 Voltage Regulator, Ref, Zener)"
        if "Construction Type" in field_values and not field_values["Construction Type"]:
            field_values["Construction Type"] = reference.resolve_diode_construction_type(text)
            notes["Construction Type"] = "점접촉/스프링 로디드 명시가 없어 기본값 적용(오늘날 실리콘 다이오드 절대다수의 접합 방식)"

    # Semiconductor/Transistor의 Rated Voltage(Vceo 기준)/Application (사용자 확정,
    # 2026-09-04, 2SB1260T100R 실전 분석). 처음엔 이 소분류에 "Rated Voltage" 필드가 안
    # 잡혀서(PSA 입력 파라미터 시트를 읽는 tools/build_reference.py의 버그 - 파라미터 열
    # 사이에 빈 칸이 있으면 그 뒤 파라미터를 통째로 놓치는 문제였음, 아래 8번 참고) 대신
    # "Operating Voltage"에 채웠었는데, 그 버그를 고친 뒤 "Rated Voltage"가 실제로 있는 필드
    # 임을 확인해서 여기로 옮김 - VCEO(항복전압)는 "정격"(절대최대) 값이라 Rated Voltage가
    # 의미상으로도 더 맞음. 무조건 덮어쓰지 않고 빈 값일 때만 채움(field_extractor가 뭔가
    # 이미 정확히 찾았다면 그대로 존중).
    if category == "Semiconductor" and subcategory == "Transistor":
        if "Rated Voltage" in field_values and not field_values["Rated Voltage"]:
            vceo_value, vceo_evidence = reference.find_transistor_vceo(text)
            if vceo_value:
                field_values["Rated Voltage"] = vceo_value
                notes["Rated Voltage"] = f"VCEO(콜렉터-이미터 항복전압) 기준: {vceo_evidence}"
                evidence["Rated Voltage"] = vceo_evidence
        if "Application" in field_values and not field_values["Application"]:
            app_value, app_evidence = reference.resolve_transistor_application(text)
            if app_value:
                field_values["Application"] = app_value
                notes["Application"] = f"용도 설명 기준 자동판정({app_value}): {app_evidence}"
                evidence["Application"] = app_evidence

    # Operating Power: 데이터시트에 명시적인 소비전력 값이 없으면, 전압 x 전류로 계산해요
    # (기존 관례대로 mW 단위 숫자로 저장 - CLAUDE.md 7번). 항상 사람이 검토해야 하는 자동
    # 계산값이라 근거를 notes에 남겨요.
    if "Operating Power" in field_values and not field_values["Operating Power"]:
        aux = extract_field_values(text, ["Operating Voltage", "Operating Current"])
        voltage_raw, current_raw = aux.get("Operating Voltage"), aux.get("Operating Current")
        power = reference.compute_operating_power_mw(voltage_raw, current_raw)
        if power is not None:
            field_values["Operating Power"] = str(power)
            notes["Operating Power"] = f"자동 계산: {voltage_raw} x {current_raw} = {power}mW (확인 필요)"


def _enforce_valid_values(category, subcategory, field_values, notes):
    """CLAUDE.md 0번 원칙(2026-08-27): '유효성 목록' 시트에 허용값이 정의된 파라미터는 그 값
    중에서만 골라야 해요. 여기서는 지금까지(텍스트 매칭 + 참고표 자동판정) 채워진 모든 필드값을
    마지막으로 한 번 더 대조해서, 허용값 목록에 없는 값은 비워요(사람이 원문 대조 후 직접
    채우게 함). 이 목록에 아예 없는 파라미터(전압/전류처럼 연속 측정값)는 건드리지 않아요."""
    for field, value in list(field_values.items()):
        if value is None:
            continue
        allowed = reference.get_allowed_values(category, subcategory, field)
        if allowed is None:
            continue  # 유효성 목록 대상 파라미터가 아님 - 규칙 적용 안 함
        if reference.is_allowed_value(category, subcategory, field, value):
            continue
        prior_note = notes.get(field)
        notes[field] = (
            f"유효성 목록에 없는 값이라 비움(추출값: {value})"
            + (f" · {prior_note}" if prior_note else "")
        )
        field_values[field] = None


def get_extraction_fields() -> list[str]:
    # 매핑맵 컬럼 헤더(품번, Part Category, Part Subcategory + PSA 파라미터들)를 그대로 알려줘요.
    return load_headers()

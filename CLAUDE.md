# CLAUDE.md — 데이터시트 분석 기준 · 결정 로그

이 문서는 `데이터시트_다운로더` 프로그램으로 전자부품 데이터시트를 분석할 때 따르는 **기준/규칙**과,
실제로 부품을 분석하면서 사용자와 함께 정한 **판단 사례**를 모아두는 살아있는 문서입니다.

> 2026-08-27, 지금 방식(입력지/출력지 분리 + PSA 입력 파라미터 시트)에 맞게 전면 갱신했습니다.
> 예전 버전(4색 매핑맵, 별도 출력 워크북, PDF 주석)은 2026-07-31에 폐지되었습니다. 프로그램 구조
> 전체를 훑어보려면 [`소프트웨어_설계문서.md`](소프트웨어_설계문서.md)와
> [`00. 배포용/프로그램_정리본.md`](../00.%20배포용/프로그램_정리본.md)를 먼저 보세요. 이 문서는
> "분석 기준" 자체에 집중합니다.

---

## 0. 최우선 원칙 — 모든 파라미터 값은 `유효성 목록` 시트 기준

**모든 파라미터 입력값은 반드시 입력지의 `유효성 목록` 시트에 정의된 값 중에서 골라야 합니다.**
자유 서술로 값을 지어내지 않고, 그 시트에 적힌 표기를 정확히(철자·대소문자·구두점까지) 그대로 씁니다.

> 예시: `IS31FL3296-UTLS4-TR`(LED 드라이버 → IC/Linear)의 **Package Type** 값은
> `유효성 목록` 시트의 Linear 열 Package Type 허용값 5개
> (Can / DIP, Glass Seal / Flatpack / Hermetic: DIPs, PGA, SMT / **Nonhermetic: DIPs, PGA, SMT**)
> 중에서 고른 **`Nonhermetic: DIPs, PGA, SMT`** 입니다.

**코드 반영 (2026-08-27)**: `유효성 목록` 시트의 파라미터 칸 287개(94개 서브카테고리) 전체를
`data/valid_values.json`으로 뽑아내고(`tools/build_reference.py`의 `build_valid_values()`), 분석
파이프라인 맨 끝에서 모든 필드값을 이 목록과 대조하는 안전망을 추가했습니다
(`ai/reference.py`의 `get_allowed_values()`/`is_allowed_value()`, `ai/pdf_parser.py`의
`_enforce_valid_values()`, `analyze_pdf()`가 분류 후 자동 호출).

- 이 목록에 허용값이 있는 파라미터는, 채워진 값이 그 목록과 정확히(공백/대소문자 무시하고) 일치할
  때만 인정합니다. 안 맞으면 **자동으로 비우고** "유효성 목록에 없는 값이라 비움(추출값: …)"이라는
  근거를 남겨 사람이 확인하게 합니다.
- 이 목록에 아예 없는 파라미터(전압/전류/열저항처럼 연속 측정값)는 이 규칙 대상이 아니라서
  건드리지 않습니다 — `field_extractor.py`의 숫자 추출 결과 39종의 유효성 목록 파라미터 이름과는
  전혀 겹치지 않는다는 것도 확인했습니다.
- `Quality Level`·`Package Type`은 이미 전용 로직(`resolve_quality_level`/`classify_package_type`)이
  허용값 안에서만 답을 내므로, 이 안전망은 그 둘에는 사실상 통과만 시키고, 나머지 285개 칸에
  대해 실질적인 방어 역할을 합니다(다만 그 285개 파라미터는 아직 field_extractor가 값 자체를
  적극적으로 추출하지는 않아서, 지금 당장은 "잘못된 값이 들어가지 않는다"는 안전망 역할이고,
  "자동으로 값을 더 많이 채워준다"는 아닙니다 — 그건 앞으로 실제 부품을 분석하며 필요에 따라
  `field_extractor.py`에 추출 로직을 추가해 나갈 부분입니다).
- 샘플 데이터시트(`IS31FL3296-UTLS4-TR_예시.pdf`)로 end-to-end 재확인함: Category=Integrated
  Circuit, Subcategory=Linear, Package Type=`Nonhermetic: DIPs, PGA, SMT` (위 예시와 일치).

---

## 1. 이 프로그램이 하는 일

MIL-HDBK-217F Notice 2 기준으로 전자부품 데이터시트를 분석해, PTC Windchill Quality에 넣을 신뢰도
파라미터를 뽑아 엑셀에 채워 넣습니다. 판정은 **키워드/정규식 기반 규칙**으로 하며 AI(LLM)를 쓰지
않습니다 — 그래서 이 문서에 규칙을 정확히 적어두는 게 곧 프로그램의 정확도입니다.

- **입력지**: 사용자가 화면에서 "입력지 선택"으로 고르는 원본 엑셀. 프로그램은 끝까지 읽기만 함.
- **출력지**: "출력지 저장" 시 입력지를 통째로 복사해 만드는 사본. 이 위에만 결과를 씀.
- 입력지/출력지 모두 시트 5개: `부품리스트`, `217F 분석기준`, `분류기준`, `유효성 목록`,
  `PSA 입력 파라미터`.
  - `217F 분석기준`·`유효성 목록`은 사람이 관리하는 **규칙 원본**입니다(품질등급표, 열저항표,
    허용값 드롭다운 등). 프로그램은 이 시트를 직접 읽지 않고, `tools/build_reference.py`가 미리
    JSON으로 뽑아둔 걸 씁니다 → 규칙 시트를 고치면 **반드시 재생성**해야 반영됩니다(8번 참고).
  - `분류기준` 시트(2026-09-03 추가): 대분류/소분류를 프로그램이 어떤 키워드로 판별하는지 사람이
    보기 좋게 정리한 **참고용 문서**입니다. 프로그램은 이 시트를 읽지 않습니다(진짜 판별 로직은
    `ai/classifier.py`) — 아래 2·3번 표를 그대로 옮겨 넣은 것이라, `ai/classifier.py`의 키워드
    사전을 고치면 이 시트도 함께 갱신해야 합니다(현재는 수동 동기화 - `vba/Import_User.xlsx`에
    `tools/build_reference.py`와 별개로 존재하는 시트라 자동 재생성 대상이 아님).
  - `PSA 입력 파라미터` 시트: 서브카테고리별 "정의행" 아래에 부품마다 한 행. 정의행 셀 색이
    범례의 "관련자료(Datasheet) 등 제시 및 분석결과값 적용" 스와치 색과 같은 칸만 프로그램이
    채웁니다. 못 채우면 공백 + 노란색. 다른 색(Relex 자동계산/설계자 검토/Default)은 절대 안 건드림.

---

## 2. 대분류 판별 기준 (`ai/classifier.py`)

General Description/Features 문단의 키워드로, 대분류마다 가중치가 매겨진 힌트 단어 점수를 합산해
가장 높은 대분류를 고릅니다. 동점이면 **근거 개수가 더 많은 쪽**을 우선(점수가 같아도 근거 1개보다
근거 2개가 더 신뢰할 만함).

| 대분류 | 핵심 힌트 |
|---|---|
| Integrated Circuit | "integrated circuit", 패키지 코드(DIP/SOIC/TSSOP/QFN), op amp/comparator/LDO/voltage regulator, NAND/NOR gate/flip-flop/decoder/mux, MCU |
| Semiconductor | diode/rectifier/transistor/BJT/FET/MOSFET/thyristor |
| Resistor | resistor, resistance, power rating, ohm |
| Capacitor | capacitor, capacitance, WVDC |
| Inductor | inductor, coil, transformer, inductance |
| Connection | connector, socket, header |
| Switching Device | toggle/pushbutton/tactile/rocker/slide/dip/rotary switch |
| Relay | relay, coil voltage, contact rating |
| Optical Device | LED, photodiode, phototransistor, optocoupler, laser diode |
| Rotating Device | motor |
| Miscellaneous | fuse, crystal resonator, battery, filter, antenna, oscillator, gyroscope, loudspeaker, microphone (또는 위 어디에도 안 걸리면 기본값) |

**특수 규칙(2026-09-03 도입, DSC8123CI5 사례)**: 제목에 "Oscillator"(또는 "oscillators")가 있으면
대분류/소분류를 바로 `Miscellaneous`/`Quartz Crystal`로 확정함 — 대분류를 통째로 제목 우선으로
바꾸는 건 위험하다고 이미 확인됐지만(아래 참고), "oscillator"는 오탐 위험이 낮은 특정 단어라 예외로
둠. 앞으로 분석되는 모든 "제목에 Oscillator가 있는" 부품에 공통 적용(사용자 확정).

**특수 규칙(2026-09-04 도입, 2SB1260T100R 사례)**: 제목에 "Transistor"가 있으면 대분류를 바로
`Semiconductor`로 확정함 — 응용 예시에 "LED driver"가 한 번 언급됐다는 이유만으로
`\bled\b`(weight 3)가 `\btransistor\b`(weight 1)를 이겨서 Optical Device로 잘못 분류된 사고를
실측 확인함. Oscillator와 같은 이유로 예외로 둠(사용자 확정).

**주의(실제 사고 이력)**: `\bnor\b`, `\band\b`, `\bor\b` 처럼 논리 게이트 단독 단어는 절대 쓰지 않음
— 법률 고지문("...nor the rights of others...")이나 평범한 접속사에도 걸려서 아무 데이터시트나
Integrated Circuit/Logic으로 잘못 분류시킨 사고가 실제로 있었음. 항상 `\bnor gate\b`, `\band gate\b`처럼
구(phrase) 단위로만 매칭.

## 3. 소분류 판별 기준

대분류별로 전략이 다릅니다.

- **소분류 판별은 제목(첫머리)을 먼저 본다**(2026-09-03 도입) — 본문 어딘가에 스쳐 지나가는
  단어 하나 때문에 엉뚱한 소분류로 잘못 판정되는 사고를 막기 위해, 제네릭 매칭
  (`classify_subcategory_generic`)은 데이터시트 첫 300자(보통 제목이 있는 자리)에서 먼저
  찾고, 거기서 하나라도 걸리면 그 결과를 바로 씀(전체 본문은 안 봄). 못 찾을 때만 기존처럼
  전체 본문에서 찾음. **대분류는 이 방식을 안 씀** — 시도해봤다가 되돌림(아래 결정 로그
  2026-09-03 참고, IS31FL3296이 제목의 "LED" 때문에 Optical Device로 잘못 판정되는 회귀가
  실측 확인됨).
- **Integrated Circuit**: 전용 키워드 사전 사용.
  - `Logic, CGA or ASIC`: gate/NAND/flip-flop/decoder/buffer/inverter (단독 and/or/nor 금지, 위와 동일 이유)
  - `Linear`: op amp/comparator/voltage regulator/LDO/voltage reference, **그리고 "driver"는 항상 Linear**
    (LED 드라이버·모터 드라이버 등 — Logic이나 Microprocessor보다 아날로그 연속 구동에 가깝다고
    사용자가 확정, IS31FL3296 LED 드라이버 사례)
  - `Memory` (SRAM/DRAM/Flash/EEPROM/ROM), `Microprocessor` (CPU/MCU/processor core),
    `GaAs Digital`, `GaAs MMIC`, `Bubble Memory`, `PAL, PLA`, `SAW`, `VHSIC/VLSI CMOS` 등도 지원.
  - **`Custom` 소분류는 안 씀** — 현재 입력지(PSA 97개 정본)에 없어서 뽑아도 매핑에서 누락되므로 제거함.
- **Optical Device**: `Detector, Isolator, Emitter`(LED/photodiode/phototransistor/optocoupler),
  `Laser Diode`.
- **Semiconductor**: `Diode`(diode/rectifier/zener/TVS), `Si FET`(MOSFET/FET), `Transistor`(BJT/NPN/PNP),
  `Thyristor`(thyristor/SCR/triac), `Unijunction Transistor`.
- **Capacitor**(2026-09-03 T322D106K035AT 사례로 도입 -> 2026-09-04 T495C107K010ATE100
  사례로 단순화): 탄탈럼(소분류 이름에 "Tant"라는 줄임말이 들어있어서, 예: "Solid, Elec, Tant
  (CSR)", 제네릭 매칭이 본문의 "Tantalum"과 단어 경계가 안 맞아 절대 못 찾음 - `\bTant\b`는
  "Tantalum" 안에서 매칭 안 됨 - 그래서 전용 규칙 필요)은 **wet/non-solid라는 명시가 없는 한
  항상 `Solid, Elec, Tant (CSR)`(고체) 기본값, 명시가 있으면만 `Nonsolid, Elec, Tant (CL,
  CLR, CRL)`(습식)** — `Chip, Elec (CWR)`은 후보에서 뺌("Tantalum Surface Mount Capacitors"
  라는 표면실장 탄탈럼도 CSR이 맞다고 확인됨, "surface mount/chip/SMD" 같은 실장 방식
  언급만으로 CWR로 넘겨짚으면 안 됨). 그 외 21개 중 나머지 커패시터 소분류는 여전히 제네릭
  매칭(제목 우선) 사용.
- **Inductor**(2026-09-03 도입, BLM21PG121SN1D 실전 분석에서 확정): 페라이트 비드(ferrite
  bead)는 소분류 이름 "Coil"과 본문 표현이 안 겹쳐서(데이터시트가 "coil"이라 안 부르고
  "ferrite bead"라고만 부름) 전용 사전 사용 — `Coil`(ferrite bead / choke), `Transformer`
  (transformer / pulse transformer).
- **그 외 대분류**: `data/subcat_params.json`에 있는 소분류 이름 자체를 단어로 쪼개 본문에서 찾음
  (단어 경계 `\b` 필수 — 안 그러면 "FET"가 "MOSFET" 안에서도 잘못 걸림).

## 4. 파라미터 값을 채우는 기준

채워야 할 파라미터 목록은 `data/subcat_params.json`에서 그 서브카테고리에 적용되는 항목을 가져오되,
아래 종류는 **처음부터 시도하지 않고 제외**합니다(늘 사람 몫):

- PTC 자동 결정: `Pi Q Value`, `Case Temp Override`, `Junction Temp Override`, `Frame Temp Override`, `Hot Spot Temperature`
- 데이터시트로 원래 알 수 없음: `Initial Temp Rise`

> `Years in Production`은 2026-08-27 전에는 여기 있었지만(데이터시트로 알 수 없다고 봤음), 지금은
> 뺐습니다 — 아래 표 참고.

**값 찾는 순서**:
1. **텍스트 패턴 매칭** (`ai/field_extractor.py`) — 파라미터 동의어 근처(같은 줄, 40자 이내)의
   "숫자+단위"를 값으로 인정. 값의 모양이 정해진 필드(Thermal Resistance=`°C/W`, Pins=순수 숫자)는
   모양이 안 맞으면 버리고 다음 후보를 찾음(실제 사고: "4-layer test PCB"의 "4"를 열저항으로,
   "-0.3V"를 핀 개수로 잘못 주운 적 있음).
2. **참고표 자동 판정** (`ai/reference.py`, 1번으로 못 채운 값만 보충):

| 파라미터 | 판정 방법 |
|---|---|
| Quality Level | 본문에서 동작온도 범위 파싱 → `-55~125℃`/`-40~85℃`/`0~70℃` 버킷(최저·최고 **둘 다** 만족해야 인정, AND 조건) → `quality_by_temp.json` 조회. 그 등급이 서브카테고리에서 미허용이면 자동으로 `Commercial` 고정. **이 규칙은 Linear만이 아니라 Quality Level 파라미터가 있는 모든 서브카테고리에 똑같이 적용되는 공통 규칙**(사용자 확정, 2026-08-27) — `resolve_quality_level()`이 category/subcategory를 인자로 받아 어떤 서브카테고리에서 호출해도 같은 로직을 탐 |
| Package Type | ① 발주번호(Ordering Information) 표에서 **정확히 이 품번**과 일치하는 줄의 패키지 우선(가장 정확) → ② 없으면 본문 키워드 검색 → ③ **그래도 물리적 패키지명 자체를 못 찾으면 기본값 `Nonhermetic: DIPs, PGA, SMT`로 확정**(사용자 확정, 2026-08-30 — 오늘날 상용 부품 패키지 대부분이 비밀봉 플라스틱/SMT라는 전제). 이 기본값이 그 서브카테고리에서 애초에 허용 안 되면(허용 목록에 없으면) 그때만 진짜로 비움 |
| Thermal Resistance | **데이터시트에 명시된 값만** 사용(표 기본값 추정 절대 금지 — "미확인이 확인된 것처럼 보이는" 문제로 폐지됨). 화면에서 고른 Case(θJC)/Ambient(θJA) 기준의 문맥에 있는 값만 채택 — **데이터시트에 그 기준의 값이 아예 없으면(예: θJA만 있고 θJC가 없는 경우) 다른 기준으로 대신 채우지 않고 그냥 빈칸으로 둠**(사용자 확정, 2026-08-27 — 화면에서 고른 기준을 존중하는 게 우선, IS31FL3296-UTLS4-TR 사례: Case 선택 시 θJC가 없어 공란이 맞음). 패키지별로 값이 여럿이면 확정 패키지 것만 사용 |
| Operating Power | 명시된 소비전력이 없으면 전압×전류로 계산(mW로 저장) 시도는 함. **다만 실제 PSA 시트에서 이 칸이 "데이터시트" 색이 아니라 "설계자 검토" 색인 서브카테고리(Linear 확인됨)에서는, 계산까지 해봤자 4-1번 색 규칙에 걸려 아예 안 써짐** — 그런 서브카테고리에선 계산 자체가 무의미하니 사람이 판단 |
| Capacitance / Rated Voltage (Capacitor 전용) | **본문 근접 매칭을 안 믿고, 발주정보(Ordering Information)의 품번 코드를 해독해서 채움**(사용자 확정, 2026-09-03, T322D106K035AT 실전 분석) — 커패시터 데이터시트 본문에는 그 시리즈 "전체"의 범위만 적혀 있어서(예: "Rated Capacitance Range 0.1–330 μF", "Voltage rating of 2–50 VDC") 라벨 근처 숫자를 줍는 방식(field_extractor)이 이 부품 하나의 값이 아니라 그 범위 문구 자체를 잘못 채우는 사고가 실제로 있었음. 발주정보 표가 "Capacitance Code (pF)" + "significant figures"(EIA 3자리 코드 방식)를 쓴다고 스스로 설명하는 경우에만 시도: 품번에서 공차 문자(J/K/M/Z) 바로 앞 3자리가 커패시턴스 코드(앞 2자리=유효숫자, 3번째 자리=10의 거듭제곱, 예: `106`→10×10⁶pF=10µF, Units=`uF`), 그 바로 다음 자리가 Rated Voltage 코드(발주정보 표의 "코드=값" 쌍과 대조, 예: `035`→35V). 이 방식이 성공하면 field_extractor가 먼저 채운 값(범위 문구)이 있어도 **무조건 덮어씀** — "빈 값만 채운다"는 일반 원칙의 예외 |
| Type (Inductor/Coil 전용) | **제목에 "(chip) ferrite bead" 문구가 있으면 항상 `Power Filter`로 고정**(사용자 확정, 2026-09-03, BLM21PG121SN1D 실전 분석) — 유효성 목록 허용값(`Load`/`Power Filter`/`RF, Fixed or Molded`/`RF, Variable`) 중 페라이트 비드(노이즈 억제용 수동 EMI 필터)는 항상 이 값. 앞으로 분석되는 모든 페라이트 비드 부품에 공통 적용 |
| Rated Voltage / Application (Semiconductor/Transistor 전용) | **Rated Voltage는 VCEO(콜렉터-이미터 항복전압) 절댓값**(사용자 확정, 2026-09-04, 2SB1260T100R 실전 분석) — "V ... CEO" 표기(아래첨자가 값과 다른 줄로 추출되는 흔한 폰트 문제 감안)로 찾음. **Application은 Linear/Switching 중 용도 설명으로 판단** — 모터/LED 드라이버처럼 부하를 켜고 끄는 용도("driver"/"switching")면 Switching, 증폭기 용도("amplifier"/"linear")면 Linear, 둘 다(또는 둘 다 아님)면 애매하니 비워둠 |
| Diode Type / Construction Type (Semiconductor/Diode 전용) | **제너 다이오드(제목/본문에 "zener")는 Diode Type이 항상 `Voltage Regulator, Ref, Zener`**(유효성 목록 값, 사용자 확정, 2026-09-03, BZT52C8V2-7 실전 분석) — 제너는 전압 기준/레귤레이터 용도라는 것 자체가 이 타입의 정의. **Construction Type은 점접촉/스프링 로디드라는 명시가 없는 한 항상 `Metallurgically`**(오늘날 실리콘 다이오드 절대다수의 접합 방식, Package Type 기본값과 같은 패턴) — 둘 다 유효성 목록 문구 자체가 원문에 그대로 안 나와서 근거 문구 없이 값만 채우고 Category/Subcategory 요약에 함께 표시됨 |
| Operating Power (일반) | **각주 번호를 값으로 착각하는 사고 방지**(2026-09-03, BZT52C8V2-7: "Power Dissipation (Note 7) ... 500 mW"에서 "(Note 7)"의 "7"을 Operating Power로 잘못 채움) — Power Rating과 같은 이유로 W(att)/mW 단위가 확실한 후보만 인정하도록 값의 "모양"을 강화함(`ai/field_extractor.py`) |
| Power Rating (일반) | **라벨("Power Rating") 바로 다음 줄에 실제 W(att) 값이 있는 표 레이아웃**(예: "Power Rating (50 VDC max.)\n70°C ... 0.15 watt" - 라벨 줄엔 전압 상한만 있음)은 field_extractor가 같은 줄만 봐서 못 채움 - 이때 `ai/reference.py`의 `find_power_rating_watts()`가 몇 줄 아래까지 봐서 보충함(사용자 확정, 2026-09-03, TC33X-2-102E 실전 분석). `Power Rating` 필드는 항상 W(att) 단위만 인정하도록 값의 "모양"도 강화함(`ai/field_extractor.py`) — 안 그러면 라벨 옆 전압 상한("50 VDC")을 전력값으로 잘못 주움 |
| Series Resistance/ESR (Capacitor "탄탈럼" 전용) | **발주정보 품번의 "E"+3자리 코드가 mΩ 값을 그대로 나타냄**(사용자 확정, 2026-09-04, T495C107K010ATE100 실전 분석 - "E100"=100mΩ=0.1Ω) — Capacitance/Rated Voltage 코드와 달리 유효숫자+배수 공식이 아니라 직독(直讀) 방식. mΩ→Ω 변환 후 유효성 목록 5단계 버킷(Years in Production과 같은 내림 방식: `>0.8`/`>0.6 to 0.8`/`>0.4 to 0.6`/`>0.2 to 0.4`/`>0.1 to 0.2`/`0 to 0.1`)으로 매핑 |
| Power Rating (Resistor "SM Series" 전용) | **TE Connectivity SM Series(SMW=Wire/SMF=Metal Film 표면실장 전력저항)는 품번의 'SM' 뒤 사이즈 숫자(2/3/5/7)로 확정**(사용자 확정, 2026-09-03, SMW3100RJT 사례: SMW+`3` → SM_3 → 3.0 Watts) — "Characteristics – Electrical" 항목에 "Power Rating @ 20°C SM_&lt;사이즈&gt;: X.0 Watts"로 직접 표로 나와 있음. field_extractor가 "Power Rating" 라벨 바로 뒤의 "@ 20°C"를 숫자+단위로 착각해 잘못 채우는 문제가 있어서 무조건 덮어씀 |
| Frequency (Miscellaneous/Quartz Crystal 전용) | **필드-프로그래머블(field-programmable) 오실레이터는 품번에 주파수가 고정돼 있지 않아서**, 본문의 "Frequency f0 ... 10 460 MHz"(그 시리즈 전체 범위) 대신 **위상잡음(Phase Noise) 등 스펙 조건에 병기된 주파수(예: "@156.25MHz")를 사용**(사용자 확정, 2026-09-03, DSC8123CI5 실전 분석) — 데이터시트 안에서 유일하게 구체적인 소수점 단위 주파수가 나오는 자리. field_extractor가 범위의 Min값을 잘못 주웠어도 무조건 덮어씀 |
| Years in Production | **Years in Production 파라미터가 있는 모든 서브카테고리에 공통 적용**(사용자 확정, 2026-08-27 — Quality Level과 마찬가지로 특정 소분류 전용 규칙이 아님. `_apply_reference()`가 category/subcategory와 무관하게 항상 같은 로직을 탐). Revision History에서 **양산 출시(mass production)** 연도 우선 → 없으면 **최초 출시(initial release)** 연도 → 그마저 없으면 문서에 나오는 `Rev.` 개정 날짜 중 가장 이른 연도(근사치)를 씀. 연도를 하나라도 찾으면 `현재 연도 − 그 연도`를 유효성 목록 5단계 버킷(`>=2.0`/`1.5`/`1`/`0.5`/`<=0.1`, 내림 방식)으로 변환. **연도를 아예 못 찾으면 기본값 `>=2.0`**(신제품보다 이미 나와 있는 부품을 다루는 경우가 대부분이라는 전제). 분석 텍스트가 앞쪽 페이지 위주라 Revision History가 문서 뒤쪽에 있으면 못 찾는 경우가 흔함 — 그래서 기본값이 실제로 자주 쓰임 |

3. **Temperature Rise는 원래 프로그램이 채우는 파라미터가 아님** — PSA 시트에서 이 칸은 "Relex
   자동계산" 색(4-1번 참고)인 경우가 많고(Linear 확인됨), 그 경우 Windchill이 내부적으로 계산하는
   값이라 우리가 절대 안 건드림(사용자 확정, 2026-08-27). 예전에 이 문서(§5)가 "사람이 계산해서
   채운다"고 썼던 건 틀린 서술이었음 — 정정함.

모든 결과는 확신도와 무관하게 "검토" 창에서 사람이 확인하기 전까지 최종 확정으로 보지 않습니다.

**중요(작업 원칙, 2026-08-27 확정)**: Claude가 데이터시트 원문을 직접 읽고 "이 값이 맞을 것 같다"고
판단하더라도(예: 패키지명에서 핀 개수를 역산하는 것처럼), **자동 파이프라인(`field_extractor`/
`reference.py`)이 스스로 못 찾은 값을 대신 채워서 엑셀에 쓰지 않는다.** 그런 값은 채팅으로 근거와
함께 사람에게 제안만 하고, 엑셀에는 공백+노란색(4-1번 참고)으로 그대로 둬서 사람이 직접 판단하고
채우게 한다. (배경: IS31FL3296-UTLS4-TR 분석 중 Pins=12를 Claude가 직접 판단해서 써넣었다가,
사용자가 "확인 못 하는 값은 공백+노란색으로 두라"고 정정함.)

## 4-1. PSA 시트 색의 실제 의미 (테마 색, 2026-08-27 실측 확인)

`write_part()`가 값을 쓸지 말지는 **field_values에 값이 있는지가 아니라, 정의행 그 칸의 실제 색이
"데이터시트" 범례 색과 같은지**로 결정됩니다(1번 참고). 실제 `Data_list_217F.xlsx`의 PSA 시트를
열어 Linear 정의행(109행) 각 칸의 색을 직접 확인한 결과:

| 색 (openpyxl theme, tint) | 의미 | Linear에서 확인된 예 |
|---|---|---|
| `theme 4, tint 0.6` | **데이터시트** — 분석 파이프라인이 값을 채우는 대상. 값을 채우면 **색 없이 값만**(2026-08-27부터 — 정의행과 같은 색을 칠했더니 글자가 안 보인다는 피드백으로 뺌), 값이 없으면 노란색(`FFFFFF00`) | Quality Level, # of Transistors, Pins, Package Type, Years in Production, Thermal Resistance, Junction- |
| `theme 7, tint 0.8` | **Relex 자동계산** — Windchill이 내부에서 계산. 절대 안 건드림(값도 색도 안 넣음) | Temperature Rise |
| `theme 9, tint 0.8` | **설계자 검토** — 사람(설계자)이 직접 판단해서 채우는 칸. 절대 안 건드림 | Operating Power |
| 색 없음(무색) | Default — 이 서브카테고리엔 원래 없는 칸(다른 서브카테고리 전용 슬롯) | Pi Q Value, Initial Temp Rise, Junction Temp Override (이건 이 자리에선 그냥 무색이지, 색 규칙과 무관) |

**이 표는 Linear 기준 실측이며, 다른 서브카테고리는 같은 파라미터라도 색이 다를 수 있습니다** —
예: Operating Power가 다른 서브카테고리에선 데이터시트 색일 수도 있음. 애매하면 그때그때
`psa_writer.color_key(정의행 셀)`로 직접 확인할 것.

## 5. 단위 규칙 (반드시 유지)

- `Operating Power`는 **mW 단위 숫자**를 그대로 저장 (예: 55µW → `0.055`) — 단, 4-1번 표대로
  이 칸이 "설계자 검토" 색인 서브카테고리에서는 애초에 안 써짐.
- `Temperature Rise`는 **채우지 않음** — Windchill(Relex) 자동계산 대상 (4-1번 참고, 예전에 여기
  적혀있던 "사람이 계산" 공식은 틀린 서술이라 삭제함).
- 열저항 기준(Case=θJC vs Ambient=θJA)은 화면에서 선택. **어느 쪽을 선택했든 그 기준의 데이터시트
  값만 인정하고(표 폴백 없음), 선택 안 한 기준값으로 대신 채우지 않음** — 값이 없으면 공란+노란색.

## 5-1. PDF 주석 ("클로드분석" PDF, 2026-08-27 도입)

엑셀(PSA 시트)에 채운 값의 **근거를 원본 데이터시트 PDF 위에 직접 표시**하는 산출물입니다. 예전
`datasheet/annotator.py`(2026-07-31에 삭제됨)와는 다른 새 방식으로, 사용자가 직접 만든 예시
(`IS31FL3296-UTLS4-TR_예시안.pdf`)의 형식을 그대로 따릅니다.

- **형식**: PyMuPDF(`fitz`)의 **하이라이트 주석**(`add_highlight_annot`) + 팝업 메모. 메모 내용은
  `파라미터 : 값` 줄바꿈 나열.
- **위치 원칙(2026-08-27 확정)**: **판정에 실제로 쓰인 정확한 근거 문구**에만 붙임 — 섹션 제목 같은
  대략적인 위치가 아니라, `page.search_for()`로 그 값을 결정한 진짜 문구를 찾아 붙임. 예:
  Quality Level → `-40°C ~ +125°C`(동작온도 범위 그 문구 자체), Category/Subcategory=Linear →
  `LED DRIVER`(classifier.py가 "driver" 키워드로 매칭한 그 문구), Package Type → Ordering
  Information의 품번 행.
- **찾지 못한 값(확인 필요)은 PDF에 표시하지 않음** — 근거 문구가 없어 정확한 위치를 특정할 수
  없고, 엑셀 PSA 시트의 노란색 표시로 이미 충분히 드러남. PDF 주석은 "찾은 근거"만 보여주는 용도.
  (예전 `datasheet/annotator.py`는 못 찾은 값을 1페이지 요약 주석으로 모았지만, 이번엔 사용자가
  그 방식 대신 "못 찾은 건 아예 표시하지 않기"로 확정함 — 예전 설계를 그대로 따르지 않음.)
- **단, "확인 필요"(공란)와 "근거 문구 없이 기본값으로 확정"은 다름**(사용자 확정, 2026-08-30) —
  Package Type/Years in Production의 기본값(4번 표 참고)처럼 도구가 실제로 값을 확정했지만 특정
  문구가 근거가 아닌 경우는, **Category/Subcategory와 같은 자리(근거 문구가 없는 값들의 요약
  위치)에 함께 적음**. "확인 필요"라 안 보여주는 것과 혼동하지 말 것 — 이건 보여줌.
- **지금은 `tools/annotate_datasheet.py`가 IS31FL3296-UTLS4-TR 전용**입니다 — 검색어/페이지 매핑을
  이 데이터시트에 맞춰 하드코딩했습니다. 아직 범용 함수로 안 뺐습니다(여러 부품을 더 만들어보고
  공통 패턴이 보이면 일반화할 것 — 예: `analyze_pdf()`의 `fields`/`reference_notes`를 입력받아
  자동으로 근거 문구를 검색하는 범용 버전).
- 출력 파일명 규칙: `<품번>_클로드분석.pdf` (엑셀의 `Data_list_217F_클로드분석.xlsx`와 같은
  "클로드분석" 접미사 사용).

## 6. 참고 데이터 파일 (`data/*.json`)

`tools/build_reference.py`가 입력지의 `217F 분석기준`·`유효성 목록`·`PSA 입력 파라미터` 시트를 읽어
아래 9개를 **매번 새로 생성**합니다(엑셀=원본, JSON=생성물 — 엑셀을 고치면 이 스크립트를 다시 돌릴 것):

```
python tools/build_reference.py
```

- `subcat_params.json`, `headers.json` — 서브카테고리별 적용 파라미터 / 컬럼 헤더
- `quality_by_temp.json`, `quality_allowed.json` — 품질등급 판정표 · 서브카테고리별 허용값
- `thermal_resistance.json` — 패키지별 θJC 폴백표
- `package_type_allowed.json` — 서브카테고리별 허용 Package Type 분류값
- `valid_values.json` — **`유효성 목록` 시트 전체(287개 파라미터 칸)의 허용값** (0번 원칙의 근거 데이터,
  2026-08-27 추가)
- `env_conversion.json`, `temp_conversion.json` — MTBF 환경/온도 변환 팩터

> `params124.json`, `parts_list_snapshot.json`, `mapping_map_snapshot.json`은 예전(2026-07-31 이전)
> 방식의 잔재로, 지금 코드 어디에서도 읽지 않습니다. 정리 대상이지만 아직 지우지는 않았습니다.

**완료된 부품 목록은 이 문서에 따로 안 둡니다** — 출력지 엑셀(PSA 입력 파라미터 시트) 자체가 최신
소스입니다. 이 문서 7번에는 "몇 번 품번을 처리했다"가 아니라 **판단 기준 자체가 애매해서 새로 정한
규칙**만 남깁니다.

---

## 7. 부품별 분석 결정 로그

실제 데이터시트를 분석하다가 기존 규칙만으로 애매했던 사례, 새로 정한 규칙, 예외 처리를 여기에
날짜순으로 쌓습니다. 아래 형식을 따라주세요.

```
### YYYY-MM-DD — 품번 (제조사)
- 상황: (무엇이 애매했는지)
- 결정: (어떻게 하기로 했는지)
- 반영: (코드/데이터를 고쳤다면 어느 파일을 고쳤는지, 아직 코드 미반영이면 "미반영"이라고 표시)
```

### 2026-08-27 — 원칙 확정: 유효성 목록 시트가 모든 파라미터 값의 기준
- 상황: 파라미터 값을 어떤 기준으로 확정할지가 명확히 정의된 적이 없었음.
- 결정: 모든 파라미터 입력값은 `유효성 목록` 시트에 있는 값 중에서만 고른다(자유 서술 금지).
  예시로 `IS31FL3296-UTLS4-TR`의 Package Type = `Nonhermetic: DIPs, PGA, SMT`를 확인함
  (Linear 서브카테고리의 허용값 5개 중 하나, 실제 엑셀에서 대조 완료).
- 반영: 문서 0번에 최우선 원칙으로 기록. **같은 날 코드에도 반영 완료** —
  `tools/build_reference.py`에 `build_valid_values()` 추가 → `data/valid_values.json`(287개
  파라미터 칸 전체) 생성. `ai/reference.py`에 `get_allowed_values()`/`is_allowed_value()` 추가.
  `ai/pdf_parser.py`에 `_enforce_valid_values()` 추가해 `analyze_pdf()` 마지막 단계에서 전체
  필드값을 이 목록과 대조 → 안 맞으면 자동으로 비우고 근거 기록. 샘플 PDF로 확인 완료(위 0번 참고).
  **남은 일**: 285개 미확보 파라미터(Type/Construction Type/Contact Form 등)는 안전망만 걸려있고
  `field_extractor.py`가 아직 값 자체를 추출하지 않음 — 실제 부품 분석하며 필요한 것부터 추출
  로직 추가 예정.

### 2026-08-27 — IS31FL3296-UTLS4-TR 첫 실전 분석: 5가지 원칙 확정
- 상황: 이 품번을 실제로 분석하면서, PSA 시트에 값을 채우는 기준이 몇 가지 불명확했음.
  (a) Quality Level의 온도버킷 규칙이 Linear에만 적용되는 건지, (b) Claude가 도구 대신 직접
  판단한 값(예: 패키지명에서 역산한 Pins=12)을 엑셀에 써도 되는지, (c) 이 부품은 θJC가 없고
  θJA만 있는데 화면이 Case 기준이면 어떻게 해야 하는지, (d) Temperature Rise를 채워야 하는지,
  (e) Operating Power를 지금 채워도 되는지.
- 결정:
  (a) Quality Level 온도버킷 규칙은 **모든 서브카테고리에 공통** — Linear 예시일 뿐 특수 규칙 아님.
  (b) Claude가 자동 도구 없이 직접 판단한 값은 **절대 엑셀에 안 씀** — 공백+노란색으로 두고
      채팅으로만 근거를 제안, 사람이 최종 판단.
  (c) Thermal Resistance/Junction-는 **화면에서 고른 기준(Case/Ambient)의 데이터시트 값만** 인정.
      그 기준의 값이 없으면 다른 기준으로 대신 채우지 않고 공백+노란색.
  (d) Temperature Rise는 **절대 안 채움**(Windchill/Relex 자동계산 대상).
  (e) Operating Power는 **지금은 공백, 색도 안 넣음**.
- 반영: (d)(e)는 실제 PSA 시트 셀 색을 열어보니 이미 코드가 올바르게 동작 중이었음(4-1번 표:
  Temperature Rise=Relex자동계산 색, Operating Power=설계자검토 색 — 둘 다 애초에 안 써지는 칸).
  코드 수정 없음, CLAUDE.md 4번/4-1번/5번에 색의 실제 의미와 근거를 문서화함. (a)(b)(c)는 CLAUDE.md
  4번에 원칙으로 명시. `Data_list_217F_클로드분석.xlsx`를 이 원칙대로 다시 저장함(Quality
  Level=B-1, Package Type=Nonhermetic: DIPs, PGA, SMT만 값 있음, 나머지 데이터시트색 칸은 공백+
  노란색).

### 2026-08-27 — 같은 부품 2차 수정: 값 칸 색 제거 + Years in Production 규칙 신설
- 상황: 위 결과물을 사용자가 실제로 열어보니 두 가지 문제가 있었음. (a) 값을 채운 칸에 정의행과
  같은 색을 칠했더니 배경색과 글자색이 겹쳐 값이 잘 안 보임(예: Quality Level 칸 색과 "B-1" 글자
  구분이 안 됨). (b) Years in Production이 계속 공백으로 남아있었음.
- 결정:
  (a) 값을 채운 칸은 **색을 아예 안 칠한다**(정의행 색 복사 중단). 값 없는 칸만 노란색 유지.
  (b) Years in Production은 더 이상 "데이터시트로 알 수 없음" 취급하지 않는다. Revision History의
      양산/최초 출시 연도 → 현재 연도 기준 경과 연수 → 유효성 목록 5단계 버킷으로 자동 판정한다.
      연도를 못 찾으면 기본값 `>=2.0`.
- 반영: `excel/psa_writer.py`의 `write_part()`에서 값 채운 칸의 `pcell.fill = copy(def_cell.fill)`
  줄 삭제(미사용된 `from copy import copy` 임포트도 제거). `ai/reference.py`에
  `find_production_year()`/`classify_years_in_production()`/`resolve_years_in_production()` 추가.
  `ai/prompt.py`의 `UNKNOWN_FROM_DATASHEET_FIELDS`에서 `Years in Production` 제거. `ai/pdf_parser.py`
  의 `_apply_reference()`에 Years in Production 처리 블록 추가. 샘플 부품으로 재확인:
  `Years in Production` = `>=2.0`(이 데이터시트는 8페이지 이내에 Revision History 원본이 없어
  현재 페이지 안의 `Rev. D, 2024` 개정일을 근사치로 씀 → 2년 경과 → `>=2.0`, 우연히 기본값과
  같은 결론). `Data_list_217F_클로드분석.xlsx` 재저장 완료, 값 칸 무색 확인함.
  **5단계 버킷 매핑 방식 확정(2026-08-27)**: "내림(floor)" 방식이 맞다고 사용자가 확인함 — 경과
  연수보다 큰 버킷을 절대 고르지 않고, 그 이하인 앵커 중 가장 큰 걸 고름(예: 1.7년 경과 → `1.5`,
  0.5년 미만은 전부 `<=0.1`). `ai/reference.py`의 `classify_years_in_production()`/`_YIP_ANCHORS`가
  이미 이 방식으로 구현돼 있어 추가 코드 변경 없음.

### 2026-08-27 — Years in Production 범위 확인 + PDF 주석("클로드분석" PDF) 도입
- 상황: (a) 앞서 만든 Years in Production 규칙이 IS31FL3296(Linear)에서만 검증됐던 터라 다른
  서브카테고리에도 똑같이 적용되는지 확인이 필요했음. (b) 이제 엑셀에 채운 값의 근거를 원본
  데이터시트 PDF 위에도 표시하고 싶어짐 — 사용자가 원하는 형식의 예시 PDF(`_예시안.pdf`)를 직접
  만들어 프로젝트에 올려둠.
- 결정: (a) Years in Production 규칙은 Quality Level과 동일하게 **이 파라미터가 있는 모든
  서브카테고리에 공통 적용**(코드는 이미 category 무관하게 동작 중이었음 - 확인만 하면 됐음.
  실제 `data/subcat_params.json` 전수 조사 결과 이 파라미터는 IC 계열 9개 서브카테고리에만 존재).
  (b) 예시 PDF를 PyMuPDF로 열어 분석한 결과, 하이라이트 주석(`add_highlight_annot`) + 팝업 메모
  (`파라미터 : 값` 형식) 방식임을 확인 → 같은 형식으로 `IS31FL3296-UTLS4-TR_클로드분석.pdf` 생성.
- 반영: (a) 코드 변경 없음, CLAUDE.md 4번 Years in Production 행에 "모든 서브카테고리 공통" 명시.
  (b) 새 스크립트 `tools/annotate_datasheet.py` 작성(지금은 이 품번 전용, 범용화는 안 함) → 5-1번에
  문서화. 근거 문구 위치는 `page.search_for()`로 실제 데이터시트에서 다시 찾아 붙임(예시 PDF의
  페이지 위치를 그대로 베끼지 않고, 진짜 근거가 있는 위치 우선 - 열저항 미확인 사유는 예시가 쓴
  페이지27(패키지 도면)이 아니라 실제 θJA 스펙이 적힌 Absolute Maximum Ratings 페이지에 붙임).

### 2026-08-27 — PDF 주석 규칙 정정: 근거 문구 정확히 짚기 + 미확인 값은 표시 안 함
- 상황: 위에서 만든 첫 버전 PDF 주석에 두 가지 문제가 있었음. (a) Category/Subcategory 하이라이트를
  "GENERAL DESCRIPTION"이라는 섹션 제목에 붙였는데, 이건 실제 판정 근거 문구가 아니라 그냥 근처
  헤딩이었음(Quality Level을 "-40°C ~ +125°C"라는 정확한 근거 문구에 붙인 것과 다른 기준). (b) 못
  찾은 값(Pins/Thermal Resistance/Junction-/# of Transistors)에 "확인 필요"라고 PDF에도 표시했음.
- 결정:
  (a) 하이라이트는 **판정에 실제로 쓰인 정확한 문구**에만 붙인다. Category/Subcategory(=Linear)는
      `classifier.py`가 "driver" 키워드로 판정했으므로, 그 키워드가 실제 나타나는 표지 제목의
      "LED DRIVER" 문구에 붙인다.
  (b) **찾지 못한 값은 데이터시트에 아예 표시하지 않는다** — 근거 문구가 없어 정확한 위치를 특정할
      수 없고, 엑셀 PSA 시트의 노란색 표시로 이미 충분히 드러남. PDF 주석은 "찾은 근거"만 보여주는
      용도로 한정.
- 반영: `tools/annotate_datasheet.py` 수정 — Category/Subcategory 하이라이트를
  `page.search_for("LED DRIVER")`(표지 제목)로 변경, Pins/Thermal Resistance·Junction-/
  # of Transistors 하이라이트 블록 3개 전부 삭제(4개 → 이제 정확히 4개: Category/Subcategory,
  Years in Production, Package Type, Quality Level만 남음). `IS31FL3296-UTLS4-TR_클로드분석.pdf`
  재생성 완료.

### 2026-08-29 — SI53340-B-GM 분석: 온도 파싱 버그 발견/수정 + 8페이지 제한 근거 확인
- 상황: 새 부품(SI53340-B-GM, Skyworks LVDS 팬아웃 클럭 버퍼)을 분석하다가 두 가지를 발견함.
  (a) Quality Level이 명백히 틀린 값(`Commercial`)으로 나옴 — 원문은 "Temperature range: –40 to
  +85 °C"인데(동작온도 버킷상 B-1이어야 함), 이 "–40"의 "–"가 아스키 하이픈이 아니라 **en dash
  (U+2013)** 라서 `parse_temp_range`의 숫자 패턴이 부호를 못 읽고 "40"(양수)으로 잘못 파싱함.
  (b) 자동 도구가 8페이지까지만 읽어서 Package Type/Pins/Thermal Resistance 등 여러 값을 못 찾음 —
  실제로는 이 정보가 있지만(패키지=16-QFN, θJC=41.5°C/W 등) 전부 8페이지 밖(17~23페이지)에 있었음.
- 결정:
  (a) **온도 범위 파싱은 en dash 등 타이포그래피 대시도 마이너스 부호로 인식해야 한다** — 실제
      데이터시트가 아스키 하이픈(-) 대신 이런 문자를 쓰는 경우가 있으므로 이건 이 부품만의 문제가
      아니라 앞으로 분석할 모든 부품에 영향을 주는 근본 버그로 판단, 코드로 수정.
  (b) **`ai/pdf_text.DEFAULT_MAX_PAGES`(8페이지)는 늘리지 않는다** — 이 부품의 전체 38페이지 텍스트로
      같은 파이프라인을 다시 돌려본 결과, 뒤쪽 페이지의 저항/터미네이션 관련 문구(Ω, 저항값 등)가
      너무 많이 섞여서 대분류가 **Integrated Circuit이 아니라 Resistor로 완전히 잘못 판정**되는 것을
      실측으로 확인함 — 페이지를 늘리는 게 "더 많이 찾기"가 아니라 "분류 정확도를 해치는" 결과를
      낳음. 8페이지 제한은 성능뿐 아니라 **분류 정확도를 지키는 안전장치**이기도 했음이 확인됨.
      대신, 8페이지 밖에 있는 값은 도구가 못 찾는 게 정상이고(설계상 트레이드오프), 사람이 직접
      원문을 더 읽어 판단하고 채워야 함(4-1번 원칙과 동일 - Claude가 수동으로 찾은 값은 엑셀/PDF에
      안 씀, 채팅으로만 제안).
- 반영: `ai/reference.py`의 `_TR_NUM`(온도 파싱 숫자 패턴)에 en dash 등(U+2010~U+2015, U+2212)을
  부호로 포함하는 `_TR_SIGN` 문자클래스 추가 + `_to_int()` 헬퍼로 int() 변환 전 정규화. 기존 아스키
  하이픈 케이스 회귀 없음 확인(IS31FL3296 재검증: 여전히 B-1). `data/*.json` 재생성 불필요(코드만
  변경, 참고표는 그대로). `SI53340-B-GM_클로드분석.xlsx`/`.pdf`를 `클로드 학습자료/` 폴더에 생성
  (Quality Level=B-1, Years in Production=`>=2.0`만 값 있음 - 둘 다 8페이지 안에서 실제로 찾은 값).
  Package Type(16-QFN 발주정보가 품번 앞줄에 있어 줄 기반 매칭 실패)·Pins(16, 22페이지 핀 표)·
  Thermal Resistance(θJC 41.5°C/W, θJA 57.6°C/W, 17페이지 표)는 Claude가 원문을 더 읽어서 찾았지만
  자동 도구는 못 찾은 값이라 파일에는 안 쓰고 채팅으로만 보고함.

### 2026-08-30 — Package Type도 Years in Production처럼 "확정 기본값" 규칙 신설
- 상황: SI53340-B-GM은 발주정보 표 레이아웃 문제로 물리 패키지명(pkg) 자체를 못 찾아 Package Type이
  계속 공란으로 남았음. Years in Production은 이미 "못 찾으면 기본값 `>=2.0`" 규칙이 있는데
  Package Type엔 그런 기본값 규칙이 없었음.
- 결정:
  (a) Package Type도 물리 패키지명을 정말 못 찾으면 기본값 `Nonhermetic: DIPs, PGA, SMT`로 확정한다
      (Years in Production과 같은 패턴 — "정확한 값 못 찾으면 이 기본값" 규칙).
  (b) PDF 주석에서, 이렇게 **근거 문구 없이 기본값으로 확정된 값**(Package Type/Years in
      Production)은 "확인 필요"라서 안 보여주는 것과 다르게 — Category/Subcategory와 같은 자리에
      함께 적어서 보여준다.
- 반영: `ai/reference.py`의 `classify_package_type()` — `package`가 `None`이어도(전혀 못 찾음)
  `allowed`에 기본값이 있으면 그 기본값으로 떨어지도록 수정(기존엔 `if not package: return None`로
  아예 시도조차 안 했음). `ai/pdf_parser.py`의 `_apply_reference()` — Package Type 분기의
  `and pkg` 조건 제거, `pkg`가 없을 때 근거 문구를 다르게 남김("물리 패키지명을 특정하지 못해
  기본값 적용"). 회귀 확인: IS31FL3296(패키지 찾음)은 그대로 동일하게 동작. `SI53340-B-GM_
  클로드분석.xlsx`/`.pdf` 재생성 — Package Type이 이제 값 있음(무색), PDF는 Category/Subcategory
  하이라이트에 Package Type·Years in Production 기본값 두 줄을 추가로 묶어서 표시. 새 스크립트
  `tools/annotate_si53340.py`로 저장.

### 2026-09-03 — 자동 PDF 주석이 수작업으로 확정한 표시 방법과 어긋난 문제 수정
- 상황: `IS31FL3296-UTLS4-TR`을 사람이 직접 분석하며 확정한 PDF 표시 방법
  (`tools/annotate_datasheet.py`, `클로드 학습자료/IS31FL3296-UTLS4-TR_클로드분석.pdf`)을
  프로그램의 "신뢰도 분석" 버튼에서 실제로 재생성해보니 다르게 나옴을 발견함. (a) Category/
  Subcategory 요약이 "LED DRIVER"(Subcategory=Linear를 실제로 결정한 문구)가 아니라, 본문
  어딘가에 우연히 한 번 나온 "MCU"(대분류 근거 - 실제 판정에 결정적이지 않은 약한 단서)
  자리에 붙음. (b) Package Type이 실제 발주정보(Ordering Information) 표의 그 품번 행이
  아니라, 표지의 요약 스펙 표에 같은 패키지명("UTQFN-12")이 우연히 또 나온 자리에 붙음.
- 결정: (a) Category/Subcategory 요약 앵커는 **소분류 근거를 대분류 근거보다 먼저** 쓴다 -
  소분류 근거(예: "driver")가 훨씬 구체적/결정적인 경우가 많고, 대분류 근거는 본문에 스쳐
  지나가듯 나온 약한 단어일 수 있음. (b) 발주정보 표로 확인한 Package Type의 PDF 근거 문구는
  패키지명 자체("UTQFN-12")가 아니라 **정확한 품번(part_number) 그대로**를 쓴다 -
  `find_ordering_package`가 애초에 이 품번 문구로 그 표의 그 줄을 찾은 것이므로, PDF에서도
  같은 문구를 찾으면 같은(진짜 근거) 자리에 붙는다.
- 반영: `datasheet/annotator.py`의 앵커 선택 순서를 `__subcategory__` → `__category__`로
  변경. `ai/pdf_parser.py`의 `_apply_reference()` - Package Type이 `confirmed_pkg`(발주정보
  매칭)로 확정됐고 `part_number`가 있으면 `evidence["Package Type"] = part_number`(기존엔
  `pkg`), 본문 키워드 검색으로만 확정된 경우는 기존처럼 `pkg` 그대로 유지. `IS31FL3296-
  UTLS4-TR` 원본 PDF로 재검증: `_highlight()` 호출을 직접 추적해 정확히 4번만 호출됨을
  확인(Quality Level/Years in Production/Category+Subcategory→1페이지, Package Type→5페이지 -
  수작업 기준 파일의 페이지 배치와 일치). `SI53340-B-GM`도 결정 로그상 Subcategory 근거
  ("Buffers")를 앵커로 썼던 사례라 이 변경과 방향이 일치함(원본 PDF가 남아있지 않아 재실행은
  못 했지만 로직상 회귀 없음 확인).

### 2026-09-03 — T322D106K035AT (KEMET) 첫 커패시터 분석: 소분류/Capacitance/Rated Voltage 3가지 규칙 신설
- 상황: 커패시터를 처음 실전 분석하면서 세 가지가 잘못됨을 확인함. (a) 소분류가
  "Solid, Elec, Tant (CSR)"이어야 하는데 "Feed Through, Paper (CZ, CZR)"로 잘못 판정됨 —
  본문의 "Through-Hole"의 "Through"가 그 소분류 이름과 우연히 겹쳐서 매칭됐고, 정작 맞는
  소분류("Tant"라는 줄임말)는 "Tantalum"과 단어 경계가 안 맞아 애초에 매칭 후보에도 못 낌.
  (b) Capacitance가 데이터시트 본문의 "Rated Capacitance Range 0.1 – 330 μF"(그 시리즈 전체
  범위)를 그대로 주워서 "0.1 to 330 μF"로 잘못 채워짐. (c) Rated Voltage도 마찬가지로
  "Voltage rating of 2 – 50 VDC"에서 "2"만 잘못 주워짐. 실제 정답(사용자 제시)은 품번
  T322D106K035AT 자체를 발주정보(Ordering Information) 표의 코드 규칙으로 해독해야 나옴:
  Capacitance Code `106`→10×10⁶pF=10µF, Rated Voltage 코드 `035`→35V(표에 코드=값 쌍이
  직접 나열돼 있음).
- 결정:
  (a) 대분류/소분류는 **데이터시트 제목(첫머리)을 기준으로 찾는다.** 탄탈럼 3종(Solid/Chip/
      Nonsolid)은 실장 방식(through-hole·molded·axial / chip·SMD / wet)으로 구분하는 전용
      키워드 사전을 새로 둔다. 그 외 소분류는 기존 제네릭 매칭(소분류 이름 단어 매칭)을
      제목 우선으로 바꾼다.
  (b)(c) Capacitance/Rated Voltage는 본문 근접 매칭을 신뢰하지 않고, 발주정보 표가 EIA
      3자리 코드 방식임을 스스로 설명할 때만 품번 자체를 해독해서 채운다(무조건 덮어씀).
- 반영: `ai/classifier.py` — `_extract_title()`(첫 300자) 추가, `CAPACITOR_SUBCATEGORY_KEYWORDS`
  신설(탄탈럼 3종), `classify_subcategory_generic()`을 제목 우선으로 변경, `classify_subcategory()`
  에 Capacitor 분기 추가, `find_subcategory_evidence()`에도 Capacitor 사전 연결(PDF 주석용).
  **대분류(`classify_category`)는 제목 우선으로 바꿨다가 되돌림** — IS31FL3296-UTLS4-TR("LED
  드라이버" IC)이 제목의 "LED"(Optical Device 가중치3 키워드) 때문에 Integrated Circuit이
  아니라 Optical Device로 잘못 재분류되는 심각한 회귀를 실측 확인함. 이미 검증된 대분류
  판정이 제목의 단어 하나로 뒤집히는 건 위험하다고 판단해, 대분류는 기존 전체 본문 가중치
  합산 방식을 그대로 유지함(소분류만 제목 우선 유지 - 회귀 없음을 프로젝트 내 실제 PDF
  9개 전수 비교로 확인). `ai/reference.py` — `decode_eia_capacitance_code()`,
  `format_capacitance_from_pf()`, `find_capacitance_code()`, `find_rated_voltage_code()` 추가.
  `ai/pdf_parser.py`의 `_apply_reference()`에 Capacitor 전용 블록 추가(성공 시 field_extractor
  값을 덮어쓰고, 남아있던 stale evidence도 같이 지움 — 안 지우면 새 값에 엉뚱한 근거 문구가
  달라붙는 버그가 있어서 발견 즉시 고침). 최종 검증: T322D106K035AT를 실제로 재분석해
  Subcategory=`Solid, Elec, Tant (CSR)`, Capacitance=`10`/Units=`uF`, Rated Voltage=`35`
  전부 사용자 제시값과 일치함을 확인. `vba/Import_User.xlsx`의 `분류기준` 시트도 이 변경에
  맞춰 갱신함(수동 동기화 대상, §1 참고) — Capacitor 전용 사전 섹션 추가, 제목 우선 방식 및
  대분류는 그대로 유지한다는 점을 요약에 반영.

### 2026-09-03 — annotate_pdf() 재실행 시 주석 중복 버그 수정
- 상황: IS31FL3296-UTLS4-TR과 T322D106K035AT를 제외한 나머지 실전 분석 부품 6개 전부에서
  같은 내용의 주석이 2~3벌씩 겹쳐 찍혀 있는 걸 발견함. `annotate_pdf()`가 `doc.saveIncr()`
  (증분 저장 - 항상 "덧붙이기"만 함)를 쓰는데, 새로 찍기 전에 예전 주석을 지우는 로직이
  없었음 — 같은 부품을 다시 분석할 때마다(입력값을 고쳐서 재분석 등) 계속 쌓이는 구조적 버그.
- 결정: `annotate_pdf()`가 새 주석을 찍기 전에, 우리가 예전에 남긴 주석(title="Claude 분석")
  만 먼저 지우도록 해서 몇 번을 다시 불러도 항상 "최신 결과 1벌"만 남게 한다.
- 반영: `datasheet/annotator.py`의 `annotate_pdf()` 맨 앞에 title 매칭 삭제 루프 추가.
  검증: IS31FL3296-UTLS4-TR로 idempotency 확인(연속 재실행해도 4개 유지), 실전 분석된 8개
  부품 전부 재실행 → 중복 0건 확인. 부수 효과로 TC33X-2-102E/BLM21PG121SN1D의 분류 폴더도
  최신 코드 기준으로 다시 정리됨.

### 2026-09-03 — BLM21PG121SN1D (Murata) 첫 인덕터 분석: 페라이트 비드 규칙 신설
- 상황: 이 부품(칩 페라이트 비드)이 대분류부터 Resistor로 잘못 분류돼 있었음 — 본문에
  DC저항(Ω) 스펙이 있어서 약한 근거로 Resistor가 이겼고, "ferrite bead"를 Inductor로 잡아줄
  키워드가 아예 없었음.
- 결정: Category=`Inductor`, Subcategory=`Coil`, Type=`Power Filter`(유효성 목록 4개 허용값
  중)로 확정. PDF 주석은 제목의 "CHIP FERRITE BEAD" 문구 자리에 표시한다. **앞으로 분석되는
  모든 페라이트 비드 부품에 동일하게 적용**(사용자 확정 - 이 부품 한정 규칙이 아님).
- 반영: `ai/classifier.py` — `CATEGORY_KEYWORDS["Inductor"]`에 `ferrite bead`(weight 3) 추가,
  `INDUCTOR_SUBCATEGORY_KEYWORDS` 신설(Coil/Transformer), `classify_subcategory()`에 Inductor
  분기 추가, `find_subcategory_evidence()`에도 연결. `ai/reference.py` —
  `find_ferrite_bead_evidence()`/`FERRITE_BEAD_TYPE` 추가. `ai/pdf_parser.py`의
  `_apply_reference()`에 Inductor/Coil 전용 Type 확정 블록 추가(근거 문구 = 매칭된
  "chip ferrite bead"/"ferrite bead" 원문 그대로, 그래서 PDF 주석이 자동으로 "CHIP FERRITE
  BEAD"에 붙음). 재분석 검증: Category=Inductor, Subcategory=Coil, Type=Power Filter,
  `Inductor/Coil/` 폴더로 자동 이동, 주석 3개(Quality Level/Type/Category+Subcategory) 전부
  정확한 위치에 붙음을 확인. `vba/Import_User.xlsx`의 `분류기준` 시트도 갱신함(Inductor 전용
  사전 섹션 추가).

### 2026-09-03 — DSC8123CI5 (Micrel) 첫 오실레이터 분석: 대분류부터 예외 규칙 신설
- 상황: 이 부품(필드-프로그래머블 LVDS 오실레이터)이 Resistor로 잘못 분류돼 있었음 — 본문에
  Pull-Up Resistor/Ω 스펙이 있어서 weight3 "resistor" 키워드가 이겨버렸고, "oscillator"는
  이미 Miscellaneous 키워드에 있었지만(weight2) 대분류가 전체 본문 가중치 합산 방식이라
  졌음. 게다가 이 부품은 필드에서 사용자가 직접 주파수를 프로그래밍하는 방식이라 품번에도
  본문에도 "이 부품의" 고정 주파수가 없음 — Frequency 필드가 본문의 "Frequency f0 ... 10
  460 MHz"(시리즈 전체 범위의 Min)를 잘못 주움.
- 결정: (a) 제목에 "Oscillator"가 있으면 대분류=Miscellaneous/소분류=Quartz Crystal로 바로
  확정한다(대분류 단계에서도 제목을 보는 유일한 예외 - IS31FL3296 회귀 이후 대분류는 전체
  본문 방식을 유지하기로 했었지만, "oscillator"는 오탐 위험이 낮아 예외로 둠). (b) Frequency는
  위상잡음 스펙 조건에 병기된 주파수(데이터시트 안에서 유일하게 구체적인 값)를 쓴다. (c) PDF
  주석은 제목의 "Oscillator" 문구 자리에 표시한다. **앞으로 분석되는 모든 "제목에 Oscillator가
  있는" 부품에 동일하게 적용**(사용자 확정).
- 반영: `ai/classifier.py` — `find_oscillator_title_evidence()`/`OSCILLATOR_CATEGORY`/
  `OSCILLATOR_SUBCATEGORY` 신설, `classify_category()`/`classify_subcategory()`/
  `find_category_evidence()`/`find_subcategory_evidence()`에 각각 연결. 대소문자 정확한
  "Oscillator"를 먼저 찾고 없으면 "oscillators"(소문자/복수형)도 인정 — 이 데이터시트가 2단
  레이아웃 분리 때문에 진짜 제목의 "Oscillator"가 300자가 아니라 1200자 부근에서야 나타나는
  걸 실측 확인해서, 이 규칙의 탐색 창만 1500자로 넉넉하게 둠(일반 `_extract_title`은 그대로
  300자 유지). `ai/reference.py` — `find_oscillator_frequency()` 추가(`@숫자MHz` 패턴).
  `ai/pdf_parser.py`의 `_apply_reference()`에 Frequency 확정 블록 추가(무조건 덮어씀 - 커패시터
  Capacitance/Rated Voltage와 같은 이유). 재분석 검증: Category=Miscellaneous,
  Subcategory=Quartz Crystal, Frequency=156.25, `Miscellaneous/Quartz Crystal/` 폴더로 자동
  이동, PDF 주석 3개(Category+Subcategory→제목의 "Oscillator", Frequency→"@156.25MHz",
  Quality Level→온도범위) 전부 정확한 위치에 붙음을 확인. `vba/Import_User.xlsx`의 `분류기준`
  시트도 갱신함(1-1번 "특수 규칙" 섹션 추가).

### 2026-09-03 — SMW3100RJT (TE Connectivity) Power Rating: 품번 사이즈 코드로 확정
- 상황: Power Rating이 본문 "Power Rating @ 20°C SM_2: 2.0 Watts" 줄의 라벨 바로 뒤 "@ 20°C"를
  field_extractor가 숫자+단위로 착각해서 "20°C"로 잘못 채워짐 - 실제로는 "Characteristics –
  Electrical" 항목에 SM_2/SM_3/SM_5/SM_7 4가지 사이즈별 값이 나란히 있어서, 라벨 근접 매칭
  방식으로는 애초에 이 부품(SMW3100RJT = 사이즈 3)에 맞는 값을 못 골라냄.
- 결정: 품번의 "SM" 뒤 사이즈 숫자(SMW**3**100RJT → 3)로 "Power Rating @ 20°C SM_3:" 줄을
  정확히 대조해서 3.0 Watts(→ "3")를 채운다. **카테고리/서브카테고리는 그대로 유지**(사용자가
  이 부분은 안 건드림 - Chassis Mount, WW Power (RE, RER) 그대로).
- 반영: `ai/reference.py` — `find_sm_series_power_rating()` 추가(품번 접두사 `SM[W|F]<숫자>`
  파싱 + "Power Rating @ 20°C SM_n: X.0 Watts" 대조). `ai/pdf_parser.py`의 `_apply_reference()`
  에 Resistor 전용 블록 추가(무조건 덮어씀 - field_extractor가 이미 잘못 채웠으므로).
  재분석 검증: Power Rating="3", PDF 주석이 정확히 "Power Rating @ 20°C SM_3:" 표 행에 붙음을
  확인. **앞으로 분석되는 모든 TE SM Series(SMW/SMF) 품번에 동일하게 적용**.

### 2026-09-03 — TC33X-2-102E (Bourns) 확인: 소수점 디코딩 버그 + Power Rating 표 레이아웃 문제
- 상황: 사용자가 이전에 title-우선 소분류 매칭으로 이미 정정된(Chassis Mount, WW Power →
  Trimmer, Var NonWW) 이 부품을 "확인해줘"라고 요청해서 직접 데이터시트를 다시 대조함. 두
  가지 문제를 발견함. (a) 이 PDF는 폰트에 소수점(.) 글리프가 없어서 숫자 사이 소수점이
  유니코드 대체 문자(U+FFFD)로 깨져 나옴 - "0.15 watt"가 "0�15 watt"로 추출돼서, 나중에
  숫자만 뽑으면 "15"(15W, 100배 틀림)가 됨. (b) Power Rating 라벨 줄엔 "(50 VDC max.)"라는
  전압 상한만 있고, 진짜 전력값("0.15 watt")은 온도 조건("70°C") 옆 다음 줄에 있어서
  field_extractor(같은 줄만 봄)가 "50 VDC"를 잘못 주움.
- 결정: (a) 숫자 사이의 대체 문자는 소수점으로 되돌린다(이 PDF 전체에 걸친 문제라 특정
  파라미터 하나가 아니라 텍스트 추출 단계에서 일괄 처리). (b) Power Rating은 항상 W(att)
  단위만 인정하고, 라벨 근처 몇 줄 아래까지 찾는다.
- 반영: `ai/pdf_text.py` — `extract_text()`가 돌려주는 텍스트에 `_fix_undecodable_decimal_points()`
  적용(숫자 사이 U+FFFD → "." 치환, 이 문서에서 5곳 확인). `ai/field_extractor.py` —
  `FIELD_VALUE_PATTERNS`에 `Power Rating`(W/watt/mW 단위만 인정) 추가. `ai/reference.py` —
  `find_power_rating_watts()` 추가(라벨 근처 150자까지 DOTALL로 찾되, 근거 문구는 "숫자
  watt(s)" 부분만 잘라서 씀 - 처음엔 라벨부터 값까지 전체 구간을 근거로 썼다가, 2단 레이아웃
  때문에 순서가 뒤섞인 다른 칸 글자("MOUNTING NOTE" 등)까지 껴서 PDF에서 그 문구를 못 찾는
  문제를 바로 발견해 고침). `ai/pdf_parser.py`의 `_apply_reference()`에 연결(field_extractor가
  못 채웠을 때만 보충). 재분석 검증: Power Rating="0.15", PDF 주석이 정확히 "0.15 watt"
  자리에 붙음을 확인. 나머지 7개 부품 재검증 결과 회귀 없음. **소수점 디코딩 보정은 이
  부품 한정이 아니라 텍스트 추출 전체에 적용되므로, 앞으로 같은 폰트 문제가 있는 다른
  데이터시트에도 자동으로 도움이 됨.**

### 2026-09-04 — BZT52C8V2-7 (Diodes Inc.) 확인: Diode Type/Construction Type 신설 + 각주오탐 수정
- 상황: 사용자가 이 부품을 확인해달라고 요청함. 세 가지를 발견/확정함. (a) Diode Type/
  Construction Type이 계속 공란이었음 - 유효성 목록에 값이 있는데 채우는 규칙이 아예 없었음.
  (b) Operating Power가 "7"로 잘못 채워져 있었음 - 원인 추적 결과 "Power Dissipation (Note 7)
  ... 500 mW"에서 각주 번호 "(Note 7)"의 "7"을 라벨 근처 첫 숫자로 잘못 주움(단위 없는 맨
  숫자였는데 걸러내는 규칙이 없었음). (c) Category/Subcategory 요약이 제목 전체("SURFACE
  MOUNT ZENER DIODE")가 아니라 "DIODE" 한 단어에만 붙어 있었음(SEMICONDUCTOR_SUBCATEGORY_
  KEYWORDS의 낱말 패턴이 온전한 구 패턴보다 먼저 리스트에 있었음).
- 결정: (a) Diode Type은 제목/본문에 "zener"가 있으면 항상 `Voltage Regulator, Ref, Zener`.
  Construction Type은 점접촉/스프링 로디드 명시가 없는 한 항상 `Metallurgically`(오늘날
  실리콘 다이오드 절대다수). (b) Operating Power도 Power Rating처럼 W(att)/mW 단위가 확실한
  후보만 인정 - 각주 번호 같은 단위 없는 맨 숫자를 원천 차단. (c) PDF 주석은 제목 전체
  "SURFACE MOUNT ZENER DIODE"에 표시.
- 반영: `ai/classifier.py` — `SEMICONDUCTOR_SUBCATEGORY_KEYWORDS["Diode"]`에
  `surface mount zener diode`/`zener diode` 온전한 구 패턴을 낱말 패턴들보다 앞에 추가(순서가
  find_subcategory_evidence의 "첫 매칭 우선" 로직에 그대로 영향 줌). `ai/reference.py` —
  `find_zener_diode_type()`/`resolve_diode_construction_type()` 신설.
  `ai/field_extractor.py` — `FIELD_VALUE_PATTERNS`에 `Operating Power`(W/watt/mW 단위만 인정)
  추가(Power Rating과 동일 패턴). `ai/pdf_parser.py`의 `_apply_reference()`에 Diode 전용 블록
  추가. 재분석 검증: Diode Type=`Voltage Regulator, Ref, Zener`, Construction Type=
  `Metallurgically`, Operating Power=공란(주석도 사라짐), PDF 주석이 정확히 "SURFACE MOUNT
  ZENER DIODE" 전체에 붙음을 확인. 나머지 7개 부품 재검증 결과 회귀 없음.

### 2026-09-04 — 2SB1260T100R (ROHM) 재분석: 대분류 오탐 수정 (Semiconductor/Transistor)
- 상황: 사용자가 제목의 "Middle Power Transistor"를 근거로 이 부품이 Semiconductor/Transistor
  여야 한다고 지적함. 실제로 확인해보니 응용 예시("Applications: Motor driver, LED driver")에
  "LED"가 한 번 언급된 것만으로 `\bled\b`(weight 3, Optical Device)가 `\btransistor\b`
  (weight 1, Semiconductor)를 이겨서 Optical Device / Detector, Isolator, Emitter로 잘못
  분류돼 있었음.
- 결정: 제목에 "Transistor"가 있으면 대분류를 바로 Semiconductor로 확정한다(Oscillator와
  같은 예외 패턴). 소분류는 기존 SEMICONDUCTOR_SUBCATEGORY_KEYWORDS의 "PNP" 매칭으로 이미
  Transistor를 정확히 찾고 있어서 별도 규칙 불필요 - 다만 PDF 주석 근거를 "PNP" 한 단어가
  아니라 제목의 "Middle Power Transistor" 전체로 표시해달라는 요청에 맞춰 온전한 구
  패턴(`middle power transistor`/`power transistor`)을 낱말 패턴보다 앞에 추가함(Diode와
  같은 방식).
- 반영: `ai/classifier.py` — `find_transistor_title_evidence()`/`TRANSISTOR_CATEGORY` 신설,
  `classify_category()`에 연결. `SEMICONDUCTOR_SUBCATEGORY_KEYWORDS["Transistor"]`에 온전한
  구 패턴 2개 추가. 재분석 검증: Category=Semiconductor, Subcategory=Transistor,
  `Semiconductor/Transistor/` 폴더로 자동 이동, PDF 주석이 정확히 제목의 "Middle Power
  Transistor" 전체에 붙음을 확인. 나머지 7개 부품 재검증 결과 회귀 없음.

### 2026-09-04 — 2SB1260T100R 추가 확인: Operating Voltage(VCEO)/Application 신설
- 상황: 사용자가 "Rated Voltage는 Vceo값인 80으로" 요청함 - 확인해보니 이 소분류
  (Semiconductor/Transistor)엔 `data/subcat_params.json` 기준 "Rated Voltage"라는 필드
  자체가 없고 "Operating Voltage"만 있음(다른 소분류엔 Rated Voltage가 있는 경우가 많아
  사용자가 일반적인 의미로 부른 것으로 보임). Application도 유효성 목록에 Linear/Switching
  둘뿐인데 채우는 규칙이 없었음.
- 결정: Operating Voltage = VCEO 절댓값(80)을 채운다. Application은 용도 설명(모터/LED
  드라이버 = Switching, 증폭기 = Linear)으로 판단해 채운다 - 이 부품은 "Motor driver, LED
  driver"라 Switching.
- 반영: `ai/reference.py` — `find_transistor_vceo()`(VCEO 표기를 "V ... CEO" 패턴으로 찾되,
  아래첨자 CEO는 lookahead로만 확인하고 근거 문구엔 안 넣음 - 폰트 베이스라인 차이로 값과
  다른 줄에 추출되는 경우가 있어 그대로 넣으면 PDF에서 못 찾아 주석이 통째로 안 붙는 문제를
  구현 중 직접 발견해 고침), `resolve_transistor_application()` 신설. `ai/pdf_parser.py`의
  `_apply_reference()`에 Transistor 전용 블록 추가. 재분석 검증: Operating Voltage=`80`,
  Application=`Switching`, PDF 주석이 각각 제목의 "-80V"와 Features의 "Driver"에 정확히
  붙음을 확인. 나머지 7개 부품 재검증 결과 회귀 없음.

### 2026-09-04 — tools/build_reference.py 버그 수정: PSA 파라미터 열 사이 빈 칸을 끝으로 오인
- 상황: 사용자가 "PSA 입력 파라미터 시트의 P열을 보면 Transistor에 Rated Voltage가 있다"고
  지적함 - 확인해보니 `build_subcat_params()`가 파라미터 열을 훑을 때 "빈 칸을 만나면 그 행은
  끝"으로 처리하고 있었는데, 실제 PSA 시트는 **모든 서브카테고리가 공유하는 고정 파라미터
  슬롯(헤더행에 SD25~SD231, 27개 열) 구조**라서, 어떤 서브카테고리는 그 슬롯들 사이사이가
  비어 있는 게 정상임(그 서브카테고리엔 해당 안 되는 파라미터라 비어 있는 것뿐, "끝"이
  아님). 실측 확인: `Semiconductor/Transistor` 행이 정확히 `Quality Level, Two Sided,
  Application, Operating Voltage, (빈칸), Rated Voltage, (빈칸), Voltage Ratio, ...` 순서라,
  네 번째 파라미터 뒤의 빈 칸에서 멈춰버려 Rated Voltage부터 그 뒤 8개 파라미터(Voltage
  Ratio/Power Rating/Operating Power/Thermal Resistance/Junction-/Temperature Rise/Junction
  Temp Override 등)를 통째로 놓치고 있었음.
- 결정: **PSA 입력 파라미터 시트 자체는 손대지 않는다**(사용자 명시) - 읽는 코드만 고친다.
  헤더행에 실제로 슬롯이 있는 마지막 열까지는 전부 훑되, 빈 칸은 "끝"이 아니라 그냥
  건너뛴다.
- 반영: `tools/build_reference.py`의 `build_subcat_params()` 수정 - "빈 칸에서 멈춤" 로직을
  "헤더행 마지막 슬롯까지 전부 훑고 빈 칸은 건너뜀"으로 교체. `python tools/build_reference.py`
  재실행으로 `data/subcat_params.json`/`data/headers.json` 재생성함(엑셀=원본, JSON=생성물
  원칙 그대로, 8번 참고). 영향 범위 확인: 서브카테고리 97개 항목 수는 그대로(행 손실 없음),
  `Semiconductor/Transistor`만 4개→13개 파라미터로 늘어남(이번에 실제로 문제가 됐던 대상).
  이 세션에서 다뤘던 나머지 7개 부품(Diode/Resistor 2종/Quartz Crystal/IC Linear/Inductor
  Coil/Capacitor CSR)은 원래 파라미터 열이 연속돼 있어서 이 버그의 영향이 없었음(재검증
  결과 회귀 없음). `ai/pdf_parser.py`의 Transistor VCEO 규칙도 이제 실제로 존재하는 "Rated
  Voltage" 필드를 채우도록 수정함(전엔 이 필드가 없는 줄 알고 "Operating Voltage"에
  대신 채웠었음 - VCEO는 절대최대 정격값이라 의미상으로도 Rated Voltage가 맞음). 재분석
  검증: 2SB1260T100R의 Rated Voltage=`80`, PDF 주석이 제목의 "-80V"에 정확히 붙음을 확인.
  **이 버그는 PSA 시트 전체(97개 서브카테고리)에 걸친 읽기 로직 문제였으므로, 앞으로 이
  스크립트를 다시 돌릴 때마다(엑셀 수정 후 등) 다른 서브카테고리에서도 이런 숨은 파라미터가
  추가로 드러날 수 있음 - 정상적인 개선이니 놀라지 말 것.**

### 2026-09-04 — T495C107K010ATE100 (KEMET/YAGEO) 분석: 탄탈럼 CSR/CWR 규칙 단순화
- 상황: 제목이 "Tantalum Surface Mount Capacitors"인 이 부품이 자동으로 `Chip, Elec (CWR)`로
  분류돼 있었음 - 2026-09-03에 만든 규칙이 "tantalum + surface mount/chip/SMD"를 CWR로 봤기
  때문. 사용자가 이 부품은 CSR이 맞다고 확정함 - "surface mount"라는 표현만으로 CWR을
  가정한 게 틀렸던 것으로 확인됨. 또한 Capacitance 해독이 실패해서(품번 코드는 정확히
  찾았는데 "Capacitance Code" 게이트 문구가 이 문서에서는 "Capacitance"와 "Code (pF)"가
  아예 다른 줄로 갈라져서 못 찾음) field_extractor의 잘못된 값("30°C/")이 그대로 남아있었음.
- 결정: 탄탈럼 커패시터는 **wet/non-solid라는 명시가 없는 한 항상 CSR 기본값**으로
  단순화한다(CWR 판별 자체를 뺌 - 실장 방식만으로는 CWR을 확신할 근거가 못 됨이 확인됨).
  Capacitance/Rated Voltage 해독은 T495에서도 정확히 작동해야 한다(Capacitance Code=107 →
  10×10⁷pF=100µF, Rated Voltage 코드=010 → 10V - 둘 다 사용자 예시와 일치 확인).
- 반영: `ai/classifier.py` — `CAPACITOR_SUBCATEGORY_KEYWORDS`(3종 사전) 제거, 대신
  `classify_tantalum_subcategory()`(wet/non-solid 우선 확인 후 기본값 CSR) 신설, `classify_
  subcategory()`/`find_subcategory_evidence()`를 이 함수로 교체. `ai/reference.py`의
  `find_capacitance_code()` 게이트 로직 일반화 - "Capacitance Code"라는 정확한 인접 구 대신,
  "capacitance"라는 단어가 나온 자리마다(여러 번 나올 수 있음) 그 뒤 800자 안에
  "significant"가 있는지 확인하는 방식으로 바꿔서, 표 레이아웃이 문서마다 다르게 깨져도
  안정적으로 게이트를 통과하게 함. 재분석 검증: Category=Capacitor, Subcategory=`Solid,
  Elec, Tant (CSR)`, Capacitance=`100`/Units=`uF`, Rated Voltage=`10` 전부 사용자 제시값과
  일치. PDF 주석이 제목의 "Tantalum"에 정확히 붙음. T322D106K035AT 등 기존 8개 부품
  재검증 결과 회귀 없음. **Series Resistance(ESR)는 이번엔 미반영** - Ordering Information의
  "E100"을 문서에 적힌 규칙대로("last three digits specify ESR in mΩ") 그대로 읽으면
  100 mΩ(=0.1Ω)인데, 사용자는 1Ω(→유효성 목록 `>0.8` 버킷)이라고 확정함 - 근거가 갈려서
  사람 확인 요청함.

### 2026-09-04 — T495C107K010ATE100 Series Resistance(ESR) 규칙 확정
- 상황: 위 항목에서 사람 확인을 요청한 결과, 사용자가 발주정보 표를 직접 대조해서
  "E100 = 100mΩ이 맞다"(제가 읽은 것과 동일)고 확인해줌 - 즉 0.1Ω이 맞고, 유효성 목록
  버킷도 그에 맞게(`0 to 0.1`) 채우면 됨(처음 요청했던 `>0.8`은 1Ω이라는 착오에 근거했던
  것으로, 0.1Ω으로 정정되면서 자동으로 철회됨).
- 결정: 발주정보 품번의 "E"+3자리 코드를 mΩ 값으로 직독(直讀)해서(Capacitance/Rated
  Voltage처럼 유효숫자+배수 공식이 아님), Ω으로 바꾼 뒤 유효성 목록 5단계 버킷에 매핑한다.
- 반영: `ai/reference.py` — `find_tantalum_esr_milliohms()`("ESR" 근처에 "mΩ" 언급이 있을
  때만 시도하는 게이트 + 품번의 "E\d{3}" 코드 추출), `classify_series_resistance()`(Ω 값을
  5단계 버킷으로 내림 매핑, Years in Production과 같은 방식) 신설. `ai/pdf_parser.py`의
  Capacitor 블록에 연결(무조건 덮어씀, 근거 문구 없이 값만 확정 - Capacitance Code와 같은
  이유로 품번 코드 문자열 자체가 원문에 그대로 안 나오는 경우가 많음). 재분석 검증:
  Series Resistance=`0 to 0.1`, `_enforce_valid_values()` 통과 확인(유효성 목록 6개 버킷 중
  정확히 일치). T322D106K035AT 등 기존 8개 부품 재검증 결과 회귀 없음.

### 2026-09-04 — 실전 분석 9개 부품 전체 재검증 + 분류기준 시트 출력지에도 반영
- 상황: 이 세션에서 누적된 모든 수정(탄탈럼 CSR 단순화, Transistor 대분류 특수규칙,
  Series Resistance 등)이 실제 9개 부품 전부에 정상 반영됐는지 다시 확인 요청받음. 또한
  지금까지 `분류기준` 시트를 `vba/Import_User.xlsx`(입력지 양식)에만 반영했었는데,
  `vba/Export_Root.xlsx`(출력지 기본 위치)에는 아직 없었음.
- 반영: 9개 부품(BZT52C8V2-7/2SB1260T100R/SMW3100RJT/TC33X-2-102E/DSC8123CI5/
  IS31FL3296-UTLS4-TR/BLM21PG121SN1D/T322D106K035AT/T495C107K010ATE100) 전체를
  analyze_pdf → move_to_classified → annotate_pdf로 다시 돌림 - 전부 분류/필드값/주석
  개수(중복 없음, 3~4개씩)까지 정상 확인. `분류기준` 시트를 `vba/Export_Root.xlsx`에도
  추가하고, 두 파일 다 최신 규칙(탄탈럼 2종 구분, Transistor 대분류 특수규칙, Diode/
  Transistor 온전한 구 우선 표시)으로 갱신함 - 이제 입력지/출력지 양식 둘 다 시트 5개
  (부품리스트/217F 분석기준/분류기준/유효성 목록/PSA 입력 파라미터) 동일 구성.

### 2026-09-04 — .env(Mouser API 키) 위치를 프로그램 폴더와 분리 (설치파일 배포 버그 수정)
- 상황: 사용자가 "설치파일(installer/)로 배포했을 때만" `.env`(Mouser API 키) 인식 문제가
  생긴다고 확정함. 원인: `installer/set_api_key.ps1`이 `.env`를 프로그램 설치 폴더 안
  (`{app}\.env`, `utils/config.py`의 `APP_DIR/.env`와 같은 자리)에 만들고 있었는데, 프로그램을
  재설치하거나 다른 위치로 옮기면(예: 업그레이드로 새 폴더에 설치) 그 안에 있던 `.env`가
  새 프로그램과 물리적으로 분리돼 버려서, 매번 API 키를 다시 입력해야 하는 구조였음.
- 결정: `.env`를 프로그램 설치 위치와 완전히 분리된, OS 표준 사용자별 설정 폴더
  (`%AppData%\DatasheetDownloader\.env`, 로밍 - 프로그램을 어디에 설치/재설치하든 안 바뀌는
  사람별 고정 자리)로 옮긴다. 구버전 설치(프로그램 폴더 안에 `.env`가 있는 경우)에서 자동으로
  넘어올 수 있게, 예전 자리도 2순위로 계속 확인하고 찾으면 새 자리로 자동 복사한다(사용자가
  키를 다시 입력할 필요 없게).
- 반영: `utils/config.py` — `USER_CONFIG_DIR`/`USER_ENV_PATH`/`LEGACY_ENV_PATH`/
  `ENV_SEARCH_PATHS` 추가, `.env` 탐색을 "1순위 %AppData%, 2순위 프로그램 폴더" 우선순위
  방식으로 교체 + 2순위에서 찾았을 때 1순위로 자동 복사(마이그레이션). `diagnostics/
  self_check.py` — MOUSER_API_KEY 못 찾았을 때 에러 메시지에 실제로 확인한 경로들을 나열하도록
  개선(문제 진단 쉽게). `installer/set_api_key.ps1` — `.env`를 `%AppData%\DatasheetDownloader\`
  에 생성하도록 변경(안내 메시지의 실제 경로도 같이 수정). `installer/launch.ps1` — API 키
  입력 여부 확인도 새 자리 기준으로 변경(구버전 자리도 유효한 걸로 인정). 검증: 기존 개발
  환경(레거시 자리에만 `.env` 있음)에서 실행 → 새 자리로 자동 마이그레이션되고 API 키 정상
  인식 확인. 레거시 `.env`를 임시로 치운 뒤 재실행 → 새 자리(APPDATA)만으로도 API 키 정상
  인식 확인(= 프로그램 폴더가 없어져도 키가 안 사라짐, 실제 버그 시나리오 재현 후 해결 확인).
  `check_connectivity()` 자가진단도 정상 통과 확인.

### 2026-09-04 — "데이터시트 다운로더 Lite" 배포판 신설 (웹 검색 기능 제외)
- 상황: 이 프로그램을 불특정 다수에게 선보이고 싶다고 요청받음. 지금 버전은 Mouser API로 못
  찾으면 자동으로 DuckDuckGo를 검색하는 단계가 있는데, 이 자동 웹 검색이 실제로 이 IP를
  차단당하게 만든 사고가 있었음(이 문서 앞쪽 결정 로그 참고) - 배포판을 여러 사람이 동시에
  돌리면 이 위험이 훨씬 커짐(요청이 여러 IP에서 나가긴 하지만, 각자의 요청 패턴이 봇으로
  보이긴 마찬가지).
- 결정: 배포용으로 **"데이터시트 다운로더 Lite"**라는 별도 제품을 만든다 - 원본과 코드
  베이스는 같지만 `datasheet/downloader.py`에서 웹(DuckDuckGo) 검색 관련 코드를 전부 빼고,
  Mouser 공식 API만 쓴다. 그걸로 못 찾으면 자동으로 다른 곳을 뒤지지 않고 Mouser/DigiKey/구글
  검색 참고 링크 3개만 남겨서 사람이 직접 찾도록 안내한다(원본의 §5-1 "찾지 못함" 케이스와
  동일한 안내 방식, 그 앞의 자동 웹 검색 단계만 없음). 원본 개발 코드베이스(`데이터시트_
  다운로더\클로드 코더`)는 전혀 안 건드리고, 설치파일 빌드용 스테이징 사본에서만 이 교체를
  적용함 - 두 버전이 독립적으로 존재함.
- 반영: `installer/lite/` 폴더 신설(`downloader.py`=웹 검색 로직 제거판, `requirements.txt`=
  `beautifulsoup4` 뺀 버전, `setup.iss`=별도 AppId/설치 폴더(`DatasheetDownloaderLite`)/
  출력 파일명(`데이터시트다운로더Lite_설치.exe`), `README.md`=재빌드 방법). Mouser API 키
  (.env) 저장 위치는 원본과 **똑같이** `%AppData%\DatasheetDownloader\.env`를 씀(의도적 -
  원본을 이미 쓰던 사람이 Lite도 설치하면 키를 또 입력할 필요 없게). 검증: 스테이징 사본에서
  `ui.main_window`/`ai.pdf_parser`/`excel.excel_writer`/`diagnostics.self_check` 등 핵심
  모듈이 전부 정상 임포트됨을 확인(제거된 웹 검색 함수를 참조하는 곳이 없음을 코드 검색으로도
  재확인). Inno Setup으로 컴파일 성공, `00. 배포용\데이터시트다운로더Lite_설치.exe` 생성 완료.

---

## 8. 반드시 지킬 것 (실제로 문제가 발생했던 부분)

- **LibreOffice 기반 재저장 절대 금지** (`soffice --headless` 변환, recalc 스크립트 등). 과거 이걸
  반복 실행하다가 셀 색상(fill)이 통째로 사라진 사고가 있었음. 검증은 openpyxl로 값/서식을
  **읽기만** 하고, 저장(recalc)하지 말 것.
- 엑셀 재생성은 **openpyxl로 직접 작성 → 그대로 저장**만 사용. LibreOffice를 거치는 변환은 금지.
- `217F 분석기준`/`유효성 목록` 시트를 고쳤으면 `tools/build_reference.py`를 반드시 다시 돌릴 것
  — 안 그러면 프로그램이 옛 규칙으로 계속 판정함.
- Thermal Resistance/Quality Level 등 참고표 자동 판정값은 **추정이 아니라 명시값 기반**이 원칙 —
  근거를 못 찾으면 채우지 말고 비워서 사람이 확인하게 할 것 (4번 표 참고).
- `.env`(`MOUSER_API_KEY`)는 절대 커밋 금지.
- `.env` 실제 위치는 `%AppData%\DatasheetDownloader\.env`(프로그램 설치 폴더와 분리된 자리,
  2026-09-04부터 - 아래 결정 로그 참고). 이 경로를 바꾸면 `utils/config.py`/
  `installer/set_api_key.ps1`/`installer/launch.ps1` 셋 다 같이 고칠 것.

---

## 9. 더 보기

- [`소프트웨어_설계문서.md`](소프트웨어_설계문서.md) — 프로그램 전체 구현 구조
- [`00. 배포용/프로그램_정리본.md`](../00.%20배포용/프로그램_정리본.md) — 처음 보는 사람용 요약본
- [`HANDOFF_2026-07-31.md`](HANDOFF_2026-07-31.md) — 지금 방식(PSA)으로 바뀐 날의 변경 내역

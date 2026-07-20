# PTC Windchill 신뢰도 예측 입력지 작업 — Claude Code 인계 문서

이 문서는 Claude(웹/앱)에서 진행하던 작업을 Claude Code로 그대로 이어가기 위한 지침서입니다.
아래 내용을 오해 없이 정확히 따르는 것이 가장 중요합니다. 특히 "반드시 지킬 것" 항목은 예외 없이 지켜주세요.

## 1. 프로젝트 목표

MIL-HDBK-217F Notice 2 표준에 따라 전자부품의 데이터시트를 분석하고, 그 결과를 PTC Windchill Quality
(신뢰도 예측 도구)의 Import 형식에 맞는 엑셀 파일로 정리하는 작업입니다.

산출물: `Windchill_217F_Mapping_Template.xlsx` (3개 시트)
참고 표준 문서: PTC WRR Reference Guide — https://support.ptc.com/help/wrr/r12.0.1.0/en/index.html

## 2. 파일 구조 (3-시트)

### 시트1: 사용가이드라인
- 워크북 사용법 3~4단계, 색상 범례 설명, 11개 대분류 판별 기준(데이터시트 문구 기반), 서브카테고리 중복 시 처리 규칙을 담은 텍스트/표 시트.
- 데이터가 아니라 "설명"만 담긴 시트이므로 코드로 재생성할 때마다 통째로 다시 써도 안전함.

### 시트2: 부품리스트
- 컬럼: `No.` | `품번 (Part Number)` | `제조사` | `데이터시트 링크` | `데이터시트 확보 현황`(드롭다운: 확보완료/미확보/확인중, 조건부서식으로 자동 색칠) | `미확인 항목 (데이터시트로 못 찾은 값)`
- 사용자는 품번만 입력하고, 나머지(제조사/링크/확보현황/미확인항목)는 Claude가 데이터시트 분석 후 채움.

### 시트3: 매핑맵 (핵심, Flat 구조)
- 1행 = 1 서브카테고리(원칙). 154개 서브카테고리 × 124개 파라미터 컬럼(+품번/대분류/소분류 3컬럼 = 총 127컬럼).
- **1행(맨 위)**: 4색 범례 (흰색/회색/보라/분홍 스와치 + 설명 텍스트)
- **2행**: 실제 컬럼 헤더 (127개)
- **3행부터**: 서브카테고리별 데이터 행

## 3. 색상 규칙 (절대 원칙)

| 색상 | HEX | 의미 | 처리 |
|---|---|---|---|
| 흰색 | FFFFFF | 직접 입력 | 데이터시트에서 값을 찾아 채움 |
| 회색 | D9D9D9 | N/A (해당없음) | 그 서브카테고리엔 적용 안 됨. **절대 값 넣지 않음** |
| 보라 | D9C6EC | PTC 자동결정 | Windchill이 내부적으로 계산. **절대 값 넣지 않음**. 대상: `Pi Q Value`, `Case Temp Override`, `Junction Temp Override`, `Frame Temp Override`, `Hot Spot Temperature` |
| 분홍 | F8CBAD | 데이터시트로 알 수 없음 | 별도 확인 전까지 **항상 공란**. 대상: `Years in Production`, `Initial Temp Rise` |

어떤 컬럼이 어떤 서브카테고리에 적용되는지는 `data/subcat_params.json`에 이미 정리되어 있음 (아래 4번 참고).
**하드코딩된 규칙**: 한 서브카테고리에 적용되는 컬럼 중 위 표의 보라/분홍 리스트에 해당하면 그 색, 아니면 흰색. 적용 안 되는 컬럼은 무조건 회색.

## 4. 참고 데이터 파일 (data/ 폴더, 반드시 재사용할 것)

- `data/headers.json`: 매핑맵 127개 컬럼 헤더, 순서 그대로 (품번, Part Category, Part Subcategory + 파라미터 124개)
- `data/subcat_params.json`: 154개 서브카테고리 각각에 대해 `{category, subcategory, params:[적용되는 헤더명 리스트]}` — 이 파일 덕분에 어떤 서브카테고리에 어떤 파라미터 컬럼이 흰색(또는 보라/분홍)이 되어야 하는지 재계산 없이 바로 알 수 있음.
- `data/params124.json`: 124개 파라미터 중 확인된 24개의 이름/타입/단위/설명 참고용. **전체 124개의 완전한 설명은 아님** — 원본 출처(`Unified_Flat_Import_Sheet.xlsx`의 `분석근거` 시트)가 현재 프로젝트 파일함에 없어서 전량 복구하지 못했음. 파라미터 이름 자체(예: Pins, Package Type, Thermal Resistance)는 대부분 직관적으로 이해 가능함. 여기 없는 파라미터를 다뤄야 한다면, `data/headers.json`의 이름과 `data/subcat_params.json`의 적용 서브카테고리를 참고해 이름 자체에서 의미를 유추하거나 사용자에게 확인할 것.
- `data/parts_list_snapshot.json`: 지금까지 부품리스트에 등록된 7개 품번의 현재 상태.
- `data/mapping_map_snapshot.json`: 지금까지 매핑맵에 실제로 채워진 6개 품번의 값 전체 (아래 6번 표와 동일 데이터).

**이 4개 JSON 파일은 이미 여러 세션에 걸쳐 검증된 데이터이므로, WRR 사이트를 재조회하거나 새로 추론하지 말고 그대로 재사용할 것.** (토큰/시간 절약 원칙)

## 5. 대분류/소분류 판별 기준 (데이터시트 읽는 법)

데이터시트의 **General Description / Features 첫 문단**에 나오는 기능 설명 문구로 판별합니다.

| 대분류 | 판별 문구 |
|---|---|
| Integrated Circuit | 여러 트랜지스터/게이트가 한 칩에 집적. 패키지가 DIP/SOIC/TSSOP/QFN 등, 핀 3개 이상 |
| Semiconductor | 단일 접합 소자. "Diode/Rectifier/Transistor/BJT/FET/MOSFET/Thyristor" 직접 등장, 보통 핀 2~3개 |
| Resistor | "Resistor", 저항값(Ω), Power Rating(W) |
| Capacitor | "Capacitor", 정전용량(pF/nF/µF), Rated Voltage(WVDC) |
| Inductor | "Inductor/Coil/Transformer", 인덕턴스(µH/mH) |
| Connection | "Connector/Socket" |
| Switching Device | "Switch/Toggle/Pushbutton" (기계식 스위치) |
| Relay | "Relay", 코일전압 + 접점정격 |
| Optical Device | "LED/Photodiode/Optocoupler/Laser Diode" |
| Rotating Device | "Motor" |
| Miscellaneous | 위 10개 어디에도 안 맞는 특수소자 (Fuse/Crystal/Battery/Filter) |

Integrated Circuit 소분류 판별 예시:
- **Logic, CGA or ASIC**: 출력이 0/1 디지털. "Gate/NAND/NOR/AND/OR/XOR/Decoder/Flip-Flop/Buffer/Inverter". 예) 74LCX02="Quad 2-Input NOR Gate"
- **Linear**: 연속적 아날로그 출력. "Op Amp/Comparator/LDO/Voltage Regulator/Voltage Reference". 예) LT1963="LDO", AD8030="Op Amp", TL391B="Comparator"
- **Memory**: "SRAM/DRAM/Flash/EEPROM/ROM" + 저장용량(bit/byte)
- **Microprocessor**: "CPU/MCU/Processor Core"

## 6. 지금까지 분석 완료된 부품 (재작업 금지, 그대로 유지)

| 품번 | 제조사 | Category/Subcategory | 확보현황 |
|---|---|---|---|
| NL27WZ08USG-Q | onsemi | IC / Logic, CGA or ASIC | 확보완료 |
| MC74HC139ADR2G-Q | onsemi | IC / Logic, CGA or ASIC | 확보완료 |
| AD8030ARZ | Analog Devices | IC / Linear | 확보완료 |
| LT1963EST-3.3#PBF | Analog Devices(Linear Tech) | IC / Linear | 확보완료 |
| TL391BQDBVRQ1 | Texas Instruments | IC / Linear | 확보완료 |
| USBLC6-2P6 | STMicroelectronics | Semiconductor / Diode | 확보완료 |
| TC75W72FU,RF(CT | - | - | **미확보 (품번 오타 추정, 사용자가 스킵 결정 — 재문의 금지, 그대로 대기)** |

값 전체는 `data/mapping_map_snapshot.json` 참고. 데이터시트 링크는 `data/parts_list_snapshot.json` 참고.

## 7. 신규 부품 분석 워크플로우 (Claude Code가 매번 따를 절차)

1. `부품리스트` 시트에 새 품번이 있으면, 제조사 공식 사이트(onsemi/ti.com/analog.com/st.com 등)에서 PDF 데이터시트를 검색.
2. General Description/Features로 대분류/소분류 판별 (5번 기준).
3. `data/subcat_params.json`에서 해당 서브카테고리의 `params` 리스트 확인 → 그 중 보라/분홍 세트(3번 표)를 뺀 나머지가 실제로 채워야 할 흰 칸.
4. **같은 서브카테고리에 이미 다른 부품이 있으면**, 기존 행을 그대로 복제(서식 포함)해서 새 행을 추가. 절대 기존 값을 덮어쓰지 않음. (여러 서브카테고리에 미리 여유 행을 만들어두지 않고, 필요할 때만 그때그때 늘리는 방식 — 사용자가 명시적으로 확정한 방침)
5. 값을 못 찾거나 근사치로만 추정한 항목은 `부품리스트`의 "미확인 항목" 칸에 구체적으로 기록.
6. Quality Level: 데이터시트에 JAN 계열 등급 표기가 없으면(자동차 AEC-Q100 등급 포함) 기본값 `Commercial`로 매핑.
7. **단위 규칙 (중요, 기존 관례 유지)**: `Operating Power` 컬럼은 실제로는 **mW 단위 숫자**를 그대로 저장해왔음 (예: 74LCX02 = 0.055 → 실제 55µW를 "0.055"로 저장). `Temperature Rise`는 항상 **실제 W 단위로 환산 후** `θJA`와 곱해서 계산 (`Temperature Rise[°C] = (OperatingPower_mW / 1000) × ThermalResistance[°C/W]`). 이 관례를 반드시 유지할 것 — 안 그러면 기존 6개 부품 데이터와 단위가 안 맞음.
8. 전력을 정확히 알 수 없는 부품(부하전류 의존 등)은 quiescent 전류 기준 근사치를 내고, 근거를 "미확인 항목"에 남길 것.

## 8. 반드시 지킬 것 (실제로 문제가 발생했던 부분)

- **LibreOffice 기반 재저장(예: soffice --headless 변환, `recalc.py` 류 스크립트)을 이 파일에 절대 실행하지 말 것.** 매핑맵 시트에는 수식이 전혀 없는데(0개), 과거 세션에서 이 스크립트를 반복 실행하다가 **모든 시트의 직접 지정 셀 색상(fill)이 통째로 사라지는 사고**가 있었음. 검증이 필요하면 `openpyxl`로 값/서식을 읽기만 하고, 파일을 다시 저장(recalc)하지 말 것.
- 코드로 파일을 재생성할 때는 **openpyxl로 직접 작성 → 그대로 저장** 방식만 사용. LibreOffice를 거치는 어떤 변환 파이프라인도 금지.
- 같은 서브카테고리에 부품이 여러 개일 때 행 복제를 빠뜨리지 말 것 (과거 세션에서 이 로직 누락으로 USBLC6-2P6 데이터가 통째로 사라진 적 있음 — 서브카테고리→부품리스트 매핑을 코드에서 처리할 때 "부품이 1개뿐인 서브카테고리"도 반드시 포함해서 처리할 것).
- 네트워크: 데이터시트 PDF는 제조사 사이트(onsemi.com, ti.com, analog.com, st.com 등)에서 받아야 하는데, 샌드박스 환경에 따라 아웃바운드 접속이 막혀 있을 수 있음(개발 도메인만 허용되는 경우). 이 경우 사용자에게 다운로드 링크만 제공하고 직접 다운로드는 못 한다고 명확히 알릴 것.
- TC75W72FU,RF(CT는 사용자가 "일단 스킵"하기로 확정한 상태 — 다시 품번을 물어보지 말 것 (사용자가 먼저 정확한 품번을 주기 전까지 대기).

## 9. 요약 체크리스트

- [ ] 새 파일 생성 시 `data/*.json` 재사용 (재추론 금지)
- [ ] 색상 규칙(3번 표) 정확히 적용
- [ ] 서브카테고리 중복 시 행 복제 (1개짜리도 빠짐없이)
- [ ] Operating Power = mW 숫자, Temperature Rise = W로 환산 후 계산
- [ ] recalc/LibreOffice 재저장 금지
- [ ] 이미 완료된 7개 품번 재작업 금지

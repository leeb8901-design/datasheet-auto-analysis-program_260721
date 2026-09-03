#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
annotate_datasheet.py

분석 결과(엑셀 PSA 시트에 채운 값)를 원본 데이터시트 PDF 위에 하이라이트+메모로 표시해서
"클로드분석" PDF를 만드는 스크립트예요. 형식은 사용자가 직접 만들어준 예시
(IS31FL3296-UTLS4-TR_예시안.pdf)를 그대로 따랐어요: 근거가 있는 문구를 노란 하이라이트로
표시하고, 그 하이라이트에 "파라미터 : 값" 형식의 메모(팝업)를 답니다.

지금은 IS31FL3296-UTLS4-TR 전용 스크립트예요(위치 탐색 규칙이 이 데이터시트 구조에 맞춰져
있음). 다른 부품에도 쓰려면 페이지/검색어 매핑을 그 데이터시트에 맞게 새로 짜야 해요 - 아직
범용화는 안 했습니다(2026-08-27, 여러 부품을 더 분석해보면서 공통 패턴이 보이면 그때 일반화).

규칙(2026-08-27 사용자 확정):
- 하이라이트는 **판정의 실제 근거가 된 정확한 문구**에만 붙여요. 대분류/소분류처럼 근거 문구가
  있는 값(예: subcategory=Linear를 결정한 "driver" 키워드가 실제로 매칭된 자리인 "LED DRIVER")도
  Quality Level의 "-40°C ~ +125°C"처럼 정확한 위치에 붙여요 - 막연히 섹션 제목에 붙이지 않아요.
- **찾지 못한(확인 필요) 값은 데이터시트에 아예 표시하지 않아요.** 이런 값은 근거 문구 자체가
  없어서 하이라이트할 정확한 자리가 없고, 엑셀 쪽 노란색 표시로 이미 충분히 드러나 있어요.
"""
import pymupdf as fitz  # PyMuPDF - "import fitz"는 옛 이름이라 매번 경고가 떠서 새 이름으로 불러옴

SRC = "Download_ datasheets/IS31FL3296-UTLS4-TR.pdf"
DST = "IS31FL3296-UTLS4-TR_클로드분석.pdf"
TITLE = "Claude 분석"


def highlight(page, rect, content):
    annot = page.add_highlight_annot(rect)
    annot.set_info(content=content, title=TITLE)
    annot.update()


def main():
    doc = fitz.open(SRC)

    # --- page 1 (index 0): 표지 제목의 "LED DRIVER" - subcategory=Linear를 결정한 실제 근거
    #     문구(classifier.py의 "driver" 키워드가 매칭된 자리, IC_SUBCATEGORY_KEYWORDS["Linear"]).
    p0 = doc[0]
    r = p0.search_for("LED DRIVER")[0]
    highlight(p0, r, "Category : Integrated Circuit\nSubcategory : Linear")

    # 같은 페이지 하단의 개정일(Rev. D, 05/21/2024)에 Years in Production 근거를 답니다.
    r = p0.search_for("Rev. D")[0]
    highlight(p0, r, "Years in Production : >=2.0\n"
                      "(근거: Rev. D, 2024 개정일 기준 근사 - 실제 양산개시일은 이 범위(8p) 밖)")

    # --- page 5 (index 4): ORDERING INFORMATION의 품번 행 - Package Type 근거
    p4 = doc[4]
    r = p4.search_for("IS31FL3296-UTLS4-TR")[0]
    highlight(p4, r, "Package Type : Nonhermetic: DIPs, PGA, SMT\n"
                      "(발주정보 표에서 이 품번 = UTQFN-12 확인 -> 217F 표준분류 자동 매핑)")

    # --- page 6 (index 5): ABSOLUTE MAXIMUM RATINGS - Quality Level 근거(동작온도 범위)
    p5 = doc[5]
    r = p5.search_for("-40°C ~ +125°C")[0]
    highlight(p5, r, "Quality Level : B-1\n(동작온도 -40°C~+125°C 기준 자동판정)")

    # Pins/Thermal Resistance/Junction-/# of Transistors는 자동 도구가 못 찾은 값이라(확인 필요)
    # 데이터시트에는 표시하지 않아요 - 근거 문구가 없어 정확한 위치를 특정할 수 없고, 이미 엑셀
    # PSA 시트에 노란색으로 표시돼 있어요.

    doc.save(DST)
    doc.close()
    print("saved ->", DST)


if __name__ == "__main__":
    main()

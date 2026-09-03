#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
annotate_si53340.py

SI53340-B-GM 전용 "클로드분석" PDF 생성 스크립트예요. tools/annotate_datasheet.py와 같은 방식
(하이라이트 주석 + "파라미터 : 값" 팝업)을 따르되, 이 부품에서 새로 확정된 규칙 하나가 다릅니다:

Package Type/Years in Production처럼 **근거 문구 없이 기본값으로 확정된 값**(사용자 확정,
2026-08-30 - ai/reference.py의 classify_package_type/resolve_years_in_production 기본값 로직)은
Category/Subcategory와 같은 자리(구체적 근거 문구가 없는 값들의 요약 위치)에 함께 적어요.
"확인 필요"라 아예 안 보여주는 것과는 다릅니다 - 이건 도구가 실제로 확정한 값이라 보여줍니다.
"""
import pymupdf as fitz  # PyMuPDF - "import fitz"는 옛 이름이라 매번 경고가 떠서 새 이름으로 불러옴

SRC = "Download_ datasheets/Sl53340-B-GM.pdf"
DST = "클로드 학습자료/SI53340-B-GM_클로드분석.pdf"
TITLE = "Claude 분석"


def highlight(page, rect, content):
    annot = page.add_highlight_annot(rect)
    annot.set_info(content=content, title=TITLE)
    annot.update()


def main():
    doc = fitz.open(SRC)
    p0 = doc[0]

    # 표지 제목의 "Buffers" - subcategory=Logic, CGA or ASIC을 결정한 "buffer" 키워드 매칭 자리.
    # 여기에 근거 문구가 없는 값들(대분류/소분류/기본값 2개)을 함께 묶어요.
    r = p0.search_for("Buffers")[0]
    highlight(p0, r,
        "Category : Integrated Circuit\n"
        "Subcategory : Logic, CGA or ASIC\n"
        "Package Type : Nonhermetic: DIPs, PGA, SMT (기본값)\n"
        "Years in Production : >=2.0 (기본값)")

    # 동작온도 문구 - Quality Level 근거(실제 진짜 근거 문구가 있는 값)
    r = p0.search_for("Temperature range: –40 to +85 °C")[0]
    highlight(p0, r, "Quality Level : B-1\n(동작온도 -40~+85°C 기준 자동판정)")

    doc.save(DST)
    doc.close()
    print("saved ->", DST)


if __name__ == "__main__":
    main()

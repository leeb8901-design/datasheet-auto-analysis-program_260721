# 신뢰도 분석 결과를 원본 데이터시트 PDF 위에 하이라이트+메모로 표시해요(2026-09-03 도입).
#
# 예전 datasheet/annotator.py(2026-07-31에 폐지됨, 값이 있는 자리마다 스티키노트를 넣던 방식)와는
# 다른 새 방식이에요. "클로드분석" 세션에서 특정 부품 하나하나에 대해 손으로 만들어봤던 것
# (tools/annotate_datasheet.py, tools/annotate_si53340.py)을, 프로그램의 "신뢰도 분석" 버튼을
# 누르면 어떤 부품이든 자동으로 똑같이 해주도록 일반화한 버전이에요.
#
# 그 세션에서 확정된 규칙을 그대로 따라요:
# - 근거 문구가 있는 값(ai.pdf_parser.analyze_pdf가 돌려주는 "evidence")만 그 문구가 실제로
#   있는 자리에 하이라이트 + "파라미터 : 값" 메모를 붙여요.
# - 근거 문구 없이 확정된 값(대분류/소분류처럼 특정 문구가 아니라 여러 단서로 판단한 것, 또는
#   물리 패키지를 못 찾아 기본값으로 떨어진 Package Type 등)은 "확인 필요"라서 안 보여주는 것과
#   다르게, 대분류/소분류와 한데 묶어 요약 하나로 표시해요.
# - 값 자체를 못 찾은(공란) 항목은 PDF에 아예 표시하지 않아요 - 엑셀(PSA 시트) 쪽 노란색 표시로
#   이미 드러나 있어요.
# - 별도 파일을 안 만들고, 지금 갖고 있는 그 PDF 파일에 바로 저장해요(사용자가 보고 있는 파일에
#   바로 나타나야 하니까).

from pathlib import Path

import pymupdf as fitz  # PyMuPDF - "import fitz"는 옛 이름이라 매번 경고가 떠서 새 이름으로 불러옴

from utils.logger import logger

_MAX_SEARCH_PAGES = 15  # 근거 문구를 찾아볼 최대 페이지 수(전체를 다 뒤지면 느려서 적당히 제한).
_ANNOTATION_TITLE = "Claude 분석"


def _clean_search_text(text: str) -> str:
    # PDF 텍스트 추출 과정에서 생긴 줄바꿈/중복 공백을 정리해요 - PyMuPDF의 search_for는 페이지에
    # 실제로 렌더링된 글자 위치를 찾는 거라, 우리가 2단 레이아웃을 합치며 넣은 줄바꿈이 그대로
    # 있으면 못 찾아요(ai/pdf_text.py 참고).
    return " ".join(text.split())


def _find_first(doc, text: str, max_pages: int = _MAX_SEARCH_PAGES):
    """여러 페이지에 걸쳐 문구를 찾아, 처음 찾은 (페이지, 사각형)을 돌려줘요. 못 찾으면 None."""
    cleaned = _clean_search_text(text)
    if not cleaned:
        return None
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        rects = page.search_for(cleaned)
        if rects:
            return page, rects[0]
        # 문구가 길면(예: 온도범위처럼 "-40°C to +125°C" 전체) 페이지 레이아웃 차이로 통짜
        # 매칭이 안 될 수 있어요 - 앞부분 일부만으로 한 번 더 시도해요.
        if len(cleaned) > 40:
            rects = page.search_for(cleaned[:40])
            if rects:
                return page, rects[0]
    return None


def _highlight(page, rect, content: str):
    annot = page.add_highlight_annot(rect)
    annot.set_info(content=content, title=_ANNOTATION_TITLE)
    annot.update()


def annotate_pdf(
    pdf_path: Path,
    category: str | None,
    subcategory: str | None,
    fields: dict[str, str | None],
    evidence: dict[str, str],
) -> bool:
    """분석 결과(analyze_pdf의 category/subcategory/fields/evidence)를 pdf_path의 PDF 위에
    하이라이트로 표시하고, 같은 파일에 그대로 덮어써요.

    성공적으로 하나 이상 표시했으면 True, 표시할 게 없거나(값이 하나도 없음 등) 파일을 못 열었거나
    저장에 실패하면 False를 돌려줘요 - 호출하는 쪽(ui/main_window.py)은 이 결과를 치명적 오류로
    다루면 안 돼요. 주석은 보너스 기능이라, 실패해도 신뢰도 분석 결과 자체(엑셀에 들어갈 값)는
    이 함수와 상관없이 이미 확정돼 있어요."""
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.log(f"  [주석] PDF를 열지 못해 건너뜁니다: {e}")
        return False

    try:
        # 같은 부품을 다시 분석하면(입력값을 고쳐서 재분석 등) 이 함수가 또 호출되는데,
        # doc.saveIncr()는 항상 "덧붙이기"만 해서 예전 주석을 알아서 지워주지 않아요 - 그래서
        # 아무 조치 없이 두 번 돌리면 같은 하이라이트가 겹겹이 쌓임(실제 사고, 2026-09-03:
        # IS31FL3296-UTLS4-TR이 같은 내용으로 2벌씩 찍혀 있던 걸 발견함). 그래서 새로 찍기 전에
        # 우리가 예전에 남긴 주석(title="Claude 분석")만 먼저 지워서 이 함수가 몇 번을 다시
        # 불려도 항상 "최신 결과 1벌"만 남도록 함(다른 도구/사람이 남긴 주석은 title이 달라서
        # 안 건드림).
        for page in doc:
            for annot in list(page.annots()):
                if annot.info.get("title") == _ANNOTATION_TITLE:
                    page.delete_annot(annot)

        annotated = False

        # "Units"는 따로 근거 문구가 없는(숫자값 옆 글자일 뿐인) 필드라 늘 ②(요약)로 빠지는데,
        # 짝이 되는 값 필드(Capacitance)가 ①에서 근거 문구를 찾으면 그 하이라이트 메모에
        # 같이 적어요(사용자 확정, 2026-09-03 - "Units는 Capacitance 주석에 작성") - Category/
        # Subcategory 요약과 뒤섞이지 않고 그 값 바로 옆에 붙어야 더 읽기 좋으니까.
        _UNIT_COMPANIONS = {"Capacitance": "Units"}
        folded_into_companion = set()

        # ① 근거 문구가 있는 필드 - 각각 그 문구 자리에 하이라이트.
        for field, value in fields.items():
            if not value or field not in evidence:
                continue
            found = _find_first(doc, evidence[field])
            if not found:
                continue
            content = f"{field} : {value}"
            companion = _UNIT_COMPANIONS.get(field)
            if companion and fields.get(companion) and companion not in evidence:
                content += f"\n{companion} : {fields[companion]}"
                folded_into_companion.add(companion)
            page, rect = found
            _highlight(page, rect, content)
            annotated = True

        # ② 근거 문구 없이 확정된 값(대분류/소분류 + 기본값으로 떨어진 나머지) - 한데 묶어 요약.
        summary_lines = []
        if category:
            summary_lines.append(f"Category : {category}")
        if subcategory:
            summary_lines.append(f"Subcategory : {subcategory}")
        for field, value in fields.items():
            if value and field not in evidence and field not in folded_into_companion:
                summary_lines.append(f"{field} : {value}")

        if summary_lines:
            anchor = None
            # 소분류 근거를 먼저 써요 - IC의 "driver"처럼 소분류를 결정한 키워드가 훨씬 구체적/
            # 결정적인 반면, 대분류 근거(예: "MCU")는 본문 어딘가에 우연히 한 번 언급된 약한
            # 단서일 수 있어요(실제로 IS31FL3296-UTLS4-TR에서, Category 근거가 애플리케이션
            # 설명 중 스쳐 지나가는 "MCU"에 걸려 표지의 "LED DRIVER"(Subcategory=Linear를 실제로
            # 결정한 문구, tools/annotate_datasheet.py에서 사람이 직접 확인/승인한 자리)보다
            # 훨씬 덜 의미있는 위치에 요약이 붙는 문제를 확인해서 순서를 바꿈, 2026-09-03).
            if "__subcategory__" in evidence:
                anchor = _find_first(doc, evidence["__subcategory__"])
            if anchor is None and "__category__" in evidence:
                anchor = _find_first(doc, evidence["__category__"])
            if anchor is None:
                # 근거 문구를 아예 못 찾았을 때의 최후 수단: 1페이지 맨 위 고정 자리.
                anchor = (doc[0], fitz.Rect(36, 36, 220, 54))
            page, rect = anchor
            _highlight(page, rect, "\n".join(summary_lines))
            annotated = True

        if not annotated:
            return False

        doc.saveIncr()  # 새 파일을 만들지 않고, 지금 이 파일에 증분 저장해요(주석 추가만 있어 안전).
        return True
    except Exception as e:
        logger.log(f"  [주석] PDF에 표시하는 중 오류가 발생해 건너뜁니다: {e}")
        return False
    finally:
        doc.close()

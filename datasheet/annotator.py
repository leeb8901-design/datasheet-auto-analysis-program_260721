# 신뢰도 분석 결과를 원본 데이터시트 PDF 위에 하이라이트+메모로 표시해요.
#
# 2026-09-15: pymupdf(PyMuPDF/fitz)를 뺐어요 - AGPL-3.0/Artifex 상용 라이선스 듀얼이라 무료
# 배포와 라이선스 조건이 충돌할 수 있어서(보안점검_2026-09-11.md 참고), 문구 위치를 찾는 건
# pdfplumber(이미 ai/pdf_text.py가 쓰는 라이브러리, pdfminer.six 기반)로, 실제로 PDF에
# 하이라이트 주석을 써넣는 건 pypdf(BSD-3-Clause)로 나눠서 대체했어요. 동작(찾는 방식/이어붙는
# 규칙/멱등 처리)은 예전과 똑같이 유지하려고 했어요.
#
# 좌표계 주의: pdfplumber는 화면처럼 "왼쪽 위가 원점, 아래로 갈수록 y가 커지는" 좌표를 써요
# (page.search()가 돌려주는 top/bottom이 그 예). 반면 PDF 파일 자체(그리고 pypdf가 주석 위치를
# 적어넣는 /Rect, /QuadPoints)는 "왼쪽 아래가 원점, 위로 갈수록 y가 커지는" 진짜 PDF 좌표계를
# 써요. 그래서 pdfplumber가 찾은 위치를 pypdf에 넘기기 전에 반드시 위아래를 뒤집어야 해요
# (_to_pdf_rect 참고) - 이걸 안 하면 하이라이트가 페이지 반대쪽에 붙는 사고가 나요.
#
# - 근거 문구가 있는 값(ai.pdf_parser.analyze_pdf가 돌려주는 "evidence")만 그 문구가 실제로
#   있는 자리에 하이라이트 + "파라미터 : 값" 메모를 붙여요.
# - 근거 문구 없이 확정된 값(대분류/소분류처럼 특정 문구가 아니라 여러 단서로 판단한 것, 또는
#   물리 패키지를 못 찾아 기본값으로 떨어진 Package Type 등)은 "확인 필요"라서 안 보여주는 것과
#   다르게, 대분류/소분류와 한데 묶어 요약 하나로 표시해요.
# - 값 자체를 못 찾은(공란) 항목은 PDF에 아예 표시하지 않아요 - 엑셀(PSA 시트) 쪽 노란색 표시로
#   이미 드러나 있어요.
# - 별도 파일을 안 만들고, 지금 갖고 있는 그 PDF 파일에 바로 저장해요(사용자가 보고 있는 파일에
#   바로 나타나야 하니까).

import io
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight
from pypdf.generic import ArrayObject, FloatObject, NameObject, TextStringObject

from utils.logger import logger

_MAX_SEARCH_PAGES = 15  # 근거 문구를 찾아볼 최대 페이지 수(전체를 다 뒤지면 느려서 적당히 제한).
_ANNOTATION_TITLE = "Claude 분석"
_HIGHLIGHT_COLOR = "ffff00"  # 노란 형광펜 - fitz의 add_highlight_annot 기본색과 동일.


def _clean_search_text(text: str) -> str:
    # PDF 텍스트 추출 과정에서 생긴 줄바꿈/중복 공백을 정리해요 - pdfplumber의 search()는 페이지에
    # 실제로 렌더링된 글자 위치를 찾는 거라, 우리가 2단 레이아웃을 합치며 넣은 줄바꿈이 그대로
    # 있으면 못 찾아요(ai/pdf_text.py 참고).
    return " ".join(text.split())


def _find_first(pdf: "pdfplumber.PDF", text: str, max_pages: int = _MAX_SEARCH_PAGES):
    """여러 페이지에 걸쳐 문구를 찾아, 처음 찾은 (페이지 인덱스, bbox) 튜플을 돌려줘요.
    bbox는 pdfplumber 좌표(x0, top, x1, bottom) 그대로예요. 못 찾으면 None."""
    cleaned = _clean_search_text(text)
    if not cleaned:
        return None
    for i, page in enumerate(pdf.pages):
        if i >= max_pages:
            break
        # regex=False: 근거 문구에 "(", "." 같은 정규식 특수문자가 그대로 들어있는 경우가
        # 많아서(예: "Power Rating (50 VDC max.)") 있는 그대로(리터럴)만 찾아요 - fitz의
        # search_for()도 리터럴 부분 문자열 검색이라 그 동작을 그대로 맞춘 거예요.
        matches = page.search(cleaned, regex=False, case=True)
        if matches:
            m = matches[0]
            return i, (m["x0"], m["top"], m["x1"], m["bottom"])
        # 문구가 길면(예: 온도범위처럼 "-40°C to +125°C" 전체) 페이지 레이아웃 차이로 통짜
        # 매칭이 안 될 수 있어요 - 앞부분 일부만으로 한 번 더 시도해요.
        if len(cleaned) > 40:
            matches = page.search(cleaned[:40], regex=False, case=True)
            if matches:
                m = matches[0]
                return i, (m["x0"], m["top"], m["x1"], m["bottom"])
    return None


def _to_pdf_rect(bbox: tuple[float, float, float, float], page_height: float) -> tuple[float, float, float, float]:
    """pdfplumber bbox(x0, top, x1, bottom - 왼쪽위 원점, y 아래로 증가)를 PDF 네이티브
    좌표(x0, y0, x1, y1 - 왼쪽아래 원점, y 위로 증가)로 뒤집어요. 페이지 높이만 알면 되는
    단순한 상하 반전이에요."""
    x0, top, x1, bottom = bbox
    return x0, page_height - bottom, x1, page_height - top


def _quad_points(rect: tuple[float, float, float, float]) -> ArrayObject:
    # PDF 텍스트 마크업 주석의 QuadPoints는 "왼쪽위 -> 오른쪽위 -> 왼쪽아래 -> 오른쪽아래"
    # 순서로 4개 점(x,y)을 적어요(pypdf 공식 예제와 동일한 순서) - 이 순서가 틀리면 하이라이트가
    # 비뚤어지거나 안 보여요.
    x0, y0, x1, y1 = rect
    return ArrayObject([FloatObject(n) for n in (x0, y1, x1, y1, x0, y0, x1, y0)])


def _highlight(writer: PdfWriter, page_index: int, rect: tuple[float, float, float, float], content: str):
    annot = Highlight(
        rect=rect,
        quad_points=_quad_points(rect),
        highlight_color=_HIGHLIGHT_COLOR,
        title_bar=_ANNOTATION_TITLE,
    )
    annot[NameObject("/Contents")] = TextStringObject(content)
    writer.add_annotation(page_number=page_index, annotation=annot)


def _remove_previous_annotations(writer: PdfWriter):
    # 같은 부품을 다시 분석하면(입력값을 고쳐서 재분석 등) 이 함수가 또 호출되는데, 예전 주석을
    # 알아서 지워주지 않으면 같은 하이라이트가 겹겹이 쌓여요(실제 사고, 2026-09-03 참고). 그래서
    # 새로 찍기 전에 우리가 예전에 남긴 주석(title="Claude 분석")만 먼저 지워서 이 함수가 몇 번을
    # 다시 불려도 항상 "최신 결과 1벌"만 남도록 해요(다른 도구/사람이 남긴 주석은 title이 달라서
    # 안 건드림) - PdfWriter.remove_annotations()는 종류(Subtype) 기준으로만 지워서 이 구분을 못 해
    # 직접 골라서 지워요.
    for page in writer.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        kept = [a for a in annots if a.get_object().get("/T") != _ANNOTATION_TITLE]
        if len(kept) != len(annots):
            page[NameObject("/Annots")] = ArrayObject(kept)


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
        data = Path(pdf_path).read_bytes()
    except OSError as e:
        logger.log(f"  [주석] PDF를 열지 못해 건너뜁니다: {e}")
        return False

    try:
        with pdfplumber.open(io.BytesIO(data)) as plumber_pdf:
            reader = PdfReader(io.BytesIO(data))
            writer = PdfWriter()
            writer.append(reader)

            _remove_previous_annotations(writer)

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
                found = _find_first(plumber_pdf, evidence[field])
                if not found:
                    continue
                page_index, bbox = found
                content = f"{field} : {value}"
                companion = _UNIT_COMPANIONS.get(field)
                if companion and fields.get(companion) and companion not in evidence:
                    content += f"\n{companion} : {fields[companion]}"
                    folded_into_companion.add(companion)
                page_height = plumber_pdf.pages[page_index].height
                rect = _to_pdf_rect(bbox, page_height)
                _highlight(writer, page_index, rect, content)
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
                # 단서일 수 있어요.
                if "__subcategory__" in evidence:
                    anchor = _find_first(plumber_pdf, evidence["__subcategory__"])
                if anchor is None and "__category__" in evidence:
                    anchor = _find_first(plumber_pdf, evidence["__category__"])
                if anchor is None:
                    # 근거 문구를 아예 못 찾았을 때의 최후 수단: 1페이지 맨 위 고정 자리
                    # (pdfplumber 좌표로 top=36~54, 왼쪽 x=36~220 - fitz.Rect(36,36,220,54)와 같은 자리).
                    page_index, bbox = 0, (36, 36, 220, 54)
                else:
                    page_index, bbox = anchor
                page_height = plumber_pdf.pages[page_index].height
                rect = _to_pdf_rect(bbox, page_height)
                _highlight(writer, page_index, rect, "\n".join(summary_lines))
                annotated = True

            if not annotated:
                return False

            tmp_path = Path(pdf_path).with_suffix(Path(pdf_path).suffix + ".tmp")
            with open(tmp_path, "wb") as f:
                writer.write(f)
            tmp_path.replace(pdf_path)  # 같은 드라이브 안 원자적 교체 - 새 파일을 따로 안 남겨요.
            return True
    except Exception as e:
        logger.log(f"  [주석] PDF에 표시하는 중 오류가 발생해 건너뜁니다: {e}")
        return False

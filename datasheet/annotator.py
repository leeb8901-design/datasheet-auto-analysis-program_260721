# 데이터시트 PDF에 분석된 파라미터 값을 스티키노트(주석)로 삽입하는 파일이에요.
# 값이 실제로 등장하는 위치를 찾아 그 자리에 주석을 달아요. 위치를 못 찾으면(스캔 이미지 PDF라 텍스트가
# 없거나, 추출값의 표기 방식이 원문과 달라 문자열이 정확히 일치하지 않는 경우 등) 1페이지 요약 주석
# 하나로 대체해요(설계서 5번 항목). 원본 PDF는 절대 건드리지 않고, 항상 새 경로에 저장해요.

from pathlib import Path

import fitz  # PyMuPDF


def _annotation_text(field_name: str, value: str, confirmed: bool) -> str:
    tag = "확인됨" if confirmed else "자동추출(확인필요)"
    return f"{field_name} = {value}  [{tag}]"


def annotate_pdf(
    pdf_path: Path,
    field_values: dict[str, str | None],
    confirmed_fields: set[str],
    out_path: Path,
) -> Path:
    """field_values에 값이 있는 항목만 주석으로 남겨요. 값이 없는(None) 항목은 건드리지 않아요
    (이미 엑셀의 '미확인 항목' 칸에 남으니, PDF에 빈 주석을 달 필요는 없어요).

    분류/추출 자체가 실패해서 field_values에 값이 하나도 없는 경우에도, 다운로드된 부품은
    출력물에서 항상 확인할 수 있어야 하므로 "분석 결과 없음" 요약 주석을 하나 남겨요."""
    doc = fitz.open(pdf_path)
    try:
        placed_any = False
        unplaced: list[str] = []
        for field_name, value in field_values.items():
            if not value:
                continue
            text = _annotation_text(field_name, value, field_name in confirmed_fields)
            placed = False
            for page in doc:
                hits = page.search_for(value)
                if hits:
                    page.add_text_annot(hits[0].tl, text)
                    placed = True
                    placed_any = True
                    break
            if not placed:
                unplaced.append(text)

        if not placed_any and not unplaced:
            doc[0].add_text_annot(
                fitz.Point(20, 20),
                "자동 분석 결과가 없습니다 (분류 실패 또는 추출값 없음). 데이터시트를 직접 확인해주세요.",
            )
        elif unplaced:
            summary = "자동 추출된 값 중 원문에서 위치를 찾지 못한 항목:\n" + "\n".join(unplaced)
            doc[0].add_text_annot(fitz.Point(20, 20), summary)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(out_path)
    finally:
        doc.close()
    return out_path

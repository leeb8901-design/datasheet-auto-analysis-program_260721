# 데이터시트 PDF에서 글자를 뽑아내는 파일이에요. 이후 분류/추출 단계는 이 텍스트를 보고 판단해요.

from pathlib import Path

import pdfplumber


def extract_text(pdf_path: Path, max_pages: int = 4) -> str:
    """PDF의 앞쪽 몇 페이지에서 텍스트를 뽑아온다.

    대분류/소분류 판별에 쓰는 General Description/Features는 보통 1페이지에 있고,
    전기적 특성표(Electrical Characteristics)도 대개 앞쪽 몇 페이지 안에 있어서,
    전체 문서를 다 읽지 않고 앞부분만 봐도 충분한 경우가 많다. 너무 큰 PDF를
    통째로 읽으면 느려지므로 기본 4페이지로 제한한다.
    """
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            page_text = page.extract_text() or ""
            texts.append(page_text)
    return "\n".join(texts)

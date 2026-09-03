# 데이터시트 PDF에서 글자를 뽑아내는 파일이에요. 이후 분류/추출 단계는 이 텍스트를 보고 판단해요.

import re
from pathlib import Path

import pdfplumber

# 대분류/소분류 판별에 쓰는 General Description/Features뿐 아니라, Ordering Information
# (발주번호↔패키지 매칭)과 Absolute Maximum Ratings(동작온도/열저항)까지 보통 이 안에 들어있다.
# 너무 큰 PDF를 통째로 읽으면 느려지므로 기본 8페이지로 제한한다.
DEFAULT_MAX_PAGES = 8

# 페이지 중앙을 가로지르는 단어가 이 비율보다 적으면 "2단(컬럼) 레이아웃"으로 판단한다.
_TWO_COLUMN_CROSSING_RATIO = 0.02


def extract_text(pdf_path: Path, max_pages: int = DEFAULT_MAX_PAGES) -> str:
    """PDF의 앞쪽 몇 페이지에서 텍스트를 뽑아온다.

    데이터시트는 대부분 좌/우 2단(컬럼) 레이아웃이다(예: 왼쪽 General Description,
    오른쪽 Features). pdfplumber의 기본 extract_text()는 글자를 위→아래 순서로만
    정렬해서 뽑기 때문에, 같은 높이에 있는 왼쪽 문단과 오른쪽 문단의 줄이 서로 섞여버려
    "-40°C to +125°C" 같은 문구 중간에 다른 컬럼의 글자가 끼어드는 문제가 실제로 있었다
    (온도 범위 파싱이 통째로 실패하는 원인이었음). 그래서 페이지마다 2단 레이아웃인지
    먼저 판단하고, 맞으면 왼쪽 절반과 오른쪽 절반을 각각 잘라서(crop) 위→아래로 따로 뽑은
    뒤 왼쪽 전체 다음에 오른쪽 전체를 이어붙인다 - 사람이 읽는 순서와 같아진다.
    """
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            texts.append(_extract_page_text(page))
    return _fix_undecodable_decimal_points("\n".join(texts))


# 일부 PDF는 소수점(.) 글리프가 폰트 CMap에 없어서, 숫자 사이의 소수점만 콕 집어 디코딩에
# 실패하고 유니코드 대체 문자(U+FFFD)로 깨져 나와요(실제 확인: Bourns TC33X-2-102E - "0.15
# watt"가 "0�15 watt"로, "1.55"가 "1�55"로 등등, 이 문서의 소수점 전부가 이렇게 깨져 있었음).
# "숫자 사이"라는 문맥이 확실할 때만 마침표로 되돌려요(다른 용도로 쓰인 대체 문자까지
# 건드리지 않도록) - Power Rating 등 숫자 필드 추출이 소수점이 통째로 없어져서 자릿수가
# 틀리는 사고(0.15W를 15W로 잘못 읽는 등)를 막기 위해서.
_UNDECODABLE_DECIMAL_RE = re.compile(r"(?<=\d)�(?=\d)")


def _fix_undecodable_decimal_points(text: str) -> str:
    return _UNDECODABLE_DECIMAL_RE.sub(".", text)


def _extract_page_text(page) -> str:
    mid = page.width / 2
    if not _looks_two_column(page, mid):
        return page.extract_text() or ""

    left = page.crop((0, 0, mid, page.height)).extract_text() or ""
    right = page.crop((mid, 0, page.width, page.height)).extract_text() or ""
    return left + "\n" + right


def _looks_two_column(page, mid: float) -> bool:
    # 표나 다이어그램은 중앙을 가로지르는 단어(칸)가 많아서 반으로 자르면 내용이 깨진다.
    # 본문 단어 대부분이 중앙선을 넘지 않을 때만(=글이 좌/우로 뚜렷이 나뉠 때만) 2단으로 봐요.
    words = page.extract_words()
    if len(words) < 20:
        return False
    crossing = sum(1 for w in words if w["x0"] < mid < w["x1"])
    return crossing <= max(2, len(words) * _TWO_COLUMN_CROSSING_RATIO)

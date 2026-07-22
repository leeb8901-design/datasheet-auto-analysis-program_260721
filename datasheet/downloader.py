# 데이터시트를 실제로 찾아서 다운로드하는 파일이에요.
# 순서: ① 이미 있으면 스킵 -> ② Mouser 검색+다운로드 -> ③ 실패하면 웹(DuckDuckGo) 검색+다운로드 -> ④ 그래도 실패하면 포기.

import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from datasheet.search import MouserClient
from utils.config import DOWNLOAD_DIR as _DEFAULT_DOWNLOAD_DIR
from utils.config import (
    STATUS_FAILED,
    STATUS_SKIPPED_EXISTING,
    STATUS_SUCCESS_MOUSER,
    STATUS_SUCCESS_WEB,
)
from utils.logger import logger

# 저장 폴더는 GUI에서 바꿀 수 있어서, 고정 상수가 아니라 바꿀 수 있는 변수로 둬요.
_download_dir = _DEFAULT_DOWNLOAD_DIR


def set_download_dir(path):
    # GUI의 "저장 폴더 선택" 버튼이 이 함수를 불러서 저장 위치를 바꿔요.
    global _download_dir
    _download_dir = Path(path)


def get_download_dir() -> Path:
    return _download_dir

# ---- 검색/다운로드 요청에 공통으로 쓰는 설정 ----
HEADERS = {"Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
MIN_DELAY_SECONDS = 1.5  # 검색 사이 최소 대기시간 (너무 빠르면 로봇으로 의심받아요)
MAX_DELAY_SECONDS = 3.5
RETRY_DELAY_SECONDS = (6.0, 10.0)  # 캡차에 걸렸을 때 재시도 전 대기시간
DOWNLOAD_RETRY_DELAY = 2.0  # 다운로드 실패 시 재시도 전 대기시간

# 같은 세션(브라우저 창 하나)을 계속 재사용해서 더 자연스러운 방문자처럼 보이게 해요.
_session = curl_requests.Session(impersonate="chrome")

# 유통사(부품 파는 가게) 사이트 — 데이터시트 출처로는 원하지 않아요.
DISTRIBUTOR_DOMAINS = [
    "mouser.com", "digikey.com", "lcsc.com", "alibaba.com", "aliexpress.com",
    "octopart.com", "findchips.com", "arrow.com", "avnet.com", "rs-online.com",
    "element14.com", "amazon.com", "ebay.com", "tme.com", "newark.com",
]

# 회사 이름에 흔히 붙는 단어들 — 도메인 매칭 힌트로는 안 써요.
GENERIC_MFR_WORDS = {
    "devices", "instruments", "electronics", "electronic", "semiconductor", "semiconductors",
    "technology", "technologies", "corporation", "corp", "inc", "co", "ltd", "group",
    "microelectronics", "systems", "international", "company",
}


@dataclass
class DownloadResult:
    # 부품 하나를 처리한 결과를 담는 상자예요.
    status: str  # utils.config의 STATUS_* 값 중 하나
    filename: str | None  # 저장된 파일 이름 (성공/이미있음일 때)
    error: str | None  # 실패 사유 (실패했을 때)
    manufacturer: str | None  # 확인된 제조사 이름
    reference_url: str | None = None  # 자동 다운로드는 실패했지만 참고할 만한 링크


def sanitize_filename(name: str) -> str:
    keep = "-_.() "
    cleaned = "".join(c for c in (name or "") if c.isalnum() or c in keep).strip()
    return cleaned or "unknown"


def build_dest_path(part_number: str, manufacturer: str | None) -> Path:
    # 제조사별 폴더 아래에 "품번.pdf"로 저장할 경로를 만들어요.
    folder = _download_dir / sanitize_filename(manufacturer or "미상")
    return folder / (sanitize_filename(part_number) + ".pdf")


# ---- 다운로드 (curl_cffi로 브라우저인 척 흉내 내며 받아요) ----

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


# 401/403(권한거부)은 서버가 "이 요청은 아예 허용 안 함"이라고 답한 거라, 완전히 똑같은 요청을
# 다시 보내도 결과가 똑같아요. 실제로 analog.com에서 헤더를 완전히 다르게(심지어 아예 없이) 줘봐도
# Akamai가 바이트 단위로 동일한 차단 페이지(errors.edgesuite.net)를 돌려주는 걸 확인했어요 — 이건
# 헤더가 아니라 요청 IP 자체를 막는 경우라, 재시도는 시간 낭비고 곧바로 포기하는 게 맞아요.
# 반대로 타임아웃/연결 오류/5xx/429 같은 건 일시적인 문제일 수 있으니 재시도해볼 만해요.
NON_RETRYABLE_STATUS = {401, 403}

MAX_RETRY_DELAY = 30.0  # 지수 백오프의 상한(초) - 계속 배로 늘어나다가 여기서 멈춰요.


def _download_once(url: str, dest_path: Path) -> tuple[str | None, bool]:
    # 다운로드 한 번 시도. (실패 사유 또는 None, 재시도해볼 만한지)를 돌려줘요.
    origin = urlparse(url)
    headers = dict(DOWNLOAD_HEADERS)
    headers["Referer"] = f"{origin.scheme}://{origin.netloc}/"

    try:
        resp = curl_requests.get(url, timeout=30, headers=headers, allow_redirects=True, impersonate="chrome")
    except Exception as e:
        return f"요청 실패: {e}", True  # 연결이 끊기거나 타임아웃 나는 건 일시적일 수 있어요.

    if resp.status_code != 200:
        retryable = resp.status_code not in NON_RETRYABLE_STATUS
        return f"HTTP {resp.status_code}", retryable

    content = resp.content
    content_type = resp.headers.get("Content-Type", "").lower()
    # 진짜 PDF가 맞는지 확인해요 (PDF는 항상 "%PDF"로 시작해요). 아니면 차단 페이지일 가능성이 커요.
    if not (content.startswith(b"%PDF") or "pdf" in content_type):
        # 차단 페이지로 추정되는 응답은 재시도해도 똑같이 나올 가능성이 높아서 곧바로 포기해요.
        return "PDF가 아닌 응답 (접근 차단/오류 페이지로 추정)", False

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(content)
    return None, True


def download_pdf(url: str, dest_path: Path, max_retries: int = 3) -> str | None:
    """실패 원인에 따라 다르게 대응해요.

    - 401/403(권한거부), PDF가 아닌 응답(차단 페이지 추정): 재시도해도 결과가 똑같을 가능성이
      높아서 곧바로 포기해요.
    - 타임아웃/연결 오류/5xx/429 등: 일시적인 문제일 수 있으니, 대기시간을 2배씩 늘려가며(지수
      백오프, 최대 MAX_RETRY_DELAY초) 최대 max_retries번 더 시도해요.
    """
    last_error = None
    delay = DOWNLOAD_RETRY_DELAY
    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.log(f"  [재시도 {attempt}/{max_retries}] {delay:.0f}초 대기 후 다시 시도...")
            time.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY)

        error, retryable = _download_once(url, dest_path)
        if error is None:
            return None
        last_error = error
        if not retryable:
            break
    return last_error


# ---- DuckDuckGo 웹 검색 (Mouser에 없을 때 제조사 공식 사이트를 찾아봐요) ----


def _extract_real_url(href):
    if href.startswith("//"):
        href = "https:" + href
    qs = parse_qs(urlparse(href).query)
    if "uddg" in qs:
        return unquote(qs["uddg"][0])
    return href


def _is_distributor(url):
    u = url.lower()
    return any(d in u for d in DISTRIBUTOR_DOMAINS)


def _manufacturer_tokens(manufacturer):
    if not manufacturer:
        return []
    words = re.findall(r"[a-zA-Z]+", manufacturer.lower())
    return [w for w in words if len(w) >= 3 and w not in GENERIC_MFR_WORDS]


def _looks_official(url, tokens):
    if not tokens:
        return False
    netloc = urlparse(url).netloc.lower()
    return any(t in netloc for t in tokens)


def _is_captcha_page(html_text):
    return "anomaly-modal" in html_text or "anomaly_modal" in html_text


def _fetch_ddg_html(query):
    resp = _session.get(
        "https://html.duckduckgo.com/html/", params={"q": query}, headers=HEADERS, impersonate="chrome", timeout=20
    )
    resp.raise_for_status()
    return resp.text


def search_datasheet_urls(part_number, manufacturer=None, max_results=10):
    query = f"{manufacturer} {part_number} datasheet pdf" if manufacturer else f"{part_number} datasheet pdf"

    time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))
    html_text = _fetch_ddg_html(query)

    if _is_captcha_page(html_text):
        time.sleep(random.uniform(*RETRY_DELAY_SECONDS))
        html_text = _fetch_ddg_html(query)
        if _is_captcha_page(html_text):
            return []  # 계속 캡차면 억지로 뚫으려 하지 않고 포기해요.

    soup = BeautifulSoup(html_text, "html.parser")
    urls = []
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if not href:
            continue
        real_url = _extract_real_url(href)
        if not _is_distributor(real_url):
            urls.append(real_url)
        if len(urls) >= max_results:
            break
    return urls


def find_datasheet(part_number, manufacturer=None, max_results=10):
    urls = search_datasheet_urls(part_number, manufacturer, max_results=max_results)
    if not urls:
        return None

    tokens = _manufacturer_tokens(manufacturer)
    pdf_urls = [u for u in urls if u.lower().endswith(".pdf")]
    page_urls = [u for u in urls if not u.lower().endswith(".pdf")]

    official_pdf = next((u for u in pdf_urls if _looks_official(u, tokens)), None)
    datasheet_url = official_pdf or (pdf_urls[0] if pdf_urls else None)

    # 막힌 PDF 직링크 대신 열어볼 "제품/문서 페이지" - 같은 제조사 도메인을 우선하고,
    # 없으면 검색 결과 중 PDF가 아닌 첫 링크로 대체해요.
    official_page = next((u for u in page_urls if _looks_official(u, tokens)), None)
    landing_page = official_page or (page_urls[0] if page_urls else None)

    return {
        "datasheet_url": datasheet_url,
        "landing_page": landing_page,
        "official": official_pdf is not None,
    }


# ---- 전체 흐름을 하나로 묶는 함수 (main.py/워커가 이 함수 하나만 부르면 돼요) ----


def download_datasheet_for_part(
    part_number: str, manufacturer_hint: str | None, mouser_client: MouserClient
) -> DownloadResult:
    """부품 하나에 대해 ① 이미 있는지 확인 -> ② Mouser -> ③ 웹 검색 순서로 데이터시트를 받아온다."""
    manufacturer = manufacturer_hint

    # ① 힌트 제조사 기준으로 이미 받아둔 파일이 있으면 그냥 스킵해요.
    if manufacturer:
        dest = build_dest_path(part_number, manufacturer)
        if dest.exists():
            return DownloadResult(STATUS_SKIPPED_EXISTING, dest.name, None, manufacturer)

    # ② Mouser 검색
    try:
        result = mouser_client.search_part(part_number, manufacturer_hint=manufacturer)
    except Exception as e:
        result = None
        mouser_error = str(e)
    else:
        mouser_error = None

    if result and result.get("manufacturer"):
        manufacturer = result["manufacturer"]  # Mouser가 확인해준 제조사가 더 정확해요.

    dest = build_dest_path(part_number, manufacturer)
    if dest.exists():
        return DownloadResult(STATUS_SKIPPED_EXISTING, dest.name, None, manufacturer)

    if result and result.get("datasheet_url"):
        fail_reason = download_pdf(result["datasheet_url"], dest)
        if fail_reason is None:
            return DownloadResult(STATUS_SUCCESS_MOUSER, dest.name, None, manufacturer)

    # ③ 웹(DuckDuckGo) 검색으로 보완
    try:
        web_result = find_datasheet(part_number, manufacturer)
    except Exception as e:
        return DownloadResult(STATUS_FAILED, None, f"웹 검색 오류: {e}", manufacturer)

    if web_result and web_result.get("datasheet_url"):
        fail_reason = download_pdf(web_result["datasheet_url"], dest)
        if fail_reason is None:
            return DownloadResult(STATUS_SUCCESS_WEB, dest.name, None, manufacturer)
        return DownloadResult(
            STATUS_FAILED, None, f"웹 다운로드 실패: {fail_reason}", manufacturer, web_result["datasheet_url"]
        )

    if web_result and web_result.get("landing_page"):
        return DownloadResult(
            STATUS_FAILED, None, "PDF 직링크를 찾지 못함", manufacturer, web_result["landing_page"]
        )

    reason = mouser_error or "Mouser/웹 모두에서 찾지 못함"
    return DownloadResult(STATUS_FAILED, None, reason, manufacturer)

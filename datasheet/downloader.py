# 데이터시트를 실제로 찾아서 다운로드하는 파일이에요.
# 순서: ① 이미 있으면 스킵 -> ② Mouser 검색+다운로드 -> ③ 실패하면 웹(DuckDuckGo) 검색+다운로드 -> ④ 그래도 실패하면 포기.

import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from bs4 import BeautifulSoup
from scrapling import StealthyFetcher

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


# ---- 다운로드 (Scrapling의 StealthyFetcher로 진짜 브라우저를 띄워서 받아요) ----
#
# 예전엔 curl_cffi(가짜 브라우저 흉내)로 받았는데, analog.com처럼 Akamai가 강하게 막는 사이트는
# 흉내만으로는 못 뚫었어요(HTTP 403). StealthyFetcher는 실제로 브라우저를 띄워서 그 안에서
# 페이지를 열기 때문에, 진짜 사람이 여는 것과 더 비슷하게 보여요. 대신 매 요청마다 브라우저를
# 띄우고 닫으므로 curl_cffi보다 훨씬 느려요(요청 1건에 몇 초씩 걸릴 수 있어요).

# 401/403(권한거부)은 서버가 "이 요청은 아예 허용 안 함"이라고 답한 거라, 완전히 똑같은 요청을
# 다시 보내도 결과가 똑같을 가능성이 높아요. 반대로 타임아웃/연결 오류/5xx/429 같은 건 일시적인
# 문제일 수 있으니 재시도해볼 만해요.
NON_RETRYABLE_STATUS = {401, 403}

MAX_RETRY_DELAY = 30.0  # 지수 백오프의 상한(초) - 계속 배로 늘어나다가 여기서 멈춰요.

FETCH_TIMEOUT_MS = 30_000  # StealthyFetcher의 타임아웃은 밀리초 단위예요.


def _register_document_response_capture(captured: dict):
    # Chrome은 PDF 링크로 이동하면 자체 내장 PDF 뷰어로 열어버리는데, 이때 Playwright의
    # page.on("response")로 잡히는 "메인 문서 응답"조차 이미 뷰어가 만든 가짜 HTML 래퍼로
    # 바뀌어 있는 경우가 있었다(실제로 관찰됨 - 특히 Mouser가 주는 순수 PDF 직링크에서). 그래서
    # 응답이 온 "뒤"에 가로채는 대신, page.route()로 요청 자체를 가로채서 우리가 직접
    # route.fetch()로 요청하고 그 결과(APIResponse)를 읽어요 - 브라우저가 그 응답을 PDF 뷰어로
    # 열든 다운로드로 처리하든 상관없이, 항상 서버가 실제로 보낸 바이트 그대로를 받아요.
    #
    # 어떤 링크(예: ti.com/lit/gpn/... 같은 "문헌 받기" 리다이렉트)는 그래도 브라우저의 파일
    # 다운로드 자체를 트리거할 수 있어서, 다운로드 이벤트도 보조 수단으로 같이 잡아둬요.
    #
    # 주의: download.path()처럼 대기(block)하는 Playwright 호출을 on_download 이벤트 콜백 안에서
    # 바로 부르면 내부적으로 멈출 수 있어요(Playwright 동기 API의 알려진 문제) - 그래서 download는
    # 객체 참조만 저장해두고, 실제로 기다리는 호출은 아래 page_action(콜백이 아니라 일반 흐름이라
    # 안전해요)에서 해요. route.fetch()는 라우트 핸들러 안에서 바로 불러도 안전해요(Playwright의
    # 공식 문서/예제에서도 이 패턴을 그대로 씀 - 응답을 가로채기 위해 설계된 API라 이벤트 리스너와는
    # 다르게 취급됨).
    def page_setup(page):
        def handle_route(route):
            request = route.request
            if request.resource_type != "document" or "handled" in captured:
                route.continue_()
                return
            captured["handled"] = True
            response = None
            try:
                response = route.fetch()
                captured["status"] = response.status
                captured["body"] = response.body()
            except Exception:
                pass  # 못 받으면 그냥 넘어가요 - 아래에서 "body" 없음으로 처리돼요.
            finally:
                try:
                    if response is not None:
                        route.fulfill(response=response)
                    else:
                        route.continue_()
                except Exception:
                    pass

        def on_download(download):
            if "body" not in captured:
                captured["download"] = download

        page.route("**/*", handle_route)
        page.on("download", on_download)

    return page_setup


def _read_captured_body(captured: dict):
    def page_action(page):
        if "body" in captured:
            return page  # route.fetch()로 이미 직접 받았어요.

        download = captured.get("download")
        if download is not None:
            try:
                path = download.path()
                if path:
                    captured["body"] = Path(path).read_bytes()
                    captured["status"] = 200  # 다운로드가 시작됐다는 건 서버가 정상 응답했다는 뜻이에요.
            except Exception:
                pass  # 못 읽으면 그냥 넘어가요 - 아래에서 "body" 없음으로 처리돼요.
        return page

    return page_action


def _download_once(url: str, dest_path: Path) -> tuple[str | None, bool]:
    # 다운로드 한 번 시도. (실패 사유 또는 None, 재시도해볼 만한지)를 돌려줘요.
    captured: dict = {}
    try:
        StealthyFetcher.fetch(
            url,
            headless=True,
            timeout=FETCH_TIMEOUT_MS,
            page_setup=_register_document_response_capture(captured),
            page_action=_read_captured_body(captured),
        )
    except Exception as e:
        return f"요청 실패: {e}", True  # 브라우저 실행/연결이 실패하는 건 일시적일 수 있어요.

    if "body" not in captured:
        return "응답을 가로채지 못함 (차단/오류 페이지로 추정)", True

    status = captured.get("status", 0)
    if status != 200:
        retryable = status not in NON_RETRYABLE_STATUS
        return f"HTTP {status}", retryable

    content = captured["body"]
    # 진짜 PDF가 맞는지 확인해요 (PDF는 항상 "%PDF"로 시작해요). 헤더가 뭐라고 하든, 실제 바이트
    # 자체로만 판단해요 - 헤더는 pdf라고 해도 실제 내용은 차단 페이지/뷰어 래퍼인 경우가 있었어요.
    if not content.startswith(b"%PDF"):
        # 실제로 뭘 받았는지 로그로 남겨요 (차단 페이지인지, 캡처 로직 자체가 잘못됐는지 구분하려고).
        preview = content[:300].decode("utf-8", errors="replace")
        logger.log(f"  [디버그] {url} 응답이 PDF가 아님 (status={status}): {preview!r}")
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


# 웹 검색 후보는 여러 개를 브라우저로 열어봐야 할 수 있어서(URL이 .pdf로 안 끝나도 실제로는 PDF인
# 경우가 있음), 브라우저 실행 자체가 느린 걸 감안해 후보 하나당 재시도 없이 딱 한 번만 열어보고,
# 최대 이 개수까지만 시도해요. 같은 URL을 반복 재시도하는 것보다 다른 후보로 넘어가는 게 시간
# 대비 성공 가능성이 더 높아요. (실측 결과 후보 하나 확인하는 데 3~4초 정도라, search_datasheet_urls가
# 찾아주는 만큼(최대 max_results=10, 유통사 제외하면 보통 7개 안팎) 다 시도해도 30초 안팎이에요.)
MAX_CANDIDATES_TO_TRY = 7


def _try_candidates(urls: list[str], dest_path: Path) -> tuple[bool, list[str]]:
    """우선순위 순서로 후보 URL을 앞에서부터 최대 MAX_CANDIDATES_TO_TRY개까지 한 번씩 열어봐요.
    성공하면 (True, 그때까지 시도한 URL들), 다 실패하면 (False, 시도한 URL 전부)를 돌려줘요."""
    to_try = urls[:MAX_CANDIDATES_TO_TRY]
    tried = []
    for i, url in enumerate(to_try, start=1):
        logger.log(f"  [웹 후보 {i}/{len(to_try)}] {url}")
        tried.append(url)
        error, _ = _download_once(url, dest_path)
        if error is None:
            return True, tried
        logger.log(f"    -> 실패: {error}")
    return False, tried


# 자동 다운로드는 다 실패해도, 사람이 직접 열어볼 참고 링크는 하나 남겨야 해요. 제조사 제품 소개
# 페이지나 부품 판매 사이트보다, "클릭하면 바로 다운로드" UI를 갖춘 데이터시트 전문 사이트가
# 사람에게 훨씬 쓸모 있어서 이런 곳을 우선으로 골라요.
KNOWN_DATASHEET_AGGREGATORS = ["alldatasheet.com", "datasheets.com"]


def _pick_reference_url(tried_urls: list[str]) -> str | None:
    if not tried_urls:
        return None
    for url in tried_urls:
        if any(domain in url.lower() for domain in KNOWN_DATASHEET_AGGREGATORS):
            return url
    return tried_urls[-1]  # 아는 사이트가 없으면 그냥 마지막으로 시도한 링크를 남겨요.


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
    tokens = [w for w in words if len(w) >= 3 and w not in GENERIC_MFR_WORDS]

    # "Texas Instruments" -> ti.com, "ON Semiconductor" -> onsemi.com 처럼, 회사 이름 단어들이
    # 흔한 단어라 다 걸러지거나 도메인이 약어인 경우가 있어요. 단어 앞글자를 모은 약어도 후보에
    # 넣어서 이런 도메인도 "공식"으로 인식하게 해요 (우선순위 정렬에만 쓰여서, 틀려도 최종 결과가
    # 잘못되진 않아요 - 실제 PDF인지는 어차피 응답 바이트로 따로 확인하니까요).
    if len(words) >= 2:
        acronym = "".join(w[0] for w in words)
        if len(acronym) >= 2:
            tokens.append(acronym)

    return tokens


def _looks_official(url, tokens):
    if not tokens:
        return False
    netloc = urlparse(url).netloc.lower()
    return any(t in netloc for t in tokens)


def _is_captcha_page(html_text):
    return "anomaly-modal" in html_text or "anomaly_modal" in html_text


def _fetch_ddg_html(query):
    url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    resp = StealthyFetcher.fetch(url, headless=True, timeout=20_000, extra_headers=HEADERS)
    if resp.status != 200:
        raise RuntimeError(f"DuckDuckGo 검색 실패: HTTP {resp.status}")
    return resp.body.decode("utf-8", errors="replace")


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
    result_links = soup.select("a.result__a")
    urls = []
    for a in result_links:
        href = a.get("href")
        if not href:
            continue
        real_url = _extract_real_url(href)
        if not _is_distributor(real_url):
            urls.append(real_url)
        if len(urls) >= max_results:
            break

    # 디버그용: DuckDuckGo가 검색 결과를 몇 개 줬고, 그중 유통사를 뺀 링크가 뭐였는지 남겨요.
    logger.log(f"  [디버그] DDG 검색 '{query}' -> 결과 {len(result_links)}개, 유통사 제외 후 {urls}")
    return urls


def find_datasheet(part_number, manufacturer=None, max_results=10):
    urls = search_datasheet_urls(part_number, manufacturer, max_results=max_results)
    if not urls:
        return None

    tokens = _manufacturer_tokens(manufacturer)

    def priority(u):
        # 낮을수록 먼저 시도해요: 공식 도메인+.pdf 확장자 > 공식 도메인 > .pdf 확장자 > 나머지.
        # URL이 .pdf로 안 끝나도(예: ti.com/lit/gpn/... 같은 제조사 공식 리다이렉트) 실제로 열어보면
        # PDF인 경우가 많아서, 문자열만 보고 걸러내지 않고 우선순위만 뒤로 미뤄요 - 실제 판단은
        # _download_once가 응답 바이트를 보고 해요.
        official = _looks_official(u, tokens)
        is_pdf = u.lower().endswith(".pdf")
        if official and is_pdf:
            return 0
        if official:
            return 1
        if is_pdf:
            return 2
        return 3

    candidates = sorted(urls, key=priority)
    return {"candidates": candidates}


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

    if web_result and web_result.get("candidates"):
        succeeded, tried_urls = _try_candidates(web_result["candidates"], dest)
        if succeeded:
            return DownloadResult(STATUS_SUCCESS_WEB, dest.name, None, manufacturer)
        return DownloadResult(
            STATUS_FAILED,
            None,
            "웹에서 찾은 후보 링크가 모두 실패함",
            manufacturer,
            _pick_reference_url(tried_urls),
        )

    reason = mouser_error or "Mouser/웹 모두에서 찾지 못함"
    return DownloadResult(STATUS_FAILED, None, reason, manufacturer)

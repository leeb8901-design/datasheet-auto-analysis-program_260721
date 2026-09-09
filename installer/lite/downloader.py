# 데이터시트를 실제로 찾아서 다운로드하는 파일이에요.
# [Lite 배포판] 순서: ① 이미 있으면 스킵 -> ② Mouser 검색+다운로드 -> ③ 실패하면 Mouser +
# DigiKey + 일반 구글 검색 참고 링크 3개를 남김(자동 다운로드/접속은 안 함 - 사람이 직접 눌러서
# 찾음).
#
# 이 파일은 원래(개발용) 버전에 있던 "③ 웹(DuckDuckGo) 검색으로 보완" 단계를 통째로 뺀 버전이에요
# (2026-09-04 도입, 2026-09-09 최신 코드로 재동기화 - Mouser 성공률 개선/202 폴링 등은 그대로
# 유지). DuckDuckGo를 자동으로 두드리다가 실제로 IP가 차단된 사고가 있었어서(원본 CLAUDE.md 결정
# 로그 참고), 불특정 다수에게 배포하는 이 버전에서는 그 위험을 아예 없애기로 함 - Mouser 공식
# API만 쓰고, 그걸로 못 찾으면 자동으로 다른 곳을 뒤지지 않고 사람이 직접 찾아보도록 참고 링크만
# 안내해요.
#
# ** 원본 datasheet/downloader.py를 고칠 때(DDG 관련이 아닌 공통 로직 - Mouser 다운로드,
# 202 폴링, 재시도, 참고 링크 만들기 등)는 이 파일에도 같은 수정을 반영해줄 것 **
# (installer/lite/README.md 참고 - 공유 함수 목록도 거기 있음).

import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from scrapling import StealthyFetcher

from datasheet.search import MouserClient
from utils.config import DOWNLOAD_DIR as _DEFAULT_DOWNLOAD_DIR
from utils.config import (
    STATUS_FAILED,
    STATUS_SKIPPED_EXISTING,
    STATUS_SUCCESS_MOUSER,
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
DOWNLOAD_RETRY_DELAY = 2.0  # 다운로드 실패 시 재시도 전 대기시간

# Akamai류 봇 차단으로 이미 여러 번 확인된 도메인들 - 완전히 빼진 않지만(나중에 풀릴 수도 있으니),
# 시도 시간을 짧게 잘라요(BLOCKED_DOMAIN_TIMEOUT_MS).
KNOWN_BLOCKED_DOMAINS = ["analog.com"]
BLOCKED_DOMAIN_TIMEOUT_MS = 20_000


def _is_known_blocked(url: str) -> bool:
    u = url.lower()
    return any(d in u for d in KNOWN_BLOCKED_DOMAINS)


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


# 다운로드 단계에서는 대분류/소분류를 구분하지 않아요 - 모든 PDF를 Download_ datasheets 폴더
# 바로 아래에 "품번.pdf"로 평평하게 저장해요(자동 다운로드든 사용자가 직접 받아서 넣은 것이든).
# '신뢰도 분석' 단계에서 대분류/소분류가 밝혀지면, 그때서야 <대분류>/<소분류> 폴더를 만들어
# 그 안으로 옮겨요(move_to_classified) - 다운로드 시점엔 아직 분류를 모르니 여기서는 안 해요.


def _pdf_filename(part_number: str) -> str:
    return sanitize_filename(part_number) + ".pdf"


def dest_path_for_part(part_number: str) -> Path:
    """다운로드가 저장할(또는 저장된) 평평한 경로예요. 새로 받는 PDF는 항상 여기로 가요."""
    return _download_dir / _pdf_filename(part_number)


def classified_dest_path(part_number: str, category: str, subcategory: str) -> Path:
    folder = _download_dir / sanitize_filename(category) / sanitize_filename(subcategory)
    return folder / _pdf_filename(part_number)


def resolve_existing_pdf(part_number: str) -> Path | None:
    """이 품번의 PDF가 지금 있는 위치를 찾아요 - 평평한 자리(다운로드 직후)든, 분석 후 분류돼
    옮겨진 자리(<대분류>/<소분류>)든 상관없이. 없으면 None."""
    flat = dest_path_for_part(part_number)
    if flat.exists():
        return flat
    if not _download_dir.exists():
        return None
    matches = list(_download_dir.glob(f"*/*/{_pdf_filename(part_number)}"))
    return matches[0] if matches else None


def has_pdf(part_number: str) -> bool:
    return resolve_existing_pdf(part_number) is not None


def is_pdf_locked(path: Path) -> bool:
    """이 파일이 지금 다른 프로그램(PDF 뷰어 등)에서 열려서 잠겨 있는지 확인해요(2026-09-04
    도입). '신뢰도 분석'은 분석된 PDF를 분류 폴더로 옮기고(move_to_classified) 그 위에 주석까지
    써야 하는데, 파일이 열려 있으면 이 과정이 실패하거나(옮기기 자체가 막힘) 주석이 조용히 안
    붙을 수 있어서, 분석을 시작하기 전에 미리 확인하는 안전장치예요. 실제로 열어보고 실패하면
    잠긴 것으로 판단해요(Windows에서 Adobe Reader 등 대부분의 PDF 뷰어는 파일을 열어둔 동안
    쓰기 잠금을 걸어요. 다만 일부 뷰어(예: 브라우저 내장 뷰어)는 파일을 한 번만 읽고 안 잠그기도
    해서 100% 확실한 검사는 아니에요). 파일이 아예 없으면 잠긴 게 아니라고 봐요."""
    if not path.exists():
        return False
    try:
        with open(path, "r+b"):
            pass
        return False
    except OSError:
        return True


def move_to_classified(part_number: str, category: str, subcategory: str, current_path: Path) -> Path:
    """분석으로 대분류/소분류가 밝혀진 뒤, 평평한 자리에 있던 PDF를 <대분류>/<소분류> 폴더로
    옮겨요. 이미 그 자리에 있으면(재분석 등) 그대로 두고, 옮길 파일이 없으면 목표 경로만 돌려줘요."""
    dest = classified_dest_path(part_number, category, subcategory)
    if dest == current_path:
        return dest
    if not current_path.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        current_path.unlink(missing_ok=True)  # 이미 옮겨져 있으면(재실행 등) 평평한 쪽 사본만 정리해요.
    else:
        current_path.replace(dest)
    return dest


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

# scrapling이 내려받는 Chrome for Testing 브라우저(chrome.exe)가 일부 Windows에서 side-by-side
# 오류로 아예 실행이 안 되는 문제가 있어요("side-by-side configuration is incorrect" /
# "spawn UNKNOWN"). 그래서 기본적으로 시스템에 설치된 진짜 Google Chrome을 사용해요.
# Chrome이 없는 환경이라면 환경변수 SCRAPLING_REAL_CHROME=0 으로 꺼서 번들 브라우저를 쓰게 할 수 있어요.
USE_REAL_CHROME = os.environ.get("SCRAPLING_REAL_CHROME", "1") != "0"

# ---- HTTP 202 Accepted 비동기 폴링 (2026-09-05 도입) ----
#
# 어떤 사이트는 데이터시트 문서 요청에 곧바로 200을 안 주고, "지금 만들고 있으니 이 주소로
# 나중에 다시 물어봐(Location) + 몇 초 뒤에(Retry-After)"라는 뜻으로 202 Accepted를 돌려줘요
# (비동기 작업 큐/봇 검증 대기 등에서 흔한 패턴). StealthyFetcher(진짜 브라우저)는 이런 "나중에
# 다시 물어보기"를 자동으로 안 해줘서, 202를 받으면 Location 주소를 우리가 직접 폴링해요.
#
# 이 폴링은 브라우저 없이 requests로 직접 보내요 - 이미 브라우저가 202를 확인해준 뒤라 봇 검증
# 자체는 통과한 상태로 보고, 같은 문서를 다시 확인만 하는 거라 가벼운 GET이면 충분해요. 대신
# "브라우저가 아니다"라는 신호를 최대한 줄이기 위해, 실제 최신 Chrome이 보내는 것과 비슷한
# 헤더를 붙여요. real_chrome=True로 뜨는 StealthyFetcher 쪽은 이미 진짜 Chrome이라 손대지
# 않아요 - 오히려 여기 헤더를 그쪽에도 억지로 덮어씌우면 JS가 보고하는 값과 HTTP 헤더 값이
# 어긋나서 더 수상해 보일 수 있어요.
BROWSER_LIKE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

ASYNC_POLL_MAX_ATTEMPTS = 10  # 최대 시도 횟수
ASYNC_POLL_DEFAULT_DELAY = 2.5  # Retry-After가 없을 때 기본 대기(초)
ASYNC_POLL_MAX_DELAY = 30.0  # Retry-After가 비정상적으로 크게 와도 이 이상은 안 기다리는 안전장치


def _header_get(headers: dict, name: str) -> str | None:
    # HTTP 헤더 이름은 대소문자를 구분하지 않는데, Playwright가 돌려주는 딕셔너리 키의 대소문자가
    # 항상 같다는 보장이 없어서 직접 대소문자 무시 검색을 해요.
    if not headers:
        return None
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _parse_retry_after(value: str | None) -> float:
    # Retry-After는 초 단위 숫자("3") 또는 HTTP 날짜("Wed, 21 Oct 2026 07:28:00 GMT") 둘 다 가능해요.
    if not value:
        return ASYNC_POLL_DEFAULT_DELAY
    value = value.strip()
    if value.isdigit():
        return min(float(value), ASYNC_POLL_MAX_DELAY)
    try:
        target_dt = parsedate_to_datetime(value)
        now = datetime.now(target_dt.tzinfo) if target_dt.tzinfo else datetime.now()
        seconds = (target_dt - now).total_seconds()
        return max(0.0, min(seconds, ASYNC_POLL_MAX_DELAY))
    except (TypeError, ValueError):
        return ASYNC_POLL_DEFAULT_DELAY


def _poll_async_202(location_url: str, retry_after: str | None, referer: str) -> tuple[bytes | None, int, str | None]:
    """서버가 202 Accepted + Location(작업 상태 확인 URL)을 돌려줬을 때, 그 URL을 Retry-After
    시간만큼 대기하며 최대 ASYNC_POLL_MAX_ATTEMPTS번 GET으로 확인해요.

    반환: (본문 바이트 또는 None, 최종 상태 코드, 실패 사유 또는 None).
    - 200이 되면 (본문, 200, None).
    - 202가 아닌 다른 오류(4xx/5xx)를 만나면 그 자리에서 바로 (None, 상태코드, 사유) - 더
      기다려도 똑같을 가능성이 높아서 폴링을 계속하지 않아요.
    - 최대 시도 횟수를 넘기면 (None, 202, 타임아웃 사유).
    """
    headers = dict(BROWSER_LIKE_HEADERS)
    headers["Referer"] = referer
    url = location_url
    delay = _parse_retry_after(retry_after)

    for attempt in range(1, ASYNC_POLL_MAX_ATTEMPTS + 1):
        logger.log(f"    [202] 비동기 작업 확인 대기 중... {delay:.1f}초 후 {attempt}/{ASYNC_POLL_MAX_ATTEMPTS}번째 확인")
        time.sleep(delay)
        try:
            resp = requests.get(url, headers=headers, timeout=20)
        except requests.RequestException as e:
            return None, 0, f"202 폴링 중 연결 오류: {e}"

        if resp.status_code == 200:
            return resp.content, 200, None
        if resp.status_code == 202:
            # 서버가 매 폴링마다 새 Location/Retry-After를 줄 수도 있어요 - 있으면 갱신하고,
            # 없으면 방금 쓴 값을 그대로 유지해요.
            url = resp.headers.get("Location") or url
            delay = _parse_retry_after(resp.headers.get("Retry-After"))
            continue
        return None, resp.status_code, f"202 폴링 중 HTTP {resp.status_code}"

    return None, 202, f"202 폴링 {ASYNC_POLL_MAX_ATTEMPTS}회 초과 (타임아웃)"


# ---- Mouser 경로 전용 가벼운 다운로드 (2026-09-05 도입, 다운로드 실패율 낮추기 요청) ----
#
# Mouser API가 주는 데이터시트 링크(DataSheetUrl)나, 그게 비어 있을 때 제품 상세페이지에서 찾은
# PDF 링크는 대부분 Mouser 자체 CDN/제조사 공식 사이트라 analog.com급 강한 봇 차단이 없는 경우가
# 많아요 - 그래서 매번 무거운 브라우저(StealthyFetcher)를 띄우지 않고, requests로 가볍고 빠르게
# 먼저 받아봐요(403 방지용 User-Agent/Referer 포함). 이 가벼운 시도가 실패하면(요청 자체 오류,
# 403, PDF 아닌 응답 등) 기존의 브라우저 기반 download_pdf로 한 번 더 시도해서, 지금까지 있던
# 성공률은 그대로 유지하고 그 위에 "더 빠른 첫 시도"만 추가하는 구조예요.
MOUSER_PDF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.mouser.com/",
}


def _fetch_pdf_direct(url: str, dest_path: Path, timeout: int = 20) -> str | None:
    """브라우저 없이 requests로 바로 받아봐요. 성공하면 None, 실패하면 사유 문자열을 돌려줘요."""
    try:
        resp = requests.get(url, headers=MOUSER_PDF_HEADERS, timeout=timeout)
    except requests.RequestException as e:
        return f"요청 실패: {e}"

    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"

    content = resp.content
    if not content.startswith(b"%PDF"):
        return "PDF가 아닌 응답 (접근 차단/오류 페이지로 추정)"

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(content)
    return None


def _fetch_datasheet_url_from_product_page(product_detail_url: str, timeout_ms: int = FETCH_TIMEOUT_MS) -> str | None:
    """Mouser API의 DataSheetUrl이 비어 있을 때, 제품 상세페이지(ProductDetailUrl) HTML을 받아서
    href에 ".pdf"가 들어간 첫 번째 링크를 데이터시트로 추정해 돌려줘요. 못 찾으면 None.

    실제로 requests로 이 페이지를 그냥 열어보면 Mouser 자체 봇 차단에 걸려 "Access to this page
    has been denied" 응답을 받는 것을 확인함(2026-09-05, 실측 - HTTP 200이지만 내용이 차단
    페이지). API 응답(search_part)과 달리, 이 사람용 웹페이지는 브라우저가 아니면 막힘 - 그래서
    이 함수만 다른 봇 차단 사이트와 같은 방식(StealthyFetcher, 실제 브라우저)으로 열어요."""
    try:
        resp = StealthyFetcher.fetch(
            product_detail_url, headless=True, real_chrome=USE_REAL_CHROME, timeout=timeout_ms, extra_headers=HEADERS
        )
    except Exception as e:
        logger.log(f"  [디버그] 제품 상세페이지({product_detail_url}) 요청 실패: {e}")
        return None
    if resp.status != 200:
        logger.log(f"  [디버그] 제품 상세페이지 응답이 200이 아님 (status={resp.status}): {product_detail_url}")
        return None

    html_text = resp.body.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html_text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" in href.lower():
            return urljoin(product_detail_url, href)
    return None


def _download_via_mouser_url(url: str, dest: Path) -> str | None:
    """Mouser 관련 URL(직접 DataSheetUrl이든, 제품 상세페이지에서 찾은 링크든) 하나를 받아봐요.
    가벼운 requests 시도를 먼저 하고, 실패하면 기존 브라우저 기반 download_pdf로 재시도해요.
    성공하면 None, 끝까지 실패하면 마지막 실패 사유를 돌려줘요."""
    light_error = _fetch_pdf_direct(url, dest)
    if light_error is None:
        return None
    logger.log(f"  [디버그] 가벼운 다운로드 실패({light_error}) - 브라우저로 재시도합니다: {url}")
    return download_pdf(url, dest)


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
                captured["headers"] = response.headers  # 202 Accepted일 때 Location/Retry-After 확인용
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


def _download_once(url: str, dest_path: Path, timeout_ms: int = FETCH_TIMEOUT_MS) -> tuple[str | None, bool]:
    # 다운로드 한 번 시도. (실패 사유 또는 None, 재시도해볼 만한지)를 돌려줘요.
    captured: dict = {}
    try:
        StealthyFetcher.fetch(
            url,
            headless=True,
            real_chrome=USE_REAL_CHROME,
            timeout=timeout_ms,
            page_setup=_register_document_response_capture(captured),
            page_action=_read_captured_body(captured),
        )
    except Exception as e:
        return f"요청 실패: {e}", True  # 브라우저 실행/연결이 실패하는 건 일시적일 수 있어요.

    if "body" not in captured:
        return "응답을 가로채지 못함 (차단/오류 페이지로 추정)", True

    status = captured.get("status", 0)
    content = captured["body"]

    if status == 202:
        # 비동기 작업 큐 응답 - Location 헤더가 있으면 그 주소를 직접 폴링해요.
        headers = captured.get("headers") or {}
        location = _header_get(headers, "Location")
        if not location:
            logger.log(f"  [디버그] {url} 응답이 202인데 Location 헤더가 없어 폴링할 수 없음")
            return "HTTP 202 (Location 헤더 없음, 폴링 불가)", True
        location = urljoin(url, location)  # 상대경로일 수 있어서 절대경로로 만들어요.
        retry_after = _header_get(headers, "Retry-After")
        logger.log(f"  [202] {url} -> Accepted, {location}에서 결과를 기다립니다.")
        polled_content, final_status, poll_error = _poll_async_202(location, retry_after, referer=url)
        if final_status != 200 or polled_content is None:
            # 429/5xx/연결오류(0)는 일시적일 수 있어 재시도해볼 만하고, 나머지 4xx는 다시 해도
            # 똑같을 가능성이 높아요.
            retryable = final_status == 0 or final_status >= 500 or final_status == 429
            return poll_error or f"202 폴링 실패 (HTTP {final_status})", retryable
        status = 200
        content = polled_content

    if status != 200:
        retryable = status not in NON_RETRYABLE_STATUS
        return f"HTTP {status}", retryable

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
    timeout_ms = BLOCKED_DOMAIN_TIMEOUT_MS if _is_known_blocked(url) else FETCH_TIMEOUT_MS
    last_error = None
    delay = DOWNLOAD_RETRY_DELAY
    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.log(f"  [재시도 {attempt}/{max_retries}] {delay:.0f}초 대기 후 다시 시도...")
            time.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY)

        error, retryable = _download_once(url, dest_path, timeout_ms=timeout_ms)
        if error is None:
            return None
        last_error = error
        if not retryable:
            break
    return last_error


def _general_search_url(part_number: str, manufacturer: str | None) -> str:
    """Mouser 자체 검색(_mouser_search_url)까지도 부족하게 느껴질 때, 사람이 좀 더 폭넓게 찾아볼
    수 있게 주는 일반 구글 검색 링크예요. 특정 데이터시트가 아니라 검색결과 페이지라, 실제로
    찾는 건 사람 몫이에요. 이 함수는 URL만 만들 뿐 절대 구글에 접속하지 않아요(스크래핑 없음) -
    순수하게 "사람이 실제 브라우저로 직접 눌러서 찾는" 용도예요."""
    query = f"{manufacturer} {part_number} datasheet" if manufacturer else f"{part_number} datasheet"
    return "https://www.google.com/search?" + urlencode({"q": query})


# ---- Mouser/DigiKey 자체 검색 링크 ----
def _mouser_search_url(part_number: str) -> str:
    """Mouser 자체 검색 결과 페이지 링크를 만들어요. 실제로 접속해서 확인하지는 않아요(사람이
    직접 눌러서 봄) - 그래서 이 부품을 Mouser가 취급하는지는 사람이 눌러봐야 알 수 있어요."""
    return "https://www.mouser.com/c/?" + urlencode({"q": part_number})


def _digikey_search_url(part_number: str) -> str:
    """DigiKey 자체 검색 결과 페이지 링크예요. Mouser와 마찬가지로 실제 접속은 안 해요."""
    return "https://www.digikey.com/en/products/result?" + urlencode({"keywords": part_number})


def _reference_url_with_distributor_fallback(part_number: str, manufacturer: str | None) -> str:
    """참고 링크를 정할 때, Mouser·DigiKey 검색 링크에 일반 구글 검색 링크까지 셋 다 줘요 - 한
    품번을 Mouser는 안 팔고 DigiKey는 파는(또는 반대) 경우가 있고, 둘 다 없으면 구글로 더 폭넓게
    찾아볼 수 있어야 해서예요.

    세 링크를 줄바꿈으로 이어서 하나의 문자열로 돌려줘요 - DownloadResult.reference_url이
    문자열 하나라서(엑셀 하이퍼링크 칸도 원래 한 셀에 링크 하나만 가능), 화면(ui/main_window.py의
    _set_datasheet_cell)에서 줄바꿈 기준으로 나눠 링크 여러 개로 보여줘요. 엑셀에 실제로 저장되는
    하이퍼링크는 첫 번째(Mouser) 것만이에요(excel/excel_writer.py 참고)."""
    return "\n".join([
        _mouser_search_url(part_number),
        _digikey_search_url(part_number),
        _general_search_url(part_number, manufacturer),
    ])


# ---- 전체 흐름을 하나로 묶는 함수 (main.py/워커가 이 함수 하나만 부르면 돼요) ----


# 품목 하나 처리 간격 사이의 대기시간이에요(2026-09-05 도입) - Mouser API를 너무 빠르게 연달아
# 두드리다 Rate Limit(요청 과다)에 걸리는 걸 막기 위한 페이싱이에요. 이미 파일이 있어서 API를
# 아예 안 부르는 품번(①)까지 괜히 늦추지 않으려고, Mouser를 실제로 호출하기 직전에만 재요.
RATE_LIMIT_DELAY_RANGE = (0.5, 1.0)


def download_datasheet_for_part(
    part_number: str, manufacturer_hint: str | None, mouser_client: MouserClient
) -> DownloadResult:
    """부품 하나에 대해 ① 이미 있는지 확인 -> ② Mouser 순서로 데이터시트를 받아온다. [Lite 배포판]
    Mouser로 못 찾으면(자동 웹 검색 없이) 참고 링크 3개(Mouser/DigiKey/구글 검색)만 남겨서 사람이
    직접 찾도록 안내한다."""
    manufacturer = manufacturer_hint
    dest = dest_path_for_part(part_number)

    # ① 이미 받아둔 파일이 있으면 그냥 스킵해요 (평평한 자리든, 이미 분석돼 분류 폴더로 옮겨진 자리든).
    existing = resolve_existing_pdf(part_number)
    if existing is not None:
        return DownloadResult(STATUS_SKIPPED_EXISTING, existing.name, None, manufacturer)

    # ② Mouser 검색 (호출 직전에 살짝 대기 - Rate Limit 방지)
    time.sleep(random.uniform(*RATE_LIMIT_DELAY_RANGE))
    try:
        result = mouser_client.search_part(part_number, manufacturer_hint=manufacturer)
    except Exception as e:
        result = None
        mouser_error = str(e)
    else:
        mouser_error = None

    if result and result.get("manufacturer"):
        manufacturer = result["manufacturer"]  # Mouser가 확인해준 제조사가 더 정확해요.

    if result:
        datasheet_url = result.get("datasheet_url")
        if not datasheet_url and result.get("product_detail_url"):
            # DataSheetUrl이 비어 있으면, 제품 상세페이지에서 PDF 링크를 직접 찾아봐요.
            datasheet_url = _fetch_datasheet_url_from_product_page(result["product_detail_url"])
            if datasheet_url:
                logger.log(f"  [디버그] {part_number}: 제품 상세페이지에서 데이터시트 링크를 찾음 -> {datasheet_url}")

        if datasheet_url:
            fail_reason = _download_via_mouser_url(datasheet_url, dest)
            if fail_reason is None:
                return DownloadResult(STATUS_SUCCESS_MOUSER, dest.name, None, manufacturer)

    # ③ Mouser로 못 찾음 (자동 웹 검색 없이 참고 링크만 남김) - Lite 배포판은 여기서 끝
    reason = mouser_error or "Mouser에서 찾지 못함"
    return DownloadResult(
        STATUS_FAILED, None, reason, manufacturer, _reference_url_with_distributor_fallback(part_number, manufacturer)
    )

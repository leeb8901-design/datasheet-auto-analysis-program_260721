# 데이터시트를 실제로 찾아서 다운로드하는 파일이에요.
# 순서: ① 이미 있으면 스킵 -> ② Mouser 검색+다운로드 -> ③ 실패하면 웹(DuckDuckGo) 검색+다운로드
# -> ④ 그래도 못 찾으면 Mouser + DigiKey + 일반 구글 검색, 참고 링크 3개를 전부 남김(자동
# 다운로드/접속은 안 함, 2026-09-03 도입 - DDG를 자동으로 두드리다 IP가 차단된 적이 있어서, 구글
# 검색결과를 긁는 것도 시도해봤지만 구글이 실제 링크를 암호화해 숨겨놔서 포기하고 이 방식으로 바꿈.
# 링크를 하나만 주면 그 사이트에 없는 품번일 때 막히니, 세 곳 다 줌).

import os
import random
import re
import threading
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
# 2026-09-03: 실제로 DuckDuckGo가 이 프로그램이 쓰는 IP를 막은 사고가 있었음(사용자가 일반
# 브라우저로 duckduckgo.com에 직접 접속해도 안 됨을 확인 - ping은 되는데 TCP 연결만 막힘,
# 즉 DDG 쪽에서 이 IP를 막은 것으로 보임). 자동화 요청이 ①짧은 간격으로 ②여러 스레드가 동시에
# 나가던 게 봇으로 보였을 가능성이 커서, 대기시간을 늘리고(아래) 동시 요청도 막았어요(밑의
# _ddg_request_lock 참고).
MIN_DELAY_SECONDS = 3.0  # 검색 사이 최소 대기시간 (너무 빠르면 로봇으로 의심받아요)
MAX_DELAY_SECONDS = 7.0
RETRY_DELAY_SECONDS = (6.0, 10.0)  # 캡차에 걸렸을 때 재시도 전 대기시간
DOWNLOAD_RETRY_DELAY = 2.0  # 다운로드 실패 시 재시도 전 대기시간

# DDG 요청은 항상 한 번에 하나만 나가게 잠가요 - 동시에 여러 스레드가 같은 사이트를 두드리는 것
# 자체가 강한 봇 신호라서, MAX_CONCURRENT_DOWNLOADS(main_window.py)로 여러 품번을 동시에 처리
# 중이어도 DDG 검색 단계만큼은 줄을 서게 해요(Mouser API 호출은 이 잠금과 무관하게 그대로 동시에
# 진행돼요 - 정식 API라 문제 없음).
_ddg_request_lock = threading.Lock()

# 연결 자체가 안 되면(첫 번째든 몇 번째든) "지금은(아마 IP 차단으로) DDG를 못 쓴다"고 보고,
# 한동안 재시도 없이 바로 건너뛰어요 - 이미 막힌 상태에서 계속 두드리는 것도 봇처럼 보이고,
# 사용자 입장에서도 실패할 게 뻔한 20~45초짜리 타임아웃을 배치 전체에서 계속 기다릴 이유가
# 없어요. 임계값을 1로 낮춤(2026-09-03 사용자 확정 - 원래 3번 연속 실패해야 건너뛰었는데,
# 처음 한 번만 실패해도 이후 품목은 바로 건너뛰고 참고 링크로 대체하도록 바꿈. DDG가 막혔을 때는
# 재시도해도 대부분 계속 막혀 있어서, 3번 다 기다려볼 이유가 없다고 판단함).
_ddg_state_lock = threading.Lock()
_ddg_consecutive_failures = 0
_ddg_blocked_until = 0.0  # time.time() 기준 - 이 시각 전까지는 DDG 요청 자체를 안 보내요.
_DDG_FAILURE_THRESHOLD = 1
_DDG_COOLDOWN_SECONDS = 600  # 10분


def _ddg_is_blocked() -> bool:
    with _ddg_state_lock:
        return time.time() < _ddg_blocked_until


def _ddg_report_result(ok: bool):
    global _ddg_consecutive_failures, _ddg_blocked_until
    with _ddg_state_lock:
        if ok:
            _ddg_consecutive_failures = 0
            return
        _ddg_consecutive_failures += 1
        if _ddg_consecutive_failures >= _DDG_FAILURE_THRESHOLD and time.time() >= _ddg_blocked_until:
            _ddg_blocked_until = time.time() + _DDG_COOLDOWN_SECONDS
            logger.log(
                f"  [알림] DuckDuckGo 연결이 {_ddg_consecutive_failures}번 연속 실패해서, "
                f"앞으로 {_DDG_COOLDOWN_SECONDS // 60}분 동안 DDG를 건너뛰고 구글 검색 링크로 대신 안내합니다."
            )

# 유통사(부품 파는 가게) 사이트 — 대부분 데이터시트 출처로 원하지 않아서 아예 걸러요.
DISTRIBUTOR_DOMAINS = [
    "lcsc.com", "alibaba.com", "aliexpress.com",
    "octopart.com", "findchips.com", "arrow.com", "avnet.com", "rs-online.com",
    "element14.com", "amazon.com", "ebay.com", "tme.com", "newark.com",
]

# Mouser/DigiKey는 예외예요 - 위 목록처럼 아예 걸러내지 않고, 후보로는 남겨두되 우선순위만
# "공식 제조사 도메인" 다음으로 매겨요. 이 두 사이트는 대체로 Akamai류 봇 차단이 없어서 빠르고,
# 제조사가 올린 PDF를 그대로 미러링해두는 경우가 많아 속도/성공률 면에서 유리해요. 목록 순서가
# 그대로 우선순위 순서예요(mouser가 digikey보다 먼저).
PREFERRED_DISTRIBUTOR_DOMAINS = ["mouser.com", "digikey.com"]

# Akamai류 봇 차단으로 이미 여러 번 확인된 도메인들 - 완전히 빼진 않지만(나중에 풀릴 수도 있으니),
# 우선순위를 가장 뒤로 미루고 시도 시간도 짧게 잘라요(BLOCKED_DOMAIN_TIMEOUT_MS).
KNOWN_BLOCKED_DOMAINS = ["analog.com"]
BLOCKED_DOMAIN_TIMEOUT_MS = 20_000


def _is_known_blocked(url: str) -> bool:
    u = url.lower()
    return any(d in u for d in KNOWN_BLOCKED_DOMAINS)

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
        timeout_ms = BLOCKED_DOMAIN_TIMEOUT_MS if _is_known_blocked(url) else FETCH_TIMEOUT_MS
        logger.log(f"  [웹 후보 {i}/{len(to_try)}] {url}")
        tried.append(url)
        error, _ = _download_once(url, dest_path, timeout_ms=timeout_ms)
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


def _general_search_url(part_number: str, manufacturer: str | None) -> str:
    """Mouser 자체 검색(_distributor_search_url)까지도 부족하게 느껴질 때, 사람이 좀 더 폭넓게
    찾아볼 수 있게 주는 일반 구글 검색 링크예요(2026-09-03 도입 - "실패한 항목엔 항상 눌러볼
    게 있어야 한다"). 특정 데이터시트가 아니라 검색결과 페이지라, 실제로 찾는 건 사람 몫이에요.

    구글로 만들어요(같은 날 DuckDuckGo에서 구글로 교체) - DuckDuckGo가 지금 이 IP에서 안 됨을
    이미 확인한 뒤라, DDG 링크를 또 줘봤자 사용자 브라우저에서도 안 열릴 가능성이 높아서예요.
    이 함수는 URL만 만들 뿐 절대 구글에 접속하지 않아요(스크래핑 없음) - 순수하게 "사람이 실제
    브라우저로 직접 눌러서 찾는" 용도예요."""
    query = f"{manufacturer} {part_number} datasheet" if manufacturer else f"{part_number} datasheet"
    return "https://www.google.com/search?" + urlencode({"q": query})


# ---- Mouser/DigiKey 자체 검색 링크 (2026-09-03 사용자 요청, 같은 날 구글 스크래핑에서 전환) ----
#
# 처음엔 구글에서 "<품번> (site:mouser.com OR site:digikey.com)"으로 검색해서 실제 제품 페이지
# 링크를 찾아보려 했는데, 실제로 겪어보니 두 가지 문제가 있었어요.
#   ① 정상 결과 페이지도 "차단 페이지"로 오탐하는 버그가 있었음(구글 자체 봇 감지 스크립트
#      코드의 "/sorry/index" 문자열이 본문에 항상 있어서) - 이건 최종 URL 리다이렉트 여부로
#      바꿔서 고침.
#   ② 그런데 오탐을 고친 뒤에도 여전히 링크를 못 찾았음 - 확인해보니 **구글이 최근 검색결과의
#      실제 목적지 URL을 아예 안 보여줌**. 예전엔 "/url?q=실제주소" 형태였는데, 지금은
#      "/goto?url=CAESgwEB6zsw..." 처럼 암호화된 값이라 사람이 브라우저에서 실제로 클릭해야만
#      풀리고, 정적으로 읽어서는 알아낼 방법이 없음(구글이 스크래핑 방지 목적으로 일부러 이렇게
#      바꾼 것으로 보임 - 코드로 고칠 수 있는 문제가 아님).
#
# 그래서 구글 검색 결과를 파싱하는 대신, **Mouser/DigiKey 자체 검색 페이지로 바로 연결되는
# 링크**를 만들어요. 오히려 더 안전하고(구글/DDG 차단 위험 자체가 없음 - 두 사이트 모두 자동
# 접속은 절대 안 하고 URL만 만듦), 품번이 정확히 일치하면 Mouser/DigiKey 검색이 그 자리에서
# 바로 제품 페이지로 넘어가는 경우도 많아서 한 단계 더 직접적이에요. Mouser를 먼저 시도하는 건
# PREFERRED_DISTRIBUTOR_DOMAINS와 같은 우선순위(Mouser가 DigiKey보다 먼저)를 따른 거예요.
def _mouser_search_url(part_number: str) -> str:
    """Mouser 자체 검색 결과 페이지 링크를 만들어요. 실제로 접속해서 확인하지는 않아요(사람이
    직접 눌러서 봄) - 그래서 이 부품을 Mouser가 취급하는지는 사람이 눌러봐야 알 수 있어요."""
    return "https://www.mouser.com/c/?" + urlencode({"q": part_number})


def _digikey_search_url(part_number: str) -> str:
    """DigiKey 자체 검색 결과 페이지 링크예요. Mouser와 마찬가지로 실제 접속은 안 해요."""
    return "https://www.digikey.com/en/products/result?" + urlencode({"keywords": part_number})


def _reference_url_with_distributor_fallback(part_number: str, manufacturer: str | None) -> str:
    """참고 링크를 정할 때, Mouser·DigiKey 검색 링크에 일반 구글 검색 링크까지 **셋 다** 줘요
    (사용자 확정, 2026-09-03) - 한 품번을 Mouser는 안 팔고 DigiKey는 파는(또는 반대) 경우가
    실제로 있고(NXH50VB47M2.5TP6.3X11 사례), 둘 다 없으면 구글로 더 폭넓게 찾아볼 수 있어야
    해서예요. "Mouser/DigiKey에 있는지"를 자동으로 확인하려면 검색 결과 페이지에 자동으로
    접속해야 하는데, 이건 Mouser/DigiKey 제품 페이지 자동접속이 봇 차단(403)되는 걸 이미 겪은
    것과 같은 위험이라 하지 않기로 함 - 대신 사람이 셋 다 눌러보고 고르면 됨.

    세 링크를 줄바꿈으로 이어서 하나의 문자열로 돌려줘요 - DownloadResult.reference_url이
    문자열 하나라서(엑셀 하이퍼링크 칸도 원래 한 셀에 링크 하나만 가능), 화면(ui/main_window.py의
    _set_datasheet_cell)에서 줄바꿈 기준으로 나눠 링크 여러 개로 보여줘요. 엑셀에 실제로 저장되는
    하이퍼링크는 첫 번째(Mouser) 것만이에요(excel/excel_writer.py 참고)."""
    return "\n".join([
        _mouser_search_url(part_number),
        _digikey_search_url(part_number),
        _general_search_url(part_number, manufacturer),
    ])


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
        return [], None
    words = re.findall(r"[a-zA-Z]+", manufacturer.lower())
    tokens = [w for w in words if len(w) >= 3 and w not in GENERIC_MFR_WORDS]

    # "Texas Instruments" -> ti.com처럼, 회사 이름 단어들이 흔한 단어라 다 걸러지거나 도메인이
    # 약어인 경우가 있어요. 단어 앞글자를 모은 약어를 따로 돌려줘서(tokens와 섞지 않음) 이런
    # 도메인도 "공식"으로 인식하게 해요 - 약어는 짧아서(2~3글자) 아무 도메인에나 우연히 들어있을
    # 수 있으니(예: "ad"가 "adatasheet.com"에도 들어있음), _looks_official에서 tokens와는 다르게
    # "도메인 첫 부분과 정확히 같을 때"만 인정해요.
    acronym = None
    if len(words) >= 2:
        candidate = "".join(w[0] for w in words)
        if len(candidate) >= 2:
            acronym = candidate

    return tokens, acronym


def _domain_main_label(url):
    # "https://www.ti.com/lit/..." -> "ti" (www. 떼고 첫 번째 점 앞부분만)
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.split(".")[0] if netloc else ""


def _looks_official(url, tokens, acronym=None):
    netloc = urlparse(url).netloc.lower()
    if tokens and any(t in netloc for t in tokens):
        return True
    if acronym and _domain_main_label(url) == acronym:
        return True
    return False


def _is_captcha_page(html_text):
    return "anomaly-modal" in html_text or "anomaly_modal" in html_text


def _fetch_ddg_html(query):
    url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    resp = StealthyFetcher.fetch(url, headless=True, real_chrome=USE_REAL_CHROME, timeout=20_000, extra_headers=HEADERS)
    if resp.status != 200:
        raise RuntimeError(f"DuckDuckGo 검색 실패: HTTP {resp.status}")
    return resp.body.decode("utf-8", errors="replace")


def search_datasheet_urls(part_number, manufacturer=None, max_results=10):
    if _ddg_is_blocked():
        logger.log("  [디버그] DuckDuckGo가 최근 연속 실패해서 이번 품번은 건너뜁니다(쿨다운 중).")
        return []

    query = f"{manufacturer} {part_number} datasheet pdf" if manufacturer else f"{part_number} datasheet pdf"

    with _ddg_request_lock:  # 동시에 여러 스레드가 DDG를 두드리지 않도록, 요청은 한 번에 하나만.
        time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))
        try:
            html_text = _fetch_ddg_html(query)
        except Exception:
            _ddg_report_result(False)
            raise
        _ddg_report_result(True)

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

    tokens, acronym = _manufacturer_tokens(manufacturer)

    def priority(u):
        # 낮을수록 먼저 시도해요:
        #   0) 공식 제조사 도메인 + .pdf 확장자
        #   1) 공식 제조사 도메인 (확장자 무관 - 예: ti.com/lit/gpn/... 같은 리다이렉트도 실제로
        #      열어보면 PDF인 경우가 많아서, 문자열만 보고 걸러내지 않고 우선순위만 매겨요)
        #   2) Mouser 직링크(.pdf), 3) DigiKey 직링크(.pdf) - 실제로 겪어보니 DDG가 이 두 사이트에서
        #      찾아주는 링크는 거의 항상 ProductDetail류 "상품 소개 페이지"였고, 그건 봇 차단(403)이
        #      analog.com만큼이나 확실했어요. 그래서 진짜 .pdf 직링크일 때만 우선순위를 올리고,
        #      상품 페이지는 그냥 5)로 취급해요 - 앞자리를 괜히 낭비하지 않게.
        #   4) 그 외 .pdf 확장자, 5) 나머지(상품 소개 페이지, 애그리게이터 등)
        #   6) 이미 차단이 확인된 도메인(KNOWN_BLOCKED_DOMAINS) - 맨 마지막. 완전히 빼지는 않되,
        #      _try_candidates가 이 등급은 20초로 시간을 짧게 잘라요.
        # 실제 PDF인지 최종 판단은 언제나 _download_once가 응답 바이트를 보고 해요.
        u_lower = u.lower()
        if _is_known_blocked(u_lower):
            return 6
        official = _looks_official(u, tokens, acronym)
        is_pdf = u_lower.endswith(".pdf")
        if official and is_pdf:
            return 0
        if official:
            return 1
        if "mouser.com" in u_lower and is_pdf:
            return 2
        if "digikey.com" in u_lower and is_pdf:
            return 3
        if is_pdf:
            return 4
        return 5

    candidates = sorted(urls, key=priority)
    return {"candidates": candidates}


# ---- 전체 흐름을 하나로 묶는 함수 (main.py/워커가 이 함수 하나만 부르면 돼요) ----


def download_datasheet_for_part(
    part_number: str, manufacturer_hint: str | None, mouser_client: MouserClient
) -> DownloadResult:
    """부품 하나에 대해 ① 이미 있는지 확인 -> ② Mouser -> ③ 웹 검색 순서로 데이터시트를 받아온다."""
    manufacturer = manufacturer_hint
    dest = dest_path_for_part(part_number)

    # ① 이미 받아둔 파일이 있으면 그냥 스킵해요 (평평한 자리든, 이미 분석돼 분류 폴더로 옮겨진 자리든).
    existing = resolve_existing_pdf(part_number)
    if existing is not None:
        return DownloadResult(STATUS_SKIPPED_EXISTING, existing.name, None, manufacturer)

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

    if result and result.get("datasheet_url"):
        fail_reason = download_pdf(result["datasheet_url"], dest)
        if fail_reason is None:
            return DownloadResult(STATUS_SUCCESS_MOUSER, dest.name, None, manufacturer)

    # ③ 웹(DuckDuckGo) 검색으로 보완
    try:
        web_result = find_datasheet(part_number, manufacturer)
    except Exception as e:
        # 검색 자체가 오류로 실패해도(네트워크 문제 등) 후보 링크가 하나도 없으니, Mouser 자체
        # 검색 링크를 참고 링크로 남겨요(사용자 확정, 2026-09-03 - 아래 "찾지 못함" 케이스와 동일).
        return DownloadResult(
            STATUS_FAILED,
            None,
            f"웹 검색 오류: {e}",
            manufacturer,
            _reference_url_with_distributor_fallback(part_number, manufacturer),
        )

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

    # 후보 링크를 단 하나도 못 찾은 경우(DuckDuckGo 검색 결과 자체가 0개 등) - "찾지 못함"이라고만
    # 하고 끝내면 사용자가 누를 게 아무것도 없어서, Mouser 자체 검색 링크를 대신 참고 링크로
    # 남겨요(사용자 확정, 2026-09-03 - T495C107K010ATE100 사례에서 이 경로가 링크 없이 끝나는 걸
    # 확인함).
    reason = mouser_error or "Mouser/웹 모두에서 찾지 못함"
    if _ddg_is_blocked():
        reason += " (DuckDuckGo 연결 불안정으로 이번엔 건너뜀 - Mouser 검색 링크로 대신 안내)"
    return DownloadResult(
        STATUS_FAILED, None, reason, manufacturer, _reference_url_with_distributor_fallback(part_number, manufacturer)
    )

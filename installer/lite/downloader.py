# 데이터시트를 실제로 찾아서 다운로드하는 파일이에요.
# [Lite 배포판] 순서: ① 이미 있으면 스킵 -> ② Mouser 검색+다운로드 -> ③ 실패하면 Mouser +
# DigiKey + 일반 구글 검색 참고 링크 3개를 남김(자동 다운로드/접속은 안 함 - 사람이 직접 눌러서
# 찾음).
#
# 이 파일은 원래(개발용) 버전에 있던 "③ 웹(DuckDuckGo) 검색으로 보완" 단계를 통째로 뺀 버전이에요
# (2026-09-04, Lite 배포판 전용). DuckDuckGo를 자동으로 두드리다가 실제로 IP가 차단된 사고가
# 있었어서(원본 CLAUDE.md 결정 로그 참고), 불특정 다수에게 배포하는 이 버전에서는 그 위험을 아예
# 없애기로 함 - Mouser 공식 API만 쓰고, 그걸로 못 찾으면 자동으로 다른 곳을 뒤지지 않고 사람이
# 직접 찾아보도록 참고 링크만 안내해요.

import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

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
# Mouser API가 알려주는 정확한 PDF 직링크 하나를 받는 용도예요(불특정 다수 사이트를 검색/탐색하는
# 게 아니라, 이미 Mouser가 "이 URL이 그 부품의 데이터시트다"라고 알려준 링크 하나를 그대로
# 가져오는 것 - 봇 차단 위험이 있는 자동 검색과는 성격이 달라요). curl_cffi(가짜 브라우저 흉내)
# 로는 Akamai가 강하게 막는 사이트(analog.com 등)를 못 뚫어서, StealthyFetcher(실제 브라우저)를
# 써요 - 대신 매 요청마다 브라우저를 띄우고 닫으므로 느려요(요청 1건에 몇 초씩 걸릴 수 있어요).

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


# ---- 참고 링크(자동 접속 없음) ----
#
# Mouser API로 못 찾으면, 자동으로 다른 곳을 검색/스크래핑하지 않고(Lite 배포판의 핵심 차이점),
# Mouser·DigiKey 자체 검색 페이지와 구글 검색 결과로 바로 연결되는 링크 3개를 만들어서 사람이
# 직접 눌러보게 안내해요. 이 함수들은 URL 문자열만 만들 뿐 실제로 그 사이트에 접속하지
# 않아요(스크래핑/자동 접속 없음) - 그래서 봇 차단 위험 자체가 없어요.


def _general_search_url(part_number: str, manufacturer: str | None) -> str:
    query = f"{manufacturer} {part_number} datasheet" if manufacturer else f"{part_number} datasheet"
    return "https://www.google.com/search?" + urlencode({"q": query})


def _mouser_search_url(part_number: str) -> str:
    """Mouser 자체 검색 결과 페이지 링크를 만들어요. 실제로 접속해서 확인하지는 않아요(사람이
    직접 눌러서 봄) - 그래서 이 부품을 Mouser가 취급하는지는 사람이 눌러봐야 알 수 있어요."""
    return "https://www.mouser.com/c/?" + urlencode({"q": part_number})


def _digikey_search_url(part_number: str) -> str:
    """DigiKey 자체 검색 결과 페이지 링크예요. Mouser와 마찬가지로 실제 접속은 안 해요."""
    return "https://www.digikey.com/en/products/result?" + urlencode({"keywords": part_number})


def _reference_url_with_distributor_fallback(part_number: str, manufacturer: str | None) -> str:
    """참고 링크로 Mouser·DigiKey 검색 링크와 일반 구글 검색 링크까지 셋 다 줘요 - 한 품번을
    Mouser는 안 팔고 DigiKey는 파는(또는 반대) 경우가 있고, 둘 다 없으면 구글로 더 폭넓게
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


def download_datasheet_for_part(
    part_number: str, manufacturer_hint: str | None, mouser_client: MouserClient
) -> DownloadResult:
    """부품 하나에 대해 ① 이미 있는지 확인 -> ② Mouser 검색+다운로드 순서로 데이터시트를 받아온다.
    [Lite 배포판] Mouser에 없거나 다운로드에 실패하면, 자동으로 다른 사이트를 뒤지지 않고(웹
    검색/스크래핑 기능 자체가 이 배포판엔 없음) Mouser/DigiKey/구글 검색 참고 링크 3개를 남겨서
    사람이 직접 찾도록 안내한다."""
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

    # ③ Mouser로 못 찾았으면(또는 다운로드 실패), 참고 링크 3개를 남기고 끝내요 - 웹 검색/
    # 스크래핑은 하지 않아요(Lite 배포판의 핵심 차이점).
    reason = mouser_error or "Mouser에서 찾지 못함"
    return DownloadResult(
        STATUS_FAILED, None, reason, manufacturer, _reference_url_with_distributor_fallback(part_number, manufacturer)
    )

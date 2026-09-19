# DigiKey 홈페이지에 "이 부품 정보 있어요?" 하고 전화(API 요청)를 거는 파일이에요.
# datasheet/search.py의 MouserClient와 역할은 같지만, DigiKey는 API 키 하나가 아니라
# OAuth2 client_credentials 방식(Client ID + Client Secret으로 토큰을 먼저 발급받아야 함)이라
# 별도 파일로 뒀어요(2026-09-19 도입 - Mouser 실패 후 DDG 웹검색으로 가기 전에 한 단계 더
# 끼워 넣는 보조 다운로드 경로, docs/superpowers/specs/2026-09-19-digikey-api-download-design.md
# 참고).
#
# DigiKey 개발자 포털에서 이 앱이 "Production" 승인을 받아야 실제 부품 데이터가 나와요(승인 전엔
# sandbox-api.digikey.com에서 고정된 더미 데이터만 돌려줌) - 이 프로젝트는 Production 승인
# 완료 상태라 api.digikey.com(운영 서버)으로 요청해요.

import time

import requests

from datasheet.search import normalize_part_number
from utils.config import USER_API_DIR, get_digikey_client_id, get_digikey_client_secret

TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
KEYWORD_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"

# 토큰이 만료되기 이 시간 전부터는 재사용하지 않고 미리 새로 받아요 - 발급 직후 바로 써도 서버와의
# 시계 오차 등으로 "이미 만료됨" 응답을 받는 걸 막기 위한 여유예요.
_TOKEN_EXPIRY_BUFFER_SECONDS = 30


class DigiKeyClient:
    """이 클래스를 하나 만들면, DigiKey한테 여러 번 물어볼 수 있는 "전화기"가 하나 생기는 셈이에요.
    MouserClient와 달리 검색 한 번 하기 전에 OAuth2 토큰을 먼저 발급받아야 하는데, 이 토큰은
    인스턴스 안에 캐시해뒀다가 만료 직전에만 새로 받아요(배치 하나에 토큰 발급을 한 번만 하면
    충분 - 토큰 수명이 약 10분이라 웬만한 배치는 그 안에 끝나요)."""

    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        # 매번 새로 읽어요(캐시된 값을 안 씀) - "API 키 관리" 창에서 값을 고친 직후에도 다음
        # 배치부터는 바로 새 값으로 동작하게 하기 위해서예요(MouserClient와 동일한 이유).
        self.client_id = client_id or get_digikey_client_id()
        self.client_secret = client_secret or get_digikey_client_secret()
        if not self.client_id or not self.client_secret:
            raise ValueError(
                f"DIGIKEY_CLIENT_ID/DIGIKEY_CLIENT_SECRET를 찾을 수 없습니다. {USER_API_DIR} 안의 파일을 확인하세요."
            )
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def _ensure_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - _TOKEN_EXPIRY_BUFFER_SECONDS:
            return self._access_token

        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"DigiKey 토큰 발급 응답에 access_token이 없습니다: {data}")

        self._access_token = token
        self._token_expires_at = time.time() + float(data.get("expires_in", 600))
        return token

    def _search_once(self, keyword: str) -> list[dict]:
        # DigiKey API를 한 번 호출해서 원문 그대로의 부품 목록을 돌려줘요(매칭/선별은 호출한 쪽에서).
        token = self._ensure_token()
        resp = requests.post(
            KEYWORD_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-DIGIKEY-Client-Id": self.client_id,
                "X-DIGIKEY-Locale-Site": "US",
                "X-DIGIKEY-Locale-Language": "en",
                "X-DIGIKEY-Locale-Currency": "USD",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"Keywords": keyword, "Limit": 10, "Offset": 0},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("Products") or []

    @staticmethod
    def _pick_exact_match(parts: list[dict], target_norm: str, manufacturer_hint: str | None) -> dict | None:
        # 정확히 일치하는 것만 인정해요(엉뚱한 부품을 잘못 고르는 사고를 막기 위해). 비교는 항상
        # 특수문자를 뺀 순수 영숫자 형태로 해요(MouserClient._pick_exact_match와 같은 이유 -
        # 구두점 표기 차이만으로 같은 부품을 놓치지 않기 위해서, 대소문자도 무시). DigiKey 응답
        # 필드 이름이 Mouser와 달라서(ManufacturerProductNumber, Manufacturer는
        # {"Id":.., "Name":..} 객체 - 실제 라이브 응답으로 확인함, 2026-09-19) 로직만 똑같이
        # 다시 구현해요.
        exact = [
            p for p in parts
            if normalize_part_number((p.get("ManufacturerProductNumber") or "")).lower() == target_norm
        ]
        if not exact:
            return None

        best = exact[0]
        if manufacturer_hint:
            hint = manufacturer_hint.strip().lower()
            preferred = next(
                (p for p in exact if hint in ((p.get("Manufacturer") or {}).get("Name") or "").strip().lower()),
                None,
            )
            if preferred:
                best = preferred
        return best

    def search_part(self, part_number: str, manufacturer_hint: str | None = None) -> dict | None:
        """부품번호로 DigiKey 키워드 검색을 수행하고 가장 일치하는 부품 정보를 반환해요.
        검색 결과가 없으면 None을 반환해요. manufacturer_hint를 주면, 같은 품번을 여러 제조사가
        쓰는 경우 그 제조사와 일치하는 것을 우선 선택해요.

        원본 품번으로 정확히 일치하는 결과가 없으면, 특수문자를 뺀 순수 영숫자 형태로 한 번 더
        검색해요(MouserClient.search_part와 동일한 재시도 규칙).

        반환값은 downloader.py가 Mouser/DigiKey를 같은 방식으로 다룰 수 있도록 MouserClient의
        search_part()와 같은 키 이름을 써요(product_detail_url은 없음 - DigiKey 키워드 검색
        응답은 DatasheetUrl을 바로 주므로 Mouser처럼 상세페이지를 스크레이핑해 보완할 필요가
        없어요)."""
        target_norm = normalize_part_number(part_number).lower()

        parts = self._search_once(part_number)
        best = self._pick_exact_match(parts, target_norm, manufacturer_hint)

        if best is None:
            normalized = normalize_part_number(part_number)
            if normalized and normalized.lower() != part_number.strip().lower():
                parts = self._search_once(normalized)
                best = self._pick_exact_match(parts, target_norm, manufacturer_hint)

        if best is None:
            return None

        manufacturer = (best.get("Manufacturer") or {}).get("Name")
        return {
            "manufacturer_part_number": best.get("ManufacturerProductNumber"),
            "manufacturer": manufacturer,
            "datasheet_url": best.get("DatasheetUrl") or None,
            "description": (best.get("Description") or {}).get("ProductDescription"),
            "digikey_part_number": best.get("ProductVariations", [{}])[0].get("DigiKeyProductNumber")
            if best.get("ProductVariations")
            else None,
        }

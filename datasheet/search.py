# Mouser 홈페이지에 "이 부품 정보 있어요?" 하고 전화(API 요청)를 거는 파일이에요.

import re

import requests

from utils.config import USER_API_DIR, get_mouser_api_key

# Mouser에게 "부품 찾아줘"라고 물어볼 때 사용하는 주소(전화번호 같은 것)
MOUSER_SEARCH_URL = "https://api.mouser.com/api/v1/search/keyword"

# 특수문자(하이픈/슬래시/공백 등)만 제거하고 영문·숫자만 남겨요(2026-09-05 도입, 다운로드 실패율
# 낮추기 요청) - Mouser 카탈로그의 실제 표기가 우리 입력지의 품번과 구두점만 다른 경우(예:
# "ABC-123" vs "ABC123")가 있어서, 원본으로 못 찾으면 이 순수 영숫자 형태로 한 번 더 찾아봐요.
# 이름 앞에 밑줄이 없어요(공개 함수) - datasheet/digikey_search.py도 같은 정규화 규칙을 그대로
# 재사용해요(2026-09-19 도입, DigiKey API 추가) - 유통사가 달라도 "품번 표기 구두점 차이" 문제는
# 똑같아서 로직을 하나만 두고 같이 써요.
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")


def normalize_part_number(part_number: str) -> str:
    return _NON_ALNUM_RE.sub("", part_number)


class MouserClient:
    # 이 클래스를 하나 만들면, Mouser한테 여러 번 물어볼 수 있는 "전화기"가 하나 생기는 셈이에요.
    def __init__(self, api_key: str | None = None):
        # 매번 새로 읽어요(캐시된 값을 안 씀) - "API 키 관리" 창에서 값을 고친 직후에도 프로그램을
        # 재시작하지 않고 바로 새 키로 동작하게 하기 위해서예요.
        self.api_key = api_key or get_mouser_api_key()
        if not self.api_key:
            raise ValueError(f"MOUSER_API_KEY를 찾을 수 없습니다. {USER_API_DIR} 안의 파일을 확인하세요.")

    def _search_once(self, keyword: str) -> list[dict]:
        # Mouser API를 한 번 호출해서 원문 그대로의 부품 목록을 돌려줘요(매칭/선별은 호출한 쪽에서).
        body = {
            "SearchByKeywordRequest": {
                "keyword": keyword,
                "records": 50,
                "startingRecord": 0,
                "searchOptions": "",
                "searchWithYourSignUpLanguage": "",
            }
        }
        resp = requests.post(
            MOUSER_SEARCH_URL,
            params={"apiKey": self.api_key},
            json=body,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        errors = data.get("Errors") or []
        if errors:
            messages = "; ".join(e.get("Message", str(e)) for e in errors)
            raise RuntimeError(f"Mouser API 오류: {messages}")

        return (data.get("SearchResults") or {}).get("Parts") or []

    @staticmethod
    def _pick_exact_match(parts: list[dict], target_norm: str, manufacturer_hint: str | None) -> dict | None:
        # 정확히 일치하는 것만 인정해요 (엉뚱한 부품을 잘못 고르는 사고를 막기 위해). 비교는 항상
        # 특수문자를 뺀 순수 영숫자 형태로 해요 - 구두점 표기 차이(하이픈 유무 등)만으로 같은
        # 부품을 놓치지 않기 위해서예요(대소문자도 무시).
        exact = [
            p for p in parts
            if normalize_part_number((p.get("ManufacturerPartNumber") or "")).lower() == target_norm
        ]
        if not exact:
            return None

        best = exact[0]
        if manufacturer_hint:
            hint = manufacturer_hint.strip().lower()
            preferred = next(
                (p for p in exact if hint in (p.get("Manufacturer") or "").strip().lower()), None
            )
            if preferred:
                best = preferred
        return best

    def search_part(self, part_number: str, manufacturer_hint: str | None = None) -> dict | None:
        """부품번호로 Mouser 키워드 검색을 수행하고 가장 일치하는 부품 정보를 반환한다.
        검색 결과가 없으면 None을 반환한다.
        manufacturer_hint를 주면, 같은 품번을 여러 제조사가 쓰는 경우 그 제조사와 일치하는 것을 우선 선택한다.

        원본 품번으로 정확히 일치하는 결과가 없으면, 특수문자(하이픈/슬래시/공백 등)를 뺀 순수
        영숫자 형태로 한 번 더 검색해요(2026-09-05 도입, 다운로드 실패율을 낮추기 위한 재시도).
        """
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

        return {
            "manufacturer_part_number": best.get("ManufacturerPartNumber"),
            "manufacturer": best.get("Manufacturer"),
            "datasheet_url": best.get("DataSheetUrl") or None,
            "product_detail_url": best.get("ProductDetailUrl") or None,
            "description": best.get("Description"),
            "mouser_part_number": best.get("MouserPartNumber"),
        }

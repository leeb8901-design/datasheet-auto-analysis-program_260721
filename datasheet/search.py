# Mouser 홈페이지에 "이 부품 정보 있어요?" 하고 전화(API 요청)를 거는 파일이에요.

import requests

from utils.config import MOUSER_API_KEY

# Mouser에게 "부품 찾아줘"라고 물어볼 때 사용하는 주소(전화번호 같은 것)
MOUSER_SEARCH_URL = "https://api.mouser.com/api/v1/search/keyword"


class MouserClient:
    # 이 클래스를 하나 만들면, Mouser한테 여러 번 물어볼 수 있는 "전화기"가 하나 생기는 셈이에요.
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or MOUSER_API_KEY
        if not self.api_key:
            raise ValueError("MOUSER_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

    def search_part(self, part_number: str, manufacturer_hint: str | None = None) -> dict | None:
        """부품번호로 Mouser 키워드 검색을 수행하고 가장 일치하는 부품 정보를 반환한다.
        검색 결과가 없으면 None을 반환한다.
        manufacturer_hint를 주면, 같은 품번을 여러 제조사가 쓰는 경우 그 제조사와 일치하는 것을 우선 선택한다.
        """
        body = {
            "SearchByKeywordRequest": {
                "keyword": part_number,
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

        parts = (data.get("SearchResults") or {}).get("Parts") or []
        if not parts:
            return None

        # 정확히 일치하는 것만 인정해요 (엉뚱한 부품을 잘못 고르는 사고를 막기 위해).
        target = part_number.strip().lower()
        exact = [p for p in parts if (p.get("ManufacturerPartNumber") or "").strip().lower() == target]
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

        return {
            "manufacturer_part_number": best.get("ManufacturerPartNumber"),
            "manufacturer": best.get("Manufacturer"),
            "datasheet_url": best.get("DataSheetUrl") or None,
            "description": best.get("Description"),
            "mouser_part_number": best.get("MouserPartNumber"),
        }

# 오픈소스 라이선스 고지 (Third-Party Notices)

> 이 프로그램(데이터시트 다운로더)은 아래 오픈소스 패키지를 사용합니다. 각 패키지는 자신의 라이선스 조건에 따라 배포됩니다. 이 목록은 `pip show`/`importlib.metadata`로 실제 설치된 가상환경(`.venv`)에서 자동 생성했습니다(생성일 2026-09-15, 보안점검 문서 4번 항목).

| 패키지 | 버전 | 라이선스 | 홈페이지 |
|---|---|---|---|
| anyio | 4.14.2 | MIT | https://github.com/agronholm/anyio |
| apify_fingerprint_datapoints | 0.15.0 | Apache License | https://docs.apify.com/academy/anti-scraping/techniques/fingerprinting |
| beautifulsoup4 | 4.15.0 | MIT License | https://www.crummy.com/software/BeautifulSoup/bs4/ |
| browserforge | 1.2.4 | Apache-2.0 | https://github.com/daijro/browserforge |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi/releases |
| charset-normalizer | 3.5.0 | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| click | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click/ |
| colorama | 0.4.6 | BSD-3-Clause | https://github.com/tartley/colorama |
| cryptography | 50.0.0 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| cssselect | 1.5.0 | BSD-3-Clause | https://github.com/scrapy/cssselect |
| curl_cffi | 0.16.0 | MIT | https://github.com/lexiforest/curl_cffi |
| et_xmlfile | 2.0.0 | MIT | https://foss.heptapod.net/openpyxl/et_xmlfile |
| greenlet | 3.5.5 | MIT AND PSF-2.0 | https://greenlet.readthedocs.io |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna/blob/master/HISTORY.md |
| lxml | 6.1.1 | BSD-3-Clause | https://lxml.de/ |
| msgspec | 0.21.1 | BSD-3-Clause | https://jcristharif.com/msgspec/ |
| openpyxl | 3.1.5 | MIT | https://openpyxl.readthedocs.io |
| orjson | 3.12.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | https://github.com/ijl/orjson/blob/master/CHANGELOG.md |
| patchright | 1.61.2 | Apache-2.0 | https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python |
| pdfminer.six | 20260107 | MIT | https://github.com/pdfminer/pdfminer.six |
| pdfplumber | 0.11.10 | MIT | https://github.com/jsvine/pdfplumber |
| pillow | 12.3.0 | MIT-CMU | https://github.com/python-pillow/Pillow/releases |
| playwright | 1.62.0 | Apache-2.0 | https://github.com/Microsoft/playwright-python |
| Protego | 0.6.2 | BSD-3-Clause | https://github.com/scrapy/protego |
| pycparser | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pyee | 13.0.1 | MIT | https://github.com/jfhbrook/pyee |
| pymupdf | 1.28.2 | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License | https://github.com/pymupdf/pymupdf |
| pypdfium2 | 5.13.0 | BSD-3-Clause, Apache-2.0, dependency licenses | https://github.com/pypdfium2-team/pypdfium2 |
| PySide6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Addons | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Essentials | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| scrapling | 0.4.14 | BSD 3-Clause License | https://github.com/D4Vinci/Scrapling |
| shiboken6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| soupsieve | 2.9.2 | MIT | https://github.com/facelessuser/soupsieve |
| tld | 0.13.2 | MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later | https://github.com/barseghyanartur/tld/issues |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions/issues |
| urllib3 | 2.7.0 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| w3lib | 2.4.1 | BSD-3-Clause | https://github.com/scrapy/w3lib |

## 특히 확인이 필요한 라이선스

- **PyMuPDF (`pymupdf`)** — GNU AFFERO GPL 3.0 또는 Artifex 상용 라이선스 중 택1. 무료/폐쇄형으로 배포한다면 상용 라이선스 구매 또는 AGPL 조건 충족(소스 공개 등) 검토 필요.
- **PySide6 / PySide6_Addons / PySide6_Essentials / shiboken6** — LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only. 동적 링크(현재 pip 표준 설치 방식) 유지 + 이 고지문 동봉으로 LGPL 조건을 충족하는 것을 목표로 함.
- **tld**(scrapling 하위 의존성) — MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later 3중 라이선스 중 가장 관대한 MPL-1.1 조건으로 사용함을 명시.

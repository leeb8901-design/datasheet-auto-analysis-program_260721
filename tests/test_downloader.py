from datasheet import downloader


def test_find_datasheet_returns_distinct_landing_page(monkeypatch):
    urls = [
        "https://www.analog.com/media/en/technical-documentation/data-sheets/AD8029_8030_8040.pdf",
        "https://www.analog.com/en/products/ad8030.html",
        "https://someblog.example.com/ad8030-review",
    ]
    monkeypatch.setattr(downloader, "search_datasheet_urls", lambda *a, **k: urls)

    result = downloader.find_datasheet("AD8030ARZ", manufacturer="Analog Devices")

    assert result["datasheet_url"] == urls[0]
    assert result["landing_page"] == "https://www.analog.com/en/products/ad8030.html"
    assert result["official"] is True


def test_find_datasheet_no_pdf_found_falls_back_to_first_page(monkeypatch):
    urls = ["https://www.ti.com/product/TL072", "https://example.com/other"]
    monkeypatch.setattr(downloader, "search_datasheet_urls", lambda *a, **k: urls)

    result = downloader.find_datasheet("TL072", manufacturer="Texas Instruments")

    assert result["datasheet_url"] is None
    assert result["landing_page"] == "https://www.ti.com/product/TL072"
    assert result["official"] is False


def test_find_datasheet_no_official_landing_page_falls_back_to_first_page_url(monkeypatch):
    urls = ["https://unofficial-blog.example.com/x.pdf", "https://unofficial-blog.example.com/x"]
    monkeypatch.setattr(downloader, "search_datasheet_urls", lambda *a, **k: urls)

    result = downloader.find_datasheet("X123", manufacturer="Analog Devices")

    assert result["datasheet_url"] == urls[0]
    assert result["landing_page"] == "https://unofficial-blog.example.com/x"
    assert result["official"] is False


def test_find_datasheet_no_search_results_returns_none(monkeypatch):
    monkeypatch.setattr(downloader, "search_datasheet_urls", lambda *a, **k: [])

    assert downloader.find_datasheet("XYZ999") is None


class _StubMouser:
    def __init__(self, result=None):
        self._result = result

    def search_part(self, part_number, manufacturer_hint=None):
        return self._result


def test_download_datasheet_for_part_sets_landing_url_on_web_download_failure(monkeypatch, tmp_path):
    downloader.set_download_dir(tmp_path)
    monkeypatch.setattr(downloader, "download_pdf", lambda url, dest, max_retries=3: "HTTP 403")
    monkeypatch.setattr(
        downloader,
        "find_datasheet",
        lambda part, manufacturer=None, max_results=10: {
            "datasheet_url": "https://www.analog.com/blocked.pdf",
            "landing_page": "https://www.analog.com/en/products/ad8030.html",
            "official": True,
        },
    )

    result = downloader.download_datasheet_for_part("AD8030ARZ", None, _StubMouser())

    assert result.status == downloader.STATUS_FAILED
    assert result.reference_url == "https://www.analog.com/blocked.pdf"
    assert result.landing_url == "https://www.analog.com/en/products/ad8030.html"


def test_download_datasheet_for_part_falls_back_to_landing_page_when_no_pdf_found(monkeypatch, tmp_path):
    downloader.set_download_dir(tmp_path)
    monkeypatch.setattr(
        downloader,
        "find_datasheet",
        lambda part, manufacturer=None, max_results=10: {
            "datasheet_url": None,
            "landing_page": "https://www.ti.com/product/TL072",
            "official": False,
        },
    )

    result = downloader.download_datasheet_for_part("TL072", "Texas Instruments", _StubMouser())

    assert result.status == downloader.STATUS_FAILED
    assert result.error == "PDF 직링크를 찾지 못함"
    assert result.reference_url == "https://www.ti.com/product/TL072"
    assert result.landing_url == "https://www.ti.com/product/TL072"


def test_download_datasheet_for_part_mouser_success_has_no_landing_url(monkeypatch, tmp_path):
    downloader.set_download_dir(tmp_path)
    monkeypatch.setattr(downloader, "download_pdf", lambda url, dest, max_retries=3: None)

    result = downloader.download_datasheet_for_part(
        "NL27WZ08USG-Q",
        None,
        _StubMouser(result={"manufacturer": "onsemi", "datasheet_url": "https://www.onsemi.com/x.pdf"}),
    )

    assert result.status == downloader.STATUS_SUCCESS_MOUSER
    assert result.landing_url is None

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

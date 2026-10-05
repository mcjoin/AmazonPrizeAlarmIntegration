"""Tests for the HA independent scraper module (run with: pytest tests)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

_PATH = (
    Path(__file__).parents[1] / "custom_components" / "amazon_preisalarm" / "scraper.py"
)
_spec = importlib.util.spec_from_file_location("amazon_scraper", _PATH)
scraper = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = scraper
_spec.loader.exec_module(scraper)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("29,99 €", 29.99),
        ("1.299,99 €", 1299.99),
        ("$1,299.99", 1299.99),
        ("£15.00", 15.0),
        ("1.299 €", 1299.0),
        ("12 €", 12.0),
        ("EUR 0,99", 0.99),
        ("", None),
        ("Derzeit nicht verfügbar", None),
    ],
)
def test_parse_price(text: str, expected: float | None) -> None:
    assert scraper.parse_price(text) == expected


@pytest.mark.parametrize(
    ("url", "domain", "asin"),
    [
        ("https://www.amazon.de/dp/B0BSHF7WHW", "amazon.de", "B0BSHF7WHW"),
        (
            "https://www.amazon.de/Some-Product-Name/dp/B0BSHF7WHW/ref=sr_1_1?keywords=x",
            "amazon.de",
            "B0BSHF7WHW",
        ),
        ("https://amazon.co.uk/gp/product/b0bshf7whw?psc=1", "amazon.co.uk", "B0BSHF7WHW"),
        ("amazon.com/gp/aw/d/B0BSHF7WHW", "amazon.com", "B0BSHF7WHW"),
        ("https://www.amazon.com.au/dp/B0BSHF7WHW", "amazon.com.au", "B0BSHF7WHW"),
    ],
)
def test_parse_product_url(url: str, domain: str, asin: str) -> None:
    ref = scraper.parse_product_url(url)
    assert ref == scraper.ProductRef(domain=domain, asin=asin)


@pytest.mark.parametrize(
    "url",
    ["https://www.google.de/dp/B0BSHF7WHW", "https://www.amazon.de/s?k=foo", "amzn.eu/d/abc"],
)
def test_parse_product_url_invalid(url: str) -> None:
    assert scraper.parse_product_url(url) is None


def test_currency() -> None:
    assert scraper.ProductRef("amazon.de", "B0BSHF7WHW").currency == "EUR"
    assert scraper.ProductRef("amazon.co.uk", "B0BSHF7WHW").currency == "GBP"


PRODUCT_PAGE = """
<html><body>
<span id="productTitle">  Tolles Produkt, 2er Pack  </span>
<div id="corePriceDisplay_desktop_feature_div">
  <span class="a-price a-text-price"><span class="a-offscreen">59,99 €</span></span>
  <span class="a-price priceToPay"><span class="a-offscreen">44,90 €</span>
    <span class="a-price-whole">44,</span><span class="a-price-fraction">90</span></span>
</div>
<div id="availability"><span>Auf Lager</span></div>
<img id="landingImage" data-old-hires="https://m.media-amazon.com/images/I/x.jpg" src="data:image/gif;base64,xx">
</body></html>
"""


def test_parse_product_page() -> None:
    info = scraper.parse_product_page(PRODUCT_PAGE)
    assert info.title == "Tolles Produkt, 2er Pack"
    assert info.price == 44.90
    assert info.availability == "Auf Lager"
    assert info.image == "https://m.media-amazon.com/images/I/x.jpg"


def test_parse_whole_fraction_fallback() -> None:
    html = """<span id="productTitle">X</span>
    <div id="corePriceDisplay_desktop_feature_div"><span class="a-price priceToPay">
    <span class="a-price-whole">1.299,</span><span class="a-price-fraction">00</span></span></div>"""
    assert scraper.parse_product_page(html).price == 1299.0


def test_parse_out_of_stock() -> None:
    html = (
        '<span id="productTitle">X ​​</span>'
        '<div id="availability">Derzeit nicht verfügbar.</div>'
    )
    info = scraper.parse_product_page(html)
    assert info.title == "X"
    assert info.price is None
    assert info.availability == "Derzeit nicht verfügbar."


def test_captcha_detected() -> None:
    html = '<form action="/errors/validateCaptcha"><input id="captchacharacters"></form>'
    with pytest.raises(scraper.AmazonBlockedError):
        scraper.parse_product_page(html)


def test_unknown_page() -> None:
    with pytest.raises(scraper.AmazonParseError):
        scraper.parse_product_page("<html><body>Hallo</body></html>")

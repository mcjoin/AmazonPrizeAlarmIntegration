"""Fetch and parse Amazon product pages.

This module only depends on aiohttp and BeautifulSoup so it can be tested
without Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)

ASIN_RE = re.compile(
    r"/(?:dp|gp/product|gp/aw/d|gp/offer-listing|exec/obidos/asin|o/asin)"
    r"/([A-Z0-9]{10})(?=[/?#&]|$)",
    re.IGNORECASE,
)
AMAZON_HOST_RE = re.compile(r"(?:^|\.)(amazon\.(?:[a-z]{2,3}(?:\.[a-z]{2})?))$")
SHORT_LINK_HOSTS = {"amzn.eu", "amzn.to", "amzn.com", "amzn.asia", "a.co"}

CURRENCY_BY_DOMAIN = {
    "amazon.de": "EUR",
    "amazon.fr": "EUR",
    "amazon.it": "EUR",
    "amazon.es": "EUR",
    "amazon.nl": "EUR",
    "amazon.ie": "EUR",
    "amazon.com.be": "EUR",
    "amazon.co.uk": "GBP",
    "amazon.com": "USD",
    "amazon.ca": "CAD",
    "amazon.com.mx": "MXN",
    "amazon.com.br": "BRL",
    "amazon.com.au": "AUD",
    "amazon.co.jp": "JPY",
    "amazon.in": "INR",
    "amazon.pl": "PLN",
    "amazon.se": "SEK",
    "amazon.com.tr": "TRY",
    "amazon.ae": "AED",
    "amazon.sa": "SAR",
    "amazon.sg": "SGD",
    "amazon.eg": "EGP",
}

ACCEPT_LANGUAGE_BY_DOMAIN = {
    "amazon.de": "de-DE,de;q=0.9,en;q=0.8",
    "amazon.fr": "fr-FR,fr;q=0.9,en;q=0.8",
    "amazon.it": "it-IT,it;q=0.9,en;q=0.8",
    "amazon.es": "es-ES,es;q=0.9,en;q=0.8",
    "amazon.nl": "nl-NL,nl;q=0.9,en;q=0.8",
    "amazon.pl": "pl-PL,pl;q=0.9,en;q=0.8",
    "amazon.se": "sv-SE,sv;q=0.9,en;q=0.8",
}

CAPTCHA_MARKERS = (
    "/errors/validatecaptcha",
    "captchacharacters",
    "api-services-support@amazon.com",
)

# Ordered from most to least specific. Strike-through list prices
# (".a-text-price") are excluded on purpose.
PRICE_SELECTORS = (
    "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .priceToPay .aok-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price:not(.a-text-price) .a-offscreen",
    "#corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen",
    "#corePrice_desktop .a-price:not(.a-text-price) .a-offscreen",
    "#apex_desktop .priceToPay .a-offscreen",
    "#apex_desktop .a-price:not(.a-text-price) .a-offscreen",
    "#tp_price_block_total_price_ww .a-offscreen",
    "#priceblock_dealprice",
    "#priceblock_ourprice",
    "#priceblock_saleprice",
    "#price_inside_buybox",
    "#newBuyBoxPrice",
    "#kindle-price",
    "#buybox .a-price:not(.a-text-price) .a-offscreen",
)
WHOLE_FRACTION_SCOPES = (
    "#corePriceDisplay_desktop_feature_div .priceToPay",
    "#corePrice_feature_div .a-price:not(.a-text-price)",
    "#apex_desktop .a-price:not(.a-text-price)",
)
INVISIBLE_RE = re.compile(r"[​-‏⁠﻿]")
PRICE_AMOUNT_RE =re.compile(r'"priceAmount"\s*:\s*"?(\d+(?:\.\d+)?)')


class AmazonError(Exception):
    """Base error."""


class InvalidAmazonUrl(AmazonError):
    """The URL is not an Amazon product URL."""


class AmazonFetchError(AmazonError):
    """The page could not be fetched."""


class AmazonBlockedError(AmazonFetchError):
    """Amazon answered with a captcha / bot check."""


class AmazonParseError(AmazonError):
    """The page could not be interpreted as a product page."""


@dataclass(frozen=True)
class ProductRef:
    """Identifies a product on a specific Amazon marketplace."""

    domain: str
    asin: str

    @property
    def url(self) -> str:
        """Canonical product URL."""
        return f"https://www.{self.domain}/dp/{self.asin}"

    @property
    def currency(self) -> str:
        """Currency of the marketplace."""
        return CURRENCY_BY_DOMAIN.get(self.domain, "EUR")

    @property
    def unique_id(self) -> str:
        """Stable identifier."""
        return f"{self.domain}_{self.asin}"


@dataclass
class ProductInfo:
    """Result of parsing a product page."""

    title: str | None
    price: float | None
    image: str | None
    availability: str | None


def parse_product_url(url: str) -> ProductRef | None:
    """Extract marketplace and ASIN from a full Amazon URL."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    if not (host_match := AMAZON_HOST_RE.search(host)):
        return None
    if not (asin_match := ASIN_RE.search(parsed.path)):
        return None
    return ProductRef(domain=host_match.group(1), asin=asin_match.group(1).upper())


def _headers(domain: str | None) -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": ACCEPT_LANGUAGE_BY_DOMAIN.get(
            domain or "", "en-US,en;q=0.9"
        ),
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }


async def async_resolve_url(session: aiohttp.ClientSession, url: str) -> ProductRef:
    """Turn any Amazon product link (incl. short links) into a ProductRef."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = f"https://{url}"
    if ref := parse_product_url(url):
        return ref

    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host not in SHORT_LINK_HOSTS:
        raise InvalidAmazonUrl(url)

    try:
        async with session.get(
            url, headers=_headers(None), timeout=REQUEST_TIMEOUT, allow_redirects=True
        ) as resp:
            candidates = [str(r.url) for r in resp.history]
            candidates.append(str(resp.url))
            candidates.extend(
                r.headers.get("Location", "") for r in resp.history
            )
    except (aiohttp.ClientError, TimeoutError) as err:
        raise AmazonFetchError(f"Could not resolve short link: {err}") from err

    for candidate in candidates:
        if candidate and (ref := parse_product_url(candidate)):
            return ref
    raise InvalidAmazonUrl(url)


async def async_fetch_html(session: aiohttp.ClientSession, ref: ProductRef) -> str:
    """Download the product page."""
    try:
        async with session.get(
            f"{ref.url}?th=1&psc=1",
            headers=_headers(ref.domain),
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        ) as resp:
            if resp.status in (429, 503):
                raise AmazonBlockedError(f"HTTP {resp.status} (bot protection)")
            if resp.status == 404:
                raise AmazonFetchError("Product not found (HTTP 404)")
            if resp.status >= 400:
                raise AmazonFetchError(f"HTTP {resp.status}")
            return await resp.text(errors="replace")
    except (aiohttp.ClientError, TimeoutError) as err:
        raise AmazonFetchError(str(err)) from err


def parse_price(text: str | None) -> float | None:
    """Parse a localized price string like '1.299,99 €' or '$1,299.99'."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.,]", "", text).strip(".,")
    if not cleaned or not any(ch.isdigit() for ch in cleaned):
        return None
    last_sep = max(cleaned.rfind(","), cleaned.rfind("."))
    if last_sep == -1:
        return float(cleaned)
    integer = re.sub(r"[.,]", "", cleaned[:last_sep])
    decimals = cleaned[last_sep + 1 :]
    if len(decimals) == 3:
        # "1.299" / "1,299" -> thousands separator
        return float(f"{integer}{decimals}")
    return float(f"{integer or '0'}.{decimals}")


def _text(soup: BeautifulSoup, selector: str) -> str | None:
    if (element := soup.select_one(selector)) is None:
        return None
    text = INVISIBLE_RE.sub("", element.get_text(" ", strip=True)).strip()
    return text or None


def _find_price(soup: BeautifulSoup, html: str) -> float | None:
    for selector in PRICE_SELECTORS:
        if (price := parse_price(_text(soup, selector))) is not None and price > 0:
            return price

    for scope in WHOLE_FRACTION_SCOPES:
        whole = _text(soup, f"{scope} .a-price-whole")
        if whole:
            fraction = _text(soup, f"{scope} .a-price-fraction") or "00"
            whole_digits = re.sub(r"\D", "", whole)
            fraction_digits = re.sub(r"\D", "", fraction) or "00"
            if whole_digits:
                return float(f"{whole_digits}.{fraction_digits}")

    twister = soup.select_one("input#twister-plus-price-data-price")
    if twister is not None:
        try:
            if (value := float(str(twister.get("value", "")))) > 0:
                return value
        except ValueError:
            pass

    if match := PRICE_AMOUNT_RE.search(html):
        value = float(match.group(1))
        if value > 0:
            return value
    return None


def parse_product_page(html: str) -> ProductInfo:
    """Extract title, price and image from a product page (CPU bound)."""
    lowered = html.lower()
    if any(marker in lowered for marker in CAPTCHA_MARKERS):
        raise AmazonBlockedError("Captcha / bot check page received")

    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup, "#productTitle") or _text(soup, "#ebooksProductTitle")
    price = _find_price(soup, html)

    if title is None and price is None:
        raise AmazonParseError("Page does not look like a product page")

    image = None
    if (img := soup.select_one("#landingImage, #imgBlkFront, #ebooksImgBlkFront")) is not None:
        image = img.get("data-old-hires") or img.get("src")
        if image and str(image).startswith("data:"):
            image = None

    return ProductInfo(
        title=title,
        price=price,
        image=str(image) if image else None,
        availability=_text(soup, "#availability"),
    )

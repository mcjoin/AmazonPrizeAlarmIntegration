"""Update coordinator for Amazon Preisalarm."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import logging
import random
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ADDED_AT,
    CONF_AMAZON_DOMAIN,
    CONF_ASIN,
    CONF_INITIAL_PRICE,
    CONF_SCAN_INTERVAL,
    CONF_TARGET_PRICE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_PRICE_CHANGED,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    STORAGE_VERSION,
    SUBENTRY_TYPE_PRODUCT,
)
from .scraper import (
    AmazonBlockedError,
    AmazonError,
    ProductRef,
    async_fetch_html,
    parse_product_page,
)

_LOGGER = logging.getLogger(__name__)

type AmazonPreisalarmConfigEntry = ConfigEntry[AmazonPriceCoordinator]


@dataclass(frozen=True)
class Product:
    """Static configuration of a tracked product (from its subentry)."""

    subentry_id: str
    ref: ProductRef
    name: str
    target_price: float | None
    initial_price: float | None
    added_at: str | None

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> Product:
        """Build from a config subentry."""
        data = subentry.data
        return cls(
            subentry_id=subentry.subentry_id,
            ref=ProductRef(domain=data[CONF_AMAZON_DOMAIN], asin=data[CONF_ASIN]),
            name=subentry.title,
            target_price=data.get(CONF_TARGET_PRICE),
            initial_price=data.get(CONF_INITIAL_PRICE),
            added_at=data.get(CONF_ADDED_AT),
        )


@dataclass(frozen=True)
class ProductState:
    """Last known state of a product."""

    title: str | None = None
    price: float | None = None
    image: str | None = None
    availability: str | None = None
    last_checked: datetime | None = None
    last_success: datetime | None = None
    error: str | None = None


class AmazonPriceCoordinator(DataUpdateCoordinator[dict[str, ProductState]]):
    """Fetch the prices of all configured products."""

    config_entry: AmazonPreisalarmConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AmazonPreisalarmConfigEntry) -> None:
        """Initialize."""
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )
        self.products: dict[str, Product] = {
            subentry_id: Product.from_subentry(subentry)
            for subentry_id, subentry in entry.subentries.items()
            if subentry.subentry_type == SUBENTRY_TYPE_PRODUCT
        }
        # Own session with a cookie jar: Amazon is less suspicious of
        # clients that keep their session cookies.
        self.session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._stored: dict[str, dict[str, Any]] = {}
        self.data = {}

    async def async_load(self) -> None:
        """Load persisted reference prices and last known values."""
        stored = (await self._store.async_load() or {}).get("products", {})
        # Drop data of products that have been removed.
        self._stored = {sid: v for sid, v in stored.items() if sid in self.products}

        for sid, product in self.products.items():
            st = self._stored.setdefault(sid, {})
            if st.get("reference_price") is None and product.initial_price is not None:
                st["reference_price"] = product.initial_price
                st["reference_since"] = product.added_at or dt_util.utcnow().isoformat()

        self.data = {
            sid: ProductState(
                title=st.get("title"),
                price=st.get("last_price"),
                image=st.get("image"),
            )
            for sid, st in self._stored.items()
        }
        self._async_schedule_save()

    async def _async_update_data(self) -> dict[str, ProductState]:
        """Fetch all products one after another."""
        data = dict(self.data or {})
        successes = 0
        blocked = False

        for index, (sid, product) in enumerate(self.products.items()):
            previous = data.get(sid) or ProductState()
            now = dt_util.utcnow()

            if blocked:
                data[sid] = replace(
                    previous, last_checked=now, error="Skipped: Amazon bot protection"
                )
                continue
            if index:
                await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

            try:
                html = await async_fetch_html(self.session, product.ref)
                info = await self.hass.async_add_executor_job(parse_product_page, html)
            except AmazonError as err:
                _LOGGER.warning(
                    "Could not update %s (%s): %s", product.name, product.ref.asin, err
                )
                data[sid] = replace(previous, last_checked=now, error=str(err))
                if isinstance(err, AmazonBlockedError):
                    blocked = True
                continue

            successes += 1
            data[sid] = ProductState(
                title=info.title or previous.title,
                price=info.price,
                image=info.image or previous.image,
                availability=info.availability,
                last_checked=now,
                last_success=now,
                error=None if info.price is not None else "No price found",
            )
            self._process_new_price(product, data[sid])

        self._async_schedule_save()

        if self.products and not successes:
            raise UpdateFailed(
                "Amazon bot protection (captcha) is active, retrying next interval"
                if blocked
                else "No product could be updated"
            )
        return data

    def _process_new_price(self, product: Product, state: ProductState) -> None:
        """Persist the new price, set the reference if needed and fire events."""
        st = self._stored.setdefault(product.subentry_id, {})
        st["title"] = state.title
        st["image"] = state.image
        if (price := state.price) is None:
            return

        if st.get("reference_price") is None:
            st["reference_price"] = price
            st["reference_since"] = dt_util.utcnow().isoformat()

        last_price = st.get("last_price")
        st["last_price"] = price
        if last_price is None or round(last_price, 2) == round(price, 2):
            return

        reference = st["reference_price"]
        self.hass.bus.async_fire(
            EVENT_PRICE_CHANGED,
            {
                "config_entry_id": self.config_entry.entry_id,
                "subentry_id": product.subentry_id,
                "name": product.name,
                "title": state.title,
                "asin": product.ref.asin,
                "url": product.ref.url,
                "currency": product.ref.currency,
                "old_price": last_price,
                "new_price": price,
                "reference_price": reference,
                "change": round(price - reference, 2),
                "change_percent": _percent(price, reference),
                "direction": "down" if price < last_price else "up",
                "target_price": product.target_price,
                "target_reached": product.target_price is not None
                and price <= product.target_price,
            },
        )

    def reference(self, subentry_id: str) -> tuple[float | None, str | None]:
        """Return reference price and since when it is valid."""
        st = self._stored.get(subentry_id, {})
        return st.get("reference_price"), st.get("reference_since")

    def price(self, subentry_id: str) -> float | None:
        """Current price."""
        state = self.data.get(subentry_id)
        return state.price if state else None

    def change(self, subentry_id: str) -> float | None:
        """Absolute change vs. the reference price."""
        price = self.price(subentry_id)
        reference, _ = self.reference(subentry_id)
        if price is None or reference is None:
            return None
        return round(price - reference, 2)

    def change_percent(self, subentry_id: str) -> float | None:
        """Relative change vs. the reference price in percent."""
        price = self.price(subentry_id)
        reference, _ = self.reference(subentry_id)
        if price is None or reference is None:
            return None
        return _percent(price, reference)

    async def async_reset_reference(self, subentry_id: str) -> None:
        """Use the current price as new reference price."""
        if (price := self.price(subentry_id)) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_current_price"
            )
        st = self._stored.setdefault(subentry_id, {})
        st["reference_price"] = price
        st["reference_since"] = dt_util.utcnow().isoformat()
        await self._store.async_save(self._data_to_save())
        self.async_update_listeners()

    def _data_to_save(self) -> dict[str, Any]:
        return {"products": self._stored}

    def _async_schedule_save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 5)


def _percent(price: float, reference: float) -> float | None:
    if not reference:
        return None
    return round((price - reference) / reference * 100, 2)

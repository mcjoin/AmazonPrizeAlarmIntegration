"""Sensors for Amazon Preisalarm."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AmazonPreisalarmConfigEntry, AmazonPriceCoordinator, Product
from .entity import AmazonProductEntity

CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonPreisalarmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors, grouped per product subentry."""
    coordinator = entry.runtime_data
    for product in coordinator.products.values():
        async_add_entities(
            [
                PriceSensor(coordinator, product),
                PriceChangeSensor(coordinator, product),
                PriceChangePercentSensor(coordinator, product),
            ],
            config_subentry_id=product.subentry_id,
        )


def format_money(value: float, currency: str, signed: bool = False) -> str:
    """Format like '+12,50 €' (comma decimals for EUR)."""
    text = f"{value:+,.2f}" if signed else f"{value:,.2f}"
    if currency == "EUR":
        text = text.replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"{text} {CURRENCY_SYMBOLS.get(currency, currency)}"


def _trend(change: float | None) -> str | None:
    if change is None:
        return None
    if change > 0:
        return "up"
    if change < 0:
        return "down"
    return "unchanged"


class PriceSensor(AmazonProductEntity, SensorEntity):
    """Current price."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator: AmazonPriceCoordinator, product: Product) -> None:
        """Initialize."""
        super().__init__(coordinator, product, "price")
        self._attr_native_unit_of_measurement = product.ref.currency

    @property
    def native_value(self) -> float | None:
        """Return the price."""
        return self.product_state.price

    @property
    def entity_picture(self) -> str | None:
        """Product image."""
        return self.product_state.image

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra information."""
        state = self.product_state
        reference, since = self.coordinator.reference(self.sid)
        return {
            "title": state.title,
            "asin": self.product.ref.asin,
            "url": self.product.ref.url,
            "availability": state.availability,
            "reference_price": reference,
            "reference_since": since,
            "target_price": self.product.target_price,
            "last_checked": state.last_checked,
            "last_success": state.last_success,
            "error": state.error,
        }


class PriceChangeSensor(AmazonProductEntity, SensorEntity):
    """Price change vs. the reference price (negative = cheaper)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: AmazonPriceCoordinator, product: Product) -> None:
        """Initialize."""
        super().__init__(coordinator, product, "price_change")
        self._attr_native_unit_of_measurement = product.ref.currency

    @property
    def native_value(self) -> float | None:
        """Return the change."""
        return self.coordinator.change(self.sid)

    @property
    def icon(self) -> str:
        """Icon depending on the direction."""
        return {
            "up": "mdi:trending-up",
            "down": "mdi:trending-down",
        }.get(_trend(self.native_value) or "", "mdi:trending-neutral")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra information."""
        change = self.coordinator.change(self.sid)
        reference, since = self.coordinator.reference(self.sid)
        currency = self.product.ref.currency
        return {
            "change_formatted": (
                format_money(change, currency, signed=True) if change is not None else None
            ),
            "trend": _trend(change),
            "current_price": self.product_state.price,
            "reference_price": reference,
            "reference_since": since,
            "change_percent": self.coordinator.change_percent(self.sid),
        }


class PriceChangePercentSensor(AmazonProductEntity, SensorEntity):
    """Relative price change vs. the reference price."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:percent"

    def __init__(self, coordinator: AmazonPriceCoordinator, product: Product) -> None:
        """Initialize."""
        super().__init__(coordinator, product, "price_change_percent")

    @property
    def native_value(self) -> float | None:
        """Return the relative change."""
        return self.coordinator.change_percent(self.sid)

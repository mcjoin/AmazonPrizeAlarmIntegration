"""Binary sensors for Amazon Preisalarm."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AmazonPreisalarmConfigEntry, AmazonPriceCoordinator, Product
from .entity import AmazonProductEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonPreisalarmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a target price sensor for every product with a target price."""
    coordinator = entry.runtime_data
    for product in coordinator.products.values():
        if product.target_price is not None:
            async_add_entities(
                [TargetPriceReachedSensor(coordinator, product)],
                config_subentry_id=product.subentry_id,
            )


class TargetPriceReachedSensor(AmazonProductEntity, BinarySensorEntity):
    """On when the current price is at or below the target price."""

    def __init__(self, coordinator: AmazonPriceCoordinator, product: Product) -> None:
        """Initialize."""
        super().__init__(coordinator, product, "target_reached")

    @property
    def is_on(self) -> bool | None:
        """Return true if the target price is reached."""
        if (price := self.product_state.price) is None:
            return None
        return price <= self.product.target_price

    @property
    def icon(self) -> str:
        """Icon."""
        return "mdi:tag-check" if self.is_on else "mdi:tag-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra information."""
        price = self.product_state.price
        return {
            "target_price": self.product.target_price,
            "current_price": price,
            "difference": (
                round(price - self.product.target_price, 2) if price is not None else None
            ),
        }

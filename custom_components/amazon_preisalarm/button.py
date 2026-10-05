"""Buttons for Amazon Preisalarm."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AmazonPreisalarmConfigEntry, AmazonPriceCoordinator, Product
from .entity import AmazonProductEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonPreisalarmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the reset buttons."""
    coordinator = entry.runtime_data
    for product in coordinator.products.values():
        async_add_entities(
            [ResetReferenceButton(coordinator, product)],
            config_subentry_id=product.subentry_id,
        )


class ResetReferenceButton(AmazonProductEntity, ButtonEntity):
    """Use the current price as new reference price."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:restore"

    def __init__(self, coordinator: AmazonPriceCoordinator, product: Product) -> None:
        """Initialize."""
        super().__init__(coordinator, product, "reset_reference")

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_reset_reference(self.sid)

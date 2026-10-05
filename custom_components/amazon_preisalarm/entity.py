"""Base entity for Amazon Preisalarm."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AmazonPriceCoordinator, Product, ProductState


class AmazonProductEntity(CoordinatorEntity[AmazonPriceCoordinator]):
    """An entity belonging to one tracked product."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: AmazonPriceCoordinator, product: Product, key: str
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.product = product
        self._attr_translation_key = key
        self._attr_unique_id = f"{product.subentry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, product.subentry_id)},
            name=product.name,
            manufacturer="Amazon",
            model=product.ref.asin,
            configuration_url=product.ref.url,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def product_state(self) -> ProductState:
        """Last known state of the product."""
        return self.coordinator.data.get(self.product.subentry_id) or ProductState()

    @property
    def sid(self) -> str:
        """Subentry id of the product."""
        return self.product.subentry_id

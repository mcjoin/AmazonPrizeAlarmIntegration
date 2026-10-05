"""The Amazon Preisalarm integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import AmazonPreisalarmConfigEntry, AmazonPriceCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]


async def async_setup_entry(
    hass: HomeAssistant, entry: AmazonPreisalarmConfigEntry
) -> bool:
    """Set up Amazon Preisalarm from a config entry."""
    coordinator = AmazonPriceCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Fetching many products takes a while (pauses between requests), so the
    # first refresh runs in the background. Until then the last known values
    # from storage are shown.
    if coordinator.products:
        entry.async_create_background_task(
            hass, coordinator.async_refresh(), name=f"{DOMAIN} initial refresh"
        )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: AmazonPreisalarmConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.session.close()
    return unloaded


async def _async_update_listener(
    hass: HomeAssistant, entry: AmazonPreisalarmConfigEntry
) -> None:
    """Reload when options or products (subentries) change."""
    await hass.config_entries.async_reload(entry.entry_id)

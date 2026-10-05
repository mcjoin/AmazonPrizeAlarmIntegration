"""Config flow for Amazon Preisalarm."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ADDED_AT,
    CONF_AMAZON_DOMAIN,
    CONF_ASIN,
    CONF_INITIAL_PRICE,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_TARGET_PRICE,
    CONF_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SUBENTRY_TYPE_PRODUCT,
)
from .scraper import (
    AmazonBlockedError,
    AmazonError,
    AmazonParseError,
    InvalidAmazonUrl,
    async_fetch_html,
    async_resolve_url,
    parse_product_page,
)

MAX_TITLE_LENGTH = 60

PRICE_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=0, step=0.01, mode=NumberSelectorMode.BOX)
)


def _interval_schema(default: int) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SCAN_INTERVAL, default=default): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    unit_of_measurement="min",
                    mode=NumberSelectorMode.BOX,
                )
            )
        }
    )


def _short_title(title: str | None) -> str | None:
    """Amazon titles are very long; cut at a word boundary."""
    if not title:
        return None
    if len(title) <= MAX_TITLE_LENGTH:
        return title
    return title[:MAX_TITLE_LENGTH].rsplit(" ", 1)[0].rstrip(" ,-|") + "…"


class AmazonPreisalarmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the main config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the (single) entry."""
        if user_input is not None:
            return self.async_create_entry(
                title="Amazon Preisalarm",
                data={},
                options={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])},
            )
        return self.async_show_form(
            step_id="user", data_schema=_interval_schema(DEFAULT_SCAN_INTERVAL)
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options flow (scan interval)."""
        return AmazonPreisalarmOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Products are added as subentries."""
        return {SUBENTRY_TYPE_PRODUCT: ProductSubentryFlow}


class AmazonPreisalarmOptionsFlow(OptionsFlow):
    """Change the scan interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        current = int(
            self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        return self.async_show_form(step_id="init", data_schema=_interval_schema(current))


class ProductSubentryFlow(ConfigSubentryFlow):
    """Add or edit a tracked product."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a product by its Amazon link."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                ref = await async_resolve_url(session, user_input[CONF_URL])
            except InvalidAmazonUrl:
                errors[CONF_URL] = "invalid_url"
            except AmazonError:
                errors["base"] = "cannot_connect"
            else:
                if any(
                    sub.unique_id == ref.unique_id
                    for sub in self._get_entry().subentries.values()
                ):
                    return self.async_abort(reason="already_configured")
                try:
                    html = await async_fetch_html(session, ref)
                    info = await self.hass.async_add_executor_job(
                        parse_product_page, html
                    )
                except AmazonBlockedError:
                    errors["base"] = "blocked"
                except AmazonParseError:
                    errors["base"] = "cannot_parse"
                except AmazonError:
                    errors["base"] = "cannot_connect"
                else:
                    title = (
                        (user_input.get(CONF_NAME) or "").strip()
                        or _short_title(info.title)
                        or ref.asin
                    )
                    return self.async_create_entry(
                        title=title,
                        unique_id=ref.unique_id,
                        data={
                            CONF_URL: ref.url,
                            CONF_ASIN: ref.asin,
                            CONF_AMAZON_DOMAIN: ref.domain,
                            CONF_TARGET_PRICE: user_input.get(CONF_TARGET_PRICE),
                            CONF_INITIAL_PRICE: info.price,
                            CONF_ADDED_AT: dt_util.utcnow().isoformat(),
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Optional(CONF_NAME): str,
                vol.Optional(CONF_TARGET_PRICE): PRICE_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change name and target price of a product."""
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            title = (user_input.get(CONF_NAME) or "").strip() or subentry.title
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=title,
                data={
                    **subentry.data,
                    CONF_TARGET_PRICE: user_input.get(CONF_TARGET_PRICE),
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Optional(CONF_TARGET_PRICE): PRICE_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_NAME: subentry.title,
                    CONF_TARGET_PRICE: subentry.data.get(CONF_TARGET_PRICE),
                },
            ),
            description_placeholders={"url": subentry.data[CONF_URL]},
        )

"""Number entity for SAJ Modbus integration."""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.components.number import NumberEntity
from homeassistant.const import CONF_NAME
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_MANUFACTURER,
    DOMAIN,
    NUMBER_TYPES,
    SajModbusNumberEntityDescription,
)
from .hub import SAJModbusHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    hub_name = entry.data[CONF_NAME]
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }

    entities = []
    for number_description in NUMBER_TYPES.values():
        number = SajNumber(
            hub_name,
            hub,
            device_info,
            number_description,
        )
        entities.append(number)

    async_add_entities(entities)
    return True


class SajNumber(CoordinatorEntity, NumberEntity):
    """Representation of an SAJ Modbus number."""

    def __init__(
        self,
        platform_name: str,
        hub: SAJModbusHub,
        device_info,
        description: SajModbusNumberEntityDescription,
    ):
        """Initialize the sensor."""
        self._platform_name = platform_name
        self._attr_device_info = device_info
        self.entity_description: SajModbusNumberEntityDescription = description

        super().__init__(coordinator=hub)

    @property
    def name(self):
        """Return the name."""
        return f"{self._platform_name} {self.entity_description.name}"

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self.entity_description.key}"

    @property
    def native_value(self):
        """Return the state of the number entity."""
        return getattr(self.coordinator, self.entity_description.key, None)

    def set_native_value(self, value: float) -> None:
        """Update the current value."""
        self.coordinator.set_value(self.entity_description.key, value)


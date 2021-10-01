"""Contec Pusher."""

import logging
from typing import List

from ContecControllers.ContecPusherActivation import ContecPusherActivation
from ContecControllers.ControllerManager import ControllerManager

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Contec Pushers."""
    controller_manager: ControllerManager = hass.data[DOMAIN][config_entry.entry_id]
    all_pushers: List[ContecPusher] = [
        ContecPusher(pusher) for pusher in controller_manager.PusherActivations
    ]
    async_add_entities(all_pushers)


class ContecPusher(BinarySensorEntity):
    """Representation of a Contec Pusher."""

    _pusher_activation: ContecPusherActivation

    def __init__(self, pusherActivation: ContecPusherActivation) -> None:
        """Initialize an ContecPusher."""
        self._pusher_activation = pusherActivation
        self._attr_unique_id = f"{pusherActivation.ControllerUnit.UnitId}-{pusherActivation.StartActivationNumber}"
        self._attr_name = f"Contec Pusher {self._attr_unique_id}"
        self._attr_should_poll = False

    @property
    def is_on(self) -> bool:
        """Return true if pusher is on."""
        return self._pusher_activation.IsPushed

    async def async_added_to_hass(self) -> None:
        """Subscribe to changes in pusher activation."""

        @callback
        def _async_state_updated(isPushed: bool) -> None:
            self.async_write_ha_state()

        self._pusher_activation.SetStateChangedCallback(_async_state_updated)

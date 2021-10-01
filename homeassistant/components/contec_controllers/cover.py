"""Contec cover entity."""

import logging
from typing import List

from ContecControllers.ContecBlindActivation import BlindState, ContecBlindActivation
from ContecControllers.ControllerManager import ControllerManager

from homeassistant.components.cover import (
    ATTR_POSITION,
    DEVICE_CLASS_BLIND,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    SUPPORT_SET_POSITION,
    CoverEntity,
)
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
    """Set up the Contec cover."""
    controller_manager: ControllerManager = hass.data[DOMAIN][config_entry.entry_id]
    all_covers: List[ContecCover] = [
        ContecCover(blind) for blind in controller_manager.BlindActivations
    ]
    async_add_entities(all_covers)


class ContecCover(CoverEntity):
    """Representation of an Contec cover."""

    _blind_activation: ContecBlindActivation

    def __init__(self, blind_activation: ContecBlindActivation) -> None:
        """Initialize an ContecCover."""
        self._blind_activation = blind_activation
        self._attr_unique_id = f"{blind_activation.ControllerUnit.UnitId}-{blind_activation.StartActivationNumber}"
        self._attr_name = f"Contec Cover {self._attr_unique_id}"
        self._attr_should_poll = False
        self._attr_device_class = DEVICE_CLASS_BLIND
        self._attr_supported_features = (
            SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_SET_POSITION
        )

    @property
    def is_opening(self) -> bool:
        """Return true if the cover is opening."""
        return self._blind_activation.MovingDirection == BlindState.MovingUp

    @property
    def is_closing(self) -> bool:
        """Return true if the cover is closing."""
        return self._blind_activation.MovingDirection == BlindState.MovingDown

    @property
    def is_closed(self) -> bool:
        """Return true if the cover is closed."""
        return self._blind_activation.BlindOpeningPercentage == 0

    @property
    def current_cover_position(self) -> int:
        """Return the current opening percentage."""
        return self._blind_activation.BlindOpeningPercentage

    async def async_added_to_hass(self) -> None:
        """Subscribe to changes in blind activation."""

        @callback
        def _async_state_updated(
            movingDirection: BlindState, blindOpeningPercentage: int
        ) -> None:
            self.async_write_ha_state()

        self._blind_activation.SetStateChangedCallback(_async_state_updated)

    async def async_open_cover(self, **kwargs) -> None:
        """Open the cover."""
        await self._blind_activation.SetBlindsState(100)

    async def async_close_cover(self, **kwargs) -> None:
        """Open the cover."""
        await self._blind_activation.SetBlindsState(0)

    async def async_set_cover_position(self, **kwargs) -> None:
        """Move the cover to a specific position."""
        position: int = kwargs[ATTR_POSITION]
        await self._blind_activation.SetBlindsState(position)

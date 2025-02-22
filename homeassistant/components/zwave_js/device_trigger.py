"""Provides device triggers for Z-Wave JS."""
from __future__ import annotations

import voluptuous as vol
from zwave_js_server.const import CommandClass, ConfigurationValueType

from homeassistant.components.automation import AutomationActionType
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event, state
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ENTITY_ID,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry,
    entity_registry,
)
from homeassistant.helpers.typing import ConfigType

from . import trigger
from .const import (
    ATTR_COMMAND_CLASS,
    ATTR_DATA_TYPE,
    ATTR_ENDPOINT,
    ATTR_EVENT,
    ATTR_EVENT_LABEL,
    ATTR_EVENT_TYPE,
    ATTR_LABEL,
    ATTR_PROPERTY,
    ATTR_PROPERTY_KEY,
    ATTR_TYPE,
    ATTR_VALUE,
    ATTR_VALUE_RAW,
    DOMAIN,
    ZWAVE_JS_NOTIFICATION_EVENT,
    ZWAVE_JS_VALUE_NOTIFICATION_EVENT,
)
from .helpers import (
    async_get_node_from_device_id,
    async_get_node_status_sensor_entity_id,
    get_zwave_value_from_config,
)
from .triggers.value_updated import ATTR_FROM, ATTR_TO

CONF_SUBTYPE = "subtype"
CONF_VALUE_ID = "value_id"

# Trigger types
ENTRY_CONTROL_NOTIFICATION = "event.notification.entry_control"
NOTIFICATION_NOTIFICATION = "event.notification.notification"
BASIC_VALUE_NOTIFICATION = "event.value_notification.basic"
CENTRAL_SCENE_VALUE_NOTIFICATION = "event.value_notification.central_scene"
SCENE_ACTIVATION_VALUE_NOTIFICATION = "event.value_notification.scene_activation"
CONFIG_PARAMETER_VALUE_UPDATED = f"{DOMAIN}.value_updated.config_parameter"
VALUE_VALUE_UPDATED = f"{DOMAIN}.value_updated.value"
NODE_STATUS = "state.node_status"

VALUE_SCHEMA = vol.Any(
    bool,
    vol.Coerce(int),
    vol.Coerce(float),
    cv.boolean,
    cv.string,
)

NOTIFICATION_EVENT_CC_MAPPINGS = (
    (ENTRY_CONTROL_NOTIFICATION, CommandClass.ENTRY_CONTROL),
    (NOTIFICATION_NOTIFICATION, CommandClass.NOTIFICATION),
)

# Event based trigger schemas
BASE_EVENT_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(ATTR_COMMAND_CLASS): vol.In([cc.value for cc in CommandClass]),
    }
)

NOTIFICATION_NOTIFICATION_SCHEMA = BASE_EVENT_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): NOTIFICATION_NOTIFICATION,
        vol.Optional(f"{ATTR_TYPE}."): vol.Coerce(int),
        vol.Optional(ATTR_LABEL): cv.string,
        vol.Optional(ATTR_EVENT): vol.Coerce(int),
        vol.Optional(ATTR_EVENT_LABEL): cv.string,
    }
)

ENTRY_CONTROL_NOTIFICATION_SCHEMA = BASE_EVENT_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): ENTRY_CONTROL_NOTIFICATION,
        vol.Optional(ATTR_EVENT_TYPE): vol.Coerce(int),
        vol.Optional(ATTR_DATA_TYPE): vol.Coerce(int),
    }
)

BASE_VALUE_NOTIFICATION_EVENT_SCHEMA = BASE_EVENT_SCHEMA.extend(
    {
        vol.Required(ATTR_PROPERTY): vol.Any(int, str),
        vol.Required(ATTR_PROPERTY_KEY): vol.Any(None, int, str),
        vol.Required(ATTR_ENDPOINT): vol.Coerce(int),
        vol.Optional(ATTR_VALUE): vol.Coerce(int),
        vol.Required(CONF_SUBTYPE): cv.string,
    }
)

BASIC_VALUE_NOTIFICATION_SCHEMA = BASE_VALUE_NOTIFICATION_EVENT_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): BASIC_VALUE_NOTIFICATION,
    }
)

CENTRAL_SCENE_VALUE_NOTIFICATION_SCHEMA = BASE_VALUE_NOTIFICATION_EVENT_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): CENTRAL_SCENE_VALUE_NOTIFICATION,
    }
)

SCENE_ACTIVATION_VALUE_NOTIFICATION_SCHEMA = (
    BASE_VALUE_NOTIFICATION_EVENT_SCHEMA.extend(
        {
            vol.Required(CONF_TYPE): SCENE_ACTIVATION_VALUE_NOTIFICATION,
        }
    )
)

# State based trigger schemas
BASE_STATE_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
    }
)

NODE_STATUSES = ["asleep", "awake", "dead", "alive"]

NODE_STATUS_SCHEMA = BASE_STATE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): NODE_STATUS,
        vol.Optional(state.CONF_FROM): vol.In(NODE_STATUSES),
        vol.Optional(state.CONF_TO): vol.In(NODE_STATUSES),
        vol.Optional(state.CONF_FOR): cv.positive_time_period_dict,
    }
)

# zwave_js.value_updated based trigger schemas
BASE_VALUE_UPDATED_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(ATTR_COMMAND_CLASS): vol.In([cc.value for cc in CommandClass]),
        vol.Required(ATTR_PROPERTY): vol.Any(int, str),
        vol.Optional(ATTR_PROPERTY_KEY): vol.Any(None, vol.Coerce(int), str),
        vol.Optional(ATTR_ENDPOINT): vol.Any(None, vol.Coerce(int)),
        vol.Optional(ATTR_FROM): VALUE_SCHEMA,
        vol.Optional(ATTR_TO): VALUE_SCHEMA,
    }
)

CONFIG_PARAMETER_VALUE_UPDATED_SCHEMA = BASE_VALUE_UPDATED_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): CONFIG_PARAMETER_VALUE_UPDATED,
        vol.Required(CONF_SUBTYPE): cv.string,
    }
)

VALUE_VALUE_UPDATED_SCHEMA = BASE_VALUE_UPDATED_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): VALUE_VALUE_UPDATED,
    }
)

TRIGGER_SCHEMA = vol.Any(
    ENTRY_CONTROL_NOTIFICATION_SCHEMA,
    NOTIFICATION_NOTIFICATION_SCHEMA,
    BASIC_VALUE_NOTIFICATION_SCHEMA,
    CENTRAL_SCENE_VALUE_NOTIFICATION_SCHEMA,
    SCENE_ACTIVATION_VALUE_NOTIFICATION_SCHEMA,
    CONFIG_PARAMETER_VALUE_UPDATED_SCHEMA,
    VALUE_VALUE_UPDATED_SCHEMA,
    NODE_STATUS_SCHEMA,
)


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict]:
    """List device triggers for Z-Wave JS devices."""
    dev_reg = device_registry.async_get(hass)
    node = async_get_node_from_device_id(hass, device_id, dev_reg)

    triggers = []
    base_trigger = {
        CONF_PLATFORM: "device",
        CONF_DEVICE_ID: device_id,
        CONF_DOMAIN: DOMAIN,
    }

    # We can add a node status trigger if the node status sensor is enabled
    ent_reg = entity_registry.async_get(hass)
    entity_id = async_get_node_status_sensor_entity_id(
        hass, device_id, ent_reg, dev_reg
    )
    if (entity := ent_reg.async_get(entity_id)) is not None and not entity.disabled:
        triggers.append(
            {**base_trigger, CONF_TYPE: NODE_STATUS, CONF_ENTITY_ID: entity_id}
        )

    # Handle notification event triggers
    triggers.extend(
        [
            {**base_trigger, CONF_TYPE: event_type, ATTR_COMMAND_CLASS: command_class}
            for event_type, command_class in NOTIFICATION_EVENT_CC_MAPPINGS
            if any(cc.id == command_class for cc in node.command_classes)
        ]
    )

    # Handle central scene value notification event triggers
    triggers.extend(
        [
            {
                **base_trigger,
                CONF_TYPE: CENTRAL_SCENE_VALUE_NOTIFICATION,
                ATTR_PROPERTY: value.property_,
                ATTR_PROPERTY_KEY: value.property_key,
                ATTR_ENDPOINT: value.endpoint,
                ATTR_COMMAND_CLASS: CommandClass.CENTRAL_SCENE,
                CONF_SUBTYPE: f"Endpoint {value.endpoint} Scene {value.property_key}",
            }
            for value in node.get_command_class_values(
                CommandClass.CENTRAL_SCENE
            ).values()
            if value.property_ == "scene"
        ]
    )

    # Handle scene activation value notification event triggers
    triggers.extend(
        [
            {
                **base_trigger,
                CONF_TYPE: SCENE_ACTIVATION_VALUE_NOTIFICATION,
                ATTR_PROPERTY: value.property_,
                ATTR_PROPERTY_KEY: value.property_key,
                ATTR_ENDPOINT: value.endpoint,
                ATTR_COMMAND_CLASS: CommandClass.SCENE_ACTIVATION,
                CONF_SUBTYPE: f"Endpoint {value.endpoint}",
            }
            for value in node.get_command_class_values(
                CommandClass.SCENE_ACTIVATION
            ).values()
            if value.property_ == "sceneId"
        ]
    )

    # Handle basic value notification event triggers
    # Nodes will only send Basic CC value notifications if a compatibility flag is set
    if node.device_config.compat.get("treatBasicSetAsEvent", False):
        triggers.extend(
            [
                {
                    **base_trigger,
                    CONF_TYPE: BASIC_VALUE_NOTIFICATION,
                    ATTR_PROPERTY: value.property_,
                    ATTR_PROPERTY_KEY: value.property_key,
                    ATTR_ENDPOINT: value.endpoint,
                    ATTR_COMMAND_CLASS: CommandClass.BASIC,
                    CONF_SUBTYPE: f"Endpoint {value.endpoint}",
                }
                for value in node.get_command_class_values(CommandClass.BASIC).values()
                if value.property_ == "event"
            ]
        )

    # Generic value update event trigger
    triggers.append({**base_trigger, CONF_TYPE: VALUE_VALUE_UPDATED})

    # Config parameter value update event triggers
    triggers.extend(
        [
            {
                **base_trigger,
                CONF_TYPE: CONFIG_PARAMETER_VALUE_UPDATED,
                ATTR_PROPERTY: config_value.property_,
                ATTR_PROPERTY_KEY: config_value.property_key,
                ATTR_ENDPOINT: config_value.endpoint,
                ATTR_COMMAND_CLASS: config_value.command_class,
                CONF_SUBTYPE: f"{config_value.value_id} ({config_value.property_name})",
            }
            for config_value in node.get_configuration_values().values()
        ]
    )

    return triggers


def copy_available_params(
    input_dict: dict, output_dict: dict, params: list[str]
) -> None:
    """Copy available params from input into output."""
    for param in params:
        if (val := input_dict.get(param)) not in ("", None):
            output_dict[param] = val


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: AutomationActionType,
    automation_info: dict,
) -> CALLBACK_TYPE:
    """Attach a trigger."""
    trigger_type = config[CONF_TYPE]
    trigger_split = trigger_type.split(".")
    # Our convention for trigger types is to have the trigger type at the beginning
    # delimited by a `.`. For zwave_js triggers, there is a `.` in the name
    trigger_platform = trigger_split[0]
    if trigger_platform == DOMAIN:
        trigger_platform = ".".join(trigger_split[:2])

    # Take input data from automation trigger UI and add it to the trigger we are
    # attaching to
    if trigger_platform == "event":
        event_data = {CONF_DEVICE_ID: config[CONF_DEVICE_ID]}
        event_config = {
            event.CONF_PLATFORM: "event",
            event.CONF_EVENT_DATA: event_data,
        }

        if ATTR_COMMAND_CLASS in config:
            event_data[ATTR_COMMAND_CLASS] = config[ATTR_COMMAND_CLASS]

        if trigger_type == ENTRY_CONTROL_NOTIFICATION:
            event_config[event.CONF_EVENT_TYPE] = ZWAVE_JS_NOTIFICATION_EVENT
            copy_available_params(config, event_data, [ATTR_EVENT_TYPE, ATTR_DATA_TYPE])
        elif trigger_type == NOTIFICATION_NOTIFICATION:
            event_config[event.CONF_EVENT_TYPE] = ZWAVE_JS_NOTIFICATION_EVENT
            copy_available_params(
                config, event_data, [ATTR_LABEL, ATTR_EVENT_LABEL, ATTR_EVENT]
            )
            if (val := config.get(f"{ATTR_TYPE}.")) not in ("", None):
                event_data[ATTR_TYPE] = val
        elif trigger_type in (
            BASIC_VALUE_NOTIFICATION,
            CENTRAL_SCENE_VALUE_NOTIFICATION,
            SCENE_ACTIVATION_VALUE_NOTIFICATION,
        ):
            event_config[event.CONF_EVENT_TYPE] = ZWAVE_JS_VALUE_NOTIFICATION_EVENT
            copy_available_params(
                config, event_data, [ATTR_PROPERTY, ATTR_PROPERTY_KEY, ATTR_ENDPOINT]
            )
            if ATTR_VALUE in config:
                event_data[ATTR_VALUE_RAW] = config[ATTR_VALUE]
        else:
            raise HomeAssistantError(f"Unhandled trigger type {trigger_type}")

        event_config = event.TRIGGER_SCHEMA(event_config)
        return await event.async_attach_trigger(
            hass, event_config, action, automation_info, platform_type="device"
        )

    if trigger_platform == "state":
        if trigger_type == NODE_STATUS:
            state_config = {state.CONF_PLATFORM: "state"}

            state_config[state.CONF_ENTITY_ID] = config[CONF_ENTITY_ID]
            copy_available_params(
                config, state_config, [state.CONF_FOR, state.CONF_FROM, state.CONF_TO]
            )
        else:
            raise HomeAssistantError(f"Unhandled trigger type {trigger_type}")

        state_config = state.TRIGGER_SCHEMA(state_config)
        return await state.async_attach_trigger(
            hass, state_config, action, automation_info, platform_type="device"
        )

    if trigger_platform == f"{DOMAIN}.value_updated":
        # Try to get the value to make sure the value ID is valid
        try:
            node = async_get_node_from_device_id(hass, config[CONF_DEVICE_ID])
            get_zwave_value_from_config(node, config)
        except (ValueError, vol.Invalid) as err:
            raise HomeAssistantError("Invalid value specified") from err

        zwave_js_config = {
            state.CONF_PLATFORM: trigger_platform,
            CONF_DEVICE_ID: config[CONF_DEVICE_ID],
        }
        copy_available_params(
            config,
            zwave_js_config,
            [
                ATTR_COMMAND_CLASS,
                ATTR_PROPERTY,
                ATTR_PROPERTY_KEY,
                ATTR_ENDPOINT,
                ATTR_FROM,
                ATTR_TO,
            ],
        )
        zwave_js_config = await trigger.async_validate_trigger_config(
            hass, zwave_js_config
        )
        return await trigger.async_attach_trigger(
            hass, zwave_js_config, action, automation_info
        )

    raise HomeAssistantError(f"Unhandled trigger type {trigger_type}")


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """List trigger capabilities."""
    trigger_type = config[CONF_TYPE]

    node = async_get_node_from_device_id(hass, config[CONF_DEVICE_ID])
    value = (
        get_zwave_value_from_config(node, config) if ATTR_PROPERTY in config else None
    )
    # Add additional fields to the automation trigger UI
    if trigger_type == NOTIFICATION_NOTIFICATION:
        return {
            "extra_fields": vol.Schema(
                {
                    vol.Optional(f"{ATTR_TYPE}."): cv.string,
                    vol.Optional(ATTR_LABEL): cv.string,
                    vol.Optional(ATTR_EVENT): cv.string,
                    vol.Optional(ATTR_EVENT_LABEL): cv.string,
                }
            )
        }

    if trigger_type == ENTRY_CONTROL_NOTIFICATION:
        return {
            "extra_fields": vol.Schema(
                {
                    vol.Optional(ATTR_EVENT_TYPE): cv.string,
                    vol.Optional(ATTR_DATA_TYPE): cv.string,
                }
            )
        }

    if trigger_type == NODE_STATUS:
        return {
            "extra_fields": vol.Schema(
                {
                    vol.Optional(state.CONF_FROM): vol.In(NODE_STATUSES),
                    vol.Optional(state.CONF_TO): vol.In(NODE_STATUSES),
                    vol.Optional(state.CONF_FOR): cv.positive_time_period_dict,
                }
            )
        }

    if trigger_type in (
        BASIC_VALUE_NOTIFICATION,
        CENTRAL_SCENE_VALUE_NOTIFICATION,
        SCENE_ACTIVATION_VALUE_NOTIFICATION,
    ):
        if value.metadata.states:
            value_schema = vol.In({int(k): v for k, v in value.metadata.states.items()})
        else:
            value_schema = vol.All(
                vol.Coerce(int),
                vol.Range(min=value.metadata.min, max=value.metadata.max),
            )

        return {"extra_fields": vol.Schema({vol.Optional(ATTR_VALUE): value_schema})}

    if trigger_type == CONFIG_PARAMETER_VALUE_UPDATED:
        # We can be more deliberate about the config parameter schema here because
        # there are a limited number of types
        if value.configuration_value_type == ConfigurationValueType.UNDEFINED:
            return {}
        if value.configuration_value_type == ConfigurationValueType.ENUMERATED:
            value_schema = vol.In({int(k): v for k, v in value.metadata.states.items()})
        else:
            value_schema = vol.All(
                vol.Coerce(int),
                vol.Range(min=value.metadata.min, max=value.metadata.max),
            )
        return {
            "extra_fields": vol.Schema(
                {
                    vol.Optional(state.CONF_FROM): value_schema,
                    vol.Optional(state.CONF_TO): value_schema,
                }
            )
        }

    if trigger_type == VALUE_VALUE_UPDATED:
        # Only show command classes on this node and exclude Configuration CC since it
        # is already covered
        return {
            "extra_fields": vol.Schema(
                {
                    vol.Required(ATTR_COMMAND_CLASS): vol.In(
                        {
                            CommandClass(cc.id).value: cc.name
                            for cc in sorted(node.command_classes, key=lambda cc: cc.name)  # type: ignore[no-any-return]
                            if cc.id != CommandClass.CONFIGURATION
                        }
                    ),
                    vol.Required(ATTR_PROPERTY): cv.string,
                    vol.Optional(ATTR_PROPERTY_KEY): cv.string,
                    vol.Optional(ATTR_ENDPOINT): cv.string,
                    vol.Optional(state.CONF_FROM): cv.string,
                    vol.Optional(state.CONF_TO): cv.string,
                }
            )
        }

    return {}

"""Test the Z-Wave JS config flow."""
import asyncio
from unittest.mock import DEFAULT, call, patch

import aiohttp
import pytest
from zwave_js_server.version import VersionInfo

from homeassistant import config_entries, setup
from homeassistant.components.hassio.handler import HassioAPIError
from homeassistant.components.zwave_js.config_flow import SERVER_VERSION_TIMEOUT, TITLE
from homeassistant.components.zwave_js.const import DOMAIN

from tests.common import MockConfigEntry

ADDON_DISCOVERY_INFO = {
    "addon": "Z-Wave JS",
    "host": "host1",
    "port": 3001,
}


USB_DISCOVERY_INFO = {
    "device": "/dev/zwave",
    "pid": "AAAA",
    "vid": "AAAA",
    "serial_number": "1234",
    "description": "zwave radio",
    "manufacturer": "test",
}

NORTEK_ZIGBEE_DISCOVERY_INFO = {
    "device": "/dev/zigbee",
    "pid": "8A2A",
    "vid": "10C4",
    "serial_number": "1234",
    "description": "nortek zigbee radio",
    "manufacturer": "nortek",
}

CP2652_ZIGBEE_DISCOVERY_INFO = {
    "device": "/dev/zigbee",
    "pid": "EA60",
    "vid": "10C4",
    "serial_number": "",
    "description": "cp2652",
    "manufacturer": "generic",
}


@pytest.fixture(name="persistent_notification", autouse=True)
async def setup_persistent_notification(hass):
    """Set up persistent notification integration."""
    await setup.async_setup_component(hass, "persistent_notification", {})


@pytest.fixture(name="setup_entry")
def setup_entry_fixture():
    """Mock entry setup."""
    with patch(
        "homeassistant.components.zwave_js.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture(name="supervisor")
def mock_supervisor_fixture():
    """Mock Supervisor."""
    with patch(
        "homeassistant.components.zwave_js.config_flow.is_hassio", return_value=True
    ):
        yield


@pytest.fixture(name="discovery_info")
def discovery_info_fixture():
    """Return the discovery info from the supervisor."""
    return DEFAULT


@pytest.fixture(name="discovery_info_side_effect")
def discovery_info_side_effect_fixture():
    """Return the discovery info from the supervisor."""
    return None


@pytest.fixture(name="get_addon_discovery_info")
def mock_get_addon_discovery_info(discovery_info, discovery_info_side_effect):
    """Mock get add-on discovery info."""
    with patch(
        "homeassistant.components.zwave_js.addon.async_get_addon_discovery_info",
        side_effect=discovery_info_side_effect,
        return_value=discovery_info,
    ) as get_addon_discovery_info:
        yield get_addon_discovery_info


@pytest.fixture(name="server_version_side_effect")
def server_version_side_effect_fixture():
    """Return the server version side effect."""
    return None


@pytest.fixture(name="get_server_version", autouse=True)
def mock_get_server_version(server_version_side_effect, server_version_timeout):
    """Mock server version."""
    version_info = VersionInfo(
        driver_version="mock-driver-version",
        server_version="mock-server-version",
        home_id=1234,
        min_schema_version=0,
        max_schema_version=1,
    )
    with patch(
        "homeassistant.components.zwave_js.config_flow.get_server_version",
        side_effect=server_version_side_effect,
        return_value=version_info,
    ) as mock_version, patch(
        "homeassistant.components.zwave_js.config_flow.SERVER_VERSION_TIMEOUT",
        new=server_version_timeout,
    ):
        yield mock_version


@pytest.fixture(name="server_version_timeout")
def mock_server_version_timeout():
    """Patch the timeout for getting server version."""
    return SERVER_VERSION_TIMEOUT


@pytest.fixture(name="addon_setup_time", autouse=True)
def mock_addon_setup_time():
    """Mock add-on setup sleep time."""
    with patch(
        "homeassistant.components.zwave_js.config_flow.ADDON_SETUP_TIMEOUT", new=0
    ) as addon_setup_time:
        yield addon_setup_time


async def test_manual(hass):
    """Test we create an entry with manual step."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "url": "ws://localhost:3000",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "Z-Wave JS"
    assert result2["data"] == {
        "url": "ws://localhost:3000",
        "usb_path": None,
        "network_key": None,
        "use_addon": False,
        "integration_created_addon": False,
    }
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1
    assert result2["result"].unique_id == 1234


async def slow_server_version(*args):
    """Simulate a slow server version."""
    await asyncio.sleep(0.1)


@pytest.mark.parametrize(
    "flow, flow_params",
    [
        (
            "flow",
            lambda entry: {
                "handler": DOMAIN,
                "context": {"source": config_entries.SOURCE_USER},
            },
        ),
        ("options", lambda entry: {"handler": entry.entry_id}),
    ],
)
@pytest.mark.parametrize(
    "url, server_version_side_effect, server_version_timeout, error",
    [
        (
            "not-ws-url",
            None,
            SERVER_VERSION_TIMEOUT,
            "invalid_ws_url",
        ),
        (
            "ws://localhost:3000",
            slow_server_version,
            0,
            "cannot_connect",
        ),
        (
            "ws://localhost:3000",
            Exception("Boom"),
            SERVER_VERSION_TIMEOUT,
            "unknown",
        ),
    ],
)
async def test_manual_errors(hass, integration, url, error, flow, flow_params):
    """Test all errors with a manual set up."""
    entry = integration
    result = await getattr(hass.config_entries, flow).async_init(**flow_params(entry))

    assert result["type"] == "form"
    assert result["step_id"] == "manual"

    result = await getattr(hass.config_entries, flow).async_configure(
        result["flow_id"],
        {
            "url": url,
        },
    )

    assert result["type"] == "form"
    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": error}


async def test_manual_already_configured(hass):
    """Test that only one unique instance is allowed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "url": "ws://localhost:3000",
            "use_addon": True,
            "integration_created_addon": True,
        },
        title=TITLE,
        unique_id=1234,
    )
    entry.add_to_hass(hass)

    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "manual"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "url": "ws://1.1.1.1:3001",
        },
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    assert entry.data["url"] == "ws://1.1.1.1:3001"
    assert entry.data["use_addon"] is False
    assert entry.data["integration_created_addon"] is False


@pytest.mark.parametrize("discovery_info", [{"config": ADDON_DISCOVERY_INFO}])
async def test_supervisor_discovery(
    hass, supervisor, addon_running, addon_options, get_addon_discovery_info
):
    """Test flow started from Supervisor discovery."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    addon_options["device"] = "/test"
    addon_options["network_key"] = "abc123"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=ADDON_DISCOVERY_INFO,
    )

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert result["data"] == {
        "url": "ws://host1:3001",
        "usb_path": "/test",
        "network_key": "abc123",
        "use_addon": True,
        "integration_created_addon": False,
    }
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    "discovery_info, server_version_side_effect",
    [({"config": ADDON_DISCOVERY_INFO}, asyncio.TimeoutError())],
)
async def test_supervisor_discovery_cannot_connect(
    hass, supervisor, get_addon_discovery_info
):
    """Test Supervisor discovery and cannot connect."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=ADDON_DISCOVERY_INFO,
    )

    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


@pytest.mark.parametrize("discovery_info", [{"config": ADDON_DISCOVERY_INFO}])
async def test_clean_discovery_on_user_create(
    hass, supervisor, addon_running, addon_options, get_addon_discovery_info
):
    """Test discovery flow is cleaned up when a user flow is finished."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    addon_options["device"] = "/test"
    addon_options["network_key"] = "abc123"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=ADDON_DISCOVERY_INFO,
    )

    assert result["type"] == "form"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": False}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "manual"

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "url": "ws://localhost:3000",
            },
        )
        await hass.async_block_till_done()

    assert len(hass.config_entries.flow.async_progress()) == 0
    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert result["data"] == {
        "url": "ws://localhost:3000",
        "usb_path": None,
        "network_key": None,
        "use_addon": False,
        "integration_created_addon": False,
    }
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


async def test_abort_discovery_with_existing_entry(
    hass, supervisor, addon_running, addon_options
):
    """Test discovery flow is aborted if an entry already exists."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    entry = MockConfigEntry(
        domain=DOMAIN, data={"url": "ws://localhost:3000"}, title=TITLE, unique_id=1234
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=ADDON_DISCOVERY_INFO,
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    # Assert that the entry data is updated with discovery info.
    assert entry.data["url"] == "ws://host1:3001"


async def test_abort_hassio_discovery_with_existing_flow(
    hass, supervisor, addon_options
):
    """Test hassio discovery flow is aborted when another discovery has happened."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USB},
        data=USB_DISCOVERY_INFO,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "usb_confirm"

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=ADDON_DISCOVERY_INFO,
    )

    assert result2["type"] == "abort"
    assert result2["reason"] == "already_in_progress"


async def test_usb_discovery(
    hass,
    supervisor,
    install_addon,
    addon_options,
    get_addon_discovery_info,
    set_addon_options,
    start_addon,
):
    """Test usb discovery success path."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USB},
        data=USB_DISCOVERY_INFO,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "usb_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] == "progress"
    assert result["step_id"] == "install_addon"

    # Make sure the flow continues when the progress task is done.
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert install_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_path": "/test", "network_key": "abc123"}
    )

    assert set_addon_options.call_args == call(
        hass, "core_zwave_js", {"options": {"device": "/test", "network_key": "abc123"}}
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        await hass.async_block_till_done()

    assert start_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert result["data"]["usb_path"] == "/test"
    assert result["data"]["integration_created_addon"] is True
    assert result["data"]["use_addon"] is True
    assert result["data"]["network_key"] == "abc123"
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


async def test_discovery_addon_not_running(
    hass, supervisor, addon_installed, addon_options, set_addon_options, start_addon
):
    """Test discovery with add-on already installed but not running."""
    addon_options["device"] = None
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=ADDON_DISCOVERY_INFO,
    )

    assert result["step_id"] == "hassio_confirm"
    assert result["type"] == "form"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_path": "/test", "network_key": "abc123"}
    )

    assert set_addon_options.call_args == call(
        hass, "core_zwave_js", {"options": {"device": "/test", "network_key": "abc123"}}
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        await hass.async_block_till_done()

    assert start_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert result["data"] == {
        "url": "ws://host1:3001",
        "usb_path": "/test",
        "network_key": "abc123",
        "use_addon": True,
        "integration_created_addon": False,
    }
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


async def test_discovery_addon_not_installed(
    hass,
    supervisor,
    addon_installed,
    install_addon,
    addon_options,
    set_addon_options,
    start_addon,
):
    """Test discovery with add-on not installed."""
    addon_installed.return_value["version"] = None
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=ADDON_DISCOVERY_INFO,
    )

    assert result["step_id"] == "hassio_confirm"
    assert result["type"] == "form"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["step_id"] == "install_addon"
    assert result["type"] == "progress"

    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert install_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_path": "/test", "network_key": "abc123"}
    )

    assert set_addon_options.call_args == call(
        hass, "core_zwave_js", {"options": {"device": "/test", "network_key": "abc123"}}
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        await hass.async_block_till_done()

    assert start_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert result["data"] == {
        "url": "ws://host1:3001",
        "usb_path": "/test",
        "network_key": "abc123",
        "use_addon": True,
        "integration_created_addon": True,
    }
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


async def test_abort_usb_discovery_with_existing_flow(hass, supervisor, addon_options):
    """Test usb discovery flow is aborted when another discovery has happened."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=ADDON_DISCOVERY_INFO,
    )

    assert result["type"] == "form"
    assert result["step_id"] == "hassio_confirm"

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USB},
        data=USB_DISCOVERY_INFO,
    )
    assert result2["type"] == "abort"
    assert result2["reason"] == "already_in_progress"


async def test_abort_usb_discovery_already_configured(hass, supervisor, addon_options):
    """Test usb discovery flow is aborted when there is an existing entry."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"url": "ws://localhost:3000"}, title=TITLE, unique_id=1234
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USB},
        data=USB_DISCOVERY_INFO,
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_usb_discovery_requires_supervisor(hass):
    """Test usb discovery flow is aborted when there is no supervisor."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USB},
        data=USB_DISCOVERY_INFO,
    )
    assert result["type"] == "abort"
    assert result["reason"] == "discovery_requires_supervisor"


async def test_usb_discovery_already_running(hass, supervisor, addon_running):
    """Test usb discovery flow is aborted when the addon is running."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USB},
        data=USB_DISCOVERY_INFO,
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    "discovery_info",
    [
        NORTEK_ZIGBEE_DISCOVERY_INFO,
        CP2652_ZIGBEE_DISCOVERY_INFO,
    ],
)
async def test_abort_usb_discovery_aborts_specific_devices(
    hass, supervisor, addon_options, discovery_info
):
    """Test usb discovery flow is aborted on specific devices."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USB},
        data=discovery_info,
    )
    assert result["type"] == "abort"
    assert result["reason"] == "not_zwave_device"


async def test_not_addon(hass, supervisor):
    """Test opting out of add-on on Supervisor."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": False}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "manual"

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "url": "ws://localhost:3000",
            },
        )
        await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert result["data"] == {
        "url": "ws://localhost:3000",
        "usb_path": None,
        "network_key": None,
        "use_addon": False,
        "integration_created_addon": False,
    }
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize("discovery_info", [{"config": ADDON_DISCOVERY_INFO}])
async def test_addon_running(
    hass,
    supervisor,
    addon_running,
    addon_options,
    get_addon_discovery_info,
):
    """Test add-on already running on Supervisor."""
    addon_options["device"] = "/test"
    addon_options["network_key"] = "abc123"
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"use_addon": True}
        )
        await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert result["data"] == {
        "url": "ws://host1:3001",
        "usb_path": "/test",
        "network_key": "abc123",
        "use_addon": True,
        "integration_created_addon": False,
    }
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    "discovery_info, discovery_info_side_effect, server_version_side_effect, "
    "addon_info_side_effect, abort_reason",
    [
        (
            {"config": ADDON_DISCOVERY_INFO},
            HassioAPIError(),
            None,
            None,
            "addon_get_discovery_info_failed",
        ),
        (
            {"config": ADDON_DISCOVERY_INFO},
            None,
            asyncio.TimeoutError,
            None,
            "cannot_connect",
        ),
        (
            None,
            None,
            None,
            None,
            "addon_get_discovery_info_failed",
        ),
        (
            {"config": ADDON_DISCOVERY_INFO},
            None,
            None,
            HassioAPIError(),
            "addon_info_failed",
        ),
    ],
)
async def test_addon_running_failures(
    hass,
    supervisor,
    addon_running,
    addon_options,
    get_addon_discovery_info,
    abort_reason,
):
    """Test all failures when add-on is running."""
    addon_options["device"] = "/test"
    addon_options["network_key"] = "abc123"
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "abort"
    assert result["reason"] == abort_reason


@pytest.mark.parametrize("discovery_info", [{"config": ADDON_DISCOVERY_INFO}])
async def test_addon_running_already_configured(
    hass, supervisor, addon_running, addon_options, get_addon_discovery_info
):
    """Test that only one unique instance is allowed when add-on is running."""
    addon_options["device"] = "/test_new"
    addon_options["network_key"] = "def456"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "url": "ws://localhost:3000",
            "usb_path": "/test",
            "network_key": "abc123",
        },
        title=TITLE,
        unique_id=1234,
    )
    entry.add_to_hass(hass)

    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    assert entry.data["url"] == "ws://host1:3001"
    assert entry.data["usb_path"] == "/test_new"
    assert entry.data["network_key"] == "def456"


@pytest.mark.parametrize("discovery_info", [{"config": ADDON_DISCOVERY_INFO}])
async def test_addon_installed(
    hass,
    supervisor,
    addon_installed,
    addon_options,
    set_addon_options,
    start_addon,
    get_addon_discovery_info,
):
    """Test add-on already installed but not running on Supervisor."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_path": "/test", "network_key": "abc123"}
    )

    assert set_addon_options.call_args == call(
        hass, "core_zwave_js", {"options": {"device": "/test", "network_key": "abc123"}}
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        await hass.async_block_till_done()

    assert start_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert result["data"] == {
        "url": "ws://host1:3001",
        "usb_path": "/test",
        "network_key": "abc123",
        "use_addon": True,
        "integration_created_addon": False,
    }
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    "discovery_info, start_addon_side_effect",
    [({"config": ADDON_DISCOVERY_INFO}, HassioAPIError())],
)
async def test_addon_installed_start_failure(
    hass,
    supervisor,
    addon_installed,
    addon_options,
    set_addon_options,
    start_addon,
    get_addon_discovery_info,
):
    """Test add-on start failure when add-on is installed."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_path": "/test", "network_key": "abc123"}
    )

    assert set_addon_options.call_args == call(
        hass, "core_zwave_js", {"options": {"device": "/test", "network_key": "abc123"}}
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert start_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "abort"
    assert result["reason"] == "addon_start_failed"


@pytest.mark.parametrize(
    "discovery_info, server_version_side_effect",
    [
        (
            {"config": ADDON_DISCOVERY_INFO},
            asyncio.TimeoutError,
        ),
        (
            None,
            None,
        ),
    ],
)
async def test_addon_installed_failures(
    hass,
    supervisor,
    addon_installed,
    addon_options,
    set_addon_options,
    start_addon,
    get_addon_discovery_info,
):
    """Test all failures when add-on is installed."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_path": "/test", "network_key": "abc123"}
    )

    assert set_addon_options.call_args == call(
        hass, "core_zwave_js", {"options": {"device": "/test", "network_key": "abc123"}}
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert start_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "abort"
    assert result["reason"] == "addon_start_failed"


@pytest.mark.parametrize(
    "set_addon_options_side_effect, discovery_info",
    [(HassioAPIError(), {"config": ADDON_DISCOVERY_INFO})],
)
async def test_addon_installed_set_options_failure(
    hass,
    supervisor,
    addon_installed,
    addon_options,
    set_addon_options,
    start_addon,
    get_addon_discovery_info,
):
    """Test all failures when add-on is installed."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_path": "/test", "network_key": "abc123"}
    )

    assert set_addon_options.call_args == call(
        hass, "core_zwave_js", {"options": {"device": "/test", "network_key": "abc123"}}
    )

    assert result["type"] == "abort"
    assert result["reason"] == "addon_set_config_failed"

    assert start_addon.call_count == 0


@pytest.mark.parametrize("discovery_info", [{"config": ADDON_DISCOVERY_INFO}])
async def test_addon_installed_already_configured(
    hass,
    supervisor,
    addon_installed,
    addon_options,
    set_addon_options,
    start_addon,
    get_addon_discovery_info,
):
    """Test that only one unique instance is allowed when add-on is installed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "url": "ws://localhost:3000",
            "usb_path": "/test",
            "network_key": "abc123",
        },
        title=TITLE,
        unique_id=1234,
    )
    entry.add_to_hass(hass)

    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_path": "/test_new", "network_key": "def456"}
    )

    assert set_addon_options.call_args == call(
        hass,
        "core_zwave_js",
        {"options": {"device": "/test_new", "network_key": "def456"}},
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert start_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    assert entry.data["url"] == "ws://host1:3001"
    assert entry.data["usb_path"] == "/test_new"
    assert entry.data["network_key"] == "def456"


@pytest.mark.parametrize("discovery_info", [{"config": ADDON_DISCOVERY_INFO}])
async def test_addon_not_installed(
    hass,
    supervisor,
    addon_installed,
    install_addon,
    addon_options,
    set_addon_options,
    start_addon,
    get_addon_discovery_info,
):
    """Test add-on not installed."""
    addon_installed.return_value["version"] = None
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "install_addon"

    # Make sure the flow continues when the progress task is done.
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert install_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_path": "/test", "network_key": "abc123"}
    )

    assert set_addon_options.call_args == call(
        hass, "core_zwave_js", {"options": {"device": "/test", "network_key": "abc123"}}
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    with patch(
        "homeassistant.components.zwave_js.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.zwave_js.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        await hass.async_block_till_done()

    assert start_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert result["data"] == {
        "url": "ws://host1:3001",
        "usb_path": "/test",
        "network_key": "abc123",
        "use_addon": True,
        "integration_created_addon": True,
    }
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


async def test_install_addon_failure(hass, supervisor, addon_installed, install_addon):
    """Test add-on install failure."""
    addon_installed.return_value["version"] = None
    install_addon.side_effect = HassioAPIError()
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "progress"

    # Make sure the flow continues when the progress task is done.
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert install_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "abort"
    assert result["reason"] == "addon_install_failed"


async def test_options_manual(hass, client, integration):
    """Test manual settings in options flow."""
    entry = integration
    entry.unique_id = 1234

    assert client.connect.call_count == 1
    assert client.disconnect.call_count == 0

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "manual"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"url": "ws://1.1.1.1:3001"}
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert entry.data["url"] == "ws://1.1.1.1:3001"
    assert entry.data["use_addon"] is False
    assert entry.data["integration_created_addon"] is False
    assert client.connect.call_count == 2
    assert client.disconnect.call_count == 1


async def test_options_manual_different_device(hass, integration):
    """Test options flow manual step connecting to different device."""
    entry = integration
    entry.unique_id = 5678

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "manual"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"url": "ws://1.1.1.1:3001"}
    )
    await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "different_device"


async def test_options_not_addon(hass, client, supervisor, integration):
    """Test options flow and opting out of add-on on Supervisor."""
    entry = integration
    entry.unique_id = 1234

    assert client.connect.call_count == 1
    assert client.disconnect.call_count == 0

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"use_addon": False}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "manual"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "url": "ws://localhost:3000",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert entry.data["url"] == "ws://localhost:3000"
    assert entry.data["use_addon"] is False
    assert entry.data["integration_created_addon"] is False
    assert client.connect.call_count == 2
    assert client.disconnect.call_count == 1


@pytest.mark.parametrize(
    "discovery_info, entry_data, old_addon_options, new_addon_options, disconnect_calls",
    [
        (
            {"config": ADDON_DISCOVERY_INFO},
            {},
            {"device": "/test", "network_key": "abc123"},
            {
                "usb_path": "/new",
                "network_key": "new123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            0,
        ),
        (
            {"config": ADDON_DISCOVERY_INFO},
            {"use_addon": True},
            {"device": "/test", "network_key": "abc123"},
            {
                "usb_path": "/new",
                "network_key": "new123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            1,
        ),
    ],
)
async def test_options_addon_running(
    hass,
    client,
    supervisor,
    integration,
    addon_running,
    addon_options,
    set_addon_options,
    restart_addon,
    get_addon_discovery_info,
    discovery_info,
    entry_data,
    old_addon_options,
    new_addon_options,
    disconnect_calls,
):
    """Test options flow and add-on already running on Supervisor."""
    addon_options.update(old_addon_options)
    entry = integration
    entry.unique_id = 1234
    data = {**entry.data, **entry_data}
    hass.config_entries.async_update_entry(entry, data=data)

    assert entry.data["url"] == "ws://test.org"

    assert client.connect.call_count == 1
    assert client.disconnect.call_count == 0

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        new_addon_options,
    )

    new_addon_options["device"] = new_addon_options.pop("usb_path")
    assert set_addon_options.call_args == call(
        hass,
        "core_zwave_js",
        {"options": new_addon_options},
    )
    assert client.disconnect.call_count == disconnect_calls

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(result["flow_id"])
    await hass.async_block_till_done()

    assert restart_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "create_entry"
    assert entry.data["url"] == "ws://host1:3001"
    assert entry.data["usb_path"] == new_addon_options["device"]
    assert entry.data["network_key"] == new_addon_options["network_key"]
    assert entry.data["use_addon"] is True
    assert entry.data["integration_created_addon"] is False
    assert client.connect.call_count == 2
    assert client.disconnect.call_count == 1


@pytest.mark.parametrize(
    "discovery_info, entry_data, old_addon_options, new_addon_options",
    [
        (
            {"config": ADDON_DISCOVERY_INFO},
            {},
            {
                "device": "/test",
                "network_key": "abc123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            {
                "usb_path": "/test",
                "network_key": "abc123",
                "log_level": "info",
                "emulate_hardware": False,
            },
        ),
    ],
)
async def test_options_addon_running_no_changes(
    hass,
    client,
    supervisor,
    integration,
    addon_running,
    addon_options,
    set_addon_options,
    restart_addon,
    get_addon_discovery_info,
    discovery_info,
    entry_data,
    old_addon_options,
    new_addon_options,
):
    """Test options flow without changes, and add-on already running on Supervisor."""
    addon_options.update(old_addon_options)
    entry = integration
    entry.unique_id = 1234
    data = {**entry.data, **entry_data}
    hass.config_entries.async_update_entry(entry, data=data)

    assert entry.data["url"] == "ws://test.org"

    assert client.connect.call_count == 1
    assert client.disconnect.call_count == 0

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        new_addon_options,
    )
    await hass.async_block_till_done()

    new_addon_options["device"] = new_addon_options.pop("usb_path")
    assert set_addon_options.call_count == 0
    assert restart_addon.call_count == 0

    assert result["type"] == "create_entry"
    assert entry.data["url"] == "ws://host1:3001"
    assert entry.data["usb_path"] == new_addon_options["device"]
    assert entry.data["network_key"] == new_addon_options["network_key"]
    assert entry.data["use_addon"] is True
    assert entry.data["integration_created_addon"] is False
    assert client.connect.call_count == 2
    assert client.disconnect.call_count == 1


async def different_device_server_version(*args):
    """Return server version for a device with different home id."""
    return VersionInfo(
        driver_version="mock-driver-version",
        server_version="mock-server-version",
        home_id=5678,
        min_schema_version=0,
        max_schema_version=1,
    )


@pytest.mark.parametrize(
    "discovery_info, entry_data, old_addon_options, new_addon_options, disconnect_calls, server_version_side_effect",
    [
        (
            {"config": ADDON_DISCOVERY_INFO},
            {},
            {
                "device": "/test",
                "network_key": "abc123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            {
                "usb_path": "/new",
                "network_key": "new123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            0,
            different_device_server_version,
        ),
    ],
)
async def test_options_different_device(
    hass,
    client,
    supervisor,
    integration,
    addon_running,
    addon_options,
    set_addon_options,
    restart_addon,
    get_addon_discovery_info,
    discovery_info,
    entry_data,
    old_addon_options,
    new_addon_options,
    disconnect_calls,
    server_version_side_effect,
):
    """Test options flow and configuring a different device."""
    addon_options.update(old_addon_options)
    entry = integration
    entry.unique_id = 1234
    data = {**entry.data, **entry_data}
    hass.config_entries.async_update_entry(entry, data=data)

    assert entry.data["url"] == "ws://test.org"

    assert client.connect.call_count == 1
    assert client.disconnect.call_count == 0

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        new_addon_options,
    )

    assert set_addon_options.call_count == 1
    new_addon_options["device"] = new_addon_options.pop("usb_path")
    assert set_addon_options.call_args == call(
        hass,
        "core_zwave_js",
        {"options": new_addon_options},
    )
    assert client.disconnect.call_count == disconnect_calls
    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    await hass.async_block_till_done()

    assert restart_addon.call_count == 1
    assert restart_addon.call_args == call(hass, "core_zwave_js")

    result = await hass.config_entries.options.async_configure(result["flow_id"])
    await hass.async_block_till_done()

    assert set_addon_options.call_count == 2
    assert set_addon_options.call_args == call(
        hass,
        "core_zwave_js",
        {"options": old_addon_options},
    )
    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    await hass.async_block_till_done()

    assert restart_addon.call_count == 2
    assert restart_addon.call_args == call(hass, "core_zwave_js")

    result = await hass.config_entries.options.async_configure(result["flow_id"])
    await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "different_device"
    assert entry.data == data
    assert client.connect.call_count == 2
    assert client.disconnect.call_count == 1


@pytest.mark.parametrize(
    "discovery_info, entry_data, old_addon_options, new_addon_options, disconnect_calls, restart_addon_side_effect",
    [
        (
            {"config": ADDON_DISCOVERY_INFO},
            {},
            {
                "device": "/test",
                "network_key": "abc123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            {
                "usb_path": "/new",
                "network_key": "new123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            0,
            [HassioAPIError(), None],
        ),
        (
            {"config": ADDON_DISCOVERY_INFO},
            {},
            {
                "device": "/test",
                "network_key": "abc123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            {
                "usb_path": "/new",
                "network_key": "new123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            0,
            [
                HassioAPIError(),
                HassioAPIError(),
            ],
        ),
    ],
)
async def test_options_addon_restart_failed(
    hass,
    client,
    supervisor,
    integration,
    addon_running,
    addon_options,
    set_addon_options,
    restart_addon,
    get_addon_discovery_info,
    discovery_info,
    entry_data,
    old_addon_options,
    new_addon_options,
    disconnect_calls,
    restart_addon_side_effect,
):
    """Test options flow and add-on restart failure."""
    addon_options.update(old_addon_options)
    entry = integration
    entry.unique_id = 1234
    data = {**entry.data, **entry_data}
    hass.config_entries.async_update_entry(entry, data=data)

    assert entry.data["url"] == "ws://test.org"

    assert client.connect.call_count == 1
    assert client.disconnect.call_count == 0

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        new_addon_options,
    )

    assert set_addon_options.call_count == 1
    new_addon_options["device"] = new_addon_options.pop("usb_path")
    assert set_addon_options.call_args == call(
        hass,
        "core_zwave_js",
        {"options": new_addon_options},
    )
    assert client.disconnect.call_count == disconnect_calls
    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    await hass.async_block_till_done()

    assert restart_addon.call_count == 1
    assert restart_addon.call_args == call(hass, "core_zwave_js")

    result = await hass.config_entries.options.async_configure(result["flow_id"])
    await hass.async_block_till_done()

    assert set_addon_options.call_count == 2
    assert set_addon_options.call_args == call(
        hass,
        "core_zwave_js",
        {"options": old_addon_options},
    )
    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    await hass.async_block_till_done()

    assert restart_addon.call_count == 2
    assert restart_addon.call_args == call(hass, "core_zwave_js")

    result = await hass.config_entries.options.async_configure(result["flow_id"])
    await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "addon_start_failed"
    assert entry.data == data
    assert client.connect.call_count == 2
    assert client.disconnect.call_count == 1


@pytest.mark.parametrize(
    "discovery_info, entry_data, old_addon_options, new_addon_options, disconnect_calls, server_version_side_effect",
    [
        (
            {"config": ADDON_DISCOVERY_INFO},
            {},
            {
                "device": "/test",
                "network_key": "abc123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            {
                "usb_path": "/test",
                "network_key": "abc123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            0,
            aiohttp.ClientError("Boom"),
        ),
    ],
)
async def test_options_addon_running_server_info_failure(
    hass,
    client,
    supervisor,
    integration,
    addon_running,
    addon_options,
    set_addon_options,
    restart_addon,
    get_addon_discovery_info,
    discovery_info,
    entry_data,
    old_addon_options,
    new_addon_options,
    disconnect_calls,
    server_version_side_effect,
):
    """Test options flow and add-on already running with server info failure."""
    addon_options.update(old_addon_options)
    entry = integration
    entry.unique_id = 1234
    data = {**entry.data, **entry_data}
    hass.config_entries.async_update_entry(entry, data=data)

    assert entry.data["url"] == "ws://test.org"

    assert client.connect.call_count == 1
    assert client.disconnect.call_count == 0

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        new_addon_options,
    )
    await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"
    assert entry.data == data
    assert client.connect.call_count == 2
    assert client.disconnect.call_count == 1


@pytest.mark.parametrize(
    "discovery_info, entry_data, old_addon_options, new_addon_options, disconnect_calls",
    [
        (
            {"config": ADDON_DISCOVERY_INFO},
            {},
            {"device": "/test", "network_key": "abc123"},
            {
                "usb_path": "/new",
                "network_key": "new123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            0,
        ),
        (
            {"config": ADDON_DISCOVERY_INFO},
            {"use_addon": True},
            {"device": "/test", "network_key": "abc123"},
            {
                "usb_path": "/new",
                "network_key": "new123",
                "log_level": "info",
                "emulate_hardware": False,
            },
            1,
        ),
    ],
)
async def test_options_addon_not_installed(
    hass,
    client,
    supervisor,
    addon_installed,
    install_addon,
    integration,
    addon_options,
    set_addon_options,
    start_addon,
    get_addon_discovery_info,
    discovery_info,
    entry_data,
    old_addon_options,
    new_addon_options,
    disconnect_calls,
):
    """Test options flow and add-on not installed on Supervisor."""
    addon_installed.return_value["version"] = None
    addon_options.update(old_addon_options)
    entry = integration
    entry.unique_id = 1234
    data = {**entry.data, **entry_data}
    hass.config_entries.async_update_entry(entry, data=data)

    assert entry.data["url"] == "ws://test.org"

    assert client.connect.call_count == 1
    assert client.disconnect.call_count == 0

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "on_supervisor"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"use_addon": True}
    )

    assert result["type"] == "progress"
    assert result["step_id"] == "install_addon"

    # Make sure the flow continues when the progress task is done.
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_configure(result["flow_id"])

    assert install_addon.call_args == call(hass, "core_zwave_js")

    assert result["type"] == "form"
    assert result["step_id"] == "configure_addon"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        new_addon_options,
    )

    new_addon_options["device"] = new_addon_options.pop("usb_path")
    assert set_addon_options.call_args == call(
        hass,
        "core_zwave_js",
        {"options": new_addon_options},
    )
    assert client.disconnect.call_count == disconnect_calls

    assert result["type"] == "progress"
    assert result["step_id"] == "start_addon"

    await hass.async_block_till_done()

    assert start_addon.call_count == 1
    assert start_addon.call_args == call(hass, "core_zwave_js")

    result = await hass.config_entries.options.async_configure(result["flow_id"])
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert entry.data["url"] == "ws://host1:3001"
    assert entry.data["usb_path"] == new_addon_options["device"]
    assert entry.data["network_key"] == new_addon_options["network_key"]
    assert entry.data["use_addon"] is True
    assert entry.data["integration_created_addon"] is True
    assert client.connect.call_count == 2
    assert client.disconnect.call_count == 1

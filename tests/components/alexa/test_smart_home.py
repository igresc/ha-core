"""Test for smart home alexa support."""
import pytest

from homeassistant.core import Context, callback
from homeassistant.const import TEMP_CELSIUS, TEMP_FAHRENHEIT
from homeassistant.components.alexa import smart_home, messages
from homeassistant.components.media_player.const import (
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SEEK,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_STOP,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
)
from homeassistant.helpers import entityfilter

from tests.common import async_mock_service

from . import (
    get_new_request,
    MockConfig,
    DEFAULT_CONFIG,
    assert_request_calls_service,
    assert_request_fails,
    ReportedProperties,
    assert_power_controller_works,
    assert_scene_controller_works,
    reported_properties,
)


@pytest.fixture
def events(hass):
    """Fixture that catches alexa events."""
    events = []
    hass.bus.async_listen(
        smart_home.EVENT_ALEXA_SMART_HOME, callback(lambda e: events.append(e))
    )
    yield events


def test_create_api_message_defaults(hass):
    """Create a API message response of a request with defaults."""
    request = get_new_request("Alexa.PowerController", "TurnOn", "switch#xy")
    directive_header = request["directive"]["header"]
    directive = messages.AlexaDirective(request)

    msg = directive.response(payload={"test": 3})._response

    assert "event" in msg
    msg = msg["event"]

    assert msg["header"]["messageId"] is not None
    assert msg["header"]["messageId"] != directive_header["messageId"]
    assert msg["header"]["correlationToken"] == directive_header["correlationToken"]
    assert msg["header"]["name"] == "Response"
    assert msg["header"]["namespace"] == "Alexa"
    assert msg["header"]["payloadVersion"] == "3"

    assert "test" in msg["payload"]
    assert msg["payload"]["test"] == 3

    assert msg["endpoint"] == request["directive"]["endpoint"]
    assert msg["endpoint"] is not request["directive"]["endpoint"]


def test_create_api_message_special():
    """Create a API message response of a request with non defaults."""
    request = get_new_request("Alexa.PowerController", "TurnOn")
    directive_header = request["directive"]["header"]
    directive_header.pop("correlationToken")
    directive = messages.AlexaDirective(request)

    msg = directive.response("testName", "testNameSpace")._response

    assert "event" in msg
    msg = msg["event"]

    assert msg["header"]["messageId"] is not None
    assert msg["header"]["messageId"] != directive_header["messageId"]
    assert "correlationToken" not in msg["header"]
    assert msg["header"]["name"] == "testName"
    assert msg["header"]["namespace"] == "testNameSpace"
    assert msg["header"]["payloadVersion"] == "3"

    assert msg["payload"] == {}
    assert "endpoint" not in msg


async def test_wrong_version(hass):
    """Test with wrong version."""
    msg = get_new_request("Alexa.PowerController", "TurnOn")
    msg["directive"]["header"]["payloadVersion"] = "2"

    with pytest.raises(AssertionError):
        await smart_home.async_handle_message(hass, DEFAULT_CONFIG, msg)


async def discovery_test(device, hass, expected_endpoints=1):
    """Test alexa discovery request."""
    request = get_new_request("Alexa.Discovery", "Discover")

    # setup test devices
    hass.states.async_set(*device)

    msg = await smart_home.async_handle_message(hass, DEFAULT_CONFIG, request)

    assert "event" in msg
    msg = msg["event"]

    assert msg["header"]["name"] == "Discover.Response"
    assert msg["header"]["namespace"] == "Alexa.Discovery"
    endpoints = msg["payload"]["endpoints"]
    assert len(endpoints) == expected_endpoints

    if expected_endpoints == 1:
        return endpoints[0]
    if expected_endpoints > 1:
        return endpoints
    return None


def get_capability(capabilities, capability_name):
    """Search a set of capabilities for a specific one."""
    for capability in capabilities:
        if capability["interface"] == capability_name:
            return capability

    return None


def assert_endpoint_capabilities(endpoint, *interfaces):
    """Assert the endpoint supports the given interfaces.

    Returns a set of capabilities, in case you want to assert more things about
    them.
    """
    capabilities = endpoint["capabilities"]
    supported = set(feature["interface"] for feature in capabilities)

    assert supported == set(interfaces)
    return capabilities


async def test_switch(hass, events):
    """Test switch discovery."""
    device = ("switch.test", "on", {"friendly_name": "Test switch"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "switch#test"
    assert appliance["displayCategories"][0] == "SWITCH"
    assert appliance["friendlyName"] == "Test switch"
    assert_endpoint_capabilities(
        appliance, "Alexa.PowerController", "Alexa.EndpointHealth", "Alexa"
    )

    await assert_power_controller_works(
        "switch#test", "switch.turn_on", "switch.turn_off", hass
    )

    properties = await reported_properties(hass, "switch#test")
    properties.assert_equal("Alexa.PowerController", "powerState", "ON")


async def test_outlet(hass, events):
    """Test switch with device class outlet discovery."""
    device = (
        "switch.test",
        "on",
        {"friendly_name": "Test switch", "device_class": "outlet"},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "switch#test"
    assert appliance["displayCategories"][0] == "SMARTPLUG"
    assert appliance["friendlyName"] == "Test switch"
    assert_endpoint_capabilities(
        appliance, "Alexa", "Alexa.PowerController", "Alexa.EndpointHealth"
    )


async def test_light(hass):
    """Test light discovery."""
    device = ("light.test_1", "on", {"friendly_name": "Test light 1"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "light#test_1"
    assert appliance["displayCategories"][0] == "LIGHT"
    assert appliance["friendlyName"] == "Test light 1"
    assert_endpoint_capabilities(
        appliance, "Alexa.PowerController", "Alexa.EndpointHealth", "Alexa"
    )

    await assert_power_controller_works(
        "light#test_1", "light.turn_on", "light.turn_off", hass
    )


async def test_dimmable_light(hass):
    """Test dimmable light discovery."""
    device = (
        "light.test_2",
        "on",
        {"brightness": 128, "friendly_name": "Test light 2", "supported_features": 1},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "light#test_2"
    assert appliance["displayCategories"][0] == "LIGHT"
    assert appliance["friendlyName"] == "Test light 2"

    assert_endpoint_capabilities(
        appliance,
        "Alexa.BrightnessController",
        "Alexa.PowerController",
        "Alexa.EndpointHealth",
        "Alexa",
    )

    properties = await reported_properties(hass, "light#test_2")
    properties.assert_equal("Alexa.PowerController", "powerState", "ON")
    properties.assert_equal("Alexa.BrightnessController", "brightness", 50)

    call, _ = await assert_request_calls_service(
        "Alexa.BrightnessController",
        "SetBrightness",
        "light#test_2",
        "light.turn_on",
        hass,
        payload={"brightness": "50"},
    )
    assert call.data["brightness_pct"] == 50


async def test_color_light(hass):
    """Test color light discovery."""
    device = (
        "light.test_3",
        "on",
        {
            "friendly_name": "Test light 3",
            "supported_features": 19,
            "min_mireds": 142,
            "color_temp": "333",
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "light#test_3"
    assert appliance["displayCategories"][0] == "LIGHT"
    assert appliance["friendlyName"] == "Test light 3"

    assert_endpoint_capabilities(
        appliance,
        "Alexa.BrightnessController",
        "Alexa.PowerController",
        "Alexa.ColorController",
        "Alexa.ColorTemperatureController",
        "Alexa.EndpointHealth",
        "Alexa",
    )

    # IncreaseColorTemperature and DecreaseColorTemperature have their own
    # tests


async def test_script(hass):
    """Test script discovery."""
    device = ("script.test", "off", {"friendly_name": "Test script"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "script#test"
    assert appliance["displayCategories"][0] == "ACTIVITY_TRIGGER"
    assert appliance["friendlyName"] == "Test script"

    capabilities = assert_endpoint_capabilities(
        appliance, "Alexa.SceneController", "Alexa"
    )
    scene_capability = get_capability(capabilities, "Alexa.SceneController")
    assert not scene_capability["supportsDeactivation"]

    await assert_scene_controller_works("script#test", "script.turn_on", None, hass)


async def test_cancelable_script(hass):
    """Test cancalable script discovery."""
    device = (
        "script.test_2",
        "off",
        {"friendly_name": "Test script 2", "can_cancel": True},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "script#test_2"
    capabilities = assert_endpoint_capabilities(
        appliance, "Alexa.SceneController", "Alexa"
    )
    scene_capability = get_capability(capabilities, "Alexa.SceneController")
    assert scene_capability["supportsDeactivation"]

    await assert_scene_controller_works(
        "script#test_2", "script.turn_on", "script.turn_off", hass
    )


async def test_input_boolean(hass):
    """Test input boolean discovery."""
    device = ("input_boolean.test", "off", {"friendly_name": "Test input boolean"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "input_boolean#test"
    assert appliance["displayCategories"][0] == "OTHER"
    assert appliance["friendlyName"] == "Test input boolean"
    assert_endpoint_capabilities(
        appliance, "Alexa.PowerController", "Alexa.EndpointHealth", "Alexa"
    )

    await assert_power_controller_works(
        "input_boolean#test", "input_boolean.turn_on", "input_boolean.turn_off", hass
    )


async def test_scene(hass):
    """Test scene discovery."""
    device = ("scene.test", "off", {"friendly_name": "Test scene"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "scene#test"
    assert appliance["displayCategories"][0] == "SCENE_TRIGGER"
    assert appliance["friendlyName"] == "Test scene"

    capabilities = assert_endpoint_capabilities(
        appliance, "Alexa.SceneController", "Alexa"
    )
    scene_capability = get_capability(capabilities, "Alexa.SceneController")
    assert not scene_capability["supportsDeactivation"]

    await assert_scene_controller_works("scene#test", "scene.turn_on", None, hass)


async def test_fan(hass):
    """Test fan discovery."""
    device = ("fan.test_1", "off", {"friendly_name": "Test fan 1"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "fan#test_1"
    assert appliance["displayCategories"][0] == "FAN"
    assert appliance["friendlyName"] == "Test fan 1"
    capabilities = assert_endpoint_capabilities(
        appliance, "Alexa.PowerController", "Alexa.EndpointHealth", "Alexa"
    )

    power_capability = get_capability(capabilities, "Alexa.PowerController")
    assert "capabilityResources" not in power_capability
    assert "configuration" not in power_capability


async def test_variable_fan(hass):
    """Test fan discovery.

    This one has variable speed.
    """
    device = (
        "fan.test_2",
        "off",
        {
            "friendly_name": "Test fan 2",
            "supported_features": 1,
            "speed_list": ["low", "medium", "high"],
            "speed": "high",
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "fan#test_2"
    assert appliance["displayCategories"][0] == "FAN"
    assert appliance["friendlyName"] == "Test fan 2"

    capabilities = assert_endpoint_capabilities(
        appliance,
        "Alexa.PercentageController",
        "Alexa.PowerController",
        "Alexa.PowerLevelController",
        "Alexa.RangeController",
        "Alexa.EndpointHealth",
        "Alexa",
    )

    range_capability = get_capability(capabilities, "Alexa.RangeController")
    assert range_capability is not None
    assert range_capability["instance"] == "fan.speed"

    properties = range_capability["properties"]
    assert properties["nonControllable"] is False
    assert {"name": "rangeValue"} in properties["supported"]

    capability_resources = range_capability["capabilityResources"]
    assert capability_resources is not None
    assert {
        "@type": "asset",
        "value": {"assetId": "Alexa.Setting.FanSpeed"},
    } in capability_resources["friendlyNames"]

    configuration = range_capability["configuration"]
    assert configuration is not None

    call, _ = await assert_request_calls_service(
        "Alexa.PercentageController",
        "SetPercentage",
        "fan#test_2",
        "fan.set_speed",
        hass,
        payload={"percentage": "50"},
    )
    assert call.data["speed"] == "medium"

    await assert_percentage_changes(
        hass,
        [("high", "-5"), ("off", "5"), ("low", "-80")],
        "Alexa.PercentageController",
        "AdjustPercentage",
        "fan#test_2",
        "percentageDelta",
        "fan.set_speed",
        "speed",
    )

    call, _ = await assert_request_calls_service(
        "Alexa.PowerLevelController",
        "SetPowerLevel",
        "fan#test_2",
        "fan.set_speed",
        hass,
        payload={"powerLevel": "50"},
    )
    assert call.data["speed"] == "medium"

    await assert_percentage_changes(
        hass,
        [("high", "-5"), ("medium", "-50"), ("low", "-80")],
        "Alexa.PowerLevelController",
        "AdjustPowerLevel",
        "fan#test_2",
        "powerLevelDelta",
        "fan.set_speed",
        "speed",
    )


async def test_oscillating_fan(hass):
    """Test oscillating fan discovery."""
    device = (
        "fan.test_3",
        "off",
        {"friendly_name": "Test fan 3", "supported_features": 3},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "fan#test_3"
    assert appliance["displayCategories"][0] == "FAN"
    assert appliance["friendlyName"] == "Test fan 3"
    capabilities = assert_endpoint_capabilities(
        appliance,
        "Alexa.PercentageController",
        "Alexa.PowerController",
        "Alexa.PowerLevelController",
        "Alexa.RangeController",
        "Alexa.ToggleController",
        "Alexa.EndpointHealth",
        "Alexa",
    )

    toggle_capability = get_capability(capabilities, "Alexa.ToggleController")
    assert toggle_capability is not None
    assert toggle_capability["instance"] == "fan.oscillating"

    properties = toggle_capability["properties"]
    assert properties["nonControllable"] is False
    assert {"name": "toggleState"} in properties["supported"]

    capability_resources = toggle_capability["capabilityResources"]
    assert capability_resources is not None
    assert {
        "@type": "asset",
        "value": {"assetId": "Alexa.Setting.Oscillate"},
    } in capability_resources["friendlyNames"]

    call, _ = await assert_request_calls_service(
        "Alexa.ToggleController",
        "TurnOn",
        "fan#test_3",
        "fan.oscillate",
        hass,
        payload={},
        instance="fan.oscillating",
    )
    assert call.data["oscillating"]

    call, _ = await assert_request_calls_service(
        "Alexa.ToggleController",
        "TurnOff",
        "fan#test_3",
        "fan.oscillate",
        hass,
        payload={},
        instance="fan.oscillating",
    )
    assert not call.data["oscillating"]


async def test_direction_fan(hass):
    """Test direction fan discovery."""
    device = (
        "fan.test_4",
        "on",
        {
            "friendly_name": "Test fan 4",
            "supported_features": 5,
            "direction": "forward",
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "fan#test_4"
    assert appliance["displayCategories"][0] == "FAN"
    assert appliance["friendlyName"] == "Test fan 4"
    capabilities = assert_endpoint_capabilities(
        appliance,
        "Alexa.PercentageController",
        "Alexa.PowerController",
        "Alexa.PowerLevelController",
        "Alexa.RangeController",
        "Alexa.ModeController",
        "Alexa.EndpointHealth",
        "Alexa",
    )

    mode_capability = get_capability(capabilities, "Alexa.ModeController")
    assert mode_capability is not None
    assert mode_capability["instance"] == "fan.direction"

    properties = mode_capability["properties"]
    assert properties["nonControllable"] is False
    assert {"name": "mode"} in properties["supported"]

    capability_resources = mode_capability["capabilityResources"]
    assert capability_resources is not None
    assert {
        "@type": "asset",
        "value": {"assetId": "Alexa.Setting.Direction"},
    } in capability_resources["friendlyNames"]

    configuration = mode_capability["configuration"]
    assert configuration is not None
    assert configuration["ordered"] is False

    supported_modes = configuration["supportedModes"]
    assert supported_modes is not None
    assert {
        "value": "direction.forward",
        "modeResources": {
            "friendlyNames": [
                {"@type": "text", "value": {"text": "forward", "locale": "en-US"}}
            ]
        },
    } in supported_modes
    assert {
        "value": "direction.reverse",
        "modeResources": {
            "friendlyNames": [
                {"@type": "text", "value": {"text": "reverse", "locale": "en-US"}}
            ]
        },
    } in supported_modes

    call, msg = await assert_request_calls_service(
        "Alexa.ModeController",
        "SetMode",
        "fan#test_4",
        "fan.set_direction",
        hass,
        payload={"mode": "direction.reverse"},
        instance="fan.direction",
    )
    assert call.data["direction"] == "reverse"
    properties = msg["context"]["properties"][0]
    assert properties["name"] == "mode"
    assert properties["namespace"] == "Alexa.ModeController"
    assert properties["value"] == "direction.reverse"

    call, msg = await assert_request_calls_service(
        "Alexa.ModeController",
        "SetMode",
        "fan#test_4",
        "fan.set_direction",
        hass,
        payload={"mode": "direction.forward"},
        instance="fan.direction",
    )
    assert call.data["direction"] == "forward"
    properties = msg["context"]["properties"][0]
    assert properties["name"] == "mode"
    assert properties["namespace"] == "Alexa.ModeController"
    assert properties["value"] == "direction.forward"

    # Test for AdjustMode instance=None Error coverage
    with pytest.raises(AssertionError):
        call, _ = await assert_request_calls_service(
            "Alexa.ModeController",
            "AdjustMode",
            "fan#test_4",
            "fan.set_direction",
            hass,
            payload={},
            instance=None,
        )
        assert call.data


async def test_fan_range(hass):
    """Test fan discovery with range controller.

    This one has variable speed.
    """
    device = (
        "fan.test_5",
        "off",
        {
            "friendly_name": "Test fan 5",
            "supported_features": 1,
            "speed_list": ["low", "medium", "high"],
            "speed": "medium",
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "fan#test_5"
    assert appliance["displayCategories"][0] == "FAN"
    assert appliance["friendlyName"] == "Test fan 5"

    capabilities = assert_endpoint_capabilities(
        appliance,
        "Alexa.PercentageController",
        "Alexa.PowerController",
        "Alexa.PowerLevelController",
        "Alexa.RangeController",
        "Alexa.EndpointHealth",
        "Alexa",
    )

    range_capability = get_capability(capabilities, "Alexa.RangeController")
    assert range_capability is not None
    assert range_capability["instance"] == "fan.speed"

    call, _ = await assert_request_calls_service(
        "Alexa.RangeController",
        "SetRangeValue",
        "fan#test_5",
        "fan.set_speed",
        hass,
        payload={"rangeValue": "1"},
        instance="fan.speed",
    )
    assert call.data["speed"] == "low"

    await assert_range_changes(
        hass,
        [("low", "-1"), ("high", "1"), ("medium", "0")],
        "Alexa.RangeController",
        "AdjustRangeValue",
        "fan#test_5",
        False,
        "fan.set_speed",
        "speed",
        instance="fan.speed",
    )


async def test_fan_range_off(hass):
    """Test fan range controller 0 turns_off fan."""
    device = (
        "fan.test_6",
        "off",
        {
            "friendly_name": "Test fan 6",
            "supported_features": 1,
            "speed_list": ["low", "medium", "high"],
            "speed": "high",
        },
    )
    await discovery_test(device, hass)

    call, _ = await assert_request_calls_service(
        "Alexa.RangeController",
        "SetRangeValue",
        "fan#test_6",
        "fan.turn_off",
        hass,
        payload={"rangeValue": "0"},
        instance="fan.speed",
    )
    assert call.data["speed"] == "off"

    await assert_range_changes(
        hass,
        [("off", "-3")],
        "Alexa.RangeController",
        "AdjustRangeValue",
        "fan#test_6",
        False,
        "fan.turn_off",
        "speed",
        instance="fan.speed",
    )


async def test_lock(hass):
    """Test lock discovery."""
    device = ("lock.test", "off", {"friendly_name": "Test lock"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "lock#test"
    assert appliance["displayCategories"][0] == "SMARTLOCK"
    assert appliance["friendlyName"] == "Test lock"
    assert_endpoint_capabilities(
        appliance, "Alexa.LockController", "Alexa.EndpointHealth", "Alexa"
    )

    _, msg = await assert_request_calls_service(
        "Alexa.LockController", "Lock", "lock#test", "lock.lock", hass
    )

    properties = msg["context"]["properties"][0]
    assert properties["name"] == "lockState"
    assert properties["namespace"] == "Alexa.LockController"
    assert properties["value"] == "LOCKED"

    _, msg = await assert_request_calls_service(
        "Alexa.LockController", "Unlock", "lock#test", "lock.unlock", hass
    )

    properties = msg["context"]["properties"][0]
    assert properties["name"] == "lockState"
    assert properties["namespace"] == "Alexa.LockController"
    assert properties["value"] == "UNLOCKED"


async def test_media_player(hass):
    """Test media player discovery."""
    device = (
        "media_player.test",
        "off",
        {
            "friendly_name": "Test media player",
            "supported_features": SUPPORT_NEXT_TRACK
            | SUPPORT_PAUSE
            | SUPPORT_PLAY
            | SUPPORT_PLAY_MEDIA
            | SUPPORT_PREVIOUS_TRACK
            | SUPPORT_SELECT_SOURCE
            | SUPPORT_STOP
            | SUPPORT_TURN_OFF
            | SUPPORT_TURN_ON
            | SUPPORT_VOLUME_MUTE
            | SUPPORT_VOLUME_SET,
            "volume_level": 0.75,
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "media_player#test"
    assert appliance["displayCategories"][0] == "TV"
    assert appliance["friendlyName"] == "Test media player"

    capabilities = assert_endpoint_capabilities(
        appliance,
        "Alexa",
        "Alexa.ChannelController",
        "Alexa.EndpointHealth",
        "Alexa.InputController",
        "Alexa.PlaybackController",
        "Alexa.PlaybackStateReporter",
        "Alexa.PowerController",
        "Alexa.Speaker",
        "Alexa.StepSpeaker",
    )

    playback_capability = get_capability(capabilities, "Alexa.PlaybackController")
    assert playback_capability is not None
    supported_operations = playback_capability["supportedOperations"]
    operations = ["Play", "Pause", "Stop", "Next", "Previous"]
    for operation in operations:
        assert operation in supported_operations

    await assert_power_controller_works(
        "media_player#test", "media_player.turn_on", "media_player.turn_off", hass
    )

    await assert_request_calls_service(
        "Alexa.PlaybackController",
        "Play",
        "media_player#test",
        "media_player.media_play",
        hass,
    )

    await assert_request_calls_service(
        "Alexa.PlaybackController",
        "Pause",
        "media_player#test",
        "media_player.media_pause",
        hass,
    )

    await assert_request_calls_service(
        "Alexa.PlaybackController",
        "Stop",
        "media_player#test",
        "media_player.media_stop",
        hass,
    )

    await assert_request_calls_service(
        "Alexa.PlaybackController",
        "Next",
        "media_player#test",
        "media_player.media_next_track",
        hass,
    )

    await assert_request_calls_service(
        "Alexa.PlaybackController",
        "Previous",
        "media_player#test",
        "media_player.media_previous_track",
        hass,
    )

    call, _ = await assert_request_calls_service(
        "Alexa.Speaker",
        "SetVolume",
        "media_player#test",
        "media_player.volume_set",
        hass,
        payload={"volume": 50},
    )
    assert call.data["volume_level"] == 0.5

    call, _ = await assert_request_calls_service(
        "Alexa.Speaker",
        "SetMute",
        "media_player#test",
        "media_player.volume_mute",
        hass,
        payload={"mute": True},
    )
    assert call.data["is_volume_muted"]

    call, _, = await assert_request_calls_service(
        "Alexa.Speaker",
        "SetMute",
        "media_player#test",
        "media_player.volume_mute",
        hass,
        payload={"mute": False},
    )
    assert not call.data["is_volume_muted"]

    await assert_percentage_changes(
        hass,
        [(0.7, "-5"), (0.8, "5"), (0, "-80")],
        "Alexa.Speaker",
        "AdjustVolume",
        "media_player#test",
        "volume",
        "media_player.volume_set",
        "volume_level",
    )

    call, _ = await assert_request_calls_service(
        "Alexa.StepSpeaker",
        "SetMute",
        "media_player#test",
        "media_player.volume_mute",
        hass,
        payload={"mute": True},
    )
    assert call.data["is_volume_muted"]

    call, _, = await assert_request_calls_service(
        "Alexa.StepSpeaker",
        "SetMute",
        "media_player#test",
        "media_player.volume_mute",
        hass,
        payload={"mute": False},
    )
    assert not call.data["is_volume_muted"]

    call, _ = await assert_request_calls_service(
        "Alexa.StepSpeaker",
        "AdjustVolume",
        "media_player#test",
        "media_player.volume_up",
        hass,
        payload={"volumeSteps": 1, "volumeStepsDefault": False},
    )

    call, _ = await assert_request_calls_service(
        "Alexa.StepSpeaker",
        "AdjustVolume",
        "media_player#test",
        "media_player.volume_down",
        hass,
        payload={"volumeSteps": -1, "volumeStepsDefault": False},
    )

    call, _ = await assert_request_calls_service(
        "Alexa.StepSpeaker",
        "AdjustVolume",
        "media_player#test",
        "media_player.volume_up",
        hass,
        payload={"volumeSteps": 10, "volumeStepsDefault": True},
    )
    call, _ = await assert_request_calls_service(
        "Alexa.ChannelController",
        "ChangeChannel",
        "media_player#test",
        "media_player.play_media",
        hass,
        payload={"channel": {"number": 24}},
    )

    call, _ = await assert_request_calls_service(
        "Alexa.ChannelController",
        "ChangeChannel",
        "media_player#test",
        "media_player.play_media",
        hass,
        payload={"channel": {"callSign": "ABC"}},
    )

    call, _ = await assert_request_calls_service(
        "Alexa.ChannelController",
        "ChangeChannel",
        "media_player#test",
        "media_player.play_media",
        hass,
        payload={"channel": {"affiliateCallSign": "ABC"}},
    )

    call, _ = await assert_request_calls_service(
        "Alexa.ChannelController",
        "ChangeChannel",
        "media_player#test",
        "media_player.play_media",
        hass,
        payload={"channel": {"uri": "ABC"}},
    )

    call, _ = await assert_request_calls_service(
        "Alexa.ChannelController",
        "SkipChannels",
        "media_player#test",
        "media_player.media_next_track",
        hass,
        payload={"channelCount": 1},
    )

    call, _ = await assert_request_calls_service(
        "Alexa.ChannelController",
        "SkipChannels",
        "media_player#test",
        "media_player.media_previous_track",
        hass,
        payload={"channelCount": -1},
    )


async def test_media_player_power(hass):
    """Test media player discovery with mapped on/off."""
    device = (
        "media_player.test",
        "off",
        {
            "friendly_name": "Test media player",
            "supported_features": 0xFA3F,
            "volume_level": 0.75,
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "media_player#test"
    assert appliance["displayCategories"][0] == "TV"
    assert appliance["friendlyName"] == "Test media player"

    assert_endpoint_capabilities(
        appliance,
        "Alexa",
        "Alexa.ChannelController",
        "Alexa.EndpointHealth",
        "Alexa.InputController",
        "Alexa.PlaybackController",
        "Alexa.PlaybackStateReporter",
        "Alexa.PowerController",
        "Alexa.SeekController",
        "Alexa.Speaker",
        "Alexa.StepSpeaker",
    )

    await assert_request_calls_service(
        "Alexa.PowerController",
        "TurnOn",
        "media_player#test",
        "media_player.media_play",
        hass,
    )

    await assert_request_calls_service(
        "Alexa.PowerController",
        "TurnOff",
        "media_player#test",
        "media_player.media_stop",
        hass,
    )


async def test_media_player_inputs(hass):
    """Test media player discovery with source list inputs."""
    device = (
        "media_player.test",
        "on",
        {
            "friendly_name": "Test media player",
            "supported_features": SUPPORT_SELECT_SOURCE,
            "volume_level": 0.75,
            "source_list": [
                "foo",
                "foo_2",
                "hdmi",
                "hdmi_2",
                "hdmi-3",
                "hdmi4",
                "hdmi 5",
                "HDMI 6",
                "hdmi_arc",
                "aux",
                "input 1",
                "tv",
            ],
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "media_player#test"
    assert appliance["displayCategories"][0] == "TV"
    assert appliance["friendlyName"] == "Test media player"

    capabilities = assert_endpoint_capabilities(
        appliance,
        "Alexa",
        "Alexa.InputController",
        "Alexa.PowerController",
        "Alexa.EndpointHealth",
    )

    input_capability = get_capability(capabilities, "Alexa.InputController")
    assert input_capability is not None
    assert {"name": "AUX"} not in input_capability["inputs"]
    assert {"name": "AUX 1"} in input_capability["inputs"]
    assert {"name": "HDMI 1"} in input_capability["inputs"]
    assert {"name": "HDMI 2"} in input_capability["inputs"]
    assert {"name": "HDMI 3"} in input_capability["inputs"]
    assert {"name": "HDMI 4"} in input_capability["inputs"]
    assert {"name": "HDMI 5"} in input_capability["inputs"]
    assert {"name": "HDMI 6"} in input_capability["inputs"]
    assert {"name": "HDMI ARC"} in input_capability["inputs"]
    assert {"name": "FOO 1"} not in input_capability["inputs"]
    assert {"name": "TV"} in input_capability["inputs"]

    call, _ = await assert_request_calls_service(
        "Alexa.InputController",
        "SelectInput",
        "media_player#test",
        "media_player.select_source",
        hass,
        payload={"input": "HDMI 1"},
    )
    assert call.data["source"] == "hdmi"

    call, _ = await assert_request_calls_service(
        "Alexa.InputController",
        "SelectInput",
        "media_player#test",
        "media_player.select_source",
        hass,
        payload={"input": "HDMI 2"},
    )
    assert call.data["source"] == "hdmi_2"

    call, _ = await assert_request_calls_service(
        "Alexa.InputController",
        "SelectInput",
        "media_player#test",
        "media_player.select_source",
        hass,
        payload={"input": "HDMI 5"},
    )
    assert call.data["source"] == "hdmi 5"

    call, _ = await assert_request_calls_service(
        "Alexa.InputController",
        "SelectInput",
        "media_player#test",
        "media_player.select_source",
        hass,
        payload={"input": "HDMI 6"},
    )
    assert call.data["source"] == "HDMI 6"

    call, _ = await assert_request_calls_service(
        "Alexa.InputController",
        "SelectInput",
        "media_player#test",
        "media_player.select_source",
        hass,
        payload={"input": "TV"},
    )
    assert call.data["source"] == "tv"


async def test_media_player_speaker(hass):
    """Test media player discovery with device class speaker."""
    device = (
        "media_player.test",
        "off",
        {
            "friendly_name": "Test media player",
            "supported_features": 51765,
            "volume_level": 0.75,
            "device_class": "speaker",
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "media_player#test"
    assert appliance["displayCategories"][0] == "SPEAKER"
    assert appliance["friendlyName"] == "Test media player"


async def test_media_player_seek(hass):
    """Test media player seek capability."""
    device = (
        "media_player.test_seek",
        "playing",
        {
            "friendly_name": "Test media player seek",
            "supported_features": SUPPORT_SEEK,
            "media_position": 300,  # 5min
            "media_duration": 600,  # 10min
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "media_player#test_seek"
    assert appliance["displayCategories"][0] == "TV"
    assert appliance["friendlyName"] == "Test media player seek"

    assert_endpoint_capabilities(
        appliance,
        "Alexa",
        "Alexa.EndpointHealth",
        "Alexa.PowerController",
        "Alexa.SeekController",
    )

    # Test seek forward 30 seconds.
    call, msg = await assert_request_calls_service(
        "Alexa.SeekController",
        "AdjustSeekPosition",
        "media_player#test_seek",
        "media_player.media_seek",
        hass,
        response_type="StateReport",
        payload={"deltaPositionMilliseconds": 30000},
    )
    assert call.data["seek_position"] == 330
    assert "properties" in msg["event"]["payload"]
    properties = msg["event"]["payload"]["properties"]
    assert {"name": "positionMilliseconds", "value": 330000} in properties

    # Test seek reverse 30 seconds.
    call, msg = await assert_request_calls_service(
        "Alexa.SeekController",
        "AdjustSeekPosition",
        "media_player#test_seek",
        "media_player.media_seek",
        hass,
        response_type="StateReport",
        payload={"deltaPositionMilliseconds": -30000},
    )
    assert call.data["seek_position"] == 270
    assert "properties" in msg["event"]["payload"]
    properties = msg["event"]["payload"]["properties"]
    assert {"name": "positionMilliseconds", "value": 270000} in properties

    # Test seek backwards more than current position (5 min.) result = 0.
    call, msg = await assert_request_calls_service(
        "Alexa.SeekController",
        "AdjustSeekPosition",
        "media_player#test_seek",
        "media_player.media_seek",
        hass,
        response_type="StateReport",
        payload={"deltaPositionMilliseconds": -500000},
    )
    assert call.data["seek_position"] == 0
    assert "properties" in msg["event"]["payload"]
    properties = msg["event"]["payload"]["properties"]
    assert {"name": "positionMilliseconds", "value": 0} in properties

    # Test seek forward more than current duration (10 min.) result = 600 sec.
    call, msg = await assert_request_calls_service(
        "Alexa.SeekController",
        "AdjustSeekPosition",
        "media_player#test_seek",
        "media_player.media_seek",
        hass,
        response_type="StateReport",
        payload={"deltaPositionMilliseconds": 800000},
    )
    assert call.data["seek_position"] == 600
    assert "properties" in msg["event"]["payload"]
    properties = msg["event"]["payload"]["properties"]
    assert {"name": "positionMilliseconds", "value": 600000} in properties


async def test_media_player_seek_error(hass):
    """Test media player seek capability for media_position Error."""
    device = (
        "media_player.test_seek",
        "playing",
        {"friendly_name": "Test media player seek", "supported_features": SUPPORT_SEEK},
    )
    await discovery_test(device, hass)

    # Test for media_position error.
    with pytest.raises(AssertionError):
        call, msg = await assert_request_calls_service(
            "Alexa.SeekController",
            "AdjustSeekPosition",
            "media_player#test_seek",
            "media_player.media_seek",
            hass,
            response_type="StateReport",
            payload={"deltaPositionMilliseconds": 30000},
        )

        assert "event" in msg
        msg = msg["event"]
        assert msg["header"]["name"] == "ErrorResponse"
        assert msg["header"]["namespace"] == "Alexa.Video"
        assert msg["payload"]["type"] == "ACTION_NOT_PERMITTED_FOR_CONTENT"


async def test_alert(hass):
    """Test alert discovery."""
    device = ("alert.test", "off", {"friendly_name": "Test alert"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "alert#test"
    assert appliance["displayCategories"][0] == "OTHER"
    assert appliance["friendlyName"] == "Test alert"
    assert_endpoint_capabilities(
        appliance, "Alexa.PowerController", "Alexa.EndpointHealth", "Alexa"
    )

    await assert_power_controller_works(
        "alert#test", "alert.turn_on", "alert.turn_off", hass
    )


async def test_automation(hass):
    """Test automation discovery."""
    device = ("automation.test", "off", {"friendly_name": "Test automation"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "automation#test"
    assert appliance["displayCategories"][0] == "OTHER"
    assert appliance["friendlyName"] == "Test automation"
    assert_endpoint_capabilities(
        appliance, "Alexa.PowerController", "Alexa.EndpointHealth", "Alexa"
    )

    await assert_power_controller_works(
        "automation#test", "automation.turn_on", "automation.turn_off", hass
    )


async def test_group(hass):
    """Test group discovery."""
    device = ("group.test", "off", {"friendly_name": "Test group"})
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "group#test"
    assert appliance["displayCategories"][0] == "OTHER"
    assert appliance["friendlyName"] == "Test group"
    assert_endpoint_capabilities(
        appliance, "Alexa.PowerController", "Alexa.EndpointHealth", "Alexa"
    )

    await assert_power_controller_works(
        "group#test", "homeassistant.turn_on", "homeassistant.turn_off", hass
    )


async def test_cover(hass):
    """Test cover discovery."""
    device = (
        "cover.test",
        "off",
        {"friendly_name": "Test cover", "supported_features": 255, "position": 30},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "cover#test"
    assert appliance["displayCategories"][0] == "OTHER"
    assert appliance["friendlyName"] == "Test cover"

    assert_endpoint_capabilities(
        appliance,
        "Alexa.ModeController",
        "Alexa.PercentageController",
        "Alexa.PowerController",
        "Alexa.EndpointHealth",
        "Alexa",
    )

    await assert_power_controller_works(
        "cover#test", "cover.open_cover", "cover.close_cover", hass
    )

    call, _ = await assert_request_calls_service(
        "Alexa.PercentageController",
        "SetPercentage",
        "cover#test",
        "cover.set_cover_position",
        hass,
        payload={"percentage": "50"},
    )
    assert call.data["position"] == 50

    await assert_percentage_changes(
        hass,
        [(25, "-5"), (35, "5"), (0, "-80")],
        "Alexa.PercentageController",
        "AdjustPercentage",
        "cover#test",
        "percentageDelta",
        "cover.set_cover_position",
        "position",
    )


async def assert_percentage_changes(
    hass, adjustments, namespace, name, endpoint, parameter, service, changed_parameter
):
    """Assert an API request making percentage changes works.

    AdjustPercentage, AdjustBrightness, etc. are examples of such requests.
    """
    for result_volume, adjustment in adjustments:
        if parameter:
            payload = {parameter: adjustment}
        else:
            payload = {}

        call, _ = await assert_request_calls_service(
            namespace, name, endpoint, service, hass, payload=payload
        )
        assert call.data[changed_parameter] == result_volume


async def assert_range_changes(
    hass,
    adjustments,
    namespace,
    name,
    endpoint,
    delta_default,
    service,
    changed_parameter,
    instance,
):
    """Assert an API request making range changes works.

    AdjustRangeValue are examples of such requests.
    """
    for result_range, adjustment in adjustments:
        payload = {
            "rangeValueDelta": adjustment,
            "rangeValueDeltaDefault": delta_default,
        }

        call, _ = await assert_request_calls_service(
            namespace, name, endpoint, service, hass, payload=payload, instance=instance
        )
        assert call.data[changed_parameter] == result_range


async def test_temp_sensor(hass):
    """Test temperature sensor discovery."""
    device = (
        "sensor.test_temp",
        "42",
        {"friendly_name": "Test Temp Sensor", "unit_of_measurement": TEMP_FAHRENHEIT},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "sensor#test_temp"
    assert appliance["displayCategories"][0] == "TEMPERATURE_SENSOR"
    assert appliance["friendlyName"] == "Test Temp Sensor"

    capabilities = assert_endpoint_capabilities(
        appliance, "Alexa.TemperatureSensor", "Alexa.EndpointHealth", "Alexa"
    )

    temp_sensor_capability = get_capability(capabilities, "Alexa.TemperatureSensor")
    assert temp_sensor_capability is not None
    properties = temp_sensor_capability["properties"]
    assert properties["retrievable"] is True
    assert {"name": "temperature"} in properties["supported"]

    properties = await reported_properties(hass, "sensor#test_temp")
    properties.assert_equal(
        "Alexa.TemperatureSensor", "temperature", {"value": 42.0, "scale": "FAHRENHEIT"}
    )


async def test_contact_sensor(hass):
    """Test contact sensor discovery."""
    device = (
        "binary_sensor.test_contact",
        "on",
        {"friendly_name": "Test Contact Sensor", "device_class": "door"},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "binary_sensor#test_contact"
    assert appliance["displayCategories"][0] == "CONTACT_SENSOR"
    assert appliance["friendlyName"] == "Test Contact Sensor"

    capabilities = assert_endpoint_capabilities(
        appliance, "Alexa.ContactSensor", "Alexa.EndpointHealth", "Alexa"
    )

    contact_sensor_capability = get_capability(capabilities, "Alexa.ContactSensor")
    assert contact_sensor_capability is not None
    properties = contact_sensor_capability["properties"]
    assert properties["retrievable"] is True
    assert {"name": "detectionState"} in properties["supported"]

    properties = await reported_properties(hass, "binary_sensor#test_contact")
    properties.assert_equal("Alexa.ContactSensor", "detectionState", "DETECTED")

    properties.assert_equal("Alexa.EndpointHealth", "connectivity", {"value": "OK"})


async def test_motion_sensor(hass):
    """Test motion sensor discovery."""
    device = (
        "binary_sensor.test_motion",
        "on",
        {"friendly_name": "Test Motion Sensor", "device_class": "motion"},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "binary_sensor#test_motion"
    assert appliance["displayCategories"][0] == "MOTION_SENSOR"
    assert appliance["friendlyName"] == "Test Motion Sensor"

    capabilities = assert_endpoint_capabilities(
        appliance, "Alexa.MotionSensor", "Alexa.EndpointHealth", "Alexa"
    )

    motion_sensor_capability = get_capability(capabilities, "Alexa.MotionSensor")
    assert motion_sensor_capability is not None
    properties = motion_sensor_capability["properties"]
    assert properties["retrievable"] is True
    assert {"name": "detectionState"} in properties["supported"]

    properties = await reported_properties(hass, "binary_sensor#test_motion")
    properties.assert_equal("Alexa.MotionSensor", "detectionState", "DETECTED")


async def test_doorbell_sensor(hass):
    """Test doorbell sensor discovery."""
    device = (
        "binary_sensor.test_doorbell",
        "off",
        {"friendly_name": "Test Doorbell Sensor", "device_class": "occupancy"},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "binary_sensor#test_doorbell"
    assert appliance["displayCategories"][0] == "DOORBELL"
    assert appliance["friendlyName"] == "Test Doorbell Sensor"

    capabilities = assert_endpoint_capabilities(
        appliance, "Alexa.DoorbellEventSource", "Alexa.EndpointHealth", "Alexa"
    )

    doorbell_capability = get_capability(capabilities, "Alexa.DoorbellEventSource")
    assert doorbell_capability is not None
    assert doorbell_capability["proactivelyReported"] is True


async def test_unknown_sensor(hass):
    """Test sensors of unknown quantities are not discovered."""
    device = (
        "sensor.test_sickness",
        "0.1",
        {"friendly_name": "Test Space Sickness Sensor", "unit_of_measurement": "garn"},
    )
    await discovery_test(device, hass, expected_endpoints=0)


async def test_thermostat(hass):
    """Test thermostat discovery."""
    hass.config.units.temperature_unit = TEMP_FAHRENHEIT
    device = (
        "climate.test_thermostat",
        "cool",
        {
            "temperature": 70.0,
            "target_temp_high": 80.0,
            "target_temp_low": 60.0,
            "current_temperature": 75.0,
            "friendly_name": "Test Thermostat",
            "supported_features": 1 | 2 | 4 | 128,
            "hvac_modes": ["off", "heat", "cool", "auto", "dry"],
            "preset_mode": None,
            "preset_modes": ["eco"],
            "min_temp": 50,
            "max_temp": 90,
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "climate#test_thermostat"
    assert appliance["displayCategories"][0] == "THERMOSTAT"
    assert appliance["friendlyName"] == "Test Thermostat"

    capabilities = assert_endpoint_capabilities(
        appliance,
        "Alexa.PowerController",
        "Alexa.ThermostatController",
        "Alexa.TemperatureSensor",
        "Alexa.EndpointHealth",
        "Alexa",
    )

    properties = await reported_properties(hass, "climate#test_thermostat")
    properties.assert_equal("Alexa.ThermostatController", "thermostatMode", "COOL")
    properties.assert_equal(
        "Alexa.ThermostatController",
        "targetSetpoint",
        {"value": 70.0, "scale": "FAHRENHEIT"},
    )
    properties.assert_equal(
        "Alexa.TemperatureSensor", "temperature", {"value": 75.0, "scale": "FAHRENHEIT"}
    )

    thermostat_capability = get_capability(capabilities, "Alexa.ThermostatController")
    assert thermostat_capability is not None
    configuration = thermostat_capability["configuration"]
    assert configuration["supportsScheduling"] is False

    supported_modes = ["OFF", "HEAT", "COOL", "AUTO", "ECO", "CUSTOM"]
    for mode in supported_modes:
        assert mode in configuration["supportedModes"]

    call, msg = await assert_request_calls_service(
        "Alexa.ThermostatController",
        "SetTargetTemperature",
        "climate#test_thermostat",
        "climate.set_temperature",
        hass,
        payload={"targetSetpoint": {"value": 69.0, "scale": "FAHRENHEIT"}},
    )
    assert call.data["temperature"] == 69.0
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal(
        "Alexa.ThermostatController",
        "targetSetpoint",
        {"value": 69.0, "scale": "FAHRENHEIT"},
    )

    msg = await assert_request_fails(
        "Alexa.ThermostatController",
        "SetTargetTemperature",
        "climate#test_thermostat",
        "climate.set_temperature",
        hass,
        payload={"targetSetpoint": {"value": 0.0, "scale": "CELSIUS"}},
    )
    assert msg["event"]["payload"]["type"] == "TEMPERATURE_VALUE_OUT_OF_RANGE"

    call, msg = await assert_request_calls_service(
        "Alexa.ThermostatController",
        "SetTargetTemperature",
        "climate#test_thermostat",
        "climate.set_temperature",
        hass,
        payload={
            "targetSetpoint": {"value": 70.0, "scale": "FAHRENHEIT"},
            "lowerSetpoint": {"value": 293.15, "scale": "KELVIN"},
            "upperSetpoint": {"value": 30.0, "scale": "CELSIUS"},
        },
    )
    assert call.data["temperature"] == 70.0
    assert call.data["target_temp_low"] == 68.0
    assert call.data["target_temp_high"] == 86.0
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal(
        "Alexa.ThermostatController",
        "targetSetpoint",
        {"value": 70.0, "scale": "FAHRENHEIT"},
    )
    properties.assert_equal(
        "Alexa.ThermostatController",
        "lowerSetpoint",
        {"value": 68.0, "scale": "FAHRENHEIT"},
    )
    properties.assert_equal(
        "Alexa.ThermostatController",
        "upperSetpoint",
        {"value": 86.0, "scale": "FAHRENHEIT"},
    )

    msg = await assert_request_fails(
        "Alexa.ThermostatController",
        "SetTargetTemperature",
        "climate#test_thermostat",
        "climate.set_temperature",
        hass,
        payload={
            "lowerSetpoint": {"value": 273.15, "scale": "KELVIN"},
            "upperSetpoint": {"value": 75.0, "scale": "FAHRENHEIT"},
        },
    )
    assert msg["event"]["payload"]["type"] == "TEMPERATURE_VALUE_OUT_OF_RANGE"

    msg = await assert_request_fails(
        "Alexa.ThermostatController",
        "SetTargetTemperature",
        "climate#test_thermostat",
        "climate.set_temperature",
        hass,
        payload={
            "lowerSetpoint": {"value": 293.15, "scale": "FAHRENHEIT"},
            "upperSetpoint": {"value": 75.0, "scale": "CELSIUS"},
        },
    )
    assert msg["event"]["payload"]["type"] == "TEMPERATURE_VALUE_OUT_OF_RANGE"

    call, msg = await assert_request_calls_service(
        "Alexa.ThermostatController",
        "AdjustTargetTemperature",
        "climate#test_thermostat",
        "climate.set_temperature",
        hass,
        payload={"targetSetpointDelta": {"value": -10.0, "scale": "KELVIN"}},
    )
    assert call.data["temperature"] == 52.0
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal(
        "Alexa.ThermostatController",
        "targetSetpoint",
        {"value": 52.0, "scale": "FAHRENHEIT"},
    )

    msg = await assert_request_fails(
        "Alexa.ThermostatController",
        "AdjustTargetTemperature",
        "climate#test_thermostat",
        "climate.set_temperature",
        hass,
        payload={"targetSetpointDelta": {"value": 20.0, "scale": "CELSIUS"}},
    )
    assert msg["event"]["payload"]["type"] == "TEMPERATURE_VALUE_OUT_OF_RANGE"

    # Setting mode, the payload can be an object with a value attribute...
    call, msg = await assert_request_calls_service(
        "Alexa.ThermostatController",
        "SetThermostatMode",
        "climate#test_thermostat",
        "climate.set_hvac_mode",
        hass,
        payload={"thermostatMode": {"value": "HEAT"}},
    )
    assert call.data["hvac_mode"] == "heat"
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal("Alexa.ThermostatController", "thermostatMode", "HEAT")

    call, msg = await assert_request_calls_service(
        "Alexa.ThermostatController",
        "SetThermostatMode",
        "climate#test_thermostat",
        "climate.set_hvac_mode",
        hass,
        payload={"thermostatMode": {"value": "COOL"}},
    )
    assert call.data["hvac_mode"] == "cool"
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal("Alexa.ThermostatController", "thermostatMode", "COOL")

    # ...it can also be just the mode.
    call, msg = await assert_request_calls_service(
        "Alexa.ThermostatController",
        "SetThermostatMode",
        "climate#test_thermostat",
        "climate.set_hvac_mode",
        hass,
        payload={"thermostatMode": "HEAT"},
    )
    assert call.data["hvac_mode"] == "heat"
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal("Alexa.ThermostatController", "thermostatMode", "HEAT")

    # Assert we can call custom modes
    call, msg = await assert_request_calls_service(
        "Alexa.ThermostatController",
        "SetThermostatMode",
        "climate#test_thermostat",
        "climate.set_hvac_mode",
        hass,
        payload={"thermostatMode": {"value": "CUSTOM", "customName": "DEHUMIDIFY"}},
    )
    assert call.data["hvac_mode"] == "dry"
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal("Alexa.ThermostatController", "thermostatMode", "CUSTOM")

    # assert unsupported custom mode
    msg = await assert_request_fails(
        "Alexa.ThermostatController",
        "SetThermostatMode",
        "climate#test_thermostat",
        "climate.set_hvac_mode",
        hass,
        payload={"thermostatMode": {"value": "CUSTOM", "customName": "INVALID"}},
    )
    assert msg["event"]["payload"]["type"] == "UNSUPPORTED_THERMOSTAT_MODE"

    msg = await assert_request_fails(
        "Alexa.ThermostatController",
        "SetThermostatMode",
        "climate#test_thermostat",
        "climate.set_hvac_mode",
        hass,
        payload={"thermostatMode": {"value": "INVALID"}},
    )
    assert msg["event"]["payload"]["type"] == "UNSUPPORTED_THERMOSTAT_MODE"

    call, _ = await assert_request_calls_service(
        "Alexa.ThermostatController",
        "SetThermostatMode",
        "climate#test_thermostat",
        "climate.set_hvac_mode",
        hass,
        payload={"thermostatMode": "OFF"},
    )
    assert call.data["hvac_mode"] == "off"

    # Assert we can call presets
    call, msg = await assert_request_calls_service(
        "Alexa.ThermostatController",
        "SetThermostatMode",
        "climate#test_thermostat",
        "climate.set_preset_mode",
        hass,
        payload={"thermostatMode": "ECO"},
    )
    assert call.data["preset_mode"] == "eco"

    # Reset config temperature_unit back to CELSIUS, required for additional tests outside this component.
    hass.config.units.temperature_unit = TEMP_CELSIUS


async def test_exclude_filters(hass):
    """Test exclusion filters."""
    request = get_new_request("Alexa.Discovery", "Discover")

    # setup test devices
    hass.states.async_set("switch.test", "on", {"friendly_name": "Test switch"})

    hass.states.async_set("script.deny", "off", {"friendly_name": "Blocked script"})

    hass.states.async_set("cover.deny", "off", {"friendly_name": "Blocked cover"})

    alexa_config = MockConfig(hass)
    alexa_config.should_expose = entityfilter.generate_filter(
        include_domains=[],
        include_entities=[],
        exclude_domains=["script"],
        exclude_entities=["cover.deny"],
    )

    msg = await smart_home.async_handle_message(hass, alexa_config, request)
    await hass.async_block_till_done()

    msg = msg["event"]

    assert len(msg["payload"]["endpoints"]) == 1


async def test_include_filters(hass):
    """Test inclusion filters."""
    request = get_new_request("Alexa.Discovery", "Discover")

    # setup test devices
    hass.states.async_set("switch.deny", "on", {"friendly_name": "Blocked switch"})

    hass.states.async_set("script.deny", "off", {"friendly_name": "Blocked script"})

    hass.states.async_set(
        "automation.allow", "off", {"friendly_name": "Allowed automation"}
    )

    hass.states.async_set("group.allow", "off", {"friendly_name": "Allowed group"})

    alexa_config = MockConfig(hass)
    alexa_config.should_expose = entityfilter.generate_filter(
        include_domains=["automation", "group"],
        include_entities=["script.deny"],
        exclude_domains=[],
        exclude_entities=[],
    )

    msg = await smart_home.async_handle_message(hass, alexa_config, request)
    await hass.async_block_till_done()

    msg = msg["event"]

    assert len(msg["payload"]["endpoints"]) == 3


async def test_never_exposed_entities(hass):
    """Test never exposed locks do not get discovered."""
    request = get_new_request("Alexa.Discovery", "Discover")

    # setup test devices
    hass.states.async_set("group.all_locks", "on", {"friendly_name": "Blocked locks"})

    hass.states.async_set("group.allow", "off", {"friendly_name": "Allowed group"})

    alexa_config = MockConfig(hass)
    alexa_config.should_expose = entityfilter.generate_filter(
        include_domains=["group"],
        include_entities=[],
        exclude_domains=[],
        exclude_entities=[],
    )

    msg = await smart_home.async_handle_message(hass, alexa_config, request)
    await hass.async_block_till_done()

    msg = msg["event"]

    assert len(msg["payload"]["endpoints"]) == 1


async def test_api_entity_not_exists(hass):
    """Test api turn on process without entity."""
    request = get_new_request("Alexa.PowerController", "TurnOn", "switch#test")

    call_switch = async_mock_service(hass, "switch", "turn_on")

    msg = await smart_home.async_handle_message(hass, DEFAULT_CONFIG, request)
    await hass.async_block_till_done()

    assert "event" in msg
    msg = msg["event"]

    assert not call_switch
    assert msg["header"]["name"] == "ErrorResponse"
    assert msg["header"]["namespace"] == "Alexa"
    assert msg["payload"]["type"] == "NO_SUCH_ENDPOINT"


async def test_api_function_not_implemented(hass):
    """Test api call that is not implemented to us."""
    request = get_new_request("Alexa.HAHAAH", "Sweet")
    msg = await smart_home.async_handle_message(hass, DEFAULT_CONFIG, request)

    assert "event" in msg
    msg = msg["event"]

    assert msg["header"]["name"] == "ErrorResponse"
    assert msg["header"]["namespace"] == "Alexa"
    assert msg["payload"]["type"] == "INTERNAL_ERROR"


async def test_api_accept_grant(hass):
    """Test api AcceptGrant process."""
    request = get_new_request("Alexa.Authorization", "AcceptGrant")

    # add payload
    request["directive"]["payload"] = {
        "grant": {
            "type": "OAuth2.AuthorizationCode",
            "code": "VGhpcyBpcyBhbiBhdXRob3JpemF0aW9uIGNvZGUuIDotKQ==",
        },
        "grantee": {"type": "BearerToken", "token": "access-token-from-skill"},
    }

    # setup test devices
    msg = await smart_home.async_handle_message(hass, DEFAULT_CONFIG, request)
    await hass.async_block_till_done()

    assert "event" in msg
    msg = msg["event"]

    assert msg["header"]["name"] == "AcceptGrant.Response"


async def test_entity_config(hass):
    """Test that we can configure things via entity config."""
    request = get_new_request("Alexa.Discovery", "Discover")

    hass.states.async_set("light.test_1", "on", {"friendly_name": "Test light 1"})
    hass.states.async_set("scene.test_1", "scening", {"friendly_name": "Test 1"})

    alexa_config = MockConfig(hass)
    alexa_config.entity_config = {
        "light.test_1": {
            "name": "Config *name*",
            "display_categories": "SWITCH",
            "description": "Config >!<description",
        },
        "scene.test_1": {"description": "Config description"},
    }

    msg = await smart_home.async_handle_message(hass, alexa_config, request)

    assert "event" in msg
    msg = msg["event"]

    assert len(msg["payload"]["endpoints"]) == 2

    appliance = msg["payload"]["endpoints"][0]
    assert appliance["endpointId"] == "light#test_1"
    assert appliance["displayCategories"][0] == "SWITCH"
    assert appliance["friendlyName"] == "Config name"
    assert appliance["description"] == "Config description via Home Assistant"
    assert_endpoint_capabilities(
        appliance, "Alexa.PowerController", "Alexa.EndpointHealth", "Alexa"
    )

    scene = msg["payload"]["endpoints"][1]
    assert scene["endpointId"] == "scene#test_1"
    assert scene["displayCategories"][0] == "SCENE_TRIGGER"
    assert scene["friendlyName"] == "Test 1"
    assert scene["description"] == "Config description via Home Assistant (Scene)"


async def test_logging_request(hass, events):
    """Test that we log requests."""
    context = Context()
    request = get_new_request("Alexa.Discovery", "Discover")
    await smart_home.async_handle_message(hass, DEFAULT_CONFIG, request, context)

    # To trigger event listener
    await hass.async_block_till_done()

    assert len(events) == 1
    event = events[0]

    assert event.data["request"] == {"namespace": "Alexa.Discovery", "name": "Discover"}
    assert event.data["response"] == {
        "namespace": "Alexa.Discovery",
        "name": "Discover.Response",
    }
    assert event.context == context


async def test_logging_request_with_entity(hass, events):
    """Test that we log requests."""
    context = Context()
    request = get_new_request("Alexa.PowerController", "TurnOn", "switch#xy")
    await smart_home.async_handle_message(hass, DEFAULT_CONFIG, request, context)

    # To trigger event listener
    await hass.async_block_till_done()

    assert len(events) == 1
    event = events[0]

    assert event.data["request"] == {
        "namespace": "Alexa.PowerController",
        "name": "TurnOn",
        "entity_id": "switch.xy",
    }
    # Entity doesn't exist
    assert event.data["response"] == {"namespace": "Alexa", "name": "ErrorResponse"}
    assert event.context == context


async def test_disabled(hass):
    """When enabled=False, everything fails."""
    hass.states.async_set("switch.test", "on", {"friendly_name": "Test switch"})
    request = get_new_request("Alexa.PowerController", "TurnOn", "switch#test")

    call_switch = async_mock_service(hass, "switch", "turn_on")

    msg = await smart_home.async_handle_message(
        hass, DEFAULT_CONFIG, request, enabled=False
    )
    await hass.async_block_till_done()

    assert "event" in msg
    msg = msg["event"]

    assert not call_switch
    assert msg["header"]["name"] == "ErrorResponse"
    assert msg["header"]["namespace"] == "Alexa"
    assert msg["payload"]["type"] == "BRIDGE_UNREACHABLE"


async def test_endpoint_good_health(hass):
    """Test endpoint health reporting."""
    device = (
        "binary_sensor.test_contact",
        "on",
        {"friendly_name": "Test Contact Sensor", "device_class": "door"},
    )
    await discovery_test(device, hass)
    properties = await reported_properties(hass, "binary_sensor#test_contact")
    properties.assert_equal("Alexa.EndpointHealth", "connectivity", {"value": "OK"})


async def test_endpoint_bad_health(hass):
    """Test endpoint health reporting."""
    device = (
        "binary_sensor.test_contact",
        "unavailable",
        {"friendly_name": "Test Contact Sensor", "device_class": "door"},
    )
    await discovery_test(device, hass)
    properties = await reported_properties(hass, "binary_sensor#test_contact")
    properties.assert_equal(
        "Alexa.EndpointHealth", "connectivity", {"value": "UNREACHABLE"}
    )


async def test_alarm_control_panel_disarmed(hass):
    """Test alarm_control_panel discovery."""
    device = (
        "alarm_control_panel.test_1",
        "disarmed",
        {
            "friendly_name": "Test Alarm Control Panel 1",
            "code_arm_required": False,
            "code_format": "number",
            "code": "1234",
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "alarm_control_panel#test_1"
    assert appliance["displayCategories"][0] == "SECURITY_PANEL"
    assert appliance["friendlyName"] == "Test Alarm Control Panel 1"
    capabilities = assert_endpoint_capabilities(
        appliance, "Alexa.SecurityPanelController", "Alexa.EndpointHealth", "Alexa"
    )
    security_panel_capability = get_capability(
        capabilities, "Alexa.SecurityPanelController"
    )
    assert security_panel_capability is not None
    configuration = security_panel_capability["configuration"]
    assert {"type": "FOUR_DIGIT_PIN"} in configuration["supportedAuthorizationTypes"]

    properties = await reported_properties(hass, "alarm_control_panel#test_1")
    properties.assert_equal("Alexa.SecurityPanelController", "armState", "DISARMED")

    call, msg = await assert_request_calls_service(
        "Alexa.SecurityPanelController",
        "Arm",
        "alarm_control_panel#test_1",
        "alarm_control_panel.alarm_arm_home",
        hass,
        response_type="Arm.Response",
        payload={"armState": "ARMED_STAY"},
    )
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal("Alexa.SecurityPanelController", "armState", "ARMED_STAY")

    call, msg = await assert_request_calls_service(
        "Alexa.SecurityPanelController",
        "Arm",
        "alarm_control_panel#test_1",
        "alarm_control_panel.alarm_arm_away",
        hass,
        response_type="Arm.Response",
        payload={"armState": "ARMED_AWAY"},
    )
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal("Alexa.SecurityPanelController", "armState", "ARMED_AWAY")

    call, msg = await assert_request_calls_service(
        "Alexa.SecurityPanelController",
        "Arm",
        "alarm_control_panel#test_1",
        "alarm_control_panel.alarm_arm_night",
        hass,
        response_type="Arm.Response",
        payload={"armState": "ARMED_NIGHT"},
    )
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal("Alexa.SecurityPanelController", "armState", "ARMED_NIGHT")


async def test_alarm_control_panel_armed(hass):
    """Test alarm_control_panel discovery."""
    device = (
        "alarm_control_panel.test_2",
        "armed_away",
        {
            "friendly_name": "Test Alarm Control Panel 2",
            "code_arm_required": False,
            "code_format": "FORMAT_NUMBER",
            "code": "1234",
        },
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "alarm_control_panel#test_2"
    assert appliance["displayCategories"][0] == "SECURITY_PANEL"
    assert appliance["friendlyName"] == "Test Alarm Control Panel 2"
    assert_endpoint_capabilities(
        appliance, "Alexa.SecurityPanelController", "Alexa.EndpointHealth", "Alexa"
    )

    properties = await reported_properties(hass, "alarm_control_panel#test_2")
    properties.assert_equal("Alexa.SecurityPanelController", "armState", "ARMED_AWAY")

    call, msg = await assert_request_calls_service(
        "Alexa.SecurityPanelController",
        "Disarm",
        "alarm_control_panel#test_2",
        "alarm_control_panel.alarm_disarm",
        hass,
        payload={"authorization": {"type": "FOUR_DIGIT_PIN", "value": "1234"}},
    )
    assert call.data["code"] == "1234"
    properties = ReportedProperties(msg["context"]["properties"])
    properties.assert_equal("Alexa.SecurityPanelController", "armState", "DISARMED")

    msg = await assert_request_fails(
        "Alexa.SecurityPanelController",
        "Arm",
        "alarm_control_panel#test_2",
        "alarm_control_panel.alarm_arm_home",
        hass,
        payload={"armState": "ARMED_STAY"},
    )
    assert msg["event"]["payload"]["type"] == "AUTHORIZATION_REQUIRED"


async def test_alarm_control_panel_code_arm_required(hass):
    """Test alarm_control_panel with code_arm_required discovery."""
    device = (
        "alarm_control_panel.test_3",
        "disarmed",
        {"friendly_name": "Test Alarm Control Panel 3", "code_arm_required": True},
    )
    await discovery_test(device, hass, expected_endpoints=0)


async def test_range_unsupported_domain(hass):
    """Test rangeController with unsupported domain."""
    device = ("switch.test", "on", {"friendly_name": "Test switch"})
    await discovery_test(device, hass)

    context = Context()
    request = get_new_request("Alexa.RangeController", "SetRangeValue", "switch#test")
    request["directive"]["payload"] = {"rangeValue": "1"}
    request["directive"]["header"]["instance"] = "switch.speed"

    msg = await smart_home.async_handle_message(hass, DEFAULT_CONFIG, request, context)

    assert "event" in msg
    msg = msg["event"]
    assert msg["header"]["name"] == "ErrorResponse"
    assert msg["header"]["namespace"] == "Alexa"
    assert msg["payload"]["type"] == "INVALID_DIRECTIVE"


async def test_mode_unsupported_domain(hass):
    """Test modeController with unsupported domain."""
    device = ("switch.test", "on", {"friendly_name": "Test switch"})
    await discovery_test(device, hass)

    context = Context()
    request = get_new_request("Alexa.ModeController", "SetMode", "switch#test")
    request["directive"]["payload"] = {"mode": "testMode"}
    request["directive"]["header"]["instance"] = "switch.direction"

    msg = await smart_home.async_handle_message(hass, DEFAULT_CONFIG, request, context)

    assert "event" in msg
    msg = msg["event"]
    assert msg["header"]["name"] == "ErrorResponse"
    assert msg["header"]["namespace"] == "Alexa"
    assert msg["payload"]["type"] == "INVALID_DIRECTIVE"


async def test_cover_position(hass):
    """Test cover position mode discovery."""
    device = (
        "cover.test",
        "off",
        {"friendly_name": "Test cover", "supported_features": 255, "position": 30},
    )
    appliance = await discovery_test(device, hass)

    assert appliance["endpointId"] == "cover#test"
    assert appliance["displayCategories"][0] == "OTHER"
    assert appliance["friendlyName"] == "Test cover"

    capabilities = assert_endpoint_capabilities(
        appliance,
        "Alexa",
        "Alexa.ModeController",
        "Alexa.PercentageController",
        "Alexa.PowerController",
        "Alexa.EndpointHealth",
    )

    mode_capability = get_capability(capabilities, "Alexa.ModeController")
    assert mode_capability is not None
    assert mode_capability["instance"] == "cover.position"

    properties = mode_capability["properties"]
    assert properties["nonControllable"] is False
    assert {"name": "mode"} in properties["supported"]

    capability_resources = mode_capability["capabilityResources"]
    assert capability_resources is not None
    assert {
        "@type": "asset",
        "value": {"assetId": "Alexa.Setting.Mode"},
    } in capability_resources["friendlyNames"]

    configuration = mode_capability["configuration"]
    assert configuration is not None
    assert configuration["ordered"] is False

    supported_modes = configuration["supportedModes"]
    assert supported_modes is not None
    assert {
        "value": "position.open",
        "modeResources": {
            "friendlyNames": [
                {"@type": "text", "value": {"text": "open", "locale": "en-US"}},
                {"@type": "text", "value": {"text": "opened", "locale": "en-US"}},
                {"@type": "text", "value": {"text": "raise", "locale": "en-US"}},
                {"@type": "text", "value": {"text": "raised", "locale": "en-US"}},
            ]
        },
    } in supported_modes
    assert {
        "value": "position.closed",
        "modeResources": {
            "friendlyNames": [
                {"@type": "text", "value": {"text": "close", "locale": "en-US"}},
                {"@type": "text", "value": {"text": "closed", "locale": "en-US"}},
                {"@type": "text", "value": {"text": "shut", "locale": "en-US"}},
                {"@type": "text", "value": {"text": "lower", "locale": "en-US"}},
                {"@type": "text", "value": {"text": "lowered", "locale": "en-US"}},
            ]
        },
    } in supported_modes

    call, msg = await assert_request_calls_service(
        "Alexa.ModeController",
        "SetMode",
        "cover#test",
        "cover.close_cover",
        hass,
        payload={"mode": "position.closed"},
        instance="cover.position",
    )
    properties = msg["context"]["properties"][0]
    assert properties["name"] == "mode"
    assert properties["namespace"] == "Alexa.ModeController"
    assert properties["value"] == "position.closed"

    call, msg = await assert_request_calls_service(
        "Alexa.ModeController",
        "SetMode",
        "cover#test",
        "cover.open_cover",
        hass,
        payload={"mode": "position.open"},
        instance="cover.position",
    )
    properties = msg["context"]["properties"][0]
    assert properties["name"] == "mode"
    assert properties["namespace"] == "Alexa.ModeController"
    assert properties["value"] == "position.open"

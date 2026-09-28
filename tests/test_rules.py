"""The fleet rules ported from Kiosk Satellite (ks_rules.py)."""

import hashlib
import json

import ks_rules as ks

# One of each kind of value a panel holds, keys out of order.
SAMPLE = {
    "screensaver.timeout": 300,
    "browser.zoom": 1.0,
    "ha.url": "http://homeassistant.local:8123/",
    "screen.orientation": "auto",
    "voice.enabled": True,
    "kiosk.pin": 'café "quoted" back\\slash',
    "screensaver.message": "line1\nline2\ttab\u0001ctl \U0001F3E0",
    "audio.duck": 0.25,
    "lockdown.enabled": False,
}


def test_fingerprint_is_dart_md5_of_sorted_compact_json():
    # FleetSyncManager.fingerprintOf is
    #   md5(utf8.encode(jsonEncode(SplayTreeMap.from(settings))))
    # and Dart's jsonEncode writes: keys in the map's (here sorted) order, no
    # spaces, a double with its ".0" (1.0 stays 1.0), non-ASCII as raw UTF-8
    # (é, the emoji), and escapes only the quote, the backslash and control
    # characters: \n and \t by name, anything else as a lowercase \u00XX.
    # Those bytes, written out by hand:
    expected = (
        '{"audio.duck":0.25,'
        '"browser.zoom":1.0,'
        '"ha.url":"http://homeassistant.local:8123/",'
        '"kiosk.pin":"café \\"quoted\\" back\\\\slash",'
        '"lockdown.enabled":false,'
        '"screen.orientation":"auto",'
        '"screensaver.message":"line1\\nline2\\ttab\\u0001ctl \U0001F3E0",'
        '"screensaver.timeout":300,'
        '"voice.enabled":true}'
    )
    assert ks.json_compact(dict(sorted(SAMPLE.items()))) == expected
    # The same map through `dart run` (jsonEncode of a SplayTreeMap on Dart
    # 3) printed these exact bytes; their md5:
    assert hashlib.md5(expected.encode("utf-8")).hexdigest() == "c06dc78237593f5ca5bc6fd70c53adb9"
    assert ks.fingerprint(SAMPLE) == "c06dc78237593f5ca5bc6fd70c53adb9"
    # Order of the input never matters.
    assert ks.fingerprint(dict(reversed(list(SAMPLE.items())))) == ks.fingerprint(SAMPLE)


def test_roster_revision_and_entry_order():
    leader = ks.directory_entry("f00d", "Panel Fleet", "0.3.0", "10.2.1.10", 2330, agent=True)
    panel = ks.directory_entry("a1", "Office Panel", "2026.9.87", "10.2.4.145", 2324)
    # FleetDevice.toDirectory's key order, the flags only when true.
    assert list(leader) == ["id", "name", "version", "address", "port", "agent"]
    assert list(panel) == ["id", "name", "version", "address", "port"]
    assert "tls" not in leader
    roster = sorted([leader, panel], key=lambda e: e["id"])
    text = ('[{"id":"a1","name":"Office Panel","version":"2026.9.87","address":"10.2.4.145",'
            '"port":2324},{"id":"f00d","name":"Panel Fleet","version":"0.3.0",'
            '"address":"10.2.1.10","port":2330,"agent":true}]')
    assert ks.json_compact(roster) == text
    assert ks.roster_revision(roster) == hashlib.md5(text.encode()).hexdigest()
    assert ks.roster_revision(roster) == "585bb52d3157bf25c5848ba4d12789ac"


def _d(key, category, **extra):
    return {"key": key, "category": category, "type": "string", **extra}


DEFINITIONS = [
    _d("ha.url", "Home Assistant"),
    _d("ha.token", "Home Assistant", secret=True),
    _d("sendspin.ma_token", "Sendspin", secret=True),
    _d("ha.satellite_entity", "Voice Satellite", perDevice=True),
    _d("browser.start_url", "Browser"),
    _d("browser.zoom", "Browser", type="number"),
    _d("webcontent.camera", "Web Content", type="boolean"),
    _d("screen.brightness_mode", "Screen & Audio"),
    _d("screensaver.mode", "Screensaver", type="select"),
    _d("screensaver.schedule", "Screensaver"),
    _d("gestures.mappings", "Gestures"),
    _d("esphome.excluded_entities", "ESPHome"),
    _d("kiosk.enabled", "Kiosk", type="boolean", default=False),
]

GESTURES = json.dumps([
    {"id": "g1", "trigger": {"type": "corner_taps", "corner": "tl", "taps": 3},
     "action": {"type": "navigate", "path": "lovelace/0"}},
    {"id": "g2", "trigger": {"type": "claps", "claps": 2},
     "action": {"type": "plugin_action", "pluginId": "p", "command": "c"}},
    {"id": "", "trigger": {}, "action": {}},
])

VALUES = {
    "ha.url": "http://ha.local:8123",
    "ha.token": "secret-ha",
    "sendspin.ma_token": "secret-ma",
    "ha.satellite_entity": "assist_satellite.office",
    "browser.start_url": "http://ha.local:8123/lovelace/0",
    "browser.zoom": 110,
    "webcontent.camera": True,
    "screen.brightness_mode": "auto",
    "screensaver.mode": "plugin:weather:radar",
    "screensaver.schedule": json.dumps([{"at": "22:00", "mode": "plugin:weather:radar"}]),
    "gestures.mappings": GESTURES,
    "esphome.excluded_entities": json.dumps(["sensor.b", "plugin_x_y", "sensor.a", "sensor.a"]),
}


def test_payload_follows_the_profile_like_kiosk_satellite():
    profile = {**ks.default_profile(), "categories": [
        "Home Assistant", "Browser", "Screensaver", "Gestures", "ESPHome", "Kiosk"]}
    out = ks.profile_settings(DEFINITIONS, VALUES, profile)
    # Per-device never; the HA token only when the profile includes it (the
    # Default does not), the MA token rides its credential switch, not its
    # category (Sendspin is not in this profile).
    assert "ha.satellite_entity" not in out
    assert "ha.token" not in out
    assert out["sendspin.ma_token"] == "secret-ma"
    # The dashboard is off by default; the zoom is excluded by default.
    assert "browser.start_url" not in out
    assert "browser.zoom" not in out
    # Web Content rides with Web Browsing.
    assert out["webcontent.camera"] is True
    # Screen & Audio is not in the profile.
    assert "screen.brightness_mode" not in out
    # A plugin screensaver, and a schedule naming one, stay local.
    assert "screensaver.mode" not in out
    assert "screensaver.schedule" not in out
    # Plugin gestures and plugin entity exclusions stay local; the rest is
    # re-encoded compactly, the exclusions sorted and de-duplicated.
    assert json.loads(out["gestures.mappings"]) == [json.loads(GESTURES)[0]]
    assert out["gestures.mappings"].startswith('[{"id":"g1","trigger":{"type":"corner_taps"')
    assert out["esphome.excluded_entities"] == '["sensor.a","sensor.b"]'
    # A value never set falls back to the definition's default.
    assert out["kiosk.enabled"] is False

    everything = {**profile, "credentials": ["ha.token"], "dashboard": True, "excluded": []}
    out = ks.profile_settings(DEFINITIONS, {**VALUES, "screensaver.mode": "clock"}, everything)
    assert out["ha.token"] == "secret-ha"
    assert "sendspin.ma_token" not in out
    assert out["browser.start_url"].endswith("/lovelace/0")
    assert out["browser.zoom"] == 110
    assert out["screensaver.mode"] == "clock"

    assert ks.profile_settings(DEFINITIONS, VALUES, ks.updates_only_profile()) == {}


def test_syncable_definitions():
    assert ks.is_syncable_definition(_d("webcontent.camera", "Web Content"))
    assert not ks.is_syncable_definition(_d("fleet.leader", "Fleet", perDevice=True))
    assert not ks.is_syncable_definition(_d("plugins.enabled", "Plugins"))
    assert not ks.is_syncable_definition(_d("device.name", "Device", perDevice=True))


def test_version_names_and_order():
    assert ks.version_name("2026.9.87+286") == "2026.9.87"
    assert ks.version_name("2026.9.87-djc-2026.09.28.1+286") == "2026.9.87-djc-2026.09.28.1"
    assert ks.is_newer("2026.9.88", "2026.9.87+300")
    assert not ks.is_newer("2026.9.87+1", "2026.9.87+2")


def test_parse_profile():
    p = ks.parse_profile({"id": "x", "name": "Hall", "categories": ["Kiosk", "Kiosk"],
                          "credentials": ["ha.token", "remote.password"]})
    assert p["categories"] == ["Kiosk"]
    assert p["credentials"] == ["ha.token"]
    assert p["excluded"] == ks.FLEET_DEFAULT_EXCLUDED
    assert p["dashboard"] is False
    assert ks.parse_profile({"id": "x"}) is None

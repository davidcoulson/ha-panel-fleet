"""Kiosk Satellite's fleet rules, ported to Python.

Panel Fleet leads Kiosk Satellite panels over their own fleet wire, so what
travels, how it is fingerprinted and who counts as a member must be exactly
what a Kiosk Satellite leader would do. Everything here is ported from
kiosk-satellite 2026.9.87, and names the Dart it came from:

- app/lib/managers/settings/definitions.dart: fleetSyncCategories,
  fleetCategoryOf, fleetCredentials, fleetDashboardKeys,
  fleetDefaultCredentials, fleetDefaultExcluded, fleetDefaultCategories,
  isPluginScreensaver, decodeEspHomeExcludedEntities.
- app/lib/managers/fleet/fleet_sync_manager.dart: SyncProfile, syncs,
  profileSettings, fingerprintOf, _rosterRevision, _pluginScreensaverSetting,
  _fleetValue, _versionName, isNewer.
- app/lib/managers/gestures/gesture_mappings.dart: decodeGestureMappings.
- app/lib/managers/fleet/fleet_manager.dart: FleetDevice.toDirectory.

When Kiosk Satellite changes one of these, this file changes with it.
"""

import hashlib
import json
import re

KS_SOURCE_VERSION = "2026.9.87"

# ── definitions.dart ──────────────────────────────────────────────────

# The categories a leader can push, in the sidebar's order: the definitions
# category, the name both UIs show for it and what stays per kiosk inside
# it. The Web Content grants ride with Web Browsing.
FLEET_SYNC_CATEGORIES = [
    ("Home Assistant", "Home Assistant Setup", ""),
    ("Voice Satellite", "Voice Satellite", "the assigned satellite"),
    ("Screen & Audio", "Screen & Audio", "microphone and speaker devices, mic gain"),
    ("Browser", "Web Browsing", ""),
    ("Screensaver", "Screensaver", ""),
    ("Camera", "Camera", "the device camera"),
    ("Sendspin", "Media Player", "the followed player, the Sendspin player id"),
    ("Cameras", "Camera Streams", ""),
    ("DLNA", "DLNA Renderer", ""),
    ("ESPHome", "ESPHome", "node name, MAC, encryption key"),
    ("Kiosk", "Kiosk Mode", "the PIN is also synced"),
    ("Lockdown", "Lockdown Mode", ""),
    ("Home", "Home Launcher", ""),
    ("Launcher", "App Launcher", ""),
    ("Gestures", "Gestures", ""),
    ("Intercom", "Intercom", "the key, unless synced as a credential"),
    ("Device", "Device", "name, remote administration, renderer workarounds, scale"),
]
CATEGORY_IDS = [c[0] for c in FLEET_SYNC_CATEGORIES]
CATEGORY_TITLES = {c[0]: c[1] for c in FLEET_SYNC_CATEGORIES}

# The credentials a follower keeps unless a profile includes each one.
FLEET_CREDENTIALS = [
    ("ha.token", "Home Assistant token"),
    ("sendspin.ma_token", "Music Assistant token"),
    ("screensaver.immich_api_key", "Immich API key"),
    ("intercom.key", "Intercom key"),
]
FLEET_CREDENTIAL_KEYS = frozenset(k for k, _ in FLEET_CREDENTIALS)

# The dashboard: synced only when a profile includes it.
FLEET_DASHBOARD_KEYS = frozenset({"browser.start_url"})

# What a new profile shares: the household's Music Assistant, Immich and
# intercom credentials, not the Home Assistant token, which names a user.
FLEET_DEFAULT_CREDENTIALS = ["sendspin.ma_token", "screensaver.immich_api_key", "intercom.key"]

# Taken out of every new profile: what scales the UI, drives the backlight
# or sets a volume, files and picks that only resolve on their own device,
# the camera's tuning, the mounting, and each room's own intercom and voice.
FLEET_DEFAULT_EXCLUDED = [
    "browser.zoom",
    "screensaver.website_zoom",
    "screensaver.clock_scale",
    "screensaver.widget_scale",
    "screensaver.immich_metadata_scale",
    "screensaver.glance_scale",
    "face.preview_scale",
    "sendspin.player_size",
    "screen.default_brightness",
    "screen.adaptive_min_brightness",
    "screen.adaptive_max_brightness",
    "screen.adaptive_dark_lux",
    "screen.adaptive_bright_lux",
    "screensaver.brightness_level",
    "screensaver.dim_level",
    "audio.media_volume",
    "audio.assistant_volume",
    "notifications.volume",
    "ha.tap_sound_volume",
    "screensaver.gallery_items",
    "screensaver.local_folder",
    "screensaver.clock_background",
    "notifications.chime_file",
    "launcher.apps",
    "motion.sensitivity",
    "motion.fps",
    "face.sensitivity",
    "camera.snapshot_resolution",
    "browser.cutout_mode",
    "screen.orientation",
    "intercom.volume",
    "intercom.answer_mode",
    "voice.mute",
    "voice.tts_output",
]

# What a new follower gets unless the leader says otherwise.
FLEET_DEFAULT_CATEGORIES = [
    "Home Assistant",
    "Voice Satellite",
    "Browser",
    "Screensaver",
    "Sendspin",
    "Cameras",
    "Kiosk",
    "Lockdown",
    "Gestures",
]


def fleet_category_of(definition):
    """The category a setting syncs under: its own, except the Web Content
    grants, which have no page and go with Web Browsing."""
    category = definition.get("category") or ""
    return "Browser" if category == "Web Content" else category


def is_syncable_definition(definition):
    """Whether a setting is one Panel Fleet keeps at all: never a per-device
    one, and only in a category a leader can push."""
    return not definition.get("perDevice") and fleet_category_of(definition) in CATEGORY_TITLES


_PLUGIN_SCREENSAVER = re.compile(r"plugin:[a-z][a-z0-9_-]{0,63}:[a-z][a-z0-9_]{0,39}")


def is_plugin_screensaver(value):
    return isinstance(value, str) and _PLUGIN_SCREENSAVER.fullmatch(value) is not None


def _decode_list(value):
    try:
        decoded = json.loads(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return decoded if isinstance(decoded, list) else None


# ── JSON as Dart writes it ────────────────────────────────────────────


def json_compact(value):
    """Dart's jsonEncode, byte for byte for what settings hold: no spaces,
    non-ASCII as UTF-8 rather than escaped, keys in the order given. Both
    escape only the quote, the backslash and control characters, and both
    write those as \\n, \\t... or a lowercase \\u00XX."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def fingerprint(settings):
    """fingerprintOf: the md5 of the settings as JSON with the keys sorted
    (a SplayTreeMap in Dart). What a follower holds is compared by it."""
    return _md5(json_compact(dict(sorted(settings.items()))))


def directory_entry(id, name, version, address, port, tls=False, agent=False):
    """FleetDevice.toDirectory: public fields only, in this key order, the
    flags only when true."""
    out = {"id": id, "name": name, "version": version, "address": address, "port": port}
    if tls:
        out["tls"] = True
    if agent:
        out["agent"] = True
    return out


def roster_revision(devices):
    """_rosterRevision: the md5 of the member list as JSON. A follower keeps
    the list it was sent re-encoded the same way and reports its md5, so the
    two match exactly when it holds this list."""
    return _md5(json_compact(devices))


# ── Versions ──────────────────────────────────────────────────────────


def version_name(version):
    """_versionName: the release without the build number. 2026.9.19+118 and
    2026.9.19+120 are the same release, and sync between them."""
    return str(version or "").split("+")[0].strip()


def is_newer(a, b):
    """isNewer: the first three numbers of each release, compared."""
    def nums(v):
        return [int(m) for m in re.findall(r"\d+", version_name(v))[:3]]
    x, y = nums(a), nums(b)
    for i in range(3):
        p = x[i] if i < len(x) else 0
        q = y[i] if i < len(y) else 0
        if p != q:
            return p > q
    return False


# ── Profiles ──────────────────────────────────────────────────────────

DEFAULT_ID = "default"
UPDATES_ONLY_ID = "updates-only"


def default_profile():
    """SyncProfile.initial: the Default until it is edited."""
    return {
        "id": DEFAULT_ID,
        "name": "Default",
        "categories": list(FLEET_DEFAULT_CATEGORIES),
        "credentials": list(FLEET_DEFAULT_CREDENTIALS),
        "dashboard": False,
        "excluded": list(FLEET_DEFAULT_EXCLUDED),
    }


def updates_only_profile():
    """SyncProfile.updatesOnly: syncs nothing. Never stored or edited."""
    return {
        "id": UPDATES_ONLY_ID,
        "name": "Updates only",
        "categories": [],
        "credentials": [],
        "dashboard": False,
        "excluded": [],
    }


def parse_profile(raw):
    """SyncProfile.parse: a profile from its JSON, or None without a list of
    categories. Unknown credentials are dropped; a missing exclusion list
    is the default one."""
    if not isinstance(raw, dict) or not isinstance(raw.get("categories"), list):
        return None
    creds = raw.get("credentials")
    excluded = raw.get("excluded")
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or ""),
        "categories": _unique(str(c) for c in raw["categories"]),
        "credentials": _unique(str(c) for c in creds if str(c) in FLEET_CREDENTIAL_KEYS)
        if isinstance(creds, list) else [],
        "dashboard": raw.get("dashboard") is True,
        "excluded": _unique(str(k) for k in excluded)
        if isinstance(excluded, list) else list(FLEET_DEFAULT_EXCLUDED),
    }


def _unique(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def describe_profile(profile):
    """SyncProfile.describe: one line for a profile row."""
    if profile["id"] == UPDATES_ONLY_ID:
        return "Nothing syncs. Only updates are pushed."
    return (f"Categories: {len(profile['categories'])} of {len(FLEET_SYNC_CATEGORIES)}. "
            f"Credentials: {len(profile['credentials'])} of {len(FLEET_CREDENTIALS)}. "
            f"Excluded: {len(profile['excluded'])}.")


# ── What travels ──────────────────────────────────────────────────────


def syncs(definition, profile):
    """Whether one setting travels under a profile."""
    if definition.get("perDevice"):
        return False
    key = definition["key"]
    if key in profile["excluded"]:
        return False
    if key in FLEET_CREDENTIAL_KEYS:
        return key in profile["credentials"]
    if key in FLEET_DASHBOARD_KEYS:
        return bool(profile["dashboard"])
    return fleet_category_of(definition) in profile["categories"]


def plugin_screensaver_setting(key, value):
    """_pluginScreensaverSetting: a plugin screensaver, or a schedule naming
    one, is local to the panel that has the plugin."""
    if key == "screensaver.mode":
        return is_plugin_screensaver(value)
    if key != "screensaver.schedule" or not isinstance(value, str):
        return False
    entries = _decode_list(value)
    return entries is not None and any(
        isinstance(e, dict) and is_plugin_screensaver(e.get("mode")) for e in entries)


def _gesture_mappings(value):
    """decodeGestureMappings: the well-formed mappings, the rest dropped."""
    out = []
    for entry in _decode_list(value) or []:
        if not isinstance(entry, dict):
            continue
        ident, trigger, action = entry.get("id"), entry.get("trigger"), entry.get("action")
        if not isinstance(ident, str) or not ident:
            continue
        if not isinstance(trigger, dict) or not isinstance(action, dict):
            continue
        out.append({"id": ident,
                    "trigger": {str(k): v for k, v in trigger.items()},
                    "action": {str(k): v for k, v in action.items()}})
    return out


def fleet_value(key, value):
    """_fleetValue: gestures bound to plugin actions and plugin entity
    exclusions stay on their panel; everything else travels as it is."""
    if key == "esphome.excluded_entities":
        ids = {i for i in (_decode_list(value) or []) if isinstance(i, str)}
        return json_compact(sorted(i for i in ids if not i.startswith("plugin_")))
    if key != "gestures.mappings":
        return value
    return json_compact([m for m in _gesture_mappings(value)
                         if ("" if m["action"].get("type") is None else m["action"]["type"])
                         != "plugin_action"])


def profile_settings(definitions, values, profile):
    """profileSettings: the values a profile pushes, full set, filtered."""
    out = {}
    for d in definitions:
        key = d["key"]
        if not syncs(d, profile):
            continue
        value = values.get(key, d.get("default"))
        # A secret never read has no value to send; Kiosk Satellite never
        # holds a null setting either.
        if value is None or plugin_screensaver_setting(key, value):
            continue
        out[key] = fleet_value(key, value)
    return out

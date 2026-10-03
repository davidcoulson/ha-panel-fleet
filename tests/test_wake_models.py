"""Custom wake word models: checked on upload, mirrored on the members whose
profile syncs Voice Satellite, compared by checksum."""

import hashlib
import json

import pytest

import wake_models as wm
from rig import make_rig, panel_pair

TFLITE = b"\x18\x00\x00\x00TFL3" + b"\x00" * 64
ONNX = b"\x08\x07\x12\x07pytorch" + b"\x00" * 32
MICRO = json.dumps({"type": "micro", "wake_word": "Hey Sputnik", "micro": {"probability_cutoff": 0.9}})
VS = json.dumps({"format": "vs-wake-word-ctc-v1", "phrase": "hey vs"})


async def body(data):
    yield data


async def upload(wake, files):
    for name, data in files.items():
        await wake.stage(name, body(data.encode() if isinstance(data, str) else data))
    return wake.commit()


def test_diff():
    mine = {"a/x.onnx": "1", "a/y.onnx": "2"}
    theirs = {"a/x.onnx": "1", "a/y.onnx": "old", "a/z.onnx": "3"}
    assert wm.diff(mine, theirs) == {"send": ["a/y.onnx"], "remove": ["a/z.onnx"]}
    assert wm.diff(mine, mine) == {"send": [], "remove": []}


async def test_upload_is_checked_and_grouped(tmp_path):
    leader = type("L", (), {"schedule_tick": lambda self: None, "members": {}})()
    wake = wm.WakeModels(leader, tmp_path)
    out = await upload(wake, {
        "hey_sputnik.json": MICRO, "hey_sputnik.tflite": TFLITE,   # microWakeWord
        "hey_vs.json": VS, "hey_vs.onnx": ONNX,                    # vsWakeWord
        "computer.onnx": ONNX,                                     # openWakeWord
        "lonely.json": MICRO,                                      # no .tflite
        "both.onnx": ONNX, "both.tflite": TFLITE,                  # two formats
        "fake.tflite": b"not a flatbuffer at all",
        "odd.json": json.dumps({"hello": 1}),
    })
    assert sorted((a["engine"], a["id"]) for a in out["added"]) == [
        ("microwakeword", "hey_sputnik"), ("openwakeword", "computer"),
        ("vswakeword", "hey_vs")]
    reasons = {r["file"]: r["reason"] for r in out["rejected"]}
    assert reasons["lonely.json"] == "A microWakeWord model needs lonely.tflite too."
    assert reasons["both.onnx"] == "Add either both.onnx or both.tflite, not both."
    assert reasons["fake.tflite"] == "fake.tflite is not a TFLite model."
    assert "neither a microWakeWord nor a vsWakeWord" in reasons["odd.json"]
    manifest = wake.manifest()
    assert set(manifest) == {"microwakeword/hey_sputnik.json", "microwakeword/hey_sputnik.tflite",
                             "vswakeword/hey_vs.json", "vswakeword/hey_vs.onnx",
                             "openwakeword/computer.onnx"}
    assert manifest["openwakeword/computer.onnx"] == hashlib.sha256(ONNX).hexdigest()
    models = {m["id"]: m for m in wake.models()}
    assert models["hey_sputnik"]["wakeWord"] == "Hey Sputnik"
    # A model of the same name is replaced whole.
    await upload(wake, {"computer.tflite": TFLITE})
    assert "openwakeword/computer.onnx" not in wake.manifest()
    assert "openwakeword/computer.tflite" in wake.manifest()
    # Names that are not model files never land.
    for bad in ("../evil.onnx", ".hidden.onnx", "model.bin", ""):
        with pytest.raises(wm.WakeModelError):
            await wake.stage(bad, body(ONNX))
    assert wake.delete("openwakeword", "computer") is None
    assert wake.delete("openwakeword", "computer") == "No such model"
    assert wake.delete("../x", "y") == "No such model"


@pytest.fixture
async def rig(aiohttp_server, tmp_path):
    panel, projector = panel_pair()
    projector.voice = False  # an agent runs no voice manager
    async with make_rig(aiohttp_server, tmp_path,
                        [(panel, True, False), (projector, True, True)]) as r:
        await r.join(panel)
        await r.join(projector)
        yield r


async def test_mirroring(rig):
    leader = rig.leader
    panel, projector = rig.panels
    wake = leader.wake
    # Nothing is mirrored without models, or before it is switched on.
    assert "Add models first" in wake.set_enabled(True)
    await upload(wake, {"hey_sputnik.json": MICRO, "hey_sputnik.tflite": TFLITE,
                        "computer.onnx": ONNX})
    panel.wake_files = {"openwakeword/computer.onnx": b"an older computer",
                        "openwakeword/stale.onnx": ONNX}
    await leader.tick()
    assert panel.wake_puts == [] and panel.wake_deletes == []

    # What it would do, without doing it.
    plan = {r["id"]: r for r in (await wake.plan())["rows"]}
    assert plan[panel.id]["send"] == ["microwakeword/hey_sputnik.json",
                                      "microwakeword/hey_sputnik.tflite",
                                      "openwakeword/computer.onnx"]
    assert plan[panel.id]["remove"] == ["openwakeword/stale.onnx"]
    assert plan[panel.id]["syncs"] is True
    assert plan[projector.id]["error"] and "send" not in plan[projector.id]
    assert panel.wake_puts == []

    assert wake.set_enabled(True) is None
    await leader.tick()
    assert sorted(panel.wake_puts) == ["microwakeword/hey_sputnik.json",
                                       "microwakeword/hey_sputnik.tflite",
                                       "openwakeword/computer.onnx"]
    assert panel.wake_deletes == ["openwakeword/stale.onnx"]
    assert panel.wake_files["openwakeword/computer.onnx"] == ONNX
    assert panel._wake_manifest() == wake.manifest()

    # An unchanged set costs nothing more.
    reads = panel.wake_reads
    await leader.tick()
    assert panel.wake_reads == reads and len(panel.wake_puts) == 3

    # One model changes: only its file travels.
    await upload(wake, {"computer.onnx": ONNX + b"v2"})
    await leader.tick()
    assert panel.wake_puts[3:] == ["openwakeword/computer.onnx"]
    assert panel._wake_manifest() == wake.manifest()


async def test_only_profiles_that_sync_voice(rig):
    leader = rig.leader
    panel, _ = rig.panels
    await upload(leader.wake, {"computer.onnx": ONNX})
    assert leader.wake.set_enabled(True) is None
    assert leader.assign_profile(panel.id, "updates-only") is None
    await leader.tick()
    assert panel.wake_reads == 0 and panel.wake_files == {}
    assert leader.assign_profile(panel.id, "default") is None
    await leader.tick()
    assert list(panel.wake_files) == ["openwakeword/computer.onnx"]


async def test_not_in_step_no_models(rig):
    """As a Kiosk Satellite leader: the models go only to a member on the
    fleet's version, after its push."""
    leader = rig.leader
    panel, _ = rig.panels
    await upload(leader.wake, {"computer.onnx": ONNX})
    leader.wake.set_enabled(True)
    panel.version = "2026.9.86"
    leader.devices()[panel.id]["version"] = panel.version
    await leader.tick()
    assert panel.wake_files == {}

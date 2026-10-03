"""Reading an APK without aapt, and picking one per device."""

import zipfile

import pytest

import apk
from apk_builder import build_apk, manifest_xml


@pytest.mark.parametrize("kw", [{}, {"utf8": True}, {"strip_names": True}])
def test_manifest_attributes(kw):
    attrs = apk.manifest_attributes(manifest_xml(version_name="2026.10.4-djc-2026.10.02.3",
                                                 version_code=302, **kw))
    assert attrs["package"] == "me.jxl.kiosk_satellite"
    assert attrs["versionName"] == "2026.10.4-djc-2026.10.02.3"
    assert attrs["versionCode"] == 302


def test_read_apk(tmp_path):
    p = tmp_path / "ks.apk"
    p.write_bytes(build_apk(abis=("armeabi-v7a",), version_name="2026.9.87", version_code=286))
    assert apk.read_apk(p) == {"package": "me.jxl.kiosk_satellite", "versionName": "2026.9.87",
                               "versionCode": 286, "abis": ["armeabi-v7a"]}
    p.write_bytes(build_apk(abis=("x86_64", "arm64-v8a", "armeabi-v7a")))
    assert apk.read_apk(p)["abis"] == ["arm64-v8a", "armeabi-v7a", "x86_64"]


def test_not_an_apk(tmp_path):
    p = tmp_path / "x.apk"
    p.write_bytes(b"hello")
    with pytest.raises(apk.ApkError, match="not a zip"):
        apk.read_apk(p)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(apk.ApkError, match="no AndroidManifest"):
        apk.read_apk(p)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("AndroidManifest.xml", "<manifest/>")
    with pytest.raises(apk.ApkError, match="not compiled"):
        apk.read_apk(p)


def test_native_abis_ignores_what_is_not_a_library():
    assert apk.native_abis(["lib/arm64-v8a/libapp.so", "lib/arm64-v8a/", "lib/README",
                            "assets/lib/x86/libz.so", "lib/armeabi-v7a/libapp.so"]) == \
        ["arm64-v8a", "armeabi-v7a"]


ARM64 = {"id": "a64", "abis": ["arm64-v8a"], "versionCode": 302}
ARM32 = {"id": "a32", "abis": ["armeabi-v7a"], "versionCode": 302}
UNIVERSAL = {"id": "uni", "abis": ["arm64-v8a", "armeabi-v7a", "x86_64"], "versionCode": 302}


def test_choose_apk_follows_the_device_preference():
    panel = ["arm64-v8a", "armeabi-v7a", "armeabi"]
    projector = ["armeabi-v7a", "armeabi"]  # a 64-bit CPU on 32-bit Android says this
    assert apk.choose_apk([ARM64, ARM32], panel)["id"] == "a64"
    assert apk.choose_apk([ARM64, ARM32], projector)["id"] == "a32"
    # The split beats the universal APK; the universal one fills the gap.
    assert apk.choose_apk([UNIVERSAL, ARM64], panel)["id"] == "a64"
    assert apk.choose_apk([UNIVERSAL, ARM64], projector)["id"] == "uni"
    # A 64-bit APK never goes to a 32-bit Android.
    assert apk.choose_apk([ARM64], projector) is None
    assert apk.choose_apk([], panel) is None
    assert apk.choose_apk([{"id": "pure", "abis": [], "versionCode": 1}], projector)["id"] == "pure"
    assert apk.runs_on([], ["x86"]) and not apk.runs_on(["arm64-v8a"], projector)

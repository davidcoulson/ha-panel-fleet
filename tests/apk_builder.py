"""Tiny fake APKs: a zip with a compiled AndroidManifest.xml and lib/ dirs.

The binary XML is written here from Android's ResourceTypes.h layout, by
hand and independently of apk.py, so the parser is tested against the
format rather than against itself.
"""

import io
import struct
import zipfile

ANDROID_NS = "http://schemas.android.com/apk/res/android"


def _len8(n):
    return bytes([(n >> 8) | 0x80, n & 0xFF]) if n > 0x7F else bytes([n])


def _string_pool(strings, utf8):
    data = b""
    offsets = []
    for s in strings:
        offsets.append(len(data))
        if utf8:
            b = s.encode("utf-8")
            data += _len8(len(s)) + _len8(len(b)) + b + b"\0"
        else:
            data += struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\0\0"
    data += b"\0" * (-len(data) % 4)
    header = 28
    start = header + 4 * len(strings)
    return (struct.pack("<HHIIIIII", 0x0001, header, start + len(data), len(strings), 0,
                        0x100 if utf8 else 0, start, 0)
            + struct.pack(f"<{len(strings)}I", *offsets) + data)


def manifest_xml(package="me.jxl.kiosk_satellite", version_name="2026.10.4-djc-2026.10.02.2",
                 version_code=302, utf8=False, strip_names=False):
    """A compiled <manifest package=… android:versionCode=…
    android:versionName=…><application/></manifest>. With strip_names the
    attribute names are blank, as a shrunk APK has them, and only the
    resource map says which is which."""
    strings = ["" if strip_names else "versionCode", "" if strip_names else "versionName",
               "package", "manifest", "android", ANDROID_NS, version_name, package, "application"]
    NO = 0xFFFFFFFF
    pool = _string_pool(strings, utf8)
    resmap = struct.pack("<HHI", 0x0180, 8, 16) + struct.pack("<II", 0x0101021B, 0x0101021C)
    ns = struct.pack("<HHIIIII", 0x0100, 16, 24, 1, NO, 4, 5)

    def attr(ns_, name, raw, dtype, data):
        return struct.pack("<IIIHBBI", ns_, name, raw, 8, 0, dtype, data)

    attrs = (attr(5, 0, NO, 0x10, version_code) + attr(5, 1, 6, 0x03, 6)
             + attr(NO, 2, 7, 0x03, 7))
    ext = struct.pack("<IIHHHHHH", NO, 3, 20, 20, 3, 0, 0, 0)
    start = struct.pack("<HHIII", 0x0102, 16, 16 + len(ext) + len(attrs), 1, NO) + ext + attrs
    app_ext = struct.pack("<IIHHHHHH", NO, 8, 20, 20, 0, 0, 0, 0)
    app = struct.pack("<HHIII", 0x0102, 16, 16 + len(app_ext), 2, NO) + app_ext
    body = pool + resmap + ns + start + app
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def build_apk(abis=("arm64-v8a",), payload=b"", **manifest):
    """The bytes of a fake APK carrying native code for `abis`, padded with
    `payload` so a test can make it as large as it likes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("AndroidManifest.xml", manifest_xml(**manifest))
        z.writestr("classes.dex", b"dex\n035\0")
        for abi in abis:
            z.writestr(f"lib/{abi}/libapp.so", b"\x7fELF" + abi.encode())
            z.writestr(f"lib/{abi}/libflutter.so", b"\x7fELF")
        if payload:
            z.writestr("assets/flutter_assets/blob.bin", payload)
    return buf.getvalue()

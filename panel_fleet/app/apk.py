"""What an uploaded Kiosk Satellite APK is, read from the file itself.

The add-on has no aapt, so this reads the two things a fleet update needs
straight out of the zip: the compiled AndroidManifest.xml (Android's binary
XML, "AXML") for the package, versionName and versionCode, and the lib/
folders for the native ABIs the APK carries. A Kiosk Satellite release has
a universal APK (every ABI) and one APK per ABI; a fork build is often one
ABI only (arm64-v8a for the wall panels, armeabi-v7a for 32-bit boxes).

Which APK a device gets mirrors Kiosk Satellite's own selectReleaseApk
(app/lib/managers/update/release_apk.dart): Android's supported ABIs in
their preference order, the first one an APK carries wins, an APK built for
that ABI alone before a universal one.
"""

import struct
import zipfile

KS_PACKAGE = "me.jxl.kiosk_satellite"

# The ABIs a Kiosk Satellite release is built for.
KNOWN_ABIS = ("arm64-v8a", "armeabi-v7a", "x86_64")

# Binary XML chunk types (frameworks/base/libs/androidfw ResourceTypes.h).
_RES_STRING_POOL = 0x0001
_RES_XML = 0x0003
_RES_XML_START_ELEMENT = 0x0102
_RES_XML_RESOURCE_MAP = 0x0180
_UTF8_FLAG = 0x100
_NO_INDEX = 0xFFFFFFFF

# Typed values (Res_value::dataType).
_TYPE_REFERENCE = 0x01
_TYPE_STRING = 0x03
_TYPE_INT_DEC = 0x10
_TYPE_INT_HEX = 0x11

# android:versionCode and android:versionName by resource id, for a
# manifest whose attribute names were stripped from the string pool.
_ATTR_IDS = {0x0101021B: "versionCode", 0x0101021C: "versionName"}


class ApkError(ValueError):
    """The file is not an APK this add-on can read; the message says why."""


def _string_pool(data, pos):
    (_, header, _, count, _, flags, start, _) = struct.unpack_from("<HHIIIIII", data, pos)
    offsets = struct.unpack_from(f"<{count}I", data, pos + header)
    base = pos + start
    utf8 = flags & _UTF8_FLAG
    out = []
    for off in offsets:
        p = base + off
        if utf8:
            # The length in UTF-16 units, then in bytes, each one byte or two.
            p += 2 if data[p] & 0x80 else 1
            n = data[p]
            p += 1
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p]
                p += 1
            out.append(data[p:p + n].decode("utf-8", "replace"))
        else:
            (n,) = struct.unpack_from("<H", data, p)
            p += 2
            if n & 0x8000:
                (low,) = struct.unpack_from("<H", data, p)
                n = ((n & 0x7FFF) << 16) | low
                p += 2
            out.append(data[p:p + 2 * n].decode("utf-16-le", "replace"))
    return out


def manifest_attributes(data):
    """The attributes of the <manifest> element of a compiled
    AndroidManifest.xml: strings as strings, typed integers as ints."""
    try:
        kind, header, _ = struct.unpack_from("<HHI", data, 0)
    except struct.error as e:
        raise ApkError("The APK's manifest is empty.") from e
    if kind != _RES_XML:
        raise ApkError("The APK's manifest is not compiled Android XML.")
    strings, resmap = [], ()
    pos = header
    try:
        while pos + 8 <= len(data):
            kind, header, size = struct.unpack_from("<HHI", data, pos)
            if size < 8 or pos + size > len(data):
                break
            if kind == _RES_STRING_POOL:
                strings = _string_pool(data, pos)
            elif kind == _RES_XML_RESOURCE_MAP:
                resmap = struct.unpack_from(f"<{(size - header) // 4}I", data, pos + header)
            elif kind == _RES_XML_START_ELEMENT:
                ext = pos + header
                _, name, attr_start, attr_size, attr_count = struct.unpack_from("<IIHHH", data, ext)
                if name < len(strings) and strings[name] == "manifest":
                    attrs = {}
                    for i in range(attr_count):
                        a = ext + attr_start + i * attr_size
                        _, aname, raw, _, _, vtype, vdata = struct.unpack_from("<IIIHBBI", data, a)
                        key = strings[aname] if aname < len(strings) else ""
                        if aname < len(resmap) and resmap[aname] in _ATTR_IDS:
                            key = _ATTR_IDS[resmap[aname]]
                        if raw != _NO_INDEX and raw < len(strings):
                            value = strings[raw]
                        elif vtype == _TYPE_STRING and vdata < len(strings):
                            value = strings[vdata]
                        elif vtype in (_TYPE_INT_DEC, _TYPE_INT_HEX):
                            value = vdata
                        elif vtype == _TYPE_REFERENCE:
                            value = None  # a resource reference: not resolvable here
                        else:
                            value = vdata
                        attrs[key] = value
                    return attrs
            pos += size
    except (struct.error, IndexError) as e:
        raise ApkError("The APK's manifest could not be read.") from e
    raise ApkError("The APK has no <manifest> element.")


def native_abis(names):
    """The ABIs an APK carries native code for, from its lib/<abi>/x.so
    entries, sorted. Empty when it has none (it would run anywhere)."""
    abis = set()
    for n in names:
        parts = n.split("/")
        if len(parts) == 3 and parts[0] == "lib" and parts[1] and parts[2].endswith(".so"):
            abis.add(parts[1])
    return sorted(abis)


def read_apk(path):
    """{package, versionName, versionCode, abis} of the APK at `path`, or
    an ApkError saying why it is not one."""
    try:
        with zipfile.ZipFile(path) as z:
            try:
                manifest = z.read("AndroidManifest.xml")
            except KeyError as e:
                raise ApkError("The file has no AndroidManifest.xml: not an APK.") from e
            names = z.namelist()
    except zipfile.BadZipFile as e:
        raise ApkError("The file is not an APK (not a zip archive).") from e
    attrs = manifest_attributes(manifest)
    package = attrs.get("package")
    version = attrs.get("versionName")
    code = attrs.get("versionCode")
    if not isinstance(package, str) or not package:
        raise ApkError("The APK names no package.")
    if not isinstance(version, str) or not version:
        raise ApkError("The APK's versionName could not be read.")
    if not isinstance(code, int):
        raise ApkError("The APK's versionCode could not be read.")
    return {"package": package, "versionName": version, "versionCode": code,
            "abis": native_abis(names)}


def runs_on(apk_abis, device_abis):
    """Whether an APK with native code for `apk_abis` installs on a device
    supporting `device_abis`. An APK with no native code runs anywhere."""
    return not apk_abis or any(a in apk_abis for a in device_abis)


def choose_apk(apks, device_abis):
    """The APK a device gets, by selectReleaseApk's rule: Android lists its
    ABIs by preference (a 64-bit CPU on a 32-bit Android lists 32-bit ones
    only), and the first ABI that some APK carries decides. Between APKs
    carrying it, one built for fewer ABIs (the split) beats a universal one,
    then the newer build. An APK with no native code is the fallback.
    None when nothing fits."""
    for abi in device_abis or ():
        fits = [a for a in apks if abi in (a.get("abis") or ())]
        if fits:
            return min(fits, key=lambda a: (len(a["abis"]), -int(a.get("versionCode") or 0)))
    anywhere = [a for a in apks if not a.get("abis")]
    if anywhere:
        return max(anywhere, key=lambda a: int(a.get("versionCode") or 0))
    return None

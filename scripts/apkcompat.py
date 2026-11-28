#!/usr/bin/env python3
"""Static compatibility check of an APK against two framework trees (B0 = where it is known to run, D2 = target).

Parses DEX (v035-v041 multi-part containers), the binary AndroidManifest.xml and the v2/v3 signer cert in pure
Python: nothing from the ROM is executed. A *regression* is a class/method/field reference the APK makes that
resolves (walking super classes and interfaces) against B0's framework jars but not against D2's. References to
classes in neither tree (ART/APEX boot jars such as java.*) are not judged, only counted.

  apkcompat.py APK B0_FRAMEWORK_DIR D2_FRAMEWORK_DIR [MORE_D2_DIRS...]  -> JSON on stdout"""
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import zipfile

NO_INDEX = 0xFFFFFFFF


def _uleb(b, off):
    out = shift = 0
    while True:
        x = b[off]
        off += 1
        out |= (x & 0x7F) << shift
        shift += 7
        if not x & 0x80:
            return out, off


def _mutf8(b, off):
    _n, off = _uleb(b, off)
    end = b.index(b"\0", off)
    return b[off:end].decode("utf-8", "surrogateescape")


def parse_dex(b):
    """{"classes": {desc: {"super", "ifaces", "methods": {(name, proto)}, "fields": {name}}},
        "method_refs": {(cls, name, proto)}, "field_refs": {(cls, name)}} over every part of the container."""
    if b[:4] != b"dex\n":
        raise ValueError("not a DEX file")
    classes, mrefs, frefs = {}, set(), set()
    h = 0
    while h + 0x70 <= len(b) and b[h:h + 4] == b"dex\n":
        (n_str, o_str, n_typ, o_typ, n_pro, o_pro, n_fld, o_fld, n_met, o_met, n_cls, o_cls) = \
            struct.unpack_from("<12I", b, h + 0x38)
        file_size = struct.unpack_from("<I", b, h + 0x20)[0]
        # v041 parts keep offsets relative to the container start; older files are a single part at 0
        strs = {}
        s = lambda i: strs[i] if i in strs else strs.setdefault(i, _mutf8(b, struct.unpack_from("<I", b, o_str + 4 * i)[0]))
        types = [s(x) for x in struct.unpack_from(f"<{n_typ}I", b, o_typ)]

        def tlist(off):
            if not off:
                return []
            n = struct.unpack_from("<I", b, off)[0]
            return [types[i] for i in struct.unpack_from(f"<{n}H", b, off + 4)]

        protos = []
        for i in range(n_pro):
            _shorty, ret, params = struct.unpack_from("<III", b, o_pro + 12 * i)
            protos.append("(" + "".join(tlist(params)) + ")" + types[ret])
        fields = [(types[c], s(n)) for c, _t, n in (struct.unpack_from("<HHI", b, o_fld + 8 * i) for i in range(n_fld))]
        methods = [(types[c], s(n), protos[p]) for c, p, n in
                   (struct.unpack_from("<HHI", b, o_met + 8 * i) for i in range(n_met))]
        frefs.update(fields)
        mrefs.update(methods)
        for i in range(n_cls):
            cls, _acc, sup, ifaces, _src, _ann, data, _sv = struct.unpack_from("<8I", b, o_cls + 32 * i)
            c = {"super": None if sup == NO_INDEX else types[sup], "ifaces": tlist(ifaces), "methods": set(),
                 "fields": set()}
            if data:
                counts, off = [], data
                for _ in range(4):
                    v, off = _uleb(b, off)
                    counts.append(v)
                for k, n in enumerate(counts):
                    idx = 0
                    for _ in range(n):
                        d, off = _uleb(b, off)
                        idx += d
                        _a, off = _uleb(b, off)
                        if k < 2:
                            c["fields"].add(fields[idx][1])
                        else:
                            _code, off = _uleb(b, off)
                            c["methods"].add(methods[idx][1:])
            classes.setdefault(types[cls], c)  # first definition wins, as in the class loader
        if not file_size:
            break
        h += file_size
    return {"classes": classes, "method_refs": mrefs, "field_refs": frefs}


def _merge(dexes):
    out = {"classes": {}, "method_refs": set(), "field_refs": set()}
    for d in dexes:
        for k, v in d["classes"].items():
            out["classes"].setdefault(k, v)
        out["method_refs"] |= d["method_refs"]
        out["field_refs"] |= d["field_refs"]
    return out


def _zip_dex(path):
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if n.startswith("classes") and n.endswith(".dex") and "/" not in n),
                       key=lambda n: (len(n), n))  # classes.dex, classes2.dex, ... classes10.dex
        return [parse_dex(z.read(n)) for n in names]


def apk_dex(path):
    return _merge(_zip_dex(path))


def framework_classes(dirs):
    """Defined classes of every .jar/.apk directly inside each dir (first dir wins on duplicates)."""
    dexes = []
    for d in dirs:
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            if n.endswith((".jar", ".apk")) and os.path.isfile(p) and zipfile.is_zipfile(p):
                dexes += _zip_dex(p)
    return _merge(dexes)["classes"]


def _resolve(world, cls, kind, member):
    """True/False when the hierarchy is fully known; None when it reaches a class outside `world`."""
    todo, seen, unknown = [cls], set(), False
    while todo:
        c = todo.pop()
        if c in seen:
            continue
        seen.add(c)
        if c not in world:
            unknown = True
            continue
        if member in world[c][kind]:
            return True
        todo += ([world[c]["super"]] if world[c]["super"] else []) + world[c]["ifaces"]
    return None if unknown else False


def compare(app, base_fw, target_fw):
    """Refs the app makes into the framework that resolve on base but not on target (see module doc)."""
    own = app["classes"]
    base, target = {**base_fw, **own}, {**target_fw, **own}
    reg = {"classes": set(), "methods": [], "fields": []}
    both = {"methods": [], "fields": []}
    outside, external = set(), 0
    refs = [("methods", (c, (n, p)), f"{c}->{n}{p}") for c, n, p in app["method_refs"]]
    refs += [("fields", (c, n), f"{c}->{n}") for c, n in app["field_refs"]]
    for kind, (cls, member), label in refs:
        if cls in own and _resolve(own, cls, kind, member):
            continue  # satisfied by the app itself
        if cls.startswith("[") or (cls not in own and cls not in base_fw and cls not in target_fw):
            outside.add(cls) if not cls.startswith("[") else None
            continue
        if kind == "methods":
            external += 1
        on_base, on_target = _resolve(base, cls, kind, member), _resolve(target, cls, kind, member)
        if on_base and not on_target:
            reg[kind].append(label)
            if cls in base_fw and cls not in target_fw:
                reg["classes"].add(cls)
        elif not on_base and not on_target:
            both[kind].append(label)
    return {"regressions": {"classes": sorted(reg["classes"]), "methods": sorted(reg["methods"]),
                            "fields": sorted(reg["fields"])},
            "unresolved_on_both": {k: sorted(v) for k, v in both.items()},
            "external_method_refs": external, "outside_framework_sets": sorted(outside)}


# --- binary XML (AndroidManifest.xml) ---
ATTR_IDS = {0x01010003: "name", 0x0101000B: "sharedUserId", 0x0101020C: "minSdkVersion",
            0x01010270: "targetSdkVersion", 0x0101028E: "required", 0x01010009: "protectionLevel"}


def _string_pool(b, off):
    _t, hsz, _size, count, _styles, flags, start, _ss = struct.unpack_from("<HHIIIIII", b, off)
    offs = struct.unpack_from(f"<{count}I", b, off + hsz)
    out, base = [], off + start
    for o in offs:
        p = base + o
        if flags & 0x100:  # UTF-8: utf16 length, then utf8 length, each 1 or 2 bytes
            p += 2 if b[p] & 0x80 else 1
            n = ((b[p] & 0x7F) << 8 | b[p + 1]) if b[p] & 0x80 else b[p]
            p += 2 if b[p] & 0x80 else 1
            out.append(b[p:p + n].decode("utf-8", "surrogateescape"))
        else:
            n = struct.unpack_from("<H", b, p)[0]
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", b, p + 2)[0]
                p += 2
            out.append(b[p + 2:p + 2 + 2 * n].decode("utf-16-le", "surrogatepass"))
    return out


def parse_axml(b):
    """[(tag, {attr: value})] for each start element; typed ints stay ints, strings stay strings."""
    if struct.unpack_from("<H", b, 0)[0] != 3:
        raise ValueError("not a binary XML document")
    strings, resmap, out = [], [], []
    off = struct.unpack_from("<H", b, 2)[0]
    while off + 8 <= len(b):
        typ, hsz, size = struct.unpack_from("<HHI", b, off)
        if typ == 0x0001:
            strings = _string_pool(b, off)
        elif typ == 0x0180:
            resmap = list(struct.unpack_from(f"<{(size - hsz) // 4}I", b, off + hsz))
        elif typ == 0x0102:
            _ns, name, astart, asize, count = struct.unpack_from("<IIHHH", b, off + 16)
            attrs = {}
            for i in range(count):
                _ans, an, raw, _sz, _r, dtype, data = struct.unpack_from("<IIIHBBI", b, off + 16 + astart + i * asize)
                key = ATTR_IDS.get(resmap[an]) if an < len(resmap) and resmap[an] in ATTR_IDS else strings[an]
                if dtype == 0x03:
                    attrs[key] = strings[data]
                elif dtype == 0x12:
                    attrs[key] = data != 0
                elif raw != NO_INDEX:
                    attrs[key] = strings[raw]
                else:
                    attrs[key] = data
            out.append((strings[name], attrs))
        if size <= 0:
            break
        off += size
    return out


def _value(dtype, data, strings):
    if dtype == 0x03:
        return strings[data]
    if dtype == 0x12:
        return "true" if data else "false"
    if dtype == 0x10:
        return str(data - (1 << 32) if data & 0x80000000 else data)
    if 0x1C <= dtype <= 0x1F:
        return f"#{data:08x}"
    if dtype in (0x01, 0x07):
        return f"@0x{data:08x}"
    return f"type{dtype:#x}:{data:#x}"  # dimensions, fractions, floats: compared raw


def parse_arsc(b):
    """{"type/key[@config]": value} for every entry of every package; bags (styles, arrays) as "<bag N>"."""
    if struct.unpack_from("<H", b, 0)[0] != 2:
        raise ValueError("not a resources.arsc table")
    off, gstr, out = struct.unpack_from("<H", b, 2)[0], [], {}
    while off + 8 <= len(b):
        typ, hsz, size = struct.unpack_from("<HHI", b, off)
        if typ == 0x0001:
            gstr = _string_pool(b, off)
        elif typ == 0x0200:
            tstr_off, _lt, kstr_off = struct.unpack_from("<III", b, off + 268)
            tnames, keys = _string_pool(b, off + tstr_off), _string_pool(b, off + kstr_off)
            p = off + hsz
            while p + 8 <= off + size:
                ctyp, chsz, csize = struct.unpack_from("<HHI", b, p)
                if ctyp == 0x0201:
                    tid, flags, _r, count, start = struct.unpack_from("<BBHII", b, p + 8)
                    cfg = b[p + 24:p + 20 + struct.unpack_from("<I", b, p + 20)[0]]
                    tag = "" if not any(cfg) else "@" + cfg.hex().rstrip("0")
                    if flags & 0x01:  # sparse: (index u16, offset/4 u16)
                        offs = [struct.unpack_from("<HH", b, p + chsz + 4 * i)[1] * 4 for i in range(count)]
                    elif flags & 0x02:  # 16-bit offsets/4, 0xffff = absent
                        offs = [None if o == 0xFFFF else o * 4 for o in struct.unpack_from(f"<{count}H", b, p + chsz)]
                    else:
                        offs = [None if o == NO_INDEX else o for o in struct.unpack_from(f"<{count}I", b, p + chsz)]
                    for o in offs:
                        if o is None:
                            continue
                        e = p + start + o
                        esize, eflags, key = struct.unpack_from("<HHI", b, e)
                        if eflags & 0x08:  # compact entry: key in the size slot, dataType in the flags high byte
                            name, val = keys[esize], _value(eflags >> 8, key, gstr)
                        elif eflags & 0x01:
                            name, val = keys[key], f"<bag {struct.unpack_from('<I', b, e + 12)[0]}>"
                        else:
                            _vs, _z, dtype, data = struct.unpack_from("<HBBI", b, e + esize)
                            name, val = keys[key], _value(dtype, data, gstr)
                        out[f"{tnames[tid - 1]}/{name}{tag}"] = val
                p += csize
        off += size
    return out


def _signers(path):
    """(scheme, [sha256 of each signer's first cert DER]) from the APK Signing Block (v3 preferred, then v2)."""
    with open(path, "rb") as f:
        data = f.read()
    eocd = data.rfind(b"PK\x05\x06")
    cd = struct.unpack_from("<I", data, eocd + 16)[0]
    if eocd < 0 or data[cd - 16:cd] != b"APK Sig Block 42":
        return None, []
    size = struct.unpack_from("<Q", data, cd - 24)[0]
    p, end, blocks = cd - size - 8 + 8, cd - 24, {}
    while p < end:
        n, bid = struct.unpack_from("<QI", data, p)
        blocks[bid] = data[p + 12:p + 8 + n]
        p += 8 + n
    lp = lambda b, o: (b[o + 4:o + 4 + struct.unpack_from("<I", b, o)[0]], o + 4 + struct.unpack_from("<I", b, o)[0])
    for scheme, bid in (("v3", 0xF05368C0), ("v2", 0x7109871A)):
        if bid not in blocks:
            continue
        seq, _ = lp(blocks[bid], 0)
        out, o = [], 0
        while o < len(seq):
            signer, o = lp(seq, o)
            signed, _ = lp(signer, 0)
            _digests, q = lp(signed, 0)
            certs, _ = lp(signed, q)
            cert, _ = lp(certs, 0)
            out.append(hashlib.sha256(cert).hexdigest())
        return scheme, out
    return None, []


def _v1_signers(path):
    """sha256 of the first cert DER in META-INF/*.RSA|DSA|EC via openssl (a trusted host tool)."""
    out = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.startswith("META-INF/") and n.upper().endswith((".RSA", ".DSA", ".EC")):
                pem = subprocess.run(["openssl", "pkcs7", "-inform", "DER", "-print_certs"], input=z.read(n),
                                     capture_output=True, check=True).stdout
                der = subprocess.run(["openssl", "x509", "-outform", "DER"], input=pem, capture_output=True,
                                     check=True).stdout
                out.append(hashlib.sha256(der).hexdigest())
    return out


def apk_info(path):
    with zipfile.ZipFile(path) as z:
        elems = parse_axml(z.read("AndroidManifest.xml"))
    root = elems[0][1] if elems and elems[0][0] == "manifest" else {}
    sdk = next((a for t, a in elems if t == "uses-sdk"), {})
    scheme, signers = _signers(path)
    if not signers:
        scheme, signers = ("v1", _v1_signers(path))
    req = lambda v: v not in (False, "false")
    return {"package": root.get("package"), "sharedUserId": root.get("sharedUserId"),
            "versionCode": root.get("versionCode"), "versionName": root.get("versionName"),
            "minSdkVersion": sdk.get("minSdkVersion"), "targetSdkVersion": sdk.get("targetSdkVersion"),
            "uses_permissions": sorted({a["name"] for t, a in elems if t == "uses-permission" and "name" in a}),
            "permissions": {a["name"]: a.get("protectionLevel") for t, a in elems if t == "permission" and "name" in a},
            "uses_libraries": [{"name": a["name"], "required": req(a.get("required", True))}
                               for t, a in elems if t in ("uses-library", "uses-native-library") and "name" in a],
            "signer_sha256": signers, "signing_scheme": scheme}


def parse_privapp_xml(text):
    """{package: {permission}} from <privapp-permissions> blocks; comments and deny-permission are ignored.
    Regex, not an XML parser: ROM XML is untrusted and entity expansion is not wanted here."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out = {}
    for pkg, body in re.findall(r'<privapp-permissions\s+package="([^"]+)"\s*>(.*?)</privapp-permissions>', text, re.S):
        out.setdefault(pkg, set()).update(re.findall(r'<permission\s+name="([^"]+)"', body))
    return out


def privileged_gaps(requested, defs, allowed):
    """Requested permissions that are privileged (flag 0x10, or legacy signatureOrSystem) and not allowlisted.
    With ro.control_privapp_permissions=enforce each of these makes system_server abort the boot."""
    priv = lambda lvl: bool(lvl & 0x10) or (lvl & 0xF) == 3
    return sorted(p for p in requested if p in defs and priv(defs[p]) and p not in allowed)


def main(argv=None):
    apk, base_dir, *target_dirs = argv if argv is not None else sys.argv[1:]
    r = compare(apk_dex(apk), framework_classes([base_dir]), framework_classes(target_dirs))
    print(json.dumps({"apk": apk, "info": apk_info(apk), **r}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

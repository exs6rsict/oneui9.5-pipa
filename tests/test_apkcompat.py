"""Static APK compatibility: DEX refs (v035 + v041 containers), binary manifest, signer cert, B0->D2 regressions."""
import hashlib, io, os, shutil, struct, sys, tempfile, unittest, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import apkcompat


def uleb(n):
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def make_dex(classes, method_refs=(), field_refs=(), base=0, version=b"035"):
    """classes: {desc: (super_desc|None, [iface], [(name, proto)], [field names])}; proto like '(I)V'.
    method_refs/field_refs: extra (cls, name, proto) / (cls, name) references. base: where this part
    starts in its container (v041 offsets are absolute)."""
    def proto_parts(p):
        args, ret = p[1:].split(")")
        out, i = [], 0
        while i < len(args):
            j = i
            while args[j] == "[":
                j += 1
            j = args.index(";", j) + 1 if args[j] == "L" else j + 1
            out.append(args[i:j])
            i = j
        return out, ret

    mrefs = sorted({(c, n, p) for c, (_s, _i, ms, _f) in classes.items() for n, p in ms} | set(method_refs))
    frefs = sorted({(c, n) for c, (_s, _i, _m, fs) in classes.items() for n in fs} | set(field_refs))
    protos = sorted({p for _c, _n, p in mrefs})
    types = {c for c in classes} | {s for s, _i, _m, _f in classes.values() if s}
    types |= {i for _s, ifs, _m, _f in classes.values() for i in ifs} | {c for c, _n, _p in mrefs}
    types |= {c for c, _n in frefs} | {"I"}
    for p in protos:
        a, r = proto_parts(p)
        types |= set(a) | {r}
    types = sorted(types)
    shorty = lambda p: "".join("L" if t[0] in "L[" else t for t in [proto_parts(p)[1]] + proto_parts(p)[0])
    strings = sorted(set(types) | {n for _c, n, _p in mrefs} | {n for _c, n in frefs} | {shorty(p) for p in protos})
    S, T = {s: i for i, s in enumerate(strings)}, {t: i for i, t in enumerate(types)}
    P = {p: i for i, p in enumerate(protos)}
    M, F = {m: i for i, m in enumerate(mrefs)}, {f: i for i, f in enumerate(frefs)}
    cdefs = sorted(classes)
    hdr = 0x78 if version == b"041" else 0x70
    off = hdr
    sid_off = off; off += 4 * len(strings)
    tid_off = off; off += 4 * len(types)
    pid_off = off; off += 12 * len(protos)
    fid_off = off; off += 8 * len(frefs)
    mid_off = off; off += 8 * len(mrefs)
    cdef_off = off; off += 32 * len(cdefs)
    data = bytearray()
    def put(blob, align=1):
        while (off + len(data)) % align:
            data.append(0)
        at = base + off + len(data)
        data.extend(blob)
        return at
    sdata = [put(uleb(len(s)) + s.encode() + b"\0") for s in strings]
    plists = []
    for p in protos:
        a, _r = proto_parts(p)
        plists.append(put(struct.pack("<I", len(a)) + b"".join(struct.pack("<H", T[t]) for t in a), 4) if a else 0)
    ilists, cdata = [], []
    for c in cdefs:
        _s, ifs, ms, fs = classes[c]
        ilists.append(put(struct.pack("<I", len(ifs)) + b"".join(struct.pack("<H", T[i]) for i in ifs), 4)
                      if ifs else 0)
        fids, mids = sorted(F[(c, n)] for n in fs), sorted(M[(c, n, p)] for n, p in ms)
        blob = uleb(0) + uleb(len(fids)) + uleb(0) + uleb(len(mids))
        prev = 0
        for i in fids:
            blob += uleb(i - prev) + uleb(1); prev = i
        prev = 0
        for i in mids:
            blob += uleb(i - prev) + uleb(1) + uleb(0); prev = i
        cdata.append(put(blob))
    body = bytearray()
    body += b"".join(struct.pack("<I", o) for o in sdata)
    body += b"".join(struct.pack("<I", S[t]) for t in types)
    for p, lo in zip(protos, plists):
        body += struct.pack("<III", S[shorty(p)], T[proto_parts(p)[1]], lo)
    body += b"".join(struct.pack("<HHI", T[c], T["I"], S[n]) for c, n in frefs)
    body += b"".join(struct.pack("<HHI", T[c], P[p], S[n]) for c, n, p in mrefs)
    for c, il, cd in zip(cdefs, ilists, cdata):
        s = classes[c][0]
        body += struct.pack("<8I", T[c], 1, T[s] if s else 0xFFFFFFFF, il, 0xFFFFFFFF, 0, cd, 0)
    size = hdr + len(body) + len(data)
    a = lambda o: base + o
    h = bytearray(hdr)
    h[0:8] = b"dex\n" + version + b"\0"
    struct.pack_into("<II", h, 0x20, size, hdr)
    struct.pack_into("<12I", h, 0x38, len(strings), a(sid_off), len(types), a(tid_off), len(protos), a(pid_off),
                     len(frefs), a(fid_off), len(mrefs), a(mid_off), len(cdefs), a(cdef_off))
    return bytes(h + body + data)


def jar(path, *dexes):
    with zipfile.ZipFile(path, "w") as z:
        for i, d in enumerate(dexes):
            z.writestr("classes.dex" if i == 0 else f"classes{i + 1}.dex", d)


# --- binary AndroidManifest.xml (UTF-16 string pool) ---
def axml(elements):
    """elements: [(tag, {attr: str|int}) | ('/', tag)] in document order; ints become TYPE_INT_DEC."""
    names = []
    for e in elements:
        for x in ([e[1]] if e[0] == "/" else [e[0], *e[1], *[v for v in e[1].values() if isinstance(v, str)]]):
            if x not in names:
                names.append(x)
    ns = "http://schemas.android.com/apk/res/android"
    names.append(ns)
    pool = b""
    offs = []
    for s in names:
        offs.append(len(pool))
        pool += struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\0\0"
    while len(pool) % 4:
        pool += b"\0"
    sp_hdr = 28
    sp = struct.pack("<HHIIIIII", 1, sp_hdr, sp_hdr + 4 * len(offs) + len(pool), len(names), 0, 0,
                     sp_hdr + 4 * len(offs), 0) + b"".join(struct.pack("<I", o) for o in offs) + pool
    nsi = names.index(ns)
    chunks = b""
    for e in elements:
        if e[0] == "/":
            chunks += struct.pack("<HHIIIII", 0x103, 16, 24, 0, 0xFFFFFFFF, 0xFFFFFFFF, names.index(e[1]))
            continue
        tag, attrs = e
        ab = b""
        for k, v in attrs.items():
            if isinstance(v, int):
                ab += struct.pack("<IIIHBBI", nsi, names.index(k), 0xFFFFFFFF, 8, 0, 0x10, v)
            else:
                ab += struct.pack("<IIIHBBI", nsi, names.index(k), names.index(v), 8, 0, 0x03, names.index(v))
        body = struct.pack("<IIHHHHHH", 0xFFFFFFFF, names.index(tag), 20, 20, len(attrs), 0, 0, 0) + ab
        chunks += struct.pack("<HHIII", 0x102, 16, 16 + len(body), 0, 0xFFFFFFFF) + body
    return struct.pack("<HHI", 3, 8, 8 + len(sp) + len(chunks)) + sp + chunks


def signing_block(cert_der):
    lp = lambda b: struct.pack("<I", len(b)) + b
    signed = lp(b"") + lp(lp(cert_der)) + lp(b"")
    signer = lp(lp(signed) + lp(b"") + lp(b""))
    pair = struct.pack("<I", 0x7109871A) + lp(signer)
    pairs = struct.pack("<Q", len(pair)) + pair
    size = len(pairs) + 8 + 16
    return struct.pack("<Q", size) + pairs + struct.pack("<Q", size) + b"APK Sig Block 42"


def with_signing_block(apk_bytes, block):
    """Insert an APK Signing Block before the central directory and fix the EOCD offset."""
    eocd = apk_bytes.rfind(b"PK\x05\x06")
    cd_off = struct.unpack_from("<I", apk_bytes, eocd + 16)[0]
    out = bytearray(apk_bytes[:cd_off] + block + apk_bytes[cd_off:])
    struct.pack_into("<I", out, eocd + len(block) + 16, cd_off + len(block))
    return bytes(out)


OBJ = ("Ljava/lang/Object;",)
FW_B0 = {"Landroid/app/Activity;": ("Ljava/lang/Object;", [], [("onCreate", "()V"), ("semOld", "()V")], ["mX"]),
         "Lcom/samsung/android/Sem;": ("Ljava/lang/Object;", ["Lcom/samsung/android/ISem;"], [("go", "(I)V")], []),
         "Lcom/samsung/android/ISem;": (None, [], [("iface", "()V")], [])}
FW_D2 = {"Landroid/app/Activity;": ("Ljava/lang/Object;", [], [("onCreate", "()V")], ["mX"]),
         "Lcom/samsung/android/ISem;": (None, [], [("iface", "()V")], [])}
APP = {"Lcom/app/Main;": ("Landroid/app/Activity;", [], [("run", "()V")], [])}
APP_REFS = [("Lcom/app/Main;", "onCreate", "()V"),        # inherited from the framework: fine on both
            ("Landroid/app/Activity;", "semOld", "()V"),  # removed in D2: regression
            ("Lcom/samsung/android/Sem;", "go", "(I)V"),  # whole class removed in D2: regression
            ("Lcom/samsung/android/Sem;", "iface", "()V"),  # via interface on B0
            ("Ljava/lang/String;", "length", "()I")]       # in neither set (ART apex): not a regression
APP_FIELDS = [("Landroid/app/Activity;", "mX"), ("Landroid/app/Activity;", "mGone")]


class DexTest(unittest.TestCase):
    def test_parses_classes_hierarchy_and_refs(self):
        d = apkcompat.parse_dex(make_dex(APP, APP_REFS, APP_FIELDS))
        self.assertEqual(d["classes"]["Lcom/app/Main;"]["super"], "Landroid/app/Activity;")
        self.assertIn(("run", "()V"), d["classes"]["Lcom/app/Main;"]["methods"])
        self.assertIn(("Lcom/samsung/android/Sem;", "go", "(I)V"), d["method_refs"])
        self.assertIn(("Landroid/app/Activity;", "mGone"), d["field_refs"])

    def test_v041_container_parts_use_absolute_offsets(self):
        p1 = make_dex({"La/A;": OBJ + ([], [("a", "()V")], [])}, version=b"041")
        p2 = make_dex({"Lb/B;": ("La/A;", [], [("b", "(I)V")], [])}, [("La/A;", "a", "()V")],
                      base=len(p1), version=b"041")
        d = apkcompat.parse_dex(p1 + p2)
        self.assertEqual(set(d["classes"]), {"La/A;", "Lb/B;"})
        self.assertEqual(d["classes"]["Lb/B;"]["super"], "La/A;")
        self.assertIn(("La/A;", "a", "()V"), d["method_refs"])

    def test_rejects_non_dex(self):
        with self.assertRaises(ValueError):
            apkcompat.parse_dex(b"PK\3\4" + bytes(200))

    def test_regressions_are_refs_resolved_on_base_but_not_target(self):
        app = apkcompat.parse_dex(make_dex(APP, APP_REFS, APP_FIELDS))
        b0 = apkcompat.parse_dex(make_dex(FW_B0))["classes"]
        d2 = apkcompat.parse_dex(make_dex(FW_D2))["classes"]
        r = apkcompat.compare(app, b0, d2)
        self.assertEqual(r["regressions"]["methods"], ["Landroid/app/Activity;->semOld()V",
                                                       "Lcom/samsung/android/Sem;->go(I)V",
                                                       "Lcom/samsung/android/Sem;->iface()V"])
        self.assertEqual(r["regressions"]["classes"], ["Lcom/samsung/android/Sem;"])
        self.assertEqual(r["regressions"]["fields"], [])  # mGone is missing on both: pre-existing, not new
        self.assertEqual(r["unresolved_on_both"]["fields"], ["Landroid/app/Activity;->mGone"])
        self.assertEqual(r["external_method_refs"], 4)  # String.length is outside both framework sets: skipped
        self.assertEqual(r["outside_framework_sets"], ["Ljava/lang/String;"])


def string_pool(strings):
    data, offs = b"", []
    for x in strings:
        offs.append(len(data))
        data += struct.pack("<H", len(x)) + x.encode("utf-16-le") + b"\0\0"
    while len(data) % 4:
        data += b"\0"
    hdr = 28
    return struct.pack("<HHIIIIII", 1, hdr, hdr + 4 * len(offs) + len(data), len(strings), 0, 0,
                       hdr + 4 * len(offs), 0) + b"".join(struct.pack("<I", o) for o in offs) + data


def arsc(entries):
    """entries: [(type, key, dataType, data)] in one package 0x7f, default config; 0x03 data = global string."""
    gstr = [d for _t, _k, dt, d in entries if dt == 3]
    types = sorted({t for t, *_ in entries})
    keys = [k for _t, k, *_ in entries]
    gpool = string_pool(gstr)
    chunks = b""
    for ti, t in enumerate(types, 1):
        es = [e for e in entries if e[0] == t]
        body = b""
        offs = []
        for _t, k, dt, d in es:
            offs.append(len(body))
            val = gstr.index(d) if dt == 3 else d
            body += struct.pack("<HHI", 8, 0, keys.index(k)) + struct.pack("<HBBI", 8, 0, dt, val)
        cfg = struct.pack("<I", 64) + bytes(60)
        hdr = 20 + len(cfg)
        start = hdr + 4 * len(offs)
        chunks += struct.pack("<HHIBBHII", 0x201, hdr, start + len(body), ti, 0, 0, len(offs), start) + cfg
        chunks += b"".join(struct.pack("<I", o) for o in offs) + body
    tpool, kpool = string_pool(types), string_pool(keys)
    phdr = 288
    name = "android".encode("utf-16-le").ljust(256, b"\0")
    pkg_body = tpool + kpool + chunks
    pkg = struct.pack("<HHII", 0x200, phdr, phdr + len(pkg_body), 0x7F) + name
    pkg += struct.pack("<IIIII", phdr, len(types), phdr + len(tpool), len(keys), 0) + pkg_body
    return struct.pack("<HHII", 2, 12, 12 + len(gpool) + len(pkg), 1) + gpool + pkg


class ArscTest(unittest.TestCase):
    def test_lists_entries_with_simple_values(self):
        got = apkcompat.parse_arsc(arsc([("bool", "config_x", 0x12, 1), ("integer", "config_n", 0x10, 280),
                                         ("string", "config_s", 0x03, "tablet")]))
        self.assertEqual(got, {"bool/config_x": "true", "integer/config_n": "280", "string/config_s": "tablet"})


class PrivappTest(unittest.TestCase):
    XML = """<?xml version="1.0" encoding="utf-8"?>
<permissions>
    <privapp-permissions package="com.samsung.android.lool">
        <permission name="android.permission.REBOOT"/>
        <permission name="android.permission.BATTERY_STATS" />
        <deny-permission name="android.permission.SEND_SMS"/>
    </privapp-permissions>
    <!-- <privapp-permissions package="x"><permission name="y"/></privapp-permissions> -->
    <privapp-permissions package="com.other"><permission name="android.permission.DUMP"/></privapp-permissions>
</permissions>"""

    def test_parses_allowlist_ignoring_comments_and_denies(self):
        self.assertEqual(apkcompat.parse_privapp_xml(self.XML),
                         {"com.samsung.android.lool": {"android.permission.REBOOT", "android.permission.BATTERY_STATS"},
                          "com.other": {"android.permission.DUMP"}})

    def test_privileged_gaps(self):
        defs = {"android.permission.REBOOT": 0x12,            # signature|privileged
                "android.permission.MANAGE_X": 0x03,          # signatureOrSystem counts as privileged
                "android.permission.INTERNET": 0x00,          # normal
                "android.permission.SIG_ONLY": 0x02,          # signature: no allowlist needed
                "android.permission.NEW_PRIV": 0x10012}       # privileged with extra flags
        requested = ["android.permission.REBOOT", "android.permission.MANAGE_X", "android.permission.INTERNET",
                     "android.permission.SIG_ONLY", "android.permission.NEW_PRIV", "com.vendor.UNKNOWN"]
        self.assertEqual(apkcompat.privileged_gaps(requested, defs, {"android.permission.REBOOT"}),
                         ["android.permission.MANAGE_X", "android.permission.NEW_PRIV"])


class ApkTest(unittest.TestCase):
    def test_manifest_cert_and_dex_from_apk(self):
        man = axml([("manifest", {"package": "com.samsung.android.lool", "sharedUserId": "android.uid.system"}),
                    ("uses-sdk", {"minSdkVersion": 35, "targetSdkVersion": 36}), ("/", "uses-sdk"),
                    ("uses-permission", {"name": "android.permission.REBOOT"}), ("/", "uses-permission"),
                    ("permission", {"name": "com.samsung.android.lool.permission.X", "protectionLevel": 2}),
                    ("/", "permission"),
                    ("application", {}),
                    ("uses-library", {"name": "semlib", "required": "false"}), ("/", "uses-library"),
                    ("/", "application"), ("/", "manifest")])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("AndroidManifest.xml", man)
            z.writestr("classes.dex", make_dex(APP, APP_REFS))
            z.writestr("classes2.dex", make_dex({"Lcom/app/Two;": OBJ + ([], [], [])}))
        cert = b"\x30\x03\x02\x01\x07"  # opaque DER bytes: only the digest is compared
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "SmartManager_v5.apk")
        with open(path, "wb") as f:
            f.write(with_signing_block(buf.getvalue(), signing_block(cert)))
        info = apkcompat.apk_info(path)
        self.assertEqual(info["package"], "com.samsung.android.lool")
        self.assertEqual(info["sharedUserId"], "android.uid.system")
        self.assertEqual((info["minSdkVersion"], info["targetSdkVersion"]), (35, 36))
        self.assertEqual(info["uses_permissions"], ["android.permission.REBOOT"])
        self.assertEqual(info["permissions"], {"com.samsung.android.lool.permission.X": 2})
        self.assertEqual(info["uses_libraries"], [{"name": "semlib", "required": False}])
        self.assertEqual(info["signer_sha256"], [hashlib.sha256(cert).hexdigest()])
        self.assertEqual(info["signing_scheme"], "v2")
        dex = apkcompat.apk_dex(path)
        self.assertIn("Lcom/app/Two;", dex["classes"])
        self.assertIn("Lcom/app/Main;", dex["classes"])

    def test_framework_merges_every_jar(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        jar(os.path.join(d, "framework.jar"), make_dex(FW_D2))
        jar(os.path.join(d, "ext.jar"), make_dex({"Lext/E;": OBJ + ([], [], [])}))
        with open(os.path.join(d, "notes.txt"), "w") as f:
            f.write("not a jar")
        fw = apkcompat.framework_classes([d])
        self.assertIn("Lext/E;", fw)
        self.assertIn("Landroid/app/Activity;", fw)


if __name__ == "__main__":
    unittest.main()

import io, json, os, sys, tempfile, unittest, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import zipaudit


def make_zip(entries, comment=b""):
    """entries: list of (ZipInfo|name, data). Returns path to a temp zip."""
    fd, path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(path, "w") as z:
        z.comment = comment
        for info, data in entries:
            if isinstance(info, str):
                info = zipfile.ZipInfo(info)
                info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return path


def patch_bytes(path, fn):
    with open(path, "rb") as f:
        raw = bytearray(f.read())
    fn(raw)
    with open(path, "wb") as f:
        f.write(raw)


class AuditTest(unittest.TestCase):
    def audit(self, entries, **kw):
        path = make_zip(entries)
        self.addCleanup(os.unlink, path)
        return zipaudit.audit(path, **kw)

    def test_lists_entry_sizes_and_compression(self):
        r = self.audit([("boot.img", os.urandom(1000))])
        e = r["entries"][0]
        self.assertEqual((e["name"], e["size"], e["compression"]), ("boot.img", 1000, "deflate"))
        self.assertEqual(r["findings"], [])

    def test_reports_path_traversal_and_absolute_names(self):
        r = self.audit([("../evil.sh", b"x"), ("/etc/passwd", b"x"), ("a/../../b", b"x"),
                        ("C:/win.bat", b"x"), ("dir\\..\\x", b"x"), ("ok/file.txt", b"x")])
        bad = sorted(f["entry"] for f in r["findings"] if f["kind"] == "unsafe-path")
        self.assertEqual(bad, ["../evil.sh", "/etc/passwd", "C:/win.bat", "a/../../b", "dir\\..\\x"])

    def test_reports_symlink_entries(self):
        link = zipfile.ZipInfo("vendor/lib")
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        r = self.audit([(link, b"/system/lib"), ("plain", b"x")])
        self.assertEqual([(f["kind"], f["entry"]) for f in r["findings"]], [("symlink", "vendor/lib")])

    def test_reports_exact_and_case_folded_duplicates(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # zipfile warns on duplicate names; that's the fixture
            r = self.audit([("super.img", b"a"), ("super.img", b"b"), ("Boot.img", b"c"), ("boot.img", b"d")])
        dup = sorted(f["entry"] for f in r["findings"] if f["kind"] == "duplicate")
        self.assertEqual(dup, ["boot.img", "super.img"])

    def test_flags_high_compression_ratio_as_possible_bomb(self):
        r = self.audit([("bomb.bin", b"\0" * 20_000_000), ("rand.bin", os.urandom(4096))])
        self.assertEqual([(f["kind"], f["entry"]) for f in r["findings"]], [("high-ratio", "bomb.bin")])
        self.assertEqual(r["totals"]["declared_size"], 20_004_096)

    def test_guesses_partitions_from_image_names_only(self):
        r = self.audit([("super.img", b"x"), ("firmware-update/dtbo.img", b"x"), ("system.new.dat.br", b"x"),
                        ("vendor.img.lz4", b"x"), ("bin/adb", b"x"), ("README.img.txt", b"x")])
        self.assertEqual(r["partitions"], {"dtbo": ["firmware-update/dtbo.img"], "super": ["super.img"],
                                           "system": ["system.new.dat.br"], "vendor": ["vendor.img.lz4"]})

    def test_flags_encrypted_entries(self):
        path = make_zip([("secret.img", b"x")])
        self.addCleanup(os.unlink, path)
        def set_encrypted_bit(raw):
            for sig, flag_off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):  # zipfile won't write bit 0 itself
                raw[raw.index(sig) + flag_off] |= 0x1
        patch_bytes(path, set_encrypted_bit)
        r = zipaudit.audit(path)
        self.assertIn(("encrypted", "secret.img"), [(f["kind"], f["entry"]) for f in r["findings"]])

    def test_reads_allowlisted_text_metadata_with_a_byte_cap(self):
        r = self.audit([("META-INF/com/google/android/updater-script", b"ui_print x\n" * 1_000_000),
                        ("source.properties", b"Pkg.Revision=35.0.2\n"),
                        ("blob.prop", b"ro.x=1\0\xff"), ("system.img", b"ro.build.version.release=17")],
                       text_cap=4096)
        t = r["text"]
        self.assertEqual(sorted(t), ["META-INF/com/google/android/updater-script", "source.properties"])
        self.assertEqual(t["source.properties"], {"text": "Pkg.Revision=35.0.2\n", "truncated": False})
        self.assertEqual((len(t["META-INF/com/google/android/updater-script"]["text"]),
                          t["META-INF/com/google/android/updater-script"]["truncated"]), (4096, True))

    def test_sniffs_container_format_from_a_bounded_prefix(self):
        import struct
        sparse = struct.pack("<I", 0xED26FF3A) + b"\0" * 64
        erofs = b"\0" * 1024 + struct.pack("<I", 0xE0F5E1E2) + b"\0" * 64
        ext4 = b"\0" * 1080 + struct.pack("<H", 0xEF53) + b"\0" * 64
        lp = b"\0" * 4096 + struct.pack("<I", 0x616C4467) + b"\0" * 64
        r = self.audit([("super.img", sparse), ("system.img", erofs), ("vendor.img", ext4), ("odm.img", lp),
                        ("boot.img", b"ANDROID!" + b"\0" * 64), ("vendor_boot.img", b"VNDRBOOT"),
                        ("vbmeta.img", b"AVB0"), ("modem.img", b"\xeb\x3c\x90"), ("adb", b"ANDROID!")])
        self.assertEqual({e["name"]: e.get("format") for e in r["entries"]},
                         {"super.img": "android-sparse", "system.img": "erofs", "vendor.img": "ext4",
                          "odm.img": "lp-super", "boot.img": "android-boot", "vendor_boot.img": "vendor-boot",
                          "vbmeta.img": "avb-vbmeta", "modem.img": "unknown", "adb": None})

    def test_corrupt_payload_stream_is_reported_not_fatal(self):
        path = make_zip([("boot.img", os.urandom(20000)), ("updater-script", b"ok\n")])
        self.addCleanup(os.unlink, path)
        def garble_deflate(raw):
            start = raw.index(b"boot.img") + len("boot.img")  # first name hit is the local header
            raw[start:start + 64] = b"\xff" * 64
        patch_bytes(path, garble_deflate)
        r = zipaudit.audit(path)
        self.assertEqual([(f["kind"], f["entry"]) for f in r["findings"]], [("unreadable", "boot.img")])
        self.assertEqual(r["text"]["updater-script"]["text"], "ok\n")


class CompareTest(unittest.TestCase):
    def inv(self, entries):
        path = make_zip(entries)
        self.addCleanup(os.unlink, path)
        return zipaudit.audit(path)

    def test_compares_entries_and_partitions_between_inventories(self):
        a = self.inv([("boot.img", b"ANDROID!" + b"1" * 10), ("super.img", b"x"), ("same.txt", b"s")])
        b = self.inv([("boot.img", b"ANDROID!" + b"22"), ("system.img", b"x"), ("same.txt", b"s")])
        d = zipaudit.compare(a, b)
        self.assertEqual(d["entries"], {"only_a": ["super.img"], "only_b": ["system.img"],
                                        "changed": [{"name": "boot.img", "a": {"size": 18, "format": "android-boot"},
                                                     "b": {"size": 10, "format": "android-boot"}}]})
        self.assertEqual(d["partitions"], {"only_a": ["super"], "only_b": ["system"], "both": ["boot"]})


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        from contextlib import redirect_stdout, redirect_stderr
        with redirect_stdout(out), redirect_stderr(err):
            code = zipaudit.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_audit_exits_2_on_unsafe_entries_and_writes_json(self):
        path = make_zip([("../x", b"x")])
        self.addCleanup(os.unlink, path)
        code, out, _ = self.run_cli("audit", path)
        self.assertEqual((code, json.loads(out)["findings"][0]["kind"]), (2, "unsafe-path"))

    def test_audit_records_sidecar_sha256_without_rehashing(self):
        path = make_zip([("boot.img", b"x")])
        self.addCleanup(os.unlink, path)
        with open(path + ".metadata.json", "w") as f:
            json.dump({"sha256": "ab" * 32, "bytes": os.path.getsize(path)}, f)
        self.addCleanup(os.unlink, path + ".metadata.json")
        code, out, _ = self.run_cli("audit", path)
        arch = json.loads(out)["archive"]
        self.assertEqual((code, arch["sidecar_sha256"], arch["bytes"]), (0, "ab" * 32, os.path.getsize(path)))

    def test_rejects_non_zip_input_with_exit_1(self):
        fd, path = tempfile.mkstemp()
        os.write(fd, b"not a zip at all")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        code, out, err = self.run_cli("audit", path)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("not a readable zip", err)

    def test_compare_reads_two_inventory_files(self):
        paths = []
        for names in (["boot.img"], ["system.img"]):
            z = make_zip([(n, b"x") for n in names])
            self.addCleanup(os.unlink, z)
            fd, j = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            self.addCleanup(os.unlink, j)
            self.assertEqual(self.run_cli("audit", z, "-o", j)[0], 0)
            paths.append(j)
        code, out, _ = self.run_cli("compare", *paths)
        self.assertEqual((code, json.loads(out)["partitions"]["only_b"]), (0, ["system"]))

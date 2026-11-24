"""Slot-A LP re-layout validator: proposes an aligned _a layout from the Gate 5 manifest and hard-rejects anything
touching GPT, userdata (sda34), linux (sda35), slot B, firmware or a raw super write. It never approves a flash."""
import copy, hashlib, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import lprelayout

ALIGN = 4096
SUPER = 64 * ALIGN
GPT = """label: gpt
device: /dev/sda
unit: sectors
sector-size: 4096

/dev/sda29 : start=      100, size=       {super}, type=X, uuid=Y, name="super"
/dev/sda34 : start=      200, size=       50, type=X, uuid=Y, name="userdata"
/dev/sda35 : start=      300, size=       50, type=X, uuid=Y, name="linux"
"""
SIZES = {"system_a": 9 * ALIGN + 1, "system_ext_a": 2 * ALIGN, "product_a": ALIGN, "vendor_a": 3 * ALIGN,
         "odm_a": 10}


def lp(b_size=None, group_max=SUPER):
    parts = [{"name": n, "group_name": "qti_dynamic_partitions_a", "size": str(ALIGN)} for n in SIZES]
    parts += [{"name": n.replace("_a", "_b"), "group_name": "qti_dynamic_partitions_b"} for n in SIZES]
    if b_size:
        parts[-1]["size"] = str(b_size)
    return {"partitions": parts,
            "groups": [{"name": "default"}, {"name": "qti_dynamic_partitions_a", "maximum_size": str(group_max)},
                       {"name": "qti_dynamic_partitions_b", "maximum_size": str(group_max)}],
            "block_devices": [{"name": "super", "size": str(SUPER), "block_size": "4096", "alignment": str(ALIGN)}]}


class RelayoutTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.arts = [dict(self.blob(f"{n}.img", b"x" * s), target=f"super:{n}", name=n) for n, s in SIZES.items()]
        self.boot = self.blob("boot.img", b"k" * 100)

    def blob(self, name, data):
        path = os.path.join(self.d, name)
        with open(path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        return {"path": path, "sha256": hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()}

    def plan(self, gpt=GPT.format(super=SUPER // ALIGN), layout=None, arts=None, **extra):
        manifest = {"artifacts": arts if arts is not None else self.arts, "approved_to_flash": False}
        p = {"slot": "a",
             "layout_backup": {"gpt": self.blob("gpt.sfdisk", gpt),
                               "super_lp": self.blob("lp.json", json.dumps(layout or lp()))},
             "manifest": self.blob("manifest.json", json.dumps(manifest))}
        p.update(extra)
        return p

    def rules(self, plan):
        return sorted({v["rule"] for v in lprelayout.validate(plan)["violations"]})

    def test_clean_plan_proposes_aligned_a_layout_but_never_approves(self):
        r = lprelayout.validate(self.plan(writes=[{"op": "write", "target": "boot_a", "image": self.boot}]))
        self.assertEqual((r["violations"], r["passes_relayout_checks"], r["requires_explicit_user_approval"],
                          r["approved_to_flash"]), ([], True, True, False))
        L = r["proposed_layout"]
        self.assertEqual({n: (v["offset"], v["size"]) for n, v in L["partitions"].items()},
                         {"system_a": (ALIGN, 10 * ALIGN), "system_ext_a": (11 * ALIGN, 2 * ALIGN),
                          "product_a": (13 * ALIGN, ALIGN), "vendor_a": (14 * ALIGN, 3 * ALIGN),
                          "odm_a": (17 * ALIGN, ALIGN)})
        self.assertEqual((L["used_bytes"], L["free_after_bytes"]), (17 * ALIGN, SUPER - 18 * ALIGN))
        self.assertEqual(L["slot_b_unchanged_empty"], ["odm_b", "product_b", "system_b", "system_ext_b", "vendor_b"])

    def test_logical_write_is_checked_against_proposed_not_live_extent(self):
        img = {k: self.arts[0][k] for k in ("path", "sha256")}  # system_a: 9 blocks + 1 B > live 1 block
        self.assertEqual(self.rules(self.plan(writes=[{"op": "write", "target": "system_a", "image": img}])), [])

    def test_rejects_gpt_userdata_linux_firmware_and_raw_super_writes(self):
        for t, rule in (("gpt", "protected"), ("PrimaryGPT", "protected"), ("userdata", "protected"),
                        ("linux", "protected"), ("/dev/sda34", "protected"), ("/dev/sda35", "protected"),
                        ("xbl_a", "protected"), ("abl", "protected"), ("super", "shared-super"),
                        ("super_a", "shared-super")):
            with self.subTest(t):
                self.assertIn(rule, self.rules(self.plan(writes=[{"op": "write", "target": t, "image": self.boot}])))

    def test_rejects_any_other_operation_or_plan_key(self):
        for key in ("gpt_edit", "super_image", "erase", "resize"):
            with self.subTest(key):
                self.assertIn("operation", self.rules(self.plan(**{key: {"target": "sda34"}})))
        for op in ("erase", "format", "resize-logical-partition", "set_active"):
            with self.subTest(op):
                self.assertIn("operation", self.rules(self.plan(writes=[{"op": op, "target": "boot_a"}])))

    def test_rejects_slot_b_targets_slot_and_slot_b_owning_space(self):
        self.assertIn("slot-b", self.rules(self.plan(writes=[{"op": "write", "target": "boot_b", "image": self.boot}])))
        p = self.plan()
        p["slot"] = "b"
        self.assertIn("slot-b", self.rules(p))
        self.assertIn("slot-b", self.rules(self.plan(layout=lp(b_size=ALIGN))))

    def test_rejects_gpt_dump_that_moved_overlapped_or_mismatched_guarded_partitions(self):
        good = GPT.format(super=SUPER // ALIGN)
        for name, gpt in (("linux moved", good.replace("sda35", "sda36")),
                          ("userdata missing", good.replace('name="userdata"', 'name="data"')),
                          ("overlap", good.replace("start=      300", "start=      220")),
                          ("super size", GPT.format(super=SUPER // ALIGN + 1)),
                          ("not sfdisk", "garbage")):
            with self.subTest(name):
                self.assertIn("gpt", self.rules(self.plan(gpt=gpt)))

    def test_rejects_bad_backup_manifest_or_image_hashes(self):
        p = self.plan()
        p["layout_backup"]["gpt"]["sha256"] = "0" * 64
        self.assertIn("layout-backup", self.rules(p))
        p = self.plan()
        p["manifest"]["sha256"] = "0" * 64
        self.assertIn("manifest", self.rules(p))
        arts = copy.deepcopy(self.arts)
        arts[2]["sha256"] = "f" * 64
        self.assertIn("image-hash", self.rules(self.plan(arts=arts)))
        self.assertIn("manifest", self.rules(self.plan(arts=self.arts[:4])))
        self.assertIn("manifest", self.rules(self.plan(arts=self.arts + [dict(self.arts[0], target="super:system_b")])))

    def test_rejects_layout_that_does_not_fit_group_or_super(self):
        self.assertIn("fit", self.rules(self.plan(layout=lp(group_max=16 * ALIGN))))
        big = [dict(self.blob("huge.img", b"z" * SUPER), target="super:system_a")] + self.arts[1:]
        self.assertIn("fit", self.rules(self.plan(arts=big)))


if __name__ == "__main__":
    unittest.main()

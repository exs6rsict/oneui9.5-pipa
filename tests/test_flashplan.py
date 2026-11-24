"""A-only write-plan validator: rejects anything that could touch slot B, shared super metadata,
the Linux host partition, GPT, userdata/metadata, or that lacks a verified layout backup."""
import copy, hashlib, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import flashplan

LAYOUT = {"partitions": {"system_a": {"size": 8192}, "vendor_a": {"size": 4096}, "system_b": {"size": 16384}}}


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.backup = {k: self.blob(k, json.dumps(LAYOUT) if k == "super_lp" else "gpt-dump")
                       for k in ("gpt", "super_lp")}
        self.img = self.blob("boot.img", "x" * 100)

    def blob(self, name, text):
        path = os.path.join(self.d, name)
        with open(path, "w") as f:
            f.write(text)
        return {"path": path, "sha256": hashlib.sha256(text.encode()).hexdigest()}

    def plan(self, *writes):
        return {"slot": "a", "layout_backup": copy.deepcopy(self.backup), "writes": list(writes)}

    def kinds(self, plan):
        return sorted({v["rule"] for v in flashplan.validate(plan)["violations"]})

    def test_clean_a_only_boot_plan_passes_checks_but_still_needs_user_approval(self):
        r = flashplan.validate(self.plan({"op": "write", "target": "boot_a", "image": self.img}))
        self.assertEqual((r["violations"], r["passes_preserve_layout_checks"], r["requires_explicit_user_approval"],
                          r["approved_to_flash"]), ([], True, True, False))

    def test_rejects_slot_b_and_ab_targets(self):
        for t in ("boot_b", "vendor_boot_b", "system_b", "boot_ab", "dtbo_AB"):
            with self.subTest(t):
                self.assertIn("slot-b", self.kinds(self.plan({"op": "write", "target": t, "image": self.img})))

    def test_rejects_whole_shared_super_overwrite(self):
        for w in ({"op": "write", "target": "super", "image": self.img},
                  {"op": "write", "target": "super_a", "image": self.img}):
            with self.subTest(w["target"]):
                self.assertIn("shared-super", self.kinds(self.plan(w)))

    def test_rejects_linux_host_gpt_userdata_metadata_by_name_or_device(self):
        for t in ("linux", "userdata", "metadata", "gpt", "PrimaryGPT", "/dev/sda35", "/dev/sda29",
                  "PARTUUID=00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002", "/dev/block/by-name/boot_a"):
            with self.subTest(t):
                self.assertIn("protected", self.kinds(self.plan({"op": "write", "target": t, "image": self.img})))

    def test_rejects_non_write_operations(self):
        for op in ("erase", "format", "set_active", "reboot", "delete-logical-partition", "resize-logical-partition"):
            with self.subTest(op):
                self.assertIn("operation", self.kinds(self.plan({"op": op, "target": "boot_a"})))

    def test_rejects_missing_or_mismatched_layout_backup(self):
        p = self.plan({"op": "write", "target": "boot_a", "image": self.img})
        del p["layout_backup"]["super_lp"]
        self.assertIn("layout-backup", self.kinds(p))
        p = self.plan({"op": "write", "target": "boot_a", "image": self.img})
        p["layout_backup"]["gpt"]["sha256"] = "0" * 64
        self.assertIn("layout-backup", self.kinds(p))

    def test_logical_a_write_must_fit_existing_extent_from_backup(self):
        big = self.blob("system.img", "y" * 12288)  # larger than live system_a (8192): would need LP edit
        self.assertIn("extent", self.kinds(self.plan({"op": "write", "target": "system_a", "image": big})))
        small = self.blob("system_small.img", "y" * 8192)
        self.assertNotIn("extent", self.kinds(self.plan({"op": "write", "target": "system_a", "image": small})))
        self.assertEqual(self.kinds(self.plan({"op": "write", "target": "system_a", "image": small})), [])

    def test_rejects_bootloader_firmware_and_unhashed_images(self):
        self.assertIn("protected", self.kinds(self.plan({"op": "write", "target": "xbl_a", "image": self.img})))
        bad = dict(self.img, sha256="f" * 64)
        self.assertIn("image-hash", self.kinds(self.plan({"op": "write", "target": "boot_a", "image": bad})))

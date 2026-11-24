"""End-to-end recipe on tiny fixtures: donor ext4 system + overlay + props -> sparse super; verified by readback."""
import hashlib, os, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import port95_build, sparselp

NEEDED = ("mke2fs", "debugfs", "e2fsck", "resize2fs", "mkfs.erofs", "lpmake", "lpdump")
LABEL = "u:object_r:system_file:s0"


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@unittest.skipUnless(all(shutil.which(t) for t in NEEDED), "android-tools/e2fsprogs/erofs-utils missing")
class BuildRecipeTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        src = self.p("donor_src")
        os.makedirs(os.path.join(src, "system/bin"))
        os.makedirs(os.path.join(src, "system/etc/init"))
        with open(os.path.join(src, "system/build.prop"), "w") as f:
            f.write("ro.build.version.sdk=37\n")
        os.makedirs(os.path.join(src, "system/product/etc/selinux"))
        with open(os.path.join(src, "system/product/etc/selinux/product_sepolicy.cil"), "w") as f:
            f.write("(type product_t)\n")
        with open(os.path.join(src, "system/bin/toybox"), "wb") as f:
            f.write(b"\x7fELF")
        self.donor = self.p("donor.img")
        subprocess.run(["mke2fs", "-q", "-t", "ext4", "-N", "32", "-d", src, self.donor, "4M"], check=True)
        label = self.p("label")
        with open(label, "wb") as f:
            f.write(LABEL.encode() + b"\0")
        for path in ("/system/build.prop", "/system/product/etc/selinux/product_sepolicy.cil"):
            subprocess.run(["debugfs", "-w", "-R", f"ea_set -f {label} {path} security.selinux", self.donor],
                           check=True, capture_output=True)
        self.donor_sha = sha(self.donor)
        for part in ("vendor", "odm"):
            os.makedirs(self.p(part + "_src"))
            with open(self.p(part + "_src", "build.prop"), "w") as f:
                f.write(f"ro.{part}.x=1\n")
            subprocess.run(["mkfs.erofs", "--quiet", self.p(part + ".img"), self.p(part + "_src")],
                           check=True, capture_output=True)
        ov = self.p("overlay")
        os.makedirs(os.path.join(ov, "system/bin"))
        os.makedirs(os.path.join(ov, "system/etc/init"))
        for rel, body, mode in (("system/bin/xiaomi-touch", b"\x7fELFtouch" * 300, 0o755),
                                ("system/etc/init/x.rc", b"service x /system/bin/xiaomi-touch\n", 0o644)):
            with open(os.path.join(ov, rel), "wb") as f:
                f.write(body)
            os.chmod(os.path.join(ov, rel), mode)

    def p(self, *n):
        return os.path.join(self.d, *n)

    def test_builds_verifiable_super_with_overlay_and_props(self):
        m = port95_build.build(donor_system=self.donor, vendor=self.p("vendor.img"), odm=self.p("odm.img"),
                               overlay=self.p("overlay"), props={"ro.radio.noril": "yes"},
                               workdir=self.p("work"), out_super=self.p("super.img"),
                               super_size=128 << 20, group="qti_dynamic_partitions")
        self.assertEqual(sha(self.donor), self.donor_sha, "donor input must stay untouched")
        sysimg = m["partitions"]["system_a"]["image"]
        cat = lambda path: subprocess.run(["debugfs", "-R", f"cat {path}", sysimg], capture_output=True).stdout
        self.assertEqual(cat("/system/bin/xiaomi-touch"), b"\x7fELFtouch" * 300)
        self.assertTrue(cat("/system/build.prop").endswith(b"ro.radio.noril=yes\n"))
        stat = subprocess.run(["debugfs", "-R", "stat /system/bin/xiaomi-touch", sysimg],
                              capture_output=True, text=True).stdout
        self.assertIn("Mode:  0755", stat)
        self.assertIn("Group:  2000", stat)
        self.assertIn(f'security.selinux (26) = "{LABEL}\\000"', stat)
        with open(self.p("super.img"), "rb") as f:
            layout = sparselp.lp_layout(sparselp.raw_prefix(f, 1 << 20))
        with open(self.p("super.img"), "rb") as f:
            hashes = sparselp.hash_partitions(f, layout, ["system_a", "vendor_a", "odm_a"])
        self.assertEqual(hashes, {"system_a": sha(sysimg), "vendor_a": sha(self.p("vendor.img")),
                                  "odm_a": sha(self.p("odm.img"))})
        self.assertEqual(m["verified"], {"e2fsck": "clean", "overlay_readback": "match", "super_roundtrip": "match"})

    def test_silent_debugfs_failure_is_caught_by_readback(self):
        os.makedirs(self.p("overlay", "system", "no_such_dir"))
        with open(self.p("overlay", "system", "no_such_dir", "f"), "w") as f:
            f.write("x")
        with self.assertRaisesRegex(RuntimeError, "readback failed for /system/no_such_dir/f"):
            port95_build.build(donor_system=self.donor, vendor=self.p("vendor.img"), odm=self.p("odm.img"),
                               overlay=self.p("overlay"), props={}, workdir=self.p("work"),
                               out_super=self.p("super.img"), super_size=128 << 20, group="qti_dynamic_partitions")

    def test_appends_cil_and_can_build_partition_image_only(self):
        cil = self.p("perm.cil")
        with open(cil, "w") as f:
            f.write("(typepermissive product_t)\n")
        m = port95_build.build(donor_system=self.donor, vendor=self.p("vendor.img"), odm=self.p("odm.img"),
                               overlay=self.p("overlay"), props={}, workdir=self.p("work"), out_super=None,
                               super_size=128 << 20, group="qti_dynamic_partitions",
                               appends={"/system/product/etc/selinux/product_sepolicy.cil": cil})
        got = subprocess.run(["debugfs", "-R", "cat /system/product/etc/selinux/product_sepolicy.cil",
                              m["partitions"]["system_a"]["image"]], capture_output=True).stdout
        self.assertEqual(got, b"(type product_t)\n(typepermissive product_t)\n")
        self.assertNotIn("super", m)
        self.assertFalse(os.path.exists(self.p("super.img")))

    def test_refuses_to_append_to_a_file_without_selinux_label(self):
        subprocess.run(["debugfs", "-w", "-R", "ea_rm /system/build.prop security.selinux", self.donor],
                       check=True, capture_output=True)
        with self.assertRaisesRegex(RuntimeError, "label"):
            port95_build.build(donor_system=self.donor, vendor=self.p("vendor.img"), odm=self.p("odm.img"),
                               overlay=self.p("overlay"), props={"a": "b"}, workdir=self.p("work"), out_super=None,
                               super_size=128 << 20, group="qti_dynamic_partitions")

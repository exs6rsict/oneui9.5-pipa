"""Collect allowlisted metadata (props, init, VINTF, SELinux, fstab) from an ext4 image via trusted debugfs."""
import os, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fsmeta


@unittest.skipUnless(shutil.which("mke2fs") and shutil.which("debugfs"), "e2fsprogs missing")
class Ext4MetadataTest(unittest.TestCase):
    FSTYPE = "ext4"

    def build(self, src, img):
        subprocess.run(["mke2fs", "-q", "-t", "ext4", "-d", src, img, "8M"], check=True)

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        tree = {"system/build.prop": "ro.build.version.sdk=37\n",
                "system/etc/init/hw/init.rc": "on boot\n",
                "system/etc/vintf/manifest.xml": "<manifest/>",
                "system/etc/selinux/plat_sepolicy.cil": "(allow a b (c (d)))",
                "system/app/Big/Big.apk": "PK" + "x" * 5000}
        src = os.path.join(self.d, "src")
        for rel, body in tree.items():
            os.makedirs(os.path.dirname(os.path.join(src, rel)), exist_ok=True)
            with open(os.path.join(src, rel), "w") as f:
                f.write(body)
        os.symlink("/proc/self/root/etc/passwd", os.path.join(src, "system/etc/vintf/evil.xml"))
        self.img = os.path.join(self.d, "fs.img")
        self.build(src, self.img)

    def test_collects_allowlisted_metadata_and_never_follows_symlinks(self):
        out = os.path.join(self.d, "out")
        got = fsmeta.collect(self.img, self.FSTYPE, out)
        self.assertEqual(sorted(got["files"]), ["system/build.prop", "system/etc/init/hw/init.rc",
                                                "system/etc/selinux/plat_sepolicy.cil",
                                                "system/etc/vintf/manifest.xml"])
        with open(os.path.join(out, "system/build.prop")) as f:
            self.assertEqual(f.read(), "ro.build.version.sdk=37\n")
        self.assertEqual(got["symlinks"], {"system/etc/vintf/evil.xml": "/proc/self/root/etc/passwd"})
        self.assertFalse(os.path.lexists(os.path.join(out, "system/etc/vintf/evil.xml")))


@unittest.skipUnless(shutil.which("mkfs.erofs") and shutil.which("fsck.erofs"), "erofs-utils missing")
class ErofsMetadataTest(Ext4MetadataTest):
    FSTYPE = "erofs"

    def build(self, src, img):
        subprocess.run(["mkfs.erofs", "-zlz4hc", "--quiet", img, src], check=True, capture_output=True)

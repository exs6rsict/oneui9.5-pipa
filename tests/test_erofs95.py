"""ext4 system image -> EROFS repack that must keep owner/mode/symlink/xattr (SELinux, capability) metadata.

Seams: ext4_manifest (what the trusted ext4 reader sees), build (the repack), erofs_manifest (an
independent on-disk EROFS reader + fsck extraction), compare (the verdict). Expected values are literals."""
import os, shutil, subprocess, sys, tarfile, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import erofs95

CAP = bytes.fromhex("0100000200300000" + "00" * 12)   # vfs cap v2: cap_net_admin|cap_net_raw permitted
LONG = "/system/" + "x" * 70                          # > 60 bytes: a slow (block-stored) symlink


def label(s):
    return {"security.selinux": (s + "\0").encode().hex()}


EXPECTED = {
    "/": {"kind": "dir", "mode": 0o755, "uid": 0, "gid": 0, "xattrs": label("u:object_r:rootfs:s0")},
    "/bin": {"kind": "dir", "mode": 0o751, "uid": 0, "gid": 2000, "xattrs": label("u:object_r:system_file:s0")},
    "/bin/tool": {"kind": "file", "mode": 0o4750, "uid": 1000, "gid": 2000, "sha256":
                  "eba7a4536eb55a37babd7edd0c3af2f36e4aca92bfd21b0772dcf3b7936a19c0",
                  "xattrs": {**label("u:object_r:tool_exec:s0"), "security.capability": CAP.hex()}},
    "/bin/tool-link": {"kind": "file", "mode": 0o4750, "uid": 1000, "gid": 2000, "hardlink_of": "/bin/tool",
                       "sha256": "eba7a4536eb55a37babd7edd0c3af2f36e4aca92bfd21b0772dcf3b7936a19c0",
                       "xattrs": {**label("u:object_r:tool_exec:s0"), "security.capability": CAP.hex()}},
    "/etc": {"kind": "dir", "mode": 0o500, "uid": 0, "gid": 0, "xattrs": label("u:object_r:system_file:s0")},
    "/etc/a b.prop": {"kind": "file", "mode": 0o600, "uid": 0, "gid": 0, "xattrs": {},
                      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    "/fast": {"kind": "symlink", "mode": 0o777, "uid": 0, "gid": 2000, "target": "/proc/self/root/etc/passwd",
              "xattrs": label("u:object_r:system_file:s0")},
    "/slow": {"kind": "symlink", "mode": 0o777, "uid": 0, "gid": 0, "target": LONG, "xattrs": {}},
}


@unittest.skipUnless(shutil.which("mke2fs") and shutil.which("debugfs"), "e2fsprogs missing")
class Ext4ManifestTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        src = os.path.join(self.d, "src")
        for rel, body in {"bin/tool": b"#!/bin/sh\necho no\n", "etc/a b.prop": b""}.items():
            os.makedirs(os.path.join(src, os.path.dirname(rel)), exist_ok=True)
            with open(os.path.join(src, rel), "wb") as f:
                f.write(body)
        os.symlink("/proc/self/root/etc/passwd", os.path.join(src, "fast"))
        os.symlink(LONG, os.path.join(src, "slow"))
        self.img = os.path.join(self.d, "system.img")
        subprocess.run(["mke2fs", "-q", "-t", "ext4", "-E", "root_owner=0:0", "-d", src, self.img, "16M"],
                       check=True, capture_output=True)
        cap = os.path.join(self.d, "cap")
        with open(cap, "wb") as f:
            f.write(CAP)
        cmds = ['ln /bin/tool /bin/tool-link', 'sif /bin/tool links_count 2']
        for path, e in EXPECTED.items():
            if e.get("hardlink_of"):
                continue
            cmds += [f'sif "{path}" uid {e["uid"]}', f'sif "{path}" gid {e["gid"]}']
            if e["kind"] != "symlink":
                kind = {"dir": 0o040000, "file": 0o100000}[e["kind"]]
                cmds.append(f'sif "{path}" mode 0{kind | e["mode"]:o}')
            for name, value in e["xattrs"].items():
                if name == "security.capability":
                    cmds.append(f'ea_set -f {cap} "{path}" {name}')
                else:
                    cmds.append(f'ea_set "{path}" {name} "{bytes.fromhex(value)[:-1].decode()}\\000"')
        r = subprocess.run(["debugfs", "-w", "-f", "-", self.img], input="\n".join(cmds) + "\n",
                           capture_output=True, text=True, check=True)
        self.assertNotIn("debugfs: ", r.stderr.replace("debugfs 1.", ""), r.stderr)
        for path, e in EXPECTED.items():  # fixture self-check: labels end in exactly one NUL
            if "security.selinux" in e["xattrs"]:
                self.assertTrue(bytes.fromhex(e["xattrs"]["security.selinux"]).endswith(b"s0\0"))

    def test_reads_owner_mode_xattrs_symlinks_and_hardlinks_without_following_links(self):
        got = erofs95.ext4_manifest(self.img, os.path.join(self.d, "stage"))
        got.pop("/lost+found")
        self.assertEqual(got, EXPECTED)
        self.assertFalse(os.path.lexists(os.path.join(self.d, "stage", "fast")))


@unittest.skipUnless(shutil.which("mkfs.erofs") and shutil.which("fsck.erofs"), "erofs-utils missing")
class ErofsRoundTripTest(Ext4ManifestTest):
    def test_erofs_image_keeps_every_owner_mode_xattr_symlink_hardlink_and_content(self):
        out = os.path.join(self.d, "system.erofs")
        erofs95.build(self.img, out, os.path.join(self.d, "work"))
        got = erofs95.erofs_manifest(out, os.path.join(self.d, "readback"))
        got.pop("/lost+found")
        self.assertEqual(got, EXPECTED)

    def test_compare_reports_lost_labels_and_capabilities_instead_of_success(self):
        work = os.path.join(self.d, "work")
        expected = erofs95.build(self.img, os.path.join(self.d, "ok.erofs"), work)
        self.assertEqual(erofs95.compare(expected, erofs95.erofs_manifest(os.path.join(self.d, "ok.erofs"),
                                                                           os.path.join(self.d, "rb1"))), [])
        lossy = os.path.join(self.d, "lossy.erofs")
        stripped = os.path.join(self.d, "noxattr.tar")   # same tree, PAX xattr records dropped
        with tarfile.open(os.path.join(work, "system.tar")) as src, \
                tarfile.open(stripped, "w", format=tarfile.PAX_FORMAT) as dst:
            for ti in src:
                ti.pax_headers = {}
                dst.addfile(ti, src.extractfile(ti) if ti.isreg() else None)
        subprocess.run(["mkfs.erofs", "--tar=f", lossy, stripped], check=True, capture_output=True)
        diffs = erofs95.compare(expected, erofs95.erofs_manifest(lossy, os.path.join(self.d, "rb2")))
        self.assertIn("/bin/tool: xattrs differ", diffs)
        self.assertIn("/: xattrs differ", diffs)

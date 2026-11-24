"""backup_slot_a_boot.sh: only reads boot_a/vendor_boot_a/dtbo_a + 2 MiB of super; never writes a device and
never touches GPT, userdata (sda34), linux (sda35) or slot B. Checked statically: tests open no device."""
import os, re, subprocess, tempfile, unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "backup_slot_a_boot.sh")


class BackupScriptTest(unittest.TestCase):
    def setUp(self):
        with open(SCRIPT) as f:
            self.text = f.read()
        self.code = "\n".join(l for l in self.text.splitlines() if not l.lstrip().startswith("#"))

    def test_shell_syntax(self):
        subprocess.run(["sh", "-n", SCRIPT], check=True)

    def test_reads_exactly_the_slot_a_boot_chain_and_super_metadata(self):
        block = re.search(r'LIST="(.*?)"', self.code, re.S)[1]
        rows = [l.split() for l in block.strip().splitlines()]
        self.assertEqual([(r[0], r[1], int(r[3])) for r in rows],
                         [("boot_a", "/dev/sde12", 201326592), ("vendor_boot_a", "/dev/sde25", 100663296),
                          ("dtbo_a", "/dev/sde18", 33554432), ("super", "/dev/sda29", 2 << 20)])

    def test_never_writes_devices_or_names_guarded_partitions(self):
        self.assertEqual(re.findall(r"\bdd\b[^\n]*", self.code),
                         ['dd if="$d" of="$OUT/$name" bs=1M count=$((n >> 20)) iflag=fullblock status=none'])
        for word in ("of=/dev", "sda34", "sda35", "userdata", "linux", "_b ", "system_a", "sfdisk", "sgdisk",
                     "parted", "lpmake", "fastboot", "conv=", "oflag", "tee /dev", "> /dev/sd"):
            with self.subTest(word):
                self.assertNotIn(word, self.code)

    def test_refuses_existing_or_device_outdir_before_touching_devices(self):
        with tempfile.TemporaryDirectory() as d:
            for out in (d, "/dev/sda34", "/proc/x"):
                with self.subTest(out):
                    r = subprocess.run(["sh", SCRIPT, out], capture_output=True, text=True)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("refusing", r.stdout)


if __name__ == "__main__":
    unittest.main()

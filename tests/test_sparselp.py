"""Streaming sparse+LP extraction, checked against the distro's trusted lpmake/lpunpack/img2simg."""
import hashlib, os, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import sparselp

TOOLS = all(shutil.which(t) for t in ("lpmake", "lpunpack", "img2simg", "lpdump"))


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@unittest.skipUnless(TOOLS, "android-tools (lpmake/lpunpack/img2simg/lpdump) not installed")
class StreamingExtractTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        # Partition payloads exercising RAW, FILL (repeated word) and zero regions.
        self.parts = {"system_a": os.urandom(40960) + b"\xab\xcd\xef\x01" * 4096 + bytes(8192),
                      "vendor_a": bytes(4096) + os.urandom(12288)}
        args = ["lpmake", "-d", str(4 << 20), "-m", "65536", "-s", "3", "-g", "grp_a:3145728", "--virtual-ab",
                "-o", self.p("super_raw.img"), "-F"]
        for n, data in self.parts.items():
            with open(self.p(n + ".in"), "wb") as f:
                f.write(data)
            args += ["-p", f"{n}:none:{len(data)}:grp_a", "-i", f"{n}={self.p(n + '.in')}"]
        subprocess.run(args, check=True, capture_output=True)
        subprocess.run(["img2simg", "-s", self.p("super_raw.img"), self.p("super.img")], check=True, capture_output=True)

    def p(self, *names):
        return os.path.join(self.d, *names)

    def test_extracts_partitions_identical_to_lpunpack(self):
        os.mkdir(self.p("oracle"))
        subprocess.run(["lpunpack", self.p("super_raw.img"), self.p("oracle")], check=True, capture_output=True)
        os.mkdir(self.p("out"))
        with open(self.p("super.img"), "rb") as f:
            layout = sparselp.lp_layout(sparselp.raw_prefix(f, 1 << 20))
        with open(self.p("super.img"), "rb") as f:
            got = sparselp.extract(f, self.p("out"), layout, ["system_a", "vendor_a"])
        for n in ("system_a", "vendor_a"):
            self.assertEqual(sha(self.p("out", n + ".img")), sha(self.p("oracle", n + ".img")), n)
        self.assertEqual(sorted(got["partitions"]), ["system_a", "vendor_a"])

    def test_hashes_partitions_in_one_pass_without_writing_them(self):
        os.mkdir(self.p("oracle"))
        subprocess.run(["lpunpack", self.p("super_raw.img"), self.p("oracle")], check=True, capture_output=True)
        with open(self.p("super.img"), "rb") as f:
            layout = sparselp.lp_layout(sparselp.raw_prefix(f, 1 << 20))
        with open(self.p("super.img"), "rb") as f:
            got = sparselp.hash_partitions(f, layout, ["system_a", "vendor_a"])
        self.assertEqual(got, {n: sha(self.p("oracle", n + ".img")) for n in ("system_a", "vendor_a")})

    def test_fixture_covers_every_chunk_kind(self):
        with open(self.p("super.img"), "rb") as f:
            kinds = {k for _o, _l, k, _p in sparselp.pieces(f)}
        self.assertEqual(kinds, {sparselp.RAW, sparselp.FILL, sparselp.DONT_CARE})


class MalformedSparseTest(unittest.TestCase):
    import struct as _s
    HDR = _s.pack("<IHHHHIIII", 0xED26FF3A, 1, 0, 28, 12, 4096, 2, 1, 0)

    def decode(self, data):
        import io
        return list(sparselp.pieces(io.BytesIO(data)))

    def test_rejects_truncated_raw_chunk(self):
        chunk = self._s.pack("<HHII", 0xCAC1, 0, 1, 12 + 4096) + b"x" * 100
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.decode(self.HDR + chunk)

    def test_rejects_chunk_beyond_declared_size(self):
        chunk = self._s.pack("<HHII", 0xCAC3, 0, 3, 12)  # 3 blocks, header declares 2
        with self.assertRaisesRegex(ValueError, "past the declared"):
            self.decode(self.HDR + chunk)

    def test_rejects_raw_chunk_whose_size_lies(self):
        chunk = self._s.pack("<HHII", 0xCAC1, 0, 1, 12 + 999_999_999)
        with self.assertRaisesRegex(ValueError, "bad chunk"):
            self.decode(self.HDR + chunk)

    def test_rejects_non_sparse_input(self):
        with self.assertRaisesRegex(ValueError, "not a version-1"):
            self.decode(b"\0" * 28)

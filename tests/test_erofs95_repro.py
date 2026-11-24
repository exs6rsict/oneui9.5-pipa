"""erofs95_repro.case(): one JSON-able verdict per case, nothing left in WORKDIR, even when mkfs.erofs fails."""
import os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import erofs95_repro


@unittest.skipUnless(shutil.which("mkfs.erofs") and shutil.which("fsck.erofs"), "erofs-utils missing")
class ReproCaseTest(unittest.TestCase):
    def test_small_file_survives_and_stale_extract_dir_is_ignored(self):
        with tempfile.TemporaryDirectory() as work:
            os.makedirs(os.path.join(work, "x-0"))
            open(os.path.join(work, "x-0", "small"), "wb").close()  # leftover of an interrupted run
            out = erofs95_repro.case(work, 0)
            self.assertEqual((out["mkfs_rc"], out["timed_out"], out["fsck_extract_rc"]), (0, False, 0))
            self.assertEqual((out["data_lost"], out["small_extracted"], out["small_content_ok"]), (False, True, True))
            self.assertEqual(os.listdir(work), [])


class ReproFailureTest(unittest.TestCase):
    def test_mkfs_exiting_early_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as fake:
            mkfs = os.path.join(fake, "mkfs.erofs")
            with open(mkfs, "w") as f:
                f.write("#!/bin/sh\necho refused >&2\nexit 3\n")
            os.chmod(mkfs, 0o755)
            path = os.environ["PATH"]
            os.environ["PATH"] = fake + os.pathsep + path
            try:
                out = erofs95_repro.case(work, 100)
            finally:
                os.environ["PATH"] = path
            self.assertEqual((out["mkfs_rc"], out["streamed_prefix_mib"]), (3, 64))
            self.assertIn("refused", out["mkfs_err"])
            self.assertIn("stream_error", out)
            self.assertNotIn("small_content_ok", out)  # mkfs failed: no image to judge
            self.assertEqual(os.listdir(work), [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Minimal reproducer: erofs-utils 1.7.1 `--tar=f` loses the data of files whose compression falls back
to uncompressed (-ENOSPC) when their diskbuf offset is in [2,4) or [6,8) GiB.

Suspected cause (v1.7.1 lib/inode.c:462,480-482): `int ret = lseek(fd, fpos, SEEK_SET); if (ret < 0)
return -errno;` truncates a u64 offset to int. Upstream changed it in 9d7b9c0 (first in v1.8).

Each case streams a tar into mkfs.erofs (no tar on disk): PREFIX MiB of zero-filled 64 MiB files (cheap
to compress), then one 1471-byte text file that cannot save a block, so it takes the fallback path.
Run on the VPS only: python3 -I erofs95_repro.py WORKDIR [PREFIX_MIB ...]; mkfs.erofs on PATH decides
which version is tested. Prints one JSON line per case."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from erofs95 import ErofsImage, compressed_without_data  # noqa: E402

CHUNK = 64 << 20
SMALL = (b"root:x:0:0::/:/bin/sh\n" * 70)[:1471]


def stream_tar(dst, prefix_mib):
    zeros = bytes(CHUNK)
    with tarfile.open(fileobj=dst, mode="w|", format=tarfile.PAX_FORMAT) as t:
        for k in range(prefix_mib * (1 << 20) // CHUNK):
            ti = tarfile.TarInfo(f"zero{k:04d}")
            ti.size = CHUNK
            t.addfile(ti, io.BytesIO(zeros))
        ti = tarfile.TarInfo("small")
        ti.size = len(SMALL)
        t.addfile(ti, io.BytesIO(SMALL))


def case(work, prefix_mib, timeout=900):
    img = os.path.join(work, f"repro-{prefix_mib}.img")
    dest = os.path.join(work, f"x-{prefix_mib}")
    shutil.rmtree(dest, ignore_errors=True)  # a stale extract from an interrupted run makes fsck fail (EEXIST)
    # prefix is streamed in whole 64 MiB files; report what was really tested, not only what was asked
    out = {"prefix_mib": prefix_mib, "streamed_prefix_mib": prefix_mib * (1 << 20) // CHUNK * (CHUNK >> 20)}
    env = dict(os.environ, TMPDIR=work)  # mkfs keeps its diskbuf tmpfile here
    try:
        with tempfile.TemporaryFile(dir=work) as errf:  # a file, not a pipe: mkfs can never block on stderr
            p = subprocess.Popen(["mkfs.erofs", "-zlz4hc", "--tar=f", "--quiet", img], stdin=subprocess.PIPE,
                                 stderr=errf, env=env)
            expired = threading.Event()
            killer = threading.Timer(timeout, lambda: (expired.set(), p.kill()))  # bounds streaming and wait
            killer.start()
            try:
                stream_tar(p.stdin, prefix_mib)
            except BrokenPipeError:
                out["stream_error"] = "mkfs.erofs stopped reading before the whole tar was sent"
            finally:
                with contextlib.suppress(BrokenPipeError):
                    p.stdin.close()
                rc = p.wait()
                killer.cancel()
            errf.seek(0)
            out.update(mkfs_rc=rc, mkfs_err=errf.read().decode(errors="replace")[-300:], timed_out=expired.is_set())
        if rc == 0 and not expired.is_set():
            fs = ErofsImage(img)
            try:
                nid = dict(fs.children(fs.inode(fs.root))).get("small")
                ino = fs.inode(nid) if nid is not None else None
            finally:
                fs.close()
            if ino is None:
                out["small_inode"] = "missing"
            else:
                out.update(layout=ino["layout"], compressed_blocks_or_blkaddr=ino["iu"],
                           data_lost="/small" in compressed_without_data(img))
            r = subprocess.run(["fsck.erofs", f"--extract={dest}", img], capture_output=True, text=True)
            out["fsck_extract_rc"] = r.returncode
            small = os.path.join(dest, "small")
            # fsck 1.7.1 can exit 0 yet skip a data-less file: a missing file is a failure, not "not checked"
            out["small_extracted"] = os.path.isfile(small) and not os.path.islink(small)
            ok = False
            if out["small_extracted"]:
                with open(small, "rb") as f:
                    ok = f.read() == SMALL
            out["small_content_ok"] = r.returncode == 0 and ok
    finally:
        shutil.rmtree(dest, ignore_errors=True)
        if os.path.exists(img):
            os.remove(img)
    return out


def main(argv):
    work, *sizes = argv
    os.makedirs(work, exist_ok=True)
    for s in [int(x) for x in sizes] or [0, 2150, 4250]:
        print(json.dumps(case(work, s)), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])

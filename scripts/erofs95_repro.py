#!/usr/bin/env python3
"""Minimal reproducer: erofs-utils 1.7.1 `--tar=f` loses the data of files whose compression falls back
to uncompressed (-ENOSPC) when their diskbuf offset is in [2,4) or [6,8) GiB.

Suspected cause (v1.7.1 lib/inode.c:462,480-482): `int ret = lseek(fd, fpos, SEEK_SET); if (ret < 0)
return -errno;` truncates a u64 offset to int. Upstream changed it in 9d7b9c0 (first in v1.8).

Each case streams a tar into mkfs.erofs (no tar on disk): PREFIX MiB of zero-filled 64 MiB files (cheap
to compress), then one 1471-byte text file that cannot save a block, so it takes the fallback path.
Run on the VPS only: python3 -I erofs95_repro.py WORKDIR [PREFIX_MIB ...]; mkfs.erofs on PATH decides
which version is tested. Prints one JSON line per case."""
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from erofs95 import ErofsImage  # noqa: E402

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
    env = dict(os.environ, TMPDIR=work)  # mkfs keeps its diskbuf tmpfile here
    p = subprocess.Popen(["mkfs.erofs", "-zlz4hc", "--tar=f", "--quiet", img], stdin=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env)
    try:
        stream_tar(p.stdin, prefix_mib)
        p.stdin.close()
        rc = p.wait(timeout=timeout)
        err = p.stderr.read().decode(errors="replace")[-300:]
    finally:
        p.kill()
        p.stderr.close()
    out = {"prefix_mib": prefix_mib, "mkfs_rc": rc, "mkfs_err": err}
    if rc == 0:
        fs = ErofsImage(img)
        try:
            nid = dict(fs.children(fs.inode(fs.root)))["small"]
            ino = fs.inode(nid)
            out.update(layout=ino["layout"], compressed_blocks_or_blkaddr=ino["iu"],
                       data_lost=ino["layout"] in (1, 3) and ino["iu"] == 0)
        finally:
            fs.close()
        dest = os.path.join(work, f"x-{prefix_mib}")
        r = subprocess.run(["fsck.erofs", f"--extract={dest}", img], capture_output=True, text=True)
        out["fsck_extract_rc"] = r.returncode
        small = os.path.join(dest, "small")
        if r.returncode == 0 and os.path.isfile(small) and not stat.S_ISLNK(os.lstat(small).st_mode):
            with open(small, "rb") as f:
                out["small_content_ok"] = hashlib.sha256(f.read()).digest() == hashlib.sha256(SMALL).digest()
        subprocess.run(["rm", "-rf", dest], check=False)
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

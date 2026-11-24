#!/usr/bin/env python3
"""Repack an ext4 system image into EROFS without losing metadata, then prove it with an independent reader.

ext4 side: trusted debugfs only (read-only, nothing mounted, symlinks recorded never followed).
Owner/mode/xattrs (security.selinux, security.capability) come straight from each inode, so no
file_contexts/fs_config is assumed. They travel to mkfs.erofs as a PAX tar (SCHILY.xattr.*).
EROFS side: an on-disk-format reader below (metadata) plus fsck.erofs extraction (content hashes)."""
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsmeta import debugfs  # noqa: E402

KINDS = {0o040000: "dir", 0o100000: "file", 0o120000: "symlink"}
SKIP_XATTRS = {"system.data"}      # ext4 inline-data storage, not a file attribute
QUOTABLE = re.compile(r'^[^"\\\n\0]*$')
MTIME = 1230768000                 # AOSP's fixed build timestamp (2009-01-01); ext4 mtimes are not kept


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def q(path):
    if not QUOTABLE.match(path):
        raise ValueError(f"path not safely quotable for debugfs: {path!r}")
    return f'"{path}"'


def _walk(img):
    """{path: (ino, mode, uid, gid)} with "/" for the root; one debugfs session per depth."""
    entries, level = {}, ["/"]
    while level:
        nxt = []
        for parent, lines in zip(level, debugfs(img, [f"ls -p {q(d)}" for d in level])):
            for line in lines:
                parts = line.split("/")
                if len(parts) < 7:
                    continue
                name = "/".join(parts[5:-2])
                ino, mode, uid, gid = int(parts[1]), int(parts[2], 8), int(parts[3]), int(parts[4])
                if name == "." and parent == "/":
                    entries["/"] = (ino, mode, uid, gid)
                if name in (".", "..") or ino == 0:  # ino 0 = unused dirent slot (e.g. lost+found)
                    continue
                path = parent.rstrip("/") + "/" + name
                if mode & 0o170000 not in KINDS:
                    # shortcut: device nodes/fifos/sockets are refused, add tar types if an image ever has them
                    raise ValueError(f"unsupported inode type {mode:o}: {path!r}")
                entries[path] = (ino, mode, uid, gid)
                if KINDS[mode & 0o170000] == "dir":
                    nxt.append(path)
        level = nxt
    return entries


def _xattrs(img, entries, stage):
    """{ino: {name: bytes}} read raw with ea_get -f; lengths are cross-checked against ea_list."""
    first = {}
    for path, (ino, *_rest) in sorted(entries.items()):
        first.setdefault(ino, path)
    inos = sorted(first)
    listed = {}
    for ino, lines in zip(inos, debugfs(img, [f"ea_list {q(first[i])}" for i in inos])):
        listed[ino] = [(m.group(1), int(m.group(2))) for m in (re.match(r"^  (\S+) \((\d+)\)", l) for l in lines)
                       if m and m.group(1) not in SKIP_XATTRS]
    os.makedirs(os.path.join(stage, "xattr"), exist_ok=True)
    jobs = [(ino, n, size, os.path.join(stage, "xattr", f"{ino}.{k}"))
            for ino in inos for k, (n, size) in enumerate(listed[ino])]
    debugfs(img, [f"ea_get -f {out} {q(first[ino])} {name}" for ino, name, _s, out in jobs])
    result = {ino: {} for ino in inos}
    for ino, name, size, out in jobs:
        with open(out, "rb") as f:
            value = f.read()
        if len(value) != size:
            raise RuntimeError(f"xattr {name} of {first[ino]!r}: read {len(value)} bytes, ea_list says {size}")
        result[ino][name] = value
    return result


def _contents(img, entries, stage):
    """Dump each regular-file inode once to stage/data/<ino>; read every symlink target."""
    data = os.path.join(stage, "data")
    os.makedirs(data, exist_ok=True)
    files, links = {}, {}
    for path, (ino, mode, *_r) in sorted(entries.items()):
        kind = KINDS[mode & 0o170000]
        if kind == "file":
            files.setdefault(ino, path)
        elif kind == "symlink":
            links[path] = ino
    debugfs(img, [f"dump {q(p)} {os.path.join(data, str(i))}" for i, p in files.items()])
    targets = {}
    slow = []
    for path, lines in zip(links, debugfs(img, [f"stat {q(p)}" for p in links])):
        m = re.search(r'^Fast link dest: "(.*)"$', "\n".join(lines), re.M)
        if m:
            targets[path] = m.group(1)
        else:
            slow.append(path)
    debugfs(img, [f"dump {q(p)} {os.path.join(data, 'link.' + str(links[p]))}" for p in slow])
    for path in slow:
        with open(os.path.join(data, f"link.{links[path]}"), "rb") as f:
            targets[path] = f.read().decode("utf-8", "surrogateescape")
    return files, targets


def scan(img, stage):
    """(manifest, {path: staged data file}) for an ext4 image; staged data is what build() packs."""
    entries = _walk(img)
    xattrs = _xattrs(img, entries, stage)
    files, targets = _contents(img, entries, stage)
    manifest, staged, seen = {}, {}, {}
    for path, (ino, mode, uid, gid) in sorted(entries.items()):
        kind = KINDS[mode & 0o170000]
        e = {"kind": kind, "mode": mode & 0o7777, "uid": uid, "gid": gid,
             "xattrs": {n: v.hex() for n, v in sorted(xattrs[ino].items())}}
        if kind == "file":
            staged[path] = os.path.join(stage, "data", str(ino))
            e["sha256"] = sha256(staged[path])
            if ino in seen:
                e["hardlink_of"] = seen[ino]
            seen.setdefault(ino, path)
        elif kind == "symlink":
            e["target"] = targets[path]
        manifest[path] = e
    return manifest, staged


def ext4_manifest(img, stage):
    return scan(img, stage)[0]


def write_tar(manifest, staged, tar_path):
    """PAX tar carrying numeric owner, mode and raw xattrs; hard links stay links; nothing is dereferenced."""
    with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT, encoding="utf-8") as tar:
        for path, e in manifest.items():
            ti = tarfile.TarInfo("." if path == "/" else path.lstrip("/"))
            ti.mode, ti.uid, ti.gid, ti.mtime, ti.uname, ti.gname = e["mode"], e["uid"], e["gid"], MTIME, "", ""
            ti.pax_headers = {"SCHILY.xattr." + n: bytes.fromhex(v).decode("utf-8", "surrogateescape")
                              for n, v in e["xattrs"].items()}
            if e["kind"] == "dir":
                ti.type = tarfile.DIRTYPE
                tar.addfile(ti)
            elif e["kind"] == "symlink":
                ti.type, ti.linkname = tarfile.SYMTYPE, e["target"]
                tar.addfile(ti)
            elif "hardlink_of" in e:
                ti.type, ti.linkname = tarfile.LNKTYPE, e["hardlink_of"].lstrip("/")
                tar.addfile(ti)
            else:
                ti.size = os.path.getsize(staged[path])
                with open(staged[path], "rb") as f:
                    tar.addfile(ti, f)


def build(img, out, work, compress="lz4hc"):
    """ext4 image -> EROFS image at `out`; returns the ext4 manifest the image must match."""
    os.makedirs(work, exist_ok=True)
    manifest, staged = scan(img, os.path.join(work, "stage"))
    tar_path = os.path.join(work, "system.tar")
    write_tar(manifest, staged, tar_path)
    r = subprocess.run(["mkfs.erofs", f"-z{compress}", "--tar=f", f"-T{MTIME}", out, tar_path],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"mkfs.erofs exit {r.returncode}: {r.stderr.strip()[-800:]}")
    return manifest


# --- independent EROFS reader (on-disk format, erofs_fs.h); only metadata, dirs and symlinks are decoded ---
XATTR_PREFIX = {1: "user.", 2: "system.posix_acl_access", 3: "system.posix_acl_default", 4: "trusted.",
                6: "security."}


class ErofsImage:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDONLY)
        sb = os.pread(self.fd, 128, 1024)
        (magic, _csum, _compat, blkszbits, _ext, self.root, _inos, _bt, _btn, _blocks, meta, xattr) = \
            struct.unpack_from("<IIIBBHQQIIII", sb)
        if magic != 0xE0F5E1E2:
            raise ValueError(f"{path}: not EROFS (magic {magic:#x})")
        self.bs = 1 << blkszbits
        self.dirbs = self.bs << sb[90]
        self.meta, self.xattr = meta * self.bs, xattr * self.bs

    def close(self):
        os.close(self.fd)

    def inode(self, nid):
        pos = self.meta + nid * 32
        raw = os.pread(self.fd, 64, pos)
        fmt = struct.unpack_from("<H", raw)[0]
        if fmt & 1:
            _f, icount, mode, _r, size, iu, _ino, uid, gid = struct.unpack_from("<HHHHQIIII", raw)
            isize = 64
        else:
            _f, icount, mode, _n, size, _r, iu, _ino, uid, gid = struct.unpack_from("<HHHHIIIIHH", raw)
            isize = 32
        xsize = 0 if icount == 0 else 12 + (icount - 1) * 4
        return {"pos": pos, "layout": (fmt >> 1) & 7, "mode": mode, "size": size, "iu": iu, "uid": uid,
                "gid": gid, "isize": isize, "xsize": xsize}

    def _entry(self, buf, off):
        name_len, index, vsize = struct.unpack_from("<BBH", buf, off)
        if index not in XATTR_PREFIX:
            raise NotImplementedError(f"xattr name index {index:#x} (long prefixes) not decoded")
        name = XATTR_PREFIX[index] + buf[off + 4:off + 4 + name_len].decode()
        value = bytes(buf[off + 4 + name_len:off + 4 + name_len + vsize])
        return name, value, (4 + name_len + vsize + 3) & ~3

    def xattrs(self, ino):
        if not ino["xsize"]:
            return {}
        buf = os.pread(self.fd, ino["xsize"], ino["pos"] + ino["isize"])
        shared = struct.unpack_from("<B", buf, 4)[0]
        out = {}
        for k in range(shared):
            sid = struct.unpack_from("<I", buf, 12 + 4 * k)[0]
            name, value, _ = self._entry(os.pread(self.fd, 4 + 255 + 65536, self.xattr + sid * 4), 0)
            out[name] = value
        off = 12 + 4 * shared
        while off < ino["xsize"]:
            name, value, step = self._entry(buf, off)
            out[name] = value
            off += step
        return out

    def data(self, ino):
        """Uncompressed (flat) data only: directories and symlinks are never compressed by mkfs.erofs."""
        size, bs = ino["size"], self.bs
        if ino["layout"] == 0:
            return os.pread(self.fd, size, ino["iu"] * bs)
        if ino["layout"] == 2:
            full = (-(-size // bs) - 1) * bs
            head = os.pread(self.fd, full, ino["iu"] * bs) if full else b""
            return head + os.pread(self.fd, size - full, ino["pos"] + ino["isize"] + ino["xsize"])
        raise NotImplementedError(f"layout {ino['layout']} for a dir/symlink")

    def children(self, ino):
        data = self.data(ino)
        for start in range(0, len(data), self.dirbs):
            blk = data[start:start + self.dirbs]
            n = struct.unpack_from("<H", blk, 8)[0] // 12
            for i in range(n):
                nid, nameoff = struct.unpack_from("<QH", blk, i * 12)
                end = struct.unpack_from("<H", blk, (i + 1) * 12 + 8)[0] if i + 1 < n else len(blk)
                name = blk[nameoff:end].rstrip(b"\0").decode("utf-8", "surrogateescape")
                if name not in (".", ".."):
                    yield name, nid


def erofs_manifest(img, scratch):
    """Manifest of an EROFS image in ext4_manifest's shape: metadata from ErofsImage, file hashes from
    fsck.erofs --extract (which also checks every file decodes)."""
    fs, manifest, seen = ErofsImage(img), {}, {}
    try:
        todo = [("/", fs.root)]
        while todo:
            path, nid = todo.pop()
            ino = fs.inode(nid)
            kind = KINDS.get(stat.S_IFMT(ino["mode"]))
            if kind is None:
                raise ValueError(f"unexpected inode type {ino['mode']:o} at {path!r}")
            e = {"kind": kind, "mode": ino["mode"] & 0o7777, "uid": ino["uid"], "gid": ino["gid"],
                 "xattrs": {n: v.hex() for n, v in sorted(fs.xattrs(ino).items())}}
            if kind == "dir":
                todo += [(path.rstrip("/") + "/" + n, c) for n, c in fs.children(ino)]
            elif kind == "symlink":
                e["target"] = fs.data(ino).decode("utf-8", "surrogateescape")
            else:
                seen.setdefault(nid, []).append(path)
            manifest[path] = e
    finally:
        fs.close()
    for paths in seen.values():
        for p in sorted(paths)[1:]:
            manifest[p]["hardlink_of"] = sorted(paths)[0]
    dest = os.path.join(scratch, "extract")
    os.makedirs(scratch, exist_ok=True)
    try:
        r = subprocess.run(["fsck.erofs", f"--extract={dest}", "--no-preserve", img], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"fsck.erofs exit {r.returncode}: {r.stderr.strip()[-800:]}")
        for path, e in manifest.items():
            if e["kind"] == "file":
                e["sha256"] = sha256(dest + path)
    finally:
        for root, dirs, _files in os.walk(dest):  # image dirs such as 0500 would block removal
            for d in dirs:
                p = os.path.join(root, d)
                if not os.path.islink(p):
                    os.chmod(p, 0o700)
        shutil.rmtree(dest, ignore_errors=True)
    return dict(sorted(manifest.items()))


def compare(expected, got):
    """Every path/field difference as 'path: field differ'; empty list means metadata+content identical."""
    diffs = [f"{p}: missing in erofs" for p in sorted(expected.keys() - got.keys())]
    diffs += [f"{p}: extra in erofs" for p in sorted(got.keys() - expected.keys())]
    for p in sorted(expected.keys() & got.keys()):
        for field in sorted(expected[p].keys() | got[p].keys()):
            if expected[p].get(field) != got[p].get(field):
                diffs.append(f"{p}: {field} differ")
    return diffs


def derived_configs(manifest):
    """fs_config / file_contexts views of the manifest, for audit only (mkfs gets metadata via the tar)."""
    fs_config, contexts = [], []
    for p, e in manifest.items():
        cap = e["xattrs"].get("security.capability", "")
        fs_config.append(f"{p} {e['uid']} {e['gid']} {e['mode']:04o}" + (f" capability={cap}" if cap else ""))
        label = bytes.fromhex(e["xattrs"].get("security.selinux", "")).rstrip(b"\0").decode("utf-8", "replace")
        contexts.append(f"{re.escape(p)} {label or '<none>'}")
    return "\n".join(fs_config) + "\n", "\n".join(contexts) + "\n"


def main(argv=None):
    """erofs95.py IMG OUT_EROFS WORK REPORT_DIR [IMAGE_PATH_TO_READ_BACK ...]; exit 1 on any difference."""
    img, out, work, report, *readback = argv if argv is not None else sys.argv[1:]
    os.makedirs(report, exist_ok=True)
    expected = build(img, out, work)
    got = erofs_manifest(out, os.path.join(work, "readback"))
    diffs = compare(expected, got)
    fs_config, contexts = derived_configs(expected)
    for name, body in (("fs_config.derived.txt", fs_config), ("file_contexts.derived.txt", contexts)):
        with open(os.path.join(report, name), "w") as f:
            f.write(body)
    for name, m in (("manifest.ext4.json", expected), ("manifest.erofs.json", got)):
        with open(os.path.join(report, name), "w") as f:
            json.dump(m, f, indent=0, sort_keys=True)
    kinds = {}
    for e in expected.values():
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    result = {
        "input": {"path": img, "size": os.path.getsize(img), "sha256": sha256(img)},
        "output": {"path": out, "size": os.path.getsize(out), "sha256": sha256(out)},
        "entries": kinds,
        "with_selinux_label": sum("security.selinux" in e["xattrs"] for e in expected.values()),
        "with_capability": sum("security.capability" in e["xattrs"] for e in expected.values()),
        "hardlinks": sum("hardlink_of" in e for e in expected.values()),
        "differences": diffs[:200], "difference_count": len(diffs),
        "readback": {p: {"ext4": expected.get(p, {}).get("sha256"), "erofs": got.get(p, {}).get("sha256")}
                     for p in readback},
        "verdict": "metadata+content identical" if not diffs else "MISMATCH",
        "approval": "NOT APPROVED FOR FLASH",
    }
    with open(os.path.join(report, "result.json"), "w") as f:
        json.dump(result, f, indent=1)
    print(json.dumps({k: result[k] for k in ("output", "difference_count", "verdict")}))
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())

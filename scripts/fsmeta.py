#!/usr/bin/env python3
"""List a filesystem image and copy out allowlisted metadata (props, init, VINTF, SELinux, fstab)
using trusted read-only userspace readers. Nothing is mounted; symlinks are recorded, never followed."""
import json
import os
import re
import shutil
import stat
import tempfile
import subprocess
import sys

WANTED = re.compile(r"(^|/)(build|default)\.prop$|(^|/)prop\.default$|(^|/)etc/(init|vintf|selinux)/"
                    r"|(^|/)etc/fstab[^/]*$|(^|/)etc/[^/]*\.rc$|(^|/)etc/linker\.config\.pb$")
MAX_FILE = 16 << 20
SAFE_NAME = re.compile(r'^[^/\0\n"]+$')


def debugfs(img, commands):
    """Run commands in one read-only debugfs session; returns stdout split per command."""
    script = "".join(c + "\n" for c in commands)
    out = subprocess.run(["debugfs", "-f", "-", img], input=script, capture_output=True, text=True,
                         errors="surrogateescape", check=True).stdout
    blocks, current = [], None
    for line in out.splitlines():
        if line.startswith("debugfs: "):
            current = []
            blocks.append(current)
        elif current is not None:
            current.append(line)
    return blocks


def walk_ext4(img):
    """{relpath: (kind, size)} for the whole tree, one debugfs session per directory depth."""
    tree, level = {}, [""]
    while level:
        blocks = debugfs(img, [f'ls -p "/{d}"' for d in level])
        nxt = []
        for parent, lines in zip(level, blocks):
            for line in lines:
                parts = line.split("/")
                if len(parts) < 7 or parts[5] in (".", ".."):
                    continue
                mode, name, size = int(parts[2], 8), "/".join(parts[5:-2]), parts[-2]
                if not SAFE_NAME.match(name):
                    tree[f"{parent}/<unsafe-name>"] = ("unsafe", 0)
                    continue
                rel = f"{parent}/{name}" if parent else name
                kind = {0o040000: "dir", 0o100000: "file", 0o120000: "symlink"}.get(mode & 0o170000, "special")
                tree[rel] = (kind, int(size) if size.isdigit() else 0)
                if kind == "dir":
                    nxt.append(rel)
        level = nxt
    return tree


def symlink_targets(img, paths):
    targets = {}
    for p, lines in zip(paths, debugfs(img, [f'stat "/{p}"' for p in paths])):
        m = re.search(r'Fast link dest: "(.*)"', "\n".join(lines))
        targets[p] = m.group(1) if m else None
    return targets


def walk_dir(root):
    """{relpath: (kind, size)} from an extracted tree, using lstat only (links are never followed)."""
    tree = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            full = os.path.join(dirpath, name)
            st = os.lstat(full)
            kind = ("dir" if stat.S_ISDIR(st.st_mode) else "file" if stat.S_ISREG(st.st_mode)
                    else "symlink" if stat.S_ISLNK(st.st_mode) else "special")
            tree[os.path.relpath(full, root)] = (kind, st.st_size if kind == "file" else 0)
    return tree


def collect_erofs(img, outdir, scratch):
    """fsck.erofs verifies every file decodes while extracting; the extraction is temporary."""
    tmp = tempfile.mkdtemp(prefix="erofs-", dir=scratch)
    try:
        dest = os.path.join(tmp, "root")
        subprocess.run(["fsck.erofs", f"--extract={dest}", img], check=True, capture_output=True)
        tree = walk_dir(dest)
        files = sorted(p for p, (k, size) in tree.items() if k == "file" and WANTED.search(p) and size <= MAX_FILE)
        for p in files:
            os.makedirs(os.path.join(outdir, os.path.dirname(p)), exist_ok=True)
            shutil.copyfile(os.path.join(dest, p), os.path.join(outdir, p), follow_symlinks=False)
        links = {p: os.readlink(os.path.join(dest, p)) for p, (k, _) in sorted(tree.items())
                 if k == "symlink" and WANTED.search(p)}
    finally:
        shutil.rmtree(tmp)
    return tree, files, links


def collect(img, fstype, outdir, scratch=None):
    if fstype == "erofs":
        tree, files, links = collect_erofs(img, outdir, scratch)
        return {"files": files, "symlinks": links,
                "tree": {p: {"kind": k, "size": s} for p, (k, s) in sorted(tree.items())}}
    if fstype != "ext4":
        raise NotImplementedError(f"{fstype}: no trusted read-only reader wired in")
    tree = walk_ext4(img)
    files = sorted(p for p, (k, size) in tree.items() if k == "file" and WANTED.search(p) and size <= MAX_FILE)
    for p in files:
        os.makedirs(os.path.join(outdir, os.path.dirname(p)), exist_ok=True)
    debugfs(img, [f'dump "/{p}" "{os.path.join(outdir, p)}"' for p in files])
    links = symlink_targets(img, sorted(p for p, (k, _) in tree.items() if k == "symlink" and WANTED.search(p)))
    return {"files": files, "symlinks": links,
            "tree": {p: {"kind": k, "size": s} for p, (k, s) in sorted(tree.items())}}


def main(argv=None):
    img, fstype, outdir, *scratch = argv if argv is not None else sys.argv[1:]
    os.makedirs(outdir, exist_ok=True)
    result = collect(img, fstype, outdir, *scratch)
    with open(os.path.join(outdir, "fsmeta.json"), "w") as f:
        json.dump(result, f, indent=1, sort_keys=True)
    print(json.dumps({"files": len(result["files"]), "entries": len(result["tree"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

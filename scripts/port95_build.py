#!/usr/bin/env python3
"""Reproducible offline recipe: donor One UI 9.5 system (ext4) + pipa integration overlay/props,
packed with the baseline's unmodified pipa vendor/odm into a sparse super image.

Only trusted host tools touch images (e2fsprogs, android-tools); nothing is mounted or executed
from the ROM. Inputs are copied, never modified. Every output is read back before it is reported."""
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sparselp  # noqa: E402

SYSTEM_FILE = "u:object_r:system_file:s0"  # /system(/.*)? catch-all in the donor plat_file_contexts
SHELL_GID = 2000                           # AID_SHELL, as the baseline ships /system/bin entries


def run(*cmd, ok=(0,), **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode not in ok:
        raise RuntimeError(f"{cmd[0]} exit {r.returncode}: {r.stderr.strip()[-500:]}")
    return r.stdout


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def overlay_files(overlay):
    for root, _dirs, files in os.walk(overlay):
        for name in sorted(files):
            full = os.path.join(root, name)
            if os.path.islink(full) or not os.path.isfile(full):
                raise ValueError(f"overlay may only hold regular files: {full}")
            yield full, "/" + os.path.relpath(full, overlay)


def debugfs_write(img, commands):
    out = run("debugfs", "-w", "-f", "-", img, input="".join(c + "\n" for c in commands))
    return out


def append_texts(props, appends):
    """[(dest, text)] to append; props become a block at the end of /system/build.prop."""
    out = []
    if props:
        out.append(("/system/build.prop", "\n# port95: pipa integration carried over from the One UI 8 baseline\n"
                    + "".join(f"{k}={v}\n" for k, v in props.items())))
    for dest, src in (appends or {}).items():
        with open(src) as f:
            out.append((dest, f.read()))
    return out


def append_cmds(img, dest, text, local):
    """Rewrite dest as original+text, keeping its mode, owner and SELinux label."""
    run("debugfs", "-R", f'dump -p "{dest}" "{local}"', img)
    label = local + ".label"
    run("debugfs", "-R", f'ea_get -f "{label}" "{dest}" security.selinux', img)
    stat = run("debugfs", "-R", f'stat "{dest}"', img)
    uid, gid = re.search(r"User:\s+(\d+)\s+Group:\s+(\d+)", stat).groups()
    if not os.path.exists(local) or not os.path.exists(label) or os.path.getsize(label) == 0:
        raise RuntimeError(f"cannot read {dest} or its SELinux label from the image; refusing to relabel blindly")
    mode = os.stat(local).st_mode & 0o7777
    with open(local, "a") as f:
        f.write(text)
    d, b = os.path.dirname(dest), os.path.basename(dest)
    return [f'rm "{dest}"', f'cd "{d}"', f'write "{local}" "{b}"',
            f'set_inode_field "{dest}" mode 0{0o100000 | mode:o}', f'set_inode_field "{dest}" uid {uid}',
            f'set_inode_field "{dest}" gid {gid}', f'ea_set -f "{label}" "{dest}" security.selinux']


def apply_overlay(img, overlay, props, tmp, appends=None):
    label = os.path.join(tmp, "label")
    with open(label, "wb") as f:
        f.write(SYSTEM_FILE.encode() + b"\0")
    cmds = []
    for src, dest in overlay_files(overlay):
        mode = os.stat(src).st_mode & 0o7777
        cmds += [f'rm "{dest}"', f'cd "{os.path.dirname(dest)}"',
                 f'write "{src}" "{os.path.basename(dest)}"',
                 f'set_inode_field "{dest}" mode 0{0o100000 | mode:o}',
                 f'set_inode_field "{dest}" uid 0',
                 f'set_inode_field "{dest}" gid {SHELL_GID if mode & 0o111 else 0}',
                 f'ea_set -f "{label}" "{dest}" security.selinux']
    for i, (dest, text) in enumerate(append_texts(props, appends)):
        cmds += append_cmds(img, dest, text, os.path.join(tmp, f"append{i}"))
    debugfs_write(img, cmds)


def verify_overlay(img, overlay, props, tmp, appends=None):
    """debugfs exits 0 even if a command failed, so every write is read back and compared."""
    for i, (src, dest) in enumerate(overlay_files(overlay)):
        got = os.path.join(tmp, f"readback{i}")
        run("debugfs", "-R", f'dump "{dest}" "{got}"', img)
        stat = run("debugfs", "-R", f'stat "{dest}"', img)
        if not os.path.exists(got) or sha256(got) != sha256(src) or f'"{SYSTEM_FILE}\\000"' not in stat:
            raise RuntimeError(f"overlay readback failed for {dest}")
    for i, (dest, text) in enumerate(append_texts(props, appends)):
        got = os.path.join(tmp, f"append-readback{i}")
        run("debugfs", "-R", f'dump "{dest}" "{got}"', img)
        with open(got) as f:
            if not f.read().endswith(text):
                raise RuntimeError(f"append readback failed for {dest}")


def build(donor_system, vendor, odm, overlay, props, workdir, out_super, super_size, group, appends=None):
    os.makedirs(workdir, exist_ok=True)
    system = os.path.join(workdir, "system_a.img")
    shutil.copyfile(donor_system, system)
    run("e2fsck", "-fy", system, ok=(0, 1))  # resize2fs refuses an unchecked filesystem
    extra = sum(os.path.getsize(s) for s, _ in overlay_files(overlay)) + (64 << 20)
    new_size = -(-(os.path.getsize(system) + extra) // 4096) * 4096
    run("resize2fs", system, f"{new_size // 1024}K")  # growing adds block groups, hence free inodes
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        apply_overlay(system, overlay, props, tmp, appends)
        verify_overlay(system, overlay, props, tmp, appends)
    run("e2fsck", "-fn", system)  # read-only check; non-zero exit raises
    parts = {"system_a": system, "vendor_a": vendor, "odm_a": odm}
    if out_super is None:  # partition image only: no LP metadata is produced
        return {"partitions": {"system_a": {"image": system, "size": os.path.getsize(system), "sha256": sha256(system)}},
                "props": props, "appends": sorted(appends or {}), "overlay": [d for _, d in overlay_files(overlay)],
                "verified": {"e2fsck": "clean", "overlay_readback": "match"}}
    args = ["lpmake", "--metadata-size", "65536", "--metadata-slots", "3", "--super-name", "super",
            "--device", f"super:{super_size}", "--group", f"{group}_a:{super_size}",
            "--group", f"{group}_b:{super_size}", "--virtual-ab", "--sparse", "--output", out_super]
    for name, img in parts.items():
        args += ["--partition", f"{name}:readonly:{os.path.getsize(img)}:{group}_a", "--image", f"{name}={img}"]
    for name in parts:
        args += ["--partition", f"{name[:-2]}_b:readonly:0:{group}_b"]
    run(*args)
    with open(out_super, "rb") as f:
        layout = sparselp.lp_layout(sparselp.raw_prefix(f, 1 << 20))
    with open(out_super, "rb") as f:
        got = sparselp.hash_partitions(f, layout, list(parts))
    want = {n: sha256(p) for n, p in parts.items()}
    if got != want:
        raise RuntimeError(f"super round-trip mismatch: {got} != {want}")
    return {"partitions": {n: {"image": p, "size": os.path.getsize(p), "sha256": want[n]} for n, p in parts.items()},
            "super": {"path": out_super, "size": os.path.getsize(out_super), "sha256": sha256(out_super),
                      "device_size": super_size, "layout": layout},
            "props": props, "appends": sorted(appends or {}), "overlay": [d for _, d in overlay_files(overlay)],
            "verified": {"e2fsck": "clean", "overlay_readback": "match", "super_roundtrip": "match"}}


def main(argv=None):
    cfg_path, out_json = argv if argv is not None else sys.argv[1:]
    with open(cfg_path) as f:
        cfg = json.load(f)
    manifest = build(**cfg)
    with open(out_json, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    print(json.dumps(manifest["verified"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

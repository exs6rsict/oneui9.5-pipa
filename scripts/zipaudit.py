#!/usr/bin/env python3
"""Offline ZIP audit: central-directory metadata only, never extracts or executes payload."""
import argparse
import json
import os
import re
import sys
import stat
import struct
import zlib
import zipfile

COMPRESSION = {zipfile.ZIP_STORED: "store", zipfile.ZIP_DEFLATED: "deflate",
               zipfile.ZIP_BZIP2: "bzip2", zipfile.ZIP_LZMA: "lzma"}

MAX_RATIO = 100  # deflate tops out ~1032:1; padded firmware images (dtbo, vendor_boot) reach ~250:1

# Name-based only: says which partition a file is *named* for, not what is inside it.
PARTITION_RE = re.compile(r"^([A-Za-z0-9_]+)(?:\.img(?:\.(?:lz4|zst|gz|xz|br))?|\.new\.dat(?:\.br)?)$")

# Text read for evidence only (never executed); installer scripts show which partitions get written.
TEXT_NAMES = {"updater-script", "update-binary", "metadata", "payload_properties.txt", "source.properties"}
TEXT_SUFFIXES = (".prop", ".properties", ".sh", ".bat", ".cfg")
TEXT_CAP = 64 * 1024        # bytes of decompressed output per entry
TEXT_BUDGET = 1024 * 1024   # bytes of decompressed output per archive


def is_text_metadata(name):
    base = name.rsplit("/", 1)[-1]
    return base in TEXT_NAMES or base.endswith(TEXT_SUFFIXES)


def read_prefix(z, info, cap):
    """Decompress at most cap+1 bytes; the extra byte only tells us whether it was truncated."""
    with z.open(info) as f:
        data = f.read(cap + 1)
    return data[:cap], len(data) > cap


SNIFF_CAP = 8192  # LP geometry sits at 4096; nothing past this prefix is decompressed


def sniff(prefix):
    """Container format from magic bytes. Identifies the wrapper only, not the build inside it."""
    def u32(off):
        return struct.unpack_from("<I", prefix, off)[0] if len(prefix) >= off + 4 else None
    for magic, name in ((b"ANDROID!", "android-boot"), (b"VNDRBOOT", "vendor-boot"), (b"AVB0", "avb-vbmeta")):
        if prefix.startswith(magic):
            return name
    if u32(0) == 0xED26FF3A:
        return "android-sparse"
    if u32(1024) == 0xE0F5E1E2:
        return "erofs"
    if u32(1024) == 0xF2F52010:
        return "f2fs"
    if len(prefix) >= 1082 and struct.unpack_from("<H", prefix, 1080)[0] == 0xEF53:
        return "ext4"
    if u32(4096) == 0x616C4467:
        return "lp-super"
    return "unknown"


def safe_prefix(z, info, cap, findings):
    """read_prefix, but a corrupt stream becomes an 'unreadable' finding instead of aborting the audit."""
    try:
        return read_prefix(z, info, cap)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as exc:
        findings.append({"kind": "unreadable", "entry": info.filename, "error": str(exc)})
        return None


def unsafe_path(name):
    """True if extracting `name` on POSIX or Windows could escape the target dir."""
    norm = name.replace("\\", "/")
    return (norm.startswith("/") or "\0" in norm or re.match(r"^[A-Za-z]:", norm) is not None
            or ".." in norm.split("/"))


def audit(path, text_cap=TEXT_CAP, text_budget=TEXT_BUDGET):
    entries, findings, seen, partitions = [], [], set(), {}
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            e = {"name": i.filename, "size": i.file_size, "compressed": i.compress_size,
                 "compression": COMPRESSION.get(i.compress_type, f"method-{i.compress_type}")}
            entries.append(e)
            m = PARTITION_RE.match(i.filename.rsplit("/", 1)[-1])
            if m and not i.is_dir():
                e["partition"] = m.group(1)
                partitions.setdefault(m.group(1), []).append(i.filename)
            if i.flag_bits & 0x1:
                findings.append({"kind": "encrypted", "entry": i.filename})
            if unsafe_path(i.filename):
                findings.append({"kind": "unsafe-path", "entry": i.filename})
            if i.create_system == 3 and stat.S_ISLNK(i.external_attr >> 16):
                findings.append({"kind": "symlink", "entry": i.filename})
            key = i.filename.replace("\\", "/").casefold()  # case-insensitive hosts collide too
            if key in seen:
                findings.append({"kind": "duplicate", "entry": i.filename})
            seen.add(key)
            if i.file_size > MAX_RATIO * max(i.compress_size, 1):
                findings.append({"kind": "high-ratio", "entry": i.filename,
                                 "ratio": round(i.file_size / max(i.compress_size, 1))})
        flagged = {f["entry"] for f in findings if f["kind"] != "high-ratio"}
        text = {}
        for e, i in zip(entries, z.infolist()):
            if "partition" not in e or i.filename in flagged:
                continue
            got = safe_prefix(z, i, SNIFF_CAP, findings)
            e["format"] = sniff(got[0]) if got else "unreadable"
        for i in z.infolist():
            if i.is_dir() or i.filename in flagged or not is_text_metadata(i.filename) or text_budget <= 0:
                continue
            got = safe_prefix(z, i, min(text_cap, text_budget), findings)
            if not got:
                continue
            data, truncated = got
            text_budget -= len(data)
            if b"\0" in data:
                continue  # binary despite the name: not text metadata
            text[i.filename] = {"text": data.decode("utf-8", "replace"), "truncated": truncated}
    totals = {"entries": len(entries), "declared_size": sum(e["size"] for e in entries),
              "compressed_size": sum(e["compressed"] for e in entries)}
    return {"entries": entries, "findings": findings, "totals": totals,
            "partitions": dict(sorted(partitions.items())), "text": text,
            "scope": "ZIP central directory + bounded prefixes; 'format' is the outer container only. "
                     "Filesystems inside images were not decoded, so no build property is asserted."}


def compare(a, b):
    """Diff two audit() results. Compares ZIP metadata and partition names, not image contents."""
    ea, eb = ({e["name"]: e for e in inv["entries"] if not e["name"].endswith("/")} for inv in (a, b))
    pick = lambda e: {"size": e["size"], "format": e.get("format")}
    changed = [{"name": n, "a": pick(ea[n]), "b": pick(eb[n])}
               for n in sorted(ea.keys() & eb.keys()) if pick(ea[n]) != pick(eb[n])]
    pa, pb = set(a["partitions"]), set(b["partitions"])
    return {"entries": {"only_a": sorted(ea.keys() - eb.keys()), "only_b": sorted(eb.keys() - ea.keys()),
                        "changed": changed},
            "partitions": {"only_a": sorted(pa - pb), "only_b": sorted(pb - pa), "both": sorted(pa & pb)}}


UNSAFE = {"unsafe-path", "symlink", "duplicate", "encrypted", "unreadable"}  # high-ratio is a warning only


def describe_archive(path):
    """Size from stat, hash from the download sidecar: a multi-GB archive is never rehashed."""
    info = {"path": os.path.abspath(path), "bytes": os.path.getsize(path), "sidecar_sha256": None}
    side = path + ".metadata.json"
    if os.path.isfile(side) and os.path.getsize(side) <= 64 * 1024:
        with open(side) as f:
            meta = json.load(f)
        info["sidecar_sha256"] = meta.get("sha256")
        info["sidecar_bytes_match"] = meta.get("bytes") == info["bytes"]
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="inventory one ZIP (exit 2 if unsafe entries)")
    a.add_argument("zip")
    a.add_argument("-o", "--output")
    c = sub.add_parser("compare", help="diff two audit JSON files (a=baseline, b=donor)")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    if args.cmd == "audit":
        try:
            result = {"archive": describe_archive(args.zip), **audit(args.zip)}
        except (zipfile.BadZipFile, OSError, EOFError) as exc:
            print(f"error: {args.zip}: not a readable zip ({exc})", file=sys.stderr)
            return 1
        code = 2 if any(f["kind"] in UNSAFE for f in result["findings"]) else 0
    else:
        with open(args.a) as fa, open(args.b) as fb:
            result, code = compare(json.load(fa), json.load(fb)), 0
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return code


if __name__ == "__main__":
    sys.exit(main())

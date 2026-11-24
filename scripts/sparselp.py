#!/usr/bin/env python3
"""Stream an Android sparse super image (e.g. straight out of a ZIP) into selected logical
partition images, without ever materialising the raw super. LP metadata is decoded by the
distro's trusted `lpdump`; this module only moves bytes and checks bounds."""
import os
import re
import struct
import subprocess
import tempfile

SPARSE_MAGIC = 0xED26FF3A
RAW, FILL, DONT_CARE, CRC = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4
PIECE = 4 << 20          # RAW payload is handled in pieces of at most this many bytes
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def read_exact(stream, n):
    data = stream.read(n)
    if len(data) != n:
        raise ValueError(f"truncated sparse stream: wanted {n} bytes, got {len(data)}")
    return data


def pieces(stream):
    """Yield (raw_offset, length, kind, payload): payload is bytes for RAW, the 4-byte word
    for FILL, None for DONT_CARE. Header fields are validated before they size any read."""
    magic, major, _minor, fhs, chs, blk, total_blocks, total_chunks, _ = struct.unpack(
        "<IHHHHIIII", read_exact(stream, 28))
    if magic != SPARSE_MAGIC or major != 1 or fhs < 28 or chs < 12 or blk == 0 or blk % 4:
        raise ValueError("not a version-1 Android sparse image")
    read_exact(stream, fhs - 28)
    raw_size, pos = blk * total_blocks, 0
    for _ in range(total_chunks):
        kind, _r, blocks, total = struct.unpack("<HHII", read_exact(stream, 12))
        read_exact(stream, chs - 12)
        body, length = total - chs, blocks * blk
        expected = {RAW: length, FILL: 4, DONT_CARE: 0, CRC: 4}.get(kind)
        if expected is None or body != expected:
            raise ValueError(f"bad chunk type {kind:#x} or size {total}")
        if kind == CRC:
            read_exact(stream, 4)
            continue
        if pos + length > raw_size:
            raise ValueError("chunk runs past the declared image size")
        if kind == RAW:
            done = 0
            while done < length:
                n = min(PIECE, length - done)
                yield pos + done, n, RAW, read_exact(stream, n)
                done += n
        else:
            yield pos, length, kind, read_exact(stream, 4) if kind == FILL else None
        pos += length
    if pos != raw_size:
        raise ValueError(f"chunks cover {pos} bytes, header declares {raw_size}")


def materialise(kind, payload, length):
    return payload if kind == RAW else (payload * (length // 4) if kind == FILL else bytes(length))


def raw_prefix(stream, n):
    """First n bytes of the raw image, decoded from the sparse stream (bounded memory)."""
    out = bytearray()
    for _off, length, kind, payload in pieces(stream):
        out += materialise(kind, payload, min(length, n - len(out)))[: n - len(out)]
        if len(out) >= n:
            break
    return bytes(out)


EXTENT_RE = re.compile(r"^\s*(\d+) \.\. (\d+) linear (\S+) (\d+)\s*$")


def lp_layout(prefix):
    """{partition: {"size": bytes, "extents": [(super_offset, length, partition_offset)]}} from lpdump."""
    with tempfile.NamedTemporaryFile(suffix=".img") as tmp:
        tmp.write(prefix)
        tmp.flush()
        text = subprocess.run(["lpdump", tmp.name], check=True, capture_output=True, text=True).stdout
    layout, current = {}, None
    for line in text.splitlines():
        if line.strip().startswith("Name:") and current is not False:
            name = line.split(":", 1)[1].strip()
            if not NAME_RE.match(name):
                raise ValueError(f"unsafe partition name {name!r}")
            current = layout.setdefault(name, {"size": 0, "extents": []})
        elif line.startswith("Super partition layout"):
            current = False  # group names below also use "Name:"; extents are complete by now
        elif current and (m := EXTENT_RE.match(line)):
            first, last, device, target = (int(m[1]), int(m[2]), m[3], int(m[4]))
            if device != "super":
                raise ValueError(f"extent on unsupported block device {device}")
            length = (last - first + 1) * 512
            current["extents"].append((target * 512, length, first * 512))
            current["size"] += length
    return layout


def extract(stream, outdir, layout, wanted):
    """Write each wanted partition to outdir/<name>.img in one pass. Zero regions stay holes."""
    files = {}
    try:
        for name in wanted:
            if name not in layout or not NAME_RE.match(name):
                raise ValueError(f"partition {name!r} not in LP layout")
            f = files[name] = open(os.path.join(outdir, name + ".img"), "wb")
            f.truncate(layout[name]["size"])
        for off, length, kind, payload in pieces(stream):
            if kind == DONT_CARE or (kind == FILL and payload == b"\0\0\0\0"):
                continue  # the truncated file already reads as zeros there
            for name, f in files.items():
                for tgt, ext_len, part_off in layout[name]["extents"]:
                    lo, hi = max(off, tgt), min(off + length, tgt + ext_len)
                    if lo >= hi:
                        continue
                    f.seek(part_off + lo - tgt)
                    if kind == RAW:
                        f.write(payload[lo - off:hi - off])
                    else:
                        for start in range(lo, hi, PIECE):  # FILL: bounded pattern buffers
                            f.write(payload * (min(PIECE, hi - start) // 4))
    finally:
        for f in files.values():
            f.close()
    return {"partitions": {n: {"size": layout[n]["size"], "path": os.path.join(outdir, n + ".img")}
                           for n in files}}


def hash_partitions(stream, layout, wanted):
    """SHA-256 of each wanted partition, computed in one streaming pass (nothing written)."""
    import hashlib
    state = {}
    for name in wanted:
        exts = layout[name]["extents"]
        if [e[2] for e in exts] != sorted(e[2] for e in exts) or [e[0] for e in exts] != sorted(e[0] for e in exts):
            raise ValueError(f"{name}: extents not in super order; cannot hash in one pass")
        state[name] = [hashlib.sha256(), 0]
    for off, length, kind, payload in pieces(stream):
        for name, st in state.items():
            for tgt, ext_len, _part_off in layout[name]["extents"]:
                lo, hi = max(off, tgt), min(off + length, tgt + ext_len)
                for start in range(lo, hi, PIECE):  # bounded buffers for FILL/DONT_CARE
                    end = min(hi, start + PIECE)
                    st[0].update(payload[start - off:end - off] if kind == RAW
                                 else materialise(kind, payload, end - start))
                    st[1] += end - start
    for name, (_h, n) in state.items():
        if n != layout[name]["size"]:
            raise ValueError(f"{name}: hashed {n} bytes, layout says {layout[name]['size']}")
    return {name: h.hexdigest() for name, (h, _n) in state.items()}


def main(argv=None):
    """sparselp.py ZIP MEMBER OUTDIR [PARTITION...]: layout JSON to stdout; extracts named partitions."""
    import json
    import sys
    import zipfile
    zpath, member, outdir, *wanted = argv if argv is not None else sys.argv[1:]
    with zipfile.ZipFile(zpath) as z:
        with z.open(member) as f:
            layout = lp_layout(raw_prefix(f, 1 << 20))  # LP geometry+metadata live in the first MiB
        result = {"layout": layout}
        if wanted:
            os.makedirs(outdir, exist_ok=True)
            with z.open(member) as f:  # reading to EOF makes zipfile verify the member CRC32
                result.update(extract(f, outdir, layout, wanted))
                f.read(1)
    json.dump(result, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate an A-only device write plan WITHOUT executing anything. It never approves a flash:
passing only means the plan respects the dual-boot preservation contract and still needs explicit
user approval. Protected: the whole _b chain, the shared super (whole/metadata), the Linux host
(sda35), GPT, userdata, metadata, persist and bootloader firmware."""
import hashlib
import json
import os
import re
import sys

ALLOWED_RAW = {"boot_a", "vendor_boot_a", "dtbo_a"}           # slot-A boot chain, pipa's own images
LOGICAL_A = {"system_a", "vendor_a", "odm_a", "product_a", "system_ext_a"}  # in-place: live extent, or lprelayout.py extent
PROTECTED_NAMES = re.compile(
    r"^(linux|userdata|metadata|persist|misc|frp|gpt|primarygpt|backupgpt|partition|"
    r"xbl|xbl_config|abl|tz|hyp|aop|keymaster|modem|devcfg|qupfw|uefisecapp|cmnlib|cmnlib64|"
    r"bluetooth|dsp|imagefv|featenabler|vbmeta|vbmeta_system)(_a)?$", re.I)
# Reject all UUID-style device identifiers, without embedding a host's actual IDs.
PROTECTED_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def lp_sizes(layout):
    """{name: bytes} from `lpdump -j` (partitions: list, size as str) or the older dict form; no size = 0 B."""
    parts = (layout or {}).get("partitions", {})
    if isinstance(parts, dict):
        return {n: int(v.get("size", 0)) for n, v in parts.items()}
    return {v["name"]: int(v.get("size", 0)) for v in parts}


def check_backup(backup, bad):
    """GPT and live-super LP dumps must exist and match their recorded hashes."""
    layout = None
    for key in ("gpt", "super_lp"):
        item = (backup or {}).get(key)
        if not item or not os.path.isfile(item.get("path", "")) or sha256(item["path"]) != item.get("sha256"):
            bad("layout-backup", key, "missing or hash mismatch")
        elif key == "super_lp":
            with open(item["path"]) as f:
                layout = json.load(f)
    return layout


def validate(plan, extents=None):
    """extents: {logical_a: bytes} from a separately validated LP re-layout (lprelayout.py); default = live."""
    violations = []
    bad = lambda rule, target, why: violations.append({"rule": rule, "target": target, "why": why})
    if plan.get("slot") != "a":
        bad("slot-b", plan.get("slot"), "only slot a may be planned")
    layout = check_backup(plan.get("layout_backup"), bad)
    for w in plan.get("writes", []):
        t = str(w.get("target", ""))
        low = t.lower()
        if w.get("op") != "write":
            bad("operation", t, f"op {w.get('op')!r} not allowed (only in-place write)")
        if low.endswith("_b") or low.endswith("_ab") or low in ("b", "ab"):
            bad("slot-b", t, "slot-B chain is protected")
        if low in ("super", "super_a", "super_b") or "super_empty" in low:
            bad("shared-super", t, "super is shared with slot B; whole/metadata writes forbidden")
        if t.startswith("/") or "partuuid" in low or PROTECTED_ID.search(low) or PROTECTED_NAMES.match(t):
            bad("protected", t, "device paths, Linux host, GPT, data, metadata and firmware are protected")
        img = w.get("image")
        if w.get("op") == "write":
            if not img or not os.path.isfile(img.get("path", "")) or sha256(img["path"]) != img.get("sha256"):
                bad("image-hash", t, "image missing or sha256 mismatch")
            elif low in LOGICAL_A:
                cur = (extents if extents is not None else lp_sizes(layout)).get(low)
                if cur is None or os.path.getsize(img["path"]) > cur:
                    bad("extent", t, f"image {os.path.getsize(img['path'])} B exceeds live extent {cur}; "
                                     "would need LP metadata change in shared super")
            elif low not in ALLOWED_RAW and not any(v["target"] == t for v in violations):
                bad("protected", t, "not on the A-only allowlist")
    return {"violations": violations, "passes_preserve_layout_checks": not violations,
            "requires_explicit_user_approval": True, "approved_to_flash": False}


def main(argv=None):
    (path,) = argv if argv is not None else sys.argv[1:]
    with open(path) as f:
        r = validate(json.load(f))
    print(json.dumps(r, indent=1))
    return 0 if r["passes_preserve_layout_checks"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

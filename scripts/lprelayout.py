#!/usr/bin/env python3
"""Offline validator for re-laying out ONLY group qti_dynamic_partitions_a inside the shared super. Executes nothing
and never approves a flash.

Input plan (JSON): {"slot": "a", "layout_backup": {"gpt": <sda dump>, "super_lp": <lpdump -j>},
"manifest": <gate5-slot-a-manifest.json>, "writes": [optional flashplan writes]}, where each file is
{"path", "sha256"}. Output: the proposed 1 MiB-aligned _a layout, or violations.

Hard rejections: any key/operation besides the above (no GPT edit, no raw super.img, no erase/resize op);
any *_b partition or group touched, or slot B owning space in the live LP; a GPT dump where super, userdata
(sda34) and linux (sda35) are not where the backup says, or overlap; logical images that are not exactly
the 5 *_a from the manifest or whose sha256 differs; a layout that does not fit the _a group or super."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flashplan  # noqa: E402

GROUP_A = "qti_dynamic_partitions_a"
ORDER = ["system_a", "system_ext_a", "product_a", "vendor_a", "odm_a"]  # same order as the live layout
assert set(ORDER) == flashplan.LOGICAL_A
PLAN_KEYS = {"slot", "layout_backup", "manifest", "writes"}
GUARDED = {"super": "sda29", "userdata": "sda34", "linux": "sda35"}  # GPT name -> device it must stay on
GPT_LINE = re.compile(r'^/dev/(\w+) : start=\s*(\d+), size=\s*(\d+),.*name="([^"]*)"')


def gpt_entries(path):
    """{name: (dev, start_byte, size_byte)} from an `sfdisk -d` dump."""
    sector, out = None, {}
    with open(path) as f:
        for line in f:
            if line.startswith("sector-size:"):
                sector = int(line.split()[1])
            m = GPT_LINE.match(line)
            if m:
                out[m[4]] = (m[1], int(m[2]), int(m[3]))
    return {n: (d, s * sector, z * sector) for n, (d, s, z) in out.items()} if sector else {}


def up(n, a):
    return -(-n // a) * a


def validate(plan):
    violations = []
    bad = lambda rule, target, why: violations.append({"rule": rule, "target": target, "why": why})
    for k in sorted(set(plan) - PLAN_KEYS):
        bad("operation", k, "only an _a group re-layout is planned here; no other operation (GPT, raw super, ...)")
    if plan.get("slot") != "a":
        bad("slot-b", plan.get("slot"), "only slot a may be planned")
    lp = flashplan.check_backup(plan.get("layout_backup"), bad)
    g = (plan.get("layout_backup") or {}).get("gpt") or {}
    gpt = gpt_entries(g["path"]) if os.path.isfile(g.get("path", "")) else {}

    # GPT: super, userdata, linux exactly where the backup recorded them, disjoint; the plan never edits GPT.
    for name, dev in GUARDED.items():
        if gpt.get(name, (None,))[0] != dev:
            bad("gpt", name, f"GPT backup must show {name} on {dev}; got {gpt.get(name, (None,))[0]}")
    spans = sorted((s, s + z, n) for n, (_d, s, z) in gpt.items() if n in GUARDED)
    for (_s1, e1, n1), (s2, _e2, n2) in zip(spans, spans[1:]):
        if s2 < e1:
            bad("gpt", f"{n1}/{n2}", "guarded GPT partitions overlap")

    # Live LP: one super block device that matches the GPT super; slot B owns nothing and stays that way.
    lp = lp or {}
    devs = lp.get("block_devices") or []
    if len(devs) != 1 or devs[0].get("name") != "super":
        bad("super-lp", "block_devices", "expected a single 'super' block device (a real `lpdump -j` dump)")
        devs = [{}]
    super_bytes, align = int(devs[0].get("size", 0)), int(devs[0].get("alignment", 0) or 0)
    if not align:
        bad("super-lp", "alignment", "missing LP alignment")
        align = 1 << 20
    if "super" in gpt and gpt["super"][2] != super_bytes:
        bad("gpt", "super", f"LP super size {super_bytes} != GPT super size {gpt['super'][2]}")
    groups = {g["name"]: int(g.get("maximum_size", 0)) for g in lp.get("groups", [])}
    if GROUP_A not in groups:
        bad("super-lp", GROUP_A, "group missing from live LP")
    live = flashplan.lp_sizes(lp)
    slot_b = sorted(n for n in live if n.endswith("_b"))
    for n in slot_b:
        if live[n]:
            bad("slot-b", n, f"slot B owns {live[n]} B in live LP; re-layout would have to move it")
    if not slot_b:
        bad("slot-b", "partitions", "live LP lists no *_b partitions; refusing an unexpected layout")

    # Images: exactly the 5 logical _a from the Gate 5 manifest, re-hashed here.
    m = plan.get("manifest") or {}
    if not os.path.isfile(m.get("path", "")) or flashplan.sha256(m["path"]) != m.get("sha256"):
        bad("manifest", "manifest", "missing or sha256 mismatch")
        arts = []
    else:
        with open(m["path"]) as f:
            arts = [a for a in json.load(f).get("artifacts", []) if str(a.get("target", "")).startswith("super:")]
    images = {}
    for a in arts:
        n = a["target"].split(":", 1)[1]
        if n not in flashplan.LOGICAL_A or n in images:
            bad("manifest", n, "not one of the 5 logical *_a, or listed twice")
        elif not os.path.isfile(a.get("path", "")) or flashplan.sha256(a["path"]) != a.get("sha256"):
            bad("image-hash", n, "image missing or sha256 mismatch")
        else:
            images[n] = os.path.getsize(a["path"])
    if arts and set(images) != flashplan.LOGICAL_A and not any(v["rule"] in ("manifest", "image-hash")
                                                                for v in violations):
        bad("manifest", "logical_a", f"need exactly {sorted(flashplan.LOGICAL_A)}, got {sorted(images)}")

    # Proposed layout: _a partitions back to back from the first aligned sector, each rounded up to alignment.
    layout, off = {}, align  # LP geometry+metadata live below the first alignment boundary
    for n in ORDER:
        if n in images:
            size = up(images[n], align)
            layout[n] = {"image_bytes": images[n], "size": size, "offset": off}
            off += size
    used = off - align
    if used > groups.get(GROUP_A, 0):
        bad("fit", GROUP_A, f"{used} B exceeds group maximum {groups.get(GROUP_A, 0)}")
    if off > super_bytes:
        bad("fit", "super", f"layout ends at {off} B, past super size {super_bytes}")

    # Optional writes reuse the A-only contract, checked against the proposed extents instead of the live ones.
    if plan.get("writes"):
        sub = {"slot": plan.get("slot"), "layout_backup": plan.get("layout_backup"), "writes": plan["writes"]}
        violations += [v for v in flashplan.validate(sub, {n: v["size"] for n, v in layout.items()})["violations"]
                       if v not in violations]
    return {"violations": violations, "passes_relayout_checks": not violations,
            "proposed_layout": {"group": GROUP_A, "alignment": align, "partitions": layout, "used_bytes": used,
                                "image_total_bytes": sum(images.values()), "super_bytes": super_bytes,
                                "free_after_bytes": super_bytes - off, "slot_b_unchanged_empty": slot_b},
            "requires_explicit_user_approval": True, "approved_to_flash": False}


def main(argv=None):
    (path,) = argv if argv is not None else sys.argv[1:]
    with open(path) as f:
        r = validate(json.load(f))
    print(json.dumps(r, indent=1))
    return 0 if r["passes_relayout_checks"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

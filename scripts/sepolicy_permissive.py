#!/usr/bin/env python3
"""Make every SELinux domain permissive *in the policy init compiles at boot*, and prove it from
the compiled binary. Compilation mirrors Android init's split-policy secilc call; decompilation
uses the host's checkpolicy, so the check reads what the kernel would load, not our own CIL text.
A policy that fails to compile still fails: permissive is no substitute for loadable policy."""
import json
import os
import re
import subprocess
import sys

POLICY_VERSION = 31  # highest policydb version a 4.19 kernel accepts
TYPEATTR = re.compile(r"^typeattribute (\S+) (.+);$", re.M)
PERMISSIVE = re.compile(r"^permissive (\S+);$", re.M)


def compile_policy(cil_files, out):
    r = subprocess.run(["secilc", "-m", "-M", "true", "-G", "-N", "-c", str(POLICY_VERSION),
                        "-o", out, "-f", os.devnull, *cil_files], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"secilc failed: {(r.stdout + r.stderr).strip()[-800:]}")


def decompile(policy, out_conf):
    subprocess.run(["checkpolicy", "-M", "-b", "-F", "-o", out_conf, policy], check=True, capture_output=True)
    with open(out_conf) as f:
        return f.read()


def domains(conf):
    return sorted(t for t, attrs in TYPEATTR.findall(conf) if "domain" in (a.strip() for a in attrs.split(",")))


def make_permissive(cil_files, out_cil, workdir):
    base_bin, base_conf = os.path.join(workdir, "base.policy"), os.path.join(workdir, "base.conf")
    compile_policy(cil_files, base_bin)
    conf = decompile(base_bin, base_conf)
    doms = domains(conf)
    if not doms:  # otherwise an empty CIL would "verify" trivially
        raise RuntimeError("no domain types found in the compiled policy; cannot prove permissive")
    with open(out_cil, "w") as f:
        f.write(";; port95: policy-level permissive for every resolved domain (generated, see reports/port95)\n")
        f.writelines(f"(typepermissive {d})\n" for d in doms)
    new_bin, new_conf = os.path.join(workdir, "permissive.policy"), os.path.join(workdir, "permissive.conf")
    compile_policy([*cil_files, out_cil], new_bin)
    got = sorted(PERMISSIVE.findall(decompile(new_bin, new_conf)))
    if got != doms:
        raise RuntimeError(f"binary permissive set != domain set ({len(got)} vs {len(doms)})")
    return {"domains": doms, "permissive_in_binary": got, "base_permissive": sorted(PERMISSIVE.findall(conf)),
            "policy_version": POLICY_VERSION, "policy_bytes": os.path.getsize(new_bin)}


def main(argv=None):
    out_cil, workdir, report, *cil_files = argv if argv is not None else sys.argv[1:]
    r = make_permissive(cil_files, out_cil, workdir)
    with open(report, "w") as f:
        json.dump({**r, "inputs": cil_files}, f, indent=1)
    print(json.dumps({"domains": len(r["domains"]), "permissive_in_binary": len(r["permissive_in_binary"]),
                      "base_permissive": len(r["base_permissive"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

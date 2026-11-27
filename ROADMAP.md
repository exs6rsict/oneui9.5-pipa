# Roadmap: Audit and Port One UI 9.5 to Xiaomi Pad 6 (`pipa`)

## Goal and Constraints

Compare an existing working One UI port on `pipa` (`B0`) against One UI 9.5 donor candidates, then execute a clean, verifiable port preserving dual-boot Linux.

- **Target device:** Xiaomi Pad 6, codename `pipa` (Slot A only; preserve `/dev/sda35` Linux and Slot B untouched).
- **Target version:** One UI 9.5 (Android 17 / SDK 37.2). One UI 9.0 is neither the target nor a fallback; `9.0` donors are configuration references only.
- **Baseline:** A verified working One UI `pipa` port (`B0`), cross-checked directly from binary images rather than distributor claims alone.
- **Separation of concerns:** Offline audit, extraction, image modification, and device flashing are strictly separate stages.
- **Evidence over assumptions:** Version labels, chipsets, or cross-device reports do not count as boot proof.

## Current Status (2026-11-28)

- [x] Set `pipa` (Slot A dual-boot safe) as target.
- [x] Gathered initial baseline & donor candidates.
- [x] Verified `B0` baseline package (`inputs/baseline-pipa/`).
- [x] Verified `D2` donor package (`inputs/donors/XGSI_SM-S948B_S948BXXU6ZZKN_arm64.zip`).
- [x] Audited binary metadata from `B0` and `D2` (`reports/port95/README.md`, [reports/CHECKPOINT.md](reports/CHECKPOINT.md)).
- [x] Captured live `pipa` GPT & LP `super` layout backups (`reports/port95/dualboot/live-backup/`).
- [x] Completed Gate 5 offline image assembly & manifest (`reports/port95/GATE5-REPORT.md`, local only).
- [x] Prepared Gate 6 Slot A bundle: `boot_a`/`vendor_boot_a`/`dtbo_a` backups, LP re-layout validator `scripts/lprelayout.py`.
- [x] Executed Gate 6 Boot Attempt 1 & diagnosed `pstore`: kernel + `init` booted, halted on `erofs_fill_symlink` bug (`nid 767` `/system_ext`).
- [x] Fixed `erofs_fill_symlink` ([0001](patches/0001-port95-erofs-fill_symlink-read-inline-data-from-next-block.patch)) and rebuilt `boot_a.img` (`7a179ab1...`) on VPS.
- [x] Executed Gate 6 Boot Attempt 2 & diagnosed `console-ramoops-0`: `erofs_fill_symlink` fixed; halted on `netbpfload` (`netd.o` helper `#122` `bpf_get_netns_cookie`) and EROFS `lz4armv8` `-3901` (`4096→4492`).
- [x] Applied patches [0002](patches/0002-port95-bpf-allow-bpf_get_netns_cookie-in-sock_ops-and-cgroup_sockopt.patch) & [0003](patches/0003-port95-erofs-use-C-LZ4-decoder-instead-of-lz4armv8-inplace.patch), built `gate6fix` kernel on VPS, passed arm64 QEMU (`bpfloader` Stage 1–3 `rc=0` / `bpf.progs_loaded=1` + EROFS `system_a` verification), packaged `boot_a.img` (`6fb3aba4...`).
- [x] **Gate 6 Boot Attempt 3 PASSED to One UI 9.5 UI (`M1–M3` verified on hardware)**: `sys.boot_completed=1`, `bpf.progs_loaded=1`, `0` EROFS errors in `dmesg-boot3.txt`, `Permissive`, `/data` f2fs mounted `rw`, Wireless ADB (`uid=0`), Wi-Fi `wlan0`, quad Awinic audio, touch/pen switch, and `sensors@1.0-service` active.
- [ ] **Phase 7 (`M4–M6`) hardware & tablet UX bugfixing**: fix phone→tablet UX (`ro.build.characteristics=tablet`, `lcd_density=280`, lockscreen rotation, Quick Settings/Notification width, `floating_feature`), restore stripped Samsung components (`com.samsung.android.lool` Device Care for `Device care`/`Battery`/`Storage`), stop `traced` 5s crash-loop, clean `vold`/RIL/lazy-AIDL noise, and fix USB ADB (`host_connected=false`).

## Initial Candidates

| ID | Candidate | Source | Role |
| --- | --- | --- | --- |
| B0 | Working One UI 8.0 port for `pipa` | https://t.me/XiaomiPad6Global/394100 | Reference for hardware integration, boot chain, and `pipa` patches |
| D1 | Tab S9+ `SM-X810`, KOO, `X810XXU6FZK2` | https://samfw.com/firmware/SM-X810/KOO/X810XXU6FZK2 | Raw tablet firmware reference (One UI 9.0, not 9.5) |
| D2 | XGSI One UI 9.5 `64_32`, `SM-S948B` / `m3q`, `S948BXXU6ZZKN` | https://t.me/xgsiupdates/233 | **Selected GSI 9.5 system base** (Android 17 / SDK 37.2) |
| D3 | XGSI One UI 9.0 `64_32`, Tab S12 Ultra `SM-X946N`, board `mt6993` | https://t.me/xgsiupdates/209 | Tablet configuration reference only (not 9.5; different platform) |
| D4 | XGSI One UI 9.0 `64_32`, `SM-F971B` / `h8q` | https://t.me/xgsiupdates/201 | Large-screen/foldable configuration reference only |

Download references for D2: https://pixeldrain.com/u/TsrGCVBL and https://t.me/xgsimirror/15.

## Planned Workspace Structure

```text
inputs/                 Original packages, read-only; never commit binaries
  baseline-pipa/
  donors/
work/                   Extraction and per-candidate experiments (gitignored)
inventory/              Checksums, image metadata, partition & filesystem manifests (gitignored)
reports/                Audits and local logs (only reports/CHECKPOINT.md is tracked)
patches/                Tracked kernel/system patches with provenance
scripts/                Inventory, diff, repack, relayout, and validation tooling
artifacts/              Output images and checksums (gitignored)
logs/                   Boot logs and hardware tests, sanitized (gitignored)
```

## Phase 0 — Package Intake and Readiness

- [x] Record original filenames, sources, byte sizes, and SHA-256 checksums.
- [x] Keep original archives unmodified; extract only into isolated candidate workspaces.
- [x] Record baseline notes (One UI/Android version, vendor/firmware base, kernel, known bugs, SELinux state).
- [x] Verify host disk space, filesystems, and required host tools from actual archive formats.
- [x] Audit archives pre-extraction (reject path traversal / dangerous symlinks; never execute package installers).

**Gate 0:** `B0` and at least one donor present, checksums logged, extraction capacity verified.

## Phase 1 — Reproducible Extraction and Inventory

- [x] Identify container/filesystem formats (sparse/raw ext4, EROFS, LP dynamic partitions, boot v3/v4).
- [x] Record extractor versions and reproducible CLI commands.
- [x] Inventory partitions present vs absent across packages.
- [x] Record exact image sizes, LP groups, and capacity limits.
- [x] Extract build properties from `system`, `system_ext`, `product`, `vendor`, and `odm`.
- [x] Cross-check Android version, SDK, fingerprint, SPL, and One UI properties against distributor claims.
- [x] Inventory APKs/APEXes/JARs, native libraries, ABIs, symlinks, permissions, SELinux contexts, init, and fstab.

**Gate 1:** Package identity and partition scope verified from binaries.

## Phase 2 — Understanding the `pipa` Baseline

- [x] Map component origins: Samsung userspace, `pipa` vendor/ODM, boot/kernel (`4.19.246-N0-kernel+`), DTBO.
- [x] Identify device-specific patches in init, properties, fstab, VINTF, SELinux, overlays, native binaries (`btaudio-hal-xiima`, `xiaomi-touch`, `auto_audio_switch.sh`).
- [x] Record display, density (`280`), audio routing, pen/keyboard, and baseline known bugs.

**Gate 2:** `pipa` hardware components and boot dependencies mapped.

## Phase 3 — Donor Compatibility Matrix

Audited `D2` against `B0`:

| Area | Check | Outcome / Findings |
| --- | --- | --- |
| Framework ↔ Vendor | VINTF manifests/matrices, FCM levels, HAL clients, VNDK (`v30..v34`) | All required HAL clients present; vendor FCM level 5 vs donor level 7+ non-fatal at boot |
| Native / ABI | ELF architectures, shared library dependencies | `64_32` verified; overlay binaries link cleanly |
| Kernel ↔ Userspace | Kernel 4.19.246 config, BPF, EROFS, cgroups | Required fixes [0001](patches/0001-port95-erofs-fill_symlink-read-inline-data-from-next-block.patch)–[0003](patches/0003-port95-erofs-use-C-LZ4-decoder-instead-of-lz4armv8-inplace.patch); `traced` cgroup `+memory` fails on 4.19 |
| Graphics | Composer 2.4, Mapper 3.0/4.0, EGL/Vulkan, SurfaceFlinger | Boots to UI cleanly (`D2` `gralloc4` adaptation compatible with `B0` vendor) |
| Boot / Init | `vendor_boot` fstab, first-stage mount, encryption, AVB | Boots with `/data` unencrypted `f2fs`; `vold` `/data/sec_pass/0` FBE errors non-fatal |
| SELinux | Split policy compile (`secilc`), runtime mode | Boots in `Permissive`; all-domain permissive CIL appended offline |
| Samsung Services | Knox, Device Care (`lool`), Camera/Clock/Gallery/Routines | `D2` stripped several apps (`lool`, `routines`, `forest`, `clockpackage`, `camera`) → Settings/Menu gaps |
| Tablet UX | Characteristics, density, lockscreen rotation, QS width, SIM UI | Still configured as `phone` / `213dpi` in `D2`; needs tablet UX patching |
| Packaging | Live `super` LP layout vs `system_a`/`vendor_a`/`odm_a` sizes | Re-laid out `qti_dynamic_partitions_a` cleanly while leaving `_b` & `sda35` untouched |

**Gate 3:** Blockers, reusable patches, and runtime verification items documented.

## Phase 4 — Port Path Decision

Compared options:
1. **Tablet firmware `D1` → `pipa`:** One UI 9.0, does not meet One UI 9.5 target; no GSI patches.
2. **XGSI `D2` → `pipa`:** One UI 9.5 (`64_32`, Android 17), boots on `pipa` kernel/vendor after EROFS/BPF kernel fixes; requires tablet UX & missing Samsung package restoration (unless a tablet One UI 9.5 `64_32` XGSI becomes available).

**Gate 4:** `D2` explicitly selected as initial system base.

## Phase 5 — Implementation and Offline Validation

- [x] Built reproducible offline tooling (`scripts/port95_build.py`, `scripts/erofs95.py`, `scripts/erofs95_repro.py`, `scripts/lprelayout.py`, `scripts/backup_slot_a_boot.sh`, `scripts/flashplan.py`, `scripts/sepolicy_permissive.py`).
- [x] Applied tracked kernel patches (`0001`–`0003`) and incremental overlays (`reports/port95/README.md`, `reports/port95/bpf-backport/README.md`).
- [x] Preserved permissions, ownership, symlinks, and SELinux contexts during EROFS `v1.8.9` repack (`metadata+content identical`, `fsck.erofs rc=0`, 689/689 domains permissive).
- [x] Validated per-partition live `pipa` Slot A sizes and built Slot A LP re-layout validator (`scripts/lprelayout.py`) protecting GPT, `sda34`, `sda35`, and Slot B.
- [x] Generated Gate 5 offline verification manifest (`reports/port95/gate5-slot-a-manifest.json`, local only).

**Gate 5:** Artifacts passed offline validation with explicit rollback procedure (`B0` Slot A images).

## Phase 6 — Device Test Preparation (Approval Required)

- [x] Confirmed device identity (`pipa`, `78589d57`), unlocked bootloader, Slot A active, live partition/LP layout dumped.
- [x] Backed up live Slot A boot partitions externally (`Boot Attempt 1–3`).
- [x] Prepared `B0` Slot A rollback path without touching Slot B, `/dev/sda35` Linux, GPT, or bootloader firmware.
- [x] Verified logging paths (Wireless ADB, `logcat`, `dmesg`, `pstore` / `console-ramoops-0`).

**Forbidden:** Never flash bootloader/hardware firmware, overwrite Slot B (`*_b`) or `/dev/sda35`, relock the bootloader, or wipe `userdata`/`metadata` unless explicitly authorized.

**Gate 6:** User explicitly approved Slot A bundle flash with backups and rollback path ready.

## Phase 7 — Bring-up and Regression Testing

Milestones:

- [x] **M1:** Kernel/init boots, all partitions mount, boot logs collected.
- [x] **M2:** Zygote, SurfaceFlinger, and `system_server` run stably to boot completion (`sys.boot_completed=1`, `bpf.progs_loaded=1`, `0` EROFS errors).
- [x] **M3:** Display/SurfaceFlinger/SystemUI/Launcher render (`1800x2880`); touch input and Wireless ADB (`uid=0`) work.
- [ ] **M4:** Setup, storage/Settings menus (`com.samsung.android.lool`), USB ADB (`host_connected`), and clean daemon state (`traced` crash-loop resolved, `vold`/RIL noise reduced).
- [ ] **M5:** Hardware and tablet UX parity check against `B0`:
  - **Display & Tablet UX:** `ro.build.characteristics=tablet`, `ro.sf.lcd_density=280` (currently `213`), lockscreen landscape orientation, Quick Settings & Notification panel tablet width, `About tablet` & Wi-Fi-only identity (no `Available SIM` / `IMEI Unknown` / `Phone` icon), `floating_feature` cleanup (remove `S948B` punchhole/ultrasonic-FP/edge flags).
  - **Audio:** quad Awinic speakers (`aw882xx` active), mic, Bluetooth audio (`btaudio-hal-xiima`), and output routing (`auto_audio_switch.sh`).
  - **Wi-Fi / Bluetooth:** `wlan0` (`v5.2.022.12B`) active; verify Bluetooth pairing persistence across sleep/reboot.
  - **Camera:** verify front/rear camera HALs & add compatible Camera/Gallery apps if stripped by donor.
  - **Input:** touch (`NVT-ts`), hardware keys, pen (`switch_pen_input_device` / Mi Smart Pen), keyboard nanoapp, hall sensor, auto-rotate (`sensors@1.0-service` active).
  - **Power:** charging, battery telemetry (`healthd`), deep sleep, wake, and thermals.
  - **USB:** fix `xgsi-usb.rc` / USB HAL sync so wired ADB (`adb -d`) & MTP work (`host_connected=false` in Attempt 3).
  - **Security:** actual SELinux mode (`Permissive`), encryption status (`noenc` `/data`), SukiSU root binary (`su` availability vs ADB root).
- [ ] **M6:** Stability, sleep/wake cycling, idle battery drain, and thermal testing.

Every check must be labeled **PASS / FAIL / NOT TESTED / NOT APPLICABLE** with artifact SHA-256, reproduction steps, and logs.

## Phase 8 — Reproducible Package and Handoff

- [ ] Rebuild cleanly from documented inputs, overlays, patches, and scripts.
- [ ] Publish complete input/output manifest, SHA-256 checksums, and `pipa` Slot-A-only flash/rollback instructions.
- [ ] Document vendor/kernel prerequisites, known bugs, and recovery steps.
- [ ] Attribute upstream patches/credits (`N0+`, `SukiSU`, `XGSI`, `btaudio-xiima`, etc.).
- [ ] Clearly label build maturity (`experimental`, `bootable`, or `daily-driver`) from verified test results only.

## Definition of Done

### Audit Complete
`B0` and donor inventories captured, baseline integration mapped, compatibility matrix and donor decision documented, open blockers recorded.

### Experimental Port Complete
Reproducible artifacts built, tested on real `pipa` hardware with user approval, hardware/UX regression results recorded with verified logs, and rollback steps documented.

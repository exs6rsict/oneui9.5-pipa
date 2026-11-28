# One UI 9.5 for Xiaomi Pad 6 (`pipa`)

Audit and porting project for One UI 9.5 compatible with Xiaomi Pad 6 (codename `pipa`), preserving dual-boot Linux on `/dev/sda35` and Slot B untouched.

> **Status (2026-11-28): Gate 6 Boot Attempt 3 SUCCEEDED — booted to the One UI 9.5 UI on `pipa` Slot A (`M1–M3` complete; `M4–M5` post-boot bugfixing active).**
> `boot_a.img` (`6fb3aba4...`, `4.19.246-N0-kernel+` + SukiSU builtin + patches [0001](patches/0001-port95-erofs-fill_symlink-read-inline-data-from-next-block.patch), [0002](patches/0002-port95-bpf-allow-bpf_get_netns_cookie-in-sock_ops-and-cgroup_sockopt.patch), [0003](patches/0003-port95-erofs-use-C-LZ4-decoder-instead-of-lz4armv8-inplace.patch)) resolved the earlier EROFS `erofs_fill_symlink`, `netbpfload` (`bpf_get_netns_cookie`), and `lz4armv8` `-3901` failures (`0` EROFS errors in `dmesg-boot3.txt`, `bpf.progs_loaded=1`, `sys.boot_completed=1`, `Permissive`, `/data` f2fs `rw`). Wi-Fi (`wlan0`), Wireless ADB (`uid=0(root)` `u:r:su:s0`), quad Awinic audio, `[NVT-ts]` touch, and accelerometer (`sensors@1.0-service`) are active.
> **Open M4–M5 bugs under investigation:** phone UX instead of tablet UX (`ro.build.characteristics=phone`, `213dpi`, sideways lockscreen rotation, narrow centered Quick Settings/Notification panel), stripped Samsung apps (`Package not found : com.samsung.android.lool` causing missing `Device care`/`Battery` and `Storage` → *"Menu not currently available."*), `traced` 5s crash-loop (`cgroup +memory` `EINVAL`), `vold`/`FsCrypt` errors, RIL/lazy-AIDL log spam, and USB ADB (`host_connected=false`). Never touch Slot B (`*_b`), `/dev/sda35`, GPT, or bootloader firmware.
> **Staged, offline-verified, NOT YET FLASHED (2026-11-29):**
> - **Option B (M4–M5 fixes):** `artifacts/port95-option-b/system_a.img` (`4,700,540,928` B, SHA-256 `b555d6a9...`, EROFS `metadata+content identical`, `fsck.erofs rc=0`) and the runtime-only SukiSU test module `artifacts/option-b-test-module/port95_optionb-v1-test.zip` (`2655bcd8...`; tablet props/`280dpi`, B0 tablet RROs, Device Care/Routines/DigitalWellbeing/SecondScreen/Gallery/Aperture APKs excluding stock Samsung Camera, `traced` off).
> - **SukiSU Manager App Profile fix:** `TemporaryRoot.saveProfile` runs `libksud.so temporary-root apply`, which gets its `[ksu_driver]` FD via `syscall(SYS_reboot, 0xDEADBEEF, 0xCAFEBABE, 0, &fd)`; N0 `kernel/reboot.c` never called `ksu_handle_sys_reboot`, so the call failed. Fixed by `recipe/0004-port95-reboot-add-ksu_handle_sys_reboot-hook.patch` → candidate `boot_a-n0-sukisu-bpf-vgate-ksureboot.img` (`201,326,592` B, `39247cd7...`; same ramdisk/header/cmdline/AVB salt as Attempt 3, kernel only differs).
> - **Diagnostic Log Collector APK:** `tools/log-reporter/` → `artifacts/log-reporter/OneUI95-LogReporter.apk` (`20,883` B, `com.pipa.port95.logreporter`, v1+v2+v3 signed; collects `logcat`, `dmesg`, `pstore`, props, mounts, USB/thermal sysfs, packages/overlays, and `dumpsys` into one shareable `.zip`).

## Target

- **Device:** Xiaomi Pad 6 (`pipa`), dual-boot Slot A (`*_a`) while preserving `/dev/sda35` Linux and Slot B (`*_b`).
- **OS target:** One UI 9.5 (Android 17 / SDK 37.2). One UI 9.0 is neither the target nor a fallback.
- **Approach:** Audit a working `pipa` One UI port baseline (`B0`) against the donor (`D2`), then apply small, verifiable integration layers with offline checks before device testing.

## Donor Candidates

| ID | Candidate | Role | Status |
| --- | --- | --- | --- |
| B0 | Port One UI 8.0 `pipa` (`oneui_8.0_gts9u_port_pipa_decrypted_20260816.zip`) | Hardware/integration baseline (`vendor`, `odm`, `product`, `system_ext`, `vendor_boot`, `dtbo`, kernel tree) | **Available & verified** (`inputs/baseline-pipa/`) |
| D1 | Tab S9+ `SM-X810` firmware (`X810XXU6FZK2`) | Tablet firmware reference | Not selected (One UI 9.0, not 9.5) |
| D2 | XGSI One UI 9.5 `64_32` (`SM-S948B` / `S948BXXU6ZZKN`, Android 17 / SDK 37.2) | **Primary GSI 9.5 system base** | **Selected, booted on Slot A** (`inputs/donors/`) |
| D3, D4 | XGSI One UI 9.0 (`SM-X946N`, `SM-F971B`) | Large-screen configuration reference only | Optional (not 9.5) |

Full phases, gates, and sources are documented in [ROADMAP.md](ROADMAP.md). Summaries in Git are tracked in [reports/CHECKPOINT.md](reports/CHECKPOINT.md) *(other `reports/port95/` files stay local and gitignored)*:
- [reports/CHECKPOINT.md](reports/CHECKPOINT.md) — main development checkpoint, Boot Attempt 1–3 timeline, and dual-boot safety contract
- `reports/port95/README.md` *(local only, `/reports/*` is gitignored)* — `B0` + `D2` offline integration audit
- `reports/port95/bpf-backport/README.md` *(local only)* — BPF `bpf_for_each_map_elem` + `vgate` backport and arm64 QEMU testing
- `reports/port95/dualboot/README.md` *(local only)* — dual-boot contract, permissive SELinux policy, and live layout dumps

## Repository Layout

| Path | Purpose |
| --- | --- |
| [ROADMAP.md](ROADMAP.md) | Phases 0–8, gates, bring-up checklists, and definition of done |
| [reports/CHECKPOINT.md](reports/CHECKPOINT.md) | Tracked engineering checkpoint & safety contract |
| `patches/` | Version-controlled kernel patches ([0001](patches/0001-port95-erofs-fill_symlink-read-inline-data-from-next-block.patch), [0002](patches/0002-port95-bpf-allow-bpf_get_netns_cookie-in-sock_ops-and-cgroup_sockopt.patch), [0003](patches/0003-port95-erofs-use-C-LZ4-decoder-instead-of-lz4armv8-inplace.patch)) |
| `scripts/`, `tests/` | Offline audit, APK compat, EROFS/sparse/LP relayout, SELinux permissive, and backup tooling + `unittest` suite |
| `tools/log-reporter/` | Standalone Android APK source & VPS build script for full on-device diagnostic log `.zip` collection |

Working directories (`inputs/`, `work/`, `inventory/`, `reports/`, `artifacts/`, `logs/`) are created as needed and gitignored. Never commit ROM archives, extracted images, flash bundles, or raw device logs.

## Workflow

1. **Phases 0–3 (offline):** Intake packages with checksums, extract & inventory partitions, map `pipa` baseline integration, build compatibility matrix.
2. **Phase 4:** Explicitly select one donor path (`D2`).
3. **Phase 5:** Reproducible patching, EROFS repack, kernel rebuild, and offline verification.
4. **Phase 6 (requires explicit approval):** Backups, Slot A LP re-layout validation, and recovery path before any device write.
5. **Phase 7–8:** Iterative hardware/UX bring-up (`M1–M6`) and reproducible handoff package.

## Safety Rules

- Audits are strictly read-only. Download, extraction, image modification, and flashing are separate stages.
- Never run vendor/community flash or recovery installer scripts verbatim.
- Never touch Slot B (`*_b`), `/dev/sda35` (Linux), GPT partition tables, `userdata`/`metadata`, or Samsung/bootloader firmware partitions.
- Never relock the bootloader or alter AVB/encryption state without explicit approval.
- Flashing happens only after Gate 6 approval with exact artifact hashes, partitions, and verified rollback images.

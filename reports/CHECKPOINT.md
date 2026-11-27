# One UI 9.5 `pipa` — Engineering Checkpoint

## Status (2026-11-28)

Offline audit tooling, image assembly, BPF + `vgate` (`5.15.136`) backports, EROFS `v1.8.9` repack, and Gate 6 Slot A preparation (`scripts/lprelayout.py`, `scripts/backup_slot_a_boot.sh`) completed, followed by three Gate 6 hardware boot attempts on `pipa` Slot A:

- **Boot Attempt 1:** Kernel (`4.19.246-N0-kernel+`) and `init` booted, halted on `erofs_fill_symlink` `-EFSCORRUPTED` for 32-byte compact inline symlinks at block offset `4064` (`nid 767` `/system_ext`). Fixed in [0001](patches/0001-port95-erofs-fill_symlink-read-inline-data-from-next-block.patch).
- **Boot Attempt 2 (`7a179ab1...`):** Passed `erofs_fill_symlink`, halted on `netbpfload` missing BPF helper `#122` (`bpf_get_netns_cookie`) for `netd.o` `$5_15` programs and EROFS `lz4armv8` `-3901 in[4096, 0] out[4492]`. Fixed in [0002](patches/0002-port95-bpf-allow-bpf_get_netns_cookie-in-sock_ops-and-cgroup_sockopt.patch) and [0003](patches/0003-port95-erofs-use-C-LZ4-decoder-instead-of-lz4armv8-inplace.patch), compiled on VPS (`gate6fix`), and passed arm64 QEMU testing (`netbpfload` → `uprobestatsbpfload` → `/system/bin/bpfloader` exit `rc=0`, `bpf.progs_loaded=1`, 181 bpffs entries, and full EROFS slice readback without `-3901`).
- **Boot Attempt 3 (`boot_a.img` `6fb3aba47f1ddc5840c0ebd5820f612da4bf6a1a420c27aa4a5e7ac4401ba1d6`, `201,326,592` B) — BOOTED TO ONE UI 9.5 UI ON `pipa` (`M1–M3` PASS):**
  - Verified on hardware (`boot-attempt-3-logs/boot/status.txt`, `dmesg-boot3.txt`, `logcat-boot3.txt`): `CP4A.261205.008.S948BXXU6ZZKN.XGSI`, One UI `90500` (Android 17 / SDK 37.2), `sys.boot_completed=1`, `bpf.progs_loaded=1`, `0` EROFS errors in 2 MB `dmesg-boot3.txt`, `Zygote` & `SurfaceFlinger` running (`system_server` PID `2098`), `getenforce=Permissive`, `/dev/block/sda34 /data f2fs rw` (unencrypted), Wireless ADB shell `uid=0(root)` (`u:r:su:s0`), `wlan0` (`v5.2.022.12B`), quad Awinic `aw882xx` audio (`kona-mtp-snd-card`), `[NVT-ts]` touch/pen switch, and `sensors@1.0-service` accelerometer active.
- **Post-boot M4–M5 bugs identified (`report one ui/` screenshots + `logcat-boot3.txt`):**
  1. **Missing Settings menus (`Device care`, `Battery`, `Storage`, `Modes and Routines`, `Digital Wellbeing`)**: `logcat-boot3.txt` shows `Settings: Package not found : com.samsung.android.lool` because `SmartManager` (`com.samsung.android.lool`) and several Samsung apps (`Routines`, `DigitalWellbeing`, `ClockPackage`, `SamsungCamera`, `SamsungGallery2018`) were stripped from the `D2` XGSI base (`Menu not currently available.` toast when opening `Storage` via Search).
  2. **Phone UX & DPI mismatch**: `/system/build.prop` still sets `ro.build.characteristics=phone`, `SM-S948B`, `ro.ims.device_category=phone`, phone `floating_feature.xml` entries (`ultrasonic_display_phone`, `PUNCHHOLE_VI`, `COMMON_CONFIG_EDGE=panel`), and lacks `ro.sf.lcd_density=280` (running at `213dpi`). This causes sideways/portrait Lock screen (`KeyguardClockPositionManager: error size mismatch size=2880.0x1800.0`, `KeyguardClockInteractor: No clock is available`), narrow centered Quick Settings & Notification panel, and `About phone` / `Available SIM` / `IMEI Unknown` / `Phone` icon.
  3. **Daemon / service noise**: `traced` 5s crash-loop (`Activation of cgroup controller +memory failed in path /sys/fs/cgroup/system/uid_9999: Invalid argument` triggering `UPDATABLE_CRASHING`), `vold` (`FsCrypt: Failed to prepare /data/sec_pass/0`, `cryptfs init_user0 Failed: Status(-8)`, 656x `Open failed`), RIL/lazy-AIDL polling spam (`ISehChannel/imsd`, `ISehRealTimeToken`, `ISehWidevineKeyProv`, `ISehSem`, `KNOXNATIVE`), and wired USB ADB `host_connected=false` despite `kernel_state=CONFIGURED`.

Binary artifacts, Flash bundles, and extracted ROM trees remain excluded from Git.

## Inputs

- **Baseline (`B0`):** One UI 8.0 `pipa` port (`oneui_8.0_gts9u_port_pipa_decrypted_20260816.zip`, `SM-X910`, `ro.build.characteristics=tablet`, `ro.sf.lcd_density=280`), sourced from https://t.me/XiaomiPad6Global/394100 .
- **Donor (`D2`):** One UI 9.5 XGSI (`XGSI_SM-S948B_S948BXXU6ZZKN_arm64.zip`, `SM-S948B`, Android 17 / SDK 37.2, `oneui=90500`), sourced from https://t.me/xgsiupdates/233 .
- **Kernel & Root:** `4.19.246-N0-kernel+` with `SukiSU` `builtin` (`adf6e86d55229ad78a5f7758bdc43d92fd1c3729` from https://git.zako.shirkneko.top:20004/shirkneko/SukiSU), `CONFIG_KSU=y`, `CONFIG_KSU_FEATURE_ADBROOT=y`. Wireless `adb shell` runs as `uid=0` (`u:r:su:s0`); standalone `su` binary not yet present in `$PATH`.

## Tooling

- `scripts/zipaudit.py`: Bounded ZIP inventory, path/duplication/symlink checks, and inventory diffs.
- `scripts/sparselp.py`: Streaming Android sparse decode and LP partition extraction.
- `scripts/fsmeta.py`: Offline ext4/EROFS metadata & allowlist inspection via userspace readers.
- `scripts/port95_build.py`: Experimental ext4 overlay/prop builder with readback and LP round-trip hash verification.
- `scripts/sepolicy_permissive.py`: Offline all-domain permissive CIL policy generator and `secilc` check.
- `scripts/erofs95.py` / `scripts/erofs95_repro.py`: ext4-to-EROFS PAX repack, independent decode verification (`erofs-utils 1.8.9+`), and diskbuf offset regression reproducer.
- `scripts/lprelayout.py`: Slot A LP re-layout validator preserving GPT, `/dev/sda34`, `/dev/sda35`, Slot B, and LP headers.
- `scripts/backup_slot_a_boot.sh` / `scripts/dump_live_layout.sh` / `scripts/flashplan.py`: Read-only backup helpers and A-only flash plan validator.

Test execution with local EROFS tools in `PATH` (`tests/`, 58 tests verified prior to Attempt 3 docs sync):

```sh
PATH="$PWD/work/port95/tools/root/usr/bin:$PATH" \
  python3 -I -W error::ResourceWarning -m unittest discover -s tests -v
```

External host dependencies include `android-tools`, `e2fsprogs`, `erofs-utils`, `secilc`, and `checkpolicy`. Local binary tools under `work/` are excluded from Git.

## Dual-Boot Safety Contract

Active Linux resides on `/dev/sda35` and must remain untouched alongside **all of Slot B (`*_b`)**. Note that `super` (`/dev/sda29`) is a shared dynamic-partition container: overwriting raw `super` can clobber Slot B metadata/extents even when flashing `_a` images.

- Never run baseline fastboot/recovery installer scripts verbatim (many write both slots and hardware firmware).
- Never write block devices, GPT headers, `/dev/sda35` Linux, Slot B (`*_b`), `userdata`/`metadata`, or bootloader firmware.
- Never resize/delete Slot B partitions, switch active slot to `_b`, or relock the bootloader.
- Keep verified external backups of Slot A partitions and live GPT/LP dumps before any device write.
- Require explicit Gate 6 approval citing exact target partitions and artifact SHA-256 hashes.
- Legacy full `super.img` experimental builds remain **NOT APPROVED FOR DUAL BOOT**.

## Open Technical Work Items (M4–M5)

1. **Tablet UX & Display Scaling:** Override `ro.build.characteristics=tablet`, `ro.sf.lcd_density=280`, Wi-Fi tablet identity/model (`SM-X910` / remove phone/SIM/IMEI/punchhole/edge entries from `build.prop` and `floating_feature.xml`), and enable tablet Lockscreen rotation & Quick Settings width.
2. **Restoring Stripped One UI 9.5 Packages:** Supply compatible One UI 9.5 (`SDK 37`) `com.samsung.android.lool` (Device Care) to restore `Device care`, `Battery`, and `Storage`, plus `Clock`, `Camera`, `Gallery`, `Routines`, and `DigitalWellbeing` as needed. (Alternatively rebase `system_a` onto a tablet One UI 9.5 `64_32` XGSI if available.)
3. **System Daemons & Wired USB ADB:** Disable/fix `traced` cgroup `+memory` crash-loop (`persist.traced.enable=0` or init override), quiet `vold`/`FsCrypt` and telephony/lazy-AIDL polling spam on Wi-Fi hardware, and reconcile `xgsi-usb.rc` with QTI USB HAL so wired `adb -d` reports `host_connected=true`.

## EROFS Tooling History

`scripts/erofs95.py` scans ext4 with read-only `debugfs`, emits a PAX tar preserving UID/GID/mode/xattr/capabilities/symlinks, and verifies content hashes and metadata via an independent reader plus `fsck.erofs`. Earlier builds with `erofs-utils 1.7.1` hit an `int` `lseek` truncation bug causing 751 of 6,972 files to lose compressed data (`scripts/erofs95_repro.py`); upgrading to `erofs-utils 1.8.9+` eliminated all content loss (`metadata+content identical`, `fsck.erofs rc=0`), and combining it with kernel patch [0003](patches/0003-port95-erofs-use-C-LZ4-decoder-instead-of-lz4armv8-inplace.patch) produced zero EROFS errors on real `pipa` hardware in Boot Attempt 3. `scripts/erofs95_run.sh` remains untracked as a workspace/VPS runner helper.

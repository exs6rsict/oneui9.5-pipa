# OneUI95 Log Reporter

Tiny APK (`com.pipa.port95.logreporter`, ~20 KB, minSdk 23 / targetSdk 29) that gathers every diagnostic
log from the pipa One UI 9.5 port into one shareable zip. It has no Gradle and no AndroidX: only framework
classes and `java.util.zip`.

## Use on the tablet

1. Install `OneUI95-LogReporter.apk` (sideload it by hand; no build script touches a device).
2. Tap **Kumpulkan Semua Log (.zip)**. Grant root in SukiSU when asked. Without root it still runs through
   `sh -c` and records which commands were denied.
3. The zip `pipa-oneui95-logs-YYYYMMDD-HHMMSS.zip` is written to
   `/sdcard/Android/data/com.pipa.port95.logreporter/files/`. With root it is also copied to `/sdcard/Download/`.
4. **Bagikan ZIP (Share)** sends the newest zip to Telegram, Files, etc. through a read-only `content://` URI.
   **Simpan Ke... (Downloads/USB)** saves it anywhere through the system file picker. Neither needs a
   storage permission.

## Zip contents

| Entry | Source |
|---|---|
| `00_summary.txt` | UTC and local time, su probe exit code and output, `id`, `uname -a`, `getenforce`, key props, `ksud --version`, Boot Control package/UID |
| `01_logcat_all.txt`, `02_logcat_errors.txt` | `logcat -b all -d -v threadtime` (all, and `*:E`) |
| `03_dmesg.txt` | `dmesg -T`, falling back to `dmesg` |
| `04_pstore_last_kmsg.txt` | `/sys/fs/pstore/*`, `/proc/last_kmsg` |
| `05_avc_ksu_bpf_erofs.txt` | dmesg filtered for `avc:\|denied\|sukisu\|ksu\|erofs\|bpf\|traced`, plus logcat AVCs |
| `06_getprop.txt` | `getprop` |
| `07_mounts_selinux_ksu.txt` | `/proc/mounts`, own SELinux context, `ls -la` of `/data/adb`, `ksu`, `temporary-root`, `modules*` (listings only, never file contents such as `state.key`) |
| `08_usb_battery_thermals.txt` | `/config/usb_gadget` tree and values, `/sys/class/power_supply/*`, `thermal_zone*` |
| `09_ps_services.txt` | `ps -A`, `init.svc.*` props, `service list` |
| `10_packages_rro_display.txt` | `pm list packages -f -U`, `cmd overlay list`, `wm size`, `wm density` |
| `11_dumpsys.txt` | `dumpsys` activity crashes, dropbox, usb, battery, display, window displays, activity top |

Each command appears as `===== $ <cmd>` followed by its output and `----- exit=<code>`. Each command has a
90 s timeout (exit 124 means it timed out).

## Build (on pipa-jakarta-vps)

```sh
rsync -a --delete tools/log-reporter/ pipa-jakarta-vps:oneui9.5-pipa/log-reporter-build/src/
ssh pipa-jakarta-vps 'bash ~/oneui9.5-pipa/log-reporter-build/src/build_vps.sh'
scp pipa-jakarta-vps:oneui9.5-pipa/log-reporter-build/out/{OneUI95-LogReporter.apk,SHA256SUMS} artifacts/log-reporter/
```

The script runs JDK 17 `javac` (Java 8 bytecode against `android-23/android.jar`), then `dalvik-exchange`
(Android dx 1.16; `/usr/bin/dx` on that host is the unrelated OpenDX), `aapt`, and `apksigner` (v1+v2+v3).
It verifies the result with `apksigner verify`, `aapt dump badging`, a required-entries check and a size
limit under 1 MiB. Last, it smoke-tests `LogCollector` on the host JVM. The signing key and its password
are created once under `~/oneui9.5-pipa/log-reporter-build/keystore/` and stay on the VPS. Keep that
folder, because updates must be signed with the same key.

Offline checks: `python3 -m unittest tests.test_log_reporter -v` (set `LOG_REPORTER_APK=<path>` to also
check a built APK).

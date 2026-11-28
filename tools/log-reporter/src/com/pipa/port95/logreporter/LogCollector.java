package com.pipa.port95.logreporter;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * Runs every diagnostic command through {@code su -c} (or {@code sh -c} when root is not granted) and
 * streams each section straight into one zip. Uses only java.* so build_vps.sh can smoke-test it on the
 * host JVM.
 */
final class LogCollector {

    /** Receives one human-readable progress line per step, on the collector's thread. */
    interface Listener {
        void status(String line);
    }

    static final String ZIP_PREFIX = "pipa-oneui95-logs-";
    static final String DOWNLOAD_DIR = "/sdcard/Download/";
    /** Per command, so one hung dumpsys cannot stall the whole collection. */
    static final int CMD_TIMEOUT_S = 90;

    /** Zip entry name followed by its commands; each runs on its own so every exit code is recorded. */
    static final String[][] SECTIONS = {
        {"00_summary.txt", "date -u", "date", "id", "uname -a", "getenforce",
            "getprop ro.build.fingerprint", "getprop ro.build.characteristics", "getprop ro.sf.lcd_density",
            "getprop ro.carrier", "getprop sys.usb.config", "getprop persist.sys.usb.config",
            "getprop persist.traced.enable", "getprop traced.relay_producer_port",
            "for k in /data/adb/ksud $(command -v ksud); do [ -x \"$k\" ] && echo \"$k: $(\"$k\" --version 2>&1)\"; done",
            "pm list packages -U | grep -iE 'boot.?control'"},
        {"01_logcat_all.txt", "logcat -b all -d -v threadtime"},
        {"02_logcat_errors.txt", "logcat -b all -d -v threadtime '*:E'"},
        {"03_dmesg.txt", "dmesg -T || dmesg"},
        {"04_pstore_last_kmsg.txt", "ls -la /sys/fs/pstore", dumpFiles("/sys/fs/pstore/*", ""),
            "cat /proc/last_kmsg"},
        {"05_avc_ksu_bpf_erofs.txt", "dmesg | grep -iE 'avc:|denied|sukisu|ksu|erofs|bpf|traced'",
            "logcat -b all -d -v threadtime | grep -iE 'avc:|denied'"},
        {"06_getprop.txt", "getprop"},
        // Directory listings only: never cat anything under /data/adb (state.key and friends are secrets).
        {"07_mounts_selinux_ksu.txt", "cat /proc/mounts", "cat /proc/self/attr/current",
            "ls -la /data/adb /data/adb/ksu /data/adb/ksu/temporary-root /data/adb/modules*"},
        {"08_usb_battery_thermals.txt", "ls -laR /config/usb_gadget",
            dumpFiles("$(find /config/usb_gadget -type f 2>/dev/null)", " | head -c 4096"),
            dumpFiles("/sys/class/power_supply/*/*", ""),
            dumpFiles("/sys/class/thermal/thermal_zone*/*", "")},
        {"09_ps_services.txt", "ps -A", "getprop | grep init.svc", "service list"},
        {"10_packages_rro_display.txt", "pm list packages -f -U", "cmd overlay list", "wm size", "wm density"},
        {"11_dumpsys.txt", "dumpsys activity crashes", "dumpsys dropbox --print", "dumpsys usb",
            "dumpsys battery", "dumpsys display", "dumpsys window displays", "dumpsys activity top"},
    };

    private final File dir;
    private final Listener listener;

    LogCollector(File dir, Listener listener) {
        this.dir = dir;
        this.listener = listener;
    }

    /** Collects every section into a new timestamped zip in {@code dir} and returns it. */
    File collect() throws IOException, InterruptedException {
        Date now = new Date();
        File zip = new File(dir, ZIP_PREFIX + format("yyyyMMdd-HHmmss", now, TimeZone.getDefault()) + ".zip");

        listener.status("Cek root: su -c id (setujui di SukiSU bila diminta)...");
        ByteArrayOutputStream probeOut = new ByteArrayOutputStream();
        int probe = runOrFail(true, "id", probeOut);
        boolean root = probe == 0 && probeOut.toString("UTF-8").contains("uid=0");
        String shell = root ? "su" : "sh";
        listener.status(root ? "Root OK, memakai su -c" : "Tanpa root (su exit=" + probe + "), memakai sh -c");

        ZipOutputStream zos = new ZipOutputStream(new FileOutputStream(zip));
        try {
            for (int i = 0; i < SECTIONS.length; i++) {
                String[] section = SECTIONS[i];
                listener.status("[" + (i + 1) + "/" + SECTIONS.length + "] " + section[0]);
                zos.putNextEntry(new ZipEntry(section[0]));
                if (i == 0) {
                    write(zos, "OneUI95 Log Reporter\ncollected_utc=" + format("yyyy-MM-dd HH:mm:ss 'UTC'", now,
                        TimeZone.getTimeZone("UTC")) + "\ncollected_local=" + format("yyyy-MM-dd HH:mm:ss zzz",
                        now, TimeZone.getDefault()) + "\nsu_probe_exit=" + probe + "\nsu_granted=" + root
                        + "\nshell=" + shell + " -c\nsu_probe_output=" + probeOut.toString("UTF-8").trim() + "\n\n");
                }
                write(zos, "===== collector: shell=" + shell + " exit=" + runOrFail(root, script(section), zos) + "\n");
                zos.closeEntry();
            }
        } finally {
            zos.close();
        }
        listener.status("ZIP: " + zip + " (" + zip.length() / 1024 + " KiB)");

        if (root) {
            int rc = runOrFail(true, "cp " + quote(zip.getPath()) + " " + DOWNLOAD_DIR, new ByteArrayOutputStream());
            listener.status(rc == 0 ? "Disalin ke " + DOWNLOAD_DIR + zip.getName()
                : "Gagal menyalin ke " + DOWNLOAD_DIR + " (exit=" + rc + ")");
        }
        return zip;
    }

    /** Shell loop printing {@code path=value} for every readable regular file matched by {@code glob}. */
    static String dumpFiles(String glob, String filter) {
        return "for f in " + glob + "; do [ -f \"$f\" ] && [ -r \"$f\" ] && echo \"$f=$(cat \"$f\" 2>/dev/null"
            + filter + ")\"; done";
    }

    /** One script per section: a header, the command under timeout, and its exact exit code. */
    static String script(String[] section) {
        StringBuilder s = new StringBuilder("T=; command -v timeout >/dev/null 2>&1 && T='timeout "
            + CMD_TIMEOUT_S + "'\n");
        for (int i = 1; i < section.length; i++) {
            s.append("echo ").append(quote("===== $ " + section[i])).append('\n')
                .append("$T sh -c ").append(quote(section[i])).append(" 2>&1 </dev/null\n")
                .append("echo \"----- exit=$?\"; echo\n");
        }
        return s.toString();
    }

    /** POSIX single-quote {@code s} so it reaches sh as one literal word. */
    static String quote(String s) {
        return "'" + s.replace("'", "'\\''") + "'";
    }

    /** Runs {@code script} via su or sh, copying stdout+stderr into {@code out}; -1 if the shell cannot start. */
    static int runOrFail(boolean root, String script, OutputStream out) throws IOException, InterruptedException {
        Process p;
        try {
            p = new ProcessBuilder(root ? "su" : "sh", "-c", script).redirectErrorStream(true).start();
        } catch (IOException e) {
            write(out, "===== collector: cannot start " + (root ? "su" : "sh") + ": " + e + "\n");
            return -1;
        }
        p.getOutputStream().close();
        InputStream in = p.getInputStream();
        try {
            copy(in, out);
        } finally {
            in.close();
        }
        return p.waitFor();
    }

    /** Copies {@code in} to {@code out} without closing either. */
    static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[64 * 1024];
        for (int n; (n = in.read(buf)) > 0; ) {
            out.write(buf, 0, n);
        }
    }

    private static void write(OutputStream out, String text) throws IOException {
        out.write(text.getBytes("UTF-8"));
    }

    private static String format(String pattern, Date date, TimeZone zone) {
        SimpleDateFormat f = new SimpleDateFormat(pattern, Locale.US);
        f.setTimeZone(zone);
        return f.format(date);
    }

    /** Host smoke test used by build_vps.sh: collect into args[0] with the host's own su/sh. */
    public static void main(String[] args) throws Exception {
        new LogCollector(new File(args[0]), new Listener() {
            @Override
            public void status(String line) {
                System.out.println(line);
            }
        }).collect();
    }
}

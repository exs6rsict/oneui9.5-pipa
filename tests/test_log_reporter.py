"""OneUI95 Log Reporter: offline checks of manifest, sources and build script, plus the built APK when one
is found ($LOG_REPORTER_APK, or artifacts/log-reporter/ in this checkout or the main worktree)."""
import glob, hashlib, os, re, subprocess, unittest, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
APP = os.path.join(ROOT, "tools", "log-reporter")
SRC = os.path.join(APP, "src", "com", "pipa", "port95", "logreporter")
A = "{http://schemas.android.com/apk/res/android}"
SECTIONS = ["00_summary.txt", "01_logcat_all.txt", "02_logcat_errors.txt", "03_dmesg.txt",
            "04_pstore_last_kmsg.txt", "05_avc_ksu_bpf_erofs.txt", "06_getprop.txt",
            "07_mounts_selinux_ksu.txt", "08_usb_battery_thermals.txt", "09_ps_services.txt",
            "10_packages_rro_display.txt", "11_dumpsys.txt"]


def read(*parts):
    """Text of a file under tools/log-reporter/."""
    with open(os.path.join(APP, *parts), encoding="utf-8") as f:
        return f.read()


def code(text, marker):
    """Text without comment lines (those starting with marker), so comments may name what code avoids."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(marker))


def java_sources():
    """{file name: text} for every Java source of the app."""
    return {os.path.basename(p): Path(p).read_text(encoding="utf-8") for p in glob.glob(os.path.join(SRC, "*.java"))}


def find_apk():
    """Path of a built APK to check, or None when none has been pulled yet."""
    rel = os.path.join("artifacts", "log-reporter", "OneUI95-LogReporter.apk")
    common = subprocess.run(["git", "-C", ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    candidates = [os.environ.get("LOG_REPORTER_APK"), os.path.join(ROOT, rel),
                  common and os.path.join(os.path.dirname(common), rel)]
    return next((c for c in candidates if c and os.path.isfile(c)), None)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.root = ET.parse(os.path.join(APP, "AndroidManifest.xml")).getroot()

    def test_package_and_sdk_levels(self):
        self.assertEqual(self.root.get("package"), "com.pipa.port95.logreporter")
        sdk = self.root.find("uses-sdk")
        self.assertEqual((sdk.get(A + "minSdkVersion"), sdk.get(A + "targetSdkVersion")), ("23", "29"))

    def test_requests_no_permissions(self):
        self.assertEqual(self.root.findall("uses-permission"), [])

    def test_provider_is_private_with_uri_grants_and_matches_java_authority(self):
        provider = self.root.find("application/provider")
        self.assertEqual(provider.get(A + "name"), ".ZipProvider")
        self.assertEqual(provider.get(A + "exported"), "false")
        self.assertEqual(provider.get(A + "grantUriPermissions"), "true")
        self.assertIn('AUTHORITY = "%s"' % provider.get(A + "authorities"), java_sources()["ZipProvider.java"])

    def test_launcher_activity(self):
        activity = self.root.find("application/activity")
        self.assertEqual(activity.get(A + "name"), ".MainActivity")
        self.assertEqual([e.get(A + "name") for e in activity.iter() if e.tag in ("action", "category")],
                         ["android.intent.action.MAIN", "android.intent.category.LAUNCHER"])


class SourceTest(unittest.TestCase):
    def setUp(self):
        self.src = java_sources()
        self.collector = code(self.src["LogCollector.java"], "//")

    def test_only_framework_and_jdk_imports(self):
        for name, text in self.src.items():
            for imp in re.findall(r"^import (\S+);", text, re.M):
                with self.subTest(name, imp=imp):
                    self.assertRegex(imp, r"^(android|java)\.")

    def test_collector_is_pure_java_for_host_smoke_test(self):
        self.assertNotIn("import android", self.collector)

    def test_sections_in_required_order(self):
        self.assertEqual(re.findall(r'\{"(\d\d_[a-z0-9_]+\.txt)"', self.collector), SECTIONS)

    def test_required_commands_present(self):
        for cmd in ("logcat -b all -d -v threadtime", "'*:E'", "dmesg -T || dmesg", "/sys/fs/pstore/*",
                    "/proc/last_kmsg", "avc:|denied|sukisu|ksu|erofs|bpf|traced", '"getprop"',
                    "cat /proc/mounts", "/proc/self/attr/current",
                    "ls -la /data/adb /data/adb/ksu /data/adb/ksu/temporary-root /data/adb/modules*",
                    "/config/usb_gadget", "/sys/class/power_supply/*/*", "/sys/class/thermal/thermal_zone*/*",
                    "ps -A", "grep init.svc", "service list", "pm list packages -f -U", "cmd overlay list",
                    "wm size", "wm density", "dumpsys activity crashes", "dumpsys dropbox --print",
                    "dumpsys usb", "dumpsys battery", "dumpsys display", "dumpsys window displays",
                    "dumpsys activity top", "uname -a", "getenforce", "ksud", "boot.?control",
                    "getprop ro.build.fingerprint", "getprop traced.relay_producer_port"):
            with self.subTest(cmd):
                self.assertIn(cmd, self.collector)

    def test_never_reads_ksu_secrets(self):
        self.assertNotIn("state.key", self.collector)
        self.assertNotRegex(self.collector, r"(cat|head|tail|cp|tar|dd)[^\"]*/data/adb")

    def test_su_with_sh_fallback_and_exit_codes(self):
        self.assertIn('root ? "su" : "sh", "-c"', self.collector)
        self.assertIn("----- exit=$?", self.collector)
        self.assertIn("su_probe_exit=", self.collector)
        self.assertIn('ZIP_PREFIX = "pipa-oneui95-logs-"', self.collector)
        self.assertIn("yyyyMMdd-HHmmss", self.collector)

    def test_ui_buttons_and_share_flow(self):
        ui = self.src["MainActivity.java"]
        for text in ("Kumpulkan Semua Log (.zip)", "Bagikan ZIP (Share)", "Simpan Ke... (Downloads/USB)",
                     "ScrollView", "Intent.ACTION_SEND", "FLAG_GRANT_READ_URI_PERMISSION",
                     "ACTION_CREATE_DOCUMENT", "new Thread("):
            with self.subTest(text):
                self.assertIn(text, ui)
        self.assertIn('MIME = "application/zip"', self.src["ZipProvider.java"])

    def test_provider_serves_only_report_names_read_only(self):
        provider = self.src["ZipProvider.java"]
        self.assertIn('\\\\d{8}-\\\\d{6}\\\\.zip"', provider)
        self.assertIn("MODE_READ_ONLY", provider)
        self.assertIn("getPathSegments().size() == 1", provider)


class BuildScriptTest(unittest.TestCase):
    def setUp(self):
        self.script = code(read("build_vps.sh"), "#")

    def test_shell_syntax(self):
        subprocess.run(["bash", "-n", os.path.join(APP, "build_vps.sh")], check=True)

    def test_toolchain_signing_and_checks(self):
        for text in ("platforms/android-23/android.jar", "-source 8 -target 8", "dalvik-exchange",
                     "--min-sdk-version=23", "aapt package", "--v1-signing-enabled true",
                     "--v2-signing-enabled true", "--v3-signing-enabled true", "apksigner verify --verbose",
                     "aapt dump badging", "classes.dex AndroidManifest.xml resources.arsc",
                     "MAX_BYTES=$((1024 * 1024))", "log-reporter-build", "sha256sum"):
            with self.subTest(text):
                self.assertIn(text, self.script)

    def test_never_touches_devices_or_other_build_trees(self):
        for word in ("adb ", "fastboot", "out-ksureboot", "oneui9.5-pipa/src", "gradle"):
            with self.subTest(word):
                self.assertNotIn(word, self.script)


@unittest.skipUnless(find_apk(), "no built APK found")
class ApkTest(unittest.TestCase):
    def setUp(self):
        self.apk = find_apk()

    def test_entries_and_size(self):
        names = zipfile.ZipFile(self.apk).namelist()
        for entry in ("classes.dex", "AndroidManifest.xml", "resources.arsc"):
            with self.subTest(entry):
                self.assertIn(entry, names)
        self.assertLess(os.path.getsize(self.apk), 1 << 20)

    def test_sha256sums_matches_when_present(self):
        sums = os.path.join(os.path.dirname(self.apk), "SHA256SUMS")
        if not os.path.isfile(sums):
            self.skipTest("no SHA256SUMS next to APK")
        with open(sums) as f, open(self.apk, "rb") as apk:
            self.assertEqual(f.read().split()[0], hashlib.sha256(apk.read()).hexdigest())


if __name__ == "__main__":
    unittest.main()

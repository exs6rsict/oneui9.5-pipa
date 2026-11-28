#!/usr/bin/env bash
# Build, sign and verify OneUI95-LogReporter.apk on pipa-jakarta-vps (no Gradle, no AndroidX).
# Usage (on the VPS, from a synced copy of tools/log-reporter/): bash build_vps.sh
# Everything lands in $BUILD (default ~/oneui9.5-pipa/log-reporter-build), never in ~/oneui9.5-pipa/src.
# Touches no device: the only thing run besides the toolchain is the collector's host smoke test.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
BUILD=${BUILD:-$HOME/oneui9.5-pipa/log-reporter-build}
ANDROID_JAR=/usr/lib/android-sdk/platforms/android-23/android.jar
JDK=/usr/lib/jvm/java-17-openjdk-amd64/bin
DEXER=dalvik-exchange   # Android dx 1.16; /usr/bin/dx on this host is OpenDX, not the dexer
APK_NAME=OneUI95-LogReporter.apk
MAX_BYTES=$((1024 * 1024))

OUT=$BUILD/out
KEYS=$BUILD/keystore            # reproducible signing key, kept on the VPS only (never committed)
KS=$KEYS/logreporter.p12
PASS=$KEYS/storepass

rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/smoke" "$KEYS"

echo "== javac (Java 8 bytecode against android-23)"
"$JDK/javac" -source 8 -target 8 -encoding UTF-8 -Xlint:-options -bootclasspath "$ANDROID_JAR" \
    -d "$OUT/classes" $(find "$HERE/src" -name '*.java')

echo "== dx"
"$DEXER" --dex --min-sdk-version=23 --output="$OUT/classes.dex" "$OUT/classes"

echo "== aapt package"
aapt package -f -M "$HERE/AndroidManifest.xml" -S "$HERE/res" -I "$ANDROID_JAR" -F "$OUT/unsigned.apk"
(cd "$OUT" && aapt add -v unsigned.apk classes.dex)

if [ ! -f "$KS" ]; then
    echo "== new keystore $KS"
    umask 077
    head -c 24 /dev/urandom | base64 > "$PASS"
    "$JDK/keytool" -genkeypair -keystore "$KS" -storetype PKCS12 -storepass:file "$PASS" -alias logreporter \
        -keyalg RSA -keysize 3072 -validity 10000 -dname "CN=OneUI95 Log Reporter, O=oneui9.5-pipa"
fi

echo "== apksigner sign (v1+v2+v3)"
apksigner sign --ks "$KS" --ks-pass "file:$PASS" --ks-key-alias logreporter --min-sdk-version 23 \
    --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
    --out "$OUT/$APK_NAME" "$OUT/unsigned.apk"

echo "== verify"
apksigner verify --verbose --print-certs "$OUT/$APK_NAME" | tee "$OUT/apksigner-verify.txt"
aapt dump badging "$OUT/$APK_NAME" | tee "$OUT/aapt-badging.txt"
unzip -l "$OUT/$APK_NAME" | tee "$OUT/unzip-l.txt"
for entry in classes.dex AndroidManifest.xml resources.arsc; do
    grep -qE " $entry\$" "$OUT/unzip-l.txt" || { echo "missing $entry" >&2; exit 1; }
done
size=$(stat -c %s "$OUT/$APK_NAME")
[ "$size" -lt "$MAX_BYTES" ] || { echo "APK is $size bytes, limit $MAX_BYTES" >&2; exit 1; }

echo "== host smoke test of LogCollector (read-only commands; Android tools are absent here)"
(cd "$OUT/smoke" && setsid -w "$JDK/java" -cp "$OUT/classes" com.pipa.port95.logreporter.LogCollector "$OUT/smoke")
unzip -l "$OUT"/smoke/pipa-oneui95-logs-*.zip | tee "$OUT/smoke-unzip-l.txt"
[ "$(grep -cE ' [0-9]{2}_[a-z0-9_]+\.txt$' "$OUT/smoke-unzip-l.txt")" -eq 12 ] || { echo "smoke zip lacks 12 sections" >&2; exit 1; }

(cd "$OUT" && sha256sum "$APK_NAME" > SHA256SUMS && cat SHA256SUMS)
echo "OK $OUT/$APK_NAME $size bytes"

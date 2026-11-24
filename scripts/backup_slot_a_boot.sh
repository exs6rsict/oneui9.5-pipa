#!/bin/sh
# READ-ONLY Gate 6 prep backup on pipa (run as root; needs blockdev and dd). It copies boot_a, vendor_boot_a and
# dtbo_a whole, plus the first 2 MiB of super (LP geometry + both metadata slots; logical data begins at
# 1 MiB), into OUTDIR, and writes SHA256SUMS. dd only opens the devices for reading. The script never opens GPT,
# userdata (sda34), linux (sda35), any *_b, or the logical *_a data.
# Every label must resolve to the device and byte size recorded in reports/port95/dualboot/live-backup.
# OUTDIR must be new. Copy it off the device afterwards: the Linux host lives on this same device.
set -eu
OUT=${1:?usage: backup_slot_a_boot.sh OUTDIR}
case $OUT in /dev/*|/sys/*|/proc/*) echo "refusing OUTDIR $OUT"; exit 2;; esac
[ ! -e "$OUT" ] || { echo "refusing: $OUT already exists"; exit 2; }
BYLABEL=/dev/disk/by-partlabel

# label  expected-device  expected-bytes  bytes-to-copy
check() {
  dev=$(readlink -f "$BYLABEL/$1")
  [ "$dev" = "$2" ] || { echo "refusing: $1 resolves to $dev, expected $2"; exit 3; }
  [ -b "$dev" ] || { echo "refusing: $dev is not a block device"; exit 3; }
  size=$(blockdev --getsize64 "$dev")
  [ "$size" = "$3" ] || { echo "refusing: $dev is $size B, expected $3"; exit 3; }
}
LIST="boot_a /dev/sde12 201326592 201326592
vendor_boot_a /dev/sde25 100663296 100663296
dtbo_a /dev/sde18 33554432 33554432
super /dev/sda29 9126805504 2097152"

# Check every device before copying anything.
echo "$LIST" | while read -r l d s _n; do check "$l" "$d" "$s"; done
mkdir -p "$OUT"
echo "$LIST" | while read -r l d _s n; do
  name=$l.img; [ "$l" = super ] && name=super-first-2MiB.img
  dd if="$d" of="$OUT/$name" bs=1M count=$((n >> 20)) iflag=fullblock status=none
  [ "$(stat -c %s "$OUT/$name")" = "$n" ] || { echo "short read on $d"; exit 4; }
done
cd "$OUT" && sha256sum boot_a.img vendor_boot_a.img dtbo_a.img super-first-2MiB.img > SHA256SUMS && cat SHA256SUMS

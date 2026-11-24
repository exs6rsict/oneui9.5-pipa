#!/bin/sh
set -eu
OUT="/home/user/orca/projects/oneui9.5-pipa/reports/port95/dualboot/live-backup"
mkdir -p "$OUT"
sfdisk -d /dev/sda > "$OUT/gpt-sda.sfdisk"
sfdisk -d /dev/sde > "$OUT/gpt-sde.sfdisk"
lpdump /dev/sda29 > "$OUT/super-lpdump.txt"
lpdump -j /dev/sda29 > "$OUT/super-lpdump.json"
chown -R user:user "$OUT"
cd "$OUT"
sha256sum gpt-sda.sfdisk gpt-sde.sfdisk super-lpdump.txt super-lpdump.json > SHA256SUMS
cat SHA256SUMS

# One UI 9.5 pipa — checkpoint pengembangan

## Status

Tooling audit dan build offline tersedia. Build image eksperimental pernah dihasilkan dan diverifikasi offline; **belum diuji boot di pipa dan tidak disetujui untuk flashing**. Artifact binary dan hasil ekstraksi tidak disimpan dalam Git.

## Input

- Baseline: port One UI 8.0 pipa dari https://t.me/XiaomiPad6Global/394100 . Pengguna melaporkan bisa diflash dan boot lewat flash script; bukan hasil uji perangkat oleh agent.
- Donor: One UI 9.5 XGSI https://t.me/xgsiupdates/233 . Properti image menunjukkan Android 17, SDK 37.2 dan One UI 90500; konfigurasi donor masih phone.
- SukiSU yang diminta: https://git.zako.shirkneko.top:20004/shirkneko/SukiSU . Root dari fork ini belum berhasil dibangun; jangan menggantikannya diam-diam dengan implementasi root lain.

## Tooling

- `scripts/zipaudit.py`: inventory ZIP berbatas, pemeriksaan path/duplikasi/symlink dan perbandingan inventory.
- `scripts/sparselp.py`: pembacaan sparse dan ekstraksi logical partitions secara streaming.
- `scripts/fsmeta.py`: metadata ext4/EROFS offline menggunakan reader userspace.
- `scripts/port95_build.py`: recipe build eksperimental dan verifikasi readback/round-trip.
- `scripts/sepolicy_permissive.py`: kompilasi dan pemeriksaan policy all-domain permissive. Ini **bukan** bukti mode global permissive atau hasil runtime.
- `scripts/flashplan.py`: validator rencana A-only, bukan flasher atau pemberi persetujuan.

Build/test dikerjakan Claude menggunakan skill Matt Pocock `tdd` dan `codebase-design`. Suite dijalankan ulang coordinator: **39 tes lulus**, dengan tool EROFS lokal tersedia di PATH. Tanpa tool tertentu, beberapa tes integrasi bisa skip; baca output, bukan exit code saja.

```sh
PATH="$PWD/work/port95/tools/root/usr/bin:$PATH" \
  python3 -I -W error::ResourceWarning -m unittest discover -s tests -v
```

Dependency eksternal mencakup android-tools, e2fsprogs, erofs-utils, secilc dan checkpolicy. Tool lokal dalam `work/` tidak disertakan di Git. CLI bukan pipeline satu perintah lengkap dari clone kosong: image input, konfigurasi build dan hasil inventory lokal masih diperlukan. Tidak ada klaim reproducibility lintas host yang sudah diuji.

## Kontrak keselamatan dual boot

Linux aktif berada di partisi terpisah dan harus dipertahankan, bersama **seluruh slot B**. Partisi Linux tidak identik dengan slot B. `super` adalah container bersama: menulis ulang full super dapat mengganti metadata/extent slot B, walaupun image hanya mengandung `_a`.

- Tidak menjalankan installer baseline apa adanya: beberapa jalur menulis kedua slot dan firmware.
- Tidak menulis block device, GPT, Linux, slot B, userdata/metadata atau firmware bootloader.
- Tidak resize/delete logical partitions, aktivasi slot, reboot atau relock sebagai bagian tooling audit.
- Dump layout live dan backup terverifikasi wajib sebelum menyusun rencana pemasangan.
- Setiap device write memerlukan persetujuan terpisah atas target dan hash artifact.
- Full `super.img` eksperimental lama **NOT APPROVED FOR DUAL BOOT**.

## Blocker

1. Kernel baseline tidak mengaktifkan KPROBES yang dibutuhkan fork SukiSU terpilih. Source kernel/commit/config/toolchain harus ditetapkan sebelum rebuild root.
2. Layout LP live belum diperoleh. Layout paket baseline tidak boleh dianggap layout perangkat saat ini.
3. Image ext4 sistem 9.5 lebih besar daripada extent system_a paket baseline. Repack EROFS dan pengukuran terhadap layout live diperlukan tanpa mengubah shared metadata.
4. Policy all-domain permissive terkompilasi offline, tetapi global permissive, pemilihan genfs oleh init dan perilaku runtime belum terverifikasi.
5. FCM lama, kernel/BPF Android 17, UX tablet dan hardware perlu validasi lanjutan.

Riset kernel dan laporan rinci lokal tetap di luar checkpoint ini sampai ditinjau. Hasil boot, root, SELinux runtime dan hardware saat ini **NOT TESTED**.

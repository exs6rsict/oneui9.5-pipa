# One UI 9.5 pipa — checkpoint pengembangan

## Status

Tooling audit dan build offline tersedia. Build image eksperimental pernah dihasilkan dan diverifikasi offline; **belum diuji boot di pipa dan tidak disetujui untuk flashing**. Artifact binary dan hasil ekstraksi tidak disimpan dalam Git.

## Input

- Baseline: port One UI 8.0 pipa dari https://t.me/XiaomiPad6Global/394100 . Pengguna melaporkan bisa diflash dan boot lewat flash script; bukan hasil uji perangkat oleh agent.
- Donor: One UI 9.5 XGSI https://t.me/xgsiupdates/233 . Properti image menunjukkan Android 17, SDK 37.2 dan One UI 90500; konfigurasi donor masih phone.
- SukiSU yang diminta: https://git.zako.shirkneko.top:20004/shirkneko/SukiSU . Kernel dengan branch `builtin` commit `adf6e86d55229ad78a5f7758bdc43d92fd1c3729` sudah berhasil dikompilasi di VPS dan kandidat boot kontrol sudah dibuat. Branch `main` yang semula diperiksa tidak kompatibel langsung dengan kernel 4.19. Root runtime **NOT TESTED**.

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

1. Kernel kontrol N0 + SukiSU builtin sudah terkompilasi. Backport BPF lanjutan dan pengujian QEMU belum selesai; keberhasilan compile bukan bukti kompatibilitas BPF donor.
2. Layout LP live belum diperoleh. Layout paket baseline tidak boleh dianggap layout perangkat saat ini.
3. Image ext4 sistem 9.5 lebih besar daripada extent system_a paket baseline. Repack EROFS dan pengukuran terhadap layout live diperlukan tanpa mengubah shared metadata.
4. Policy all-domain permissive terkompilasi offline, tetapi global permissive, pemilihan genfs oleh init dan perilaku runtime belum terverifikasi.
5. FCM lama, kernel/BPF Android 17, UX tablet dan hardware perlu validasi lanjutan.

## EROFS — tooling eksperimental, bukan image rilis

`scripts/erofs95.py` memindai ext4 dengan debugfs read-only, membuat tar PAX dengan UID/GID/mode/xattr/capability/symlink, lalu membandingkan metadata dan hash isi hasil EROFS memakai reader independen + fsck.erofs. Timestamp dinormalisasi; bukan salinan bit-identik seluruh metadata filesystem.

Empat tes fixture EROFS dijalankan ulang coordinator di VPS: **4 lulus**. Ini terpisah dari suite 39 tes checkpoint sebelumnya; tidak ada klaim 43 tes sudah dijalankan sebagai satu suite.

**Real-image build dengan erofs-utils 1.7.1 gagal:** fsck gagal dan 751 dari 6.972 file tercatat terkompresi tanpa data. Ukuran 4.531.716.096 byte bukan bukti image valid/muat. Image dikarantina, tidak disertakan dalam Git. Worker menelusuri masalah ke hasil `lseek` yang disimpan dalam `int` pada erofs-utils 1.7.1 dan fix upstream `9d7b9c0`; reproducer menunjukkan pola kehilangan data pada rentang offset diskbuf tertentu. Ini bukan klaim bahwa semua korupsi EROFS disebabkan bug tersebut. Tool pengganti 1.8.9 kemudian berhasil disiapkan lewat alur worker; 5 tes fixture lulus dan empat kasus reproducer yang dilaporkan worker tidak kehilangan data. Coordinator menjalankan ulang 5 tes di VPS: semuanya lulus. Repack image nyata sudah dijalankan, tetapi hasil akhirnya belum diperiksa karena pengguna meminta rehat. Belum ada klaim EROFS valid.

`scripts/erofs95_run.sh` sengaja tidak disertakan: runner khusus workspace/VPS masih belum ditinjau sebagai interface rilis. Jangan menganggap pipeline recovery/release siap. CLI pengembangan harus dijalankan hanya pada salinan image, workspace terisolasi, dengan tool tepercaya dan pemeriksaan hasil penuh. Semua kompilasi/repack dan tes image selanjutnya dilakukan di VPS pilihan pengguna, bukan di perangkat pipa.

Persyaratan decrypted default masih perlu pengujian: fstab vendor untuk late-mount /data tidak membawa flag FBE, tetapi fstab first-stage berbeda dan dependensi vold/Knox belum diuji. Menghapus flag tidak mendekripsi userdata lama, dan tidak memberi izin format/wipe.

Riset kernel, patch queue yang masih berubah dan laporan rinci lokal tetap di luar checkpoint ini sampai ditinjau. Hasil boot, root, SELinux runtime dan hardware saat ini **NOT TESTED**.

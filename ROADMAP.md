# Roadmap audit dan port One UI 9.5 ke Xiaomi Pad 6 (pipa)

## Tujuan dan batasan

Membandingkan ROM One UI yang sudah diport ke pipa dengan kandidat donor One UI 9.5, lalu memilih jalur implementasi berdasarkan bukti kompatibilitas.

- Target utama: Xiaomi Pad 6, codename `pipa`.
- Target: One UI 9.5 yang kompatibel dengan pipa. One UI 9 bukan target dan bukan fallback; donor 9.0 hanya boleh dipakai sebagai referensi konfigurasi.
- Baseline: ROM One UI pipa yang sudah bekerja, beserta versi vendor/kernel dan catatan bug-nya. Versi dan sumber harus dikonfirmasi dari paket, bukan diasumsikan.
- Tahap awal hanya audit offline. Download, ekstraksi, modifikasi image, dan flashing adalah tahap terpisah.
- Tidak ada jaminan boot atau kompatibilitas hanya berdasarkan label versi, chipset, atau laporan perangkat lain.

## Status terkini (2026-11-25)

- [x] Menetapkan pipa sebagai target.
- [x] Mengumpulkan tautan kandidat awal.
- [x] Menyediakan paket baseline port pipa (`inputs/baseline-pipa/`).
- [x] Menyediakan paket donor D2 (`inputs/donors/XGSI_SM-S948B_S948BXXU6ZZKN_arm64.zip`).
- [x] Memverifikasi metadata langsung dari image (`reports/port95/README.md`, `reports/CHECKPOINT.md`).
- [x] Mengambil dump GPT & LP `super` live perangkat `pipa` (`reports/port95/dualboot/live-backup/`).
- [x] Menyelesaikan perakitan offline & manifest Gate 5 (`reports/port95/GATE5-REPORT.md`, lokal saja): offline verified, **NOT APPROVED FOR FLASH**.
- [ ] Uji perangkat & bring-up nyata di `pipa` (Fase 6–7, menunggu Gate 5 + persetujuan eksplisit Gate 6).

## Kandidat awal

| ID | Kandidat | Sumber | Peran audit |
| --- | --- | --- | --- |
| B0 | Port One UI yang sudah bekerja di pipa | Menunggu paket/sumber dari pengguna | Acuan integrasi hardware, boot, dan patch |
| D1 | Tab S9+ `SM-X810`, KOO, `X810XXU6FZK2`; listing menyebut One UI 9 / Android 17 | https://samfw.com/firmware/SM-X810/KOO/X810XXU6FZK2 | Donor firmware tablet mentah |
| D2 | XGSI One UI 9.5 `64_32`, donor `SM-S948B` / `m3q`, build `S948BXXU6ZZKN` | https://t.me/xgsiupdates/233 | Kandidat GSI 9.5 dan referensi patch kompatibilitas |
| D3 | XGSI One UI 9.0 `64_32`, donor Tab S12 Ultra `SM-X946N`, board tercantum `mt6993` | https://t.me/xgsiupdates/209 | Referensi konfigurasi tablet saja (bukan target); platform berbeda |
| D4 | XGSI One UI 9.0 `64_32`, donor `SM-F971B` / `h8q` | https://t.me/xgsiupdates/201 | Referensi konfigurasi layar besar/foldable saja (bukan target) |

D3 dan D4 opsional; tidak perlu mengunduh semuanya sebelum memulai audit. Prioritas awal: **B0 + D1 + D2**.

Referensi download D2: https://pixeldrain.com/u/TsrGCVBL atau https://t.me/xgsimirror/15. Posting https://t.me/xgsiupdates/234 adalah varian bercandaan berlabel Boykisser UI, bukan kandidat utama.

## Struktur workspace yang direncanakan

```text
inputs/                 Paket asli, read-only secara prosedural; jangan commit binary
  baseline-pipa/
  donors/
work/                   Hasil ekstraksi dan eksperimen per kandidat
inventory/              Hash, metadata image, manifest partisi dan filesystem
reports/                Audit, diff terarah, keputusan donor dan hasil uji
patches/                Patch yang terlacak asal-usul serta alasannya
scripts/                Tool inventory, diff, repack dan validasi
artifacts/              Image/installer keluaran beserta checksum
logs/                   Log boot dan uji hardware; sanitasi sebelum dibagikan
```

Direktori dibuat saat diperlukan. Sebelum menaruh binary, siapkan `.gitignore` untuk input, hasil ekstraksi, artifact, dan log sensitif. Jangan commit paket ROM atau data pribadi.

## Fase 0 — Penerimaan bahan dan kesiapan

- [ ] Catat nama asli, sumber, ukuran byte dan SHA-256 setiap paket.
- [ ] Simpan paket asli tanpa dimodifikasi; ekstraksi ke direktori kandidat masing-masing.
- [ ] Minta catatan baseline: versi One UI/Android, vendor/firmware prasyarat, kernel, cara instalasi, known bugs, dan status SELinux.
- [ ] Kumpulkan script/repo/changelog port baseline jika tersedia; tanpa source, tandai asal patch yang belum diketahui.
- [ ] Periksa ruang disk, filesystem host, serta kebutuhan tool berdasarkan format paket yang benar-benar ditemukan.
- [ ] Inventarisasi archive sebelum ekstraksi; tolak path traversal/symlink berbahaya, jangan menjalankan script installer dari paket selama audit.

**Gate 0:** B0 dan minimal satu donor tersedia, checksum tercatat, kapasitas ekstraksi cukup. Bahan yang hilang disebut eksplisit, bukan ditebak.

## Fase 1 — Ekstraksi dan inventory reproducible

- [ ] Identifikasi format: ZIP/TAR/Odin AP, LZ4, sparse/raw image, dynamic partitions/super, payload OTA, EROFS/ext4 sesuai temuan.
- [ ] Rekam tool, versi dan command ekstraksi agar bisa diulang.
- [ ] Inventarisasi partisi yang tersedia dan partisi yang tidak disertakan dalam paket.
- [ ] Rekam filesystem, ukuran image, logical partition/group dan batas kapasitas yang relevan.
- [ ] Ekstrak properti build di `system`, `system_ext`, `product`, `vendor`, dan `odm` jika ada.
- [ ] Cocokkan versi Android, SDK, fingerprint, patch keamanan dan properti versi One UI dengan klaim distributor; catat kontradiksi.
- [ ] Inventarisasi APK/APEX/JAR, native libraries, ABI, symlink, permissions, file contexts, init dan fstab.

**Output:** `inventory/packages.json`, inventory per kandidat, dan `reports/01-inventory.md`.

**Gate 1:** Identitas paket dan cakupan image diketahui. Label `64_32` tidak diperlakukan sebagai bukti lengkap dukungan ABI tanpa pemeriksaan isi.

## Fase 2 — Memahami baseline pipa

- [ ] Petakan asal komponen: Samsung userspace, vendor/ODM pipa, boot/kernel, DTBO dan modul bila ada.
- [ ] Identifikasi patch device-specific pada init, properties, fstab, VINTF, SELinux, overlay, framework dan native library.
- [ ] Catat layanan Samsung yang dihapus, diganti atau dinonaktifkan dan alasan yang bisa dibuktikan.
- [ ] Rekam konfigurasi display, density, refresh rate, taskbar, multiwindow, rotasi, audio dan input aksesori.
- [ ] Bedakan perilaku baseline yang teruji di perangkat dari klaim changelog atau inferensi statis.
- [ ] Jika tersedia firmware Samsung asal baseline, lakukan diff terhadap sumber itu untuk mengisolasi patch port. Tanpa sumber, jangan menyebut seluruh perbedaan sebagai patch pipa.

**Output:** `reports/02-baseline-pipa.md` dan katalog patch baseline dengan tingkat keyakinan.

**Gate 2:** Komponen hardware pipa dan dependensi boot baseline terpetakan; ketidakpastian yang tersisa terdokumentasi.

## Fase 3 — Matriks kompatibilitas donor

Audit setiap donor terhadap B0, bukan sekadar donor terhadap donor.

| Area | Pemeriksaan | Bukti yang dicatat |
| --- | --- | --- |
| Framework ↔ vendor | VINTF manifest/matrix, FCM, deklarasi HAL, VNDK/linker namespace bila relevan | Konflik spesifik dan hasil tool pemeriksa |
| Native/ABI | Arsitektur ELF, dependensi library, simbol yang diperlukan, library yang hilang | File dan simbol konkret |
| Kernel ↔ userspace | Versi/config kernel aktual, BPF dan fitur yang diperlukan, modul | Config/simbol/log; bukan tebakan dari versi Android |
| Graphics | Composer, allocator/mapper/gralloc, EGL/Vulkan dan SurfaceFlinger | Interface yang diminta dibanding yang disediakan |
| Boot/init | Boot image header/ramdisk bila tersedia, mount, fstab, enkripsi dan AVB | Perbedaan konfigurasi dan kebutuhan penyesuaian |
| SELinux | Policy split/version, contexts dan domain layanan | Konflik kompilasi/validasi atau AVC saat uji |
| Samsung services | Dependensi Knox, hardware Samsung, framework/vendor service | Pemanggil, dependency dan kemungkinan dampak |
| Tablet UX | Overlay, launcher, taskbar, multiwindow/DeX jika tersedia, density dan fitur layar besar | Resource/konfigurasi yang benar-benar ada |
| Packaging | Kapasitas super/logical partitions, format filesystem dan installer | Ukuran serta batas aktual pipa |

- [ ] Periksa patch gralloc yang disebut D2 dari isi image atau source pembuat jika tersedia; jangan menganggap kredit patch sebagai bukti kompatibilitas pipa.
- [ ] Pisahkan patch generik GSI dari penyesuaian khusus donor dan penyesuaian yang diperlukan pipa.
- [ ] Jangan menggabungkan framework/JAR/APEX lintas build secara acak; petakan dependensi sebelum setiap transplantasi.

**Output:** `reports/03-compatibility-matrix.md`; setiap temuan diberi status **terverifikasi / indikasi / belum diketahui**.

**Gate 3:** Setiap donor memiliki daftar blocker, patch yang mungkin dipakai ulang, dan kebutuhan pengujian runtime.

## Fase 4 — Keputusan jalur port

Bandingkan dua opsi berdasarkan hasil audit:

1. **Firmware tablet D1 → pipa:** mempertahankan basis UI tablet dan membawa ulang patch pipa yang relevan.
2. **GSI D2 → pipa:** memanfaatkan adaptasi GSI untuk eksperimen 9.5; tetap mengaudit integrasi hardware dan UX tablet.

Target tetap One UI 9.5. Jika semua jalur terblokir, hasilnya dilaporkan sebagai blocker, bukan turun ke One UI 9.

- [ ] Nilai peluang boot berdasarkan bukti, kelengkapan tablet UX, kompatibilitas kernel/vendor, kemudahan debug dan asal patch.
- [ ] Pilih satu target awal; hindari mengerjakan banyak donor sekaligus sebelum memperoleh log boot pertama.
- [ ] Tentukan komponen yang dipertahankan, diganti, diadaptasi atau tidak didukung.
- [ ] Buat backlog patch per blocker dan rencana uji masing-masing.

**Output:** `reports/04-donor-decision.md` berisi pilihan, alasan, risiko dan batas scope.

**Gate 4:** Donor dipilih secara eksplisit. Tidak ada klaim “siap flash” dari audit statis saja.

## Fase 5 — Implementasi dan validasi offline

- [x] Buat script patch/repack yang dapat diulang tanpa mengubah input asli (`scripts/port95_build.py`, `scripts/erofs95.py`, `scripts/erofs95_repro.py`).
- [x] Terapkan perubahan kecil bertahap; catat sumber, alasan dan file yang disentuh (`reports/port95/README.md`, `reports/port95/bpf-backport/README.md`).
- [x] Tangani permissions, ownership, symlink dan SELinux contexts saat repack (EROFS `v1.8.9` terverifikasi `metadata+content identical`, `fsck.erofs rc=0`, 689/689 domain permissive via `scripts/sepolicy_permissive.py`).
- [ ] Validasi ukuran partisi terhadap layout live `pipa` **per partisi**, bukan total vs seluruh `super`. In-place (extent live, aturan `scripts/flashplan.py`) **tidak muat**: `product_a`, `vendor_a`, `odm_a` melebihi extent live (`GATE5-REPORT.md` §4). Total `7,004,303,360 B` vs `super` `9,126,805,504 B` hanya batas atas, bukan bukti muat. Physical `boot_a`/`vendor_boot_a`/`dtbo_a` sama persis dengan ukuran GPT. Filesystem, konfigurasi mount dan VINTF/HAL sudah diperiksa offline.
- [ ] Rencana re-layout LP grup `_a` saja (bukan `lpmake` super utuh): validator wajib menjaga GPT, `sda34` userdata, `sda35` Linux, entri/grup slot B dan header metadata. Tanpa validator itu, `flashplan.py` menolak resize (`shared-super`).
- [x] Hasilkan manifest artifact, checksum, daftar perubahan serta daftar keterbatasan final untuk Gate 5 (`reports/port95/gate5-slot-a-manifest.json`, lokal saja).

**Gate 5:** Artifact lolos pemeriksaan offline dan memiliki prosedur pengujian serta rollback yang spesifik. Lolos gate ini belum membuktikan boot.

## Fase 6 — Persiapan uji perangkat (memerlukan persetujuan)

- [ ] Konfirmasi perangkat benar-benar pipa, bootloader unlocked, slot/layout partisi dan keadaan recovery/fastboot aktual.
- [ ] Pastikan baseline diketahui bekerja pada perangkat yang diuji.
- [ ] Cadangkan data penting dan partisi relevan sesuai layout; simpan backup di luar perangkat.
- [ ] Sediakan paket pemulihan pipa yang sesuai dan dokumentasikan cara kembali ke baseline.
- [ ] Jelaskan kemungkinan wipe, kehilangan data, bootloop dan keterbatasan pemulihan sebelum pengguna menyetujui flashing.
- [ ] Tentukan jalur pengambilan log: ADB/logcat, kernel log dan pstore bila tersedia.

**Larangan:** jangan flash bootloader, firmware hardware, `vendor`, DTBO atau boot image Samsung ke pipa. Jangan relock bootloader dengan image modifikasi. Jangan mengubah AVB/enkripsi atau menulis partisi berdasarkan command generik yang belum dicocokkan ke perangkat.

**Gate 6:** Pengguna menyetujui rencana flash yang menyebut artifact dan partisi secara tepat, dengan backup serta jalur recovery tersedia. Roadmap ini bukan persetujuan flashing.

## Fase 7 — Bring-up dan uji regresi

Urutan milestone:

- [ ] **M1:** kernel/init berjalan; mount partisi berhasil; log dapat diambil.
- [ ] **M2:** zygote dan system_server stabil; tidak ada crash loop berulang.
- [ ] **M3:** SurfaceFlinger/SystemUI/launcher tampil; touchscreen dan navigasi berfungsi.
- [ ] **M4:** setup selesai, storage/dekripsi berfungsi dan reboot konsisten.
- [ ] **M5:** uji hardware dan fungsi tablet terhadap B0.
- [ ] **M6:** uji stabilitas, sleep/wake, idle drain dan thermal.

Checklist M5:

- Display: brightness, rotasi, refresh rate dan rendering GPU.
- Audio: semua speaker, mikrofon, Bluetooth dan routing output.
- Wi-Fi/Bluetooth: koneksi ulang setelah sleep dan reboot.
- Kamera: depan/belakang, foto dan video; catat keterbatasan aplikasi.
- Input: touch, tombol, keyboard/stylus jika tersedia, hall sensor dan auto-rotate.
- Power: charging, indikator baterai, deep sleep, wake dan thermal.
- USB: ADB, transfer file, OTG dan display output jika didukung setup uji.
- UX tablet: landscape, taskbar, split-screen, popup window dan fitur DeX yang memang ditargetkan.
- Keamanan: SELinux aktual, enkripsi, lockscreen dan patch level aktual; jangan memalsukan status sertifikasi.
- Kompatibilitas aplikasi: APK sesuai ABI; DRM dan Play Integrity dilaporkan apa adanya, bukan dijanjikan.

Setiap hasil diberi label **PASS / FAIL / NOT TESTED / NOT APPLICABLE**, disertai artifact hash, base vendor/kernel, langkah reproduksi dan log. Boot ke launcher bukan bukti siap daily driver.

**Output:** `reports/05-bringup.md`, laporan regresi dan log yang disanitasi.

## Fase 8 — Paket reproducible dan handoff

- [ ] Build ulang dari input asli dan script yang terdokumentasi.
- [ ] Rilis manifest input/output, SHA-256 dan instruksi instalasi spesifik pipa.
- [ ] Dokumentasikan prasyarat vendor/firmware/kernel, known bugs dan rollback.
- [ ] Cantumkan kredit serta lisensi patch yang digunakan; jangan mendistribusikan ulang bahan tanpa mempertimbangkan izin/lisensinya.
- [ ] Pisahkan status experimental, bootable dan daily-driver berdasarkan hasil uji, bukan nama versi.

## Definisi selesai

### Audit selesai

Inventory B0 dan donor tersedia; patch baseline terpetakan sejauh bukti memungkinkan; matriks kompatibilitas serta keputusan donor selesai; blocker dan ketidakpastian dicatat. **Tidak mensyaratkan flashing.**

### Port eksperimental selesai

Artifact reproducible tersedia, benar-benar diuji di pipa dengan persetujuan pengguna, hasil boot/hardware dicatat dan rollback terdokumentasi. Fitur yang belum diuji tetap diberi label demikian.

## Langkah berikutnya setelah paket diunduh

1. Berikan path absolut paket baseline port pipa dan kandidat donor, atau tempatkan di `inputs/` setelah `.gitignore` disiapkan.
2. Sertakan link sumber baseline, instruksi instalasi dan known bugs jika ada.
3. Mulai Fase 0–3 secara offline; jangan flash apa pun sebelum keputusan donor dan kesiapan pemulihan disepakati.

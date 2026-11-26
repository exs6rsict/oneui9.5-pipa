# One UI 9.5 untuk Xiaomi Pad 6 (pipa)

Proyek audit dan port One UI 9.5 yang kompatibel dengan Xiaomi Pad 6 (codename `pipa`).

> **Status (2026-11-26): Gate 6 Boot Attempt 1 dianalisis; kandidat `boot_a` perbaikan siap uji Attempt 2.** Image Gate 6 (`system_a` EROFS v1.8.9, `system_ext_a`, `product_a`, `vendor_a`, `odm_a`, `dtbo_a`, `vendor_boot_a`, `boot_a` SukiSU+BPF/vgate) sudah di-flash ke Slot A dengan persetujuan eksplisit. Boot Attempt 1 mengeksekusi kernel & `init`, lalu berhenti di logo MIUI karena bug `erofs_fill_symlink` (`inline data cross block boundary @ nid 767`, `/system_ext`). Fix EROFS symlink ([patches/0001-port95-erofs-fill_symlink-read-inline-data-from-next-block.patch](patches/0001-port95-erofs-fill_symlink-read-inline-data-from-next-block.patch)) sudah dikompilasi di VPS dan dikemas ke `boot_a.img` baru (`7a179ab1...`), siap untuk uji `boot_a`-only Attempt 2 (perangkat saat ini di fallback Linux Slot B; Attempt 2 **belum diuji**). Jangan menyentuh Slot B (`*_b`), `sda35`, GPT, atau firmware bootloader.

## Target

- Perangkat: Xiaomi Pad 6, `pipa`.
- Versi: One UI 9.5 saja. One UI 9 bukan target dan bukan fallback.
- Pendekatan: audit baseline port pipa yang sudah jalan (B0) terhadap donor, lalu pilih satu jalur berdasarkan bukti dari isi image.

## Kandidat donor

| ID | Kandidat | Peran | Status |
| --- | --- | --- | --- |
| B0 | Port One UI 8.0 pipa (`oneui_8.0_gts9u_port_pipa_decrypted_20260816.zip`) | Baseline (vendor/odm/product/system_ext/boot/dtbo) | **Tersedia & terverifikasi** (`inputs/baseline-pipa/`) |
| D1 | Tab S9+ `SM-X810` firmware | Donor firmware tablet | Tidak dipilih |
| D2 | XGSI One UI 9.5 `64_32` (`SM-S948B` / `S948BXXU6ZZKN`, Android 17 / SDK 37.2) | **Jalur utama** GSI 9.5 | **Dipilih & terverifikasi** (`inputs/donors/`) |
| D3, D4 | XGSI One UI 9.0 | Referensi konfigurasi saja | Opsional |

Detail dan sumber ada di [ROADMAP.md](ROADMAP.md). Ringkasan checkpoint & bukti teknis tersedia di (hanya `reports/CHECKPOINT.md` yang ada di Git; laporan `reports/port95/` hanya ada di workspace lokal):
- [reports/CHECKPOINT.md](reports/CHECKPOINT.md) — checkpoint utama pengembangan & kontrak keselamatan dual-boot
- `reports/port95/README.md` *(lokal saja, tidak di Git: `/reports/*` di-gitignore)* — audit integrasi B0 + D2
- `reports/port95/bpf-backport/README.md` *(lokal saja, tidak di Git: `/reports/*` di-gitignore)* — backport BPF `bpf_for_each_map_elem` + `vgate` + uji QEMU arm64
- `reports/port95/dualboot/README.md` *(lokal saja, tidak di Git: `/reports/*` di-gitignore)* — kontrak dual-boot, SELinux permissive, dan dump layout live `reports/port95/dualboot/live-backup/`

## Isi repo

| File | Fungsi |
| --- | --- |
| [ROADMAP.md](ROADMAP.md) | Fase 0–8, gate, checklist uji, dan definisi selesai |
| `README.md` | Ringkasan ini |

Direktori kerja (`inputs/`, `work/`, `inventory/`, `reports/`, `patches/`, `scripts/`, `artifacts/`, `logs/`) dibuat saat dibutuhkan. Paket ROM, hasil ekstraksi, artifact, dan log tidak boleh di-commit; cek `.gitignore` sebelum menaruh binary.

## Alur kerja

1. **Fase 0–3 (offline):** terima bahan dan catat checksum, ekstrak dan inventory, petakan patch baseline, lalu buat matriks kompatibilitas donor.
2. **Fase 4:** pilih satu donor secara eksplisit.
3. **Fase 5:** patch dan repack yang reproducible, divalidasi offline.
4. **Fase 6 (perlu persetujuan):** persiapan uji perangkat dengan backup dan jalur recovery.
5. **Fase 7–8:** bring-up bertahap (M1–M6) dan paket handoff.

## Aturan keselamatan

- Tahap audit hanya membaca. Download, ekstraksi, modifikasi image, dan flashing adalah tahap terpisah.
- Jangan menjalankan script installer dari paket selama audit.
- Jangan flash bootloader, firmware hardware, `vendor`, DTBO, atau boot image Samsung ke pipa.
- Jangan relock bootloader dengan image modifikasi atau mengubah AVB/enkripsi tanpa persetujuan.
- Flashing hanya setelah Gate 6: Anda menyetujui artifact dan partisi secara tepat, backup ada, dan jalur recovery tersedia.
- Label versi, chipset, atau laporan perangkat lain bukan bukti boot.

## Memulai

Berikan path absolut paket baseline pipa (B0) dan minimal satu donor, atau taruh di `inputs/`. Sertakan link sumber baseline, cara instalasi, dan known bugs jika ada. Setelah itu Fase 0–1 bisa dimulai.

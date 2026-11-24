# One UI 9.5 untuk Xiaomi Pad 6 (pipa)

Proyek audit dan port One UI 9.5 yang kompatibel dengan Xiaomi Pad 6 (codename `pipa`).

> **Status: tahap audit offline.** Belum ada artifact, belum ada image yang diuji, dan belum ada klaim boot atau kompatibilitas. Jangan flash apa pun dari repo ini.

## Target

- Perangkat: Xiaomi Pad 6, `pipa`.
- Versi: One UI 9.5 saja. One UI 9 bukan target dan bukan fallback.
- Pendekatan: audit baseline port pipa yang sudah jalan (B0) terhadap donor, lalu pilih satu jalur berdasarkan bukti dari isi image.

## Kandidat donor

| ID | Kandidat | Peran |
| --- | --- | --- |
| B0 | Port One UI yang sudah bekerja di pipa | Baseline (belum disediakan) |
| D1 | Tab S9+ `SM-X810` firmware | Donor firmware tablet; versi One UI perlu diverifikasi |
| D2 | XGSI One UI 9.5 `64_32` (`SM-S948B`) | Kandidat GSI 9.5 |
| D3, D4 | XGSI One UI 9.0 | Referensi konfigurasi saja |

Detail dan sumber ada di [ROADMAP.md](ROADMAP.md). Metadata itu berasal dari halaman distribusi dan belum diverifikasi dari binary.

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

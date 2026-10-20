# MoraRepublic — Scraper Leads + Dashboard

Kumpulkan data bisnis (kos, hotel, kafe, sekolah, dll.) dari **OpenStreetMap**,
cek jangkauan **FTTH/FWA** (SheetDB), lalu tampilkan di dashboard **Streamlit**.
Aplikasi ini hanya **mengumpulkan dan menampilkan** data — tidak mengirim
WhatsApp / email apa pun.

## Struktur Proyek

```
morarep-scrappers/
├── morarepublic.py            # Scraper utama (bisa dipakai dari terminal/CLI)
├── app.py                     # Dashboard Streamlit + riwayat scraping
├── requirements.txt           # Daftar paket Python
├── morarepublic_history.db    # (dibuat otomatis) database riwayat scraping
├── index.ipynb                # Notebook dokumentasi cara pakai CLI
└── venv/                      # Virtual environment Python
```

## Persyaratan

- Windows
- Python 3.14
- Koneksi internet (akses Nominatim, Overpass, SheetDB)

## 1. Aktifkan Virtual Environment (venv)

Buka terminal di folder proyek:

```powershell
cd E:\DataAnalyst\morarep-scrappers
```

**PowerShell:**

```powershell
.\venv\Scripts\Activate.ps1
```

**CMD:**

```bat
venv\Scripts\activate.bat
```

Setelah aktif, awal prompt berubah jadi `(venv)`. Semua perintah `python`
dan `pip` di bawah ini dijalankan dalam keadaan venv aktif.

> Jika PowerShell menolak dengan pesan _running scripts is disabled_,
> jalankan ini sekali di sesi terminal itu, lalu ulangi aktivasi:
>
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```

## 2. Install Paket (sekali saja, atau kalau requirements berubah)

```powershell
pip install -r requirements.txt
```

Isi `requirements.txt`: `streamlit`, `pandas`, `requests`, `beautifulsoup4`.

## 3. Jalankan Dashboard

```powershell
streamlit run app.py
```

Browser terbuka otomatis ke `http://localhost:8501`. Isi email kontak di
sidebar (syarat pemakaian Nominatim/Overpass), atur parameter, klik
**Cari leads**.

### Riwayat Scraping

- Setiap pencarian yang berhasil **otomatis tersimpan** ke database:
  - **Di komputer sendiri**: file `morarepublic_history.db` (SQLite) di folder proyek.
  - **Saat deploy** (Streamlit Cloud dll): database hosted (Postgres/Supabase)
    lewat Secret `DATABASE_URL` — lihat bagian [Deploy ke Streamlit Cloud](#deploy-ke-streamlit-cloud).
- Buka tab **Riwayat scraping** untuk melihat sesi-sesi sebelumnya:
  metrics, tabel, peta, unduh CSV per sesi, hapus sesi.
- Backup lokal cukup dengan menyalin file `.db` tersebut.
  (File tidak bisa dihapus saat dashboard sedang berjalan — tutup dulu.)

### Unduh Hasil

Di tab **Hasil**, tombol **Unduh CSV** mengunduh data sesuai filter
yang sedang aktif. Di tab riwayat, tiap sesi punya tombol unduh sendiri.

## 4. Jalankan Scraper dari Terminal (tanpa dashboard)

Dengan venv aktif, contoh perintah:

```powershell
# per kota, beberapa segmen
python morarepublic.py --kota "Banjarmasin" --kategori kos,hotel,perumahan

# titik pusat + radius
python morarepublic.py --pusat "-3.4425,114.8325" --radius-km 3 --kategori kos,kafe,sekolah

# dengan cek jangkauan FTTH/FWA
python morarepublic.py --kota "Banjarmasin" --kategori kos --radius-ftth 200 --radius-fwa 800

# analisis website bisnis (lebih lambat)
python morarepublic.py --kota "Banjarmasin" --kategori hotel --enrich

# lihat daftar segmen yang tersedia
python morarepublic.py --list-kategori
```

Hasil default tersimpan ke `morarepublic.csv` (ubah dengan `--output namafile.csv`).

## Matikan venv

```powershell
deactivate
```

## Deploy ke Streamlit Cloud

Filesystem Streamlit Community Cloud **sementara**: file yang ditulis saat
runtime (termasuk SQLite) hilang tiap app di-restart/redeploy. Karena itu
versi deploy memakai database hosted:

1. Buat database Postgres gratis, misalnya [Supabase](https://supabase.com)
   atau [Neon](https://neon.tech). Catat connection string-nya.
2. Push repo ini ke GitHub, lalu deploy di <https://share.streamlit.io>.
3. Di Streamlit Cloud: **App settings → Secrets**, tambahkan:

   ```toml
   DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/NAMADB"
   ```

4. `app.py` otomatis memakai Postgres kalau secret tersebut ada; kalau tidak
   ada, fallback ke SQLite lokal. Tidak perlu mengubah kode.

Di lokal pun bisa memakai Postgres dengan cara yang sama lewat environment
variable `DATABASE_URL`.

## Apakah `morarepublic_history.db` Aman Dipublish?

**Tidak disarankan.** File tersebut berisi hasil scraping: nama bisnis,
alamat, nomor WhatsApp/telepon, dan email. Menaruhnya di repo publik sama
dengan menyebarkan data kontak itu. `.gitignore` sudah mengecualikannya
(`*.db`). Kalau tidak sengaja sudah ter-commit, hapus dari riwayat git, bukan
sekadar dari commit terakhir.

Terkait data sumber: hasil scraping berasal dari OpenStreetMap (lisensi
ODbL) — jika dipublikasikan ulang, sertakan atribusi dan ikuti ketentuan
lisensinya.

URL SheetDB (`FTTH_URL` / `FWA_URL` di `morarepublic.py`) adalah endpoint
baca publik tanpa kunci. Kalau repo dipublikasikan, orang lain bisa ikut
memakai kuota SheetDB kamu. Kalau kuota jadi masalah, pindahkan URL ke
Secret/environment variable dengan pola yang sama seperti `DATABASE_URL`.

## Troubleshooting

| Masalah                                                                               | Penyebab & Solusi                                                                                                                                                                                |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ModuleNotFoundError: No module named 'requests'` (atau `streamlit`, `pandas`, `bs4`) | Paket belum terinstall di environment yang sedang aktif. Aktifkan venv lalu `pip install -r requirements.txt`.                                                                                   |
| `ModuleNotFoundError: No module named 'morarepublic'` saat jalankan `app.py`          | Python tidak melihat folder skrip (Python Laragon berjalan mode _isolated_ karena ada `python314._pth`). `app.py` sudah punya penanganan otomatis. Untuk CLI, jalankan dari dalam folder proyek. |
| `ModuleNotFoundError: No module named 'morarepublic'` padahal file ada                | File mungkin terhapus — cek **Recycle Bin**. `morarepublic.py` harus satu folder dengan `app.py`.                                                                                                |
| Aktivasi venv gagal di PowerShell                                                     | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, lalu ulangi.                                                                                                                       |
| `streamlit` tidak dikenali                                                            | Pakai `python -m streamlit run app.py`, atau aktifkan venv dulu.                                                                                                                                 |
| Riwayat kosong / hilang                                                               | File `morarepublic_history.db` mungkin terhapus; riwayat lama tidak bisa dikembalikan kecuali dari backup.                                                                                       |

## Catatan Pemakaian yang Bertanggung Jawab

- **Wajib** isi email kontak yang benar di dashboard / sertakan identitas di
  User-Agent saat pakai CLI (`--email`) — ini syarat pemakaian Nominatim & Overpass.
- Data berasal dari OpenStreetMap (ODbL). Hormati ketentuan lisensi saat
  mempublikasikan ulang.
- Aplikasi ini tidak mengirim pesan apa pun ke siapa pun; hasil hanya data
  publik yang dikumpulkan dan ditampilkan.

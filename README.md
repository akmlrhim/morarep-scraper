# MoraRepublic - Scraper Leads + Dashboard

MoraRepublic adalah tools gratis untuk mengumpulkan data bisnis (kos, hotel,
kafe, sekolah, dll.) dari **OpenStreetMap**, mengecek jangkauan **FTTH/FWA**
lewat SheetDB, dan menampilkan hasilnya di dashboard **Streamlit**. Cocok
buat kamu yang sedang meriset area layanan WiFi/Fiber.

Aplikasi ini hanya **mengumpulkan dan menampilkan** data, tidak mengirim
WhatsApp / email apa pun.

## Apa yang Kamu Dapatkan

- **Dashboard interaktif**: cari leads per kota atau titik pusat + radius,
  filter berdasarkan skor/segmen/jangkauan, lihat peta sebaran.
- **Riwayat scraping**: setiap pencarian tersimpan otomatis (SQLite lokal
  atau Postgres saat deploy), bisa dibuka ulang kapan saja.
- **Cek jangkauan FTTH/FWA**: tiap leads dinilai dalam/luar jangkauan
  berdasarkan titik ODP dan site FWA dari SheetDB.
- **Skor prospek otomatis**: leads diurutkan dari potensi terbesar,
  lengkap dengan alasan skornya.
- **Ekspor CSV**: unduh hasil sesuai filter yang sedang aktif.
- **Mode CLI**: semua fitur bisa dipakai tanpa dashboard lewat terminal.
- **Analisis website (opsional)**: kunjungi website bisnis untuk menemukan
  email, WhatsApp, dan sebutan kompetitor. Tidak mengirim apa pun.

## Struktur Proyek

```
morarep-scrappers/
├── morarepublic.py            # Scraper utama (bisa dipakai dari terminal/CLI)
├── app.py                     # Dashboard Streamlit + riwayat scraping
├── requirements.txt           # Daftar paket Python
├── morarepublic_history.db    # (dibuat otomatis) database riwayat scraping
└── index.ipynb                # Notebook dokumentasi cara pakai CLI
```

Folder `venv/` tidak ikut di repo, kamu buat sendiri di langkah berikut.

## Persyaratan

- Windows / Linux / macOS
- Python 3.14 (versi 3.x lain besar kemungkinan juga jalan)
- Koneksi internet (akses Nominatim, Overpass, SheetDB)
- Git (untuk clone repo)

## 1. Clone Repo & Buat Virtual Environment

Clone repo ini, lalu masuk ke foldernya:

```powershell
git clone <URL-repo-ini>
cd morarep-scrappers
```

Buat virtual environment baru:

```powershell
python -m venv venv
```

Aktifkan:

**PowerShell:**

```powershell
.\venv\Scripts\Activate.ps1
```

**CMD:**

```bat
venv\Scripts\activate.bat
```

**Linux / macOS:**

```bash
source venv/bin/activate
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

Isi `requirements.txt`: `streamlit`, `pandas`, `requests`, `beautifulsoup4`,
`sqlalchemy`.

## 3. Jalankan Dashboard

```powershell
streamlit run app.py
```

Browser terbuka otomatis ke `http://localhost:8501`. Isi email kontak di
sidebar (syarat pemakaian Nominatim/Overpass), atur parameter, klik
**Cari leads**.

### Riwayat Scraping

- Setiap pencarian yang berhasil **otomatis tersimpan**:
  - **Di komputermu**: file `morarepublic_history.db` (SQLite) di folder proyek.
  - **Saat deploy** (Streamlit Cloud dll): database hosted (Postgres/Supabase)
    lewat Secret `DATABASE_URL`, lihat bagian [Deploy ke Streamlit Cloud](#deploy-ke-streamlit-cloud).
- Buka tab **Riwayat scraping** untuk melihat sesi-sesi sebelumnya:
  metrics, tabel, peta, unduh CSV per sesi, hapus sesi.
- Backup lokal cukup dengan menyalin file `.db` tersebut.
  (File tidak bisa dihapus saat dashboard sedang berjalan, tutup dulu.)

### Unduh Hasil

Di tab **Hasil**, tombol **Unduh CSV** mengunduh data sesuai filter
yang sedang aktif. Di tab riwayat, tiap sesi punya tombol unduh sendiri.

## Kamus Istilah di Sidebar

Beberapa istilah di sidebar dashboard mungkin asing. Ini artinya:

| Istilah di Sidebar | Artinya |
| --- | --- |
| **Area: Per kota** | Mencari leads di seluruh wilayah satu kota (dikirim ke Nominatim untuk mendapatkan batas wilayahnya). |
| **Area: Titik pusat + radius** | Mencari leads dalam lingkaran dari satu koordinat (lat,lon) dengan jarak tertentu. Cocok kalau target kamu cuma sekitar lokasi tertentu. |
| **Radius (km)** | Jarak lingkaran pencarian dari titik pusat (mode titik pusat). |
| **Segmen** | Jenis tempat yang dicari: kos, hotel, perumahan, apartemen, sekolah, klinik, coworking, kantor, kafe, gym, toko. Sumber datanya tag/label di OpenStreetMap. |
| **Bobot** (di belakang tiap segmen) | Nilai potensi segmen itu: makin tinggi bobot, makin besar kontribusinya ke skor leads. Contoh: kos dan hotel bobot 5 (calon pelanggan banyak), toko bobot 2. |
| **Maks. leads** | Batas jumlah hasil yang disimpan per pencarian. |
| **Cek jangkauan FTTH/FWA** | Menyocokkan lokasi tiap leads dengan titik jaringan milik ISP (dari SheetDB) supaya tahu leads itu masuk area layanan atau tidak. |
| **FTTH** | *Fiber To The Home*: internet serat optik sampai ke pelanggan. Kecepatan dan stabilitas paling tinggi. Leads "dalam jangkauan FTTH" berarti dekat dengan titik ODP. |
| **FWA** | *Fixed Wireless Access*: internet lewat sinyal radio dari menara/site ke rumah, tanpa kabel. Kualitas biasanya di bawah FTTH, tapi menjangkau area yang belum terjangkau kabel. |
| **ODP** | *Optical Distribution Point*: titik pembagian kabel serat optik terdekat dengan pelanggan. Makin dekat leads ke ODP, makin murah dan cepat pemasangan FTTH. |
| **Radius FTTH (m)** | Leads dianggap terjangkau FTTH kalau jaraknya ke ODP terdekat tidak lebih dari nilai ini (default 250 m). |
| **Radius FWA (m)** | Sama, tapi untuk site FWA terdekat (default 1000 m), karena sinyal radio boleh lebih jauh. |
| **Hanya yang dalam jangkauan** | Buang leads yang tidak masuk radius FTTH maupun FWA, sehingga hasilnya cuma calon pelanggan yang realistis dilayani. |
| **Unduh ulang data jangkauan** | Data titik FTTH/FWA di-cache di `coverage_cache.json` supaya hemat kuota SheetDB. Centang ini kalau sheet barusan kamu update dan ingin ambil data terbaru. |
| **Analisis website bisnis** | Membuka website tiap leads untuk mencari email, nomor WhatsApp, dan sebutan kompetitor (IndiHome, Biznet, dll.). Hasilnya sinyal tambahan untuk skor. Lebih lambat karena membuka banyak situs. |
| **Thread** | Jumlah website yang dibuka paralel saat analisis website (1-8). Makin besar makin cepat, tapi makin berat ke server target, cukup 4. |
| **Jeda antar request (detik)** | Jeda tiap thread sebelum membuka halaman berikutnya. Jaga tetap ada (±1 detik) supaya tidak dianggap serangan oleh server tujuan. |
| **Email kontak** (di atas) | Identitas kamu yang dikirim ke API Nominatim/Overpass sebagai User-Agent, sesuai kewajiban syarat pemakaian keduanya. Wajib diisi, tapi tidak dipakai untuk menghubungi siapa pun. |
| **Skor** (di tabel hasil) | Angka hasil penilaian otomatis: bobot segmen + jangkauan + kapasitas + kelengkapan kontak. Makin tinggi, makin layak dihubungi duluan. |
| **Jangkauan** (di tabel hasil) | Status leads: `FTTH` (dalam jangkauan serat optik), `FWA` (cuma terjangkau radio), atau `tidak` (di luar keduanya). |

Istilah pendukung yang muncul di README dan kode:

| Istilah | Artinya |
| --- | --- |
| **SheetDB** | Layanan yang mengubah Google Sheet jadi API. Dipakai untuk menyimpan daftar titik ODP dan site FWA. |
| **Overpass API** | Mesin pencari data OpenStreetMap, dipakai untuk mengambil daftar tempat per kota/radius. |
| **Nominatim** | Layanan geocoding OpenStreetMap, mengubah nama kota jadi batas wilayah, dan mengambil koordinat. |
| **Enrichment** | Tahap memperkaya data leads dengan info tambahan (dari website bisnis) setelah data dasar terkumpul. |

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

> Sebelum pakai CLI, ganti `CONTACT_EMAIL` di bagian atas `morarepublic.py`
> dengan email kamu, karena itu identitas yang dikirim ke API Nominatim/Overpass.

## Matikan venv

```powershell
deactivate
```

## Deploy ke Streamlit Cloud

Filesystem Streamlit Community Cloud **sementara**: file yang ditulis saat
runtime (termasuk SQLite) hilang tiap app di-restart/redeploy. Kalau kamu
men-deploy versi kamu, pakai database hosted:

1. Buat database Postgres gratis, misalnya [Supabase](https://supabase.com)
   atau [Neon](https://neon.tech). Catat connection string-nya.
2. Push repo kamu ke GitHub, lalu deploy di <https://share.streamlit.io>.
3. Di Streamlit Cloud: **App settings → Secrets**, tambahkan:

   ```toml
   DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/NAMADB"
   ```

4. `app.py` otomatis memakai Postgres kalau secret tersebut ada; kalau tidak
   ada, fallback ke SQLite lokal. Tidak perlu mengubah kode.

Di lokal pun bisa memakai Postgres dengan cara yang sama lewat environment
variable `DATABASE_URL`.

## Hal yang Perlu Kamu Tahu Soal Data

- **Jangan pernah push `morarepublic_history.db` ke repo publik.** File itu
  berisi hasil scraping: nama bisnis, alamat, nomor WhatsApp/telepon, dan
  email; menyebarluaskannya berarti menyebarluaskan data kontak orang lain.
  `.gitignore` di repo ini sudah mengecualikannya (`*.db`), jadi biarkan
  begitu. Kalau tidak sengaja sudah ter-commit, hapus dari riwayat git,
  bukan sekadar dari commit terakhir.
- **Data sumber berasal dari OpenStreetMap (lisensi ODbL).** Kalau kamu
  mempublikasikan ulang hasil scraping, sertakan atribusi dan ikuti
  ketentuan lisensinya.
- **URL SheetDB bawaan** (`FTTH_URL` / `FWA_URL` di `morarepublic.py`)
  adalah endpoint baca publik tanpa kunci yang dipakai bersama. Kalau kamu
  serius memakai tools ini, buat sheet dan endpoint SheetDB milikmu sendiri,
  lalu arahkan lewat `--ftth-url` / `--fwa-url` (CLI) atau ganti konstanta
  di file, dengan begitu kuota tidak bergantung pada pihak lain.

## Troubleshooting

| Masalah                                                                               | Penyebab & Solusi                                                                                                                                                                |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ModuleNotFoundError: No module named 'requests'` (atau `streamlit`, `pandas`, `bs4`) | Paket belum terinstall di environment yang sedang aktif. Aktifkan venv lalu `pip install -r requirements.txt`.                                                                   |
| `ModuleNotFoundError: No module named 'morarepublic'` saat jalankan `app.py`          | Python tidak melihat folder skrip (beberapa distribusi Python berjalan mode _isolated_). `app.py` sudah punya penanganan otomatis. Untuk CLI, jalankan dari dalam folder proyek. |
| `ModuleNotFoundError: No module named 'morarepublic'` padahal file ada                | File mungkin terhapus, cek **Recycle Bin**. `morarepublic.py` harus satu folder dengan `app.py`.                                                                                |
| Aktivasi venv gagal di PowerShell                                                     | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, lalu ulangi.                                                                                                       |
| `streamlit` tidak dikenali                                                            | Pakai `python -m streamlit run app.py`, atau aktifkan venv dulu.                                                                                                                 |
| Riwayat kosong / hilang                                                               | File `morarepublic_history.db` mungkin terhapus; riwayat lama tidak bisa dikembalikan kecuali dari backup.                                                                       |

## Catatan Pemakaian yang Bertanggung Jawab

- **Wajib** isi email kontak yang benar di dashboard, dan ganti
  `CONTACT_EMAIL` di `morarepublic.py` kalau pakai CLI, karena itu syarat
  pemakaian Nominatim & Overpass.
- Data berasal dari OpenStreetMap (ODbL). Hormati ketentuan lisensi saat
  mempublikasikan ulang.
- Aplikasi ini tidak mengirim pesan apa pun ke siapa pun; hasilnya hanya
  data publik yang dikumpulkan dan ditampilkan.

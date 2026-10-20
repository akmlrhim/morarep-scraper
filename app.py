"""
Dashboard Streamlit untuk MoraRepublic.

Taruh file ini satu folder dengan morarepublic.py, lalu jalankan:
    pip install streamlit pandas requests beautifulsoup4
    streamlit run app.py

Aplikasi ini hanya MENGUMPULKAN dan MENAMPILKAN data. Tidak ada fitur kirim
WhatsApp / email apa pun.

Setiap pencarian yang berhasil otomatis tersimpan ke SQLite
(morarepublic_history.db) sehingga bisa dilihat ulang di tab "Riwayat scraping".
"""

import contextlib
import io
import os
import sys
import tempfile
import time

import pandas as pd
import streamlit as st

# Pastikan folder file ini ada di sys.path, supaya `import morarepublic`
# selalu berhasil walau Python berjalan dalam mode isolated (mis. ada
# python314._pth dari Laragon yang menghapus folder skrip dari sys.path).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import morarepublic as L

OUT_PATH = os.path.join(tempfile.gettempdir(), "morarepublic_streamlit.csv")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "morarepublic_history.db")


# ----------------------------------------------------------------------------
# Penyimpanan riwayat (SQLite lokal, atau Postgres hosted saat deploy)
#
# Lokal    : file morarepublic_history.db (SQLite), tanpa setup apa pun.
# Deploy   : isi Secret "DATABASE_URL" di Streamlit Cloud, contoh:
#            postgresql+psycopg://user:password@host:5432/namadb
#            sehingga riwayat tetap ada walau app di-restart/redeploy.
# ----------------------------------------------------------------------------
@st.cache_resource
def _engine():
    """Engine SQLAlchemy: Postgres kalau ada DATABASE_URL, selain itu SQLite lokal."""
    try:
        url = st.secrets.get("DATABASE_URL", "")
    except Exception:
        url = os.environ.get("DATABASE_URL", "")
    if not url:
        url = "sqlite:///" + DB_PATH
    from sqlalchemy import create_engine
    return create_engine(url, pool_pre_ping=True)


def new_run_id():
    from sqlalchemy import text
    rid = time.strftime("%Y%m%d-%H%M%S")
    try:
        with _engine().connect() as con:
            ada = con.execute(
                text("SELECT 1 FROM runs WHERE run_id = :rid"), {"rid": rid}
            ).fetchone()
        if ada:  # bentrok detik yang sama, tambah akhiran unik
            rid += "-" + os.urandom(2).hex()
    except Exception:
        pass  # tabel belum ada (jalanan pertama) — pakai ID apa adanya
    return rid


def save_run(df, meta):
    """Simpan satu hasil scraping (metadata + semua baris) ke database."""
    run_id = new_run_id()
    eng = _engine()
    pd.DataFrame([{"run_id": run_id, **meta}]).to_sql(
        "runs", eng, if_exists="append", index=False
    )
    out = df.copy()
    out.insert(0, "run_id", run_id)
    out.to_sql("leads", eng, if_exists="append", index=False)
    return run_id


def load_runs():
    """Ambil daftar semua sesi scraping (terbaru dulu)."""
    try:
        return pd.read_sql("SELECT * FROM runs ORDER BY run_id DESC", _engine())
    except Exception:
        return pd.DataFrame()  # database belum ada / kosong


def load_leads(run_id):
    """Ambil semua baris leads milik satu sesi."""
    from sqlalchemy import text
    df = pd.read_sql(
        text("SELECT * FROM leads WHERE run_id = :rid"),
        _engine(),
        params={"rid": run_id},
    )
    return df.drop(columns=["run_id"]).fillna("")


def delete_run(run_id):
    from sqlalchemy import text
    with _engine().begin() as con:
        con.execute(text("DELETE FROM runs WHERE run_id = :rid"), {"rid": run_id})
        con.execute(text("DELETE FROM leads WHERE run_id = :rid"), {"rid": run_id})


st.set_page_config(page_title="MoraRepublic", layout="wide")
st.title("MoraRepublic")

# ----------------------------------------------------------------------------
# Sidebar: parameter pencarian
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("Pencarian")

    email = st.text_input(
        "Email kontak (untuk User-Agent)",
        value="",
        placeholder="emailkamu@domain.com",
        help="Syarat pemakaian Nominatim/Overpass: identitas yang jelas.",
    )

    mode = st.radio("Area", ["Per kota", "Titik pusat + radius"], horizontal=True)
    if mode == "Per kota":
        kota = st.text_input("Kota", value="Banjarmasin")
        pusat, radius_km = "", 3.0
    else:
        pusat = st.text_input("Titik pusat (lat,lon)", value="-3.4425,114.8325")
        radius_km = st.slider("Radius (km)", 0.5, 10.0, 3.0, 0.5)
        kota = ""

    kategori = st.multiselect(
        "Segmen",
        options=list(L.KATEGORI.keys()),
        default=["kos", "hotel"],
        format_func=lambda k: f"{k} (bobot {L.KATEGORI[k]['bobot']})",
    )
    limit = st.number_input("Maks. leads", 10, 2000, 300, step=10)

    st.header("Jangkauan")
    cek_jangkauan = st.checkbox("Cek jangkauan FTTH/FWA", value=True)
    radius_ftth = st.number_input("Radius FTTH (m)", 50, 2000, 250, step=50, disabled=not cek_jangkauan)
    radius_fwa = st.number_input("Radius FWA (m)", 100, 5000, 1000, step=100, disabled=not cek_jangkauan)
    hanya = st.checkbox("Hanya yang dalam jangkauan", value=False, disabled=not cek_jangkauan)
    refresh = st.checkbox("Unduh ulang data jangkauan", value=False, disabled=not cek_jangkauan)

    st.header("Lanjutan")
    enrich = st.checkbox(
        "Analisis website bisnis (lebih lambat)",
        value=False,
        help="Membuka halaman publik website untuk membaca email/WA yang tertulis, "
             "sebutan WiFi, dan provider kompetitor. Tidak mengirim apa pun.",
    )
    workers = st.slider("Thread", 1, 8, 4, disabled=not enrich)
    delay = st.slider("Jeda antar request (detik)", 0.5, 5.0, 1.0, 0.5, disabled=not enrich)

    jalankan = st.button("Cari leads", type="primary", width="stretch")


# ----------------------------------------------------------------------------
# Jalankan pencarian
# ----------------------------------------------------------------------------
def build_argv():
    argv = [
        "--kategori", ",".join(kategori),
        "--limit", str(int(limit)),
        "--output", OUT_PATH,
        "--radius-ftth", str(int(radius_ftth)),
        "--radius-fwa", str(int(radius_fwa)),
        "--workers", str(int(workers)),
        "--delay", str(float(delay)),
    ]
    if mode == "Per kota":
        argv += ["--kota", kota.strip()]
    else:
        argv += ["--pusat", pusat.strip(), "--radius-km", str(radius_km)]
    if not cek_jangkauan:
        argv.append("--tanpa-jangkauan")
    else:
        if hanya:
            argv.append("--hanya-dalam-jangkauan")
        if refresh:
            argv.append("--refresh")
    if enrich:
        argv.append("--enrich")
    return argv


if jalankan:
    if not kategori:
        st.error("Pilih minimal satu segmen.")
    elif mode == "Per kota" and not kota.strip():
        st.error("Isi nama kota.")
    elif not email.strip() or "@" not in email:
        st.error("Isi email kontak yang valid (syarat pemakaian Nominatim/Overpass).")
    else:
        # pasang identitas di User-Agent (dict HEADERS dipakai bersama oleh semua fungsi)
        ua = f"MoraRepublic/1.0 (riset area layanan; {email.strip()})"
        L.USER_AGENT = ua
        L.HEADERS["User-Agent"] = ua

        if os.path.exists(OUT_PATH):
            os.remove(OUT_PATH)

        buf = io.StringIO()
        error_msg = ""
        with st.spinner("Mengambil data... (bisa sekitar satu menit)"):
            try:
                with contextlib.redirect_stdout(buf):
                    L.main(build_argv())
            except SystemExit as e:  # skrip memakai sys.exit(pesan) untuk error fatal
                error_msg = str(e.code) if e.code not in (None, 0) else ""
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"

        st.session_state["log"] = buf.getvalue()
        st.session_state["error"] = error_msg
        if os.path.exists(OUT_PATH):
            df_baru = pd.read_csv(
                OUT_PATH, encoding="utf-8-sig",
                dtype={"telepon": str, "whatsapp": str, "email": str},
            ).fillna("")
            st.session_state["df"] = df_baru

            # simpan ke riwayat
            area = kota.strip() if mode == "Per kota" else f"{pusat.strip()} (radius {radius_km} km)"
            try:
                run_id = save_run(
                    df_baru,
                    {
                        "waktu": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "mode": mode,
                        "area": area,
                        "kategori": ", ".join(kategori),
                        "cek_jangkauan": "Ya" if cek_jangkauan else "Tidak",
                        "enrich": "Ya" if enrich else "Tidak",
                        "jumlah_leads": len(df_baru),
                    },
                )
                st.session_state["last_run_id"] = run_id
                st.toast(f"Riwayat tersimpan: {run_id}")
            except Exception as e:
                st.warning(f"Gagal menyimpan riwayat: {type(e).__name__}: {e}")
        else:
            st.session_state.pop("df", None)


tab_hasil, tab_riwayat = st.tabs(["Hasil", "Riwayat scraping"])

# ----------------------------------------------------------------------------
# Tab hasil
# ----------------------------------------------------------------------------
with tab_hasil:
    df = st.session_state.get("df")
    log = st.session_state.get("log", "")
    error_msg = st.session_state.get("error", "")

    if error_msg:
        st.error(error_msg)

    if df is None:
        if log:
            st.warning("Tidak ada file hasil. Lihat log di bawah untuk penyebabnya.")
        else:
            st.info("Atur parameter di sidebar, lalu klik **Cari leads**.")
    else:
        # filter
        c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
        skor_min = c1.slider("Skor minimum", int(df["skor"].min()), int(df["skor"].max()), int(df["skor"].min()))
        opsi_jangkauan = sorted(x for x in df["jangkauan"].unique() if x)
        pilih_jangkauan = c2.multiselect("Jangkauan", opsi_jangkauan, default=opsi_jangkauan)
        pilih_segmen = c3.multiselect("Segmen", sorted(df["segmen"].unique()), default=sorted(df["segmen"].unique()))
        cari = c4.text_input("Cari nama / alamat")
        hanya_kontak = st.checkbox("Hanya yang punya kontak (WhatsApp / telepon / email)")

        f = df[(df["skor"] >= skor_min) & (df["segmen"].isin(pilih_segmen))]
        if opsi_jangkauan:
            f = f[f["jangkauan"].isin(pilih_jangkauan)]
        if cari.strip():
            q = cari.strip().lower()
            f = f[f["nama"].str.lower().str.contains(q, na=False) | f["alamat"].str.lower().str.contains(q, na=False)]
        if hanya_kontak:
            f = f[(f["whatsapp"] != "") | (f["telepon"] != "") | (f["email"] != "")]

        # ringkasan
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total leads", len(f))
        m2.metric("FTTH", int((f["jangkauan"] == "FTTH").sum()))
        m3.metric("FWA saja", int((f["jangkauan"] == "FWA").sum()))
        m4.metric("Punya WhatsApp", int((f["whatsapp"] != "").sum()))
        m5.metric("Skor ≥ 10", int((f["skor"] >= 10).sum()))

        tab_tabel, tab_peta = st.tabs(["Tabel", "Peta"])
        with tab_tabel:
            st.dataframe(
                f,
                width="stretch",
                hide_index=True,
                column_config={
                    "maps_link": st.column_config.LinkColumn("Maps", display_text="buka"),
                    "website": st.column_config.LinkColumn("Website"),
                    "skor": st.column_config.NumberColumn("Skor", format="%d"),
                },
            )
        with tab_peta:
            peta = f[["latitude", "longitude"]].apply(pd.to_numeric, errors="coerce").dropna()
            if peta.empty:
                st.info("Tidak ada koordinat untuk ditampilkan.")
            else:
                st.map(peta)

        st.download_button(
            "Unduh CSV (sesuai filter)",
            data=f.to_csv(index=False).encode("utf-8-sig"),
            file_name="morarepublic.csv",
            mime="text/csv",
        )

    if log:
        with st.expander("Log proses"):
            st.code(log)

# ----------------------------------------------------------------------------
# Tab riwayat scraping
# ----------------------------------------------------------------------------
with tab_riwayat:
    runs = load_runs()
    if runs.empty:
        st.info(
            "Belum ada riwayat"
        )
    else:
        pilihan = st.selectbox(
            "Pilih sesi",
            options=runs["run_id"].tolist(),
            format_func=lambda rid: "  •  ".join(
                str(runs.loc[runs["run_id"] == rid].iloc[0][c])
                for c in ("waktu", "area", "kategori", "jumlah_leads")
            ),
        )
        row = runs[runs["run_id"] == pilihan].iloc[0]

        info = st.columns(6)
        info[0].metric("Total leads", int(row["jumlah_leads"]))
        info[1].metric("Mode", row["mode"])
        info[2].metric("Jangkauan", row["cek_jangkauan"])
        info[3].metric("Enrich", row["enrich"])

        st.caption(
            f"{row['waktu']}  •  {row['area']}  •  {row['kategori']}"
        )

        try:
            df_hist = load_leads(pilihan)
        except Exception as e:
            st.error(f"Gagal membaca data sesi: {type(e).__name__}: {e}")
            df_hist = pd.DataFrame()

        aksi1, aksi2 = st.columns([1, 1])
        with aksi1:
            if not df_hist.empty:
                st.download_button(
                    "Unduh CSV sesi ini",
                    data=df_hist.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"morarepublic_{pilihan}.csv",
                    mime="text/csv",
                    width="stretch",
                )
        with aksi2:
            if st.button("Hapus sesi ini", width="stretch"):
                delete_run(pilihan)
                st.rerun()

        if df_hist.empty:
            st.warning("Baris data sesi ini tidak ditemukan di database.")
        else:
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("FTTH", int((df_hist["jangkauan"] == "FTTH").sum()))
            h2.metric("FWA saja", int((df_hist["jangkauan"] == "FWA").sum()))
            h3.metric("Punya WhatsApp", int((df_hist["whatsapp"] != "").sum()))
            h4.metric("Skor ≥ 10", int((df_hist["skor"].fillna(0).astype(int) >= 10).sum()))

            tab_h_tabel, tab_h_peta = st.tabs(["Tabel", "Peta"])
            with tab_h_tabel:
                st.dataframe(
                    df_hist,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "maps_link": st.column_config.LinkColumn("Maps", display_text="buka"),
                        "website": st.column_config.LinkColumn("Website"),
                        "skor": st.column_config.NumberColumn("Skor", format="%d"),
                    },
                )
            with tab_h_peta:
                peta = df_hist[["latitude", "longitude"]].apply(pd.to_numeric, errors="coerce").dropna()
                if peta.empty:
                    st.info("Tidak ada koordinat untuk ditampilkan.")
                else:
                    st.map(peta)

        with st.expander("Hapus semua riwayat"):
            st.write("Menghapus **semua** sesi dan datanya secara permanen dari database.")
            yakin = st.checkbox("Saya yakin ingin menghapus semua riwayat")
            if st.button("Hapus semua", disabled=not yakin, type="primary"):
                from sqlalchemy import text
                with _engine().begin() as con:
                    con.execute(text("DELETE FROM leads"))
                    con.execute(text("DELETE FROM runs"))
                st.success("Semua riwayat terhapus.")
                st.rerun()

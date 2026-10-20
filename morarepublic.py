"""
Leads Finder untuk MoraRepublic (WiFi/Fiber, gratis, tanpa API key)

Sumber data : OpenStreetMap (Overpass API) + Nominatim untuk geocoding
Fokus       : tempat dengan banyak pengguna internet (kos, perumahan, apartemen,
              hotel, sekolah, klinik, kafe, kantor, coworking, dll.)
Fitur       : - cari per kota ATAU per titik pusat + radius
              - cek jangkauan otomatis dari data SheetDB: titik FTTH (ODP) & titik FWA
                (jarak terdekat, status FTTH / FWA / tidak, filter "dalam jangkauan")
              - (opsional) kunjungi website bisnis: email, WhatsApp, sosmed,
                sebutan WiFi, dan provider kompetitor yang terdeteksi
              - skor prospek (tanpa fitur kirim pesan, murni pengumpulan data)
Output      : CSV (utf-8-sig) diurutkan dari skor tertinggi

Install:
    pip install requests beautifulsoup4

Contoh:
    python morarepublic.py --kota "Banjarmasin" --kategori kos,hotel,perumahan
    python morarepublic.py --pusat "-3.4425,114.8325" --radius-km 3 --kategori kos,kafe,sekolah
    python morarepublic.py --kota "Banjarbaru" --kategori kos --hanya-dalam-jangkauan
    python morarepublic.py --kota "Banjarmasin" --kategori kos --radius-ftth 200 --radius-fwa 800
    python morarepublic.py --kota "Banjarmasin" --kategori kos --refresh      # unduh ulang data jangkauan
    python morarepublic.py --kota "Banjarmasin" --kategori kos --tanpa-jangkauan
    python morarepublic.py --kota "Banjarmasin" --kategori hotel --enrich
    python morarepublic.py --list-kategori

Data jangkauan diambil dari SheetDB (URL di FTTH_URL / FWA_URL, bisa diganti lewat
--ftth-url / --fwa-url) lalu disimpan di coverage_cache.json supaya kuota API hemat.
Kolom yang dibaca (tidak peka huruf besar/kecil): Latitude, Longitude, dan
"Nama Lokasi" atau "label". Koordinat berkoma desimal ("-3,435931") otomatis dikonversi.

Di Google Colab / Jupyter (argumen diberikan lewat list, bukan command line):
    # sel 1: install + jalankan isi file ini
    %pip install -q requests beautifulsoup4
    # sel 2:
    main(["--kota", "Banjarmasin", "--kategori", "kos,hotel,perumahan", "--hanya-dalam-jangkauan"])
Hasil CSV tersimpan di folder kerja Colab dan otomatis diunduh ke komputermu.

PENTING: ganti CONTACT_EMAIL dengan emailmu (syarat penggunaan Nominatim/Overpass).
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

IN_NOTEBOOK = "ipykernel" in sys.modules or "google.colab" in sys.modules

CONTACT_EMAIL = "akmalrahim376@gmail.com"
USER_AGENT = f"MoraRepublic/1.0 (riset area layanan; {CONTACT_EMAIL})"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "id,en;q=0.8"}

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def sel(key, values):
    return f'["{key}"~"^(' + "|".join(values) + ')$"]'


KATEGORI = {
    "kos": {
        "bobot": 5,
        "combos": [
            [sel("building", ["dormitory"])],
            [sel("tourism", ["hostel", "guest_house", "motel"])],
            ['["name"~"kost|kos |kontrakan|homestay|asrama",i]'],
        ],
    },
    "perumahan": {
        "bobot": 5,
        "combos": [
            ['["landuse"="residential"]',
             '["name"~"perumahan|cluster|residence|regency|griya|permata|villa|townhouse|komplek|kompleks",i]'],
        ],
    },
    "apartemen": {
        "bobot": 5,
        "combos": [[sel("building", ["apartments"])], [sel("tourism", ["apartment"])]],
    },
    "hotel": {
        "bobot": 5,
        "combos": [[sel("tourism", ["hotel", "resort", "guest_house", "hostel", "motel"])]],
    },
    "sekolah": {
        "bobot": 4,
        "combos": [[sel("amenity", ["school", "kindergarten", "college", "university", "language_school", "training"])]],
    },
    "klinik": {
        "bobot": 4,
        "combos": [[sel("amenity", ["clinic", "hospital", "dentist", "doctors"])]],
    },
    "coworking": {
        "bobot": 4,
        "combos": [[sel("office", ["coworking"])], [sel("amenity", ["coworking_space"])]],
    },
    "kantor": {
        "bobot": 3,
        "combos": [[sel("office", ["company", "government", "estate_agent", "insurance", "lawyer", "ngo", "financial"])]],
    },
    "kafe": {
        "bobot": 3,
        "combos": [[sel("amenity", ["cafe", "restaurant", "fast_food", "food_court"])]],
    },
    "gym": {
        "bobot": 3,
        "combos": [[sel("leisure", ["fitness_centre", "sports_centre"])]],
    },
    "toko": {
        "bobot": 2,
        "combos": [[sel("shop", ["supermarket", "convenience", "electronics", "mobile_phone", "computer", "copyshop"])]],
    },
}

COMPETITORS = {
    "IndiHome/Telkom": r"indihome|telkomsel|telkom\b",
    "Biznet": r"biznet",
    "MyRepublic": r"myrepublic|my republic",
    "First Media": r"first ?media",
    "ICONNET": r"iconnet|icon\+",
    "CBN": r"\bcbn\b",
    "Oxygen": r"oxygen\.id",
    "Indosat HiFi": r"hifi air|indosat",
}

JUNK_EMAIL = re.compile(r"(\.(png|jpe?g|gif|svg|webp|css|js)$|sentry|example\.|domain\.com|wixpress|@2x)", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
WA_RE = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=|whatsapp\.com/send\?phone=)\+?(\d{8,15})")
WIFI_RE = re.compile(r"wi-?fi|hotspot|internet|fiber|fibre", re.I)


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


FTTH_URL = "https://sheetdb.io/api/v1/6aeuma5j2lv3q"
FWA_URL = "https://sheetdb.io/api/v1/v36428t06dzby"
CACHE_FILE = "coverage_cache.json"


def to_float(v):
    """'-3,435931' -> -3.435931 (koma desimal ala Indonesia)."""
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def fetch_sheetdb(url, page=1000):
    rows, offset = [], 0
    while True:
        r = requests.get(url, params={"limit": page, "offset": offset}, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            sys.exit(f"Respons tak terduga dari {url}: {str(data)[:200]}")
        rows.extend(data)
        if len(data) < page:
            break
        offset += page
        time.sleep(0.5)
    return rows


def parse_points(rows):
    pts = []
    for row in rows:
        r = {str(k).strip().lower(): v for k, v in row.items()}
        lat = to_float(r.get("latitude") or r.get("lat"))
        lon = to_float(r.get("longitude") or r.get("lon") or r.get("lng"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        name = r.get("nama lokasi") or r.get("label") or r.get("nama") or ""
        pts.append((lat, lon, str(name).strip()))
    return pts


def load_coverage(ftth_url, fwa_url, refresh=False):
    cache = {}
    if not refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    out = {}
    for key, url in (("ftth", ftth_url), ("fwa", fwa_url)):
        if not url:
            out[key] = []
            continue
        if cache.get(key) and cache.get("urls", {}).get(key) == url:
            out[key] = [tuple(p) for p in cache[key]]
            print(f"[i] {key.upper()}: {len(out[key])} titik (dari cache)")
        else:
            out[key] = parse_points(fetch_sheetdb(url))
            print(f"[i] {key.upper()}: {len(out[key])} titik dimuat dari SheetDB")
        if not out[key]:
            print(f"[!] Data {key.upper()} kosong / kolom koordinat tidak terbaca.")
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"ftth": out["ftth"], "fwa": out["fwa"], "urls": {"ftth": ftth_url, "fwa": fwa_url}}, f)
    return out["ftth"], out["fwa"]


def nearest(lat, lon, pts):
    """Titik terdekat -> (jarak_meter, nama). (None, '') bila tidak ada dalam ~55 km."""
    best, name = None, ""
    for a, b, n in pts:
        if abs(a - lat) > 0.5 or abs(b - lon) > 0.5:
            continue
        d = haversine_m(lat, lon, a, b)
        if best is None or d < best:
            best, name = d, n
    return best, name


def geocode(kota):
    r = requests.get(
        NOMINATIM_URL,
        params={"q": kota, "format": "json", "limit": 1, "countrycodes": "id"},
        headers=HEADERS, timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        sys.exit(f"Lokasi '{kota}' tidak ditemukan.")
    s, n, w, e = map(float, data[0]["boundingbox"])
    print(f"[i] Area: {data[0]['display_name']}")
    return f"({s},{w},{n},{e})"


def build_query(combos, area):
    parts = [f'nwr{"".join(c)}["name"]{area};' for c in combos]
    return "[out:json][timeout:120];(" + "".join(parts) + ");out center tags;"


def fetch_overpass(query):
    last = None
    for url in OVERPASS_URLS:
        for _ in range(2):
            try:
                r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=150)
                if r.status_code == 200:
                    return r.json().get("elements", [])
                last = f"HTTP {r.status_code} dari {url}"
            except requests.RequestException as ex:
                last = str(ex)
            time.sleep(3)
    sys.exit(f"Overpass gagal: {last}")


def normalize_wa(phone):
    if not phone:
        return ""
    d = re.sub(r"\D", "", phone.split(";")[0])
    if d.startswith("0"):
        d = "62" + d[1:]
    elif d.startswith("8"):
        d = "62" + d
    return d if d.startswith("628") and 10 <= len(d) <= 15 else ""


def first_int(val):
    m = re.search(r"\d+", val or "")
    return int(m.group()) if m else 0


def to_lead(el, label):
    t = el.get("tags", {})
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    phone = t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or t.get("mobile") or ""
    alamat = ", ".join(x for x in [
        t.get("addr:street"), t.get("addr:housenumber"),
        t.get("addr:suburb") or t.get("addr:subdistrict"), t.get("addr:city"),
    ] if x)
    tipe = next((t[k] for k in ("tourism", "building", "amenity", "office", "shop", "leisure", "landuse") if k in t), "")
    kapasitas = max(first_int(t.get("rooms")), first_int(t.get("capacity")), first_int(t.get("beds")))
    ia = (t.get("internet_access") or "").lower()
    return {
        "segmen": label,
        "nama": t.get("name", "").strip(),
        "tipe_osm": tipe,
        "alamat": alamat,
        "telepon": phone.split(";")[0].strip(),
        "whatsapp": normalize_wa(phone),
        "email": (t.get("email") or t.get("contact:email") or "").strip(),
        "website": (t.get("website") or t.get("contact:website") or t.get("url") or "").strip(),
        "instagram": t.get("contact:instagram", "") or t.get("instagram", ""),
        "facebook": t.get("contact:facebook", "") or t.get("facebook", ""),
        "kapasitas": kapasitas or "",
        "wifi_osm": "ya" if ia in ("wlan", "yes", "wired", "wifi") else "",
        "latitude": lat,
        "longitude": lon,
        "maps_link": f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else "",
    }


def norm_url(u):
    if not u:
        return ""
    return u if re.match(r"^https?://", u, re.I) else "https://" + u


def allowed_by_robots(url):
    try:
        p = urlparse(url)
        r = requests.get(f"{p.scheme}://{p.netloc}/robots.txt", headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return True
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def get_html(url):
    r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
    if "html" not in r.headers.get("Content-Type", "").lower():
        raise ValueError("bukan HTML")
    return r


def extract(html, soup):
    emails = {a["href"][7:].split("?")[0].strip().lower() for a in soup.select('a[href^="mailto:"]')}
    emails.update(m.lower() for m in EMAIL_RE.findall(soup.get_text(" ")))
    emails = {e for e in emails if not JUNK_EMAIL.search(e)}
    wa = set(WA_RE.findall(html))
    soc = {"instagram": "", "facebook": ""}
    for a in soup.find_all("a", href=True):
        low = a["href"].lower()
        for k in soc:
            if f"{k}.com" in low and not soc[k] and not any(x in low for x in ("sharer", "share?", "intent", "/p/", "/reel/")):
                soc[k] = a["href"]
    return emails, wa, soc


def analyze_site(lead, delay):
    out = {"site_status": "", "wifi_disebut": "", "kompetitor": ""}
    url = norm_url(lead["website"])
    if not url:
        out["site_status"] = "tidak ada website"
        return out, set(), set(), {}
    if not allowed_by_robots(url):
        out["site_status"] = "diblokir robots.txt"
        return out, set(), set(), {}
    try:
        r = get_html(url)
    except Exception as ex:
        out["site_status"] = f"error: {type(ex).__name__}"
        return out, set(), set(), {}

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ")
    out["site_status"] = "ok"
    out["wifi_disebut"] = "ya" if WIFI_RE.search(text) else "tidak"
    out["kompetitor"] = ", ".join(n for n, rx in COMPETITORS.items() if re.search(rx, r.text, re.I))
    emails, wa, soc = extract(r.text, soup)

    if not emails:
        for a in soup.find_all("a", href=True):
            label = (a.get_text(" ") + a["href"]).lower()
            if any(k in label for k in ("kontak", "contact", "hubungi")):
                cu = urljoin(r.url, a["href"])
                if urlparse(cu).netloc == urlparse(r.url).netloc:
                    try:
                        time.sleep(delay)
                        r2 = get_html(cu)
                        e2, w2, s2 = extract(r2.text, BeautifulSoup(r2.text, "html.parser"))
                        emails |= e2
                        wa |= w2
                        for k, v in s2.items():
                            soc[k] = soc.get(k) or v
                    except Exception:
                        pass
                    break
    time.sleep(delay)
    return out, emails, wa, soc


def score_lead(l, coverage_on):
    score, why = KATEGORI[l["segmen"]]["bobot"], [f"segmen {l['segmen']}"] if l["segmen"] in KATEGORI else []
    if coverage_on:
        if l["jangkauan"] == "FTTH":
            score += 5; why.append(f"jangkauan FTTH (ODP {l['jarak_ftth_m']} m)")
        elif l["jangkauan"] == "FWA":
            score += 3; why.append(f"jangkauan FWA (site {l['jarak_fwa_m']} m)")
        else:
            score -= 6; why.append("di luar jangkauan FTTH/FWA")
    cap = l["kapasitas"] or 0
    if cap >= 50:
        score += 3; why.append(f"kapasitas besar ({cap})")
    elif cap >= 20:
        score += 2; why.append(f"kapasitas sedang ({cap})")
    elif cap >= 10:
        score += 1; why.append(f"kapasitas {cap}")
    if l["wifi_osm"] == "ya" or l.get("wifi_disebut") == "ya":
        score += 2; why.append("menyediakan/menyebut WiFi")
    if l["whatsapp"]:
        score += 2; why.append("ada WhatsApp")
    elif l["telepon"]:
        score += 1; why.append("ada telepon")
    if l["email"]:
        score += 1; why.append("ada email")
    if not (l["whatsapp"] or l["telepon"] or l["email"]):
        score -= 2; why.append("kontak tidak ditemukan")
    if l.get("kompetitor"):
        why.append(f"terdeteksi: {l['kompetitor']} (peluang switch)")
    return score, "; ".join(why)


FIELDS = [
    "skor", "alasan_skor", "segmen", "nama", "tipe_osm", "alamat", "telepon", "whatsapp",
    "email", "website", "kapasitas", "wifi_osm", "wifi_disebut", "kompetitor", "jangkauan",
    "jarak_ftth_m", "odp_terdekat", "jarak_fwa_m", "site_fwa_terdekat", "instagram", "facebook", "site_status", "latitude", "longitude", "maps_link",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description="MoraRepublic leads finder (OpenStreetMap, gratis)")
    ap.add_argument("--kota", help='Contoh: "Banjarmasin"')
    ap.add_argument("--pusat", help='Titik pusat "lat,lon", contoh: "-3.4425,114.8325"')
    ap.add_argument("--radius-km", type=float, default=3.0, help="Radius dari --pusat (default 3 km)")
    ap.add_argument("--kategori", default="", help="Pisahkan koma, lihat --list-kategori")
    ap.add_argument("--ftth-url", default=FTTH_URL, help="API SheetDB titik FTTH (ODP)")
    ap.add_argument("--fwa-url", default=FWA_URL, help="API SheetDB titik FWA")
    ap.add_argument("--radius-ftth", type=int, default=250, help="Jarak maks ke titik FTTH, meter (default 250)")
    ap.add_argument("--radius-fwa", type=int, default=1000, help="Jarak maks ke titik FWA, meter (default 1000)")
    ap.add_argument("--refresh", action="store_true", help="Unduh ulang data jangkauan (abaikan cache)")
    ap.add_argument("--tanpa-jangkauan", action="store_true", help="Lewati pengecekan jangkauan")
    ap.add_argument("--hanya-dalam-jangkauan", action="store_true", help="Buang leads di luar FTTH/FWA")
    ap.add_argument("--enrich", action="store_true", help="Kunjungi website bisnis untuk cari kontak/sinyal")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--output", default="morarepublic.csv")
    ap.add_argument("--list-kategori", action="store_true")
    args, unknown = ap.parse_known_args(argv)
    if unknown and not IN_NOTEBOOK:
        ap.error("argumen tidak dikenal: " + " ".join(unknown))

    if args.list_kategori:
        for k, v in KATEGORI.items():
            print(f"- {k:10s} bobot {v['bobot']}")
        return
    if IN_NOTEBOOK and not (args.kota or args.pusat) and not args.kategori:
        print("Di Colab/Jupyter, panggil dengan list argumen, contoh:\n"
              '    main(["--kota", "Banjarmasin", "--kategori", "kos,hotel,perumahan"])\n'
              "Daftar kategori:  main([\"--list-kategori\"])")
        return
    if not (args.kota or args.pusat):
        ap.error("isi --kota atau --pusat")
    if not args.kategori:
        ap.error("isi --kategori")

    cats = [c.strip().lower() for c in args.kategori.split(",") if c.strip()]
    for c in cats:
        if c not in KATEGORI:
            sys.exit(f"Kategori '{c}' tidak dikenal. Pakai --list-kategori.")

    if args.pusat:
        try:
            lat0, lon0 = [float(x) for x in args.pusat.split(",")]
        except ValueError:
            sys.exit('Format --pusat salah. Contoh: "-3.4425,114.8325"')
        area = f"(around:{int(args.radius_km * 1000)},{lat0},{lon0})"
        print(f"[i] Area: radius {args.radius_km} km dari {lat0},{lon0}")
    else:
        area = geocode(args.kota)
        time.sleep(1)

    ftth, fwa = ([], []) if args.tanpa_jangkauan else load_coverage(args.ftth_url, args.fwa_url, args.refresh)
    coverage_on = bool(ftth or fwa)

    leads, seen = [], set()
    for c in cats:
        print(f"[i] Mengambil '{c}' dari OpenStreetMap ...")
        for el in fetch_overpass(build_query(KATEGORI[c]["combos"], area)):
            l = to_lead(el, c)
            key = (l["nama"].lower(), l["latitude"], l["longitude"])
            if not l["nama"] or l["latitude"] is None or key in seen:
                continue
            seen.add(key)
            leads.append(l)
        time.sleep(2)

    print(f"[i] Ditemukan {len(leads)} tempat unik.")
    if not leads:
        print("Tidak ada hasil dari OpenStreetMap, jadi file CSV TIDAK dibuat. "
              "Coba perbesar radius atau ganti kategori (cakupan OSM belum merata).")
        return

    for l in leads:
        if coverage_on:
            d1, n1 = nearest(l["latitude"], l["longitude"], ftth)
            d2, n2 = nearest(l["latitude"], l["longitude"], fwa)
            in_ftth = d1 is not None and d1 <= args.radius_ftth
            in_fwa = d2 is not None and d2 <= args.radius_fwa
            l["jarak_ftth_m"] = int(d1) if d1 is not None else ""
            l["odp_terdekat"] = n1
            l["jarak_fwa_m"] = int(d2) if d2 is not None else ""
            l["site_fwa_terdekat"] = n2
            l["jangkauan"] = "FTTH" if in_ftth else ("FWA" if in_fwa else "tidak")
        else:
            l.update({"jarak_ftth_m": "", "odp_terdekat": "", "jarak_fwa_m": "",
                      "site_fwa_terdekat": "", "jangkauan": ""})

    if coverage_on:
        n_f = sum(1 for l in leads if l["jangkauan"] == "FTTH")
        n_w = sum(1 for l in leads if l["jangkauan"] == "FWA")
        print(f"[i] Jangkauan: {n_f} FTTH (<= {args.radius_ftth} m), {n_w} FWA saja "
              f"(<= {args.radius_fwa} m), {len(leads) - n_f - n_w} di luar jangkauan.")
        if args.hanya_dalam_jangkauan:
            leads = [l for l in leads if l["jangkauan"] != "tidak"]
            if not leads:
                print("Tidak ada leads dalam jangkauan FTTH/FWA, jadi file CSV TIDAK dibuat. "
                      "Coba perbesar --radius-ftth/--radius-fwa, ganti area/kategori, "
                      "atau jalankan tanpa --hanya-dalam-jangkauan.")
                return

    leads.sort(key=lambda x: bool(x["whatsapp"] or x["telepon"] or x["email"] or x["website"]), reverse=True)
    leads = leads[: args.limit]

    for l in leads:
        l.update({"wifi_disebut": "", "kompetitor": "", "site_status": ""})
    if args.enrich:
        targets = [l for l in leads if l["website"]]
        print(f"[i] Menganalisis {len(targets)} website ({args.workers} thread) ...")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(analyze_site, l, args.delay): l for l in targets}
            done = 0
            for f in as_completed(futs):
                l = futs[f]
                try:
                    res, emails, wa, soc = f.result()
                except Exception as err:
                    res, emails, wa, soc = {"site_status": f"error: {type(err).__name__}"}, set(), set(), {}
                l.update(res)
                if emails and not l["email"]:
                    l["email"] = sorted(emails)[0]
                if wa and not l["whatsapp"]:
                    l["whatsapp"] = sorted(wa)[0]
                l["instagram"] = l["instagram"] or soc.get("instagram", "")
                l["facebook"] = l["facebook"] or soc.get("facebook", "")
                done += 1
                if done % 10 == 0 or done == len(targets):
                    print(f"    {done}/{len(targets)}")

    for l in leads:
        l["skor"], l["alasan_skor"] = score_lead(l, coverage_on)

    leads.sort(key=lambda x: x["skor"], reverse=True)
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(leads)

    hot = sum(1 for l in leads if l["skor"] >= 10)
    wa_n = sum(1 for l in leads if l["whatsapp"])
    print(f"\n[ok] {len(leads)} leads -> {args.output} | skor >= 10: {hot} | punya WhatsApp: {wa_n}")
    print(f"[ok] Lokasi file: {os.path.abspath(args.output)}")
    if IN_NOTEBOOK:
        try:
            import pandas as pd
            from IPython.display import display
            display(pd.read_csv(args.output, encoding="utf-8-sig").head(15))
        except Exception:
            pass

    if "google.colab" in sys.modules:
        try:
            from google.colab import files
            files.download(args.output)
        except Exception as ex:
            print(f"[i] Unduh otomatis gagal ({type(ex).__name__}); ambil manual dari panel Files di kiri.")


if __name__ == "__main__":
    main()
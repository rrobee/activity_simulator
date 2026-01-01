import streamlit as st
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import random
import math
import io
import pandas as pd
import re

# --- Matematikai alapfüggvények ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_real_elevations(locations):
    """Lekéri a valós magasságokat több részletben, hogy ne legyen hiba"""
    all_elevations = []
    # 200-as csomagokban kérjük le, hogy az API ne dobjon hibát
    for i in range(0, len(locations), 200):
        chunk = locations[i:i + 200]
        try:
            response = requests.post(
                'https://api.open-elevation.com/api/v1/lookup',
                json={'locations': chunk},
                timeout=20
            )
            if response.status_code == 200:
                all_elevations.extend([r['elevation'] for r in response.json()['results']])
            else:
                return None
        except:
            return None
    return all_elevations

# --- Felület ---
st.set_page_config(page_title="Garmin GPX Pro vFinal", page_icon="🏃", layout="wide")
st.title("🏃 Garmin & GeoGo Pro - A Végleges Verzió")

with st.sidebar:
    st.header("⚙️ Tevékenység")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    level = st.selectbox("Szint (Erőnlét)", ["Kezdő", "Középhaladó", "Haladó"], index=1)
    path_type = st.radio("Pálya típusa", ["Szakasz", "Körpálya"])
    
    st.divider()
    st.header("🕒 Idő és Tempó")
    start_date = st.date_input("Indulási nap", value=datetime.now().date())
    start_time = st.time_input("Indulási idő", value=datetime.now().time())
    speed_boost = st.slider("Tempó gyorsítása (1.0 = normál)", 0.8, 2.0, 1.2, help="Növeld, ha túl hosszúnak találod az időtartamot!")
    
    st.divider()
    st.header("👤 Felhasználó & Eszköz")
    weight = st.number_input("Súly (kg)", 10.0, 200.0, 94.0)
    age = st.number_input("Életkor", 1, 100, 43)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 43)
    device_name = st.text_input("Óra típusa", "Garmin Fenix 7X")

uploaded_file = st.file_uploader("GPX fájl feltöltése", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Profi Konvertálás Indítása"):
        try:
            with st.spinner('Magasságok lekérése és útvonal újraszámítása...'):
                raw_data = uploaded_file.read().decode("utf-8")
                
                # Csak a trackpontok (Waypoint szűrés)
                track_content = re.search(r'<trk>.*</trk>', raw_data, re.DOTALL)
                track_raw = track_content.group(0) if track_content else raw_data
                lats = re.findall(r'lat="([-+]?\d*\.\d+|\d+)"', track_raw)
                lons = re.findall(r'lon="([-+]?\d*\.\d+|\d+)"', track_raw)
                
                if not lats:
                    st.error("Nem sikerült kinyerni az útvonalat!")
                    st.stop()

                # Összes pont magasságának lekérése (ritkítva, ha túl sok, a sebesség miatt)
                step = 1 if len(lats) < 600 else len(lats) // 500
                lats_f = lats[::step]
                lons_f = lons[::step]
                
                locs = [{"latitude": float(lats_f[i]), "longitude": float(lons_f[i])} for i in range(len(lats_f))]
                real_eles = get_real_elevations(locs)
                
                if not real_eles:
                    st.warning("API hiba. Mesterséges domborzatot használok.")
                    real_eles = [220.0 + (i * 0.1) for i in range(len(lats_f))]

            # --- Számítás ---
            start_dt = datetime.combine(start_date, start_time)
            base_s = {"Túrázás": 1.3, "Futás": 3.0, "Kerékpár": 6.5}[activity_type]
            # Szint módosító
            lvl_mod = {"Kezdő": 0.8, "Középhaladó": 1.0, "Haladó": 1.2}[level]
            target_speed = base_s * lvl_mod * speed_boost

            gpx_ns = "http://www.topografix.com/GPX/1/1"
            tpe_ns = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
            ET.register_namespace('', gpx_ns)
            ET.register_namespace('gpxtpx', tpe_ns)
            
            new_root = ET.Element(f"{{{gpx_ns}}}gpx", {'version': '1.1', 'creator': device_name})
            trk = ET.SubElement(new_root, f"{{{gpx_ns}}}trk")
            trkseg = ET.SubElement(trk, f"{{{gpx_ns}}}trkseg")

            total_dist = 0
            total_ascent = 0
            current_time = start_dt
            heart_rates = []

            for i in range(len(lats_f)):
                lat, lon, ele = float(lats_f[i]), float(lons_f[i]), float(real_eles[i])
                
                if i > 0:
                    d = haversine(float(lats_f[i-1]), float(lons_f[i-1]), lat, lon)
                    total_dist += d
                    diff = ele - real_eles[i-1]
                    if diff > 0: total_ascent += diff
                    
                    # Tobler-túrázó függvény (finomított)
                    slope = diff / d if d > 0 else 0
                    speed_mod = math.exp(-2.0 * abs(slope + 0.02))
                    current_time += timedelta(seconds=d / max(0.2, target_speed * speed_mod))

                pt = ET.SubElement(trkseg, f"{{{gpx_ns}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(pt, f"{{{gpx_ns}}}ele").text = f"{ele:.1f}"
                ET.SubElement(pt, f"{{{gpx_ns}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                # Pulzus
                ext = ET.SubElement(pt, f"{{{gpx_ns}}}extensions")
                tpe = ET.SubElement(ext, f"{{{tpe_ns}}}TrackPointExtension")
                hr = int(rest_hr + 60 + (ele - real_eles[0]) * 0.3 + random.randint(-2, 3))
                final_hr = max(rest_hr+15, min(hr, 190))
                heart_rates.append(final_hr)
                ET.SubElement(tpe, f"{{{tpe_ns}}}hr").text = str(final_hr)

            # Körpálya lezárása
            if path_type == "Körpálya":
                d_end = haversine(float(lats_f[-1]), float(lons_f[-1]), float(lats_f[0]), float(lons_f[0]))
                current_time += timedelta(seconds=d_end / target_speed)

            # Megjelenítés
            st.success("✅ Feldolgozás kész!")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Távolság", f"{total_dist/1000:.2f} km")
            c2.metric("Szintemelkedés", f"{total_ascent:.0f} m")
            c3.metric("Időtartam", f"{str(current_time - start_dt).split('.')[0]}")
            c4.metric("Kalória", f"{int((weight * 0.8) * (total_dist/1000))} kcal")

            st.subheader("⛰️ Magassági profil")
            st.area_chart(real_eles)
            
            buffer = io.BytesIO()
            ET.ElementTree(new_root).write(buffer, encoding='utf-8', xml_declaration=True)
            st.download_button("📥 Kész GPX Letöltése", buffer.getvalue(), f"garmin_final.gpx", "application/gpx+xml", use_container_width=True)

        except Exception as e:
            st.error(f"Hiba: {e}")

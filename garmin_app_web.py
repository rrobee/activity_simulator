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
    """Lekéri a valós magasságokat több részletben az API-ról"""
    all_elevations = []
    # 200-as csomagokban kérjük le a stabilitás miatt
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

# --- Web Felület ---
st.set_page_config(page_title="Garmin GPX Pro vFinal", page_icon="🏃", layout="wide")
st.title("🏃 Garmin & GeoGo Pro - Teljes Verzió")

with st.sidebar:
    st.header("⚙️ Tevékenység")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    level = st.selectbox("Szint (Erőnlét)", ["Kezdő", "Középhaladó", "Haladó"], index=1)
    path_type = st.radio("Pálya típusa", ["Szakasz", "Körpálya"])
    
    st.divider()
    st.header("🕒 Idő és Tempó")
    start_date = st.date_input("Indulási nap", value=datetime.now().date())
    start_time = st.time_input("Indulási idő", value=datetime.now().time())
    speed_boost = st.slider("Tempó gyorsítása (1.0 = alap)", 0.8, 2.0, 1.3, help="Húzd jobbra, ha rövidebb időtartamot szeretnél!")
    
    st.divider()
    st.header("👤 Felhasználó & Eszköz")
    # Súly egész számként
    weight = st.number_input("Súly (kg)", 10, 200, 94)
    age = st.number_input("Életkor", 1, 100, 43)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 43)
    device_name = st.text_input("Óra típusa", "Garmin Fenix 7X")

uploaded_file = st.file_uploader("Töltsd fel a GPX fájlt", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Profi Feldolgozás Indítása"):
        try:
            with st.spinner('Magasságok lekérése és útvonal rajzolása...'):
                raw_data = uploaded_file.read().decode("utf-8")
                
                # Szigorú útvonal-kivonás (csak a <trk> szekció)
                track_content = re.search(r'<trk>.*</trk>', raw_data, re.DOTALL)
                track_raw = track_content.group(0) if track_content else raw_data
                lats = re.findall(r'lat="([-+]?\d*\.\d+|\d+)"', track_raw)
                lons = re.findall(r'lon="([-+]?\d*\.\d+|\d+)"', track_raw)
                
                if not lats:
                    st.error("Nem sikerült útvonalat találni a fájlban!")
                    st.stop()

                # Pontok kezelése (max 500 pont az API limit miatt)
                step = 1 if len(lats) < 600 else len(lats) // 500
                lats_f = lats[::step]
                lons_f = lons[::step]
                
                locs = [{"latitude": float(lats_f[i]), "longitude": float(lons_f[i])} for i in range(len(lats_f))]
                real_eles = get_real_elevations(locs)
                
                if not real_eles:
                    st.warning("A magassági szerver nem válaszolt. Mesterséges adatokat generálok.")
                    real_eles = [220.0 + (i * 0.15) for i in range(len(lats_f))]

            # --- Számítási Logika ---
            start_dt = datetime.combine(start_date, start_time)
            # Alapsebesség (m/s)
            base_s = {"Túrázás": 1.45, "Futás": 3.3, "Kerékpár": 7.0}[activity_type]
            lvl_mod = {"Kezdő": 0.85, "Középhaladó": 1.0, "Haladó": 1.3}[level]
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
            map_points = []
            hr_list = []

            for i in range(len(lats_f)):
                lat, lon, ele = float(lats_f[i]), float(lons_f[i]), float(real_eles[i])
                map_points.append({"lat": lat, "lon": lon})
                
                if i > 0:
                    d = haversine(float(lats_f[i-1]), float(lons_f[i-1]), lat, lon)
                    total_dist += d
                    diff = ele - real_eles[i-1]
                    if diff > 0: total_ascent += diff
                    
                    # Tobler-sebesség korrekció
                    slope = diff / d if d > 0 else 0
                    speed_mod = math.exp(-2.2 * abs(slope + 0.02))
                    current_time += timedelta(seconds=d / max(0.35, target_speed * speed_mod))

                pt = ET.SubElement(trkseg, f"{{{gpx_ns}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(pt, f"{{{gpx_ns}}}ele").text = f"{ele:.1f}"
                ET.SubElement(pt, f"{{{gpx_ns}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                # Garmin pulzus adatok
                ext = ET.SubElement(pt, f"{{{gpx_ns}}}extensions")
                tpe = ET.SubElement(ext, f"{{{tpe_ns}}}TrackPointExtension")
                hr = int(rest_hr + 65 + (ele - real_eles[0]) * 0.4 + random.randint(-2, 3))
                final_hr = max(rest_hr+15, min(hr, 195))
                hr_list.append(final_hr)
                ET.SubElement(tpe, f"{{{tpe_ns}}}hr").text = str(final_hr)

            # Eredmények kijelzése
            st.success("✅ Konvertálás sikeres!")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Távolság", f"{total_dist/1000:.2f} km")
            m2.metric("Szintemelkedés", f"{total_ascent:.0f} m")
            m3.metric("Időtartam", f"{str(current_time - start_dt).split('.')[0]}")
            m4.metric("Kalória", f"{int((weight * 0.8) * (total_dist/1000))} kcal")

            c_l, c_r = st.columns(2)
            with c_l:
                st.subheader("⛰️ Magassági profil")
                st.area_chart(real_eles)
            with c_r:
                st.subheader("🗺️ Útvonal")
                st.map(pd.DataFrame(map_points))
            
            # Letöltés
            buffer = io.BytesIO()
            ET.ElementTree(new_root).write(buffer, encoding='utf-8', xml_declaration=True)
            st.download_button("📥 Kész GPX Letöltése", buffer.getvalue(), "garmin_final_pro.gpx", "application/gpx+xml", use_container_width=True)

        except Exception as e:
            st.error(f"Váratlan hiba: {e}")

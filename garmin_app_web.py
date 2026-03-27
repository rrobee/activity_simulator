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
    all_elevations = []
    for i in range(0, len(locations), 200):
        chunk = locations[i:i + 200]
        try:
            response = requests.post('https://api.open-elevation.com/api/v1/lookup', json={'locations': chunk}, timeout=20)
            if response.status_code == 200: all_elevations.extend([r['elevation'] for r in response.json()['results']])
            else: return None
        except: return None
    return all_elevations

# --- Web Felület ---
st.set_page_config(page_title="Garmin GPX Ultra Pro", page_icon="📊", layout="wide")
st.title("📊 Garmin - GeoGo - Aktivitás Szimulátor GPX Pro")

with st.sidebar:
    st.header("⚙️ Tevékenység")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    level = st.selectbox("Szint (Erőnlét)", ["Kezdő", "Középhaladó", "Haladó"], index=1)
    path_type = st.radio("Pálya típusa", ["Szakasz", "Körpálya"])
    lap_count = st.number_input("Körök száma", min_value=1, max_value=20, value=1)
    
    st.divider()
    st.header("🕒 Idő és Tempó")
    start_date = st.date_input("Indulási nap", value=datetime.now().date(), key="date_picker")
    # Itt a módosítás: két oszlopra bontjuk az órát/percet és a másodpercet
    col_h, col_s = st.columns([2, 1])
    with col_h:
        # A step=60 beállítással percenkénti választást teszel lehetővé
        start_time_base = st.time_input(
            "Indulási idő", 
            value=datetime.now().time(), 
            key="time_picker",
            step=60
        )
    with col_s:
        start_sec = st.number_input("Mp", 0, 59, 0, key="sec_picker")

    st.header("📊 Finomhangolás")
    hr_mult = st.slider("Pulzus intenzitás", 0.5, 1.5, 1.0)
    cad_mult = st.slider("Cadence szorzó", 0.5, 1.5, 1.0)
    speed_boost = st.slider("Tempó gyorsítása", 0.5, 1.5, 1.0)
    
    st.divider()
    st.header("👤 Felhasználó")
    weight = st.number_input("Súly (kg)", 10, 200, 90)
    user_height = st.number_input("Testmagasság (cm)", 100, 250, 186)
    age = st.number_input("Életkor", 1, 100, 43)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 49)

uploaded_file = st.file_uploader("GPX fájl feltöltése", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Szimuláció indítása"):
        try:
            with st.spinner('Adatok feldolgozása...'):
                raw_data = uploaded_file.read().decode("utf-8")
                track_content = re.search(r'<trk>.*</trk>', raw_data, re.DOTALL)
                track_raw = track_content.group(0) if track_content else raw_data
                lats = re.findall(r'lat="([-+]?\d*\.\d+|\d+)"', track_raw)
                lons = re.findall(r'lon="([-+]?\d*\.\d+|\d+)"', track_raw)
                
                if not lats:
                    st.error("Nincs útvonal!")
                    st.stop()

                step = 1 if len(lats) < 600 else len(lats) // 500
                lats_f, lons_f = lats[::step], lons[::step]
                locs = [{"latitude": float(lats_f[i]), "longitude": float(lons_f[i])} for i in range(len(lats_f))]
                real_eles = get_real_elevations(locs)
                if not real_eles: real_eles = [220.0] * len(lats_f)
                    
                if lap_count > 1:
                    # Megismételjük a koordinátákat és a magasságokat
                    lats_f = lats_f * lap_count
                    lons_f = lons_f * lap_count
                    real_eles = real_eles * lap_count

            start_dt = datetime.combine(start_date, start_time_base) + timedelta(seconds=start_sec)
            base_s = {"Túrázás": 1.3, "Futás": 3.0, "Kerékpár": 7.0}[activity_type]
            target_speed = base_s * ({"Kezdő": 0.8, "Középhaladó": 1.0, "Haladó": 1.3}[level]) * speed_boost

            gpx_ns, tpe_ns = "http://www.topografix.com/GPX/1/1", "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
            ET.register_namespace('', gpx_ns)
            ET.register_namespace('gpxtpx', tpe_ns)
            root = ET.Element(f"{{{gpx_ns}}}gpx", {'version': '1.1', 'creator': 'GarminPro'})
            trkseg = ET.SubElement(ET.SubElement(root, f"{{{gpx_ns}}}trk"), f"{{{gpx_ns}}}trkseg")

            total_dist, total_asc, current_time = 0, 0, start_dt
            hr_list, cad_list, map_points = [], [], []

            for i in range(len(lats_f)):
                lat, lon, ele = float(lats_f[i]), float(lons_f[i]), float(real_eles[i])
                map_points.append({"lat": lat, "lon": lon})
                
                if i > 0:
                    d = haversine(float(lats_f[i-1]), float(lons_f[i-1]), lat, lon)
                    total_dist += d
                    diff = ele - real_eles[i-1]
                    if diff > 0: total_asc += diff
                    slope = diff / d if d > 0 else 0
                    speed_mod = math.exp(-2.5 * abs(slope + 0.02))
                    current_time += timedelta(seconds=d / max(0.4, target_speed * speed_mod))

                pt = ET.SubElement(trkseg, f"{{{gpx_ns}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(pt, f"{{{gpx_ns}}}ele").text = f"{ele:.1f}"
                ET.SubElement(pt, f"{{{gpx_ns}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
 ########## SZÁMÍTÁSI LOGIKA START ##########
                # --- FINOMÍTOTT PULZUS (Nincs "plafon" effektus) ---
                hr_offset = 70 if activity_type == "Kerékpár" else 60
                max_hr_allowed = 220 - age

                # Alapérték kiszámítása
                hr_base = (rest_hr + hr_offset + (ele - real_eles[0]) * 0.35) * hr_mult

                # Ha közelítünk a maximumhoz, csökkentjük az ingadozást, de nem tüntetjük el
                hr_with_swing = hr_base + random.randint(-3, 4)

                # "Soft limit" logika: ha átlépné a maxot, kicsit visszahúzzuk, de hagyunk benne micro-mozgást
                if hr_with_swing >= max_hr_allowed:
                    final_hr = max_hr_allowed - random.randint(0, 3)
                else:
                    final_hr = int(max(rest_hr + 15, hr_with_swing))

                hr_list.append(final_hr)
                
                # --- ÉLETSZERŰ CADENCE (Dinamikus szorzóval) ---
                if activity_type == "Kerékpár":
                    cad_base = (70 + (target_speed * 1.5)) * cad_mult
                elif activity_type == "Túrázás":
                    cad_base = (90 + (target_speed * 8) - (user_height * 0.05)) * cad_mult
                else: # Futás
                    cad_base = (150 + (target_speed * 5)) * cad_mult
                
                # Véletlenszerű lépés-ingadozás hozzáadása
                cad = int(max(0, cad_base + random.randint(-3, 3)))
                cad_list.append(cad)
                
                # --- GPX fájlba írás ---
                ext = ET.SubElement(pt, f"{{{gpx_ns}}}extensions")
                tpe = ET.SubElement(ext, f"{{{tpe_ns}}}TrackPointExtension")
                ET.SubElement(tpe, f"{{{tpe_ns}}}hr").text = str(final_hr)
                ET.SubElement(tpe, f"{{{tpe_ns}}}cad").text = str(cad)
########## SZÁMÍTÁSI LOGIKA END ##########

            if path_type == "Körpálya":
                d_back = haversine(float(lats_f[-1]), float(lons_f[-1]), float(lats_f[0]), float(lons_f[0]))
                if d_back > 50: current_time += timedelta(seconds=d_back / target_speed)

            # --- Megjelenítés ---
            st.success("✅ Feldolgozás kész!")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Távolság", f"{total_dist/1000:.2f} km")
            c2.metric("Szint", f"{total_asc:.0f} m")
            c3.metric("Időtartam", f"{str(current_time - start_dt).split('.')[0]}")
            c4.metric("Átlag pulzus", f"{int(sum(hr_list)/len(hr_list))} bpm")
            c5.metric("Átlag Cadence", f"{int(sum(cad_list)/len(cad_list))}")

            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("⛰️ Magassági profil (m)")
                st.area_chart(real_eles)
                st.subheader("🗺️ Útvonal")
                st.map(pd.DataFrame(map_points))
            with col_b:
                st.subheader("❤️ Pulzus profil (bpm)")
                st.line_chart(pd.DataFrame({"BPM": hr_list}), color="#FF4B4B")
                st.subheader("👟 Cadence profil")
                st.line_chart(pd.DataFrame({"Cadence": cad_list}), color="#4B9BFF")

            act_map = {"Túrázás": "hiking", "Futás": "running", "Kerékpár": "cycling"}
            act_slug = act_map.get(activity_type, "activity")
            timestamp_str = start_dt.strftime("%Y%m%d_%H%M%S")
            file_name_final = f"garmin_{act_slug}_{timestamp_str}.gpx"

            # 3. Fájl előkészítése és a letöltő gomb
            buffer = io.BytesIO()
            ET.ElementTree(root).write(buffer, encoding='utf-8', xml_declaration=True)
            
            st.download_button(
                label="📥 GPX Letöltése",
                data=buffer.getvalue(),
                file_name=file_name_final,
                mime="application/gpx+xml",
                use_container_width=True
            )

        except Exception as e:
            st.error(f"Hiba: {e}")











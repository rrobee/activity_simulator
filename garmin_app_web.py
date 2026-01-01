import streamlit as st
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

# --- Web Felület ---
st.set_page_config(page_title="Garmin GPX Pro", page_icon="🏃", layout="wide")
st.title("🏃 Garmin & GeoGo Pro Konverter")

# Session State az idő megőrzéséhez
if 'start_date' not in st.session_state:
    st.session_state['start_date'] = datetime.now().date()
if 'start_time' not in st.session_state:
    st.session_state['start_time'] = datetime.now().time()

with st.sidebar:
    st.header("⚙️ Beállítások")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    level = st.selectbox("Szint", ["Kezdő", "Középhaladó", "Haladó"])
    path_type = st.radio("Pálya típusa", ["Kör", "Szakasz"])
    
    st.divider()
    st.header("🕒 Időpont")
    start_date = st.date_input("Indulási nap", key='start_date')
    start_time = st.time_input("Indulási idő", key='start_time')
    
    st.divider()
    st.header("👤 Felhasználói adatok")
    age = st.number_input("Életkor", 1, 100, 43)
    weight = st.number_input("Súly (kg)", 10.0, 200.0, 94.0)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 43)
    device_name = st.text_input("Óra típusa", "Garmin Fenix 7X")

uploaded_file = st.file_uploader("GPX fájl feltöltése", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Generálás és Elemzés"):
        try:
            start_dt = datetime.combine(st.session_state.start_date, st.session_state.start_time)
            raw_content = uploaded_file.read().decode("utf-8")
            
            # --- ADATKINYERÉS (REGEX - BIZTOS MÓDSZER) ---
            lats = re.findall(r'lat="([-+]?\d*\.\d+|\d+)"', raw_content)
            lons = re.findall(r'lon="([-+]?\d*\.\d+|\d+)"', raw_content)
            eles = re.findall(r'<ele>([-+]?\d*\.\d+|\d+)</ele>', raw_content)

            if not lats or not lons:
                st.error("Nem találtam koordinátákat a fájlban!")
                st.stop()

            # Ha nincs magasság, 220m alapérték
            if not eles:
                eles = ["220.0"] * len(lats)
            elif len(eles) < len(lats):
                eles += [eles[-1]] * (len(lats) - len(eles))

            # --- PARAMÉTEREK ---
            level_code = {"Kezdő": "K", "Középhaladó": "KH", "Haladó": "H"}[level]
            speeds = {"Túrázás": {"K": 0.95, "KH": 1.15, "H": 1.40}, 
                      "Futás": {"K": 2.2, "KH": 2.7, "H": 3.4}, 
                      "Kerékpár": {"K": 4.5, "KH": 6.0, "H": 8.0}}
            target_speed = speeds[activity_type][level_code]
            
            max_hr = 220 - age
            hr_reserve = max_hr - rest_hr
            hr_intensity = {"K": 0.50, "KH": 0.60, "H": 0.70}[level_code]
            cad_base = {"Túrázás": 52, "Futás": 165, "Kerékpár": 85}[activity_type]

            # --- GPX ÉPÍTÉS ---
            GPX_NS = "http://www.topografix.com/GPX/1/1"
            TPE_NS = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
            ET.register_namespace('', GPX_NS)
            ET.register_namespace('gpxtpx', TPE_NS)
            
            new_root = ET.Element(f"{{{GPX_NS}}}gpx", {'version': '1.1', 'creator': device_name})
            trk = ET.SubElement(new_root, f"{{{GPX_NS}}}trk")
            trkseg = ET.SubElement(trk, f"{{{GPX_NS}}}trkseg")

            elevations = []
            heart_rates = []
            coords_map = []
            current_time = start_dt
            total_dist = 0
            total_ascent = 0

            for i in range(len(lats)):
                lat, lon, ele = float(lats[i]), float(lons[i]), float(eles[i])
                elevations.append(ele)
                coords_map.append({'lat': lat, 'lon': lon})
                
                d = 0
                if i > 0:
                    prev_lat, prev_lon, prev_ele = float(lats[i-1]), float(lons[i-1]), float(eles[i-1])
                    d = haversine(prev_lat, prev_lon, lat, lon)
                    total_dist += d
                    if ele > prev_ele: total_ascent += (ele - prev_ele)
                    
                    # Időhaladás lejtő/emelkedő módosítóval
                    inc = (ele - prev_ele) / d if d > 0 else 0
                    s_mod = math.exp(-3.5 * abs(inc + 0.05))
                    current_time += timedelta(seconds=d / max(0.1, target_speed * s_mod))

                # XML Pont
                pt = ET.SubElement(trkseg, f"{{{GPX_NS}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(pt, f"{{{GPX_NS}}}ele").text = f"{ele:.2f}"
                ET.SubElement(pt, f"{{{GPX_NS}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                # Garmin Extensions (Pulzus + Kadencia)
                ext = ET.SubElement(pt, f"{{{GPX_NS}}}extensions")
                tpe = ET.SubElement(ext, f"{{{TPE_NS}}}TrackPointExtension")
                
                # Pulzus dinamika
                hr_mod = (ele - float(eles[i-1])) * 12 if i > 0 else 0
                curr_hr = int(rest_hr + (hr_reserve * hr_intensity) + hr_mod + random.randint(-2, 2))
                final_hr = max(rest_hr+10, min(curr_hr, max_hr-5))
                heart_rates.append(final_hr)
                ET.SubElement(tpe, f"{{{TPE_NS}}}hr").text = str(final_hr)
                
                cad_val = 0 if (activity_type == "Kerékpár" and d == 0 and i > 0) else (cad_base + random.randint(-4, 4))
                ET.SubElement(tpe, f"{{{TPE_NS}}}cad").text = str(max(0, cad_val))

            # Körpálya zárás
            if path_type == "Kör":
                d_end = haversine(float(lats[-1]), float(lons[-1]), float(lats[0]), float(lons[0]))
                current_time += timedelta(seconds=d_end / target_speed)
                end_pt = ET.SubElement(trkseg, f"{{{GPX_NS}}}trkpt", {'lat': str(lats[0]), 'lon': str(lons[0])})
                ET.SubElement(end_pt, f"{{{GPX_NS}}}ele").text = f"{float(eles[0]):.2f}"
                ET.SubElement(end_pt, f"{{{GPX_NS}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            # --- MEGJELENÍTÉS ---
            duration = current_time - start_dt
            st.success("✅ Feldolgozás kész!")
            
            st.subheader("📊 Összegzés")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Távolság", f"{total_dist/1000:.2f} km")
            m2.metric("Időtartam", f"{str(duration).split('.')[0]}")
            m3.metric("Szintemelkedés", f"{total_ascent:.0f} m")
            m4.metric("Kalória", f"{int(7.5 * weight * (duration.total_seconds()/3600))} kcal")

            col_l, col_r = st.columns(2)
            with col_l:
                st.subheader("⛰️ Magassági profil")
                st.area_chart(elevations)
            with col_r:
                st.subheader("🗺️ Útvonal")
                st.map(pd.DataFrame(coords_map))

            # Letöltés
            buffer = io.BytesIO()
            tree = ET.ElementTree(new_root)
            tree.write(buffer, encoding='utf-8', xml_declaration=True)
            st.download_button("📥 Kész GPX Letöltése", buffer.getvalue(), f"garmin_{activity_type}.gpx", "application/gpx+xml", use_container_width=True)

        except Exception as e:
            st.error(f"Hiba: {e}")

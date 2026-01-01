import streamlit as st
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import random
import math
import io
import pandas as pd

# --- Matematikai alapfüggvények ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def add_gps_noise(coord):
    return coord + random.uniform(-0.000005, 0.000005)

# --- Web Felület ---
st.set_page_config(page_title="Garmin GPX Fix", page_icon="⚡", layout="wide")
st.title("⚡ Garmin GPX Pro - Adatjavítás")

if 'start_date' not in st.session_state:
    st.session_state['start_date'] = datetime.now().date()
if 'start_time' not in st.session_state:
    st.session_state['start_time'] = datetime.now().time()

with st.sidebar:
    st.header("⚙️ Beállítások")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    level = st.selectbox("Szint", ["Kezdő", "Középhaladó", "Haladó"])
    
    st.divider()
    st.header("🕒 Időpont")
    start_date = st.date_input("Indulási nap", key='start_date')
    start_time = st.time_input("Indulási idő", key='start_time')
    
    st.divider()
    st.header("👤 Felhasználó")
    age = st.number_input("Életkor", 1, 100, 43)
    weight = st.number_input("Súly (kg)", 10.0, 200.0, 94.0)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 43)

uploaded_file = st.file_uploader("Töltsd fel a GPX fájlt", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Konvertálás indítása"):
        try:
            start_dt = datetime.combine(st.session_state.start_date, st.session_state.start_time)
            
            # Paraméterek
            speeds = {"Túrázás": 1.2, "Futás": 2.8, "Kerékpár": 5.5}
            target_speed = speeds[activity_type]
            max_hr = 220 - age
            hr_reserve = max_hr - rest_hr
            
            # XML betöltés névtér-függetlenül
            content = uploaded_file.read()
            root = ET.fromstring(content)
            
            # Minden pont megkeresése (bármilyen névtérben)
            # A '{*}' jelenti, hogy bármilyen névtér jöhet
            trkpts = root.findall('.//{*}trkpt')
            
            if not trkpts:
                st.error("Nem találtam útvonalpontokat a fájlban!")
                st.stop()

            new_gpx_ns = "http://www.topografix.com/GPX/1/1"
            tpe_ns = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
            ET.register_namespace('', new_gpx_ns)
            
            new_root = ET.Element(f"{{{new_gpx_ns}}}gpx", {'version': '1.1', 'creator': 'GarminGPXTool'})
            trk = ET.SubElement(new_root, f"{{{new_gpx_ns}}}trk")
            trkseg = ET.SubElement(trk, f"{{{new_gpx_ns}}}trkseg")

            elevations = []
            heart_rates = []
            coords = []
            
            current_time = start_dt
            last_lat, last_lon, last_ele = None, None, None
            total_dist = 0
            total_ascent = 0

            for pt in trkpts:
                lat = float(pt.get('lat'))
                lon = float(pt.get('lon'))
                
                # MAGASSÁG KERESÉSE OKOSAN
                ele_node = pt.find('{*}ele')
                if ele_node is not None:
                    ele = float(ele_node.text)
                else:
                    ele = 220.0 # Ha végképp nincs, marad a default
                
                elevations.append(ele)
                coords.append({'lat': lat, 'lon': lon})
                
                # Számítások
                if last_lat is not None:
                    d = haversine(last_lat, last_lon, lat, lon)
                    total_dist += d
                    if ele > last_ele:
                        total_ascent += (ele - last_ele)
                    
                    # Időhaladás a terep függvényében
                    slope = (ele - last_ele) / d if d > 0 else 0
                    speed_mod = math.exp(-3.5 * abs(slope + 0.05))
                    current_time += timedelta(seconds=d / max(0.1, target_speed * speed_mod))

                # Új pont létrehozása
                new_pt = ET.SubElement(trkseg, f"{{{new_gpx_ns}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(new_pt, f"{{{new_gpx_ns}}}ele").text = f"{ele:.2f}"
                ET.SubElement(new_pt, f"{{{new_gpx_ns}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                # Garmin pulzus adatok
                ext = ET.SubElement(new_pt, f"{{{new_gpx_ns}}}extensions")
                tpe = ET.SubElement(ext, f"{{{tpe_ns}}}TrackPointExtension")
                
                # Pulzus dinamika: emelkedőn nő
                hr_mod = (ele - (last_ele if last_ele else ele)) * 8
                current_hr = int(rest_hr + (hr_reserve * 0.6) + hr_mod + random.randint(-3, 3))
                final_hr = max(rest_hr + 10, min(current_hr, max_hr - 5))
                heart_rates.append(final_hr)
                ET.SubElement(tpe, f"{{{tpe_ns}}}hr").text = str(final_hr)
                
                last_lat, last_lon, last_ele = lat, lon, ele

            # Megjelenítés
            st.success(f"Feldolgozva: {len(trkpts)} pont.")
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Távolság", f"{total_dist/1000:.2f} km")
            c2.metric("Szintemelkedés", f"{total_ascent:.0f} m")
            c3.metric("Idő", f"{str(current_time - start_dt).split('.')[0]}")
            c4.metric("Átlag pulzus", f"{int(sum(heart_rates)/len(heart_rates))} bpm")

            st.subheader("⛰️ Magassági profil")
            st.area_chart(elevations)
            
            st.subheader("🗺️ Térkép")
            st.map(pd.DataFrame(coords))

            # Mentés
            buffer = io.BytesIO()
            tree = ET.ElementTree(new_root)
            ET.indent(tree, space="  ")
            tree.write(buffer, encoding='utf-8', xml_declaration=True)
            
            st.download_button("📥 Kész GPX Letöltése", buffer.getvalue(), f"garmin_fix_{uploaded_file.name}", "application/gpx+xml")

        except Exception as e:
            st.error(f"Hiba történt: {e}")

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

# --- Web Felület Beállítások ---
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
    st.header("🏔️ Domborzat")
    # Mivel a fájljaidban nincs magasság, ez alapból be van kapcsolva
    generate_ele = st.checkbox("Mesterséges domborzat generálása", value=True)
    avg_ele = st.number_input("Alap magasság (m)", 100, 1000, 220)
    
    st.divider()
    st.header("👤 Felhasználó")
    weight = st.number_input("Súly (kg)", 10.0, 200.0, 94.0)
    age = st.number_input("Életkor", 1, 100, 43)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 43)
    device_name = st.text_input("Óra típusa", "Garmin Fenix 7X")

uploaded_file = st.file_uploader("Töltsd fel a GPX fájlt", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Konvertálás Indítása"):
        try:
            start_dt = datetime.combine(st.session_state.start_date, st.session_state.start_time)
            
            # XML beolvasás
            tree = ET.parse(uploaded_file)
            root = tree.getroot()
            # Névtér kezelése (wildcard módszer a biztonságért)
            points = root.findall('.//{*}trkpt')
            
            if not points:
                st.error("Nem találhatók útvonalpontok a fájlban!")
                st.stop()

            # Új GPX alapjai
            gpx_ns = "http://www.topografix.com/GPX/1/1"
            tpe_ns = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
            ET.register_namespace('', gpx_ns)
            ET.register_namespace('gpxtpx', tpe_ns)
            
            new_root = ET.Element(f"{{{gpx_ns}}}gpx", {'version': '1.1', 'creator': device_name})
            trk = ET.SubElement(new_root, f"{{{gpx_ns}}}trk")
            trkseg = ET.SubElement(trk, f"{{{gpx_ns}}}trkseg")

            # Számítási alapok
            speeds = {"Túrázás": 1.1, "Futás": 2.7, "Kerékpár": 5.5}
            target_speed = speeds[activity_type]
            
            elevations = []
            heart_rates = []
            coords_list = []
            current_time = start_dt
            total_dist = 0
            total_ascent = 0
            fake_ele = float(avg_ele)

            for i, pt in enumerate(points):
                lat, lon = float(pt.get('lat')), float(pt.get('lon'))
                
                # Magasság: vagy a fájlból, vagy generálva
                ele_node = pt.find('{*}ele')
                if ele_node is not None and not generate_ele:
                    ele = float(ele_node.text)
                else:
                    # Természetes hatású hullámzás
                    fake_ele += random.uniform(-1.2, 1.3)
                    ele = fake_ele
                
                elevations.append(ele)
                coords_list.append({'lat': lat, 'lon': lon})
                
                if i > 0:
                    d = haversine(coords_list[i-1]['lat'], coords_list[i-1]['lon'], lat, lon)
                    total_dist += d
                    if ele > elevations[i-1]:
                        total_ascent += (ele - elevations[i-1])
                    
                    # Időhaladás (lejtőn gyorsabb, emelkedőn lassabb)
                    slope = (ele - elevations[i-1]) / d if d > 0 else 0
                    speed_mod = math.exp(-3.0 * abs(slope + 0.05))
                    current_time += timedelta(seconds=d / max(0.2, target_speed * speed_mod))

                # Új pont létrehozása
                new_pt = ET.SubElement(trkseg, f"{{{gpx_ns}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(new_pt, f"{{{gpx_ns}}}ele").text = f"{ele:.2f}"
                ET.SubElement(new_pt, f"{{{gpx_ns}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                # Garmin pulzus kiterjesztés
                ext = ET.SubElement(new_pt, f"{{{gpx_ns}}}extensions")
                tpe = ET.SubElement(ext, f"{{{tpe_ns}}}TrackPointExtension")
                
                # Pulzus logika: terhelés + emelkedő + véletlen
                hr_val = int(rest_hr + 55 + (ele - elevations[0]) * 0.4 + random.randint(-2, 3))
                ET.SubElement(tpe, f"{{{tpe_ns}}}hr").text = str(max(rest_hr+10, min(hr_val, 185)))

            # Statisztikai adatok megjelenítése
            st.success(f"✅ Kész! Távolság: {total_dist/1000:.2f} km")
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Távolság", f"{total_dist/1000:.2f} km")
            c2.metric("Szintemelkedés", f"{total_ascent:.0f} m")
            c3.metric("Időtartam", f"{str(current_time - start_dt).split('.')[0]}")
            c4.metric("Kalória (becsült)", f"{int((weight * 0.75) * (total_dist/1000))} kcal")

            st.subheader("⛰️ Magassági profil")
            st.area_chart(elevations)
            
            st.subheader("🗺️ Útvonal")
            st.map(pd.DataFrame(coords_list))

            # Mentés és letöltés
            buffer = io.BytesIO()
            tree = ET.ElementTree(new_root)
            ET.indent(tree, space="  ")
            tree.write(buffer, encoding='utf-8', xml_declaration=True)
            
            st.download_button("📥 Konvertált GPX Letöltése", buffer.getvalue(), f"garmin_{activity_type}.gpx", "application/gpx+xml", use_container_width=True)

        except Exception as e:
            st.error(f"Hiba történt: {e}")

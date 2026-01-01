import streamlit as st
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import random
import math
import io
import pandas as pd
import re  # Új modul a nyers szöveges kereséshez

# --- Matematikai alapfüggvények ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# --- Web Felület ---
st.set_page_config(page_title="Garmin GPX Ultra Fix", page_icon="🚨", layout="wide")
st.title("🚨 Garmin GPX - Végső hibajavítás")

# Session state az idő megőrzéséhez
if 'start_date' not in st.session_state:
    st.session_state['start_date'] = datetime.now().date()
if 'start_time' not in st.session_state:
    st.session_state['start_time'] = datetime.now().time()

with st.sidebar:
    st.header("⚙️ Beállítások")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    age = st.number_input("Életkor", 1, 100, 43)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 43)
    
    st.divider()
    st.header("🕒 Időpont")
    start_date = st.date_input("Indulási nap", key='start_date')
    start_time = st.time_input("Indulási idő", key='start_time')

uploaded_file = st.file_uploader("Töltsd fel a GPX-et", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Brutál Konvertálás"):
        try:
            start_dt = datetime.combine(st.session_state.start_date, st.session_state.start_time)
            raw_content = uploaded_file.read().decode("utf-8")
            
            # 1. SZÖVEGES KERESÉS (Ez nem tud hibázni, ha ott van az adat)
            # Megkeressük az összes lat, lon és ele értéket nyers szövegként
            lats = re.findall(r'lat="([-+]?\d*\.\d+|\d+)"', raw_content)
            lons = re.findall(r'lon="([-+]?\d*\.\d+|\d+)"', raw_content)
            # Ez a rész kigyűjti a <ele> értékeit
            eles = re.findall(r'<ele>([-+]?\d*\.\d+|\d+)</ele>', raw_content)

            if not lats or not lons:
                st.error("Nem találtam koordinátákat a fájlban!")
                st.stop()

            # Ha nincs magasság a fájlban, feltöltjük 220-al, hogy ne dőljön el
            if not eles:
                eles = ["220.0"] * len(lats)
                st.warning("⚠️ A fájlban valóban nincs <ele> adat, alapértelmezett értéket használok.")
            elif len(eles) < len(lats):
                # Ha csak néhány pontnál hiányzik, kipótoljuk az utolsóval
                eles += [eles[-1]] * (len(lats) - len(eles))

            # --- Új GPX építése ---
            GPX_NS = "http://www.topografix.com/GPX/1/1"
            TPE_NS = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
            ET.register_namespace('', GPX_NS)
            
            new_root = ET.Element(f"{{{GPX_NS}}}gpx", {'version': '1.1', 'creator': 'UltraFix'})
            trk = ET.SubElement(new_root, f"{{{GPX_NS}}}trk")
            trkseg = ET.SubElement(trk, f"{{{GPX_NS}}}trkseg")

            elevations = []
            heart_rates = []
            coords_for_map = []
            
            current_time = start_dt
            total_dist = 0
            total_ascent = 0
            
            target_speed = {"Túrázás": 1.25, "Futás": 2.8, "Kerékpár": 5.5}[activity_type]

            for i in range(len(lats)):
                lat, lon, ele = float(lats[i]), float(lons[i]), float(eles[i])
                elevations.append(ele)
                coords_for_map.append({'lat': lat, 'lon': lon})
                
                if i > 0:
                    prev_lat, prev_lon, prev_ele = float(lats[i-1]), float(lons[i-1]), float(eles[i-1])
                    d = haversine(prev_lat, prev_lon, lat, lon)
                    total_dist += d
                    if ele > prev_ele:
                        total_ascent += (ele - prev_ele)
                    
                    # Időhaladás
                    slope = (ele - prev_ele) / d if d > 0 else 0
                    speed_mod = math.exp(-3.5 * abs(slope + 0.05))
                    current_time += timedelta(seconds=d / max(0.1, target_speed * speed_mod))

                # Pont hozzáadása
                pt = ET.SubElement(trkseg, f"{{{GPX_NS}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(pt, f"{{{GPX_NS}}}ele").text = f"{ele:.2f}"
                ET.SubElement(pt, f"{{{GPX_NS}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                # Pulzus (most már biztosan változni fog, ha az ele változik)
                ext = ET.SubElement(pt, f"{{{GPX_NS}}}extensions")
                tpe = ET.SubElement(ext, f"{{{TPE_NS}}}TrackPointExtension")
                
                # Dinamikus pulzus számítás
                base_hr = rest_hr + ((220-age-rest_hr) * 0.55)
                # Ha emelkedik a terep, felmegy a pulzus
                ele_diff = (ele - float(eles[i-1])) if i > 0 else 0
                current_hr = int(base_hr + (ele_diff * 15) + random.randint(-2, 2))
                final_hr = max(rest_hr + 5, min(current_hr, 220-age-5))
                heart_rates.append(final_hr)
                ET.SubElement(tpe, f"{{{TPE_NS}}}hr").text = str(final_hr)

            # Eredmények
            st.success("Sikeres feldolgozás nyers kereséssel!")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Távolság", f"{total_dist/1000:.2f} km")
            c2.metric("Szintemelkedés", f"{total_ascent:.1f} m")
            c3.metric("Átlag pulzus", f"{int(sum(heart_rates)/len(heart_rates))} bpm")
            c4.metric("Időtartam", f"{str(current_time - start_dt).split('.')[0]}")

            st.area_chart(elevations)
            st.map(pd.DataFrame(coords_for_map))

            # Letöltés
            buffer = io.BytesIO()
            tree = ET.ElementTree(new_root)
            tree.write(buffer, encoding='utf-8', xml_declaration=True)
            st.download_button("📥 Kész GPX Letöltése", buffer.getvalue(), "fix.gpx", "application/gpx+xml")

        except Exception as e:
            st.error(f"Hiba: {e}")

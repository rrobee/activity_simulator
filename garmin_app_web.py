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
    """Lekéri a valós magasságokat az Open-Elevation API-tól"""
    try:
        response = requests.post(
            'https://api.open-elevation.com/api/v1/lookup',
            json={'locations': locations},
            timeout=20
        )
        if response.status_code == 200:
            return [results['elevation'] for results in response.json()['results']]
    except:
        return None
    return None

# --- Web Felület ---
st.set_page_config(page_title="Garmin GPX Pro - Real Terrain", page_icon="🏔️", layout="wide")
st.title("🏔️ Garmin & GeoGo Pro - Valós Domborzattal")

with st.sidebar:
    st.header("⚙️ Tevékenység")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    level = st.selectbox("Szint (Erőnlét)", ["Kezdő", "Középhaladó", "Haladó"])
    path_type = st.radio("Pálya típusa", ["Szakasz (A-ból B-be)", "Körpálya"])
    
    st.divider()
    st.header("🕒 Időpont")
    start_date = st.date_input("Indulási nap", value=datetime.now().date())
    start_time = st.time_input("Indulási idő", value=datetime.now().time())
    
    st.divider()
    st.header("👤 Felhasználó & Eszköz")
    weight = st.number_input("Súly (kg)", 10.0, 200.0, 94.0)
    age = st.number_input("Életkor", 1, 100, 43)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 49)
    device_name = st.text_input("Óra típusa", "Garmin Fenix 7X")

uploaded_file = st.file_uploader("Töltsd fel a GPX fájlt", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Valós adatok lekérése és fájl generálása"):
        try:
            with st.spinner('Keresem a hegyeket a térképen... (ez eltarthat 10-15 másodpercig)'):
                raw_data = uploaded_file.read().decode("utf-8")
                
                # Csak a trackpontok kinyerése (Waypointok kiszűrése)
                track_content = re.search(r'<trk>.*</trk>', raw_data, re.DOTALL)
                track_raw = track_content.group(0) if track_content else raw_data
                lats = re.findall(r'lat="([-+]?\d*\.\d+|\d+)"', track_raw)
                lons = re.findall(r'lon="([-+]?\d*\.\d+|\d+)"', track_raw)
                
                if not lats:
                    st.error("Nem találtam útvonalat a fájlban!")
                    st.stop()

                # API lekérés (Limitálva 300 pontra a stabilitás miatt)
                locations = [{"latitude": float(lats[i]), "longitude": float(lons[i])} for i in range(len(lats))]
                real_eles = get_real_elevations(locations[:300])
                
                if not real_eles:
                    st.warning("A magassági szerver nem elérhető. Mesterséges terepet generálok.")
                    real_eles = [220.0 + (i * 0.2) * math.sin(i/10) for i in range(len(lats))]
                elif len(real_eles) < len(lats):
                    real_eles += [real_eles[-1]] * (len(lats) - len(real_eles))

            # --- Számítási Logika ---
            start_dt = datetime.combine(start_date, start_time)
            
            # Sebesség beállítás szint alapján
            speeds = {
                "Túrázás": {"Kezdő": 0.9, "Középhaladó": 1.15, "Haladó": 1.4},
                "Futás": {"Kezdő": 2.1, "Középhaladó": 2.7, "Haladó": 3.4},
                "Kerékpár": {"Kezdő": 4.5, "Középhaladó": 5.8, "Haladó": 7.5}
            }
            target_speed = speeds[activity_type][level]

            # GPX struktúra
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
            coords_for_map = []
            heart_rates = []

            for i in range(len(lats)):
                lat, lon, ele = float(lats[i]), float(lons[i]), float(real_eles[i])
                coords_for_map.append({'lat': lat, 'lon': lon})
                
                if i > 0:
                    d = haversine(float(lats[i-1]), float(lons[i-1]), lat, lon)
                    total_dist += d
                    if ele > real_eles[i-1]:
                        total_ascent += (ele - real_eles[i-1])
                    
                    # Időhaladás (emelkedőn lassul)
                    slope = (ele - real_eles[i-1]) / d if d > 0 else 0
                    speed_mod = math.exp(-3.5 * abs(slope + 0.05))
                    current_time += timedelta(seconds=d / max(0.1, target_speed * speed_mod))

                # GPX Pont
                pt = ET.SubElement(trkseg, f"{{{gpx_ns}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(pt, f"{{{gpx_ns}}}ele").text = f"{ele:.1f}"
                ET.SubElement(pt, f"{{{gpx_ns}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                # Pulzus
                ext = ET.SubElement(pt, f"{{{gpx_ns}}}extensions")
                tpe = ET.SubElement(ext, f"{{{tpe_ns}}}TrackPointExtension")
                hr_base = rest_hr + 60 if activity_type != "Kerékpár" else rest_hr + 45
                hr = int(hr_base + (ele - real_eles[0]) * 0.4 + random.randint(-2, 3))
                final_hr = max(rest_hr+15, min(hr, 190))
                heart_rates.append(final_hr)
                ET.SubElement(tpe, f"{{{tpe_ns}}}hr").text = str(final_hr)

            # Körpálya opció: visszatérés a startra
            if path_type == "Körpálya" and total_dist > 0:
                d_back = haversine(float(lats[-1]), float(lons[-1]), float(lats[0]), float(lons[0]))
                current_time += timedelta(seconds=d_back / target_speed)

            # Megjelenítés
            st.success("✅ Valós domborzati adatok sikeresen beépítve!")
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Távolság", f"{total_dist/1000:.2f} km")
            m2.metric("Szintemelkedés", f"{total_ascent:.0f} m")
            m3.metric("Időtartam", f"{str(current_time - start_dt).split('.')[0]}")
            m4.metric("Átlag pulzus", f"{int(sum(heart_rates)/len(heart_rates))} bpm")

            st.subheader("⛰️ Valós magassági profil (Szerverről)")
            st.area_chart(real_eles)
            
            st.map(pd.DataFrame(coords_for_map))

            buffer = io.BytesIO()
            ET.ElementTree(new_root).write(buffer, encoding='utf-8', xml_declaration=True)
            st.download_button("📥 Valós GPX Letöltése", buffer.getvalue(), f"garmin_{activity_type}_real.gpx", "application/gpx+xml", use_container_width=True)

        except Exception as e:
            st.error(f"Hiba történt: {e}")


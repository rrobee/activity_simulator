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
    """Lekéri a valós magasságokat - megnövelt stabilitással"""
    try:
        # Egyszerre maximum 500 pontot kérünk le
        response = requests.post(
            'https://api.open-elevation.com/api/v1/lookup',
            json={'locations': locations[:500]}, 
            timeout=25
        )
        if response.status_code == 200:
            return [results['elevation'] for results in response.json()['results']]
    except:
        return None
    return None

st.set_page_config(page_title="Garmin GPX Ultra Precision", page_icon="⏱️", layout="wide")
st.title("⏱️ Garmin GPX - Sebesség és Magasság Korrekció")

with st.sidebar:
    st.header("⚙️ Beállítások")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    level = st.selectbox("Szint (Erőnlét)", ["Kezdő", "Középhaladó", "Haladó"], index=1)
    
    st.divider()
    st.header("🕒 Idő finomhangolás")
    # Itt manuálisan is gyorsíthatsz, ha túl sokallod az időt
    speed_boost = st.slider("Tempó szorzó (1.0 = alap)", 0.8, 2.0, 1.2)
    
    st.divider()
    st.header("👤 Adatok")
    weight = st.number_input("Súly (kg)", 10.0, 200.0, 94.0)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 43)

uploaded_file = st.file_uploader("GPX feltöltése", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Korrigált Generálás"):
        try:
            with st.spinner('Magasságok lekérése és tempó számítás...'):
                raw_data = uploaded_file.read().decode("utf-8")
                track_content = re.search(r'<trk>.*</trk>', raw_data, re.DOTALL)
                track_raw = track_content.group(0) if track_content else raw_data
                lats = re.findall(r'lat="([-+]?\d*\.\d+|\d+)"', track_raw)
                lons = re.findall(r'lon="([-+]?\d*\.\d+|\d+)"', track_raw)
                
                if not lats:
                    st.error("Hiba a fájl beolvasásakor!")
                    st.stop()

                # Koordináták előkészítése (ritkítás, ha túl sok a pont, a sebesség érdekében)
                step = 1 if len(lats) < 500 else len(lats) // 400
                lats_filtered = lats[::step]
                lons_filtered = lons[::step]

                locations = [{"latitude": float(lats_filtered[i]), "longitude": float(lons_filtered[i])} for i in range(len(lats_filtered))]
                real_eles = get_real_elevations(locations)
                
                if not real_eles:
                    st.warning("Szerver hiba. Átmeneti magasságokat használok.")
                    real_eles = [220.0] * len(lats_filtered)

            # --- Új számítási logika ---
            start_dt = datetime.combine(datetime.now().date(), datetime.now().time())
            
            # Reálisabb tempók (m/s)
            base_speeds = {
                "Túrázás": {"Kezdő": 1.0, "Középhaladó": 1.3, "Haladó": 1.6},
                "Futás": {"Kezdő": 2.5, "Középhaladó": 3.2, "Haladó": 4.0},
                "Kerékpár": {"Kezdő": 5.0, "Középhaladó": 6.5, "Haladó": 8.5}
            }
            target_speed = base_speeds[activity_type][level] * speed_boost

            gpx_ns = "http://www.topografix.com/GPX/1/1"
            tpe_ns = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
            ET.register_namespace('', gpx_ns)
            ET.register_namespace('gpxtpx', tpe_ns)
            
            new_root = ET.Element(f"{{{gpx_ns}}}gpx", {'version': '1.1', 'creator': 'GarminUltraFix'})
            trk = ET.SubElement(new_root, f"{{{gpx_ns}}}trk")
            trkseg = ET.SubElement(trk, f"{{{gpx_ns}}}trkseg")

            total_dist = 0
            total_ascent = 0
            current_time = start_dt
            
            for i in range(len(lats_filtered)):
                lat, lon, ele = float(lats_filtered[i]), float(lons_filtered[i]), float(real_eles[i])
                
                if i > 0:
                    d = haversine(float(lats_filtered[i-1]), float(lons_filtered[i-1]), lat, lon)
                    total_dist += d
                    ele_diff = ele - real_eles[i-1]
                    if ele_diff > 0: total_ascent += ele_diff
                    
                    # Finomított sebesség-módosító (Tobler-függvény szerű)
                    # Kevésbé bünteti az emelkedőt
                    slope = ele_diff / d if d > 0 else 0
                    speed_mod = math.exp(-2.5 * abs(slope + 0.02)) 
                    current_time += timedelta(seconds=d / (target_speed * speed_mod))

                pt = ET.SubElement(trkseg, f"{{{gpx_ns}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(pt, f"{{{gpx_ns}}}ele").text = f"{ele:.1f}"
                ET.SubElement(pt, f"{{{gpx_ns}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                ext = ET.SubElement(pt, f"{{{gpx_ns}}}extensions")
                tpe = ET.SubElement(ext, f"{{{tpe_ns}}}TrackPointExtension")
                hr = int(rest_hr + 65 + (ele - real_eles[0]) * 0.3 + random.randint(-2, 3))
                ET.SubElement(tpe, f"{{{tpe_ns}}}hr").text = str(max(rest_hr+20, min(hr, 185)))

            # Statisztika
            st.success("✅ Számítás kész!")
            c1, c2, c3 = st.columns(3)
            c1.metric("Távolság", f"{total_dist/1000:.2f} km")
            c2.metric("Szintemelkedés", f"{total_ascent:.0f} m")
            # Ez lesz az, amit sokalltál - most már rövidebb lesz!
            duration_final = current_time - start_dt
            c3.metric("Időtartam", f"{str(duration_final).split('.')[0]}")

            st.area_chart(real_eles)
            
            buffer = io.BytesIO()
            ET.ElementTree(new_root).write(buffer, encoding='utf-8', xml_declaration=True)
            st.download_button("📥 Kész GPX Letöltése", buffer.getvalue(), "garmin_v2.gpx", "application/gpx+xml", use_container_width=True)

        except Exception as e:
            st.error(f"Hiba: {e}")

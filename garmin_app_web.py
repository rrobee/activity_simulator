import streamlit as st
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import random
import math
import io
import pandas as pd
import re

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
            timeout=15
        )
        if response.status_code == 200:
            return [results['elevation'] for results in response.json()['results']]
    except:
        return None
    return None

st.set_page_config(page_title="Garmin GPX Real Terrain", page_icon="🏔️", layout="wide")
st.title("🏔️ Garmin GPX - Valós Domborzati Adatokkal")

with st.sidebar:
    st.header("⚙️ Beállítások")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    weight = st.number_input("Súly (kg)", 10.0, 200.0, 94.0)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 43)
    
    st.divider()
    st.info("Ez a verzió online adatbázisból kéri le Sopron és környéke valós magassági adatait!")

uploaded_file = st.file_uploader("Válaszd ki a GPX fájlt", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Valós adatok lekérése és konvertálás"):
        try:
            with st.spinner('Magassági adatok lekérése a műholdas adatbázisból...'):
                raw_data = uploaded_file.read().decode("utf-8")
                
                # Csak a trackpontok kinyerése
                track_content = re.search(r'<trk>.*</trk>', raw_data, re.DOTALL)
                track_raw = track_content.group(0) if track_content else raw_data
                lats = re.findall(r'lat="([-+]?\d*\.\d+|\d+)"', track_raw)
                lons = re.findall(r'lon="([-+]?\d*\.\d+|\d+)"', track_raw)
                
                if not lats:
                    st.error("Nem találtam útvonalpontokat!")
                    st.stop()

                # API lekéréshez előkészítés
                locations = [{"latitude": float(lats[i]), "longitude": float(lons[i])} for i in range(len(lats))]
                
                # Mivel az API limitált, ha túl sok pont van, szeleteljük (vagy csak az első 200-at nézzük tesztként)
                real_eles = get_real_elevations(locations[:250]) # API korlát miatt most 250 pont
                
                if not real_eles:
                    st.warning("Az ingyenes magassági szerver nem válaszolt. Mesterséges adatokat használok.")
                    real_eles = [220.0 + random.uniform(-1, 1) * i * 0.1 for i in range(len(lats))]
                elif len(real_eles) < len(lats):
                    # Ha kevesebb jött vissza, kipótoljuk
                    real_eles += [real_eles[-1]] * (len(lats) - len(real_eles))

            # --- GPX Építés ---
            start_dt = datetime.combine(st.session_state.get('start_date', datetime.now().date()), 
                                        st.session_state.get('start_time', datetime.now().time()))
            
            gpx_ns = "http://www.topografix.com/GPX/1/1"
            tpe_ns = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
            ET.register_namespace('', gpx_ns)
            ET.register_namespace('gpxtpx', tpe_ns)
            
            new_root = ET.Element(f"{{{gpx_ns}}}gpx", {'version': '1.1', 'creator': 'GarminRealElevation'})
            trk = ET.SubElement(new_root, f"{{{gpx_ns}}}trk")
            trkseg = ET.SubElement(trk, f"{{{gpx_ns}}}trkseg")

            total_dist = 0
            total_ascent = 0
            current_time = start_dt
            target_speed = {"Túrázás": 1.1, "Futás": 2.7, "Kerékpár": 5.5}[activity_type]

            for i in range(len(lats)):
                lat, lon, ele = float(lats[i]), float(lons[i]), float(real_eles[i])
                
                if i > 0:
                    d = haversine(float(lats[i-1]), float(lons[i-1]), lat, lon)
                    total_dist += d
                    if ele > real_eles[i-1]:
                        total_ascent += (ele - real_eles[i-1])
                    current_time += timedelta(seconds=d / target_speed)

                pt = ET.SubElement(trkseg, f"{{{gpx_ns}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(pt, f"{{{gpx_ns}}}ele").text = f"{ele:.1f}"
                ET.SubElement(pt, f"{{{gpx_ns}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                ext = ET.SubElement(pt, f"{{{gpx_ns}}}extensions")
                tpe = ET.SubElement(ext, f"{{{tpe_ns}}}TrackPointExtension")
                hr = int(rest_hr + 60 + (ele - real_eles[0]) * 0.5 + random.randint(-2, 2))
                ET.SubElement(tpe, f"{{{tpe_ns}}}hr").text = str(max(rest_hr+10, min(hr, 185)))

            # Statisztika
            st.success("Adatok sikeresen lekérve a domborzati modellből!")
            c1, c2, c3 = st.columns(3)
            c1.metric("Valós távolság", f"{total_dist/1000:.2f} km")
            c2.metric("Mért szintemelkedés", f"{total_ascent:.0f} m")
            c3.metric("Időtartam", f"{str(current_time - start_dt).split('.')[0]}")

            st.area_chart(real_eles)
            st.map(pd.DataFrame([{"lat": float(lats[i]), "lon": float(lons[i])} for i in range(len(lats))]))

            buffer = io.BytesIO()
            ET.ElementTree(new_root).write(buffer, encoding='utf-8', xml_declaration=True)
            st.download_button("📥 Valós GPX letöltése", buffer.getvalue(), "valos_szintes_tura.gpx", "application/gpx+xml")

        except Exception as e:
            st.error(f"Hiba: {e}")

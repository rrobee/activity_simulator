import streamlit as st
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import random
import math
import io

# --- Logikai rész (Változatlan a föprogramból) ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def add_gps_noise(coord):
    return coord + random.uniform(-0.000012, 0.000012)

# --- Webes felület ---
st.set_page_config(page_title="Garmin GPX Tool", page_icon="⛰️")
st.title("⛰️ Garmin & GeoGo GPX Generátor")

with st.sidebar:
    st.header("⚙️ Beállítások")
    activity_type = st.selectbox("Tevékenység", ["Túrázás", "Futás", "Kerékpár"])
    level = st.selectbox("Szint", ["Kezdő", "Középhaladó", "Haladó"])
    path_type = st.radio("Pálya típusa", ["Kör", "Szakasz"])
    
    st.divider()
    start_date = st.date_input("Nap", datetime.now())
    start_time = st.time_input("Idő", datetime.now().time())
    
    st.divider()
    age = st.number_input("Életkor", 1, 100, 43)
    weight = st.number_input("Súly (kg)", 10.0, 200.0, 94.0)
    rest_hr = st.number_input("Nyugalmi pulzus", 30, 100, 43)
    device_name = st.text_input("Óra", "Garmin Fenix 7X")

uploaded_file = st.file_uploader("GPX fájl feltöltése", type=['gpx'])

if uploaded_file:
    if st.button("🚀 Mehet!"):
        try:
            # Idő és típusok beállítása
            start_dt = datetime.combine(start_date, start_time)
            garmin_type = {"Túrázás": "hiking", "Futás": "running", "Kerékpár": "cycling"}[activity_type]
            level_code = {"Kezdő": "K", "Középhaladó": "KH", "Haladó": "H"}[level]
            
            # Sebesség és pulzus kalkuláció alapjai
            speeds = {"Túrázás": {"K": 0.95, "KH": 1.15, "H": 1.40}, 
                      "Futás": {"K": 2.2, "KH": 2.7, "H": 3.4}, 
                      "Kerékpár": {"K": 4.5, "KH": 6.0, "H": 8.0}}
            target_speed = speeds[activity_type][level_code]
            max_hr = 220 - age
            hr_reserve = max_hr - rest_hr
            hr_intensity = {"K": 0.50, "KH": 0.60, "H": 0.70}[level_code]
            cad_base = {"Túrázás": 52, "Futás": 165, "Kerékpár": 85}[activity_type]

            # XML betöltés és névterek (GeoGo kompatibilitás!)
            source_tree = ET.parse(uploaded_file)
            source_root = source_tree.getroot()
            GPX_NS = "http://www.topografix.com/GPX/1/1"
            TPE_NS = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
            XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
            
            # Ez a rész felel azért, hogy ne ns0, hanem ns3 legyen a fájlban
            ET.register_namespace('', GPX_NS)
            ET.register_namespace('ns3', TPE_NS)
            ET.register_namespace('xsi', XSI_NS)

            new_root = ET.Element(f"{{{GPX_NS}}}gpx", {
                'creator': device_name,
                'version': '1.1',
                f'{{{XSI_NS}}}schemaLocation': f"{GPX_NS} http://www.topografix.com/GPX/1/1/gpx.xsd {TPE_NS} http://www.garmin.com/xmlschemas/TrackPointExtensionv1.xsd"
            })

            # Metadata és Track felépítése (ugyanaz a logika)
            metadata = ET.SubElement(new_root, f"{{{GPX_NS}}}metadata")
            link = ET.SubElement(metadata, f"{{{GPX_NS}}}link", {'href': 'connect.garmin.com'})
            ET.SubElement(link, f"{{{GPX_NS}}}text").text = "Garmin Connect"
            ET.SubElement(metadata, f"{{{GPX_NS}}}time").text = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            trk = ET.SubElement(new_root, f"{{{GPX_NS}}}trk")
            ET.SubElement(trk, f"{{{GPX_NS}}}name").text = f"Sopron {activity_type}"
            ET.SubElement(trk, f"{{{GPX_NS}}}type").text = garmin_type
            trkseg = ET.SubElement(trk, f"{{{GPX_NS}}}trkseg")

            ns_map = {'default': GPX_NS}
            source_points = source_root.findall('.//default:trkpt', ns_map)
            
            current_time = start_dt
            last_ele, last_lat, last_lon = None, None, None
            total_dist = 0
            first_pt = source_points[0]
            first_coords = (float(first_pt.get('lat')), float(first_pt.get('lon')))
            first_ele = float(first_pt.find('default:ele', ns_map).text) if first_pt.find('default:ele', ns_map) is not None else 220.0

            for i, pt in enumerate(source_points):
                lat, lon = float(pt.get('lat')), float(pt.get('lon'))
                if 0 < i < len(source_points) - 1:
                    lat, lon = add_gps_noise(lat), add_gps_noise(lon)
                
                ele_node = pt.find('default:ele', ns_map)
                ele = float(ele_node.text) if ele_node is not None else 220.0
                
                d = 0
                if last_lat is not None:
                    d = haversine(last_lat, last_lon, lat, lon)
                    total_dist += d
                    inc = (ele - last_ele) / d if d > 0 else 0
                    s_mod = math.exp(-3.5 * abs(inc + 0.05))
                    current_time += timedelta(seconds=d / max(0.1, target_speed * s_mod))

                new_pt = ET.SubElement(trkseg, f"{{{GPX_NS}}}trkpt", {'lat': str(lat), 'lon': str(lon)})
                ET.SubElement(new_pt, f"{{{GPX_NS}}}ele").text = f"{ele:.2f}"
                ET.SubElement(new_pt, f"{{{GPX_NS}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                ext = ET.SubElement(new_pt, f"{{{GPX_NS}}}extensions")
                tpe = ET.SubElement(ext, f"{{{TPE_NS}}}TrackPointExtension")
                ET.SubElement(tpe, f"{{{TPE_NS}}}atemp").text = "22.0"
                
                hr_mod = (ele - (last_ele if last_ele else ele)) * 12
                curr_hr = int(rest_hr + (hr_reserve * hr_intensity) + hr_mod + random.randint(-2, 2))
                ET.SubElement(tpe, f"{{{TPE_NS}}}hr").text = str(max(rest_hr+10, min(curr_hr, max_hr-5)))
                
                cad_val = 0 if (activity_type == "Kerékpár" and d == 0 and i > 0) else (cad_base + random.randint(-4, 4))
                ET.SubElement(tpe, f"{{{TPE_NS}}}cad").text = str(max(0, cad_val))

                last_lat, last_lon, last_ele = lat, lon, ele

            if path_type == "Kör":
                dist_end = haversine(last_lat, last_lon, first_coords[0], first_coords[1])
                current_time += timedelta(seconds=dist_end / target_speed)
                end_pt = ET.SubElement(trkseg, f"{{{GPX_NS}}}trkpt", {'lat': str(first_coords[0]), 'lon': str(first_coords[1])})
                ET.SubElement(end_pt, f"{{{GPX_NS}}}ele").text = f"{first_ele:.2f}"
                ET.SubElement(end_pt, f"{{{GPX_NS}}}time").text = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Letöltés felajánlása
            buffer = io.BytesIO()
            ET.indent(new_root, space="  ", level=0)
            tree = ET.ElementTree(new_root)
            tree.write(buffer, encoding='utf-8', xml_declaration=True)
            
            st.success(f"Kész! Távolság: {total_dist/1000:.2f} km")
            st.download_button(
                label="📥 Letöltés",
                data=buffer.getvalue(),
                file_name=f"garmin_{garmin_type}.gpx",
                mime="application/gpx+xml"
            )

        except Exception as e:
            st.error(f"Hiba történt: {e}")
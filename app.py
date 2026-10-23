import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Download Dati Meteo FVG", layout="wide")
BASE_URL = "https://monitor.protezionecivile.fvg.it/api"

# --- GESTIONE API TRAMITE I MODELLI ESATTI ---

@st.cache_data(ttl=3600)
def fetch_stations():
    """Scarica le stazioni (Modello Station)"""
    try:
        res = requests.get(f"{BASE_URL}/stations")
        if res.status_code == 200:
            data = res.json()
            stations_list = data if isinstance(data, list) else data.get('data', [])
            return {
                s.get("name"): s 
                for s in stations_list 
                if isinstance(s, dict) and s.get("name") and s.get("id")
            }
    except Exception as e:
        st.error(f"Errore API Stazioni: {e}")
    return {}

@st.cache_data(ttl=3600)
def fetch_sensors(station_id):
    """Scarica i sensori (Modello Sensor) per una specifica stazione"""
    try:
        res = requests.get(f"{BASE_URL}/stations/{station_id}/sensors")
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for k in ['data', 'items', 'sensors']:
                    if k in data and isinstance(data[k], list):
                        return data[k]
    except:
        pass
    return []

def fetch_data_in_chunks(sensor_id, start_date, end_date):
    """Scarica le misure (Modello Measure) aggirando i limiti temporali"""
    all_data = []
    current_start = start_date
    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=6), end_date)
        
        str_start = current_start.strftime("%Y-%m-%dT00:00:00")
        str_end = current_end.strftime("%Y-%m-%dT23:59:59")
        
        # Filtri basati sulla nomenclatura standard REST (spesso start/end o start_date/end_date)
        params = {
            "sensor_id": sensor_id,
            "start": str_start,
            "end": str_end,
            "start_date": str_start,
            "end_date": str_end
        }
        
        try:
            res = requests.get(f"{BASE_URL}/measures", params=params)
            if res.status_code == 200:
                data = res.json()
                
                measures_list = []
                if isinstance(data, list):
                    measures_list = data
                elif isinstance(data, dict):
                    for key in ['measures', 'data', 'items']:
                        if key in data and isinstance(data[key], list):
                            measures_list = data[key]
                            break
                            
                # Estrazione rigorosa dal Modello Measure: dt e value
                for m in measures_list:
                    if "dt" in m and "value" in m:
                        all_data.append({
                            "data_ora": m["dt"],
                            "valore": m["value"]
                        })
        except Exception:
            pass
            
        current_start = current_end + timedelta(days=1)
        
    return all_data

# --- INIZIALIZZAZIONE STATO ---
if "selected_stations" not in st.session_state:
    st.session_state.selected_stations = []
if "processed_tooltip" not in st.session_state:
    st.session_state.processed_tooltip = None

stations_dict = fetch_stations()

# Gestione sincrona della mappa invisibile
map_state = st.session_state.get("fvg_map")
if map_state and map_state.get("last_object_clicked_tooltip"):
    current_click = map_state["last_object_clicked_tooltip"]
    if current_click != st.session_state.processed_tooltip:
        st.session_state.processed_tooltip = current_click
        if current_click in st.session_state.selected_stations:
            st.session_state.selected_stations.remove(current_click)
        else:
            st.session_state.selected_stations.append(current_click)

# --- INTERFACCIA UTENTE ---
st.title("Download Massivo Dati - Protezione Civile FVG")
col_map, col_controls = st.columns([2, 1])

with col_controls:
    st.header("1. Impostazioni")
    
    selected_from_ui = st.multiselect(
        "Cerca o seleziona Stazioni", 
        options=list(stations_dict.keys()),
        default=st.session_state.selected_stations
    )
    
    if set(selected_from_ui) != set(st.session_state.selected_stations):
        st.session_state.selected_stations = selected_from_ui
        st.rerun()
    
    start_date = st.date_input("Data di Inizio", value=datetime(2025, 1, 1))
    end_date = st.date_input("Data di Fine", value=datetime.today().date())
    
    st.header("2. Seleziona Sensori")
    selected_sensors_per_station = {}
    
    if not st.session_state.selected_stations:
        st.info("👈 Clicca su una stazione o sceglila dal menu.")
    
    for st_name in st.session_state.selected_stations:
        st_info = stations_dict[st_name]
        station_id = st_info.get("id")
        
        sensors_list = fetch_sensors(station_id)
        
        if not sensors_list:
            st.warning(f"{st_name}: Nessun sensore trovato.")
            continue
            
        # Nomi e unità basati sul Modello Sensor (quantity, unit, id)
        sensor_options = {}
        for s in sensors_list:
            if isinstance(s, dict):
                s_quantity = s.get("quantity") or s.get("name") or "Sensore"
                s_unit = s.get("unit", "")
                s_id = s.get("id")
                
                if s_id:
                    label = f"{s_quantity} {f'[{s_unit}]' if s_unit else ''} - (ID: {s_id})"
                    sensor_options[label] = s_id
        
        chosen = st.multiselect(f"Sensori per {st_name}:", options=list(sensor_options.keys()))
        if chosen:
            selected_sensors_per_station[st_name] = [sensor_options[c] for c in chosen]

    if st.button("Scarica dati selezionati", type="primary", use_container_width=True):
        if not selected_sensors_per_station:
            st.error("Seleziona almeno un sensore.")
        elif start_date > end_date:
            st.error("Date non valide.")
        else:
            final_dataframe = pd.DataFrame()
            progress_text = st.empty()
            progress_bar = st.progress(0)
            
            total_sensors = sum(len(v) for v in selected_sensors_per_station.values())
            processed = 0
            
            for st_name, sensor_ids in selected_sensors_per_station.items():
                for s_id in sensor_ids:
                    progress_text.text(f"Scaricamento: {st_name} (Sensore {s_id})...")
                    
                    raw_data = fetch_data_in_chunks(s_id, start_date, end_date)
                    if raw_data:
                        temp_df = pd.DataFrame(raw_data)
                        temp_df.insert(0, "stazione", st_name)
                        temp_df.insert(1, "id_sensore", s_id)
                        final_dataframe = pd.concat([final_dataframe, temp_df], ignore_index=True)
                        
                    processed += 1
                    progress_bar.progress(processed / total_sensors)
                    
            progress_text.text("Completato!")
            
            if not final_dataframe.empty:
                st.success(f"Scaricati {len(final_dataframe)} record.")
                st.dataframe(final_dataframe.head())
                csv = final_dataframe.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Salva il CSV Unificato",
                    data=csv,
                    file_name="dati_meteo_fvg.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            else:
                st.warning("Nessun dato temporale trovato per i sensori scelti. (Le misurazioni storiche potrebbero richiedere un URL dedicato, es: /sensors/{id}/measures)")

with col_map:
    # Centratura basata sul modello Station (lat, lon)
    m = folium.Map(location=[46.06, 13.23], zoom_start=9)
    for s_name, s_data in stations_dict.items():
        lat = s_data.get("lat")
        lon = s_data.get("lon")
        
        if lat and lon:
            color = "red" if s_name in st.session_state.selected_stations else "blue"
            folium.Marker(
                [lat, lon],
                tooltip=s_name,
                icon=folium.Icon(color=color, icon="cloud")
            ).add_to(m)

    st_folium(m, width=800, height=600, key="fvg_map", returned_objects=["last_object_clicked_tooltip"])

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Download Dati Meteo FVG", layout="wide")

BASE_URL = "https://monitor.protezionecivile.fvg.it/api"

# --- GESTIONE DATI API ---
@st.cache_data(ttl=3600)
def fetch_stations():
    """Scarica e memorizza in cache l'anagrafica delle stazioni e dei sensori"""
    try:
        response = requests.get(f"{BASE_URL}/stations")
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ['data', 'items', 'stations', 'features']:
                    if key in data and isinstance(data[key], list):
                        return data[key]
    except Exception as e:
        st.error(f"Errore connessione API: {e}")
    return []

def fetch_data_in_chunks(sensor_id, start_date, end_date):
    """Scarica i dati aggirando il limite settimanale"""
    all_data = []
    current_start = start_date
    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=6), end_date)
        str_start = current_start.strftime("%Y-%m-%dT00:00:00")
        str_end = current_end.strftime("%Y-%m-%dT23:59:59")
        
        params = {"id": sensor_id, "from": str_start, "to": str_end}
        try:
            res = requests.get(f"{BASE_URL}/measures", params=params)
            if res.status_code == 200:
                data = res.json()
                
                # --- MODIFICA CHIAVE QUI ---
                # Estraiamo la lista reale dei dati a prescindere da come la incapsula l'API
                if isinstance(data, list):
                    all_data.extend(data)
                elif isinstance(data, dict):
                    # Cerca l'array dei dati nelle chiavi più usate (in base al tuo CSV la chiave è 'measures')
                    for key in ['measures', 'data', 'items', 'values']:
                        if key in data and isinstance(data[key], list):
                            all_data.extend(data[key])
                            break
        except Exception:
            pass
            
        current_start = current_end + timedelta(days=1)
        
    return all_data

# --- INIZIALIZZAZIONE STATO ---
if "selected_stations" not in st.session_state:
    st.session_state.selected_stations = []
if "processed_tooltip" not in st.session_state:
    st.session_state.processed_tooltip = None

stations_data = fetch_stations()
stations_dict = {
    s.get("name"): s 
    for s in stations_data 
    if isinstance(s, dict) and s.get("name")
}

# --- LOGICA INVISIBILE: GESTIONE CLIC SULLA MAPPA ---
# Leggiamo lo stato della mappa PRIMA di renderizzare l'interfaccia
map_state = st.session_state.get("fvg_map")
if map_state and map_state.get("last_object_clicked_tooltip"):
    current_click = map_state["last_object_clicked_tooltip"]
    
    # Se è un clic nuovo che non abbiamo ancora processato
    if current_click != st.session_state.processed_tooltip:
        st.session_state.processed_tooltip = current_click
        
        # Aggiungi o rimuovi dalla selezione
        if current_click in st.session_state.selected_stations:
            st.session_state.selected_stations.remove(current_click)
        else:
            st.session_state.selected_stations.append(current_click)

# --- INTERFACCIA UTENTE ---
st.title("Download Massivo Dati - Protezione Civile FVG")

col_map, col_controls = st.columns([2, 1])

with col_controls:
    st.header("1. Impostazioni")
    
    # Il menu a tendina legge lo stato aggiornato
    selected_from_ui = st.multiselect(
        "Cerca o seleziona Stazioni", 
        options=list(stations_dict.keys()),
        default=st.session_state.selected_stations
    )
    
    # Se l'utente ha modificato manualmente il menu a tendina, aggiorniamo lo stato
    if set(selected_from_ui) != set(st.session_state.selected_stations):
        st.session_state.selected_stations = selected_from_ui
        st.rerun() # Aggiorna istantaneamente la mappa
    
    start_date = st.date_input("Data di Inizio", value=datetime.today().date() - timedelta(days=7))
    end_date = st.date_input("Data di Fine", value=datetime.today().date())
    
    st.header("2. Seleziona Sensori")
    selected_sensors_per_station = {}
    
    if not st.session_state.selected_stations:
        st.info("👈 Clicca su una stazione nella mappa o sceglila dal menu sopra.")
    
    for st_name in st.session_state.selected_stations:
        st_info = stations_dict[st_name]
        
        # 1. Tentativo: cerca i sensori nelle chiavi più comuni
        sensors_list = st_info.get("sensors") or st_info.get("sensor") or st_info.get("equipments") or st_info.get("metrics") or []
        
        # 2. Tentativo: se la lista è vuota, proviamo a interrogare l'endpoint specifico dei sensori per questa stazione
        if not sensors_list:
            station_id = st_info.get("id") or st_info.get("stationId") or st_info.get("code")
            if station_id:
                try:
                    res = requests.get(f"{BASE_URL}/stations/{station_id}/sensors")
                    if res.status_code == 200:
                        s_data = res.json()
                        if isinstance(s_data, list):
                            sensors_list = s_data
                        elif isinstance(s_data, dict):
                            for k in ['data', 'items', 'sensors']:
                                if k in s_data and isinstance(s_data[k], list):
                                    sensors_list = s_data[k]
                except:
                    pass
        
        # 3. Se ancora non troviamo nulla, mostriamo l'oggetto grezzo per fare debug!
        if not sensors_list:
            st.warning(f"{st_name}: Impossibile trovare la lista dei sensori in automatico.")
            with st.expander(f"🔍 DEBUG: Mostra i dati grezzi di '{st_name}' per capire la struttura"):
                st.write("L'API restituisce questi dati. Se vedi sotto quale nome si nascondono i sensori, fammelo sapere!")
                st.json(st_info)
            continue
            
        # Estraiamo dinamicamente il nome e l'ID del sensore
        sensor_options = {}
        for s in sensors_list:
            if isinstance(s, dict):
                s_name_display = s.get("type") or s.get("name") or s.get("description") or s.get("sensorType") or "Sensore Ignoto"
                s_id = s.get("id") or s.get("sensorId") or s.get("code")
                
                if s_id:
                    sensor_options[f"{s_name_display} (ID: {s_id})"] = s_id
        
        if not sensor_options:
            st.warning(f"{st_name}: Trovati sensori ma privi di un ID valido per il download.")
            with st.expander(f"🔍 DEBUG: Mostra i sensori grezzi di '{st_name}'"):
                st.json(sensors_list)
            continue
            
        chosen = st.multiselect(f"Sensori disponibili per {st_name}:", options=list(sensor_options.keys()))
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
                        temp_df["station_name"] = st_name
                        temp_df["sensor_id"] = s_id
                        final_dataframe = pd.concat([final_dataframe, temp_df], ignore_index=True)
                        
                    processed += 1
                    progress_bar.progress(processed / total_sensors)
                    
            progress_text.text("Completato!")
            
            if not final_dataframe.empty:
                st.success(f"Scaricati {len(final_dataframe)} record.")
                csv = final_dataframe.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Salva il CSV Unificato",
                    data=csv,
                    file_name="dati_meteo_fvg.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            else:
                st.warning("Nessun dato trovato.")

with col_map:
    # --- COSTRUZIONE MAPPA ---
    m = folium.Map(location=[46.06, 13.23], zoom_start=9)
    
    for s_name, s_data in stations_dict.items():
        lat = s_data.get("lat") or s_data.get("latitude")
        lon = s_data.get("lon") or s_data.get("longitude")
        
        if lat and lon:
            # Colora di rosso se selezionato
            color = "red" if s_name in st.session_state.selected_stations else "blue"
            folium.Marker(
                [lat, lon],
                tooltip=s_name,
                icon=folium.Icon(color=color, icon="cloud")
            ).add_to(m)

    # La "key" è fondamentale per evitare che il componente iframe della mappa venga distrutto e ricreato
    st_folium(m, width=800, height=600, key="fvg_map", returned_objects=["last_object_clicked_tooltip"])

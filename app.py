import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Download Dati Meteo FVG", layout="wide")

BASE_URL = "https://monitor.protezionecivile.fvg.it/api"

# Header HTTP per evitare blocchi 403 Forbidden dai firewall WAF del server
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

# --- GESTIONE DATI API CON CACHE SICURA ---

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stations():
    """Scarica le stazioni. Se fallisce, solleva un'eccezione senza salvare la cache vuota."""
    try:
        res = requests.get(f"{BASE_URL}/stations", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            stations_list = data if isinstance(data, list) else data.get('data', [])
            
            result = {
                s.get("name"): s 
                for s in stations_list 
                if isinstance(s, dict) and s.get("name") and s.get("id")
            }
            if result:
                return result
            else:
                raise ValueError("Nessuna stazione trovata nella risposta JSON dell'API.")
        else:
            raise ValueError(f"HTTP Error {res.status_code}: {res.text}")
    except Exception as e:
        # Rilanciamo l'eccezione in modo che Streamlit NON salvi l'errore in cache
        raise RuntimeError(f"Impossibile scaricare l'elenco stazioni: {e}")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_sensors(station_id):
    """Scarica i sensori associati a una specifica stazione."""
    try:
        res = requests.get(f"{BASE_URL}/stations/{station_id}/sensors", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for k in ['data', 'items', 'sensors']:
                    if k in data and isinstance(data[k], list):
                        return data[k]
    except Exception:
        pass
    return []

def fetch_data_in_chunks(station_id, sensor_id, start_date, end_date):
    """Scarica le misurazioni storiche ciclando per blocchi di 7 giorni."""
    all_data = []
    current_start = start_date
    
    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=6), end_date)
        
        # Formato data ISO 8601 UTC richiesto dal campo 'dt' del modello Measure
        str_start = current_start.strftime("%Y-%m-%dT00:00:00Z")
        str_end = current_end.strftime("%Y-%m-%dT23:59:59Z")
        
        # Inseriamo i nomi dei parametri di data supportati dallo Swagger
        params = {
            "from": str_start,
            "to": str_end,
            "start": str_start,
            "end": str_end,
            "date_from": str_start,
            "date_to": str_end,
            "dt_from": str_start,
            "dt_to": str_end,
            "sensor_id": sensor_id
        }
        
        # Prova progressiva degli endpoint previsti dallo Swagger dell'API
        endpoints_to_try = [
            f"{BASE_URL}/stations/{station_id}/sensors/{sensor_id}/measures",
            f"{BASE_URL}/sensors/{sensor_id}/measures",
            f"{BASE_URL}/measures"
        ]
        
        chunk_success = False
        for url in endpoints_to_try:
            try:
                res = requests.get(url, params=params, headers=HEADERS, timeout=12)
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
                                
                    if measures_list:
                        for m in measures_list:
                            if isinstance(m, dict) and "dt" in m and "value" in m:
                                all_data.append({
                                    "data_ora": m["dt"],
                                    "valore": m["value"]
                                })
                        chunk_success = True
                        break # Esce dal ciclo se trova dati validi
            except Exception:
                continue
                
        current_start = current_end + timedelta(days=1)
        
    return all_data

# --- BARRA LATERALE CONTROLLO CACHE ---
with st.sidebar:
    st.header("Strumenti System")
    if st.button("🔄 Svuota Cache e Ricarica API"):
        st.cache_data.clear()
        st.session_state.selected_stations = []
        st.rerun()

# --- CARICAMENTO ANAGRAFICA STAZIONI ---
try:
    stations_dict = fetch_stations()
except Exception as err:
    st.error(f"⚠️ **Errore nel recupero dati dalle API Protezione Civile FVG:**")
    st.info(str(err))
    st.warning("Prova a premere il pulsante '🔄 Svuota Cache e Ricarica API' nella barra laterale.")
    st.stop()

# --- INIZIALIZZAZIONE STATO INTERFACCIA ---
if "selected_stations" not in st.session_state:
    st.session_state.selected_stations = []
if "processed_tooltip" not in st.session_state:
    st.session_state.processed_tooltip = None

# Sincronizzazione clic sulla mappa
map_state = st.session_state.get("fvg_map")
if map_state and map_state.get("last_object_clicked_tooltip"):
    current_click = map_state["last_object_clicked_tooltip"]
    if current_click != st.session_state.processed_tooltip:
        st.session_state.processed_tooltip = current_click
        if current_click in st.session_state.selected_stations:
            st.session_state.selected_stations.remove(current_click)
        else:
            st.session_state.selected_stations.append(current_click)

# --- CORPO DELL'APPLICAZIONE ---
st.title("Download Massivo Dati Meteo - Protezione Civile FVG")

col_map, col_controls = st.columns([2, 1])

with col_controls:
    st.header("1. Impostazioni Stazioni")
    
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
        st.info("👈 Clicca su una stazione sulla mappa o sceglila dal menu in alto.")
    
    for st_name in st.session_state.selected_stations:
        st_info = stations_dict[st_name]
        station_id = st_info.get("id")
        
        sensors_list = fetch_sensors(station_id)
        
        if not sensors_list:
            st.warning(f"{st_name}: Nessun sensore rilevato dall'API.")
            continue
            
        sensor_options = {}
        for s in sensors_list:
            if isinstance(s, dict):
                s_quantity = s.get("quantity") or s.get("name") or "Sensore"
                s_unit = s.get("unit", "")
                s_id = s.get("id")
                
                if s_id:
                    label = f"{s_quantity} {f'[{s_unit}]' if s_unit else ''} - (ID: {s_id})"
                    sensor_options[label] = s_id
        
        chosen = st.multiselect(f"Sensori disponibili per {st_name}:", options=list(sensor_options.keys()))
        if chosen:
            selected_sensors_per_station[st_name] = {
                "station_id": station_id,
                "sensor_ids": [sensor_options[c] for c in chosen]
            }

    if st.button("Scarica dati selezionati", type="primary", use_container_width=True):
        if not selected_sensors_per_station:
            st.error("Seleziona almeno un sensore.")
        elif start_date > end_date:
            st.error("La data di inizio deve essere precedente alla data di fine.")
        else:
            final_dataframe = pd.DataFrame()
            progress_text = st.empty()
            progress_bar = st.progress(0)
            
            total_sensors = sum(len(v["sensor_ids"]) for v in selected_sensors_per_station.values())
            processed = 0
            
            for st_name, info in selected_sensors_per_station.items():
                st_id = info["station_id"]
                for s_id in info["sensor_ids"]:
                    progress_text.text(f"Scaricamento in corso: {st_name} (Sensore ID: {s_id})...")
                    
                    raw_data = fetch_data_in_chunks(st_id, s_id, start_date, end_date)
                    if raw_data:
                        temp_df = pd.DataFrame(raw_data)
                        temp_df.insert(0, "stazione", st_name)
                        temp_df.insert(1, "id_sensore", s_id)
                        final_dataframe = pd.concat([final_dataframe, temp_df], ignore_index=True)
                        
                    processed += 1
                    progress_bar.progress(processed / total_sensors)
                    
            progress_text.text("Completato!")
            
            if not final_dataframe.empty:
                st.success(f"Scaricati {len(final_dataframe)} record con successo!")
                st.dataframe(final_dataframe.head(10))
                
                csv = final_dataframe.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Scarica il File CSV",
                    data=csv,
                    file_name=f"dati_meteo_fvg_{start_date}_{end_date}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            else:
                st.warning("L'API non ha restituito dati per i sensori e le date selezionate.")

with col_map:
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

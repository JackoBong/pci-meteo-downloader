import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import folium
from streamlit_folium import st_folium
import pytz
import math

st.set_page_config(page_title="Download Dati Meteo FVG", layout="wide")

BASE_URL = "https://monitor.protezionecivile.fvg.it/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

# --- INIZIALIZZAZIONE STATO GLOBALE ---
if "selected_sensors_per_station" not in st.session_state:
    st.session_state.selected_sensors_per_station = {}
if "processed_tooltip" not in st.session_state:
    st.session_state.processed_tooltip = None

# --- GESTIONE DATI API ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stations():
    """Scarica le stazioni cercando dinamicamente l'array nel JSON."""
    try:
        res = requests.get(f"{BASE_URL}/stations", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            stations_list = []
            if isinstance(data, list):
                stations_list = data
            elif isinstance(data, dict):
                for k in ['data', 'items', 'stations', 'features', 'result', 'records']:
                    if k in data and isinstance(data[k], list):
                        stations_list = data[k]
                        break
                if not stations_list:
                    for val in data.values():
                        if isinstance(val, list):
                            stations_list = val
                            break
            if not stations_list:
                raise ValueError(f"Formato JSON imprevisto.")
                
            result = {
                s.get("name"): s 
                for s in stations_list 
                if isinstance(s, dict) and s.get("name") and "id" in s
            }
            if result: return result
            else: raise ValueError("Alle stazioni mancano 'name' o 'id'.")
        else:
            raise ValueError(f"Errore HTTP {res.status_code}")
    except Exception as e:
        raise RuntimeError(f"{e}")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_sensors(station_id):
    """Scarica i sensori associati a una specifica stazione."""
    try:
        res = requests.get(f"{BASE_URL}/stations/{station_id}/sensors", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list): return data
            elif isinstance(data, dict):
                for k in ['data', 'items', 'sensors']:
                    if k in data and isinstance(data[k], list): return data[k]
                for val in data.values():
                    if isinstance(val, list): return val
    except Exception:
        pass
    return []

@st.cache_data(ttl=3600, show_spinner=False)
def get_global_sensor_types():
    """Scansiona tutti i sensori globalmente per popolare il filtro della mappa."""
    try:
        res = requests.get(f"{BASE_URL}/sensors", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            s_list = []
            if isinstance(data, list): s_list = data
            elif isinstance(data, dict):
                for k in ['data', 'items', 'sensors', 'result', 'features']:
                    if k in data and isinstance(data[k], list):
                        s_list = data[k]
                        break
            
            temp_map = {}
            unique_types = set()
            
            for s in s_list:
                if isinstance(s, dict):
                    st_id = s.get("station_id")
                    s_type = s.get("quantity") or s.get("name")
                    if st_id and s_type:
                        s_type_str = str(s_type).strip().capitalize()
                        if st_id not in temp_map:
                            temp_map[st_id] = set()
                        temp_map[st_id].add(s_type_str)
                        unique_types.add(s_type_str)
            
            # Converte in tuple in modo che Streamlit possa conservare in cache senza problemi
            final_map = {k: tuple(v) for k, v in temp_map.items()}
            return final_map, sorted(list(unique_types))
    except Exception:
        pass
    return {}, []

def fetch_data_in_chunks(station_id, sensor_id, start_date, end_date, pbar=None, text_element=None, st_name=""):
    """Scarica i dati a blocchi ottimizzati da 100 giorni (Max API limit 10000)."""
    all_data = []
    current_date = start_date
    local_tz = pytz.timezone("Europe/Rome")
    
    chunk_days_limit = 99
    total_days = (end_date - start_date).days + 1
    total_chunks = math.ceil(total_days / (chunk_days_limit + 1))
    current_chunk = 1
    
    while current_date <= end_date:
        chunk_end_date = min(current_date + timedelta(days=chunk_days_limit), end_date)
        
        if text_element is not None:
            text_element.markdown(f"Scaricamento **{st_name}** (Sensore: {sensor_id}) - Blocco API **{current_chunk} di {total_chunks}**...")
        
        local_start = local_tz.localize(datetime.combine(current_date, datetime.min.time()))
        local_end = local_tz.localize(datetime.combine(chunk_end_date, datetime.max.time()))
        
        utc_start = local_start.astimezone(pytz.UTC)
        utc_end = local_end.astimezone(pytz.UTC)
        
        str_start = utc_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        str_end = utc_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        params = {
            "from": str_start, "to": str_end,
            "start": str_start, "end": str_end,
            "date_from": str_start, "date_to": str_end,
            "dt_from": str_start, "dt_to": str_end,
            "sensor_id": sensor_id
        }
        
        endpoints_to_try = [
            f"{BASE_URL}/stations/{station_id}/sensors/{sensor_id}/measures",
            f"{BASE_URL}/sensors/{sensor_id}/measures",
            f"{BASE_URL}/measures"
        ]
        
        for url in endpoints_to_try:
            try:
                res = requests.get(url, params=params, headers=HEADERS, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    measures_list = []
                    
                    if isinstance(data, list): measures_list = data
                    elif isinstance(data, dict):
                        for key in ['measures', 'data', 'items', 'values']:
                            if key in data and isinstance(data[key], list):
                                measures_list = data[key]
                                break
                        if not measures_list:
                            for val in data.values():
                                if isinstance(val, list):
                                    measures_list = val
                                    break
                                
                    if measures_list:
                        for m in measures_list:
                            if isinstance(m, dict) and "dt" in m and "value" in m:
                                all_data.append({"data_ora": m["dt"], "valore": m["value"]})
                        break
            except Exception:
                continue
        
        if pbar is not None:
            progress_fraction = min(current_chunk / total_chunks, 1.0)
            pbar.progress(progress_fraction)
            
        current_date = chunk_end_date + timedelta(days=1)
        current_chunk += 1
        
    return all_data

# --- MODALE POPUP (Appare al clic sulla mappa) ---
@st.dialog("⚙️ Configurazione Stazione")
def show_sensor_popup(station_name, station_id):
    st.write(f"Seleziona i sensori da scaricare per la stazione **{station_name}**:")
    
    with st.spinner("Recupero sensori in corso..."):
        sensors_list = fetch_sensors(station_id)
        
    if not sensors_list:
        st.warning("Nessun sensore disponibile per questa stazione.")
        if st.button("Chiudi", use_container_width=True):
            st.rerun()
        return
        
    sensor_options = {}
    for s in sensors_list:
        if isinstance(s, dict):
            s_quantity = s.get("quantity") or s.get("name") or "Sensore"
            s_unit = s.get("unit", "")
            s_id = s.get("id")
            if s_id:
                label = f"{s_quantity} {f'[{s_unit}]' if s_unit else ''} - (ID: {s_id})"
                sensor_options[label] = s_id
                
    current_selected = []
    if station_name in st.session_state.selected_sensors_per_station:
        existing_ids = st.session_state.selected_sensors_per_station[station_name]["sensor_ids"]
        for label, sid in sensor_options.items():
            if sid in existing_ids:
                current_selected.append(label)
                
    chosen = st.multiselect("Sensori disponibili:", options=list(sensor_options.keys()), default=current_selected)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 Salva nel Carrello", type="primary", use_container_width=True):
            if chosen:
                st.session_state.selected_sensors_per_station[station_name] = {
                    "station_id": station_id,
                    "sensor_ids": [sensor_options[c] for c in chosen]
                }
            else:
                if station_name in st.session_state.selected_sensors_per_station:
                    del st.session_state.selected_sensors_per_station[station_name]
            st.rerun()
    with col2:
        if st.button("🗑️ Rimuovi Stazione", use_container_width=True):
            if station_name in st.session_state.selected_sensors_per_station:
                del st.session_state.selected_sensors_per_station[station_name]
            st.rerun()

# --- CARICAMENTO ANAGRAFICA INIZIALE ---
try:
    stations_dict = fetch_stations()
    station_sensors_map, all_sensor_types = get_global_sensor_types()
except Exception as err:
    st.error("⚠️ **Errore nel recupero dati dalle API Protezione Civile FVG:**")
    st.info(str(err))
    st.stop()

# --- BARRA LATERALE (Filtri e Ricerca) ---
with st.sidebar:
    st.header("🔍 Filtra Mappa")
    if all_sensor_types:
        filtro_sensori = st.multiselect(
            "Mostra solo stazioni dotate di:", 
            options=all_sensor_types,
            help="Se selezioni più sensori, la mappa mostrerà solo le stazioni che li possiedono TUTTI."
        )
    else:
        st.warning("Filtro globale mappa non disponibile a causa di limitazioni dell'API.")
        filtro_sensori = []
        
    st.divider()
    st.header("⚙️ Ricerca Manuale")
    cerca_stazione = st.selectbox("Cerca stazione per nome:", options=list(stations_dict.keys()))
    if st.button("➕ Configura questa stazione", use_container_width=True):
        st.session_state.processed_tooltip = cerca_stazione
        show_sensor_popup(cerca_stazione, stations_dict[cerca_stazione]["id"])
        
    st.divider()
    st.header("Strumenti di Sistema")
    if st.button("🔄 Svuota Cache e Ricarica API"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.session_state.selected_sensors_per_station = {}
        st.session_state.processed_tooltip = None
        st.rerun()

# --- LOGICA CLIC SULLA MAPPA (Apre il Modale) ---
map_state = st.session_state.get("fvg_map")
if map_state and map_state.get("last_object_clicked_tooltip"):
    current_click = map_state["last_object_clicked_tooltip"]
    # Se il clic è nuovo, registralo e lancia il popup
    if current_click != st.session_state.processed_tooltip:
        st.session_state.processed_tooltip = current_click
        st_info = stations_dict.get(current_click)
        if st_info:
            show_sensor_popup(current_click, st_info.get("id"))

# --- COSTRUZIONE MAPPA OTTIMIZZATA ---
@st.cache_resource
def crea_mappa_fluida(stazioni, filtro_sensori_tuple, _station_sensors_map_dict, cart_keys_tuple):
    m = folium.Map(location=[46.06, 13.23], zoom_start=9)
    for s_name, s_data in stazioni.items():
        st_id = s_data.get("id")
        mostra = True
        
        # Se è attivo un filtro, verifichiamo che la stazione abbia TUTTI i sensori richiesti
        if filtro_sensori_tuple and _station_sensors_map_dict:
            st_types = _station_sensors_map_dict.get(st_id, tuple())
            if not all(f in st_types for f in filtro_sensori_tuple):
                mostra = False
                
        if mostra:
            lat = s_data.get("lat")
            lon = s_data.get("lon")
            if lat and lon:
                color = "red" if s_name in cart_keys_tuple else "blue"
                folium.Marker(
                    [lat, lon],
                    tooltip=s_name,
                    icon=folium.Icon(color=color, icon="cloud")
                ).add_to(m)
    return m

# --- CORPO DELL'APPLICAZIONE ---
st.title("Download Massivo Dati Meteo - Protezione Civile FVG")

col_map, col_controls = st.columns([2, 1])

with col_controls:
    st.header("📥 Carrello Download")
    
    if not st.session_state.selected_sensors_per_station:
        st.info("👈 Clicca su una stazione sulla mappa per scegliere i sensori da scaricare.")
    else:
        for st_name, info in list(st.session_state.selected_sensors_per_station.items()):
            with st.expander(f"✅ {st_name} ({len(info['sensor_ids'])} sensori selezionati)", expanded=False):
                st.write(f"- **ID Stazione:** {info['station_id']}")
                st.write(f"- **ID Sensori:** {', '.join(map(str, info['sensor_ids']))}")
                if st.button("✏️ Modifica Sensori", key=f"mod_{st_name}", use_container_width=True):
                    show_sensor_popup(st_name, info["station_id"])
                    
    st.divider()
    st.header("📅 Periodo di Estrazione")
    start_date = st.date_input("Data di Inizio", value=datetime(2025, 1, 1))
    end_date = st.date_input("Data di Fine", value=datetime.today().date())
    
    if st.button("🚀 Avvia Download Massivo", type="primary", use_container_width=True):
        if not st.session_state.selected_sensors_per_station:
            st.error("Il carrello è vuoto. Aggiungi almeno un sensore.")
        elif start_date > end_date:
            st.error("La data di inizio deve essere precedente alla data di fine.")
        else:
            final_dataframe = pd.DataFrame()
            st.write("---")
            text_globale = st.empty()
            pbar_globale = st.progress(0)
            
            text_singolo = st.empty()
            pbar_singolo = st.progress(0)
            
            total_sensors = sum(len(v["sensor_ids"]) for v in st.session_state.selected_sensors_per_station.values())
            processed_sensors = 0
            
            for st_name, info in st.session_state.selected_sensors_per_station.items():
                st_id = info["station_id"]
                for s_id in info["sensor_ids"]:
                    text_globale.markdown(f"**Avanzamento Globale:** {processed_sensors} di {total_sensors} sensori completati")
                    pbar_singolo.progress(0)
                    
                    raw_data = fetch_data_in_chunks(
                        st_id, s_id, start_date, end_date, 
                        pbar=pbar_singolo, text_element=text_singolo, st_name=st_name
                    )
                    
                    if raw_data:
                        temp_df = pd.DataFrame(raw_data)
                        temp_df.insert(0, "stazione", st_name)
                        temp_df.insert(1, "id_sensore", s_id)
                        final_dataframe = pd.concat([final_dataframe, temp_df], ignore_index=True)
                        
                    processed_sensors += 1
                    pbar_globale.progress(processed_sensors / total_sensors)
                    
            text_globale.markdown("**✅ Elaborazione Completata!**")
            text_singolo.empty()
            pbar_singolo.empty()
            
            if not final_dataframe.empty:
                st.success(f"Scaricati {len(final_dataframe)} record con successo!")
                
                final_dataframe["data_ora"] = pd.to_datetime(final_dataframe["data_ora"])
                final_dataframe["data_ora"] = final_dataframe["data_ora"].dt.tz_localize("UTC").dt.tz_convert("Europe/Rome")
                final_dataframe["data_ora"] = final_dataframe["data_ora"].dt.strftime('%Y-%m-%d %H:%M:%S')
                
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
    filtro_tuple = tuple(filtro_sensori)
    cart_tuple = tuple(st.session_state.selected_sensors_per_station.keys())
    
    mappa_ottimizzata = crea_mappa_fluida(
        stations_dict, 
        filtro_tuple, 
        station_sensors_map, 
        cart_tuple
    )
    
    st_folium(mappa_ottimizzata, width=800, height=600, key="fvg_map", returned_objects=["last_object_clicked_tooltip"])

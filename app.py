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
        response = requests.get(f"{BASE_URL}/stations") # Verifica endpoint esatto
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        st.error(f"Errore connessione API: {e}")
    return []

def fetch_data_in_chunks(sensor_id, start_date, end_date):
    """Scarica i dati aggirando il limite settimanale"""
    all_data = []
    current_start = start_date
    total_days = (end_date - start_date).days + 1
    
    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=6), end_date)
        
        str_start = current_start.strftime("%Y-%m-%dT00:00:00")
        str_end = current_end.strftime("%Y-%m-%dT23:59:59")
        
        params = {"sensorId": sensor_id, "dateFrom": str_start, "dateTo": str_end}
        
        try:
            res = requests.get(f"{BASE_URL}/measures", params=params)
            if res.status_code == 200 and res.json():
                all_data.extend(res.json())
        except Exception:
            pass
            
        current_start = current_end + timedelta(days=1)
        
    return all_data

# --- INIZIALIZZAZIONE STATO ---
if "selected_stations" not in st.session_state:
    st.session_state.selected_stations = []

stations_data = fetch_stations()
# Creiamo un dizionario per rapido accesso ai dati della stazione {Nome: Dati}
stations_dict = {s.get("name"): s for s in stations_data if s.get("name")}

# --- INTERFACCIA UTENTE ---
st.title("Download Massivo Dati - Protezione Civile FVG")

col_map, col_controls = st.columns([2, 1])

with col_controls:
    st.header("1. Impostazioni")
    
    # Sincronizza il selettore laterale con lo stato (e quindi con la mappa)
    selected_station_names = st.multiselect(
        "Cerca o seleziona Stazioni", 
        options=list(stations_dict.keys()),
        default=st.session_state.selected_stations,
        key="station_multiselect"
    )
    st.session_state.selected_stations = selected_station_names
    
    start_date = st.date_input("Data di Inizio", value=datetime.today().date() - timedelta(days=7))
    end_date = st.date_input("Data di Fine", value=datetime.today().date())
    
    st.header("2. Seleziona Sensori")
    selected_sensors_per_station = {}
    
    if not st.session_state.selected_stations:
        st.info("👈 Clicca su una stazione nella mappa o sceglila dal menu sopra.")
    
    # Genera dinamicamente i menu dei sensori per ogni stazione scelta
    for st_name in st.session_state.selected_stations:
        st_info = stations_dict[st_name]
        sensors_list = st_info.get("sensors", [])
        
        # Mappiamo il nome del sensore al suo ID per l'utente { "Vento (ID:123)": "123" }
        sensor_options = {
            f"{s.get('type', 'Sensore')} ({s.get('id')})": s.get("id") 
            for s in sensors_list
        }
        
        if not sensor_options:
            st.warning(f"{st_name}: Nessun sensore trovato nell'API.")
            continue
            
        chosen = st.multiselect(f"Sensori in: {st_name}", options=list(sensor_options.keys()))
        if chosen:
            selected_sensors_per_station[st_name] = [sensor_options[c] for c in chosen]

    # Bottone di Download
    if st.button("Scarica tutti i dati selezionati", type="primary", use_container_width=True):
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
                    progress_text.text(f"Scaricamento: Stazione {st_name} | Sensore {s_id}...")
                    
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
                st.success(f"Scaricati {len(final_dataframe)} record complessivi.")
                st.dataframe(final_dataframe.head())
                
                csv = final_dataframe.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Salva il CSV Unificato",
                    data=csv,
                    file_name=f"dati_meteo_fvg_multi.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            else:
                st.warning("Nessun dato disponibile nel periodo richiesto per i sensori scelti.")

with col_map:
    # --- COSTRUZIONE MAPPA ---
    # Centriamo la mappa sul Friuli-Venezia Giulia
    m = folium.Map(location=[46.06, 13.23], zoom_start=9)
    
    for s_name, s_data in stations_dict.items():
        lat = s_data.get("lat") or s_data.get("latitude")
        lon = s_data.get("lon") or s_data.get("longitude")
        
        if lat and lon:
            # Coloriamo di rosso i marker se la stazione è attualmente selezionata
            color = "red" if s_name in st.session_state.selected_stations else "blue"
            
            folium.Marker(
                [lat, lon],
                tooltip=s_name, # Il tooltip passa il nome allo script al click
                icon=folium.Icon(color=color, icon="cloud")
            ).add_to(m)

    # st_folium renderizza la mappa e cattura gli eventi
    map_data = st_folium(m, width=800, height=600, returned_objects=["last_object_clicked_tooltip"])
    
    # Logica per intercettare il click sulla mappa
    if map_data and map_data.get("last_object_clicked_tooltip"):
        clicked_station = map_data["last_object_clicked_tooltip"]
        
        # Aggiungi o rimuovi la stazione dalla selezione
        if clicked_station not in st.session_state.selected_stations:
            st.session_state.selected_stations.append(clicked_station)
            st.rerun() # Forza l'aggiornamento dell'interfaccia

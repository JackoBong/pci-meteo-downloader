import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Download Dati Meteo FVG", layout="wide")
BASE_URL = "https://monitor.protezionecivile.fvg.it/api"

# --- GESTIONE DATI API TRAMITE I MODELLI UFFICIALI ---

@st.cache_data(ttl=3600)
def fetch_anagrafica():
    """Scarica stazioni e sensori e li incrocia usando i modelli ufficiali"""
    stations_dict = {}
    try:
        # 1. Scarichiamo le Stazioni (Modello Station)
        res_stations = requests.get(f"{BASE_URL}/stations")
        if res_stations.status_code == 200:
            data = res_stations.json()
            # Gestione dinamica in caso sia incapsulato
            stations_list = data if isinstance(data, list) else data.get('data', [])
            
            for s in stations_list:
                if "id" in s and "name" in s:
                    stations_dict[s["id"]] = {
                        "name": s["name"],
                        "lat": s.get("lat"),
                        "lon": s.get("lon"),
                        "sensors": [] # Lo popoleremo tra poco
                    }

        # 2. Scarichiamo i Sensori (Modello SensorWithStatus)
        res_sensors = requests.get(f"{BASE_URL}/sensors")
        if res_sensors.status_code == 200:
            data = res_sensors.json()
            sensors_list = data if isinstance(data, list) else data.get('data', [])
            
            for sens in sensors_list:
                st_id = sens.get("station_id")
                # Se la stazione esiste nel nostro dizionario, aggiungiamo il sensore
                if st_id in stations_dict:
                    stations_dict[st_id]["sensors"].append({
                        "id": sens.get("id"),
                        "name": sens.get("name", "Ignoto"),
                        "quantity": sens.get("quantity", ""),
                        "unit": sens.get("unit", "")
                    })
                    
        return stations_dict
    except Exception as e:
        st.error(f"Errore di connessione API: {e}")
        return {}

def fetch_data_in_chunks(sensor_id, start_date, end_date):
    """Scarica le misure usando le chiavi snake_case dei Modelli"""
    all_data = []
    current_start = start_date
    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=6), end_date)
        
        # Formato date standard
        str_start = current_start.strftime("%Y-%m-%dT00:00:00")
        str_end = current_end.strftime("%Y-%m-%dT23:59:59")
        
        # Uso dei parametri corretti in base ai modelli (testiamo le nomenclature più usate in caso di dubbi)
        params = {
            "sensor_id": sensor_id,
            "start": str_start,
            "end": str_end,
            "date_from": str_start,  # Inviandoli entrambi siamo sicuri che l'API lo "peschi"
            "date_to": str_end
        }
        
        try:
            res = requests.get(f"{BASE_URL}/measures", params=params)
            if res.status_code == 200:
                data = res.json()
                
                # Estraiamo la lista dal Modello Measure
                measures_list = []
                if isinstance(data, list):
                    measures_list = data
                elif isinstance(data, dict):
                    # Spesso è sotto data, items o measures
                    for key in ['measures', 'data', 'items']:
                        if key in data and isinstance(data[key], list):
                            measures_list = data[key]
                            break
                            
                # Pulizia opzionale: teniamo solo data e valore per alleggerire
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
if "selected_stations_ids" not in st.session_state:
    st.session_state.selected_stations_ids = []
if "processed_tooltip" not in st.session_state:
    st.session_state.processed_tooltip = None

stations_dict = fetch_anagrafica()
# Dizionario di utilità per i menu a tendina: { "Osoppo (ID: 12)": 12 }
ui_station_options = {f"{v['name']} (ID: {k})": k for k, v in stations_dict.items()}
reverse_ui_station_options = {v: k for k, v in ui_station_options.items()}

# Gestione Clic sulla Mappa
map_state = st.session_state.get("fvg_map")
if map_state and map_state.get("last_object_clicked_tooltip"):
    clicked_name = map_state["last_object_clicked_tooltip"]
    if clicked_name != st.session_state.processed_tooltip:
        st.session_state.processed_tooltip = clicked_name
        
        # Troviamo l'ID corrispondente al nome cliccato sulla mappa
        clicked_id = next((k for k, v in stations_dict.items() if v["name"] == clicked_name), None)
        
        if clicked_id:
            if clicked_id in st.session_state.selected_stations_ids:
                st.session_state.selected_stations_ids.remove(clicked_id)
            else:
                st.session_state.selected_stations_ids.append(clicked_id)

# --- INTERFACCIA UTENTE ---
st.title("Download Massivo Dati - Protezione Civile FVG")
col_map, col_controls = st.columns([2, 1])

with col_controls:
    st.header("1. Impostazioni")
    
    current_ui_selection = [reverse_ui_station_options[s_id] for s_id in st.session_state.selected_stations_ids if s_id in reverse_ui_station_options]
    
    selected_from_ui = st.multiselect(
        "Cerca o seleziona Stazioni", 
        options=list(ui_station_options.keys()),
        default=current_ui_selection
    )
    
    new_selected_ids = [ui_station_options[name] for name in selected_from_ui]
    if set(new_selected_ids) != set(st.session_state.selected_stations_ids):
        st.session_state.selected_stations_ids = new_selected_ids
        st.rerun()
    
    start_date = st.date_input("Data di Inizio", value=datetime(2025, 1, 1))
    end_date = st.date_input("Data di Fine", value=datetime.today().date())
    
    st.header("2. Seleziona Sensori")
    selected_sensors_per_station = {}
    
    if not st.session_state.selected_stations_ids:
        st.info("👈 Clicca su una stazione o sceglila dal menu.")
    
    for st_id in st.session_state.selected_stations_ids:
        st_data = stations_dict[st_id]
        st_name = st_data["name"]
        sensors_list = st_data["sensors"]
        
        if not sensors_list:
            st.warning(f"{st_name}: Nessun sensore associato.")
            continue
            
        sensor_options = {f"{s['quantity']} ({s['unit']}) - {s['name']} (ID: {s['id']})": s["id"] for s in sensors_list}
        
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
                st.success(f"Scaricati {len(final_dataframe)} record effettivi.")
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
                st.warning("Nessun dato temporale trovato per i sensori scelti. Verifica che abbiano misurazioni storiche nel periodo indicato.")

with col_map:
    m = folium.Map(location=[46.06, 13.23], zoom_start=9)
    for st_id, st_data in stations_dict.items():
        if st_data["lat"] and st_data["lon"]:
            color = "red" if st_id in st.session_state.selected_stations_ids else "blue"
            folium.Marker(
                [st_data["lat"], st_data["lon"]],
                tooltip=st_data["name"], 
                icon=folium.Icon(color=color, icon="cloud")
            ).add_to(m)

    st_folium(m, width=800, height=600, key="fvg_map", returned_objects=["last_object_clicked_tooltip"])

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# Configurazione API (Verifica URL ed endpoint esatti sullo Swagger)
BASE_URL = "https://monitor.protezionecivile.fvg.it/api"

def fetch_data_in_chunks(sensor_id, start_date, end_date):
    all_data = []
    current_start = start_date
    
    # Crea una barra di progresso
    progress_bar = st.progress(0)
    total_days = (end_date - start_date).days + 1
    
    while current_start <= end_date:
        # L'API permette max 1 settimana. Avanziamo di 6 giorni alla volta.
        current_end = min(current_start + timedelta(days=6), end_date)
        
        # Formattazione ISO 8601
        str_start = current_start.strftime("%Y-%m-%dT00:00:00")
        str_end = current_end.strftime("%Y-%m-%dT23:59:59")
        
        params = {
            "sensorId": sensor_id,
            "dateFrom": str_start,
            "dateTo": str_end
        }
        
        try:
            response = requests.get(f"{BASE_URL}/measures", params=params)
            if response.status_code == 200:
                data = response.json()
                if data:
                    all_data.extend(data)
        except Exception as e:
            st.error(f"Errore durante il download: {e}")
            break
            
        # Aggiorna la barra di progresso
        days_processed = (current_end - start_date).days + 1
        progress_bar.progress(days_processed / total_days)
        
        # Passa al blocco successivo
        current_start = current_end + timedelta(days=1)
        
    return all_data

# --- INTERFACCIA STREAMLIT ---
st.title("Download Dati Meteo FVG - Protezione Civile")
st.write("Scarica intervalli personalizzati aggirando il limite settimanale dell'API.")

# Input utente
sensor_id = st.text_input("ID Sensore", value="INSERISCI_ID_SENSORE")
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Data di Inizio", value=datetime(2025, 1, 1))
with col2:
    end_date = st.date_input("Data di Fine", value=datetime(2025, 1, 31))

if st.button("Estrai Dati"):
    if start_date > end_date:
        st.error("La data di inizio deve essere precedente a quella di fine.")
    else:
        with st.spinner("Scaricamento in corso. Potrebbe richiedere qualche minuto..."):
            raw_data = fetch_data_in_chunks(sensor_id, start_date, end_date)
            
            if raw_data:
                df = pd.DataFrame(raw_data)
                st.success(f"Scaricati {len(df)} record con successo!")
                
                # Mostra un'anteprima
                st.dataframe(df.head())
                
                # Bottone per il download del CSV
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Scarica il file CSV",
                    data=csv,
                    file_name=f"dati_meteo_{start_date}_{end_date}.csv",
                    mime="text/csv",
                )
            else:
                st.warning("Nessun dato trovato per questo periodo o sensore.")

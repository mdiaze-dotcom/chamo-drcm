
# app.py - Robust version

import streamlit as st
import pandas as pd
from datetime import datetime, date, time
from google.oauth2.service_account import Credentials
import gspread

st.set_page_config(page_title="Actualización DRCM PRO+", layout="wide")
st.title("📋 Actualización de Expedientes - DRCM (Google Sheets)")

SHEET_ID = "1mDeXDyKTZjNmRK8TnSByKbm3ny_RFhT4Rvjpqwekvjg"
SHEET_INDEX = 0

EXPECTED_COLS = [
    "Número de Expediente",
    "Dependencia",
    "Fecha de Expediente",
    "Días restantes",
    "Tipo de Proceso",
    "Tipo de Calidad Migratoria",
    "Fecha Inicio de Etapa",
    "Fecha Fin de Etapa",
    "Estado Trámite",
    "Fecha Pase DRCM"
]

def gs_client_from_secrets():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope
    )
    return gspread.authorize(creds)

@st.cache_data(ttl=40)
def load_sheet_df():
    client = gs_client_from_secrets()
    sh = client.open_by_key(SHEET_ID)
    ws = sh.get_worksheet(SHEET_INDEX)

    header = ws.row_values(1)
    records = ws.get_all_records()

    df = pd.DataFrame(records)

    for col in EXPECTED_COLS:
        if col not in df.columns:
            df[col] = pd.NA

    for col in ["Fecha de Expediente", "Fecha Inicio de Etapa", "Fecha Fin de Etapa", "Fecha Pase DRCM"]:
        df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    return df, ws, header

def compute_days_remaining(fecha_exp, fecha_envio):
    if pd.isna(fecha_exp):
        return None
    if fecha_envio is None or pd.isna(fecha_envio):
        fecha_envio = pd.to_datetime(date.today())
    return int((fecha_envio.normalize() - fecha_exp.normalize()).days)

def get_col_index(header, colname):
    return header.index(colname) + 1

df, ws, header = load_sheet_df()

deps = sorted(df["Dependencia"].dropna().unique().tolist())
dep = st.selectbox("Seleccione Dependencia:", ["--"] + deps)

if dep == "--":
    st.stop()

clave = st.text_input("Clave (DEPENDENCIA + 2025):", type="password")
if clave != dep.upper() + "2025":
    st.warning("Clave incorrecta.")
    st.stop()

st.success(f"Acceso: {dep}")

df_dep = df[(df["Dependencia"] == dep) & (df["Estado Trámite"].str.lower() == "pendiente")]

if df_dep.empty:
    st.info("No hay expedientes pendientes.")
    st.stop()

for idx, row in df_dep.iterrows():
    cols = st.columns([2,1,1,1])
    with cols[0]:
        st.markdown(f"### {row['Número de Expediente']}")
    with cols[1]:
        fecha_env_act = row["Fecha Pase DRCM"]
        default = fecha_env_act.date() if not pd.isna(fecha_env_act) else date.today()
        nueva = st.date_input("Fecha Pase DRCM", value=default, key=f"f{idx}")
    with cols[2]:
        dias = compute_days_remaining(row["Fecha de Expediente"], fecha_env_act)
        st.write("Días:", dias)
    with cols[3]:
        if st.button("Guardar", key=f"g{idx}"):

            try:
                client = gs_client_from_secrets()
                sh = client.open_by_key(SHEET_ID)
                ws_live = sh.get_worksheet(SHEET_INDEX)
                header_live = ws_live.row_values(1)

                fecha_col = get_col_index(header_live, "Fecha Pase DRCM")
                dias_col = get_col_index(header_live, "Días restantes")

                live_records = ws_live.get_all_records()
                df_live = pd.DataFrame(live_records)

                match = df_live.index[df_live["Número de Expediente"] == row["Número de Expediente"]].tolist()
                if not match:
                    st.error("Expediente no encontrado.")
                    continue

                row_number = match[0] + 2

                fecha_dt = datetime.combine(nueva, time())
                fecha_str = fecha_dt.strftime("%d/%m/%Y %H:%M:%S")

                dias_calc = compute_days_remaining(
                    pd.to_datetime(df_live.loc[match[0], "Fecha de Expediente"], errors="coerce", dayfirst=True),
                    fecha_dt
                )

                ws_live.update_cell(row_number, fecha_col, fecha_str)
                ws_live.update_cell(row_number, dias_col, dias_calc)

                st.success(f"Actualizado: {row['Número de Expediente']}")
                st.cache_data.clear()

            except Exception as e:
                st.error("Error actualizando.")
                st.exception(e)

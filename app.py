# app.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import datetime, date, time
from google.oauth2.service_account import Credentials
import gspread

st.set_page_config(page_title="BD Expedientes DRCM (PRO)", layout="wide")
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
    scope = ["https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client

@st.cache_data(ttl=60)
def load_sheet_df():
    client = gs_client_from_secrets()
    sh = client.open_by_key(SHEET_ID)
    ws = sh.get_worksheet(SHEET_INDEX)
    records = ws.get_all_records()
    if not records:
        df = pd.DataFrame(columns=EXPECTED_COLS)
    else:
        df = pd.DataFrame(records)
    df.columns = [c.strip() for c in df.columns]
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    for col in ["Fecha de Expediente", "Fecha Inicio de Etapa", "Fecha Fin de Etapa", "Fecha Pase DRCM"]:
        df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    return df, ws

def compute_days_remaining(fecha_expediente, fecha_envio):
    if pd.isna(fecha_expediente):
        return None
    ref = fecha_envio if (fecha_envio is not None and not pd.isna(fecha_envio)) else pd.to_datetime(date.today())
    return int((pd.to_datetime(ref).normalize() - pd.to_datetime(fecha_expediente).normalize()).days)

def ensure_log_sheet(sh):
    try:
        log_ws = sh.worksheet("Log")
    except Exception:
        log_ws = sh.add_worksheet(title="Log", rows="1000", cols="10")
        log_ws.append_row(["timestamp", "dependencia", "usuario", "numero_expediente", "fecha_pase"])
    return log_ws

try:
    df_all, ws = load_sheet_df()
except Exception as e:
    st.error("No fue posible conectar a Google Sheets. Revisa st.secrets y permisos.")
    st.exception(e)
    st.stop()

dependencias = sorted(df_all["Dependencia"].dropna().unique().tolist())
dependencia_sel = st.selectbox("Seleccione la Dependencia:", ["-- Seleccione --"] + dependencias)

if dependencia_sel == "-- Seleccione --":
    st.info("Seleccione una dependencia.")
    st.stop()

clave = st.text_input("Clave de acceso:", type="password")
if clave != dependencia_sel.upper() + "2025":
    st.warning("Clave incorrecta.")
    st.stop()

st.success(f"Acceso concedido a: {dependencia_sel}")

df = df_all.copy()
df_dep = df[(df["Dependencia"] == dependencia_sel) & (df["Estado Trámite"].str.lower() == "pendiente")].copy()
st.subheader(f"Expedientes pendientes - {dependencia_sel} ({len(df_dep)})")
st.write("Formato fecha: dd/mm/yyyy HH:MM:SS")

if df_dep.empty:
    st.info("No hay pendientes.")
    st.stop()

for idx, row in df_dep.iterrows():
    cols = st.columns([2,1,1,1,1])
    with cols[0]:
        st.markdown(f"**{row.get('Número de Expediente','---')}**")
        fecha_exped = row.get("Fecha de Expediente")
        fecha_exped_txt = fecha_exped.strftime("%d/%m/%Y %H:%M:%S") if not pd.isna(fecha_exped) else "---"
        st.write(f"📅 Fecha Expediente: **{fecha_exped_txt}**")
    with cols[1]:
        fecha_envio_actual = row.get("Fecha Pase DRCM")
        default_date = fecha_envio_actual.date() if (not pd.isna(fecha_envio_actual)) else date.today()
        nueva_fecha = st.date_input("Fecha Pase DRCM", value=default_date, key=f"envio_{idx}")
    with cols[2]:
        dias = compute_days_remaining(row.get("Fecha de Expediente"), row.get("Fecha Pase DRCM"))
        if dias is None:
            st.write("-- días")
        else:
            if dias >= 6:
                st.markdown(f"<span style='color:red;font-weight:bold'>{dias} días</span>", unsafe_allow_html=True)
            else:
                st.write(f"{dias} días")
    with cols[3]:
        if st.button("💾 Guardar", key=f"guardar_{idx}"):
            try:
                client = gs_client_from_secrets()
                sh = client.open_by_key(SHEET_ID)
                ws_live = sh.get_worksheet(SHEET_INDEX)
                rows = ws_live.get_all_records()
                df_live = pd.DataFrame(rows)
                df_live.columns = [c.strip() for c in df_live.columns]
            except Exception as e:
                st.error("Error recargando hoja.")
                st.exception(e)
                continue

            matches = df_live.index[df_live["Número de Expediente"] == row["Número de Expediente"]].tolist()
            if not matches:
                st.error("No se encontró en la hoja.")
                continue
            row_number = matches[0] + 2

            headers = df_live.columns.tolist()
            col_fecha_idx = headers.index("Fecha Pase DRCM") + 1
            col_dias_idx = headers.index("Días restantes") + 1

            fecha_guardar_dt = datetime.combine(nueva_fecha, time())
            fecha_str = fecha_guardar_dt.strftime("%d/%m/%Y %H:%M:%S")
            dias_calc = compute_days_remaining(pd.to_datetime(df_live.loc[matches[0],"Fecha de Expediente"],dayfirst=True,errors="coerce"), fecha_guardar_dt)

            try:
                ws_live.update_cell(row_number, col_fecha_idx, fecha_str)
                ws_live.update_cell(row_number, col_dias_idx, int(dias_calc) if dias_calc else "")
                st.success(f"Actualizado: {row['Número de Expediente']}")
                log_ws = ensure_log_sheet(sh)
                ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                log_ws.append_row([ts, dependencia_sel, dependencia_sel, row["Número de Expediente"], fecha_str])
                st.cache_data.clear()
            except Exception as e:
                st.error("Error escribiendo en Google Sheets.")
                st.exception(e)

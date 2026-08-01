import calendar
import json
import math
import os
from pathlib import Path
from typing import Iterable

import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import rasterio
import streamlit as st
from folium.plugins import Fullscreen, MeasureControl
from google.oauth2 import service_account
from plotly.subplots import make_subplots
from rasterio.io import MemoryFile
from rasterio.mask import mask as raster_mask
from rasterio.transform import array_bounds
from rasterio.warp import transform_bounds, transform_geom
from streamlit_folium import st_folium

import ee

# =============================================================================
# 1. CONFIGURACIÓN GENERAL
# =============================================================================
st.set_page_config(
    page_title="SAT de Estiaje | Estación Guardia",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ESTACION_LAT = 10.5616
ESTACION_LON = -85.5910
FECHA_INICIO_NIVEL = pd.Timestamp("2015-05-10")
FECHA_FIN_NIVEL = pd.Timestamp("2021-03-13")
P50_SEVERIDAD = 0.6648
P75_SEVERIDAD = 1.1119
EE_PROJECT_FALLBACK = os.getenv("EE_PROJECT", "proyecto-catie")
GEE_KEY_PATH = Path(os.getenv("GEE_SERVICE_ACCOUNT_FILE", ""))

# Geometrías del área aportante. 
BASIN_FILES = [
    "cuenca_aportante_guardia_gee.geojson",
]
SUBBASIN_FILES = [
    "subcuencas_guardia.geojson",
    "cuencas_aportantes_guardia_gee.geojson",
]
RIVER_FILES = [
    "cauce_tempisque.geojson",
]

ICON_FORECAST_URLS = {
    1: "https://data.meteo.tech/icon/a_pcpn_24.tif",
    2: "https://data.meteo.tech/icon/a_pcpn_48.tif",
    3: "https://data.meteo.tech/icon/a_pcpn_72.tif",
    4: "https://data.meteo.tech/icon/a_pcpn_96.tif",
    5: "https://data.meteo.tech/icon/a_pcpn_120.tif",
    6: "https://data.meteo.tech/icon/a_pcpn_144.tif",
    7: "https://data.meteo.tech/icon/a_pcpn_168.tif",
}
SPI_BASE_START = 1981

MESES = [
    "Ene", "Feb", "Mar", "Abr", "May", "Jun",
    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
]

UMBRALES = pd.DataFrame(
    {
        "mes": np.arange(1, 13),
        "nombre_mes": MESES,
        "nivel_p20_m": [0.5255, 0.4138, 0.3806, 0.3533, 0.3643, 0.5294, 0.5872, 0.5384, 0.5852, 0.7830, 0.6596, 0.6312],
        "nivel_p10_m": [0.4864, 0.4029, 0.3717, 0.3446, 0.3254, 0.5065, 0.5541, 0.5075, 0.5081, 0.6680, 0.6156, 0.5683],
        "nivel_p05_m": [0.4752, 0.3993, 0.3632, 0.3400, 0.2938, 0.4916, 0.5376, 0.4965, 0.4893, 0.5970, 0.5977, 0.5400],
    }
)

# Los colores de alerta se reservan exclusivamente para el SAT.
NAVY = "#17324D"
TEAL = "#247C7B"
SLATE = "#5E7184"
GRID = "#D9E1E8"
GREEN = "#2E7D5B"
WATCH = "#356C9B"
YELLOW = "#C9A227"
ORANGE = "#D97706"
RED = "#A33A3A"
MUTED = "#6B7C8C"

ALERT_STYLE = {
    "Verde": (GREEN, "Condición normal"),
    "Vigilancia": (WATCH, "Secuencia en observación"),
    "Amarilla": (YELLOW, "Evento persistente moderado"),
    "Naranja": (ORANGE, "Evento persistente severo"),
    "Roja": (RED, "Evento persistente extremo"),
    "Sin dato": (MUTED, "Condición no evaluable"),
}

st.markdown(
    """
    <style>
    :root {
        --navy: #17324D;
        --teal: #247C7B;
        --ink: #243746;
        --muted: #6B7C8C;
        --surface: #FFFFFF;
        --canvas: #F3F6F8;
        --line: #DCE4EA;
    }
    html, body, [class*="css"] {
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
                     "Segoe UI", sans-serif;
        color: var(--ink);
    }
    .stApp { background: var(--canvas); }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #132B43 0%, #17324D 100%);
        border-right: 1px solid rgba(255,255,255,.08);
    }
    [data-testid="stSidebar"] * { color: #F5F8FA; }
    [data-testid="stSidebar"] label { font-weight: 600; }
    [data-testid="stSidebar"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] [data-baseweb="base-input"] > div,
    [data-testid="stSidebar"] [data-baseweb="input"] > div,
    [data-testid="stSidebar"] input {
        background-color: #1D3A54 !important;
        border-color: rgba(255,255,255,.18) !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] [data-baseweb="select"] span {
        color: #FFFFFF !important;
    }
    .block-container {
        max-width: 1600px;
        padding-top: 1.4rem;
        padding-bottom: 2.5rem;
    }
    h1, h2, h3 { color: var(--navy); letter-spacing: -0.02em; }
    h1 { font-size: 2.15rem !important; margin-bottom: .1rem !important; }
    h2 { font-size: 1.42rem !important; }
    h3 { font-size: 1.05rem !important; }
    .project-subtitle {
        color: var(--teal); font-size: 1.08rem; font-weight: 650; margin-top: -.2rem;
    }
    .eyebrow {
        color: var(--muted); text-transform: uppercase; letter-spacing: .09em;
        font-size: .70rem; font-weight: 750; margin-bottom: .25rem;
    }
    .panel {
        background: var(--surface); border: 1px solid var(--line); border-radius: 14px;
        box-shadow: 0 5px 16px rgba(29, 55, 75, .045); padding: 1rem 1.1rem;
    }
    .alert-banner {
        border-radius: 14px; padding: 1rem 1.2rem; margin: .55rem 0 1rem 0;
        background: #FFFFFF; border: 1px solid var(--line);
        box-shadow: 0 5px 16px rgba(29,55,75,.045);
        display: flex; align-items: center; justify-content: space-between; gap: 1rem;
    }
    .alert-title { font-weight: 800; font-size: 1.20rem; }
    .alert-explanation { color: var(--muted); font-size: .88rem; margin-top: .2rem; }
    .alert-date { color: var(--muted); font-size: .78rem; text-align: right; min-width: 150px; }
    .kpi-card {
        background: #FFFFFF; border: 1px solid var(--line); border-radius: 13px;
        box-shadow: 0 4px 13px rgba(29,55,75,.04); padding: .85rem .95rem;
        min-height: 112px;
    }
    .kpi-label { color: var(--muted); font-size: .76rem; font-weight: 700; }
    .kpi-value { color: var(--navy); font-size: 1.43rem; font-weight: 800; margin-top: .28rem; }
    .kpi-note { color: var(--muted); font-size: .72rem; margin-top: .18rem; line-height: 1.25; }
    .section-note {
        background: #EAF2F5; border-left: 4px solid var(--teal); border-radius: 8px;
        padding: .72rem .9rem; color: #385466; font-size: .82rem;
    }
    .method-step {
        background: #FFFFFF; border: 1px solid var(--line); border-radius: 12px;
        padding: .8rem .9rem; min-height: 112px;
    }
    .method-number {
        display: inline-flex; align-items:center; justify-content:center;
        width: 28px; height: 28px; border-radius: 50%; background: var(--navy);
        color: #FFFFFF; font-size: .78rem; font-weight: 800; margin-bottom:.5rem;
    }
    .method-title { font-size: .83rem; font-weight: 750; color: var(--navy); }
    .method-text {
        font-size: .73rem; color: var(--muted); margin-top:.28rem;
        line-height: 1.45;
    }
    .forecast-heading {
        display: flex; align-items: flex-end; justify-content: space-between;
        gap: 1rem; margin: .4rem 0 .8rem;
    }
    .forecast-heading-title {
        color: var(--navy); font-size: 1.05rem; font-weight: 780;
    }
    .forecast-horizon {
        color: var(--teal); background: #E7F2F1; border: 1px solid #CBE0DE;
        border-radius: 999px; padding: .38rem .72rem; font-size: .74rem;
        font-weight: 760; white-space: nowrap;
    }
    .forecast-grid {
        display: grid;
        grid-template-columns: repeat(var(--forecast-columns), minmax(0, 1fr));
        gap: .65rem; margin: 0 0 1.15rem;
    }
    .forecast-card {
        background: #FFFFFF; border: 1px solid var(--line);
        border-top: 4px solid var(--forecast-color);
        border-radius: 13px; box-shadow: 0 5px 15px rgba(29,55,75,.05);
        padding: .78rem .72rem .72rem; min-width: 0;
    }
    .forecast-day {
        color: var(--navy); font-size: .78rem; font-weight: 800;
        display: flex; justify-content: space-between; align-items: baseline;
        gap: .35rem;
    }
    .forecast-hour {
        color: var(--muted); font-size: .64rem; font-weight: 680;
    }
    .forecast-status {
        background: var(--forecast-color); color: #FFFFFF;
        border-radius: 7px; padding: .40rem .35rem; margin: .55rem 0;
        text-align: center; font-size: .76rem; font-weight: 800;
        line-height: 1.15;
    }
    .forecast-rain {
        color: var(--navy); font-size: 1.12rem; font-weight: 820;
        letter-spacing: -.02em;
    }
    .forecast-detail {
        color: var(--muted); font-size: .67rem; line-height: 1.35;
        margin-top: .18rem;
    }
    .small-muted { color: var(--muted); font-size: .75rem; }
    div[data-testid="stTabs"] button {
        color: var(--muted) !important;
        font-weight: 700;
    }
    div[data-testid="stTabs"] button[aria-selected="true"] {
        color: var(--teal) !important;
    }
    div[data-testid="stMetric"] {
        background:#FFFFFF; border:1px solid var(--line); padding:.65rem .8rem;
        border-radius:12px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.55rem !important;
        line-height: 1.15 !important;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: clip !important;
    }
    @media (max-width: 768px) {
        .block-container { padding-left: .8rem; padding-right: .8rem; }
        .alert-banner { display:block; }
        .alert-date { text-align:left; margin-top:.65rem; }
        .forecast-heading { display:block; }
        .forecast-horizon { display:inline-block; margin-top:.55rem; }
        .forecast-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 430px) {
        .forecast-grid { grid-template-columns: 1fr; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =============================================================================

# >>> SAT_SECTION: 02_datos
# 2. DATOS: CARGA REAL CUANDO EXISTE, DEMOSTRACIÓN EN CASO CONTRARIO
# =============================================================================
def _first_existing(names: Iterable[str]) -> Path | None:
    for name in names:
        path = DATA_DIR / name
        if path.exists():
            return path
    return None


def _standardize_date(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    date_col = "fecha" if "fecha" in df.columns else "periodo"
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df.dropna(subset=[date_col]).rename(columns={date_col: "fecha"}).sort_values("fecha")


def _build_event_fields(level: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = level.copy().sort_values("fecha").reset_index(drop=True)
    data["mes"] = data["fecha"].dt.month
    data = data.drop(columns=[c for c in ["nivel_p20_m", "nivel_p10_m", "nivel_p05_m"] if c in data], errors="ignore")
    data = data.merge(UMBRALES.drop(columns="nombre_mes"), on="mes", how="left")

    conditions = [
        data["nivel_diario_m"] <= data["nivel_p05_m"],
        data["nivel_diario_m"] <= data["nivel_p10_m"],
        data["nivel_diario_m"] <= data["nivel_p20_m"],
    ]
    data["categoria_nivel"] = np.select(
        conditions,
        ["Extremadamente bajo", "Muy bajo", "Bajo"],
        default="Normal",
    )
    data.loc[data["nivel_diario_m"].isna(), "categoria_nivel"] = "Sin dato"
    data["bajo_p20"] = data["nivel_diario_m"].le(data["nivel_p20_m"])
    data["bajo_p10"] = data["nivel_diario_m"].le(data["nivel_p10_m"])
    data["bajo_p05"] = data["nivel_diario_m"].le(data["nivel_p05_m"])
    # np.where devuelve un arreglo de NumPy. Se usa np.maximum para
    # impedir déficits negativos sin llamar Series.clip sobre un ndarray.
    data["deficit_nivel_m"] = np.maximum(
        np.where(
            data["bajo_p20"],
            data["nivel_p20_m"] - data["nivel_diario_m"],
            0.0,
        ),
        0.0,
    )

    date_gap = data["fecha"].diff().dt.days.ne(1)
    new_event = data["bajo_p20"] & (~data["bajo_p20"].shift(fill_value=False) | date_gap)
    data["id_evento"] = new_event.cumsum().where(data["bajo_p20"])
    data["dias_consecutivos"] = data.groupby("id_evento").cumcount().add(1).where(data["bajo_p20"], 0)
    data["deficit_acumulado_evento"] = data.groupby("id_evento")["deficit_nivel_m"].cumsum().fillna(0)

    events = (
        data.dropna(subset=["id_evento"])
        .groupby("id_evento", as_index=False)
        .agg(
            fecha_inicio=("fecha", "min"),
            fecha_fin=("fecha", "max"),
            duracion_dias=("fecha", "size"),
            nivel_minimo_m=("nivel_diario_m", "min"),
            deficit_maximo_m=("deficit_nivel_m", "max"),
            deficit_medio_m=("deficit_nivel_m", "mean"),
            deficit_acumulado_m_dia=("deficit_nivel_m", "sum"),
            dias_bajo_p10=("bajo_p10", "sum"),
            dias_bajo_p05=("bajo_p05", "sum"),
        )
    )
    events = events.loc[events["duracion_dias"] >= 7].copy()
    events["severidad_evento"] = np.select(
        [
            events["deficit_acumulado_m_dia"] > P75_SEVERIDAD,
            events["deficit_acumulado_m_dia"] > P50_SEVERIDAD,
        ],
        ["Extremo", "Severo"],
        default="Moderado",
    )
    return data, events


@st.cache_data(show_spinner=False)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    level_path = _first_existing([
        "nivel_guardia_diario_reconstruido.csv",
        "nivel_guardia_diario_reconstruido(1).csv",
        "nivel_guardia_diario.csv",
    ])
    climate_path = _first_existing(["clima_guardia_gee.csv"])
    spi_path = _first_existing(["spi_guardia_gee.csv"])

    if level_path and climate_path and spi_path:
        level = _standardize_date(pd.read_csv(level_path, encoding="utf-8-sig"))
        climate = _standardize_date(pd.read_csv(climate_path, encoding="utf-8-sig"))
        spi = _standardize_date(pd.read_csv(spi_path, encoding="utf-8-sig"))

        required_level = {"fecha", "nivel_diario_m"}
        required_climate = {"fecha", "lluvia_mm", "eto_media_cuenca_mm", "balance_diario_mm"}
        required_spi = {"fecha", "spi_1", "spi_3", "spi_6"}
        if not required_level.issubset(level.columns):
            raise ValueError(f"El CSV de nivel requiere: {sorted(required_level)}")
        if not required_climate.issubset(climate.columns):
            raise ValueError(f"El CSV climático requiere: {sorted(required_climate)}")
        if not required_spi.issubset(spi.columns):
            raise ValueError(f"El CSV de SPI requiere: {sorted(required_spi)}")

        level["nivel_diario_m"] = pd.to_numeric(level["nivel_diario_m"], errors="coerce")
        if "es_imputado" not in level.columns:
            level["es_imputado"] = False
        for col in ["lluvia_mm", "eto_media_cuenca_mm", "balance_diario_mm"]:
            climate[col] = pd.to_numeric(climate[col], errors="coerce")
        for window in [7, 30, 90]:
            if f"lluvia_acum_{window}d" not in climate:
                climate[f"lluvia_acum_{window}d"] = climate["lluvia_mm"].rolling(window).sum()
            if f"eto_acum_{window}d" not in climate:
                climate[f"eto_acum_{window}d"] = climate["eto_media_cuenca_mm"].rolling(window).sum()
            if f"balance_{window}d" not in climate:
                climate[f"balance_{window}d"] = climate["balance_diario_mm"].rolling(window).sum()
        for col in ["spi_1", "spi_3", "spi_6"]:
            spi[col] = pd.to_numeric(spi[col], errors="coerce")
        level, events = _build_event_fields(level)
        return level, climate, spi, events, ""

    missing = []
    if not level_path:
        missing.append("nivel_guardia_diario_reconstruido.csv (GitHub)")
    if not climate_path:
        missing.append("clima_guardia_gee.csv (actualizado desde GEE)")
    if not spi_path:
        missing.append("spi_guardia_gee.csv (derivado de CHIRPS/GEE)")
    raise FileNotFoundError(
        "Faltan archivos requeridos: " + ", ".join(missing) + ". "
        "Ejecute el workflow «Actualizar clima desde GEE» en GitHub Actions."
    )


try:
    level, climate, spi, events, data_mode = load_data()
except Exception as exc:
    st.error(f"No fue posible cargar los datos: {exc}")
    st.stop()

CLIMATE_COMMON_START_DATE = climate["fecha"].min().normalize()
CLIMATE_COMMON_END_DATE = climate["fecha"].max().normalize()
CLIMATE_LAST_COMPLETE_PERIOD = (
    CLIMATE_COMMON_END_DATE.to_period("M")
    if CLIMATE_COMMON_END_DATE.is_month_end
    else CLIMATE_COMMON_END_DATE.to_period("M") - 1
)
SPI_BASE_END = (
    CLIMATE_COMMON_END_DATE.year
    if (
        CLIMATE_COMMON_END_DATE.month == 12
        and CLIMATE_COMMON_END_DATE.day == 31
    )
    else CLIMATE_COMMON_END_DATE.year - 1
)
if SPI_BASE_END < SPI_BASE_START:
    st.error("No existe al menos un año climático completo para el geoportal.")
    st.stop()

# =============================================================================
# <<< SAT_SECTION: 02_datos

# >>> SAT_SECTION: 03_funciones_auxiliares
# 3. FUNCIONES AUXILIARES DE PRESENTACIÓN Y ESTADO
# =============================================================================
def fmt_date(value: pd.Timestamp) -> str:
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    return f"{value.day} de {months[value.month - 1]} de {value.year}"


def kpi_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_row_for_date(date: pd.Timestamp) -> pd.Series:
    valid = level.loc[level["fecha"].le(date)]
    if valid.empty:
        return level.iloc[0]
    return valid.iloc[-1]


def get_alert_state(row: pd.Series) -> tuple[str, str, str]:
    if pd.isna(row.get("nivel_diario_m", np.nan)):
        return "Sin dato", "No evaluable", "No existe un nivel válido para la fecha seleccionada."
    persistence = int(row.get("dias_consecutivos", 0))
    deficit = float(row.get("deficit_acumulado_evento", 0.0))
    if not bool(row.get("bajo_p20", False)):
        return "Verde", "Sin evento", "El nivel se encuentra por encima del P20 mensual."
    if persistence < 7:
        return "Vigilancia", "En observación", f"Se contabilizan {persistence} días consecutivos bajo P20."
    if deficit <= P50_SEVERIDAD:
        return "Amarilla", "Moderado", "Evento confirmado; déficit acumulado igual o inferior al P50."
    if deficit <= P75_SEVERIDAD:
        return "Naranja", "Severo", "Evento confirmado; déficit acumulado entre P50 y P75."
    return "Roja", "Extremo", "Evento confirmado; déficit acumulado superior al P75."


def csv_bytes(data: pd.DataFrame) -> bytes:
    """Serializa una tabla con codificación compatible con Excel en español."""
    return data.to_csv(index=False).encode("utf-8-sig")


@st.cache_resource(show_spinner=False)
def fit_level_forecast_model() -> dict:
    """Ajusta una regresión ridge diaria para el escenario hidrométrico a 7 días.

    El modelo relaciona el nivel del día, su tendencia, los antecedentes
    hidroclimáticos y la lluvia del día siguiente. Es un componente preliminar
    de esta versión; no sustituye un modelo hidrológico calibrado.
    """
    merged = (
        level[["fecha", "nivel_diario_m"]]
        .merge(
            climate[["fecha", "lluvia_mm", "balance_diario_mm"]],
            on="fecha",
            how="inner",
        )
        .sort_values("fecha")
        .reset_index(drop=True)
    )
    spi_model = spi[["fecha", "spi_1"]].copy()
    spi_model["mes_fecha"] = spi_model["fecha"].dt.to_period("M")
    merged["mes_fecha"] = merged["fecha"].dt.to_period("M")
    merged = merged.merge(
        spi_model[["mes_fecha", "spi_1"]],
        on="mes_fecha",
        how="left",
    )
    merged["tendencia_7d"] = merged["nivel_diario_m"].diff(7).div(7)
    merged["lluvia_previa_7d"] = merged["lluvia_mm"].rolling(7).sum()
    merged["balance_previo_30d"] = merged["balance_diario_mm"].rolling(30).sum()
    merged["lluvia_siguiente_mm"] = merged["lluvia_mm"].shift(-1)
    merged["nivel_siguiente_m"] = merged["nivel_diario_m"].shift(-1)
    angle = 2 * np.pi * merged["fecha"].dt.dayofyear / 365.25
    merged["seno_doy"] = np.sin(angle)
    merged["coseno_doy"] = np.cos(angle)

    feature_names = [
        "nivel_diario_m",
        "tendencia_7d",
        "lluvia_previa_7d",
        "balance_previo_30d",
        "spi_1",
        "seno_doy",
        "coseno_doy",
        "lluvia_siguiente_mm",
    ]
    training = merged.dropna(subset=feature_names + ["nivel_siguiente_m"]).copy()
    if len(training) < 180:
        raise RuntimeError(
            "No existe traslape suficiente entre nivel y clima para ajustar "
            "el escenario hidrométrico."
        )

    x = training[feature_names].to_numpy(dtype=float)
    y = training["nivel_siguiente_m"].to_numpy(dtype=float)
    x_mean = x.mean(axis=0)
    x_std = x.std(axis=0)
    x_std[x_std < 1e-9] = 1.0
    y_mean = float(y.mean())
    xs = (x - x_mean) / x_std

    # Ridge cerrado: estabiliza predictores correlacionados sin añadir sklearn.
    ridge_lambda = 1.0
    beta = np.linalg.solve(
        xs.T @ xs + ridge_lambda * np.eye(xs.shape[1]),
        xs.T @ (y - y_mean),
    )
    daily_changes = training["nivel_siguiente_m"] - training["nivel_diario_m"]
    return {
        "feature_names": feature_names,
        "x_mean": x_mean,
        "x_std": x_std,
        "y_mean": y_mean,
        "beta": beta,
        "change_low": float(daily_changes.quantile(0.01)),
        "change_high": float(daily_changes.quantile(0.99)),
        "level_low": float(level["nivel_diario_m"].quantile(0.005)),
        "level_high": float(level["nivel_diario_m"].quantile(0.995)),
    }


def build_level_forecast_scenario(daily_rain: list[float]) -> pd.DataFrame:
    """Proyecta hasta siete pasos y aplica umbrales, persistencia y severidad."""
    if not 1 <= len(daily_rain) <= 7:
        raise ValueError("El escenario requiere entre uno y siete acumulados diarios.")

    model = fit_level_forecast_model()
    base = level.dropna(subset=["nivel_diario_m"]).iloc[-1]
    base_date = pd.Timestamp(base["fecha"])
    level_history = (
        level.loc[level["fecha"].le(base_date), "nivel_diario_m"]
        .dropna()
        .tail(8)
        .astype(float)
        .tolist()
    )
    rain_history = (
        climate.loc[climate["fecha"].le(base_date), "lluvia_mm"]
        .dropna()
        .tail(7)
        .astype(float)
        .tolist()
    )
    balance_history = (
        climate.loc[climate["fecha"].le(base_date), "balance_diario_mm"]
        .dropna()
        .tail(30)
        .astype(float)
        .tolist()
    )
    eto_climatology = (
        climate.assign(mes=climate["fecha"].dt.month)
        .groupby("mes")["eto_media_cuenca_mm"]
        .mean()
    )

    persistence = int(base.get("dias_consecutivos", 0))
    accumulated_deficit = float(base.get("deficit_acumulado_evento", 0.0))
    previous_alert = get_alert_state(base)[0]
    alert_order = {"Verde": 0, "Vigilancia": 1, "Amarilla": 2, "Naranja": 3, "Roja": 4}
    records = []

    for horizon, rain_value in enumerate(daily_rain, start=1):
        scenario_date = base_date + pd.Timedelta(days=horizon)
        current_level = float(level_history[-1])
        reference_level = float(level_history[-8]) if len(level_history) >= 8 else float(level_history[0])
        trend_7d = (current_level - reference_level) / max(min(len(level_history) - 1, 7), 1)
        rain_previous_7d = float(sum(rain_history[-7:]))
        balance_previous_30d = float(sum(balance_history[-30:]))
        spi_candidates = spi.loc[
            spi["fecha"].le(scenario_date.to_period("M").start_time),
            "spi_1",
        ].dropna()
        spi_1_value = float(spi_candidates.iloc[-1]) if not spi_candidates.empty else 0.0
        angle = 2 * np.pi * scenario_date.dayofyear / 365.25

        features = np.array(
            [
                current_level,
                trend_7d,
                rain_previous_7d,
                balance_previous_30d,
                spi_1_value,
                math.sin(angle),
                math.cos(angle),
                float(rain_value),
            ],
            dtype=float,
        )
        predicted = model["y_mean"] + ((features - model["x_mean"]) / model["x_std"]) @ model["beta"]
        daily_change = float(
            np.clip(
                predicted - current_level,
                model["change_low"],
                model["change_high"],
            )
        )
        predicted = float(
            np.clip(
                current_level + daily_change,
                model["level_low"],
                model["level_high"],
            )
        )

        monthly_thresholds = UMBRALES.loc[UMBRALES["mes"].eq(scenario_date.month)].iloc[0]
        p20 = float(monthly_thresholds["nivel_p20_m"])
        p10 = float(monthly_thresholds["nivel_p10_m"])
        p05 = float(monthly_thresholds["nivel_p05_m"])
        below_p20 = predicted <= p20
        if below_p20:
            persistence += 1
            accumulated_deficit += max(p20 - predicted, 0.0)
        else:
            persistence = 0
            accumulated_deficit = 0.0

        category = (
            "Extremadamente bajo" if predicted <= p05
            else "Muy bajo" if predicted <= p10
            else "Bajo" if predicted <= p20
            else "Normal"
        )
        state_row = pd.Series(
            {
                "nivel_diario_m": predicted,
                "bajo_p20": below_p20,
                "dias_consecutivos": persistence,
                "deficit_acumulado_evento": accumulated_deficit,
            }
        )
        alert, severity, _ = get_alert_state(state_row)
        if alert_order[alert] > alert_order[previous_alert]:
            evolution = f"Se intensifica a {alert}"
        elif alert_order[alert] < alert_order[previous_alert]:
            evolution = f"Se atenúa a {alert}"
        else:
            evolution = f"Se mantiene {alert}"

        records.append(
            {
                "horizonte_dia": horizon,
                "fecha_escenario": scenario_date,
                "lluvia_icon_mm": float(rain_value),
                "nivel_proyectado_m": predicted,
                "categoria_nivel": category,
                "persistencia_dias": persistence,
                "deficit_acumulado_m_dia": accumulated_deficit,
                "alerta_esperada": alert,
                "severidad": severity,
                "condicion_esperada": evolution,
            }
        )
        previous_alert = alert
        level_history.append(predicted)
        rain_history.append(float(rain_value))
        eto_future = float(eto_climatology.get(scenario_date.month, 0.0))
        balance_history.append(float(rain_value) - eto_future)

    return pd.DataFrame(records)


def base_layout(
    fig: go.Figure,
    height: int = 420,
    y_title: str | None = None,
    top_margin: int = 88,
    bottom_margin: int = 42,
    title_size: int = 18,
) -> go.Figure:
    """Aplica un diseño compacto y legible a los gráficos de Plotly."""
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=48, r=22, t=top_margin, b=bottom_margin),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Inter, sans-serif", color="#243746", size=12),
        title=dict(
            font=dict(color=NAVY, size=title_size),
            x=0.01,
            xanchor="left",
            y=0.965,
            yanchor="top",
            yref="container",
            pad=dict(t=0, b=0),
        ),
        title_automargin=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            font=dict(size=11),
            tracegroupgap=4,
        ),
        hovermode="x unified",
    )
    fig.update_xaxes(
        showgrid=False,
        linecolor=GRID,
        tickfont=dict(color=MUTED),
        automargin=True,
    )
    fig.update_yaxes(
        gridcolor=GRID,
        zerolinecolor=GRID,
        title=y_title,
        tickfont=dict(color=MUTED),
        automargin=True,
    )
    return fig


def apply_spanish_date_ticks(
    fig: go.Figure,
    start: pd.Timestamp,
    end: pd.Timestamp,
    max_ticks: int = 9,
) -> go.Figure:
    """Construye etiquetas de fecha breves en español sin depender del locale."""
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    span_days = max(int((end - start).days), 1)
    step_days = max(1, math.ceil(span_days / max(max_ticks - 1, 1)))
    tick_values = list(pd.date_range(start, end, freq=f"{step_days}D"))
    if not tick_values or tick_values[-1] != end:
        tick_values.append(end)
    tick_text = []
    previous_year = None
    for tick in tick_values:
        year_suffix = (
            f"<br>{tick.year}"
            if previous_year is None or tick.year != previous_year
            else ""
        )
        tick_text.append(f"{tick.day} {MESES[tick.month - 1]}{year_suffix}")
        previous_year = tick.year
    fig.update_xaxes(
        tickmode="array",
        tickvals=tick_values,
        ticktext=tick_text,
    )
    return fig


# =============================================================================
# <<< SAT_SECTION: 03_funciones_auxiliares

# >>> SAT_SECTION: 04_graficos
# 4. GRÁFICOS HIDROMÉTRICOS Y CLIMÁTICOS
# =============================================================================
def hydrometric_chart(
    start: pd.Timestamp,
    end: pd.Timestamp,
    show_imputed: bool,
    show_thresholds: bool,
    focus_date: pd.Timestamp | None = None,
) -> go.Figure:
    data = level.loc[level["fecha"].between(start, end)].copy()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=data["fecha"], y=data["nivel_diario_m"], mode="lines",
            name="Nivel diario", line=dict(color=NAVY, width=2.1),
            hovertemplate="%{x|%d/%m/%Y}<br>Nivel: %{y:.3f} m<extra></extra>",
        )
    )
    if show_imputed and "es_imputado" in data:
        imp = data.loc[data["es_imputado"].fillna(False)]
        fig.add_trace(
            go.Scatter(
                x=imp["fecha"], y=imp["nivel_diario_m"], mode="markers",
                name="Dato imputado",
                marker=dict(color="#7C3AED", size=6, symbol="circle-open", line=dict(width=1.4)),
                hovertemplate="%{x|%d/%m/%Y}<br>Imputado: %{y:.3f} m<extra></extra>",
            )
        )
    if show_thresholds:
        for col, name, color, dash in [
            ("nivel_p20_m", "P20 mensual", TEAL, "dash"),
            ("nivel_p10_m", "P10 mensual", ORANGE, "dash"),
            ("nivel_p05_m", "P05 mensual", RED, "dot"),
        ]:
            fig.add_trace(
                go.Scatter(
                    x=data["fecha"], y=data[col], mode="lines", name=name,
                    line=dict(color=color, width=1.5, dash=dash),
                    hovertemplate=f"%{{x|%d/%m/%Y}}<br>{name}: %{{y:.3f}} m<extra></extra>",
                )
            )

    # Resaltar eventos sin repetir textos sobre el gráfico.
    # Las bandas muestran todos los eventos; únicamente el evento asociado
    # con la fecha evaluada recibe una anotación.
    visible_events = []
    focused_event = None
    focus_ts = pd.Timestamp(focus_date) if focus_date is not None else None

    for _, event in events.iterrows():
        event_start = pd.Timestamp(event["fecha_inicio"])
        event_end = pd.Timestamp(event["fecha_fin"])

        if event_end < start or event_start > end:
            continue

        visible_events.append((event_start, event_end))
        confirm = event_start + pd.Timedelta(days=6)

        surveillance_end = min(confirm, event_end, end)
        if surveillance_end > max(event_start, start):
            fig.add_vrect(
                x0=max(event_start, start),
                x1=surveillance_end,
                fillcolor="#DCE9F3",
                opacity=0.42,
                line_width=0,
                layer="below",
            )

        if confirm < event_end and confirm <= end:
            fig.add_vrect(
                x0=max(confirm, start),
                x1=min(event_end, end),
                fillcolor="#F6D8C4",
                opacity=0.34,
                line_width=0,
                layer="below",
            )

        if focus_ts is not None and event_start <= focus_ts <= event_end:
            focused_event = (event_start, event_end, confirm)

    # Entradas de leyenda para explicar las bandas sin saturar el gráfico.
    if visible_events:
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                name="Vigilancia · días 1–6",
                marker=dict(symbol="square", size=11, color="#DCE9F3"),
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                name="Evento confirmado",
                marker=dict(symbol="square", size=11, color="#F6D8C4"),
                hoverinfo="skip",
            )
        )

    # Marcar solamente la confirmación del evento evaluado.
    if focused_event is not None:
        _, _, confirm = focused_event
        if start <= confirm <= end:
            midpoint = start + (end - start) / 2
            anchor = "right" if confirm > midpoint else "left"
            fig.add_vline(
                x=confirm,
                line_color=ORANGE,
                line_dash="dot",
                line_width=1.6,
            )
            fig.add_annotation(
                x=confirm,
                y=0.965,
                xref="x",
                yref="paper",
                text="Confirmación · día 7",
                showarrow=False,
                xanchor=anchor,
                yanchor="top",
                bgcolor="rgba(255,255,255,0.88)",
                bordercolor=ORANGE,
                borderwidth=1,
                borderpad=4,
                font=dict(size=10, color=NAVY),
            )

    fig.update_layout(title="Nivel diario y umbrales mensuales")
    fig = base_layout(
        fig,
        height=445,
        y_title="Nivel medio diario (m)",
        top_margin=108,
        bottom_margin=48,
        title_size=18,
    )
    fig.update_layout(
        margin=dict(l=55, r=25, t=108, b=48),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            font=dict(size=11),
        ),
    )
    return apply_spanish_date_ticks(fig, start, end)


def threshold_chart() -> go.Figure:
    medians = level.groupby(level["fecha"].dt.month)["nivel_diario_m"].median().reindex(range(1, 13))
    data = UMBRALES.copy()
    data["mediana"] = medians.to_numpy()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data["nombre_mes"], y=data["mediana"], name="Mediana mensual", line=dict(color=NAVY, width=2.6), mode="lines+markers"))
    fig.add_trace(go.Scatter(x=data["nombre_mes"], y=data["nivel_p20_m"], name="P20", line=dict(color=TEAL, width=1.8)))
    fig.add_trace(go.Scatter(x=data["nombre_mes"], y=data["nivel_p10_m"], name="P10", line=dict(color=ORANGE, width=1.6)))
    fig.add_trace(go.Scatter(x=data["nombre_mes"], y=data["nivel_p05_m"], name="P05", line=dict(color=RED, width=1.6)))
    fig.update_layout(title="Umbrales mensuales ajustados a la estacionalidad")
    return base_layout(fig, height=390, y_title="Nivel (m)")


def annual_hydrographs_chart(focus_year: int | None = None) -> go.Figure:
    """Alinea cada año por mes y día para comparar la estacionalidad."""
    data = level.copy()
    data["anio"] = data["fecha"].dt.year
    data["fecha_referencia"] = pd.to_datetime(
        {
            "year": np.full(len(data), 2000),
            "month": data["fecha"].dt.month,
            "day": data["fecha"].dt.day,
        },
        errors="coerce",
    )
    data = data.dropna(subset=["fecha_referencia", "nivel_diario_m"])
    years = sorted(data["anio"].unique())
    palette = [
        "#356C9B",
        "#D97706",
        "#2E7D5B",
        "#A33A3A",
        "#7C5BB5",
        "#8B6B4A",
        "#D26A9A",
    ]
    fig = go.Figure()
    for index, year in enumerate(years):
        subset = data.loc[data["anio"].eq(year)].sort_values("fecha_referencia")
        is_partial = (
            subset["fecha"].min().month != 1
            or subset["fecha"].min().day != 1
            or subset["fecha"].max().month != 12
            or subset["fecha"].max().day != 31
        )
        is_focus = focus_year is not None and int(year) == int(focus_year)
        color = palette[index % len(palette)]
        fig.add_trace(
            go.Scatter(
                x=subset["fecha_referencia"],
                y=subset["nivel_diario_m"],
                mode="lines",
                name=f"{year}{' · parcial' if is_partial else ''}",
                line=dict(
                    color=color,
                    width=3.0 if is_focus else 1.65,
                    dash="dash" if is_partial else "solid",
                ),
                opacity=1.0 if is_focus else .82,
                hovertemplate=(
                    f"{year} · %{{x|%d/%m}}"
                    "<br>Nivel: %{y:.3f} m<extra></extra>"
                ),
            )
        )
    month_ticks = pd.date_range("2000-01-01", "2000-12-01", freq="MS")
    fig.update_layout(
        title="Hidrogramas anuales alineados por día del año",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            font=dict(size=10),
        ),
    )
    fig = base_layout(
        fig,
        height=430,
        y_title="Nivel medio diario (m)",
        top_margin=106,
        bottom_margin=44,
        title_size=17,
    )
    fig.update_xaxes(
        tickmode="array",
        tickvals=month_ticks,
        ticktext=MESES,
        range=[pd.Timestamp("2000-01-01"), pd.Timestamp("2000-12-31")],
    )
    return fig


def event_anatomy_chart(
    event: pd.Series,
    focus_date: pd.Timestamp | None = None,
) -> go.Figure:
    event_start = pd.Timestamp(event["fecha_inicio"])
    event_end = pd.Timestamp(event["fecha_fin"])
    confirm_date = event_start + pd.Timedelta(days=6)
    plot_start = max(level["fecha"].min(), event_start - pd.Timedelta(days=5))
    plot_end = min(level["fecha"].max(), event_end + pd.Timedelta(days=5))

    context = level.loc[level["fecha"].between(plot_start, plot_end)].copy()
    event_data = level.loc[
        level["id_evento"].eq(event["id_evento"])
        & level["fecha"].between(event_start, event_end)
    ].copy()
    event_data["deficit_acumulado"] = event_data["deficit_nivel_m"].cumsum()

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=.09,
        row_heights=[.64, .36],
    )
    fig.add_trace(
        go.Scatter(
            x=context["fecha"],
            y=context["nivel_diario_m"],
            mode="lines",
            name="Nivel diario",
            line=dict(color=NAVY, width=2.2),
            hovertemplate="%{x|%d/%m/%Y}<br>Nivel: %{y:.3f} m<extra></extra>",
        ),
        row=1,
        col=1,
    )
    for column, name, color, dash in [
        ("nivel_p20_m", "P20 mensual", TEAL, "dash"),
        ("nivel_p10_m", "P10 mensual", ORANGE, "dash"),
        ("nivel_p05_m", "P05 mensual", RED, "dot"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=context["fecha"],
                y=context[column],
                mode="lines",
                name=name,
                line=dict(color=color, width=1.35, dash=dash),
                hovertemplate=f"%{{x|%d/%m/%Y}}<br>{name}: %{{y:.3f}} m<extra></extra>",
            ),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=event_data["fecha"],
            y=event_data["deficit_acumulado"],
            mode="lines+markers",
            name="Déficit acumulado",
            line=dict(color=ORANGE, width=2.4),
            marker=dict(size=4),
            fill="tozeroy",
            fillcolor="rgba(217,119,6,.14)",
            hovertemplate="%{x|%d/%m/%Y}<br>Déficit acumulado: %{y:.3f} m·día<extra></extra>",
        ),
        row=2,
        col=1,
    )

    fig.add_vrect(
        x0=event_start,
        x1=min(confirm_date, event_end),
        fillcolor="#DCE9F3",
        opacity=.40,
        line_width=0,
        row="all",
        col=1,
    )
    if confirm_date < event_end:
        fig.add_vrect(
            x0=confirm_date,
            x1=event_end,
            fillcolor="#F6D8C4",
            opacity=.30,
            line_width=0,
            row="all",
            col=1,
        )
    fig.add_vline(
        x=confirm_date,
        line_color=ORANGE,
        line_dash="dot",
        line_width=1.6,
        row=1,
        col=1,
    )
    fig.add_annotation(
        x=confirm_date,
        y=.98,
        xref="x",
        yref="paper",
        text="Confirmación · día 7",
        showarrow=False,
        xanchor="left",
        yanchor="top",
        bgcolor="rgba(255,255,255,.90)",
        bordercolor=ORANGE,
        borderwidth=1,
        borderpad=4,
        font=dict(size=10, color=NAVY),
    )
    fig.add_hline(
        y=P50_SEVERIDAD,
        line_dash="dash",
        line_color=YELLOW,
        annotation_text="P50",
        row=2,
        col=1,
    )
    fig.add_hline(
        y=P75_SEVERIDAD,
        line_dash="dash",
        line_color=RED,
        annotation_text="P75",
        row=2,
        col=1,
    )
    if focus_date is not None and plot_start <= pd.Timestamp(focus_date) <= plot_end:
        focus_timestamp = pd.Timestamp(focus_date)
        fig.add_vline(
            x=focus_timestamp,
            line_color=SLATE,
            line_dash="dash",
            line_width=1.2,
            row="all",
            col=1,
        )
        fig.add_annotation(
            x=focus_timestamp,
            y=.90,
            xref="x",
            yref="paper",
            text="Fecha evaluada",
            showarrow=False,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(255,255,255,.90)",
            bordercolor=SLATE,
            borderwidth=1,
            borderpad=4,
            font=dict(size=10, color=NAVY),
        )

    fig.update_layout(
        title=f"Anatomía del evento · {event_start:%d/%m/%Y}–{event_end:%d/%m/%Y}",
        showlegend=True,
    )
    fig = base_layout(fig, height=570)
    fig.update_layout(
        margin=dict(l=58, r=24, t=112, b=45),
        title=dict(
            x=0.01,
            xanchor="left",
            y=0.965,
            yanchor="top",
            yref="container",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            font=dict(size=11),
        ),
    )
    fig.update_yaxes(title_text="Nivel (m)", row=1, col=1)
    fig.update_yaxes(title_text="Déficit (m·día)", row=2, col=1)
    return apply_spanish_date_ticks(fig, plot_start, plot_end)


def climate_series_chart(variable: str, window: int, start: pd.Timestamp, end: pd.Timestamp) -> go.Figure:
    data = climate.loc[climate["fecha"].between(start, end)].copy()
    mapping = {
        "Precipitación": (f"lluvia_acum_{window}d", "Precipitación acumulada", "mm", NAVY),
        "ETo equivalente": (f"eto_acum_{window}d", "ETo equivalente acumulada", "mm", ORANGE),
        "Balance P−ETo": (f"balance_{window}d", "Balance climático acumulado", "mm", TEAL),
    }
    col, title, unit, color = mapping[variable]

    # Para periodos extensos se conserva la señal de la ventana antecedente,
    # pero se muestra su promedio mensual. Esto evita dibujar más de 16 000
    # observaciones diarias en la vista histórica completa.
    is_long_period = (pd.Timestamp(end) - pd.Timestamp(start)).days > 730
    if is_long_period:
        data = (
            data.set_index("fecha")[[col]]
            .resample("MS")
            .mean()
            .dropna()
            .reset_index()
        )
        trace_name = f"{window} días · promedio mensual"
        chart_title = f"{title} · {window} d · promedio mensual"
    else:
        trace_name = f"{window} días"
        chart_title = f"{title} · {window} días"

    fig = go.Figure(
        go.Scatter(
            x=data["fecha"],
            y=data[col],
            mode="lines",
            name=trace_name,
            line=dict(color=color, width=2.2),
        )
    )
    if variable == "Balance P−ETo":
        fig.add_hline(y=0, line_color=SLATE, line_width=1)
    fig.update_layout(title=chart_title)
    return base_layout(fig, height=400, y_title=unit, top_margin=86, title_size=17)


def climatology_chart() -> go.Figure:
    data = climate.loc[
        climate["fecha"].between("1991-01-01", "2020-12-31")
    ].copy()
    data["anio"] = data["fecha"].dt.year
    data["mes"] = data["fecha"].dt.month
    monthly = (
        data.groupby(["anio", "mes"], as_index=False)
        .agg(
            lluvia=("lluvia_mm", "sum"),
            eto=("eto_media_cuenca_mm", "sum"),
            dias_validos=("lluvia_mm", "count"),
        )
        .loc[lambda frame: frame["dias_validos"].ge(27)]
    )
    clim = monthly.groupby("mes").agg(
        lluvia=("lluvia", "mean"),
        lluvia_p10=("lluvia", lambda values: values.quantile(.10)),
        lluvia_p90=("lluvia", lambda values: values.quantile(.90)),
        eto=("eto", "mean"),
    ).reindex(range(1, 13))
    fig = go.Figure()
    fig.add_bar(
        x=MESES,
        y=clim["lluvia"],
        name="Precipitación",
        marker_color=NAVY,
        opacity=.82,
        error_y=dict(
            type="data",
            symmetric=False,
            array=(clim["lluvia_p90"] - clim["lluvia"]).clip(lower=0),
            arrayminus=(clim["lluvia"] - clim["lluvia_p10"]).clip(lower=0),
            color=SLATE,
            thickness=1,
        ),
    )
    fig.add_trace(
        go.Scatter(
            x=MESES,
            y=clim["eto"],
            name="ETo equivalente",
            line=dict(color=ORANGE, width=2.4),
            mode="lines+markers",
        )
    )
    fig.update_layout(title="Climatología mensual 1991–2020")
    fig = base_layout(
        fig,
        height=390,
        y_title="Milímetros por mes",
        top_margin=86,
        bottom_margin=44,
        title_size=17,
    )
    fig.update_layout(
        margin=dict(l=52, r=18, t=86, b=44),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            font=dict(size=11),
        ),
    )
    return fig


def spi_chart(scale: int, start: pd.Timestamp, end: pd.Timestamp) -> go.Figure:
    col = f"spi_{scale}"
    data = spi.loc[spi["fecha"].between(start.to_period("M").start_time, end.to_period("M").start_time)].copy()
    colors = np.where(data[col] < -1.5, RED, np.where(data[col] < -1, ORANGE, np.where(data[col] < 0, "#D9A8A8", np.where(data[col] < 1, "#A9C7D8", TEAL))))
    fig = go.Figure()
    for lower, upper, color in [
        (-3.5, -2.0, "rgba(163,58,58,.15)"),
        (-2.0, -1.5, "rgba(217,119,6,.14)"),
        (-1.5, -1.0, "rgba(201,162,39,.14)"),
    ]:
        fig.add_hrect(
            y0=lower,
            y1=upper,
            fillcolor=color,
            line_width=0,
            layer="below",
        )
    fig.add_trace(
        go.Bar(
            x=data["fecha"],
            y=data[col],
            marker_color=colors,
            name=f"SPI-{scale}",
            hovertemplate="%{x|%m/%Y}<br>SPI: %{y:.2f}<extra></extra>",
        )
    )
    for y, dash in [(-1, "dot"), (-1.5, "dash"), (-2, "dash")]:
        fig.add_hline(y=y, line_color="#8E3A3A", line_dash=dash, line_width=1)
    fig.add_hline(y=0, line_color=SLATE, line_width=1)
    fig.update_layout(title=f"Evolución temporal del SPI-{scale}", showlegend=False)
    fig = base_layout(fig, height=440, y_title=f"SPI-{scale}")
    fig.update_yaxes(range=[-3.2, 3.2])
    return fig


def forecast_scenario_chart(scenario: pd.DataFrame) -> go.Figure:
    """Combina la entrada ICON con el nivel proyectado y los umbrales mensuales."""
    dates = scenario["fecha_escenario"]
    horizons = scenario["horizonte_dia"].map(lambda value: f"Día {int(value)}")
    threshold_rows = UMBRALES.set_index("mes").loc[dates.dt.month]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(
        x=horizons,
        y=scenario["lluvia_icon_mm"],
        name="Lluvia ICON diaria",
        marker_color="#4B9CD3",
        opacity=.70,
        secondary_y=True,
        hovertemplate="%{x}<br>Lluvia: %{y:.1f} mm<extra></extra>",
    )
    fig.add_trace(
        go.Scatter(
            x=horizons,
            y=scenario["nivel_proyectado_m"],
            mode="lines+markers",
            name="Nivel proyectado",
            line=dict(color=NAVY, width=3),
            marker=dict(size=8),
            hovertemplate="%{x}<br>Nivel: %{y:.3f} m<extra></extra>",
        ),
        secondary_y=False,
    )
    for column, label, color, dash in [
        ("nivel_p20_m", "P20", YELLOW, "dash"),
        ("nivel_p10_m", "P10", ORANGE, "dot"),
        ("nivel_p05_m", "P05", RED, "dot"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=horizons,
                y=threshold_rows[column].to_numpy(),
                mode="lines",
                name=label,
                line=dict(color=color, width=1.5, dash=dash),
                hoverinfo="skip",
            ),
            secondary_y=False,
        )
    fig.update_layout(
        template="plotly_white",
        height=420,
        title=f"Escenario hidrométrico preliminar · {len(scenario)} días disponibles",
        margin=dict(l=50, r=50, t=90, b=45),
        legend=dict(orientation="h", y=1.02, x=0),
        hovermode="x unified",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Inter, sans-serif", color="#243746"),
    )
    fig.update_yaxes(title_text="Nivel (m)", gridcolor=GRID, secondary_y=False)
    fig.update_yaxes(title_text="Lluvia diaria (mm)", showgrid=False, secondary_y=True)
    fig.update_xaxes(showgrid=False, linecolor=GRID, title_text="Horizonte")
    return fig


# =============================================================================
# <<< SAT_SECTION: 04_graficos

# >>> SAT_SECTION: 05_componente_geoespacial
# 5. COMPONENTE GEOESPACIAL: GEE, GEOJSON TEMPORALES E ICON
# =============================================================================
def _geojson_to_ee_geometry(geojson_data: dict) -> ee.Geometry:
    """Convierte Geometry, Feature o FeatureCollection de GeoJSON a ee.Geometry."""
    geojson_type = geojson_data.get("type")
    if geojson_type == "FeatureCollection":
        geometries = [
            ee.Geometry(feature["geometry"])
            for feature in geojson_data.get("features", [])
            if feature.get("geometry")
        ]
        if not geometries:
            raise ValueError("El GeoJSON de la cuenca no contiene geometrías.")
        return ee.FeatureCollection(
            [ee.Feature(geometry) for geometry in geometries]
        ).geometry()
    if geojson_type == "Feature":
        return ee.Geometry(geojson_data["geometry"])
    return ee.Geometry(geojson_data)


def _geojson_geometries(geojson_data: dict) -> list[dict]:
    """Extrae una lista de geometrías para recortar los GeoTIFF de ICON."""
    if geojson_data.get("type") == "FeatureCollection":
        return [
            feature["geometry"]
            for feature in geojson_data.get("features", [])
            if feature.get("geometry")
        ]
    if geojson_data.get("type") == "Feature":
        return [geojson_data["geometry"]]
    return [geojson_data]


def _shift_geometry_to_360(geometry: dict) -> dict:
    """Convierte longitudes negativas a 0–360 para GeoTIFF que usan ese dominio."""
    shifted = json.loads(json.dumps(geometry))

    def shift_coordinates(values):
        if (
            isinstance(values, list)
            and len(values) >= 2
            and isinstance(values[0], (int, float))
            and isinstance(values[1], (int, float))
        ):
            return [
                values[0] + 360 if values[0] < 0 else values[0],
                values[1],
                *values[2:],
            ]
        return [shift_coordinates(value) for value in values]

    if "coordinates" in shifted:
        shifted["coordinates"] = shift_coordinates(shifted["coordinates"])
    elif shifted.get("type") == "GeometryCollection":
        shifted["geometries"] = [
            _shift_geometry_to_360(item)
            for item in shifted.get("geometries", [])
        ]
    return shifted


@st.cache_resource(show_spinner=False)
def initialize_earth_engine() -> bool:
    """Inicializa GEE con Streamlit Secrets o con un archivo local opcional."""
    service_account_info = None

    try:
        available_secrets = set(st.secrets.keys())
    except Exception:
        # Es normal cuando se ejecuta localmente sin secrets.toml.
        available_secrets = set()

    if "GEE_SERVICE_ACCOUNT_JSON" in available_secrets:
        secret_value = st.secrets["GEE_SERVICE_ACCOUNT_JSON"]
        service_account_info = (
            json.loads(secret_value)
            if isinstance(secret_value, str)
            else dict(secret_value)
        )
    elif "gee_service_account" in available_secrets:
        service_account_info = dict(st.secrets["gee_service_account"])

    if service_account_info is None and GEE_KEY_PATH.is_file():
        service_account_info = json.loads(
            GEE_KEY_PATH.read_text(encoding="utf-8")
        )

    if not service_account_info:
        raise RuntimeError(
            "No se configuró GEE_SERVICE_ACCOUNT_JSON en los secretos de "
            "Streamlit. Consulte GUIA_PUBLICACION.md."
        )

    private_key = service_account_info.get("private_key")
    if isinstance(private_key, str):
        service_account_info["private_key"] = private_key.replace("\\n", "\n")

    ee_project = (
        os.getenv("EE_PROJECT")
        or service_account_info.get("project_id")
        or EE_PROJECT_FALLBACK
    )
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=[
            "https://www.googleapis.com/auth/earthengine",
            "https://www.googleapis.com/auth/cloud-platform",
        ],
    )
    ee.Initialize(credentials=credentials, project=ee_project)
    return True


def _monthly_chirps_total(year: ee.Number, month: int) -> ee.Image:
    start = ee.Date.fromYMD(ee.Number(year).toInt(), month, 1)
    end = start.advance(1, "month")
    return (
        ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
        .filterDate(start, end)
        .select("precipitation")
        .sum()
        .rename("value")
    )


def _era5_potential_evaporation_mm(image: ee.Image) -> ee.Image:
    """Convierte la evaporación potencial diaria de ERA5-Land de m a mm."""
    return (
        ee.Image(image)
        .select("potential_evaporation_sum")
        .multiply(-1000)
        .max(0)
        .rename("value")
    )


def _monthly_era5_eto_total(year: ee.Number, month: int) -> ee.Image:
    start = ee.Date.fromYMD(ee.Number(year).toInt(), month, 1)
    end = start.advance(1, "month")
    return (
        ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
        .filterDate(start, end)
        .map(_era5_potential_evaporation_mm)
        .sum()
        .rename("value")
    )


def _spi_gamma_image(target_date: ee.Date, scale_months: int) -> ee.Image:
    """Calcula SPI raster usando todos los años completos del período común."""
    target_end = target_date.advance(1, "month")
    target_start = target_end.advance(-scale_months, "month")
    target = (
        ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
        .filterDate(target_start, target_end)
        .select("precipitation")
        .sum()
        .rename("value")
    )
    target_month = ee.Number(target_date.get("month"))
    years = ee.List.sequence(SPI_BASE_START, SPI_BASE_END)

    def accumulated_for_year(year):
        hist_end = ee.Date.fromYMD(
            ee.Number(year).toInt(),
            target_month,
            1,
        ).advance(1, "month")
        hist_start = hist_end.advance(-scale_months, "month")
        return (
            ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
            .filterDate(hist_start, hist_end)
            .select("precipitation")
            .sum()
            .rename("value")
        )

    history = ee.ImageCollection.fromImages(years.map(accumulated_for_year))
    positive = history.map(lambda image: ee.Image(image).updateMask(ee.Image(image).gt(0)))
    mean = positive.mean().max(1e-6)
    mean_log = positive.map(lambda image: ee.Image(image).log()).mean()
    a_value = mean.log().subtract(mean_log).max(1e-6)
    alpha = (
        ee.Image(1)
        .add(ee.Image(1).add(a_value.multiply(4 / 3)).sqrt())
        .divide(a_value.multiply(4))
    )
    beta = mean.divide(alpha)
    zero_probability = history.map(
        lambda image: ee.Image(image).eq(0)
    ).sum().divide(history.count().max(1))
    gamma_cdf = target.max(1e-6).divide(beta).gammainc(alpha)
    probability = (
        zero_probability
        .add(ee.Image(1).subtract(zero_probability).multiply(gamma_cdf))
        .clamp(1e-6, 1 - 1e-6)
    )
    return probability.multiply(2).subtract(1).erfInv().multiply(math.sqrt(2)).rename("SPI")


@st.cache_data(ttl=3300, show_spinner=False)
def get_geoportal_tile_url(
    variable: str,
    date_iso: str,
    basin_geojson_text: str,
) -> tuple[str | None, str, dict | None]:
    """Genera la capa raster elegida, siempre recortada a la cuenca."""
    try:
        initialize_earth_engine()
        selected = pd.Timestamp(date_iso)
        month = int(selected.month)
        basin_geometry = _geojson_to_ee_geometry(json.loads(basin_geojson_text))

        if variable == "DEM":
            image = ee.Image("USGS/SRTMGL1_003").select("elevation")
            vis = {
                "min": 0,
                "max": 1800,
                "palette": ["0B3D2E", "2F7D5B", "86B96B", "D8C982", "B98255", "76513B", "F4F1E8"],
            }
            label = "DEM SRTM 30 m"
            legend = {"min": "0 m", "max": "1800 m", "palette": vis["palette"]}
        elif variable == "Precipitación media mensual histórica":
            years = ee.List.sequence(SPI_BASE_START, SPI_BASE_END)
            image = ee.ImageCollection.fromImages(
                years.map(lambda year: _monthly_chirps_total(year, month))
            ).mean()
            vis = {
                "min": 0,
                "max": 450,
                "palette": ["F7FBFF", "C6DBEF", "6BAED6", "2171B5", "08306B"],
            }
            label = f"Precipitación media de {MESES[month - 1]} · CHIRPS {SPI_BASE_START}–{SPI_BASE_END}"
            legend = {"min": "0 mm/mes", "max": "450 mm/mes", "palette": vis["palette"]}
        elif variable == "ETo equivalente media mensual histórica":
            years = ee.List.sequence(SPI_BASE_START, SPI_BASE_END)
            image = ee.ImageCollection.fromImages(
                years.map(
                    lambda year: _monthly_era5_eto_total(year, month)
                )
            ).mean()
            vis = {
                "min": 60,
                "max": 220,
                "palette": ["FFF7BC", "FEC44F", "FE9929", "EC7014", "CC4C02", "8C2D04"],
            }
            label = (
                f"ETo equivalente media de {MESES[month - 1]} · "
                f"ERA5-Land {SPI_BASE_START}–{SPI_BASE_END}"
            )
            legend = {"min": "60 mm/mes", "max": "220 mm/mes", "palette": vis["palette"]}
        else:
            scale_months = int(variable.split("-")[1].split()[0])
            target_date = ee.Date.fromYMD(int(selected.year), month, 1)
            image = _spi_gamma_image(target_date, scale_months)
            vis = {
                "min": -2.5,
                "max": 2.5,
                "palette": ["7F0000", "D7301F", "FC8D59", "FEE08B", "FFFFBF", "D9EF8B", "91CF60", "1A9850", "006837"],
            }
            label = f"SPI-{scale_months} · {selected:%m/%Y} · ajuste gamma"
            legend = {"min": "−2.5 seco", "max": "+2.5 húmedo", "palette": vis["palette"]}

        map_id = image.clip(basin_geometry).getMapId(vis)
        return map_id["tile_fetcher"].url_format, label, legend
    except Exception as exc:
        return None, f"No fue posible preparar la capa: {exc}", None


@st.cache_data(ttl=86_400, show_spinner=False)
def get_dem_physiographic_stats(
    basin_geojson_text: str,
) -> tuple[dict | None, str]:
    """Obtiene área y elevaciones SRTM del área aportante."""
    try:
        initialize_earth_engine()
        geometry = _geojson_to_ee_geometry(
            json.loads(basin_geojson_text)
        )
        elevation = (
            ee.Image("USGS/SRTMGL1_003")
            .select("elevation")
            .rename("elevation")
        )
        reducer = ee.Reducer.minMax().combine(
            reducer2=ee.Reducer.mean(),
            sharedInputs=True,
        )
        zonal = elevation.reduceRegion(
            reducer=reducer,
            geometry=geometry,
            scale=30,
            bestEffort=True,
            maxPixels=1_000_000_000,
            tileScale=4,
        )
        result = ee.Dictionary(zonal).set(
            "area_km2",
            geometry.area(maxError=100).divide(1_000_000),
        ).getInfo()
        return (
            {
                "area_km2": float(result["area_km2"]),
                "elevation_min_m": float(result["elevation_min"]),
                "elevation_mean_m": float(result["elevation_mean"]),
                "elevation_max_m": float(result["elevation_max"]),
            },
            "SRTM 30 m · estadísticas zonales del área aportante",
        )
    except Exception as exc:
        return None, f"No fue posible calcular los indicadores DEM: {exc}"


def _add_map_legend(map_obj: folium.Map, title: str, legend: dict) -> None:
    colors = ", ".join(f"#{color.lstrip('#')}" for color in legend["palette"])
    ticks = legend.get("ticks")
    if ticks:
        tick_html = (
            '<div style="display:flex;justify-content:space-between;'
            'gap:2px;font-size:10px;">'
            + "".join(f"<span>{tick}</span>" for tick in ticks)
            + "</div>"
        )
    else:
        tick_html = (
            '<div style="display:flex;justify-content:space-between;">'
            f"<span>{legend['min']}</span><span>{legend['max']}</span>"
            "</div>"
        )
    html = f"""
    <div style="
      position: fixed; z-index: 9999; right: 28px; bottom: 28px;
      width: 245px; padding: 10px 12px; background: rgba(255,255,255,.94);
      border: 1px solid #DCE4EA; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,.13);
      font-family: Inter, Segoe UI, sans-serif; font-size: 11px; color: #243746;">
      <b>{title}</b>
      <div style="height:10px; margin:7px 0 4px; border-radius:4px;
                  background:linear-gradient(to right, {colors});"></div>
      {tick_html}
    </div>
    """
    map_obj.get_root().html.add_child(folium.Element(html))


def create_map(
    alert_name: str,
    row: pd.Series,
    compact: bool = False,
    layer_variable: str = "DEM",
    layer_date: pd.Timestamp | None = None,
    opacity: float = .72,
    show_subbasins: bool = True,
    show_station: bool = True,
) -> tuple[folium.Map, bool, str]:
    map_obj = folium.Map(
        location=[ESTACION_LAT, ESTACION_LON],
        zoom_start=9 if compact else 8,
        tiles=None,
        control_scale=True,
        zoom_control=True,
    )
    folium.TileLayer(tiles="CartoDB positron", name="Mapa base", control=False).add_to(map_obj)
    if not compact:
        Fullscreen(position="topright").add_to(map_obj)
        MeasureControl(
            position="topleft",
            primary_length_unit="kilometers",
            secondary_length_unit="meters",
        ).add_to(map_obj)

    basin_path = _first_existing(BASIN_FILES)
    subbasin_path = _first_existing(SUBBASIN_FILES)
    analysis_path = subbasin_path or basin_path
    river_path = _first_existing(RIVER_FILES)
    basin_geojson = None
    basin_layer = None
    subbasin_layer = None
    raster_added = False
    raster_status = "La capa raster se carga únicamente en el geoportal principal."

    if analysis_path:
        display_basin_path = basin_path or analysis_path
        basin_geojson = json.loads(
            display_basin_path.read_text(encoding="utf-8")
        )
        if not compact:
            analysis_geojson = json.loads(
                analysis_path.read_text(encoding="utf-8")
            )
            basin_text = json.dumps(
                analysis_geojson,
                ensure_ascii=False,
                sort_keys=True,
            )
            tile_url, raster_status, legend = get_geoportal_tile_url(
                layer_variable,
                (layer_date or pd.Timestamp("2020-05-01")).strftime("%Y-%m-%d"),
                basin_text,
            )
            if tile_url:
                folium.TileLayer(
                    tiles=tile_url,
                    attr="Google Earth Engine",
                    name=raster_status,
                    overlay=True,
                    control=True,
                    opacity=opacity,
                    show=True,
                ).add_to(map_obj)
                raster_added = True
                if legend:
                    _add_map_legend(map_obj, raster_status, legend)

        basin_layer = folium.GeoJson(
            basin_geojson,
            name="Área aportante a Guardia",
            style_function=lambda _: {
                "color": NAVY,
                "weight": 2.3,
                "fillColor": "#9CC7D4",
                "fillOpacity": .16 if compact else .04,
            },
            tooltip="Área aportante aguas arriba de Guardia",
        )
        basin_layer.add_to(map_obj)
    else:
        raster_status = (
            "Falta data/subcuencas_guardia.geojson para delimitar "
            "el área aportante."
        )

    if show_subbasins and subbasin_path:
        subbasin_layer = folium.GeoJson(
            json.loads(subbasin_path.read_text(encoding="utf-8")),
            name="Subcuencas aportantes a Guardia",
            style_function=lambda _: {
                "color": TEAL,
                "weight": 1.45,
                "fillColor": "#B9D9D4",
                "fillOpacity": .10,
            },
            tooltip="Subcuencas aportantes aguas arriba de Guardia",
        )
        subbasin_layer.add_to(map_obj)
    if river_path:
        folium.GeoJson(
            json.loads(river_path.read_text(encoding="utf-8")),
            name="Cauce principal del río Tempisque",
            style_function=lambda _: {
                "color": "#1565C0",
                "weight": 4.0,
                "opacity": .95,
            },
            tooltip="Cauce principal del río Tempisque · GitHub",
        ).add_to(map_obj)

    if show_station:
        marker_color = {
            "Verde": "green",
            "Vigilancia": "blue",
            "Amarilla": "beige",
            "Naranja": "orange",
            "Roja": "red",
            "Sin dato": "gray",
        }[alert_name]
        popup = folium.Popup(
            f"""
            <div style='font-family:Inter, Segoe UI, sans-serif; min-width:220px'>
              <b>Estación Guardia (190302)</b><br>
              Nivel: {row['nivel_diario_m']:.3f} m<br>
              P20 mensual: {row['nivel_p20_m']:.3f} m<br>
              Persistencia: {int(row['dias_consecutivos'])} días<br>
              Alerta: <b>{alert_name}</b>
            </div>
            """,
            max_width=280,
        )
        folium.Marker(
            [ESTACION_LAT, ESTACION_LON],
            tooltip="Estación hidrométrica Guardia",
            popup=popup,
            icon=folium.Icon(color=marker_color, icon="tint", prefix="fa"),
        ).add_to(map_obj)

    extent_layer = subbasin_layer or basin_layer
    if extent_layer is not None:
        try:
            map_obj.fit_bounds(
                extent_layer.get_bounds(),
                padding=(18, 18),
                max_zoom=9 if compact else 10,
            )
        except Exception:
            pass

    if not compact:
        folium.LayerControl(collapsed=True, position="topright").add_to(map_obj)
    return map_obj, raster_added, raster_status


def _read_icon_raster(url: str, basin_geojson_text: str) -> dict:
    response = requests.get(
        url,
        timeout=(12, 90),
        headers={"User-Agent": "SAT-Guardia-academic-platform/1.0"},
    )
    response.raise_for_status()
    with MemoryFile(response.content) as memory_file:
        with memory_file.open() as source:
            if source.crs is None:
                raise ValueError("El GeoTIFF no declara un sistema de coordenadas.")
            basin_geojson = json.loads(basin_geojson_text)
            source_geometries = _geojson_geometries(basin_geojson)
            if (
                source.crs.is_geographic
                and source.bounds.left >= 0
                and source.bounds.right > 180
            ):
                source_geometries = [
                    _shift_geometry_to_360(geometry)
                    for geometry in source_geometries
                ]
            geometries = [
                transform_geom("EPSG:4326", source.crs, geometry, precision=6)
                for geometry in source_geometries
            ]
            clipped, clipped_transform = raster_mask(
                source,
                geometries,
                crop=True,
                filled=False,
                indexes=1,
            )
            array = np.ma.asarray(clipped, dtype=float)
            scale = float(source.scales[0]) if source.scales else 1.0
            offset = float(source.offsets[0]) if source.offsets else 0.0
            array = array * scale + offset
            values = np.ma.filled(array, np.nan)
            values[~np.isfinite(values)] = np.nan
            values[values < 0] = np.nan
            west, south, east, north = array_bounds(
                values.shape[0],
                values.shape[1],
                clipped_transform,
            )
            west, south, east, north = transform_bounds(
                source.crs,
                "EPSG:4326",
                west,
                south,
                east,
                north,
                densify_pts=21,
            )
            if west > 180:
                west -= 360
                east -= 360
            return {
                "cumulative_array": values,
                "bounds": [[south, west], [north, east]],
            }


@st.cache_data(ttl=90_000, show_spinner=False)
def load_icon_forecast(
    basin_geojson_text: str,
    forecast_cache_day: str,
) -> tuple[list[dict], list[str]]:
    """Descarga ICON una vez por día y obtiene incrementos diarios recortados."""
    # forecast_cache_day forma parte de la llave de caché y fuerza la
    # actualización al cambiar el día local, aunque no se use en el cálculo.
    _ = forecast_cache_day
    records: list[dict] = []
    errors: list[str] = []
    previous = None
    previous_day = 0
    for day, url in ICON_FORECAST_URLS.items():
        try:
            raster = _read_icon_raster(url, basin_geojson_text)
            cumulative = raster["cumulative_array"]
            if day == 1:
                daily = cumulative.copy()
            elif (
                previous is not None
                and previous_day == day - 1
                and previous.shape == cumulative.shape
                and np.allclose(
                    np.asarray(records[-1]["bounds"], dtype=float),
                    np.asarray(raster["bounds"], dtype=float),
                    atol=1e-5,
                )
            ):
                daily = cumulative - previous
            else:
                raise ValueError(
                    "no se pudo diferenciar el acumulado porque falta el horizonte anterior"
                )
            daily = np.where(np.isfinite(daily), np.maximum(daily, 0.0), np.nan)
            records.append(
                {
                    "day": day,
                    "url": url,
                    "daily_array": daily,
                    "mean_mm": float(np.nanmean(daily)),
                    "bounds": raster["bounds"],
                    "available": True,
                }
            )
            previous = cumulative
            previous_day = day
        except Exception as exc:
            errors.append(f"Día {day}: {exc}")
            records.append(
                {
                    "day": day,
                    "url": url,
                    "daily_array": None,
                    "mean_mm": np.nan,
                    "bounds": None,
                    "available": False,
                }
            )
            previous = None
            previous_day = day
    return records, errors


def precipitation_rgba(values: np.ndarray) -> np.ndarray:
    """Aplica una paleta de precipitación y transparencia fuera de la cuenca."""
    stops = np.array([0, 1, 5, 10, 20, 50], dtype=float)
    colors = np.array(
        [
            [222, 235, 247],
            [158, 202, 225],
            [107, 174, 214],
            [49, 130, 189],
            [253, 174, 107],
            [127, 0, 0],
        ],
        dtype=float,
    )
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    valid = np.isfinite(values)
    clipped = np.clip(np.where(valid, values, 0.0), stops[0], stops[-1])
    for channel in range(3):
        rgba[..., channel] = np.interp(clipped, stops, colors[:, channel]).astype(np.uint8)
    rgba[..., 3] = np.where(valid & (values > 0), 215, 0).astype(np.uint8)
    return rgba


def create_forecast_map(forecast_record: dict) -> folium.Map:
    """Construye ICON recortado al área aportante aguas arriba de Guardia."""
    map_obj = folium.Map(
        location=[ESTACION_LAT, ESTACION_LON],
        zoom_start=8,
        tiles="CartoDB positron",
        control_scale=True,
    )
    Fullscreen(position="topright").add_to(map_obj)
    basin_path = _first_existing(BASIN_FILES)
    subbasin_path = _first_existing(SUBBASIN_FILES)
    river_path = _first_existing(RIVER_FILES)
    basin_layer = None
    subbasin_layer = None
    if forecast_record.get("available") and forecast_record.get("daily_array") is not None:
        folium.raster_layers.ImageOverlay(
            image=precipitation_rgba(forecast_record["daily_array"]),
            bounds=forecast_record["bounds"],
            name=f"ICON · día {forecast_record['day']}",
            opacity=.82,
            interactive=True,
            cross_origin=False,
            zindex=2,
        ).add_to(map_obj)
        _add_map_legend(
            map_obj,
            f"Precipitación ICON · día {forecast_record['day']}",
            {
                "min": "0 mm/día",
                "max": "≥50 mm/día",
                "ticks": ["0", "1", "5", "10", "20", "≥50"],
                "palette": ["DEEBF7", "9ECAE1", "6BAED6", "3182BD", "FDAE6B", "7F0000"],
            },
        )
    if basin_path:
        basin_layer = folium.GeoJson(
            json.loads(basin_path.read_text(encoding="utf-8")),
            name="Cuenca aportante",
            style_function=lambda _: {
                "color": NAVY,
                "weight": 2.3,
                "fillOpacity": 0,
            },
        ).add_to(map_obj)
    if subbasin_path:
        subbasin_layer = folium.GeoJson(
            json.loads(subbasin_path.read_text(encoding="utf-8")),
            name="Subcuencas aportantes a Guardia",
            style_function=lambda _: {
                "color": TEAL,
                "weight": 1.45,
                "fillColor": "#B9D9D4",
                "fillOpacity": .08,
            },
            tooltip="Subcuencas aportantes aguas arriba de Guardia",
        )
        subbasin_layer.add_to(map_obj)
    if river_path:
        folium.GeoJson(
            json.loads(river_path.read_text(encoding="utf-8")),
            name="Cauce principal del río Tempisque",
            style_function=lambda _: {
                "color": "#1565C0",
                "weight": 4.0,
                "opacity": .95,
            },
        ).add_to(map_obj)
    folium.Marker(
        [ESTACION_LAT, ESTACION_LON],
        tooltip="Estación Guardia",
        icon=folium.Icon(color="blue", icon="tint", prefix="fa"),
    ).add_to(map_obj)
    extent_layer = subbasin_layer or basin_layer
    if extent_layer is not None:
        try:
            map_obj.fit_bounds(
                extent_layer.get_bounds(),
                padding=(18, 18),
                max_zoom=10,
            )
        except Exception:
            pass
    folium.LayerControl(collapsed=True).add_to(map_obj)
    return map_obj

# =============================================================================
# <<< SAT_SECTION: 05_componente_geoespacial

# >>> SAT_SECTION: 06_filtros_globales
# 6. BARRA LATERAL Y FILTROS GLOBALES
# =============================================================================
with st.sidebar:
    st.markdown("## SAT Guardia")
    st.caption("Plataforma de monitoreo y alerta por estiaje hidrométrico.")
    st.markdown("---")

    st.markdown("### Filtros del análisis")
    min_date = level["fecha"].min().date()
    max_date = level["fecha"].max().date()
    default_date = min(pd.Timestamp("2020-05-08").date(), max_date)
    selected_date = pd.Timestamp(
        st.date_input(
            "Fecha evaluada",
            value=default_date,
            min_value=min_date,
            max_value=max_date,
            format="DD/MM/YYYY",
        )
    )

    period_label = st.selectbox(
        "Período de visualización",
        ["7 días", "15 días", "30 días", "90 días"],
        index=2,
    )
    period_days = {"7 días": 7, "15 días": 15, "30 días": 30, "90 días": 90}[period_label]
    window = st.select_slider("Ventana climática", options=[7, 30, 90], value=30, format_func=lambda x: f"{x} días")
    spi_scale = st.radio("Escala del SPI", [1, 3, 6], index=1, horizontal=True)
    show_imputed = st.toggle("Resaltar datos imputados", value=True)
    show_thresholds = st.toggle("Mostrar P20, P10 y P05", value=True)

    st.markdown("---")
    st.markdown("### Cobertura")
    st.caption(f"**Nivel:** {level['fecha'].min():%d/%m/%Y}–{level['fecha'].max():%d/%m/%Y}")
    st.caption(f"**Clima:** {climate['fecha'].min():%d/%m/%Y}–{climate['fecha'].max():%d/%m/%Y}")
    st.caption(f"**SPI:** {spi['fecha'].min():%m/%Y}–{spi['fecha'].max():%m/%Y}")
    st.caption("**Actualización climática:** automática desde GEE")
    st.markdown("---")
    st.info("Modo histórico · plataforma académica", icon="🎓")

row = get_row_for_date(selected_date)
alert_name, severity_name, alert_reason = get_alert_state(row)
alert_color, alert_label = ALERT_STYLE[alert_name]

chart_start = max(level["fecha"].min(), selected_date - pd.Timedelta(days=period_days - 1))
chart_end = min(selected_date, level["fecha"].max())

climate_row = climate.loc[climate["fecha"].le(selected_date)].iloc[-1]
spi_month = selected_date.to_period("M").start_time
spi_candidates = spi.loc[spi["fecha"].le(spi_month)]
spi_row = spi_candidates.iloc[-1] if not spi_candidates.empty else pd.Series({"spi_1": np.nan, "spi_3": np.nan, "spi_6": np.nan})

# =============================================================================
# <<< SAT_SECTION: 06_filtros_globales

# >>> SAT_SECTION: 07_encabezado
# 7. ENCABEZADO
# =============================================================================
st.markdown('<div class="eyebrow">Sistema de alerta temprana · plataforma académica</div>', unsafe_allow_html=True)
st.markdown("# SAT de Estiaje Hidrométrico")
st.markdown('<div class="project-subtitle">Estación Guardia · Cuenca media del río Tempisque</div>', unsafe_allow_html=True)

st.markdown(
    f"""
    <div class="alert-banner" style="border-left: 7px solid {alert_color};">
      <div>
        <div class="alert-title" style="color:{alert_color};">ALERTA OPERATIVA: {alert_name.upper()}</div>
        <div class="alert-explanation"><b>{alert_label}.</b> {alert_reason}</div>
      </div>
      <div class="alert-date">Fecha evaluada<br><b style="color:#17324D; font-size:.92rem">{fmt_date(selected_date)}</b></div>
    </div>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# <<< SAT_SECTION: 07_encabezado

# >>> SAT_SECTION: 08_navegacion_principal
# 8. NAVEGACIÓN PRINCIPAL
# =============================================================================
tab_summary, tab_level, tab_climate, tab_forecast, tab_geo, tab_method = st.tabs(
    [
        "Resumen del SAT",
        "Nivel y alertas",
        "Contexto climático",
        "Pronóstico",
        "Geoportal",
        "Metodología paso a paso",
    ]
)

with tab_summary:
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        kpi_card("Nivel diario", f"{row['nivel_diario_m']:.3f} m", str(row["categoria_nivel"]))
    with k2:
        kpi_card("P20 mensual", f"{row['nivel_p20_m']:.3f} m", f"Umbral de entrada · {MESES[int(row['mes'])-1]}")
    with k3:
        kpi_card("Persistencia", f"{int(row['dias_consecutivos'])} días", "Evento confirmado a partir del día 7")
    with k4:
        kpi_card("Déficit acumulado", f"{row['deficit_acumulado_evento']:.3f} m·día", f"P50={P50_SEVERIDAD:.4f} · P75={P75_SEVERIDAD:.4f}")
    with k5:
        kpi_card(f"SPI-{spi_scale}", f"{spi_row[f'spi_{spi_scale}']:.2f}", "Contexto de sequía meteorológica")

    st.write("")
    left, right = st.columns([1.65, 1], gap="large")
    with left:
        st.plotly_chart(
            hydrometric_chart(
                chart_start,
                chart_end,
                show_imputed,
                show_thresholds,
                focus_date=selected_date,
            ),
            width="stretch",
            theme=None,
            config={"displaylogo": False},
            key="summary_hydrometric_chart",
        )
    with right:
        st.markdown("### Localización y estado de la estación")
        map_obj, _, _ = create_map(alert_name, row, compact=True)
        st_folium(map_obj, height=455, use_container_width=True, key="summary_map")
        if not (
            _first_existing(SUBBASIN_FILES)
            or _first_existing(BASIN_FILES)
        ):
            st.caption(
                "Falta data/subcuencas_guardia.geojson para mostrar "
                "el área aportante."
            )

    st.markdown("### Contexto hidroclimático antecedente")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card(f"Precipitación · {window} d", f"{climate_row[f'lluvia_acum_{window}d']:.1f} mm", "Acumulado antecedente en el área aportante")
    with c2:
        kpi_card(f"ETo equivalente · {window} d", f"{climate_row[f'eto_acum_{window}d']:.1f} mm", "Demanda evaporativa acumulada")
    with c3:
        balance_value = climate_row[f"balance_{window}d"]
        kpi_card(f"Balance P−ETo · {window} d", f"{balance_value:.1f} mm", "Déficit" if balance_value < 0 else "Superávit")
    with c4:
        kpi_card("Estado hidrométrico", str(row["categoria_nivel"]), f"Comparación con P20, P10 y P05 de {MESES[int(row['mes'])-1]}")

    st.markdown(
        '<div class="section-note">Las variables climáticas proporcionan contexto hidroclimático antecedente. La alerta se determina a partir del nivel, los umbrales mensuales, la persistencia y el déficit acumulado.</div>',
        unsafe_allow_html=True,
    )

with tab_level:
    st.markdown("## Monitoreo hidrométrico y motor de alertas")
    st.caption("La lectura diaria, la estacionalidad y la persistencia se presentan como resultados complementarios.")
    st.download_button(
        "Descargar serie hidrométrica completa",
        data=csv_bytes(level),
        file_name="nivel_guardia_procesado.csv",
        mime="text/csv",
        key="download_level_series",
    )

    sub1, sub2, sub3 = st.tabs(["Serie y umbrales", "Eventos persistentes", "Estacionalidad"])
    with sub1:
        st.plotly_chart(
            hydrometric_chart(
                chart_start,
                chart_end,
                show_imputed,
                show_thresholds,
                focus_date=selected_date,
            ),
            width="stretch",
            theme=None,
            config={"displaylogo": False},
            key="level_hydrometric_chart",
        )
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            kpi_card("Estado diario", str(row["categoria_nivel"]), "Clasificación frente a los umbrales mensuales")
        with m2:
            kpi_card("Persistencia", f"{int(row['dias_consecutivos'])} días", "Días consecutivos bajo el P20")
        with m3:
            kpi_card("Déficit diario", f"{row['deficit_nivel_m']:.3f} m", "Diferencia entre P20 y nivel observado")
        with m4:
            kpi_card("Severidad acumulada", severity_name, f"{row['deficit_acumulado_evento']:.3f} m·día")

    with sub2:
        if not events.empty:
            event_options = events.sort_values("fecha_inicio").reset_index(drop=True)
            option_ids = event_options["id_evento"].tolist()
            current_event_id = row.get("id_evento", np.nan)
            default_event_index = len(option_ids) - 1
            if pd.notna(current_event_id) and current_event_id in option_ids:
                default_event_index = option_ids.index(current_event_id)

            selected_event_id = st.selectbox(
                "Evento persistente analizado",
                options=option_ids,
                index=default_event_index,
                format_func=lambda event_id: (
                    lambda event_row: (
                        f"{event_row['fecha_inicio']:%d/%m/%Y}–"
                        f"{event_row['fecha_fin']:%d/%m/%Y} · "
                        f"{event_row['severidad_evento']}"
                    )
                )(
                    event_options.loc[
                        event_options["id_evento"].eq(event_id)
                    ].iloc[0]
                ),
            )
            selected_event = event_options.loc[
                event_options["id_evento"].eq(selected_event_id)
            ].iloc[0]

            left_ev, right_ev = st.columns([1.75, .85], gap="large")
            with left_ev:
                st.plotly_chart(
                    event_anatomy_chart(selected_event, focus_date=selected_date),
                    width="stretch",
                    theme=None,
                    config={"displaylogo": False},
                    key="event_anatomy_chart",
                )
            with right_ev:
                severity_color = {
                    "Moderado": YELLOW,
                    "Severo": ORANGE,
                    "Extremo": RED,
                }[selected_event["severidad_evento"]]
                st.markdown("### Ficha del evento")
                st.markdown(
                    f"""
                    <div class="panel">
                      <b>Periodo</b><br>
                      {selected_event['fecha_inicio']:%d/%m/%Y}–{selected_event['fecha_fin']:%d/%m/%Y}<br><br>
                      <b>Duración</b><br>
                      {int(selected_event['duracion_dias'])} días<br><br>
                      <b>Nivel mínimo</b><br>
                      {selected_event['nivel_minimo_m']:.3f} m<br><br>
                      <b>Déficit máximo</b><br>
                      {selected_event['deficit_maximo_m']:.3f} m<br><br>
                      <b>Déficit acumulado</b><br>
                      {selected_event['deficit_acumulado_m_dia']:.3f} m·día<br><br>
                      <b>Días bajo P10 / P05</b><br>
                      {int(selected_event['dias_bajo_p10'])} / {int(selected_event['dias_bajo_p05'])}<br><br>
                      <b>Severidad integral</b><br>
                      <span style="color:{severity_color};font-weight:800">
                        {selected_event['severidad_evento']}
                      </span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.caption(
                    "La confirmación ocurre al séptimo día. La severidad integra "
                    "magnitud y duración mediante el déficit acumulado."
                )

            st.markdown("### Inventario de eventos persistentes")
            event_table = events.copy().sort_values("fecha_inicio", ascending=False)
            event_table["fecha_inicio"] = event_table["fecha_inicio"].dt.strftime("%d/%m/%Y")
            event_table["fecha_fin"] = event_table["fecha_fin"].dt.strftime("%d/%m/%Y")
            event_table = event_table.rename(columns={
                "fecha_inicio": "Inicio",
                "fecha_fin": "Final",
                "duracion_dias": "Duración (días)",
                "nivel_minimo_m": "Nivel mínimo (m)",
                "deficit_maximo_m": "Déficit máximo (m)",
                "deficit_acumulado_m_dia": "Déficit acumulado (m·día)",
                "severidad_evento": "Severidad",
            })
            display_cols = ["Inicio", "Final", "Duración (días)", "Nivel mínimo (m)", "Déficit máximo (m)", "Déficit acumulado (m·día)", "Severidad"]
            st.dataframe(event_table[display_cols], width="stretch", hide_index=True)
            st.download_button(
                "Descargar inventario CSV",
                event_table[display_cols].to_csv(index=False).encode("utf-8-sig"),
                file_name="eventos_persistentes_guardia.csv",
                mime="text/csv",
            )
        else:
            st.info("No se detectaron eventos persistentes en el conjunto cargado.")

    with sub3:
        left_thr, right_thr = st.columns([.9, 1.65], gap="large")
        with left_thr:
            st.plotly_chart(
                threshold_chart(),
                width="stretch",
                theme=None,
                config={"displaylogo": False},
                key="monthly_threshold_chart",
            )
        with right_thr:
            st.plotly_chart(
                annual_hydrographs_chart(focus_year=selected_date.year),
                width="stretch",
                theme=None,
                config={"displaylogo": False},
                key="annual_hydrographs_chart",
            )
        st.markdown(
            '<div class="section-note">Los hidrogramas alineados permiten comparar '
            'la evolución intraanual entre años. Las líneas discontinuas identifican '
            'años con cobertura parcial; el año de la fecha evaluada se resalta.</div>',
            unsafe_allow_html=True,
        )

with tab_climate:
    st.markdown("## Contexto climático antecedente")
    st.caption(
        "Precipitación, ETo equivalente, balance climático e SPI se "
        "interpretan como contexto y no como predictores directos del nivel. "
        f"Última fecha común disponible: {CLIMATE_COMMON_END_DATE:%d/%m/%Y}."
    )
    download_climate, download_spi = st.columns(2)
    with download_climate:
        st.download_button(
            "Descargar clima diario desde GEE",
            data=csv_bytes(climate),
            file_name="clima_guardia_gee.csv",
            mime="text/csv",
            key="download_climate_series",
            use_container_width=True,
        )
    with download_spi:
        st.download_button(
            "Descargar SPI mensual derivado de CHIRPS",
            data=csv_bytes(spi),
            file_name="spi_guardia_gee.csv",
            mime="text/csv",
            key="download_spi_series",
            use_container_width=True,
        )

    ctrl1, ctrl2 = st.columns([1, 2.4])
    with ctrl1:
        climate_variable = st.selectbox(
            "Variable principal",
            ["Precipitación", "ETo equivalente", "Balance P−ETo"],
            index=2,
        )
    with ctrl2:
        full_climate_label = f"{climate['fecha'].min():%Y}–{climate['fecha'].max():%Y}"
        climate_period = st.selectbox(
            "Período climático mostrado",
            [full_climate_label, "Período del nivel"],
            index=0,
        )

    if climate_period == full_climate_label:
        climate_start, climate_end = climate["fecha"].min(), climate["fecha"].max()
    else:
        climate_start, climate_end = chart_start, chart_end

    left_cl, right_cl = st.columns([1.4, 1], gap="large")
    with left_cl:
        st.plotly_chart(
            climate_series_chart(
                climate_variable,
                window,
                climate_start,
                climate_end,
            ),
            width="stretch",
            theme=None,
            config={"displaylogo": False},
            key="climate_series_chart",
        )
    with right_cl:
        st.plotly_chart(
            climatology_chart(),
            width="stretch",
            theme=None,
            config={"displaylogo": False},
            key="monthly_climatology_chart",
        )
        st.caption(
            "El período 1991–2020 corresponde a la normal climatológica "
            "estándar más reciente de la Organización Meteorológica Mundial (OMM)."
        )

    st.plotly_chart(
        spi_chart(spi_scale, climate_start, climate_end),
        width="stretch",
        theme=None,
        config={"displaylogo": False},
        key="spi_time_series_chart",
    )

    st.markdown("### Lectura técnica de las variables")
    cards = st.columns(4)
    explanations = [
        ("Precipitación", "Describe el aporte atmosférico de agua. Los acumulados antecedentes permiten evaluar la humedad previa de la cuenca."),
        ("ETo equivalente", "Representa la evaporación potencial diaria de ERA5-Land y ayuda a interpretar la intensidad de la estación seca."),
        ("Balance P−ETo", "Resume de forma simplificada el superávit o déficit climático antecedente usando la ETo equivalente. No equivale al balance hídrico completo."),
        ("SPI", "Estandariza la precipitación en escalas de 1, 3 y 6 meses para contextualizar la sequía meteorológica."),
    ]
    for col, (title, text) in zip(cards, explanations):
        with col:
            st.markdown(f'<div class="method-step"><div class="method-title">{title}</div><div class="method-text">{text}</div></div>', unsafe_allow_html=True)


with tab_forecast:
    st.markdown("## Pronóstico de intensificación del estiaje")
    basin_path = _first_existing(SUBBASIN_FILES) or _first_existing(BASIN_FILES)
    if not basin_path:
        st.error(
            "Falta el área aportante aguas arriba de Guardia. "
            "Verifique data/subcuencas_guardia.geojson en GitHub."
        )
    else:
        basin_text = json.dumps(
            json.loads(basin_path.read_text(encoding="utf-8")),
            ensure_ascii=False,
            sort_keys=True,
        )
        forecast_cache_day = pd.Timestamp.now(
            tz="America/Costa_Rica"
        ).strftime("%Y-%m-%d")
        with st.spinner("Actualizando automáticamente el pronóstico ICON del día…"):
            icon_records, _icon_errors = load_icon_forecast(
                basin_text,
                forecast_cache_day,
            )
        if icon_records:
            scenario = None
            consecutive_rain = []
            for record in icon_records:
                expected_day = len(consecutive_rain) + 1
                if record["available"] and record["day"] == expected_day:
                    consecutive_rain.append(record["mean_mm"])
                else:
                    break
            if consecutive_rain:
                try:
                    scenario = build_level_forecast_scenario(consecutive_rain)
                except Exception as exc:
                    st.error(f"No fue posible construir el escenario de nivel: {exc}")

            available_records = icon_records[:len(consecutive_rain)]
            alert_colors = {
                "Verde": GREEN,
                "Vigilancia": WATCH,
                "Amarilla": YELLOW,
                "Naranja": ORANGE,
                "Roja": RED,
            }
            if available_records:
                horizon_days = len(available_records)
                st.markdown(
                    (
                        '<div class="forecast-heading">'
                        '<div class="forecast-heading-title">'
                        "Estado esperado por día de pronóstico"
                        "</div>"
                        '<div class="forecast-horizon">'
                        f"Horizonte disponible: {horizon_days} días · "
                        f"24 h a {horizon_days * 24} h"
                        "</div></div>"
                    ),
                    unsafe_allow_html=True,
                )
                forecast_cards = []
                for record in available_records:
                    scenario_match = (
                        scenario.loc[
                            scenario["horizonte_dia"].eq(record["day"])
                        ]
                        if scenario is not None
                        else pd.DataFrame()
                    )
                    scenario_row = (
                        scenario_match.iloc[0]
                        if not scenario_match.empty
                        else None
                    )
                    alert_state = (
                        str(scenario_row["alerta_esperada"])
                        if scenario_row is not None
                        else "Sin escenario"
                    )
                    projected_level = (
                        f"{scenario_row['nivel_proyectado_m']:.3f} m"
                        if scenario_row is not None
                        else "—"
                    )
                    card_color = (
                        alert_colors.get(alert_state, SLATE)
                        if scenario_row is not None
                        else SLATE
                    )
                    forecast_cards.append(
                        (
                            '<article class="forecast-card" '
                            f'style="--forecast-color:{card_color};">'
                            '<div class="forecast-day">'
                            f"<span>Día {record['day']}</span>"
                            '<span class="forecast-hour">'
                            f"{record['day'] * 24} h</span></div>"
                            f'<div class="forecast-status">{alert_state}</div>'
                            '<div class="forecast-rain">'
                            f"{record['mean_mm']:.1f} mm</div>"
                            '<div class="forecast-detail">'
                            "Lluvia media del área aportante</div>"
                            '<div class="forecast-detail">'
                            f"Nivel proyectado: <b>{projected_level}</b>"
                            "</div></article>"
                        )
                    )
                forecast_grid_html = (
                    '<div class="forecast-grid" '
                    f'style="--forecast-columns:{horizon_days};">'
                    + "".join(forecast_cards)
                    + "</div>"
                )
                st.markdown(
                    forecast_grid_html,
                    unsafe_allow_html=True,
                )

            if scenario is not None:
                st.plotly_chart(
                    forecast_scenario_chart(scenario),
                    width="stretch",
                    theme=None,
                    config={"displaylogo": False},
                    key="forecast_scenario_chart",
                )
                st.download_button(
                    "Descargar escenario de pronóstico",
                    data=csv_bytes(scenario),
                    file_name=f"pronostico_estiaje_icon_{len(scenario)}_dias.csv",
                    mime="text/csv",
                    key="download_forecast_scenario",
                )
            else:
                st.warning(
                    "No fue posible iniciar la trayectoria porque falta el primer "
                    "acumulado ICON; los horizontes ausentes no se sustituyen por cero."
                )

            available_days = [
                record["day"] for record in available_records
            ]
            if available_days:
                map_day = st.select_slider(
                    "Día mostrado en el mapa",
                    options=available_days,
                    value=available_days[0],
                    format_func=lambda value: f"Día {value}",
                )
                map_record = next(
                    record for record in icon_records if record["day"] == map_day
                )
                st.markdown(
                    "### Pronóstico de precipitación en el área aportante"
                )
                st_folium(
                    create_forecast_map(map_record),
                    height=570,
                    use_container_width=True,
                    key=f"icon_forecast_map_{map_day}",
                )

            st.info(
                f"Nota metodológica: el último nivel disponible corresponde al "
                f"{level['fecha'].max():%d/%m/%Y}. La lluvia ICON es actual, pero la "
                "trayectoria se ancla metodológicamente al último estado hidrométrico; "
                "no debe interpretarse como un pronóstico operativo hasta disponer de nivel actualizado."
            )


with tab_geo:
    st.markdown("## Geoportal de la cuenca y estación Guardia")
    control_1, control_2, control_3 = st.columns([1.5, 1, 1])
    with control_1:
        geo_variable = st.selectbox(
            "Variable espacial",
            [
                "DEM",
                "Precipitación media mensual histórica",
                "ETo equivalente media mensual histórica",
                "SPI-1 raster",
                "SPI-3 raster",
                "SPI-6 raster",
            ],
            index=0,
        )
    with control_2:
        geo_period_options = list(
            pd.period_range(
                f"{SPI_BASE_START}-01",
                CLIMATE_LAST_COMPLETE_PERIOD,
                freq="M",
            )
        )
        default_geo_period = selected_date.to_period("M")
        default_geo_index = (
            geo_period_options.index(default_geo_period)
            if default_geo_period in geo_period_options
            else len(geo_period_options) - 1
        )
        geo_period = st.selectbox(
            "Mes/año del raster",
            options=geo_period_options,
            index=default_geo_index,
            format_func=lambda value: value.strftime("%m/%Y"),
            key="geoportal_month_year",
        )
    with control_3:
        geo_opacity = st.slider(
            "Opacidad de la capa",
            min_value=0.15,
            max_value=1.0,
            value=0.72,
            step=0.05,
        )
    toggle_1, toggle_2 = st.columns(2)
    with toggle_1:
        geo_show_subbasins = st.toggle(
            "Mostrar subcuencas aportantes",
            value=True,
            key="geo_show_subbasins",
        )
    with toggle_2:
        geo_show_station = st.toggle(
            "Mostrar estación Guardia",
            value=True,
            key="geo_show_station",
        )

    map_obj, raster_added, raster_status = create_map(
        alert_name,
        row,
        compact=False,
        layer_variable=geo_variable,
        layer_date=geo_period.start_time,
        opacity=geo_opacity,
        show_subbasins=geo_show_subbasins,
        show_station=geo_show_station,
    )
    st_folium(
        map_obj,
        height=720,
        use_container_width=True,
        returned_objects=[],
        key="geo_map",
    )
    if raster_added:
        st.caption(
            f"{raster_status} · mes/año seleccionado: "
            f"{geo_period.strftime('%m/%Y')} · capa recortada al área aportante."
        )
    else:
        st.warning(raster_status)

    analysis_path = (
        _first_existing(SUBBASIN_FILES)
        or _first_existing(BASIN_FILES)
    )
    if analysis_path:
        analysis_text = json.dumps(
            json.loads(analysis_path.read_text(encoding="utf-8")),
            ensure_ascii=False,
            sort_keys=True,
        )
        dem_stats, dem_status = get_dem_physiographic_stats(analysis_text)
        st.markdown("### Indicadores fisiográficos del área aportante")
        if dem_stats:
            indicator_columns = st.columns(4)
            indicator_values = [
                (
                    "Área aportante",
                    f"{dem_stats['area_km2']:,.1f} km²",
                    "Subcuencas aguas arriba",
                ),
                (
                    "Elevación mínima",
                    f"{dem_stats['elevation_min_m']:,.0f} m",
                    "SRTM",
                ),
                (
                    "Elevación media",
                    f"{dem_stats['elevation_mean_m']:,.0f} m",
                    "SRTM",
                ),
                (
                    "Elevación máxima",
                    f"{dem_stats['elevation_max_m']:,.0f} m",
                    "SRTM",
                ),
            ]
            for column, (label, value, note) in zip(
                indicator_columns,
                indicator_values,
            ):
                with column:
                    kpi_card(label, value, note)
            st.caption(
                f"{dem_status}. Los valores describen la geometría utilizada "
                "para los análisis climáticos y el pronóstico."
            )
        else:
            st.warning(dem_status)

    if not analysis_path:
        st.warning(
            "Falta el área aportante. Por seguridad cartográfica, "
            "ningún raster se muestra sin una geometría válida para recortarlo."
        )

    with st.expander(
        "Información de la estación, fuentes y capa mostrada",
        expanded=False,
    ):
        station_info, source_info = st.columns(2, gap="large")
        with station_info:
            st.markdown(
                f"""
                <div class="panel">
                  <b>Estación:</b> Guardia (código 190302)<br><br>
                  <b>Coordenadas:</b> {ESTACION_LAT:.4f}, {ESTACION_LON:.4f}<br><br>
                  <b>Variable principal:</b> nivel medio diario<br><br>
                  <b>Fecha hidrométrica evaluada:</b> {selected_date:%d/%m/%Y}<br><br>
                  <b>Alerta:</b>
                  <span style="color:{alert_color}; font-weight:800">{alert_name}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with source_info:
            st.markdown(
                f"""
                <div class="panel">
                  <b>Capa mostrada:</b> {geo_variable}<br><br>
                  <b>Mes/año:</b> {geo_period.strftime('%m/%Y')}<br><br>
                  <b>Precipitación:</b> CHIRPS diario mediante GEE<br><br>
                  <b>ETo equivalente:</b> evaporación potencial diaria ERA5-Land mediante GEE<br><br>
                  <b>SPI:</b> ajuste gamma sobre CHIRPS<br><br>
                  <b>Cuencas:</b> HydroBASINS nivel 7 mediante GEE<br><br>
                  <b>Cauce principal:</b> Geojson desde GitHub
                </div>
                """,
                unsafe_allow_html=True,
            )

with tab_method:
    st.markdown("## Construcción del SAT paso a paso")
    st.caption(
        "Esta sección documenta qué hace la plataforma desde la carga de datos "
        "hasta la asignación de la alerta."
    )

    methodology_steps = [
        (
            "1",
            "Cargar los insumos",
            "El CSV de nivel y el GeoJSON del cauce principal del río Tempisque se cargan desde el repositorio en GitHub.",
        ),
        (
            "2",
            "Definir el área aportante",
            "Las subcuencas HydroBASINS nivel 7, previamente delimitadas con NEXT_DOWN, se cargan desde GitHub; su unión define el área que descarga hacia la estación Guardia.",
        ),
        (
            "3",
            "Obtener clima desde GEE",
            "Una tarea diaria de GitHub Actions consulta en GEE las fechas faltantes de CHIRPS y ERA5-Land, las recorta al último día común y actualiza los acumulados y el balance P−ETo.",
        ),
        (
            "4",
            "Calcular el SPI",
            "La precipitación CHIRPS se acumula en escalas de 1, 3 y 6 meses completos; posteriormente se ajusta por mes a una distribución gamma y se transforma a la normal estándar usando años calendario completos.",
        ),
        (
            "5",
            "Asignar umbrales mensuales",
            "Cada nivel diario se compara con P20, P10 y P05 del mes correspondiente para respetar la estacionalidad.",
        ),
        (
            "6",
            "Detectar persistencia",
            "Se cuentan los días consecutivos bajo P20. Los primeros seis días se mantienen en vigilancia.",
        ),
        (
            "7",
            "Confirmar el evento",
            "Al séptimo día consecutivo bajo P20 se confirma un evento persistente de nivel bajo.",
        ),
        (
            "8",
            "Calcular severidad",
            "Se integra el déficit diario P20−nivel para obtener el déficit acumulado en m·día.",
        ),
        (
            "9",
            "Asignar la alerta",
            "La persistencia, la categoría del nivel y la severidad acumulada determinan el estado verde, vigilancia, amarillo, naranja o rojo.",
        ),
        (
            "10",
            "Contextualizar con clima",
            "Precipitación, ETo equivalente, balance climático y SPI ayudan a interpretar el evento, pero no sustituyen la señal hidrométrica.",
        ),
        (
            "11",
            "Construir el geoportal",
            "El DEM SRTM y los rasters de precipitación, ETo equivalente y SPI se consultan en GEE y se recortan al área aportante; se combinan con las subcuencas, la estación Guardia y el cauce principal.",
        ),
        (
            "12",
            "Proyectar el horizonte disponible",
            "La lluvia ICON disponible se promedia sobre el área aportante y se incorpora a un modelo estadístico de regresión regularizada entrenado con el nivel actual, su tendencia, la lluvia antecedente, el balance P−ETo, el SPI-1 y la estacionalidad. El nivel se proyecta día a día y se evalúa con los umbrales, la persistencia y la severidad del SAT.",
        ),
    ]

    for start in range(0, len(methodology_steps), 2):
        columns = st.columns(2, gap="large")
        for column, (number, title, text) in zip(
            columns,
            methodology_steps[start:start + 2],
        ):
            with column:
                st.markdown(
                    f'<div class="method-step">'
                    f'<div class="method-number">{number}</div>'
                    f'<div class="method-title">{title}</div>'
                    f'<div class="method-text">{text}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    st.markdown("### Flujo del motor de decisión")
    step_cols = st.columns(6)
    steps = [
        ("1", "Actualizar y validar", "Fechas, duplicados, vacíos y trazabilidad."),
        ("2", "Comparar umbrales", "Nivel frente a P20, P10 y P05 del mes."),
        ("3", "Evaluar persistencia", "Días consecutivos bajo el P20 mensual."),
        ("4", "Confirmar evento", "Evento persistente al alcanzar siete días."),
        ("5", "Acumular déficit", "Diferencia P20−nivel integrada en m·día."),
        ("6", "Asignar alerta", "Verde, vigilancia, amarilla, naranja o roja."),
    ]
    for col, (number, title, text) in zip(step_cols, steps):
        with col:
            st.markdown(
                f'<div class="method-step"><div class="method-number">{number}</div><div class="method-title">{title}</div><div class="method-text">{text}</div></div>',
                unsafe_allow_html=True,
            )

    with st.expander("Criterios técnicos y limitaciones del sistema"):
        st.markdown(
            f"""
            - **Estado diario:** normal, bajo, muy bajo o extremadamente bajo según P20, P10 y P05 mensuales.
            - **Persistencia:** vigilancia durante los primeros seis días bajo P20 y confirmación al séptimo día.
            - **Severidad:** moderada hasta {P50_SEVERIDAD:.4f} m·día; severa entre {P50_SEVERIDAD:.4f} y {P75_SEVERIDAD:.4f} m·día; extrema por encima de {P75_SEVERIDAD:.4f} m·día.
            - **Contexto climático:** precipitación, ETo equivalente, balance P−ETo y SPI no definen por sí solos la alerta.
            - **Fuentes GEE:** CHIRPS diario, ERA5-Land diario, SRTM 30 m e HydroBASINS nivel 7.
            - **Período climático común:** CHIRPS y ERA5-Land se recortan automáticamente a la menor de sus últimas fechas disponibles; el visor usa solo los años calendario completos de ese mismo período.
            - **ETo equivalente:** se obtiene como `max(−potential_evaporation_sum × 1000, 0)` en mm/día. Es evaporación potencial de ERA5-Land y no una ETo FAO-56 calculada con datos de estación.
            - **Pronóstico:** ICON aporta la lluvia; el nivel es un escenario estadístico preliminar anclado al último registro disponible, no una predicción operativa.
            - **Alcance:** los umbrales y el modelo ridge requieren una fase posterior de validación, actualización de nivel e incorporación de incertidumbre.
            """
        )
# <<< SAT_SECTION: 08_navegacion_principal

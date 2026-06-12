from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

SOURCE_DIR = Path(__file__).parent / "source"

# Schweizer Zahlenformat: Dezimalpunkt + Apostroph als Tausendertrennzeichen.
pio.templates[pio.templates.default].layout.separators = ".'"


@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lastgang (Viertelstundenwerte) auf Tagesbasis aggregieren und PV-Tageswerte laden."""
    df = pd.read_csv(SOURCE_DIR / "lastgang-2025.csv", sep=";", decimal=".")
    df["timeFrom"] = pd.to_datetime(df["timeFrom"], format="%d.%m.%Y %H:%M")

    # Tagessummen: kW × 0.25 h pro Viertelstunden-Intervall = kWh
    daily = (
        df.groupby(df["timeFrom"].dt.date)[["Bezug-Wirkenergie", "Ruecklieferung-Wirkenergie"]]
        .sum()
        .reset_index()
    )
    daily.columns = ["Datum", "Bezug_kWh", "Ruecklieferung_kWh"]
    daily["Bezug_kWh"] = daily["Bezug_kWh"] * 0.25
    daily["Ruecklieferung_kWh"] = daily["Ruecklieferung_kWh"] * 0.25
    daily["Datum"] = pd.to_datetime(daily["Datum"])

    pv = pd.read_csv(SOURCE_DIR / "pv_01012025-31122025.csv")
    pv["Datum"] = pd.to_datetime(pv["Date and time [dd.MM.yyyy]"], format="%d.%m.%Y")

    return daily, pv


def plot_daily(daily: pd.DataFrame, pv: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily["Datum"], y=daily["Bezug_kWh"].round(2),
        mode="lines+markers", name="Bezug", line=dict(color="steelblue"),
    ))
    fig.add_trace(go.Scatter(
        x=daily["Datum"], y=daily["Ruecklieferung_kWh"].round(2),
        mode="lines+markers", name="Ruecklieferung", line=dict(color="orange"),
    ))
    fig.add_trace(go.Scatter(
        x=pv["Datum"], y=pv["Total system [kWh]"].round(2),
        mode="lines+markers", name="PV Produktion", line=dict(color="green"),
    ))
    fig.update_layout(
        title="Lastgang 2025 - Tageswerte",
        xaxis_title="Datum",
        yaxis_title="Energie [kWh/Tag]",
        hovermode="x unified",
    )
    return fig


st.set_page_config(page_title="PV Eigenverbrauch 2025", layout="wide")
st.title("PV Eigenverbrauch 2025")

daily, pv = load_data()

# Kennzahlen 2025
sum_feed_in = round(daily["Ruecklieferung_kWh"].sum(), 1)
sum_consumption_from_grid = round(daily["Bezug_kWh"].sum(), 1)
pv_production = round(pv["Total system [kWh]"].sum(), 1)
self_consumption = pv_production - sum_feed_in

col1, col2, col3, col4 = st.columns(4)
col1.metric("PV Produktion", f"{pv_production:,.0f} kWh".replace(",", "'"))
col2.metric("Netzbezug", f"{sum_consumption_from_grid:,.0f} kWh".replace(",", "'"))
col3.metric("Einspeisung", f"{sum_feed_in:,.0f} kWh".replace(",", "'"))
col4.metric("Eigenverbrauch", f"{self_consumption / pv_production * 100:.1f} %")

st.subheader("Lastgang 2025 - Tageswerte")
st.plotly_chart(plot_daily(daily, pv), use_container_width=True)

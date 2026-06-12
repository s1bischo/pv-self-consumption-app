import io
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

SOURCE_DIR = Path(__file__).parent / "source"
LAST_PATH = SOURCE_DIR / "lastgang-2025.csv"
PV_PATH = SOURCE_DIR / "pv_01012025-31122025.csv"

# Schweizer Zahlenformat: Dezimalpunkt + Apostroph als Tausendertrennzeichen.
pio.templates[pio.templates.default].layout.separators = ".'"


def _read_text(src) -> str:
    """Roh-Text aus Pfad oder hochgeladenem File-Objekt lesen.

    Probiert mehrere Kodierungen, weil der Original-Export je nach Quelle
    UTF-8 (mit BOM) oder Windows-1252/Latin-1 (Umlaute) sein kann.
    """
    if hasattr(src, "getvalue"):       # st.file_uploader -> UploadedFile
        data = src.getvalue()
    elif hasattr(src, "read"):
        data = src.read()
    else:
        data = Path(src).read_bytes()
    if isinstance(data, str):
        return data
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _canon(col: str) -> str:
    """Spaltenname vereinheitlichen: Einheit [..] weg, Umlaut, Mehrfach-Spaces, lower."""
    col = re.sub(r"\[.*?\]", "", col)                 # Einheit '[kW]' entfernen
    col = col.replace("ü", "ue").replace("Ü", "Ue")
    return re.sub(r"\s+", " ", col).strip().lower()


# Kanonische Zielspalten je normalisiertem Quellnamen / Schlüsselwort.
_LASTGANG_HEADER_KEYS = ("zeitraum von", "timefrom")


def _normalize_lastgang(df: pd.DataFrame) -> pd.DataFrame:
    """Original- und bereits umbenannte Spaltennamen auf das Zielschema mappen."""
    rename: dict[str, str] = {}
    for col in df.columns:
        c = _canon(str(col))
        if c in ("zeitraum von", "timefrom"):
            rename[col] = "timeFrom"
        elif c in ("zeitraum bis", "timeto"):
            rename[col] = "timeTo"
        elif "bezug" in c and "wirkenergie" in c:
            rename[col] = "Bezug-Wirkenergie"
        elif "ruecklieferung" in c and "wirkenergie" in c:
            rename[col] = "Ruecklieferung-Wirkenergie"
    return df.rename(columns=rename)


@st.cache_data
def parse_lastgang(src) -> pd.DataFrame:
    """Lastgang-CSV (Viertelstundenwerte) auf Tagessummen aggregieren.

    Akzeptiert das Original-Exportformat (Header 'Zeitraum von;...;Bezug
    Wirkenergie [kW];...' mit optionalem Metadaten-Vorspann und Umlauten)
    ebenso wie die vereinfachte Variante (timeFrom;...;Bezug-Wirkenergie;...).
    src ist ein Pfad (Demo-Daten) oder ein hochgeladenes File-Objekt (im RAM).
    """
    lines = _read_text(src).splitlines()

    # Header-Zeile suchen -> evtl. vorangestellte Metadaten-Zeilen überspringen.
    header_row = next(
        (i for i, line in enumerate(lines)
         if _canon(line.split(";")[0]) in _LASTGANG_HEADER_KEYS),
        None,
    )
    if header_row is None:
        raise ValueError(
            "Header nicht gefunden – erwarte eine Zeile mit 'Zeitraum von' bzw. 'timeFrom'."
        )

    df = pd.read_csv(io.StringIO("\n".join(lines[header_row:])), sep=";", decimal=".")
    df = _normalize_lastgang(df)

    required = {"timeFrom", "Bezug-Wirkenergie", "Ruecklieferung-Wirkenergie"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Lastgang-CSV: fehlende Spalten {sorted(missing)}")

    # Footer-Zeilen (z. B. 'Minimalwert;;…', 'Mittelwert', 'Maximalwert') und
    # sonstige Fremdzeilen verwerfen: was kein gültiges Datum ergibt, fliegt raus.
    df["timeFrom"] = pd.to_datetime(df["timeFrom"], format="%d.%m.%Y %H:%M", errors="coerce")
    df = df.dropna(subset=["timeFrom"]).copy()
    for col in ("Bezug-Wirkenergie", "Ruecklieferung-Wirkenergie"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

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
    return daily


@st.cache_data
def parse_pv(src) -> pd.DataFrame:
    """PV-Produktions-CSV (Tageswerte) laden.

    Erwartete Spalten: 'Date and time [dd.MM.yyyy]', 'Total system [kWh]'.
    """
    pv = pd.read_csv(src)
    required = {"Date and time [dd.MM.yyyy]", "Total system [kWh]"}
    missing = required - set(pv.columns)
    if missing:
        raise ValueError(f"PV-CSV: fehlende Spalten {sorted(missing)}")

    pv["Datum"] = pd.to_datetime(pv["Date and time [dd.MM.yyyy]"], format="%d.%m.%Y")
    return pv


def plot_daily(daily: pd.DataFrame | None, pv: pd.DataFrame | None) -> go.Figure:
    """Tageswerte-Plot. Zeichnet nur die Linien, deren Daten vorhanden sind."""
    fig = go.Figure()
    if daily is not None:
        fig.add_trace(go.Scatter(
            x=daily["Datum"], y=daily["Bezug_kWh"].round(2),
            mode="lines+markers", name="Bezug", line=dict(color="steelblue"),
        ))
        fig.add_trace(go.Scatter(
            x=daily["Datum"], y=daily["Ruecklieferung_kWh"].round(2),
            mode="lines+markers", name="Ruecklieferung", line=dict(color="orange"),
        ))
    if pv is not None:
        fig.add_trace(go.Scatter(
            x=pv["Datum"], y=pv["Total system [kWh]"].round(2),
            mode="lines+markers", name="PV Produktion", line=dict(color="green"),
        ))
    fig.update_layout(
        title="Lastgang - Tageswerte",
        xaxis_title="Datum",
        yaxis_title="Energie [kWh/Tag]",
        hovermode="x unified",
    )
    return fig


def load_source(uploaded, parse_fn, demo_path, use_demo: bool, label: str):
    """Quelle wählen: hochgeladene Datei > Demo (nur im unberührten Startzustand).

    Gibt (DataFrame | None) zurück und zeigt bei Parse-Fehlern st.error statt Stacktrace.
    """
    src = uploaded if uploaded is not None else (str(demo_path) if use_demo else None)
    if src is None:
        return None
    try:
        return parse_fn(src)
    except Exception as exc:  # noqa: BLE001 - Nutzer-Feedback statt Absturz
        st.error(f"{label} konnte nicht gelesen werden: {exc}")
        return None


def fmt_kwh(value: float) -> str:
    return f"{value:,.0f} kWh".replace(",", "'")


st.set_page_config(page_title="PV Eigenverbrauch", layout="wide")
st.title("PV Eigenverbrauch")

with st.sidebar:
    st.header("Eigene Daten hochladen")
    up_last = st.file_uploader("Lastgang-CSV", type="csv")
    st.caption("`;`-getrennt — Spalten: timeFrom, Bezug-Wirkenergie, Ruecklieferung-Wirkenergie")
    up_pv = st.file_uploader("PV-Produktion-CSV", type="csv")
    st.caption("`,`-getrennt — Spalten: 'Date and time [dd.MM.yyyy]', 'Total system [kWh]'")
    st.caption("Hochgeladene Dateien werden nur für die Auswertung verwendet und nicht gespeichert.")

# Demo-Daten nur im unberührten Startzustand (nichts hochgeladen).
any_upload = up_last is not None or up_pv is not None
if not any_upload:
    st.info("Beispielansicht mit den hinterlegten Daten aus source/. "
            "Lade links eigene Dateien hoch, um deine Auswertung zu sehen.")

daily = load_source(up_last, parse_lastgang, LAST_PATH, not any_upload, "Lastgang-CSV")
pv = load_source(up_pv, parse_pv, PV_PATH, not any_upload, "PV-CSV")

if daily is None and pv is None:
    st.warning("Keine auswertbaren Daten vorhanden. Bitte lade mindestens eine gültige CSV hoch.")
    st.stop()

# Kennzahlen – nur was sich aus den vorhandenen Daten berechnen lässt.
metrics: list[tuple[str, str]] = []
sum_feed_in = sum_consumption = pv_production = None
if daily is not None:
    sum_consumption = round(daily["Bezug_kWh"].sum(), 1)
    sum_feed_in = round(daily["Ruecklieferung_kWh"].sum(), 1)
    metrics.append(("Netzbezug", fmt_kwh(sum_consumption)))
    metrics.append(("Einspeisung", fmt_kwh(sum_feed_in)))
if pv is not None:
    pv_production = round(pv["Total system [kWh]"].sum(), 1)
    metrics.insert(0, ("PV Produktion", fmt_kwh(pv_production)))
if pv_production and sum_feed_in is not None:
    self_consumption = pv_production - sum_feed_in
    metrics.append(("Eigenverbrauch", f"{self_consumption / pv_production * 100:.1f} %"))

if metrics:
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)

st.subheader("Lastgang - Tageswerte")
st.plotly_chart(plot_daily(daily, pv), use_container_width=True)

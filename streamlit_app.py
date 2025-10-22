
import io
import os
import re
import sqlite3
import tempfile
from typing import Dict, List

import pandas as pd
import streamlit as st

# ----------------- Postavke stranice -----------------
st.set_page_config(page_title="Rezultati – prazna app (Excel upload)", page_icon="📄", layout="wide")

# (Opcionalno) zaštita lozinkom preko Secrets; ako nije postavljena, ne traži lozinku
def check_auth():
    expected = st.secrets.get("APP_PASSWORD", os.environ.get("APP_PASSWORD", ""))
    if not expected:
        return True
    if "authed" not in st.session_state:
        st.session_state.authed = False
    if st.session_state.authed:
        return True
    st.title("🔒 Zaštićen pristup")
    pwd = st.text_input("Lozinka", type="password")
    if st.button("Prijava"):
        if pwd == expected:
            st.session_state.authed = True
            st.experimental_rerun()
        else:
            st.error("Netočna lozinka.")
    st.stop()

check_auth()

# ----------------- Helperi -----------------
def slugify(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r"[^\w\s-]", "", n)
    n = re.sub(r"[\s\-]+", "_", n)
    return n

def load_excel(bytes_data: bytes) -> Dict[str, pd.DataFrame]:
    """Učitaj sve sheetove iz Excela u {sheet: DataFrame} i normaliziraj nazive stupaca."""
    xls = pd.ExcelFile(io.BytesIO(bytes_data))
    data = {}
    for sheet in xls.sheet_names:
        df = xls.parse(sheet)
        # očisti nazive stupaca
        df.columns = [slugify(str(c)) for c in df.columns]
        data[slugify(sheet)] = df
    return data

def union_frames(frames: List[pd.DataFrame]) -> pd.DataFrame:
    """Sigurno spoji više tablica (union po svim stupcima)."""
    if not frames:
        return pd.DataFrame()
    all_cols = sorted(set().union(*[f.columns for f in frames]))
    aligned = [f.reindex(columns=all_cols) for f in frames]
    return pd.concat(aligned, ignore_index=True)

def unique_sorted(df: pd.DataFrame, col: str) -> List[str]:
    """Jedinstvene vrijednosti sortirane kao tekst (sprječava miješane tipove)."""
    if col and col in df.columns:
        vals = df[col].dropna().astype(str).unique().tolist()
        vals = [v for v in vals if v.strip()]
        return sorted(vals, key=str)
    return []

def df_to_sqlite_bytes(tables: Dict[str, pd.DataFrame]) -> bytes:
    """Spremi više DataFrameova u SQLite i vrati bytes datoteke."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        path = tmp.name
    try:
        conn = sqlite3.connect(path)
        for name, df in tables.items():
            df.to_sql(name, conn, if_exists="replace", index=False)
        conn.close()
        with open(path, "rb") as f:
            content = f.read()
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
    return content

# ----------------- UI: Upload -----------------
st.sidebar.header("📁 Učitaj Excel")
uploaded = st.sidebar.file_uploader("Excel (.xlsx)", type=["xlsx"])

st.title("📄 Prazna aplikacija — učitaj Excel i radi s podacima")

if not uploaded:
    st.info("Učitaj svoj **.xlsx** (s više sheetova po želji). App će sve spojiti i omogućiti filtriranje te izvoz.")
    st.stop()

# Učitavanje Excela
tables = load_excel(uploaded.getvalue())
st.sidebar.success(f"Učitano listova: {len(tables)}")

# Dodaj heuristički stupac 'godina' iz naziva sheeta (ako sadrži 20xx)
frames = []
for sheet_name, df in tables.items():
    m = re.search(r"(20\d{2})", sheet_name)
    df = df.copy()
    df["izvor_tablice"] = sheet_name
    df["godina"] = int(m.group(1)) if m else pd.NA
    frames.append(df)

df = union_frames(frames)

if df.empty:
    st.warning("Excel je prazan ili nisam mogao pročitati podatke.")
    st.stop()

# ----------------- Heuristika stupaca (ako postoje) -----------------
def pick_col(df: pd.DataFrame, candidates) -> str | None:
    cols = set(df.columns)
    for cand in candidates:
        for c in cols:
            if c == cand or c.endswith(f"_{cand}") or cand in c:
                return c
    return None

col_ime       = pick_col(df, ["ime", "ime_prezime", "sportas", "natjecatelj", "athlete", "competitor"])
col_prezime   = pick_col(df, ["prezime", "surname", "last_name"])
col_klub      = pick_col(df, ["klub", "club", "team"])
col_kat       = pick_col(df, ["kategorija", "kat", "divizija", "uzrast", "age_group"])
col_plasman   = pick_col(df, ["plasman", "mjesto", "place", "rank"])
col_datum     = pick_col(df, ["datum", "date", "vrijeme", "datum_natjecanja"])
col_natjecanje= pick_col(df, ["natjecanje", "turnir", "dogadaj", "event", "naziv_natjecanja", "priredba"])

# ----------------- Brzi sažetak -----------------
with st.expander("📊 Sažetak", expanded=True):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Broj zapisa", len(df))
    if "godina" in df.columns:
        c2.metric("Godina (unikatno)", df["godina"].dropna().nunique())
    if col_klub:
        c3.metric("Klubova", df[col_klub].dropna().nunique())
    if col_kat:
        c4.metric("Kategorija", df[col_kat].dropna().nunique())

# ----------------- Filteri -----------------
st.sidebar.header("🔎 Filteri")
q = st.sidebar.text_input("Pretraga (ime/prezime/naziv natjecanja)", placeholder="npr. Ana, Kovač…")
godine = st.sidebar.multiselect("Godina", unique_sorted(df, "godina"), default=unique_sorted(df, "godina"))
kat = st.sidebar.multiselect("Kategorija", unique_sorted(df, col_kat))
klub = st.sidebar.multiselect("Klub", unique_sorted(df, col_klub))

fdf = df.copy()
if "godina" in fdf.columns and godine:
    fdf = fdf[fdf["godina"].astype(str).isin([str(g) for g in godine])]

def contains_any(row: pd.Series, term: str) -> bool:
    term = term.strip()
    if not term:
        return True
    fields = []
    for c in [col_ime, col_prezime, col_natjecanje]:
        if c and c in row:
            fields.append(str(row[c]) if pd.notna(row[c]) else "")
    return any(term.lower() in s.lower() for s in fields)

if q:
    fdf = fdf[fdf.apply(lambda r: contains_any(r, q), axis=1)]

if kat and col_kat in fdf.columns:
    fdf = fdf[fdf[col_kat].astype(str).isin([str(x) for x in kat])]

if klub and col_klub in fdf.columns:
    fdf = fdf[fdf[col_klub].astype(str).isin([str(x) for x in klub])]

# ----------------- Tablica -----------------
st.subheader("📋 Podaci")
priority = [c for c in [col_ime, col_prezime, col_klub, col_kat, col_plasman, col_natjecanje, col_datum, "godina", "izvor_tablice"] if c and c in fdf.columns]
other = [c for c in fdf.columns if c not in priority]
view_cols = priority + other
st.dataframe(fdf[view_cols], use_container_width=True)

# ----------------- Exporti -----------------
st.subheader("⬇️ Izvoz")
csv_bytes = fdf[view_cols].to_csv(index=False).encode("utf-8")
st.download_button("Preuzmi filtrirane podatke (CSV)", data=csv_bytes, file_name="rezultati_filtrirano.csv", mime="text/csv")

# SQLite (svaki sheet ide u zasebnu tablicu; plus jedna 'sveukupno')
tables_for_sqlite = {name: df for name, df in tables.items()}
tables_for_sqlite["sveukupno"] = df
sqlite_bytes = df_to_sqlite_bytes(tables_for_sqlite)
st.download_button("Preuzmi SQLite bazu (iz ovog Excela)", data=sqlite_bytes, file_name="rezultati_iz_excela.sqlite", mime="application/octet-stream")

st.caption("Ovo je minimalna verzija – nema trajnog spremanja na server. Svaki put učitaj Excel i po želji preuzmi CSV/SQLite.")

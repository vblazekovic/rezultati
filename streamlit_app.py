
import os
import re
import sqlite3
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Rezultati – HK Podravka", page_icon="🥇", layout="wide")

# -------- 1) Zaštita lozinkom --------
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

# -------- 2) Pomoćne funkcije --------
def slugify(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r"[^\w\s-]", "", n)
    n = re.sub(r"[\s\-]+", "_", n)
    return n

@st.cache_data(show_spinner=False)
def load_sqlite(db_path: str) -> dict:
    """Učitaj sve tablice iz SQLite u dict {tablica: DataFrame}."""
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    data = {}
    for t in tables:
        try:
            df = pd.read_sql(f"SELECT * FROM {t}", conn)
            df.columns = [slugify(str(c)) for c in df.columns]
            df["izvor_tablice"] = t
            m = re.search(r"(20\d{2})", t)
            df["godina"] = int(m.group(1)) if m else pd.NA
            data[t] = df
        except Exception as e:
            st.warning(f"Ne mogu učitati tablicu {t}: {e}")
    conn.close()
    return data

@st.cache_data(show_spinner=False)
def excel_to_frames(bytes_data: bytes) -> dict:
    """Učitaj Excel u dict {sheet: DataFrame} s normaliziranim nazivima stupaca."""
    import io
    xls = pd.ExcelFile(io.BytesIO(bytes_data))
    data = {}
    for sheet in xls.sheet_names:
        df = xls.parse(sheet)
        df.columns = [slugify(str(c)) for c in df.columns]
        df["izvor_tablice"] = slugify(sheet)
        m = re.search(r"(20\d{2})", sheet)
        df["godina"] = int(m.group(1)) if m else pd.NA
        data[slugify(sheet)] = df
    return data

def pick_col(df: pd.DataFrame, candidates) -> str | None:
    """Vrati naziv prvog pronađenog stupca koji odgovara kandidatima."""
    cols = set(df.columns)
    for cand in candidates:
        for c in cols:
            if c == cand or c.endswith(f"_{cand}") or cand in c:
                return c
    return None

def union_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Sigurno spoji sve tablice (union po svim stupcima)."""
    if not frames:
        return pd.DataFrame()
    all_cols = sorted(set().union(*[f.columns for f in frames]))
    aligned = [f.reindex(columns=all_cols) for f in frames]
    df = pd.concat(aligned, ignore_index=True)
    return df

def unique_sorted(df, col):
    """Vrati sortirane jedinstvene vrijednosti kao stringove (sprječava TypeError)."""
    if col and col in df.columns:
        vals = df[col].dropna().astype(str).unique().tolist()
        vals = [v for v in vals if v.strip() != ""]
        return sorted(vals, key=str)
    return []

# -------- 3) Izvor podataka (baza ili upload Excel) --------
st.sidebar.header("📁 Izvor podataka")
default_db_path = "data/rezultati_baza.sqlite"
use_uploaded = st.sidebar.toggle("Koristi učitani Excel umjesto baze", value=False)
uploaded = st.sidebar.file_uploader("Učitaj Excel (.xlsx)", type=["xlsx"], disabled=not use_uploaded)

if use_uploaded and uploaded is not None:
    data_dict = excel_to_frames(uploaded.getvalue())
else:
    data_dict = load_sqlite(default_db_path)

if not data_dict:
    st.warning("Nema učitanih tablica. Učitaj Excel (gore lijevo) ili dodaj `rezultati_baza.sqlite` u folder `data/`.")
    st.stop()

st.sidebar.write(f"Učitano tablica: **{len(data_dict)}**")

frames = list(data_dict.values())
df = union_frames(frames)
if df.empty:
    st.warning("Nema podataka za prikaz.")
    st.stop()

# -------- 4) Heuristika stupaca --------
col_ime = pick_col(df, ["ime", "ime_prezime", "sportas", "natjecatelj", "athlete", "competitor"])
col_prezime = pick_col(df, ["prezime", "surname", "last_name"])
col_klub = pick_col(df, ["klub", "club", "team"])
col_kat = pick_col(df, ["kategorija", "kat", "divizija", "uzrast", "age_group"])
col_datum = pick_col(df, ["datum", "date", "vrijeme", "datum_natjecanja"])
col_bodovi = pick_col(df, ["bodovi", "bod", "points", "score"])
col_medalja = pick_col(df, ["medalja", "medal", "medalja_tip"])
col_plasman = pick_col(df, ["plasman", "mjesto", "place", "rank"])
col_natjecanje = pick_col(df, ["natjecanje", "turnir", "dogadaj", "event", "naziv_natjecanja", "priredba", "competiton"])

# -------- 5) Filteri --------
st.sidebar.header("🔎 Filteri")
q = st.sidebar.text_input("Pretraga imena / prezimena", placeholder="npr. Ana, Kovač…")
g_sel = sorted([g for g in df["godina"].dropna().unique().tolist()]) if "godina" in df.columns else []
godine = st.sidebar.multiselect("Godina", g_sel, default=g_sel)

kat_vals = unique_sorted(df, col_kat)
kat = st.sidebar.multiselect("Kategorija", kat_vals, default=[])

klub_vals = unique_sorted(df, col_klub)
klub = st.sidebar.multiselect("Klub", klub_vals, default=[])

fdf = df.copy()
if "godina" in fdf.columns and godine:
    fdf = fdf[fdf["godina"].isin(godine)]

def contains_safe(series: pd.Series, term: str):
    return series.fillna("").str.contains(term, case=False, na=False)

if q and (col_ime or col_prezime):
    if col_ime and col_prezime and col_ime in fdf.columns and col_prezime in fdf.columns:
        fdf = fdf[contains_safe(fdf[col_ime], q) | contains_safe(fdf[col_prezime], q)]
    else:
        name_cols = [c for c in [col_ime, col_prezime] if c in fdf.columns]
        if name_cols:
            mask = False
            for c in name_cols:
                mask = mask | contains_safe(fdf[c], q)
            fdf = fdf[mask]

if kat and col_kat in fdf.columns:
    fdf = fdf[fdf[col_kat].isin(kat)]
if klub and col_klub in fdf.columns:
    fdf = fdf[fdf[col_klub].isin(klub)]

# -------- 6) Prikaz --------
st.title("🥇 Rezultati — pretraga i statistika")
st.caption("HK Podravka • Brza pretraga po imenima, klubovima, kategorijama i godinama.")

with st.expander("📊 Brza statistika", expanded=False):
    left, right, right2 = st.columns(3)
    left.metric("Broj zapisa", len(fdf))
    if col_klub in fdf.columns:
        right.metric("Broj klubova", fdf[col_klub].nunique())
    if col_kat in fdf.columns:
        right2.metric("Broj kategorija", fdf[col_kat].nunique())
    if col_klub in fdf.columns and col_plasman in fdf.columns:
        st.subheader("Poredak klubova po medaljama (1.–3.)")
        md = fdf[fdf[col_plasman].astype(str).isin(["1", "2", "3"])]
        tally = md.groupby([col_klub, col_plasman]).size().unstack(fill_value=0)
        tally["ukupno"] = tally.sum(axis=1)
        tally = tally.sort_values("ukupno", ascending=False)
        st.dataframe(tally, use_container_width=True)

st.subheader("📋 Rezultati")
priority_cols = [c for c in [
    col_ime, col_prezime, col_klub, col_kat, col_plasman, col_bodovi, col_medalja, col_natjecanje, col_datum, "godina", "izvor_tablice"
] if c and c in fdf.columns]
other_cols = [c for c in fdf.columns if c not in priority_cols]
view_cols = priority_cols + other_cols
st.dataframe(fdf[view_cols], use_container_width=True)

st.download_button(
    "⬇️ Preuzmi filtrirane rezultate (CSV)",
    data=fdf[view_cols].to_csv(index=False).encode("utf-8"),
    file_name="filtrirani_rezultati.csv",
    mime="text/csv",
)

st.sidebar.markdown("---")
st.sidebar.caption("Pristup zaštićen lozinkom.")

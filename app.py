import io
import json
import re
from typing import List, Optional, Tuple

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from utils import *

st.set_page_config(page_title="Poles map", layout="wide")
st.title("📍 Poles by Hour — Folium in Streamlit")

POPUP_W = 520
IMG_MAX_H = 320
REQUIRED_COLS: List[str] = [
    "lat", "lon", "ts", "fwd_path", "pole_id", "segment_id",
    "rail_incl_smoothed", "misplacement_smoothed", "pole_incl_right",
]

EDITABLE_COLS = ["rail_incl_smoothed", "misplacement_smoothed", "pole_incl_right"]

def street_view_url(lat, lon, heading=0, pitch=0, fov=90):
    return (
        f"https://www.google.com/maps/@?api=1&map_action=pano"
        f"&viewpoint={lat},{lon}&heading={heading}&pitch={pitch}&fov={fov}"
    )

@st.cache_data(show_spinner=True)
def load_data(name: str, data_bytes: bytes) -> pd.DataFrame:
    name_l = (name or "").lower()

    if any(name_l.endswith(ext) for ext in [
        ".parquet", ".parq", ".pq", ".parquet.gzip", ".parq.gz", ".pq.gz"
    ]):
        try:
            df = pd.read_parquet(io.BytesIO(data_bytes), engine="pyarrow", columns=REQUIRED_COLS)
        except Exception:
            df = pd.read_parquet(io.BytesIO(data_bytes), engine="pyarrow")
    else:
        try:
            df = pd.read_csv(io.BytesIO(data_bytes), low_memory=False)
        except Exception:
            df = pd.read_csv(io.BytesIO(data_bytes), low_memory=False, encoding="latin-1")

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df[REQUIRED_COLS].copy()

    for c in ["lat", "lon", "rail_incl_smoothed", "misplacement_smoothed", "pole_incl_right"]:
        df[c] = pd.to_numeric(df[c], errors="coerce", downcast="float")
    for c in ["pole_id", "segment_id", "fwd_path"]:
        df[c] = df[c].astype("category")

    if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    df["hour"] = df["ts"].dt.hour.astype("Int8")

    df = df.reset_index(drop=False).rename(columns={"index": "row_id"})
    df["row_id"] = df["row_id"].astype("Int64")

    def _fmt(v, fmt):
        try:
            return fmt.format(v) if pd.notna(v) else "—"
        except Exception:
            return "—"

    df["rail_txt"] = df["rail_incl_smoothed"].apply(lambda v: _fmt(v, "{:.0f}°"))
    df["misp_txt"] = df["misplacement_smoothed"].apply(lambda v: _fmt(v, "{:.2f}"))
    df["pole_txt"] = df["pole_incl_right"].apply(lambda v: _fmt(v, "{:.2f}"))

    df["color"] = df["misplacement_smoothed"].apply(lambda v: get_color(v))
    return df

uploaded = st.file_uploader(
    "Upload merged dataframe (Parquet or CSV)",
    type=["parquet","parq","pq","parquet.gz","parq.gz","pq.gz","parquet.gzip","csv","csv.gz"],
)
if not uploaded:
    st.info(
        "Upload a file with at least: lat, lon, ts, fwd_path, pole_id, segment_id, "
        "rail_incl_smoothed, misplacement_smoothed, pole_incl_right."
    )
    st.stop()

try:
    df = load_data(uploaded.name, uploaded.getvalue())
except Exception as e:
    st.error(str(e))
    st.stop()

st.caption(f"Loaded **{len(df):,}** rows • approx memory: "
           f"**{df.memory_usage(deep=True).sum()/1e6:.1f} MB**")

if "edits" not in st.session_state:
    st.session_state.edits = []  # list of dicts
if "selected_row_id" not in st.session_state:
    st.session_state.selected_row_id = None

hours_present = sorted([int(h) for h in df["hour"].dropna().unique().tolist()])
default_hours = [h for h in hours_present if 5 <= h <= 15] or hours_present

with st.sidebar:
    st.header("Filters & Performance")
    sel_hours = st.multiselect("Hours (local to `ts`)", options=hours_present, default=default_hours)
    MAX_POINTS = st.slider("Max points to render", 500, 20000, 2000, step=500)  # slightly lower default for smoothness
    zoom_start = st.slider("Initial zoom", 6, 18, 12)

subset = df[df["hour"].isin(sel_hours)] if sel_hours else df

def make_intro_marker(fmap: folium.Map, center: Tuple[float, float]):
    folium.Marker(
        location=center,
        icon=folium.Icon(color="blue", icon="info-sign"),
        popup=folium.Popup(
            "Click a circle to select a row for editing below.",
            max_width=280,
        ),
    ).add_to(fmap)

def build_popup(row) -> folium.Popup:
    sv_url = street_view_url(row["lat"], row["lon"])
    fwd_url = row.get("fwd_path")
    has_fwd = pd.notna(fwd_url) and str(fwd_url).strip() != ""

    # Always embed forward image in popup (or show a placeholder note)
    if has_fwd:
        img_html = (
            f"<div style='margin-top:6px'>"
            f"  <img src='{fwd_url}' style='width:100%;max-height:{IMG_MAX_H}px;object-fit:contain;"
            f"  border:1px solid #ccc;border-radius:6px' loading='lazy'/>"
            f"</div>"
        )
    else:
        img_html = "<div style='margin-top:6px;color:#888;'>No forward image available</div>"

    html = (
        f"<div style='font-size:16px; line-height:1.35;' data-rowid='{int(row.get('row_id'))}'>"
        f"  <div><strong>Row ID:</strong> {int(row.get('row_id'))}</div>"
        f"  <div><strong>Pole id:</strong> {row.get('pole_id')}</div>"
        f"  <div><strong>Segment_id:</strong> {row.get('segment_id')}</div>"
        f"  <div><strong>Rail inclination:</strong> {row.get('rail_txt')}</div>"
        f"  <div><strong>Misplacement:</strong> {row.get('misp_txt')}</div>"
        f"  <div><strong>Pole incl right:</strong> {row.get('pole_txt')}</div>"
        f"  <div style='margin-top:6px;'><a href='{sv_url}' target='_blank' style='font-weight:600;'>Street View</a></div>"
        f"  {img_html}"
        f"</div>"
    )
    return folium.Popup(html, max_width=POPUP_W, min_width=POPUP_W)

def add_points_with_cluster(fmap: folium.Map, data: pd.DataFrame, cap: int):
    cluster = MarkerCluster(disableClusteringAtZoom=16, spiderfyOnMaxZoom=True)
    cluster.add_to(fmap)

    if len(data) > cap:
        data = data.sample(cap, random_state=0)

    for _, row in data.iterrows():
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=4,         
            fill=True,
            color=row["color"],
            opacity=0,          # no stroke for faster paint
            weight=0,           # no stroke width
            fill_opacity=0.55,
            popup=build_popup(row),
        ).add_to(cluster)

def extract_row_id_from_popup(popup_html: Optional[str]) -> Optional[int]:
    """Reads data-rowid="<id>" from popup html."""
    if not popup_html:
        return None
    m = re.search(r'data-rowid=[\'"](\d+)[\'"]', str(popup_html))
    return int(m.group(1)) if m else None

# ----- Map render -----
if subset.empty:
    st.warning("No rows match the selected hours.")
else:
    center = [subset["lat"].mean(), subset["lon"].mean()]
    fmap = folium.Map(
        location=center,
        zoom_start=zoom_start,
        control_scale=True,
        prefer_canvas=True,        # smoother with many points
        tiles="CartoDB Positron",  # light basemap
    )
    make_intro_marker(fmap, center)
    add_points_with_cluster(fmap, subset, MAX_POINTS)
    folium.LayerControl(collapsed=False).add_to(fmap)

    out = st_folium(
        fmap,
        height=720,
        use_container_width=True,                 # (streamlit-folium param is fine)
        key="points_map",
        returned_objects=["last_object_clicked_popup"],  # only clicks trigger a rerun
    )

    clicked_popup = out.get("last_object_clicked_popup") if out else None
    rid = extract_row_id_from_popup(clicked_popup)
    if rid is not None:
        st.session_state.selected_row_id = rid

# ----- Editing panel -----
st.subheader("✏️ Edit selected measurement (writes to diff file, original data untouched)")

col_sel, col_info = st.columns([1, 2], vertical_alignment="top")

with col_sel:
    selected_row_id = st.number_input(
        "Row ID",
        min_value=0,
        value=int(st.session_state.selected_row_id) if st.session_state.selected_row_id is not None else 0,
        step=1,
        help="Click a marker to auto-fill. Or type a Row ID."
    )
    row_exists = selected_row_id in df["row_id"].values

with col_info:
    if not row_exists:
        st.info("Select a valid Row ID by clicking a marker on the map, or enter one manually.")
    else:
        row = df.loc[df["row_id"] == selected_row_id].iloc[0]
        st.markdown(
            f"**Pole:** `{row['pole_id']}` &nbsp;&nbsp; **Segment:** `{row['segment_id']}` &nbsp;&nbsp; "
            f"**Lat/Lon:** {row['lat']:.6f}, {row['lon']:.6f} &nbsp;&nbsp; **Hour:** {int(row['hour']) if pd.notna(row['hour']) else '—'}"
        )
        st.markdown("**Current values:** "
                    f"Rail incl: `{row['rail_incl_smoothed']}` &nbsp;&nbsp; "
                    f"Misplacement: `{row['misplacement_smoothed']}` &nbsp;&nbsp; "
                    f"Pole incl right: `{row['pole_incl_right']}`")

        with st.form(key="edit_form", clear_on_submit=False):
            st.write("Set new values (leave blank to skip). Check 'NaN' to clear a value.")
            new_vals = {}
            for col in EDITABLE_COLS:
                c1, c2 = st.columns([3, 1])
                with c1:
                    txt = st.text_input(f"{col}", value="", placeholder="leave blank = no change")
                with c2:
                    set_nan = st.checkbox(f"NaN {col}", value=False, key=f"nan_{col}")
                if set_nan:
                    new_vals[col] = None
                elif txt.strip() != "":
                    try:
                        new_vals[col] = float(txt)
                    except ValueError:
                        st.warning(f"Could not parse number for {col}; change for that field ignored.")

            submitted = st.form_submit_button("Add change to diff", key="submit_edit")
            if submitted:
                if not any(k in new_vals for k in EDITABLE_COLS):
                    st.info("No changes provided.")
                else:
                    ts = pd.Timestamp.utcnow().isoformat()
                    for col, val in new_vals.items():
                        if col in EDITABLE_COLS and (val is None or isinstance(val, float)):
                            st.session_state.edits.append({
                                "row_id": int(selected_row_id),
                                "pole_id": str(row["pole_id"]),
                                "segment_id": str(row["segment_id"]),
                                "column": col,
                                "new_value": None if val is None else float(val),
                                "timestamp_utc": ts,
                            })
                    st.success("Change(s) queued in diff buffer below. Use Download to save to file.")

# ----- Diff review & download -----
st.divider()
st.subheader("📝 Pending edits (not applied to original data)")

if len(st.session_state.edits) == 0:
    st.caption("No edits yet. Add some above.")
else:
    edits_df = pd.DataFrame(st.session_state.edits)
    st.dataframe(edits_df, width="stretch", hide_index=True)

    # CSV (NaN as empty) and JSONL variants
    csv_buf = io.StringIO()
    edits_export = edits_df.copy()
    edits_export["new_value"] = edits_export["new_value"].apply(lambda v: "" if v is None else v)
    edits_export.to_csv(csv_buf, index=False)
    csv_bytes = csv_buf.getvalue().encode("utf-8")

    jsonl_buf = io.StringIO()
    for rec in st.session_state.edits:
        jsonl_buf.write(json.dumps(rec) + "\n")
    jsonl_bytes = jsonl_buf.getvalue().encode("utf-8")

    cdl, cdl2, clr = st.columns([1, 1, 1])
    with cdl:
        st.download_button(
            "⬇️ Download edits.csv",
            data=csv_bytes,
            file_name="edits.csv",
            mime="text/csv",
            width="stretch",
            key="dl_csv",
        )
    with cdl2:
        st.download_button(
            "⬇️ Download edits.jsonl",
            data=jsonl_bytes,
            file_name="edits.jsonl",
            mime="application/json",
            width="stretch",
            key="dl_jsonl",
        )
    with clr:
        if st.button("🧹 Clear pending edits", key="clear_edits_btn"):
            st.session_state.edits = []
            st.rerun()

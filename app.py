import io
import json
from typing import List

import pandas as pd
import pydeck as pdk
import streamlit as st

from utils import *

st.set_page_config(page_title="Poles map", layout="wide")
st.title("📍 Inclination QC")

pdk.settings.map_provider = "carto"
pdk.settings.map_style = "light"

POPUP_W = 400
IMG_MAX_H = 300
REQUIRED_COLS: List[str] = [
    "lat", "lon", "ts", "fwd_path", "pole_id",
    "rail_incl_corrected", "misplacement",
    "rail_top_amsl", "asphalt_amsl", "shoulder_amsl",
]
EDITABLE_COLS = ["rail_incl_corrected", "misplacement"]

# ---------------------- Session state ----------------------
if "edits" not in st.session_state:
    st.session_state.edits = []
if "selected_row_id" not in st.session_state:
    st.session_state.selected_row_id = None


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

    # Ensure ts is datetime
    if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
        with pd.option_context("mode.chained_assignment", None):
            df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)

    df["hour"] = df["ts"].dt.hour.astype("Int8")
    df = df.reset_index(drop=True)
    df["row_id"] = df.index.astype("Int64")

    # Color → hex via your util, then to RGB for pydeck
    df["color_hex"] = df["misplacement"].apply(lambda v: get_color(v))
    df["rgb"] = df["color_hex"].apply(hex_to_rgb_list)

    return df

# ---------------------- Upload ----------------------
uploaded = st.file_uploader(
    "Upload merged dataframe (Parquet or CSV)",
    type=["parquet","parq","pq","parquet.gz","parq.gz","pq.gz","parquet.gzip","csv","csv.gz"],
)
if not uploaded:
    st.info("Upload a file with at least: lat, lon, ts, fwd_path, pole_id, rail_incl_corrected, misplacement.")
    st.stop()

try:
    df = load_data(uploaded.name, uploaded.getvalue())
except Exception as e:
    st.error(str(e))
    st.stop()

# ---------------------- Sidebar filters ----------------------
hours_present = sorted([int(h) for h in df["hour"].dropna().unique().tolist()])
default_hours = [h for h in hours_present if 5 <= h <= 15] or hours_present

with st.sidebar:
    st.header("Filters & Rendering")
    sel_hours = st.multiselect("Hours (local to `ts`)", options=hours_present, default=default_hours)
    zoom_start = st.slider("Initial zoom", 6, 18, 12)
    show_img = st.checkbox("Show forward image in tooltip", value=True,
                           help="Disable if hovering becomes heavy on slow networks.")

subset = df[df["hour"].isin(sel_hours)] if sel_hours else df

with st.sidebar:
    st.subheader("Render row range")
    if subset.empty:
        st.info("No rows for the selected hours.")
        st.stop()
    render_min = int(subset["row_id"].min())
    render_max = int(subset["row_id"].max())
    render_start, render_end = st.slider(
        "Row IDs (inclusive)",
        min_value=render_min,
        max_value=render_max,
        value=(render_min, render_max),
        step=1,
        help="Only points whose row_id is within this range will be drawn.",
        key="render_range",
    )

# Final slice to render
to_render = subset[(subset["row_id"] >= render_start) & (subset["row_id"] <= render_end)].copy()

if to_render.empty:
    st.warning("No rows match the selected hours and row range.")
    st.stop()

# Add derived fields used by tooltip (avoid heavy formatting in HTML)
to_render["mispl_str"] = to_render["misplacement"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "—")
to_render["rail_incl_str"] = to_render["rail_incl_corrected"].map(lambda x: f"{x:.0f}" if pd.notna(x) else "—")
to_render["sv_url"] = to_render.apply(lambda r: street_view_url(r["lat"], r["lon"]), axis=1)

# ---------------------- pydeck map ----------------------
center_lat = float(to_render["lat"].mean())
center_lon = float(to_render["lon"].mean())

view_state = pdk.ViewState(
    latitude=center_lat,
    longitude=center_lon,
    zoom=float(zoom_start),
    pitch=0,
    bearing=0,
)

st.markdown("""
<style>
  /* Let tooltip capture clicks and sit above the canvas */
  .deck-tooltip{
    pointer-events: auto !important;
    z-index: 99999 !important;
    /* Pull the tooltip under the cursor so you can click without moving */
    margin: -24px 0 0 -24px; /* tweak -16..-32px as you like */
  }
  .deck-tooltip a{
    pointer-events: auto !important;
    display: block;
    width: 100%;
    height: 100%;  /* make the whole tooltip clickable */
    cursor: pointer;
  }
</style>
""", unsafe_allow_html=True)



tooltip_html = (
    """
<a href="{sv_url}" target="_blank" rel="noopener noreferrer"
   style="display:block; text-decoration:none; color:inherit;">
  <div style="width:{POPUP_W}px">
    <div style="font-weight:600;margin-bottom:6px;">Open Street View ↗</div>
    <div><b>Row ID:</b> {row_id}</div>
    <div><b>Pole:</b> {pole_id}</div>
    <div><b>Rail incl:</b> {rail_incl_str}°</div>
    <div><b>Misplacement:</b> {mispl_str} m</div>
"""
    + (
        f"""    <div style="margin-top:6px">
      <img src="{{fwd_path}}" style="width:100%; max-height:{IMG_MAX_H}px;object-fit:contain;border:1px solid #ccc;border-radius:6px"/>
    </div>"""
        if show_img
        else ""
    )
    + """
  </div>
</a>
"""
)


# Invisible, larger picking layer (so hover doesn't flicker if you twitch the mouse)
hover_layer = pdk.Layer(
    "ScatterplotLayer",
    data=to_render,
    get_position='[lon, lat]',
    get_radius=32,            # big-ish hover/tap target (in pixels)
    radius_units="pixels",
    get_fill_color=[100, 0, 0, 0.1],  # fully transparent
    opacity=0.5,                # not visible
    pickable=True,            # used only for picking + tooltip
    stroked=False,
)

# Your tiny, visible dots — not pickable (tooltip comes from hover_layer)
scatter = pdk.Layer(
    "ScatterplotLayer",
    data=to_render,
    get_position='[lon, lat]',
    get_fill_color="rgb",
    opacity=0.8,
    pickable=False,           # <-- turn off here
    auto_highlight=True,
    stroked=False,
    radius_units="pixels",
    get_radius=3,             # tiny visual dot
    radius_min_pixels=1,
    radius_max_pixels=12,
)

deck = pdk.Deck(
    layers=[hover_layer, scatter],  # invisible picker first
    initial_view_state=view_state,
    tooltip={
        "html": tooltip_html,
        "style": {
            "pointerEvents": "auto",       # allow click on the tooltip itself
            "backgroundColor": "rgba(255,255,255,0.96)",
            "color": "black",
        },
    },
)


st.pydeck_chart(deck, use_container_width=True, height=600)

# ---------------------- Editing panel ----------------------
st.subheader("✏️ Edit selected measurement (writes to diff file, original data untouched)")
col_sel, col_info = st.columns([1, 2], vertical_alignment="top")

with col_sel:
    min_id = int(df["row_id"].min())
    max_id = int(df["row_id"].max())
    # pydeck can't push click → Python; use the Row ID shown in tooltip
    default_start = int(st.session_state.selected_row_id) if st.session_state.selected_row_id is not None else min_id

    start_id = st.number_input(
        "Start Row ID",
        min_value=min_id, max_value=max_id,
        value=default_start, step=1,
        help="Use the Row ID visible in the tooltip.",
        key="row_start",
    )
    end_id = st.number_input(
        "End Row ID (inclusive)",
        min_value=min_id, max_value=max_id,
        value=int(start_id), step=1,
        help="Use the same as Start to edit a single row.",
        key="row_end",
    )

    # Normalize range, build target ids that actually exist
    s, e = int(start_id), int(end_id)
    if e < s:
        s, e = e, s
    all_ids = set(df["row_id"].astype(int).tolist())
    target_ids = [rid for rid in range(s, e + 1) if rid in all_ids]
    row_exists = len(target_ids) > 0

with col_info:
    if not row_exists:
        st.info("No valid rows in the selected range. Adjust Start/End.")
    else:
        if len(target_ids) == 1:
            row_for_preview = df.loc[df["row_id"] == target_ids[0]].iloc[0]
            st.markdown(
                f"**Pole:** `{row_for_preview['pole_id']}` &nbsp;&nbsp; "
                f"**Lat/Lon:** {row_for_preview['lat']:.6f}, {row_for_preview['lon']:.6f} &nbsp;&nbsp; "
                f"**Hour:** {int(row_for_preview['hour']) if pd.notna(row_for_preview['hour']) else '—'}"
            )
            st.markdown(
                "**Current values:** "
                f"Rail incl (corr): `{row_for_preview['rail_incl_corrected']}` &nbsp;&nbsp; "
                f"Misplacement: `{row_for_preview['misplacement']}`"
            )
        else:
            st.markdown(f"**Range selected:** **{s}–{e}** → **{len(target_ids)}** rows will be updated.")

        with st.form(key="edit_form", clear_on_submit=False):
            st.write("Set new values (leave blank to skip). Check 'NaN' to clear a value for all rows in range.")
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

            submitted = st.form_submit_button("Add change(s) to diff", key="submit_edit")
            if submitted:
                if len(target_ids) == 0:
                    st.info("No valid rows in the selected range.")
                elif not any(k in new_vals for k in EDITABLE_COLS):
                    st.info("No changes provided.")
                else:
                    ts = pd.Timestamp.utcnow().isoformat()
                    for rid in target_ids:
                        row_i = df.loc[df["row_id"] == rid].iloc[0]
                        for col, val in new_vals.items():
                            if col in EDITABLE_COLS and (val is None or isinstance(val, float)):
                                st.session_state.edits.append({
                                    "row_id": int(rid),
                                    "pole_id": str(row_i["pole_id"]),
                                    "column": col,
                                    "new_value": None if val is None else float(val),
                                    "timestamp_utc": ts,
                                })
                    st.success(f"Queued changes for **{len(target_ids)}** row(s). Use Download to save to file.")

# ---------------------- Diff review & download ----------------------
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
            use_container_width=True,
            key="dl_csv",
        )
    with cdl2:
        st.download_button(
            "⬇️ Download edits.jsonl",
            data=jsonl_bytes,
            file_name="edits.jsonl",
            mime="application/json",
            use_container_width=True,
            key="dl_jsonl",
        )
    with clr:
        if st.button("🧹 Clear pending edits", key="clear_edits_btn"):
            st.session_state.edits = []
            st.rerun()

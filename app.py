
import io

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from utils import *

st.set_page_config(page_title="Poles map", layout="wide")
def street_view_url(lat, lon, heading=0, pitch=0, fov=90):
    return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}&heading={heading}&pitch={pitch}&fov={fov}"


st.title("📍 Poles by Hour — Folium in Streamlit")

uploaded = st.file_uploader(
    "Upload merged dataframe (Parquet or CSV)",
    type=["parquet","parq","pq","parquet.gz","parq.gz","pq.gz","parquet.gzip","csv","csv.gz"]
)

if not uploaded:
    st.info("Upload a file with at least: lat, lon, ts, fwd_path, pole_id, segment_id, rail_incl_smoothed, misplacement_smoothed, pole_incl_right.")
    st.stop()

if uploaded.name.lower().endswith(".parquet.gzip"):
    df = pd.read_parquet(uploaded)
else:
    data = uploaded.read()
    try:
        df = pd.read_csv(io.BytesIO(data))
    except Exception:
        df = pd.read_csv(io.BytesIO(data), encoding="latin-1")

required_cols = ["lat", "lon", "ts", "fwd_path", "pole_id", "segment_id",
                 "rail_incl_smoothed", "misplacement_smoothed", "pole_incl_right"]
missing = [c for c in required_cols if c not in df.columns]
if missing:
    st.error(f"Missing required columns: {missing}")
    st.stop()


center = [df["lat"].mean(), df["lon"].mean()]
m = folium.Map(location=center, zoom_start=14, control_scale=True)

POPUP_W = 700      # px
IMG_MAX_H = 500    # px

# Intro marker
folium.Marker(
    location=center,
    icon=folium.Icon(color="blue", icon="info-sign"),
    popup=folium.Popup(
        "Toggle layers in the top-right. Click any circle to open the forward image and Street View for that pole.",
        max_width=260,
    ),
).add_to(m)

# Hours to display (05:00–15:00, inclusive of 15 if present)
HOURS = range(5, 16)

for hr in HOURS:
    df_hr = df[df["ts"].dt.hour == hr]
    if df_hr.empty:
        continue

    fg = folium.FeatureGroup(name=f"{hr:02d}:00", show=(hr == HOURS.start))
    center_hr = [df_hr["lat"].mean(), df_hr["lon"].mean()]

    folium.Marker(
        location=center_hr,
        icon=folium.Icon(color="lightblue", icon="flag"),
        tooltip=f"Center of {hr:02d}:00 layer",
    ).add_to(fg)

    for idx, row in df_hr.iterrows():
        color = get_color(row.get("misplacement_smoothed"))
        fwd_url = row.get("fwd_path")
        has_fwd = pd.notna(fwd_url) and str(fwd_url).strip() != ""

        sv_url = street_view_url(row["lat"], row["lon"])
        img_html = (
            f"<div style='margin-top:6px'>"
            f"  <img src='{fwd_url}' style='width:100%;max-height:{IMG_MAX_H}px;object-fit:contain;"
            f"  border:1px solid #ccc;border-radius:6px' loading='lazy'/>"
            f"</div>"
            if has_fwd else ""
        )
        rail_incl = row.get("rail_incl_smoothed")
        mispl     = row.get("misplacement_smoothed")
        pole_incl = row.get("pole_incl_right")

        rail_txt = f"{rail_incl:.0f}°" if pd.notna(rail_incl) else "—"
        misp_txt = f"{mispl:.2f}" if pd.notna(mispl) else "—"
        pole_txt = f"{pole_incl:.2f}" if pd.notna(pole_incl) else "—"

        popup_html = (
            f"<div style='font-size:18px; line-height:1.35;'>"
            f"  <div><strong>Pole id:</strong> {row.get('pole_id')}</div>"
            f"  <div><strong>Segment_id:</strong> {row.get('segment_id')}</div>"
            f"  <div><strong>Index:</strong> {idx}</div>"
            f"  <div><strong>Rail inclination:</strong> {rail_txt}</div>"
            f"  <div><strong>Misplacement:</strong> {misp_txt}</div>"
            f"  <div><strong>Pole incl right:</strong> {pole_txt}</div>"
            f"  <div style='margin-top:6px;'><a href='{sv_url}' target='_blank' style='font-weight:600;'>Street View</a></div>"
            f"  {img_html}"
            f"</div>"
        )


        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=3,
            fill=True,
            color=color,
            fill_opacity=0.4,
            popup=folium.Popup(popup_html, max_width=POPUP_W, min_width=POPUP_W),
        ).add_to(fg)

    fg.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

st_folium(m, height=700, use_container_width=True)


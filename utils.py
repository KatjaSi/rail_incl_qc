import re

import pandas as pd
from branca.element import MacroElement, Template


def street_view_url(lat, lon, heading=0, pitch=0, fov=90):
    return (
        f"https://www.google.com/maps/@?api=1&map_action=pano"
        f"&viewpoint={lat},{lon}&heading={heading}&pitch={pitch}&fov={fov}"
    )


def get_color(val: float) -> str:
    if pd.isna(val):
        return "gray"

    abs_val = abs(val)

    if abs_val < 0.07:
        return "green"

    if val >= 0:
        if abs_val < 0.095:
            return "yellow"
        elif abs_val > 0.15:
            return "red"
        else:
            return "orange"
    else:
        if abs_val < 0.1:
            return "lightblue"  # e.g., "#ADD8E6"
        elif abs_val > 0.15:
            return "purple"  # e.g., "#800080"
        else:
            return "blue"  # e.g., "#0000FF"

def hex_to_rgb_list(c: str):
    """Accepts CSS color names (e.g. 'green'), #RRGGBB / #RGB hex, or 'rgb(r,g,b)'.
    Returns [R, G, B]. Falls back to gray."""
    NAMED = {
        "gray": [128, 128, 128],
        "green": [0, 128, 0],
        "yellow": [255, 255, 0],
        "orange": [255, 165, 0],
        "lightblue": [173, 216, 230],
        "purple": [128, 0, 128],
        "blue": [0, 0, 255],
        "red": [255, 0, 0],
        "black": [0, 0, 0],
        "white": [255, 255, 255],
    }

    # handle NaN / None
    try:
        if c is None or (isinstance(c, float) and pd.isna(c)):
            return NAMED["gray"]
    except Exception:
        pass

    s = str(c).strip().lower()
    if not s:
        return NAMED["gray"]

    # CSS named color
    if s in NAMED:
        return NAMED[s]

    # rgb(r,g,b)
    m = re.match(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", s)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        clamp = lambda x: max(0, min(255, x))
        return [clamp(r), clamp(g), clamp(b)]

    # hex #RGB or #RRGGBB
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)  # expand #abc -> #aabbcc
    if len(s) == 6:
        try:
            return [int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)]
        except Exception:
            pass

    # fallback
    return NAMED["gray"]


def add_misplacement_legend(m) -> None:
    template = """
    {% macro html(this, kwargs) %}
    <div style="
        position: fixed; bottom: 20px; left: 20px; z-index:9999;
        background: white; padding: 10px 12px;
        border: 1px solid #999; border-radius: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        font-size: 12px; line-height: 1.2;">
      <div style="font-weight:600; margin-bottom:6px;">Misplacement color key (m)</div>

      <div><span style="display:inline-block;width:12px;height:12px;background:green;border:1px solid #333;margin-right:6px;"></span>|m| &lt; 0.07</div>

      <div style="font-weight:600; margin-top:6px;">Positive (m &gt; 0)</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:yellow;border:1px solid #333;margin-right:6px;"></span>0.07 ≤ m &lt; 0.10</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:orange;border:1px solid #333;margin-right:6px;"></span>0.10 ≤ m ≤ 0.15</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:red;border:1px solid #333;margin-right:6px;"></span>m &gt; 0.15</div>

      <div style="font-weight:600; margin-top:6px;">Negative (m &lt; 0)</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:lightblue;border:1px solid #333;margin-right:6px;"></span>-0.10 &lt; m ≤ -0.07</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:blue;border:1px solid #333;margin-right:6px;"></span>-0.15 ≤ m ≤ -0.10</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:purple;border:1px solid #333;margin-right:6px;"></span>m &lt; -0.15</div>
    </div>
    {% endmacro %}
    """
    macro = MacroElement()
    macro._template = Template(template)
    m.get_root().add_child(macro)


def get_img_path(row: pd.Series, camera: str = "FWD", rig: str = "rig-front-uf") -> str:
    camera_filed = f"{camera}_HUSE"
    img_path = f"http://10.10.10.100:8173//{camera}/{rig}/{row['ts'].strftime('%Y/%m/%d/%H')}/{row[camera_filed]}"
    return img_path

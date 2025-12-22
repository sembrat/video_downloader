
import re
import math
import pandas as pd
import numpy as np
from urllib.parse import urlparse


print("STEP 1 =========== IMPORTING DATA SET")
# ------------- 0) Load -------------
# Use openpyxl for .xlsx files
df = pd.read_excel("scenes.xlsx", engine="openpyxl")

# ------------- 1) Basic normalization -------------
# Rename for consistent downstream usage
df = df.rename(columns={
    "Domain": "homepage_id_original",
    "Scene #": "scene_order",
    "Length": "length_str"
})

# scene_order as integer
df["scene_order"] = pd.to_numeric(df["scene_order"], errors="coerce").astype("Int64")

# Parse "HH:MM:SS" or "HH:MM:SS.ff" and variants into seconds (float)
_time_rx = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[.:](?P<f>\d{1,3}))?$")
def parse_time_to_seconds(s: str) -> float:
    if pd.isna(s):
        return math.nan
    s = str(s).strip()
    m = _time_rx.match(s)
    if not m:
        # Fallback: try MM:SS or plain seconds
        parts = s.replace(".", ":").split(":")
        try:
            if len(parts) == 3:
                h, m_, s_ = map(float, parts)
                return h*3600 + m_*60 + s_
            elif len(parts) == 2:
                m_, s_ = map(float, parts)
                return m_*60 + s_
            else:
                return float(parts[0])
        except:
            return math.nan
    h = float(m.group("h"))
    mi = float(m.group("m"))
    se = float(m.group("s"))
    f = m.group("f")
    frac = 0.0 if f is None else float(f) / (1000.0 if len(f) == 3 else 100.0)
    return h*3600 + mi*60 + se + frac

df["duration_seconds"] = df["length_str"].apply(parse_time_to_seconds)

# ------------- 2) Label mapping (your table) -------------
label_to_code = {
    "code_academics_legacy": "code_academics_legacy",
    "code_campus": "code_campus",
    "code_management": "code_management",
    "code_international": "code_international",
    "code_innovation": "code_innovation",
    "code_social": "code_social",
    "code_finearts": "code_finearts",
    "code_athletics": "code_athletics",
    "code_student": "code_student",
    "code_value": "code_value",
    "code_other": "code_other",
    "code_advertisement": "code_advertisement",
    "code_brand": "code_brand",
    "code_industry": "code_industry",
    "code_atmosphere": "code_atmosphere",
    "code_academics": "code_academics",
    "code_teaching": "code_teaching",
    "code_research": "code_research",
    "code_location": "code_location",
    "code_story": "code_story",
}
code_cols = sorted(set(label_to_code.values()))

# Helpers to sanitize and split label strings
def normalize_label(lbl: str) -> str:
    if pd.isna(lbl):
        return None
    # remove leading/trailing quotes and whitespace
    x = str(lbl).strip().strip('"').strip("'")
    # collapse interior whitespace
    x = re.sub(r"\s+", " ", x)
    return x

def parse_labels(cell) -> list[str]:
    if pd.isna(cell):
        return []
    # split on commas and strip quotes/whitespace for each token
    tokens = [normalize_label(t) for t in str(cell).split(",")]
    return [t for t in tokens if t]  # drop empties

# ------------- 3) Build multi-hot code columns -------------
df["labels_raw"] = df["Category"].apply(parse_labels)

def map_to_codes(labels: list[str]) -> tuple[list[str], list[str]]:
    codes, unknown = [], []
    for lbl in labels:
        code = label_to_code.get(lbl)
        if code:
            codes.append(code)
        else:
            unknown.append(lbl)
    return sorted(set(codes)), sorted(set(unknown))

mapped = df["labels_raw"].apply(map_to_codes)
df["codes_list"] = mapped.apply(lambda t: t[0])
df["unknown_labels"] = mapped.apply(lambda t: t[1])

# Wide binary matrix via explosion + pivot (fast for large data)
long = (df[["homepage_id_original", "scene_order", "codes_list"]]
        .explode("codes_list")
        .dropna(subset=["codes_list"]))

wide = (long
        .assign(val=1)
        .pivot_table(index=long.index, columns="codes_list", values="val",
                     aggfunc="max", fill_value=0)
        .reset_index(drop=True))

# Ensure every code column exists even if absent in the current sheet
for c in code_cols:
    if c not in wide.columns:
        wide[c] = 0

# Align and merge back with the main df (index alignment matters)
wide = wide[code_cols]  # ordered
df = pd.concat([df.reset_index(drop=True), wide], axis=1)

# ------------- 4) Quick quality checks -------------
# Which labels didn’t map?
unknown_counts = (df["unknown_labels"]
                  .explode().dropna()
                  .value_counts().sort_values(ascending=False))
print("\nUNMAPPED LABELS (top 20):\n", unknown_counts.head(20))

# Summary prevalence of each code
prevalence = df[code_cols].mean().sort_values(ascending=False)
print("\nCODE PREVALENCE (share of scenes):\n", prevalence.head(20))



# Final columns you’ll use downstream
print("\nFinal df columns head:\n", df.columns.tolist()[:20])


# 1) Load IPEDS HD (adjust path)
hd = pd.read_csv("resource/hd2023.csv", engine='python', encoding="utf-8")  # CONTROL, SECTOR, OBEREG, ICLEVEL, LOCALE, CARNEGIEIC, INSTSIZE, plus URLs

# 2) Normalize the IPEDS homepage host (strip scheme/path/port)
def host_only(url):
    if pd.isna(url): return None
    s = str(url).strip()
    if s.startswith("//"): s = "http:" + s
    elif "://" not in s:   s = "http://" + s
    p = urlparse(s)
    host = (p.netloc or p.path).split("@")[-1].split(":",1)[0].lower().rstrip(".")
    for pref in ("www.", "m.", "amp."):  # align with your normalization
        if host.startswith(pref): host = host[len(pref):]
    return host.split("/",1)[0]
hd["homepage_id_norm"] = hd["WEBADDR"].apply(host_only)  # adjust column name if different

# 3) Join onto your df (which already has homepage_id normalized)
df["homepage_id_norm"] = df["homepage_id_original"].apply(host_only)
df_ipeds = df.merge(hd[["homepage_id_norm","CONTROL","SECTOR","OBEREG","ICLEVEL","LOCALE","CARNEGIE","INSTSIZE"]],
                    on="homepage_id_norm", how="left")

# 4) Cross-tabs: prevalence by strata (example CONTROL × code)
by_control = df_ipeds.groupby("CONTROL")[code_cols].mean()
by_sector  = df_ipeds.groupby("SECTOR")[code_cols].mean()
by_region  = df_ipeds.groupby("OBEREG")[code_cols].mean()
by_locale  = df_ipeds.groupby("LOCALE")[code_cols].mean()

by_control.to_csv("ipeds_control_prevalence.csv")
by_sector.to_csv("ipeds_sector_prevalence.csv")
by_region.to_csv("ipeds_region_prevalence.csv")
by_locale.to_csv("ipeds_locale_prevalence.csv")

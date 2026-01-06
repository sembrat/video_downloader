
import pandas as pd
import numpy as np
import re
from pathlib import Path

# -------- Config --------
INPUT_XLSX = Path("scenes.xlsx")
OUT_CATEGORY_PHASE = Path("scene_category_phase.csv")
OUT_INSTITUTION_PHASE = Path("scene_institution_phase.csv")
OUT_SCENE_DETAIL = Path("scene_detail_tagged_phased.csv")
OUT_INST_CAT_PHASE = Path("scene_institution_category_phase.csv")

# -------- Load --------
df = pd.read_excel(INPUT_XLSX, engine="openpyxl")
df.columns = [str(c).strip() for c in df.columns]

# Column detection (robust to slight naming drift)
col_domain   = next((c for c in df.columns if c.lower() in ["domain","institution","school","site"]), None)
col_len      = next((c for c in df.columns if "length" in c.lower()), None)
col_scene    = next((c for c in df.columns if "scene" in c.lower()), None)
col_category = next((c for c in df.columns if c.lower() == "category"), None) \
               or next((c for c in df.columns if c.lower() == "comment"), None)

if not col_domain or not col_scene or not col_category:
    raise ValueError(f"Missing required columns: domain={col_domain}, scene={col_scene}, category={col_category}")

work = df[[c for c in [col_domain, col_scene, col_len, col_category] if c]].copy()
work.rename(columns={col_domain: "institution",
                     col_scene: "scene_number",
                     col_len: "length_str",
                     col_category: "codes_raw"}, inplace=True)

# -------- Clean scene number & ordering --------
work["scene_number_num"] = pd.to_numeric(work["scene_number"], errors="coerce")
work["row_order"] = np.arange(len(work))  # fallback order in case numbers are missing

# Time parser → seconds
def parse_time_to_seconds(s):
    if pd.isna(s): return np.nan
    s = str(s).strip().replace(",", ":")
    parts = re.split(r"[^0-9]+", s)
    parts = [p for p in parts if p != ""]
    if not parts: return np.nan
    nums = list(map(int, parts))
    if len(nums) == 1:
        return float(nums[0])
    elif len(nums) == 2:
        mm, ss = nums
        return mm*60 + ss
    else:
        hh, mm, ss = nums[:3]
        return hh*3600 + mm*60 + ss

work["length_seconds"] = work.get("length_str", pd.Series(index=work.index)).apply(parse_time_to_seconds)

# -------- Split & normalize codes --------
work["codes_raw"] = work["codes_raw"].astype(str).str.replace('"', '', regex=False).str.strip()
work["code_list"] = work["codes_raw"].str.split(r"\s*,\s*")

exploded = work.explode("code_list").rename(columns={"code_list": "code"})
exploded["code"] = exploded["code"].astype(str).str.strip()

# keep tokens resembling tags: code_* OR short alnum/underscore
mask_taglike = exploded["code"].str.match(r"(?i)code_[a-z0-9_]+") | exploded["code"].str.match(r"^[a-z][a-z0-9_]+$")
exploded = exploded[mask_taglike].copy()

# drop spurious placeholders
bad = {"nan", "none", "null", ""}
exploded = exploded[~exploded["code"].str.lower().isin(bad)].copy()

# -------- Order & phase within institution --------
# Prefer numeric Scene #, fallback to row_order
exploded["order_key"] = exploded.groupby("institution")["scene_number_num"].rank(method="first")
nan_mask = exploded["scene_number_num"].isna()
exploded.loc[nan_mask, "order_key"] = exploded[nan_mask].groupby("institution")["row_order"].rank(method="first")

exploded["inst_total"] = exploded.groupby("institution")["order_key"].transform("max")
exploded["position_pct"] = (exploded["order_key"] / exploded["inst_total"]).astype(float)

def assign_phase(row):
    n = int(row["inst_total"]) if not pd.isna(row["inst_total"]) else 0
    pos = float(row["position_pct"]) if not pd.isna(row["position_pct"]) else np.nan
    if n <= 1:
        return "early"
    elif n == 2:
        return "early" if row["order_key"] == 1 else "middle"
    else:
        if pos <= 1/3 + 1e-9:   return "early"
        elif pos <= 2/3 + 1e-9: return "middle"
        else:                   return "late"

exploded["phase"] = exploded.apply(assign_phase, axis=1)

# -------- Aggregations --------
cat_phase = (exploded
             .groupby(["code","phase"], as_index=False)
             .size().rename(columns={"size":"count"}))
cat_tot = cat_phase.groupby("code")["count"].transform("sum")
cat_phase["pct_within_code"] = (cat_phase["count"] / cat_tot).round(4)

inst_phase = (exploded
              .groupby(["institution","phase"], as_index=False)
              .size().rename(columns={"size":"count"}))
inst_tot = inst_phase.groupby("institution")["count"].transform("sum")
inst_phase["pct_within_institution"] = (inst_phase["count"] / inst_tot).round(4)

scene_detail = exploded[["institution","scene_number","scene_number_num","length_seconds","code","phase"]].copy()

inst_cat_phase = (exploded
                  .groupby(["institution","code","phase"], as_index=False)
                  .size().rename(columns={"size":"count"}))

# -------- Save --------
cat_phase.to_csv(OUT_CATEGORY_PHASE, index=False)
inst_phase.to_csv(OUT_INSTITUTION_PHASE, index=False)
scene_detail.to_csv(OUT_SCENE_DETAIL, index=False)
inst_cat_phase.to_csv(OUT_INST_CAT_PHASE, index=False)

# Optional: print a short synopsis to console
early_codes = (cat_phase.pivot(index="code", columns="phase", values="pct_within_code")
               .fillna(0).sort_values(by="early", ascending=False)).head(10)
early_insts = (inst_phase.pivot(index="institution", columns="phase", values="pct_within_institution")
               .fillna(0).sort_values(by="early", ascending=False)).head(10)
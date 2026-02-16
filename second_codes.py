import pandas as pd
import numpy as np
import re
from datetime import datetime
from urllib.parse import urlparse

# ----------------------------
# Helpers
# ----------------------------
def extract_domain(x):
    """Normalize to a bare domain like 'example.edu' from either a domain or URL."""
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    if not s:
        return np.nan

    # Already looks like a domain
    if re.match(r'^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', s) and ' ' not in s and '/' not in s:
        host = s
    else:
        # urlparse needs a scheme to reliably parse hostnames
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', s):
            s = "http://" + s
        try:
            host = urlparse(s).hostname
        except Exception:
            host = None

    if not host:
        return np.nan
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host

def make_key(df, cols):
    """Create a stratum key from a list of columns."""
    if not cols:
        return pd.Series(["ALL"] * len(df), index=df.index)
    return df[cols].fillna("NA").astype(str).agg("|".join, axis=1)

# ----------------------------
# Configuration
# ----------------------------
SCENES_XLSX = "scenes_complete.xlsx"
IPEDS_CSV   = "resource/hd2024.csv"
SEED = 42
SAMPLE_RATE = 0.10  # 10%

# Which IPEDS columns to use for representativeness (if present)
# (These exist in standard IPEDS HD files; script auto-falls back if some are missing.)
PREFERRED_STRATA_COLS = ["SECTOR", "ICLEVEL", "CONTROL", "OBEREG"]

# ----------------------------
# Load scenes workbook (all sheets)
# ----------------------------
xls = pd.ExcelFile(SCENES_XLSX, engine="openpyxl")
sheets = {name: pd.read_excel(SCENES_XLSX, sheet_name=name, engine="openpyxl")
          for name in xls.sheet_names}

# Identify main sheet (prefer one containing 'Domain' column)
main_sheet_name = None
for name, df in sheets.items():
    if any(str(c).strip().lower() == "domain" for c in df.columns):
        main_sheet_name = name
        break
if main_sheet_name is None:
    main_sheet_name = xls.sheet_names[0]

scenes_df = sheets[main_sheet_name].copy()

# Locate domain column
domain_col = None
for c in scenes_df.columns:
    if str(c).strip().lower() == "domain":
        domain_col = c
        break
if domain_col is None:
    # fallback: look for anything URL-ish
    url_like = [c for c in scenes_df.columns if re.search(r"url|web|site|domain", str(c), re.I)]
    domain_col = url_like[0] if url_like else None
if domain_col is None:
    raise ValueError("Could not find a Domain/URL column in scenes_complete.xlsx")

scenes_df["_domain"] = scenes_df[domain_col].apply(extract_domain)

# ----------------------------
# Load IPEDS HD file and build domain->stratum mapping
# ----------------------------
hd = pd.read_csv(IPEDS_CSV, dtype=str, low_memory=False)

# Locate website column (standard is WEBADDR)
web_col = "WEBADDR" if "WEBADDR" in hd.columns else None
if web_col is None:
    for c in hd.columns:
        if str(c).strip().lower() in ("webaddr", "web", "website", "url"):
            web_col = c
            break
if web_col is None:
    raise ValueError("Could not find WEBADDR (website) column in hd2024.csv")

hd["_domain"] = hd[web_col].apply(extract_domain)

# Determine which strata columns exist
strata_cols = [c for c in PREFERRED_STRATA_COLS if c in hd.columns]
hd["_stratum"] = make_key(hd, strata_cols)

# Map each domain to a stratum (first match per domain)
hd_map = hd.dropna(subset=["_domain"]).drop_duplicates(subset=["_domain"])
domain_to_stratum = hd_map.set_index("_domain")["_stratum"]

# Attach stratum to scenes; keep UNKNOWN when no match
scenes_df["_stratum"] = scenes_df["_domain"].map(domain_to_stratum).fillna("UNKNOWN")

# ----------------------------
# Compute representative 10% sample
# ----------------------------
N = len(scenes_df)
sample_n = int(np.ceil(SAMPLE_RATE * N)) if N else 0

# National shares by stratum (IPEDS)
nat_counts = hd["_stratum"].value_counts(dropna=True)

present_strata = scenes_df["_stratum"].value_counts().index.tolist()
present_non_unknown = [s for s in present_strata if s != "UNKNOWN"]

# Use national shares restricted to strata present in scenes
if present_non_unknown:
    nat_present = nat_counts.reindex(present_non_unknown).fillna(0)
    if nat_present.sum() > 0:
        nat_shares = nat_present / nat_present.sum()
    else:
        # fallback to dataset distribution (excluding UNKNOWN)
        ds_counts = scenes_df.loc[scenes_df["_stratum"] != "UNKNOWN", "_stratum"].value_counts()
        nat_shares = ds_counts / ds_counts.sum()
else:
    nat_shares = pd.Series(dtype=float)

# Allocate counts per stratum (integer, total == sample_n)
alloc = {}
remaining = sample_n

if sample_n > 0 and len(nat_shares) > 0:
    float_targets = nat_shares * sample_n
    base = np.floor(float_targets).astype(int)

    avail = scenes_df["_stratum"].value_counts()
    base = base.clip(upper=avail.reindex(base.index).fillna(0).astype(int))

    alloc = base.to_dict()
    remaining = sample_n - int(base.sum())

    remainders = (float_targets - base).sort_values(ascending=False)
    for stratum in remainders.index:
        if remaining <= 0:
            break
        if alloc.get(stratum, 0) < int(avail.get(stratum, 0)):
            alloc[stratum] = alloc.get(stratum, 0) + 1
            remaining -= 1

# If still short, fill from UNKNOWN then any stratum with remaining capacity
if remaining > 0:
    avail = scenes_df["_stratum"].value_counts()
    capacity = {s: int(avail[s]) - int(alloc.get(s, 0)) for s in avail.index}

    order = []
    if "UNKNOWN" in capacity and capacity["UNKNOWN"] > 0:
        order.append("UNKNOWN")
    order += [s for s, _ in sorted([(s, c) for s, c in capacity.items() if s != "UNKNOWN"],
                                   key=lambda x: x[1], reverse=True)]
    for s in order:
        if remaining <= 0:
            break
        take = min(capacity.get(s, 0), remaining)
        if take > 0:
            alloc[s] = alloc.get(s, 0) + take
            remaining -= take

# Sample rows per stratum
selected_idx = []
for stratum, n_take in alloc.items():
    if n_take <= 0:
        continue
    subset = scenes_df[scenes_df["_stratum"] == stratum]
    if len(subset) == 0:
        continue
    sampled = subset.sample(n=min(n_take, len(subset)), random_state=SEED)
    selected_idx.extend(sampled.index.tolist())

# Ensure exact count
selected_idx = list(dict.fromkeys(selected_idx))
if len(selected_idx) > sample_n:
    selected_idx = selected_idx[:sample_n]
elif len(selected_idx) < sample_n:
    extra_n = sample_n - len(selected_idx)
    remaining_idx = scenes_df.index.difference(selected_idx)
    if extra_n > 0 and len(remaining_idx) > 0:
        extra = scenes_df.loc[remaining_idx].sample(n=min(extra_n, len(remaining_idx)), random_state=SEED)
        selected_idx.extend(extra.index.tolist())

# Add the boolean column
scenes_df["Second Coder"] = False
scenes_df.loc[selected_idx, "Second Coder"] = True

# ----------------------------
# Write output workbook with timestamp
# ----------------------------
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out_path = f"scenes_complete_secondcoder_{stamp}.xlsx"

# Replace the main sheet, keep others unchanged
sheets_out = sheets.copy()
sheets_out[main_sheet_name] = scenes_df.drop(columns=["_domain", "_stratum"], errors="ignore")

with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
    for name, df in sheets_out.items():
        df.to_excel(writer, sheet_name=name[:31], index=False)

print(f"Created: {out_path}")
print(f"Main sheet modified: {main_sheet_name}")
print(f"Rows: {N} | Second Coder=True: {int(scenes_df['Second Coder'].sum())} ({SAMPLE_RATE:.0%} target)")
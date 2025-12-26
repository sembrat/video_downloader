
import re
import math
import pandas as pd
import numpy as np
from urllib.parse import urlparse
from math import sqrt
from scipy.stats import chi2_contingency

# ------------- DEFINITIONS ---------------------
# Normalize the IPEDS homepage host (strip scheme/path/port)
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
df["homepage_id_norm"] = df["homepage_id_original"].apply(host_only)

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
long = (df[["homepage_id_norm", "scene_order", "codes_list"]]
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

print("STEP 1 =========== CORRELATING DATA SET WITH IPEDS")
# 1) Load IPEDS HD (adjust path)
hd = pd.read_csv("resource/hd2023.csv", engine='python', encoding="utf-8")  # CONTROL, SECTOR, OBEREG, ICLEVEL, LOCALE, CARNEGIEIC, INSTSIZE, plus URLs

hd["homepage_id_norm"] = hd["WEBADDR"].apply(host_only)  # adjust column name if different
df_ipeds = df.merge(hd[["homepage_id_norm","CONTROL","SECTOR","OBEREG","ICLEVEL","LOCALE","CARNEGIE","INSTSIZE"]],
                    on="homepage_id_norm", how="left")

# 4) Cross-tabs: prevalence by strata (example CONTROL × code)
by_control = df_ipeds.groupby("CONTROL")[code_cols].mean()
by_sector  = df_ipeds.groupby("SECTOR")[code_cols].mean()
by_region  = df_ipeds.groupby("OBEREG")[code_cols].mean()
by_locale  = df_ipeds.groupby("LOCALE")[code_cols].mean()

by_control.to_csv("analysis/output/ipeds_control_prevalence.csv")
by_sector.to_csv("analysis/output/ipeds_sector_prevalence.csv")
by_region.to_csv("analysis/output/ipeds_region_prevalence.csv")
by_locale.to_csv("analysis/output/ipeds_locale_prevalence.csv")

print("STEP 3 =========== CHI SQUARE")

def chisq_code_vs_stratum(df_ipeds, code_cols, stratum_col):
    """Run chi-square tests of independence for each code_* vs an IPEDS stratum."""
    results = []
    # only keep rows with a non-null stratum value
    sub = df_ipeds.dropna(subset=[stratum_col])
    for code in code_cols:
        # Build contingency: rows=stratum categories, cols={0,1} absent/present
        ct = pd.crosstab(sub[stratum_col], sub[code])
        if ct.shape[1] < 2:  # if no variability in the code column
            continue
        chi2, p, dof, expected = chi2_contingency(ct)
        results.append({
            "code": code,
            "stratum": stratum_col,
            "chi2": chi2,
            "p_value": p,
            "dof": dof,
            "n": int(ct.sum().sum())
        })
    return pd.DataFrame(results).sort_values("p_value")


tests_control = chisq_code_vs_stratum(df_ipeds, code_cols, "CONTROL")
tests_sector  = chisq_code_vs_stratum(df_ipeds, code_cols, "SECTOR")
tests_locale  = chisq_code_vs_stratum(df_ipeds, code_cols, "LOCALE")
tests_carnegie = chisq_code_vs_stratum(df_ipeds, code_cols, "CARNEGIE")

# Save results
tests_control.to_csv("analysis/output/chisq_codes_vs_CONTROL.csv", index=False)
tests_sector.to_csv("analysis/output/chisq_codes_vs_SECTOR.csv", index=False)
tests_locale.to_csv("analysis/output/chisq_codes_vs_LOCALE.csv", index=False)
tests_carnegie.to_csv("analysis/output/chisq_codes_vs_CARNEGIE.csv", index=False)


print("STEP 4 =========== CARNEGIE: EFFECT SIZES, MULTIPLE TESTS, RESIDUALS")

# --- Helpers ---
def cramer_v_from_chi2(chi2: float, n: int, k: int = 2) -> float:
    """Cramér's V for binary vs multi-category contingency.
    k = min(rows, cols). With binary columns, k = 2.
    """
    if n <= 0 or (k - 1) <= 0:
        return float('nan')
    return float(np.sqrt(chi2 / (n * (k - 1))))


def p_adjust_bh(pvals: pd.Series) -> pd.Series:
    """Benjamini–Hochberg FDR correction. Returns q-values aligned to pvals index."""
    p = np.asarray(pvals, dtype=float)
    n = p.size
    order = np.argsort(p)
    ranked = np.empty(n)
    ranked[order] = np.arange(1, n + 1)
    q = p * n / ranked
    # enforce monotonicity of q-values when sorted by p
    q_sorted = q[order]
    q_sorted = np.minimum.accumulate(q_sorted[::-1])[::-1]
    q_final = np.empty(n)
    q_final[order] = q_sorted
    return pd.Series(np.minimum(q_final, 1.0), index=pvals.index)


# --- 4A. Augment chi-square results for CARNEGIE with Cramér's V and BH q-values ---
if 'tests_carnegie' in globals():
    df_c = tests_carnegie.copy()
    # Cramér's V (binary vs multi-category => k=2)
    df_c['cramers_v'] = df_c.apply(lambda r: cramer_v_from_chi2(r['chi2'], int(r['n']), 2), axis=1)
    # Benjamini–Hochberg q-values
    df_c['q_value_BH'] = p_adjust_bh(df_c['p_value'])
    # Order by effect size
    df_c = df_c.sort_values(['cramers_v', 'p_value'], ascending=[False, True])
    df_c.to_csv('analysis/output/carnegie_chisq_effects.csv', index=False)
    print("Saved: analysis/output/carnegie_chisq_effects.csv (with Cramér's V and BH q-values)")
else:
    print("WARN: tests_carnegie not found; run STEP 3 chi-square first.")


# --- 4B. Per-category standardized residuals (which Carnegie classes over/under-index) ---
# Prefer readable Carnegie labels if present; else fall back to numeric codes
carnegie_label_col = None
for cand in ['C21BASIC_name', 'CARNEGIE_name', 'CARNEGIE', 'C21BASIC']:
    if 'df_ipeds' in globals() and cand in df_ipeds.columns:
        carnegie_label_col = cand
        break

if 'df_ipeds' in globals() and carnegie_label_col is not None:
    sub = df_ipeds.dropna(subset=[carnegie_label_col])
    residual_rows = []
    for code in [c for c in code_cols if c in sub.columns]:
        ct = pd.crosstab(sub[carnegie_label_col], sub[code])
        # ensure we have both 0 and 1 columns
        if ct.shape[1] < 2:
            # add missing column with zeros
            for val in [0, 1]:
                if val not in ct.columns:
                    ct[val] = 0
            ct = ct[[0, 1]]
        chi2, p, dof, expected = chi2_contingency(ct)
        # standardized residuals: (O - E) / sqrt(E)
        std_resid = (ct - expected) / np.sqrt(expected)
        # Focus on presence column (1) for over-/under-indexing of the code
        if 1 in std_resid.columns:
            sr1 = std_resid[1].rename('std_resid_present')
            for cat, val in sr1.items():
                residual_rows.append({
                    'code': code,
                    'carnegie_category': cat,
                    'std_resid_present': float(val),
                    'chi2': float(chi2),
                    'p_value': float(p),
                    'n': int(ct.values.sum())
                })
    residuals_long = pd.DataFrame(residual_rows)
    residuals_long.to_csv('analysis/output/carnegie_residuals_long.csv', index=False)
    print("Saved: analysis/output/carnegie_residuals_long.csv (standardized residuals for presence)")

    # Top-k by category (over-index: highest positive residuals)
    TOP_K = 5
    top_by_cat = (residuals_long
                  .sort_values(['carnegie_category', 'std_resid_present'], ascending=[True, False])
                  .groupby('carnegie_category', as_index=False)
                  .head(TOP_K))
    top_by_cat.to_csv('analysis/output/visual_signature_top5_by_CARNEGIE.csv', index=False)
    print("Saved: analysis/output/visual_signature_top5_by_CARNEGIE.csv (top {} codes per Carnegie)".format(TOP_K))
else:
    print("WARN: df_ipeds or a Carnegie label column not available; cannot compute per-category residuals.")


# --- 4C. Convenience: pretty print top global signals ---
if 'df_c' in globals():
    print("Top 10 codes by Cramér's V (global association with CARNEGIE):")
    try:
        display_cols = ['code', 'chi2', 'cramers_v', 'p_value', 'q_value_BH', 'dof', 'n']
        print(df_c[display_cols].head(10).to_string(index=False))
    except Exception:
        print(df_c.head(10).to_string(index=False))


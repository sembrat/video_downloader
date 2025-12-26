
import pandas as pd
import re
from pathlib import Path

# Load
df = pd.read_excel('scenes.xlsx', engine='openpyxl')

# Normalize col names
df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]

FPS = 30.0
def parse_duration_to_seconds(x):
    if pd.isna(x): return None
    s = str(x).strip().replace('\u200b','')
    # Plain numeric seconds
    if re.fullmatch(r"\d+(\.\d+)?", s): return float(s)
    # HH:MM:SS:FF (frames)
    m = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}):(\d{1,3})", s)
    if m:
        hh, mm, ss, ff = m.groups()
        return int(hh)*3600 + int(mm)*60 + int(ss) + int(ff)/FPS
    # HH:MM:SS(.fraction)
    m = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?", s)
    if m:
        hh, mm, ss, frac = m.groups()
        base = int(hh)*3600 + int(mm)*60 + int(ss)
        if frac is None: return base
        return base + (int(frac)/ (10 if len(frac)==1 else 100 if len(frac)==2 else 1000))
    # Fallback to pandas
    if ':' in s:
        try:
            return pd.to_timedelta(s).total_seconds()
        except Exception:
            return None
    return None

# Identify critical columns
domain_col = next((c for c in df.columns if df[c].astype(str).str.contains(r"\.edu\b", na=False).any()), None)
length_col = next((c for c in df.columns if str(c).lower().strip() in ['length','duration','time']), None)
if length_col is None:
    length_col = next((c for c in df.columns
                       if df[c].astype(str).str.match(r"\d{2}:\d{2}:\d{2}(:\d{1,3}|\.\d{1,3})?").sum() > 10), None)
category_code_col = next((c for c in df.columns if df[c].astype(str).str.contains(r"^code_", na=False).sum() > 20), None)

# Compute seconds
df['duration_seconds'] = df[length_col].apply(parse_duration_to_seconds)
df = df.dropna(subset=['duration_seconds'])

# Aggregations
by_cat = (df.groupby(category_code_col, dropna=False)
          .agg(total_seconds=('duration_seconds','sum'),
               scene_count=('duration_seconds','size'),
               avg_seconds=('duration_seconds','mean'))
          .sort_values('total_seconds', ascending=False))
by_inst = (df.groupby(domain_col)
          .agg(total_seconds=('duration_seconds','sum'),
               scene_count=('duration_seconds','size'),
               avg_seconds=('duration_seconds','mean'))
          .sort_values('total_seconds', ascending=False))
pivot_inst_cat = pd.pivot_table(df, index=domain_col, columns=category_code_col,
                                values='duration_seconds', aggfunc='sum', fill_value=0.0)

by_cat.to_csv('analysis/output/scene_durations_by_category.csv')
by_inst.to_csv('analysis/output/scene_durations_by_institution.csv')

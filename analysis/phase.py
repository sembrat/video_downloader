
import pandas as pd
import numpy as np
import re

# 1) Read the uploaded Excel file (openpyxl as engine)
df = pd.read_excel('scenes.xlsx', engine='openpyxl')

# 2) Standardize headers
df.columns = [str(c).strip().lower() for c in df.columns]

# 3) Find columns of interest irrespective of exact header text
col_map = {}
for c in df.columns:
    if re.search(r'^domain$', c): col_map['domain'] = c
    elif re.search(r'^length', c): col_map['length'] = c
    elif re.search(r'scene', c):   col_map['scene'] = c
    elif re.search(r'^description$', c): col_map['description'] = c
    elif re.search(r'\bai\s*category\b', c): col_map['ai_category'] = c
    elif re.search(r'^category$', c): col_map['category'] = c
    elif re.search(r'^comment$', c):  col_map['comment'] = c

# 4) Coerce Scene # into a numeric sort key when possible
def parse_scene_number(x):
    if pd.isna(x): return np.nan
    s = str(x).strip()
    if ':' in s and not re.match(r'^\d+(\.\d+)?$', s):  # time-like strings -> ignore
        return np.nan
    m = re.search(r'\d+(?:\.\d+)?', s)
    return float(m.group(0)) if m else np.nan

work = df.copy()
work['domain']    = work[col_map['domain']].astype(str).str.strip()
work['scene_num'] = work[col_map['scene']].apply(parse_scene_number)
work['row_order'] = np.arange(len(work))  # stable fallback order

# 5) Sort within domain by scene_num then row_order; create position counters
work = work.sort_values(['domain','scene_num','row_order'])
work['pos_in_domain']    = work.groupby('domain').cumcount()+1
work['count_in_domain']  = work.groupby('domain')['domain'].transform('count')

# 6) Assign Early/Middle/Late terciles per domain
def assign_phase(row):
    n = int(row['count_in_domain']); i = int(row['pos_in_domain'])
    if n <= 3:  # tiny sequences
        return ['Early','Middle','Late'][i-1]
    early_end  = int(np.ceil(n/3))
    middle_end = int(np.ceil(2*n/3))
    return 'Early' if i <= early_end else ('Middle' if i <= middle_end else 'Late')

work['phase'] = work.apply(assign_phase, axis=1)

# 7) Keep convenient columns for export
for k in ('ai_category','category','length','description'):
    if k in col_map: work[k] = work[col_map[k]].astype(str)
    else:            work[k] = ''

scenes_with_phase = work[['domain','scene_num','pos_in_domain','count_in_domain',
                          'phase','category','ai_category','length','description']].copy()

# 8) Aggregations
phase_by_category = (scenes_with_phase.groupby(['category','phase'], as_index=False)
                     .size()
                     .pivot(index='category', columns='phase', values='size')
                     .fillna(0).astype(int).reset_index())

phase_by_institution = (scenes_with_phase.groupby(['domain','phase'], as_index=False)
                        .size()
                        .pivot(index='domain', columns='phase', values='size')
                        .fillna(0).astype(int).reset_index())

phase_by_inst_cat = (scenes_with_phase.groupby(['domain','category','phase'], as_index=False)
                     .size()
                     .pivot_table(index=['domain','category'], columns='phase', values='size', fill_value=0)
                     .reset_index())

# 9) Write CSVs
scenes_with_phase.to_csv('analysis/output/scenes_with_phase.csv', index=False)
phase_by_category.to_csv('analysis/output/phase_by_category.csv', index=False)
phase_by_institution.to_csv('analysis/output/phase_by_institution.csv', index=False)
phase_by_inst_cat.to_csv('analysis/output/phase_by_institution_category.csv', index=False)

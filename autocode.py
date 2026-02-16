#!/usr/bin/env python3
"""process_scenes_complete_v5.py

PURPOSE
-------
1) Build glue.csv per domain using your "continuation" rule (v4):
   - One row per Excel clip (base)
   - Row format: `base,continuation_ranges` or just `base`
   - Continuation scenes are determined from scene files present on disk.

2) Run an OpenAI-compatible *vision* request per clip row (per Excel row):
   - Passes domain + clip number + (optionally) the continuation range + context
   - Uses a .jpg frame file that already exists on disk (no frame extraction)

ASSUMPTIONS
-----------
- scenes_complete.xlsx has columns: Domain, #, plus optional metadata (Length, Description, Category...).
- For each domain, scene assets exist under:
      results/<domain>/scenes/
  and include BOTH:
      scene_<n>.mp4   (used for existence / gut-check)
      scene_<n>.jpg   (used as the image sent to the LLM)

- Local OpenAI-compatible endpoint is available (default):
      http://localhost:8000/v1/chat/completions

USAGE
-----
python process_scenes_complete_v5.py \
  --input scenes_complete.xlsx \
  --output_dir results \
  --openai_base_url http://localhost:8000/v1 \
  --openai_api_key YOUR_KEY \
  --model your-vision-model

If you don't want to call the LLM (only build glue):
  --no_llm

OUTPUTS
-------
Per domain:
- results/<domain>/glue.csv                  (headerless)
- results/<domain>/clips_analysis.csv        (row-level + LLM output)

Consolidated:
- results/clips_complete_<timestamp>.xlsx

"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from datetime import datetime
from typing import List, Optional, Set, Tuple

import pandas as pd
from openai import OpenAI
import lmstudio as lms
import requests

# --- parsing helpers ---
DOMAIN_RE = re.compile(r"([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})")
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

def parse_domain(val: object) -> str:
    """Extract a domain-like token from a cell value."""
    if pd.isna(val):
        return ""
    s = str(val).strip()
    m = DOMAIN_RE.search(s)
    return m.group(1).lower() if m else s


def safe_folder(name: str) -> str:
    """Make filesystem-safe folder name."""
    name = name.strip()
    name = re.sub(r"[\\/]+", "_", name)
    name = re.sub(r"[:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", "_", name)
    return name


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {c: re.sub(r"\s+", " ", str(c).strip().lower()) for c in df.columns}
    return df.rename(columns=mapping)


def detect_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def compress_ints(nums: List[int]) -> str:
    """Compress sorted ints into comma-separated ranges (e.g., 2-4,6,8)."""
    if not nums:
        return ""
    nums = sorted(set(nums))
    out = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = n
    out.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ",".join(out)


def expand_range_str(rng: str) -> List[int]:
    """Optional utility: expand '2-4,6,8-9' -> [2,3,4,6,8,9]."""
    if not rng:
        return []
    out: List[int] = []
    for part in rng.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            out.extend(list(range(int(a), int(b) + 1)))
        else:
            out.append(int(part))
    return out


# --- filesystem scene helpers ---

def list_existing_scene_numbers(scenes_dir: str, mp4_ext: str = '.mp4', prefix: str = 'scene_') -> List[int]:
    """Return sorted unique scene numbers with existing mp4 files."""
    if not os.path.isdir(scenes_dir):
        return []
    nums: List[int] = []
    for fn in os.listdir(scenes_dir):
        if not fn.lower().startswith(prefix.lower()):
            continue
        if not fn.lower().endswith(mp4_ext.lower()):
            continue
        m = re.search(r"(\d+)", fn)
        if m:
            nums.append(int(m.group(1)))
    return sorted(set(nums))


def continuation_scenes(existing: Set[int], base: int, next_base: Optional[int], max_scene: Optional[int]) -> List[int]:
    """Continuation window: (base+1 .. next_base-1) or (base+1 .. max_scene), filtered by existence."""
    if not existing or max_scene is None:
        return []
    start = base + 1
    end = (next_base - 1) if next_base is not None else max_scene
    if end < start:
        return []
    return [n for n in range(start, end + 1) if n in existing]


def scene_jpg_path(scenes_dir: str, n: int, jpg_ext: str = '.jpg', prefix: str = 'scene_') -> str:
    return os.path.join(scenes_dir, f"{prefix}{n}_screenshot{jpg_ext}")


def choose_image_for_clip(scenes_dir: str, base: int, cont_list: List[int], jpg_ext: str = '.jpg', prefix: str = 'scene_') -> Optional[str]:
    """Preferred image:
    1) scene_<base>.jpg if exists
    2) scene_<first_continuation>.jpg if exists
    3) None
    """
    p = scene_jpg_path(scenes_dir, base, jpg_ext=jpg_ext, prefix=prefix)
    print(f"Looking for image at: {p}")
    if os.path.exists(p):
        return p
    if cont_list:
        p2 = scene_jpg_path(scenes_dir, cont_list[0], jpg_ext=jpg_ext, prefix=prefix)
        if os.path.exists(p2):
            return p2
    return None


def image_file_to_data_url(path: str) -> str:
    """Load image bytes and return data URL suitable for OpenAI image_url."""
    with open(path, 'rb') as f:
        b = f.read()
    b64 = base64.b64encode(b).decode('utf-8')
    # assume jpg
    return f"data:image/jpeg;base64,{b64}"


# --- OpenAI-compatible call ---

def call_openai_vision(
    base_url: str,
    api_key: str,
    model: str,
    domain: str,
    clip_number: int,
    image_path: str,
    prompt_text: str,
    timeout: int = 90,
) -> str:
    """Send a single vision request. Returns string content."""
    url = base_url.rstrip('/') + '/chat/completions'
    headers = {
        'Content-Type': 'application/json',
    }
    # If your local server uses OpenAI-style auth:
    if api_key:
        headers['Authorization'] = f"Bearer {api_key}"

    data_url = image_file_to_data_url(image_path)

    code_examples_text = """CODE_EXAMPLES (codebook) 

                    All codes below are marked in a format like: `code_label :: description`. The description may include example imagery, scene details, or other context to guide coding. All examples are marked in Markdown unordered lists. 
                    
                    Only return the code_label in your output, comma-separated if multiple apply. Do NOT return the descriptions or examples in your output.
    
                    code_campus :: University environment, Campus aesthetics
                    - aerial campus overview (brick buildings, clock/bell tower, tree‑lined walks)
                    - signature landmarks (fountain/statue circled by paths and benches)
                    - historic hall exterior (Gothic facade, arched windows, manicured lawn)
                    - modern student center (glass facade, flag/signage, landscaped entrance)
                    - quad in season (students crossing brick paths under autumn foliage/spring blooms)
                    - library interior (high ceilings, stacks/study tables, skylight)
                    - night stadium district (lit athletics complex with adjacent academic buildings)

                    code_student :: Student life
                    - students on the quad (small study circle on the grass, laptops and notebooks)
                    - friends at picnic table (casual conversation, snacks/laptops, campus backdrop)
                    - walk‑and‑talk between classes (backpacks on brick walkway near academic buildings)
                    - dorm hangout (posed selfies on lofted beds, string lights, posters)
                    - game‑day bleachers (students cheering in school colors at indoor court)
                    - wellness/rec moment (yoga on lawn/fitness ropes in campus gym)
                    - mascot meet‑and‑greet (photos with mascot on field/at campus festival)

                    code_teaching :: Teaching, classroom, training
                    - whiteboard lecture (instructor pointing to equations/diagrams in classroom)
                    - nursing simulation bedside care (students in scrubs practicing on mannequin)
                    - hands‑on workshop (faculty guiding welding/milling/CNC operation)
                    - studio coaching (music/audio mixing console demo in darkened lab)
                    - flight/vehicle simulator (instructor at console, runway or cockpit visuals)
                    - lab walk‑through (pipettes, models, safety goggles, bench instruction)
                    - seminar around the table (laptops open, facilitator leading discussion)

                    code_athletics :: Intercollegiate athletics
                    - players on athletics field (football huddle/tackle under stadium lights)
                    - indoor court action (basketball drives/layups with bleachers)
                    - volleyball at the net (jump spikes/blocks on polished floor)
                    - soccer under the lights (dribble/shot with scoreboard behind)
                    - baseball/softball moment (swing, slide, or dugout celebration)
                    - swim lanes (dive or mid‑stroke in blue pool with markers)
                    - track & field (sprint blocks/hurdles on red or blue track)

                    code_academics :: Academics, studying, group work
                    - library study tables (laptops, open texts, quiet focus)
                    - project huddle (charts/wireframes on whiteboard, small‑group planning)
                    - typing close‑up (hands on keyboard, study nook or reading room)
                    - podium presentation (speaker with projected graphs/data behind)
                    - computing and coding work (students at workstations, multi‑monitor setup)
                    - advising/tutoring (two‑three students with notes and faculty guidance)
                    - discipline-specific visual aid (maps, anatomical models, or legal volumes in frame)

                    code_finearts :: Fine arts
                    - main‑stage performance (orchestra/choir under spotlights with conductor)
                    - dance rehearsal (mirrored studio, leaps/lines, polished floor)
                    - studio art making (pottery wheel/easel painting, tools and clay)
                    - recital solo (violin/sax/acoustic guitar under warm light)
                    - theater scene (costumed actors on set with props and dramatic lighting)
                    - gallery walkthrough (visitors with sculptures/framed works on walls)
                    - jazz combo (brass and rhythm section in dim auditorium)

                    code_research :: Research, laboratory
                    - bench science in action (pipetting, test tubes, microscopes, lab coats)
                    - advanced instrumentation (CNC/robotic arm/server racks under supervision)
                    - field study (stream sampling, greenhouse plants, beekeeping frames)
                    - medical imaging/ultrasound (student analyzing live monitor output)
                    - maker‑research overlap (3D printer prototyping in engineering lab)
                    - drone operations (outdoor test flight with controller and observers)
                    - data review (heatmaps/charts open on large display during analysis)

                    code_value :: Value, Success
                    - commencement procession (rows of caps and gowns entering venue)
                    - on‑stage diploma moment (handshake/hooding with faculty regalia)
                    - cap toss celebration (graduates raising mortarboards outdoors)
                    - family embrace (graduate with relatives post‑ceremony)
                    - regalia detail (tassels, cords, or medals close‑up)
                    - arena panorama (packed seating, banners, stage view)
                    - cohort group photo (diplomas in hand at campus landmark)

                    code_industry :: Employment, work, industry
                    - shop‑floor training (welding sparks/grinder in industrial bay)
                    - ag/land‑grant scene (tractor/combine, students amid rows of crops)
                    - aviation tech (flightline checks/simulator cockpit)
                    - culinary line (chef demo at stainless stations, plated dishes)
                    - automotive service (diagnostics tablet/lifted vehicle)
                    - broadcast/studio ops (control room boards, headsets, cameras)
                    - public service/military (cadet formation/firefighter drills)

                    code_brand :: University brand, brand mark
                    - logo lock‑up (university crest/seal on solid or textured background)
                    - monument signage (large gateway/stone sign with emblem)
                    - mascot branding (costumed character in arena/on quad)
                    - event backdrop (podium seal/banner in ceremony setting)
                    - apparel & merch (bookstore display/branded sweatshirts)
                    - athletics identity (lettered seats/field marks/jerseys)
                    - campaign graphic (school name + tagline over campus imagery)

                    code_advertisement :: Advertisement
                    - rankings overlay (aerial campus with “Top #/Ranked” text)
                    - program promo card (accreditation/outcomes on bold background)
                    - slogan splash (“Transform Your Life Today” over purple campus hue)
                    - open‑day montage (sign + URL + admissions call to action)
                    - sports tournament banner (event logo with date and host)
                    - achievement tile (Carnegie/designation shield in gold)
                    - destination billboard (campus or partner site with apply link)

                    code_location :: Location
                    - region reveal (skyline/capitol dome/coastal harbor beyond campus)
                    - mountains & hills (aerial valley/ridge above the university)
                    - waterfront (sandy beach/kayaks along rocky shoreline)
                    - bridges & rivers (span over waterway, industrial backdrop)
                    - channel (freighter or canal)
                    - winter wildlife (snow‑covered trees, deer near campus edge)
                    - park & trail (wooded paths, benches, stone buildings peeking through)

                    code_social :: Belonging, Ethics, social responsibility
                    - campus celebration (cheering crowd with hands raised outdoors)
                    - cultural flags line‑up (students posing with international flags)
                    - service day (cleanup/garden planting with bags and tools)
                    - faith/chapel gathering (raised hands, choir/ceremony seating)
                    - club‑fair table (branded tablecloth, brochures, flowers)
                    - night social (dancing under string lights/indoor party)
                    - spirit moment (students with mascot with foam fingers)

                    code_innovation :: Innovation
                    - robotics demo (industrial arm/wheeled rover in makerspace)
                    - VR/AR immersion (headset user with simulated content)
                    - 3D printing lab (prototype emerging on build plate)
                    - smart lab walkthrough (advanced instruments, LED lighting, screens)
                    - design ideation (sketching footwear/product with swatches)
                    - esports/tech studio (gaming rigs, team jerseys, stage lighting)
                    - sustainability tech (solar install/hydroponic trays under LEDs)

                    code_atmosphere :: Atmosphere, vibe
                    - indoor/abstract ambience (conceptual light on black, waves)
                    - nature and outdoors (curving forest roadway, river gorge outlook, wildlife)
                    - weather and landscapes (misty mountain valley, open rural highway)

                    code_management :: Management, leadership
                    - leader at podium (address with school seal and flags)
                    - ribbon‑cutting (executives with shovels/scissors under stage lights)
                    - boardroom seminar (suits, slide deck, planning whiteboard)
                    - career/industry mixer (handshakes at booth/hallway meet‑and‑greet)
                    - panel dialogue (dais with mics, auditorium audience)
                    - classroom leadership talk (blazer‑clad speaker with cohort)
                    - official signing (administrator at desk, document close‑up)

                    code_international :: International Projection
                    - flag hall (atrium/stage lined with national flags)
                    - graduates with flags (regalia plus country banners)
                    - cultural performance (traditional dress on campus stage)
                    - global fair (tables with maps, food, and language displays)
                    - program signage (“International Studies” wall or doorway marker)
                    - map motif (world/regional map graphic in academic space)
                    - multicultural processional (mixed flags during ceremony)

                    code_feature :: Feature story
                    - Interview vignettes (woman in ornate interior, young man with cityscape backdrop)
                    - textual graphic context (“70 YEARS AGO” historical framing)
                    - historical photos (pixelated, grayscale photography)
                    """

    payload = {
        'model': model,
        'messages': [
            {
                'role': 'system',
                'content': f'You are coding a single video clip frame for dataset coding. {code_examples_text}.'
            },
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': f"Domain: {domain}\nClip: {clip_number}\n{prompt_text}"},
                    {'type': 'image_url', 'image_url': {'url': data_url}},
                ],
            }
        ],
        'temperature': 0,
    }

    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
    r.raise_for_status()
    j = r.json()
    return j['choices'][0]['message']['content'].strip()


def write_glue_csv(path: str, bases: List[int], cont_lists: List[List[int]]) -> None:
    """Headerless glue.csv: each line is base or base,compressed_continuation."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for base, cont in zip(bases, cont_lists):
            if cont:
                f.write(f"{base},{compress_ints(cont)}\n")
            else:
                f.write(f"{base}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='scenes_complete.xlsx')
    ap.add_argument('--output_dir', default='results')

    # scenes layout
    ap.add_argument('--scenes_subdir', default='scenes')
    ap.add_argument('--scene_prefix', default='scene_')
    ap.add_argument('--scene_mp4_ext', default='.mp4')
    ap.add_argument('--scene_jpg_ext', default='.jpg')

    # OpenAI / local endpoint
    ap.add_argument('--openai_base_url', default='http://localhost:1234/v1')
    ap.add_argument('--openai_api_key', default='lm-studio')
    ap.add_argument('--model', default='gemma-3-4b-it-qat')
    ap.add_argument('--no_llm', action='store_true', help='Skip OpenAI calls; still build glue + analysis CSV')
    ap.add_argument('--sleep', type=float, default=0.0, help='Optional delay between requests')

    # Optional column overrides
    ap.add_argument('--domain_col', default=None)
    ap.add_argument('--clip_col', default=None)
    ap.add_argument('--time_col', default=None)
    ap.add_argument('--desc_col', default=None)
    ap.add_argument('--category_col', default=None)
    ap.add_argument('--subcat_col', default=None)
    ap.add_argument('--desc_rev_col', default=None)

    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    df = pd.read_excel(args.input, engine='openpyxl')
    df = normalize_columns(df)

    # Detect expected columns from your file
    domain_col = args.domain_col or detect_column(df, ['domain', 'institution', 'site', 'url', 'domain/institution'])
    clip_col = args.clip_col or detect_column(df, ['#', 'clip number', 'clip_number', 'clip', 'number'])
    time_col = args.time_col or detect_column(df, ['length', 'timecode', 'tc', 'duration'])
    desc_col = args.desc_col or detect_column(df, ['description', 'desc', 'scene description'])
    category_col = args.category_col or detect_column(df, ['category', 'code', 'codes', 'code_tags'])
    subcat_col = args.subcat_col or detect_column(df, ['sub category', 'subcategory', 'sub_category'])
    desc_rev_col = args.desc_rev_col or detect_column(df, ['description revision', 'description_revision', 'revision'])

    if domain_col is None or clip_col is None:
        raise SystemExit(f"Missing required columns. Found: {list(df.columns)}")

    # Coerce clip numbers
    df[clip_col] = pd.to_numeric(df[clip_col], errors='coerce')

    # Canonical columns
    df['institution_domain'] = df[domain_col].map(parse_domain)
    df['clip_number'] = df[clip_col]
    df['timecode_or_length'] = df[time_col].astype(str) if time_col else ''
    df['description'] = df[desc_col].astype(str) if desc_col else ''
    df['category'] = df[category_col].astype(str) if category_col else ''
    df['sub_category'] = df[subcat_col].astype(str) if subcat_col else ''
    df['description_revision'] = df[desc_rev_col].astype(str) if desc_rev_col else ''

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_frames = []

    grouped = df.dropna(subset=['institution_domain', 'clip_number']).groupby('institution_domain')

    for domain, dom_df in grouped:
        dom_dir = os.path.join(args.output_dir, safe_folder(domain))
        scenes_dir = os.path.join(dom_dir, args.scenes_subdir)
        os.makedirs(dom_dir, exist_ok=True)

        existing_scene_nums = list_existing_scene_numbers(
            scenes_dir,
            mp4_ext=args.scene_mp4_ext,
            prefix=args.scene_prefix,
        )
        existing_set = set(existing_scene_nums)
        max_scene = max(existing_scene_nums) if existing_scene_nums else None

        # Bases are the clip numbers from Excel; your data uses ints like 1,5,7...
        dom_df = dom_df.sort_values('clip_number').reset_index(drop=True)
        bases = [int(x) for x in dom_df['clip_number'].tolist()]
        next_bases: List[Optional[int]] = bases[1:] + [None]

        cont_lists: List[List[int]] = []
        cont_strs: List[str] = []
        img_paths: List[str] = []

        for base, nxt in zip(bases, next_bases):
            cont = continuation_scenes(existing_set, base, nxt, max_scene)
            cont_lists.append(cont)
            cont_strs.append(compress_ints(cont))
            img = choose_image_for_clip(scenes_dir, base, cont, jpg_ext=args.scene_jpg_ext, prefix=args.scene_prefix)
            img_paths.append(img or '')

        # 1) Write glue.csv
        write_glue_csv(os.path.join(dom_dir, 'glue.csv'), bases, cont_lists)

        print(f"Preparing LLM request for domain:", domain, "clip:", base)    
        # 2) LLM per clip row
        llm_outputs: List[str] = []
        if args.no_llm:
            print("Skipping LLM calls (--no_llm set); filling with empty strings.")
            llm_outputs = ['' for _ in bases]
        else:
            print(f"Calling LLM for domain: {domain} with model: {args.model}")
            for base, cont_str, img in zip(bases, cont_strs, img_paths):
                if not img or not os.path.exists(img):
                    print(f"WARNING: No image found for domain {domain} clip {base}. Skipping LLM call for this row: {img_paths}")
                    llm_outputs.append('')
                    continue

                # Prompt context can include your continuation range + any other metadata
                prompt_text = f"Continuation scenes on disk: {cont_str or '(none)'}\n Please provide the code label(s) of this clip's representative image. Do not provide code descriptions. Only return the code label(s), comma-separated if multiple apply." 
                try:
                    out = call_openai_vision(
                        base_url=args.openai_base_url,
                        api_key=args.openai_api_key,
                        model=args.model,
                        domain=domain,
                        clip_number=base,
                        image_path=img,
                        prompt_text=prompt_text,
                    )
                except Exception as e:
                    out = f"ERROR: {type(e).__name__}: {e}"

                llm_outputs.append(out)
                if args.sleep:
                    time.sleep(args.sleep)

        dom_df['next_clip_number'] = [float(x) if x is not None else float('nan') for x in next_bases]
        dom_df['scenes_guess'] = cont_strs
        dom_df['image_path_used'] = img_paths
        dom_df['LLM Output'] = llm_outputs

        # Per-domain analysis CSV
        analysis_cols = [
            'institution_domain','clip_number','next_clip_number','timecode_or_length',
            'category','sub_category','description','description_revision',
            'scenes_guess','image_path_used','LLM Output'
        ]
        dom_df[analysis_cols].to_csv(os.path.join(dom_dir, 'clips_analysis.csv'), index=False)

        out_frames.append(dom_df)

    # Consolidated Excel
    all_df = pd.concat(out_frames, ignore_index=True) if out_frames else df
    out_xlsx = os.path.join(args.output_dir, f'clips_complete_{timestamp}.xlsx')
    all_df.to_excel(out_xlsx, index=False, engine='openpyxl')
    print(f'Wrote consolidated: {out_xlsx}')


if __name__ == '__main__':
    main()

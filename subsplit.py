import os
import csv
import argparse
import subprocess
import shutil
import mimetypes
import time
from config import sites, subsplit

# Define the base directory
results_dir = 'results'
table_lookup = "lookup.csv"

# Default variables
scene_crawl = 10
scene_diff = 0.30

# Regular functions
# -----------------------------------------------------------------------

# Stores scene split lookup
def scene_split_lookup(csv_file_path):
    with open(csv_file_path, mode='r', newline='', encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)
        return list(reader)  # List of dictionaries

# An agnostic find_row content for scene_split dictionary
def find_row(data, search_value):
    for row in data:
        print(row)
        if row['site'] == search_value:
            return row
    return None

def scene_split_process(directory):
    result = find_row(sites_lookup, directory)
    global scene_crawl 
    global scene_diff
    if not result:
        # Reapply default variables
        print("Applying default scene variables...")
        scene_crawl = 10
        scene_diff = 0.30
    else:
        scene_crawl = result['crawl']
        # Take difference and divide by two, since we can't catch a break with this scene.
        scene_diff = float(result['diff']) / 4
    print(f"Processing video with crawl={scene_crawl}, diff={scene_diff}")
    return None

def is_directory_empty(path):
    return not os.listdir(path)

def sanitize_filename(filename):
    return filename.split('?')[0]

def is_file_smaller_than_1kb(file_path):
    return os.path.getsize(file_path) < 1024

def is_video_corrupted(file_path):
    try:
        result = subprocess.run(
            [
                "ffprobe", "-hide_banner", "-v", 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True
        )
        return False # ffprobe succeeded
    except subprocess.CalledProcessError as e:
        print(f"ffprobe failed: {e.stderr}")
        return True

def get_video_duration(video_path):
    # Get the duration of the video in seconds.
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of",
            "default=noprint_wrappers=1:nokey=1", video_path
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    return float(result.stdout)

def capture_middle_frame(video_path):
    print(f"Generating screenshot for {video_path}...")
    duration = get_video_duration(video_path)
    midpoint = duration / 2

    base_name = os.path.splitext(os.path.basename(video_path))[0]
    output_image_name = f"{base_name}_screenshot.jpg"
    output_image_path = os.path.join(os.path.dirname(video_path),output_image_name)

    if os.path.exists(output_image_path):
        os.remove(output_image_path)

    subprocess.run([
        "ffmpeg",
        "-y",
        "-ss", str(midpoint),
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_image_path,
        '-loglevel', 'error', '-stats'
    ])
    print(f"Screenshot saved as: {output_image_path}")

# Function to detect scenes and split video
def process_video(video_path, institution_scenes_dir):
    scene_log_file = os.path.dirname(video_path) + '/scene_log.txt'
    print(f"Processing crawler={scene_crawl}, diff={scene_diff}...")

    scene_detection_command = [
        'ffmpeg', '-i', video_path, '-filter_complex',
        f"select='not(mod(n,{scene_crawl}))',select='gt(scene,{scene_diff})',showinfo", '-f', 'null', '-'
    ]
    with open(scene_log_file, 'w') as log_file:
        subprocess.run(scene_detection_command, stderr=log_file)

    # Step 2: Parse timestamps
    timestamps = []
    with open(scene_log_file, 'r') as log_file:
        for line in log_file:
            if 'pts_time:' in line:
                timestamp = float(line.split('pts_time:')[1].split(' ')[0])
                timestamps.append(timestamp)
    
    # Step 3: Split video
    result_files = []
    print("Video analyzed; found " + str(len(timestamps)) + " splits!")
    if str(len(timestamps)) == "0":
        print("No scenes found, creating duplicate for AI usage...")
        output_clip = os.path.join(institution_scenes_dir,  f'{subsplit}_1.mp4')
        shutil.copyfile(video_path,output_clip)
        print(f"Created {subsplit}_1.mp4!")
        result_files.append(f"{subsplit}_{1}.mp4")
    else:
        previous_timestamp = 0
        for i, timestamp in enumerate(timestamps):
            print(f"Creating {subsplit}_{i+1}.mp4...")
            output_clip = os.path.join(institution_scenes_dir, f'{subsplit}_{i+1}.mp4')
            split_command = [
                'ffmpeg','-y', '-i', video_path, '-ss', str(previous_timestamp), '-to', str(timestamp),
                '-c:v', 'libx264', '-c:a', 'aac', output_clip, '-loglevel', 'error', '-stats'
            ]
            subprocess.run(split_command)
            print(f"Created {subsplit}_{i+1}.mp4!")
            result_files.append(f"{subsplit}_{i+1}.mp4")
            previous_timestamp = timestamp

        # Final segment
        output_clip = os.path.join(institution_scenes_dir, f'{subsplit}_{len(timestamps)+1}.mp4')
        final_timestamp = get_video_duration(video_path)
        print("Creating final clip...")
        split_command = [
            'ffmpeg', '-y', '-i', video_path, '-ss', str(timestamp), '-to', str(final_timestamp), 
            '-c:v', 'libx264', '-c:a', 'aac', output_clip, '-loglevel', 'error', '-stats'
        ]
        subprocess.run(split_command)
        result_files.append(f"{subsplit}_{len(timestamps)+1}.mp4")
        print(f"Created {subsplit}_{len(timestamps)+1}.mp4!")
    for result_file in result_files:
        result_file_path = os.path.join(institution_scenes_dir, result_file)
        capture_middle_frame(result_file_path)

def prune_folder(institution_path):
    shutil.rmtree(institution_path)

def process_folder(institution_path):
    if os.path.isdir(institution_path):
        # Create 'scenes' subdirectory inside the institution folder
        institution_scenes_dir = os.path.join(institution_path, 'scenes')
        # Build split video file from the config sub variable
        split_video_file = subsplit + ".mp4"
        # Now, attempt to toss that sucker into here.
        video_file = os.path.join(institution_scenes_dir, split_video_file)
        if os.path.exists(video_file):
            # Check if video has a fubar name
            video_file_sanitized = sanitize_filename(video_file)
            if video_file_sanitized != video_file:
                os.rename(os.path.join(institution_path, video_file), os.path.join(institution_path, video_file_sanitized))
                video_file = video_file_sanitized
                del video_file_sanitized
            # Legacy handoff for code - yes it's ugly, no I don't care.
            video_path = video_file
            if os.path.isfile(video_path):
                print(f"Checking {video_path}... ")
                if mimetypes.guess_type(video_path)[0] is None:
                    print(f"File is none, skipping...")
                    exit
                if is_video_corrupted(video_path):
                    print(f"{video_path} is corrupt - removing the video.")
                    prune_folder(institution_path)
                    exit
                if mimetypes.guess_type(video_path)[0].startswith('video'):
                    print(f"Processing video {video_path}")
                    process_video(video_path, institution_scenes_dir)
                    # Now, given the video processed, we should able to sniff out all clips starting with this?
                else:
                    print(f"Cannot process {video_path}, mimetype is " + mimetypes.guess_type(video_path)[0])

# main function run
# -----------------------------------------------------------------------
# Load once
sites_lookup = scene_split_lookup(table_lookup)

if sites:
    # Processing array of troublemakers
    for site in sites:
        print(f"Processing {site}...")
        scene_split_process(site)
        institution_path = os.path.join(results_dir, site)
        process_folder(institution_path)
else:
    # Throw grumpy error
    print("What have you done? No sites variable found.")
    exit 

print("Scene detection and video splitting completed for all videos.")

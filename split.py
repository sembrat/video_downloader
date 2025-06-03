import os
import argparse
import subprocess
import shutil
import mimetypes

#argument 
parser = argparse.ArgumentParser("split")
parser.add_argument("-site", help="Add a domain to (re-)generate scene splits for.", type=str)
args = parser.parse_args()

args.site = "cmn.edu"

# Define the base directory
results_dir = 'results'

def is_file_smaller_than_1kb(file_path):
    return os.path.getsize(file_path) < 1024

def get_video_duration(video_path):
    """Get the duration of the video in seconds."""
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
        print(f"Screenshot already exists: {output_image_name}")

    subprocess.run([
        "ffmpeg",
        "-y",
        "-ss", str(midpoint),
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_image_path
    ])
    print(f"Screenshot saved as: {output_image_path}")

# Function to detect scenes and split video
def process_video(video_path, institution_scenes_dir):
    scene_log_file = os.path.dirname(video_path) + '/scene_log.txt'
    
    # Step 1: Detect scene changes
    scene_crawl = 10
    scene_diff = 0.30
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
    previous_timestamp = 0
    for i, timestamp in enumerate(timestamps):
        output_clip = os.path.join(institution_scenes_dir, f'scene_{i+1}.mp4')
        split_command = [
            'ffmpeg','-y', '-i', video_path, '-ss', str(previous_timestamp), '-to', str(timestamp),
            '-c:v', 'libx264', '-c:a', 'aac', output_clip
        ]
        subprocess.run(split_command)
        previous_timestamp = timestamp

    # Final segment
    output_clip = os.path.join(institution_scenes_dir, f'scene_{len(timestamps)+1}.mp4')
    split_command = [
        'ffmpeg', '-y', '-i', video_path, '-ss', str(previous_timestamp), '-c', 'copy', output_clip
    ]
    subprocess.run(split_command)

def process_folder(institution_path):
    if os.path.isdir(institution_path):
        for video_file in os.listdir(institution_path):
            video_path = os.path.join(institution_path, video_file)
            if os.path.isfile(video_path):
                # Create 'scenes' subdirectory inside the institution folder
                institution_scenes_dir = os.path.join(institution_path, 'scenes')
                if os.path.isdir(institution_scenes_dir):
                    shutil.rmtree(institution_scenes_dir)
                os.makedirs(institution_scenes_dir, exist_ok=True)
                print(f"Checking {video_path}... ")
                if mimetypes.guess_type(video_path)[0] is None:
                    print(f"File is none, skipping...")
                    continue
                if mimetypes.guess_type(video_path)[0].startswith('video'):
                    print(f"Processing video {video_path}")
                    process_video(video_path, institution_scenes_dir)
                else:
                    print(f"Cannot process {video_path}, mimetype is " + mimetypes.guess_type(video_path)[0])
                ## Checking for blacked out videos and removing.
                subprocess.run(["python", "black.py", institution_scenes_dir])
                for video_clip_file in os.listdir(institution_scenes_dir):
                    if video_clip_file == ".DS_Store":
                        print(f"Blasting {video_clip_file} into the sun!")
                        continue
                    video_clip_path = os.path.join(institution_scenes_dir, video_clip_file)    
                    # Removing tiny videos. 
                    if is_file_smaller_than_1kb(video_clip_path):
                        print(f"{video_clip_path} is corrupt - removing the video.")
                        os.remove(video_clip_path)
                    else:
                        if os.path.isfile(video_clip_path):
                            print(f"Analyzing {video_clip_file}...")
                            capture_middle_frame(video_clip_path)
                        else:
                            print(f"Path does not exist {video_clip_path}")

if args.site == "":
    # Process all videos in results/
    for institution_folder in os.listdir(results_dir):
        institution_path = os.path.join(results_dir, institution_folder)
        process_folder(institution_path)
else:
    print(f"Processing {args.site}...")
    institution_path = os.path.join(results_dir, args.site)
    process_folder(institution_path)

print("Scene detection and video splitting completed for all videos.")
import os
import csv
import argparse
import subprocess
import shutil
import mimetypes
import time
from config import sites

# Define the base directory
results_dir = 'results'

def merge_files(institution_scenes_dir, process_videos, file):
    file_path = os.path.join(institution_scenes_dir, file)
    video_file = os.path.join(institution_scenes_dir, "videos.txt")
    with open(video_file, "w") as f:
        for video in process_videos:
            #video_path = os.path.join(institution_scenes_dir, video)
            f.write(f"file '{video}'\n")

    # FFmpeg command to concatenate videos
    ffmpeg_command = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", video_file,
        "-c", "copy",
        file_path,
         '-loglevel', 'error', '-stats'
    ]

    # Run the command
    subprocess.run(ffmpeg_command)
    for f in process_videos:
        f_path = os.path.join(institution_scenes_dir, f)
        # Check if the file exists before trying to delete it
        if os.path.exists(f_path):
            if f == file:
                print(f"Cannot remove {f}, it is the final form video.")
            else:
                os.remove(f_path)
                print(f"Deleted unnecessary scene: {f_path}")
                # Now, remove screencaps.
                screencap_path = os.path.join(institution_scenes_dir, f"{os.path.splitext(f)[0]}_screenshot.jpg")
                if os.path.exists(screencap_path):
                    os.remove(screencap_path)
                    print(f"Deleted screenshot: {screencap_path}")

        else:
            print(f"{f_path} does not exist.")
        if os.path.exists(video_file):
            os.remove(video_file)

def lookup_file(institution_scenes_dir,file_dict, current_key):
    process_videos = []
    lookup_key = "{:02d}".format(int(current_key))
    if str(lookup_key) in file_dict:
        print(f"Found file: {file_dict[str(lookup_key)]}")
    else:
        print("File not found.")

    while True:
        direction = input("Would you like to check the [next (n)] or [previous (p)] file? (or type 'exit' to quit): ").strip().lower()
        
        if direction == "n" or direction == "next":
            second_key = "{:02d}".format(int(current_key+1))
            process_videos.append(file_dict[str(lookup_key)])
            process_videos.append(file_dict[str(second_key)])

        elif direction == "p" or direction == "previous":
            second_key = "{:02d}".format(int(current_key-1))
            process_videos.append(file_dict[str(second_key)])
            process_videos.append(file_dict[str(lookup_key)])
        elif direction == "e" or direction == "exit":
            print("Exiting lookup.")
            break
        else:
            print("Invalid input. Please type 'next', 'previous', or 'exit'.")
            continue
        
        # Here's my process queue.
        print(process_videos)
        merge_files(institution_scenes_dir, process_videos, file_dict[str(lookup_key)])
        break  # Prevent infinite recursion

def process_folder(institution_path):
    videos = {}
    if os.path.isdir(institution_path):
        # Create 'scenes' subdirectory inside the institution folder
        institution_scenes_dir = os.path.join(institution_path, 'scenes')
        for video in os.listdir(institution_scenes_dir):
            if video.startswith('scene_') and video.endswith('.mp4'):
                scene_number = os.path.splitext(video)[0].split('_')[1]
                scene_number_normalized = "{:02d}".format(int(scene_number))
                videos[scene_number_normalized] = video
                print(f"Scene found! {scene_number_normalized}")
        #print(f"Found {len(videos)} scenes!")
       
        sorted_videos = {key: videos[key] for key in sorted(videos)}

        for k, v in sorted_videos.items():
            print(k, v)
        user_input = ""
        while user_input is not "exit":
            user_input = int(input("Enter a number to look up a file: "))
            if user_input is not "exit":
                lookup_file(institution_scenes_dir, sorted_videos, user_input)
    else:
        print("Error, no folder found!")
        exit

# main function run
# -----------------------------------------------------------------------

# Processing array of troublemakers
for site in sites:
    print(f"Processing {site}...")
    institution_path = os.path.join(results_dir, site)
    process_folder(institution_path)

print("Fix splits complete.")

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

def lookup_file(institution_scenes_dir,file_dict, current_key):
    process_videos = []
    if str(current_key) in file_dict:
        print(f"Found file: {file_dict[str(current_key)]}")
    else:
        print("File not found.")

    while True:
        direction = input("Would you like to check the [next (n)] or [previous (p)] file? (or type 'exit' to quit): ").strip().lower()
        
        if direction == "n" or direction == "next":
            process_videos.append(file_dict[str(current_key)])
            process_videos.append(file_dict[str(current_key+1)])

        elif direction == "p" or direction == "previous":
            process_videos.append(file_dict[str(current_key-1)])
            process_videos.append(file_dict[str(current_key)])
        elif direction == "e" or direction == "exit":
            print("Exiting lookup.")
            break
        else:
            print("Invalid input. Please type 'next', 'previous', or 'exit'.")
            continue
        
        print(process_videos)
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

import os
import csv
import subprocess
import tempfile
import re
from config import sites

# Define the base directory
results_dir = 'results'

# Define the subdirectory containing the video files
video_subdirectory = "path/to/video/files"  # Replace with your actual path
# Define the path to the glue.csv file
glue_csv_path = "glue.csv"

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

for site in sites:
    video_subdirectory = os.path.join("results", site, "scenes")
    print(f"Processing {site} [{video_subdirectory}]...")

    #First, remove all screenshots.
    # Remove all scene_#_screenshot.jpg files
    print(f"Removing all screenshots...")
    for filename in os.listdir(video_subdirectory):
        if re.match(r"scene_\d+_screenshot\.jpg", filename):
            file_path = os.path.join(video_subdirectory, filename)
            try:
                os.remove(file_path)
                print(f"Deleted screenshot: {file_path}")
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")

    # Read the glue.csv file and process each line
    with open(glue_csv_path, newline='') as csvfile:
        reader = csv.reader(csvfile)
        print(f"Sniffing glue...")
        for row in reader:
            if not row:
                continue  # Skip empty lines
            scene_numbers = [int(num.strip()) for num in row]
            destination_scene = scene_numbers[0]
            print(f"Processing {destination_scene} glue...")

            # Create a temporary file listing the input videos for ffmpeg
            with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as list_file:
                for scene_num in scene_numbers:
                    video_path = os.path.abspath(os.path.join(video_subdirectory, f"scene_{scene_num}.mp4"))
                    if os.path.exists(video_path):
                        list_file.write(f"file '{video_path}'\n")
                    else:
                        print(f"Warning: {video_path} does not exist and will be skipped.")
                list_file_path = list_file.name

            # Define the output file path
            output_path = os.path.join(video_subdirectory, f"scene_{destination_scene}.mp4")

            # Run ffmpeg to concatenate the videos
            result = subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file_path, "-c", "copy", output_path
            ])

            # Remove the temporary file
            os.remove(list_file_path)

            # If ffmpeg succeeded, delete the source scene files except the destination
            if result.returncode == 0:
                print(f"Successful glue, removing legacy files...")
                for scene_num in scene_numbers:
                    if scene_num != destination_scene:
                        source_path = os.path.join(video_subdirectory, f"scene_{scene_num}.mp4")
                        if os.path.exists(source_path):
                            try:
                                print(f"Removing {scene_num} [{source_path}]")
                                os.remove(source_path)
                            except Exception as e:
                                print(f"Error deleting {source_path}: {e}")
            else:
                print(f"FFmpeg failed for scene {destination_scene}. Source files not deleted.")
           

    print(f"Gluecation complete!")
    for video_clip_file in os.listdir(video_subdirectory):
        if video_clip_file == ".DS_Store":
            print(f"Blasting {video_clip_file} into the sun!")
            continue
        video_clip_path = os.path.join(video_subdirectory, video_clip_file)    
        if os.path.isfile(video_clip_path):
            print(f"Analyzing {video_clip_file}...")
            capture_middle_frame(video_clip_path)
        else:
            print(f"Path does not exist {video_clip_path}")

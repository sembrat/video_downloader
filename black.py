import os
import subprocess
import argparse
from pathlib import Path


# Create the parser
parser = argparse.ArgumentParser(description="Process an video file path.")

# Add an argument
parser.add_argument("path", help="Path to video files.")

# Parse the arguments
args = parser.parse_args()

# Use the argument
print(f"Running blank video scenes on video path: {args.path}")

# Directory containing the videos
VIDEO_DIR = Path(args.path)
# Thresholds
BLACK_THRESHOLD_SECONDS = 0.85  # if this much of the video is black, it will be removed

def is_mostly_black(video_path):
    """Uses ffmpeg to check if the video is mostly black"""
    try:
        # Get video duration
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        duration = float(result.stdout.strip())
        print(f"{video_path} has {duration} length.")

        # Run blackdetect
        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vf", "blackdetect=d=0.5:pic_th=0.10",
            "-an", "-f", "null", "-"
        ]
        result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
        stderr = result.stderr

        # Extract total black duration
        black_duration = 0.0
        for line in stderr.splitlines():
            if "black_start:" in line:
                parts = line.strip().split()
                for part in parts:
                    if part.startswith("black_duration:"):
                        black_duration += float(part.split(":")[1])
                        print(f"Black duration: {black_duration}")
        black_total = (black_duration >= (BLACK_THRESHOLD_SECONDS * duration))
        if black_duration > 0.0:
            print(f"{black_total} value determined for white duration: {black_duration}")
        return black_total
    except Exception as e:
        print(f"Error processing {video_path}: {e}")
        return False

def is_mostly_white(video_path):
        """Uses ffmpeg to check if the video is mostly black"""
        try:
            # Get video duration
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            duration = float(result.stdout.strip())
            print(f"{video_path} has {duration} length.")

            # Run blackdetect
            cmd = [
                "ffmpeg", "-i", str(video_path),
                "-vf", "negate,blackdetect=d=0.5:pic_th=0.10",
                "-an", "-f", "null", "-"
            ]
            result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
            stderr = result.stderr

            # Extract total black duration
            black_duration = 0.0
            for line in stderr.splitlines():
                if "black_start:" in line:
                    parts = line.strip().split()
                    for part in parts:
                        if part.startswith("black_duration:"):
                            black_duration += float(part.split(":")[1])
                            print(f"White duration: {black_duration}")
            black_total = (black_duration >= (BLACK_THRESHOLD_SECONDS * duration))
            if black_duration > 0.0:
                print(f"{black_total} value determined for white duration: {black_duration}")
            return black_total
        except Exception as e:
            print(f"Error processing {video_path}: {e}")
            return False

def process_directory(directory):
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    for video_file in directory.iterdir():
        if video_file.suffix.lower() in video_extensions:
            if is_mostly_black(video_file):
                print(f"Removing {video_file}, as it was a dark blank video.")
                os.remove(video_file)
            if is_mostly_white(video_file):
                print(f"Removed {video_file}, as it was a bright blank video.")
                os.remove(video_file)

process_directory(VIDEO_DIR)
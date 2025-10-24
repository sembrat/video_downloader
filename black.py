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
BLACK_THRESHOLD_SECONDS = 0.9  # if this much of the video is black, it will be renamed

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
        print(f"Video has {duration} length.")

        # Run blackdetect
        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vf", "blackdetect=d=0.1:pic_th=0.98",
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

        return black_duration >= (BLACK_THRESHOLD_SECONDS * duration)
    except Exception as e:
        print(f"Error processing {video_path}: {e}")
        return False

def process_directory(directory):
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    for video_file in directory.iterdir():
        if video_file.suffix.lower() in video_extensions and not video_file.name.startswith("BLACK_"):
            if is_mostly_black(video_file):
                os.remove(os.path.join(directory,video_file))
                print(f"Removed {directory}/{video_file}, as it was a blank video.")

if __name__ == "__main__":
    process_directory(VIDEO_DIR)
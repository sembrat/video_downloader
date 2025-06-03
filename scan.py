import os
import requests
import pandas as pd
import subprocess
from urllib.parse import urlparse

# Define paths
excel_file = 'scan_results.xlsx'
#input_file_name = "resource/hd2023.csv"
#output_file_name = "resource/crawler.csv"
results_dir = 'results'

# Create the main results directory if it doesn't exist
os.makedirs(results_dir, exist_ok=True)

# Helper function to sanitize folder names
def sanitize_folder_name(name):
    return "".join(c for c in name if c.isalnum() or c in (' ', '.', '_')).rstrip()

# Read the Excel file
df = pd.read_excel(excel_file)

# Process each row
for _, row in df.iterrows():
    video_url = row.get('Video Source')
    institution_url = row.get('URL')
    is_primary = row.get('Is Primary Site')

    # Skip if 'Video Source' is empty or NaN
    if not isinstance(video_url, str) or not video_url.strip():
        print(f"Skipping {institution_url}...")
        continue
    if not is_primary:
        print(f"Is not a primary URL {institution_url}, skipping...")
        continue
    if not ".edu" in institution_url:
        print(f"Is not a higher edcuation URL {institution_url}, skipping...")
        continue
    # Use the netloc part of the URL as the folder name
    parsed_url = urlparse(institution_url)
    institution_name = sanitize_folder_name(parsed_url.netloc or str(institution_url))

    # Create subfolder for the institution
    institution_folder = os.path.join(results_dir, institution_name)
    os.makedirs(institution_folder, exist_ok=True)

    # Determine the video filename
    video_filename = os.path.join(institution_folder, os.path.basename(video_url))

    # Skip download if file already exists
    if os.path.exists(video_filename):
        print(f"Video already exists for {institution_name}, skipping: {video_filename}")
        continue

    # Download the video
    try:
        headers = {
            "authority": "www.google.com",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "max-age=0",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            # add more headers as needed
        }
        response = requests.get(video_url, headers=headers, stream=True)
        response.raise_for_status()

        with open(video_filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"Downloaded video for {institution_name} to {video_filename}")
    except Exception as e:
        print(f"Failed to download video from {video_url} for {institution_name}: {e}")
# Now, split.
subprocess.run(["python", "split.py"])

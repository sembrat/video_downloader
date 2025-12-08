import requests
import lmstudio as lms
import base64
import os
import subprocess
import csv
import re
import pandas as pd
from openai import OpenAI
from config import sites 
from collections import defaultdict
from datetime import datetime, timedelta

#-----------------------------------------------------------------------
# Configure inference
# sites = [ "www.andrewcollege.edu" ] # this is now in config.py

# Regular functions
# -----------------------------------------------------------------------
def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return encoded_string


def convert_to_timedelta(time_str):
    """
    Converts a time string in HH:MM:SS.ss format to a timedelta object.
    """
    try:
        h, m, s = time_str.split(":")
        return timedelta(hours=int(h), minutes=int(m), seconds=float(s))
    except ValueError:
        raise ValueError("Time string must be in HH:MM:SS.ss format")


def add_time_strings(time_str1, time_str2):
    """Adds two time strings and returns the result in HH:MM:SS.ss format."""
    td1 = convert_to_timedelta(time_str1)
    td2 = convert_to_timedelta(time_str2)
    total_seconds = (td1 + td2).total_seconds()

    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:05.2f}"


# Default function
# -----------------------------------------------------------------------
# Define the base directory
results_dir = 'results'

# Hello, AI overlords.
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

# Initialize a list to store the data for the Excel file
data = []
video_timestamps = {}

# glue some inferences together
glue_csv_path = "glue.csv"
glue_stick = {}

# First, populate sites if the argument is empty
if not sites:
    sites = os.listdir(results_dir)

# Iterate through each domain folder in the results directory
for domain in sites:
    print(f"Analyzing {domain}...")
    domain_path = os.path.join(results_dir, domain)

    # Check if the domain path is a directory
    if os.path.isdir(domain_path):
        scenes_path = os.path.join(domain_path, 'scenes')
        print(f"Analyzing scenes {scenes_path}")
        # Check if the scenes path exists and is a directory
        if os.path.isdir(scenes_path):
            print(f"Analyzing {scenes_path}...")

            # First, check glue CSV
            with open(glue_csv_path, newline='') as csvfile:
                reader = csv.reader(csvfile)
                print(f"Sniffing glue...")
                for row in reader:
                    if not row:
                        continue  # Skip empty lines
                    # Checking if dash exists
                    first, second = row[0], row[1]

                    # Check if second part contains '-'
                    if "-" in second:
                        start, end = map(int, second.split("-"))
                        scene_numbers = [str(i) for i in range(start, end + 1)]
                        destination_scene = first
                    else:
                        scene_numbers = [int(num.strip()) for num in row]
                        destination_scene = scene_numbers[0]
                        # Since destination is key, no longer needed in array
                        scene_numbers.remove(destination_scene)
                    
                    #print(f"Inserting glue {destination_scene}{scene_numbers} into nose!")
                    glue_stick[destination_scene] = scene_numbers
                    # Glue Stick is now rendered.
                print(f"Glue Stick is rendered: {glue_stick}")

            videos = [ f for f in os.listdir(scenes_path) if f.endswith('.mp4') ]
            for video in videos:
                video_path = os.path.join(scenes_path, video)
                video_length = None
                if os.path.exists(video_path):
                    result = subprocess.run(
                        ['ffmpeg', '-i', video_path],
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    for line in result.stderr.split('\n'):
                        if 'Duration' in line:
                            duration = line.split('Duration: ')[1].split(',')[0]
                            video_length = duration.strip()
                            break
                    if video_length is None:
                        video_length = "error"
                # Get scene number
                match = re.search(r'scene_(\d+)', video)
                if match:
                    video_scene_match = int(match.group(1))
                else:
                    print("No scene number found.")
                video_timestamps[video_scene_match] = video_length
            print(f"Timestamps is rendered: {video_timestamps}")
                
        
            # Iterate through each image in the scenes directory
            images = [ f for f in os.listdir(scenes_path) if f.endswith('.jpg') ]
            for image in sorted(images):
                # Variable to snip out inference
                # Is the scene a key value in glue?
                glue_key = False
                glue_key_index = 0
                # Is the scene an array value in glue?
                glue_array = False

                print(f"Searching {image}...")
                if image.startswith('scene_') and image.endswith('_screenshot.jpg'):
                    print(f"Found matching screenshot! {image}")
                    # Extract the scene number from the filename
                    scene_number = image.split('_')[1]
                    scene_number_normalized = "{:03d}".format(int(scene_number))
                    print(f"Scene: {scene_number_normalized}")
                    
                    if not glue_stick:
                        print("Glue stick is empty.")
                    else:
                        # GLUE
                        print("Checking for scene glue...")
                        # First, check for glue_key
                        for key, values in glue_stick.items():
                            #print(f"Sniffing keys: {key} versus {scene_number}")
                            if str(key) == str(scene_number):
                                print(f"Scene {scene_number} is a destination scene.")
                                print(f"Associated scenes: {glue_stick[key]}")
                                glue_key = True
                                glue_key_index = key
                                break
                            for value in values:
                                #print(f"Sniffing value: {value} versus {scene_number}")
                                if str(value) == str(scene_number):
                                    print(f"Scene is a child scene for glue, skipping analysis of scene {value}!")
                                    glue_array = True
                                    break
                            if glue_array:
                                # Break free of the loop.
                                break
    
                        if glue_array is True:
                            continue

                    # Determine video_length
                    video_length = video_timestamps[int(scene_number)]
                    if video_length is None:
                        print("We gotta problem.")
                    if glue_key:
                        print(f"Time starts as {video_length}")
                        for subscene in glue_stick[glue_key_index]:
                            video_length = add_time_strings(video_length, video_timestamps[int(subscene)])
                            print(f"Time is now {video_length}, with the addition of {video_timestamps[int(subscene)]}")

                    # Define the path to the image file
                    image_path = os.path.join(scenes_path, image)
                    print(f"Analyzing {image_path}...")

                    if glue_array is True:
                        break
                    else:
                        # AI generation
                        base64_encoded_image = image_to_base64(image_path)
                        response = client.chat.completions.create(
                            model="gemma-3-4b-it-qat",
                            messages=[{
                                "role": "user", 
                                "content": [
                                    {
                                    "type": "text",
                                    "text": "This is a screenshot of a video displayed on a higher education institution website. Describe what this image shows. Do not include any formatting markdown, or provide any introduction to the response. Just give the visual description of the photo.",
                                    },
                                    {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{base64_encoded_image}"},
                                    },
                                ]
                            }],
                        )

                        # Get the video description.
                        video_description = (response.choices[0].message.content)
                        print(f"Video description: {video_description}")
                        
                        response = client.chat.completions.create(
                            model="gemma-3-4b-it-qat",
                            messages=[{
                                "role": "user", 
                                "content": [
                                    {
                                    "type": "text",
                                    "text": "Categorize this photo. Only provide the category without markdown formatting as plain text, or use Other if it does not match. Categories are: **Academics, Teaching and Research**: Student(s) in a classroom or lab (safety glasses; lab coat; scientific equipment); faculty/older individual present (non-traditional college age) at blackboard; lecture; students outside in circle with presence of instructor; sole image of instructor; books; computer lab, high-tech equipment (e.g., solar panels, high-powered telescope).<br>**University environment, Campus aesthetics**: Architecture; campus lawns; buildings as sole focus of image; marquee/signs on buildings; trees; garden; lawn; flowers; mountains; statues; signs on campus; snow.<br>**Management**: Entrepreneurship, management, governance.<br>**International Projection**: International students, campuses, and organizations.<br>**Innovation**: Technological innovation, educational innovation and management Innovation, commercialization efforts, university differentiation.<br>**Social responsibility**: Equity, belonging.<br>**Fine arts**: Playing instrument; on stage; painting; sculpting; drawing; singing; acting; costumes; artwork; museums; theatre stills.<br>**Intercollegiate athletics**: Players on playing field; team uniforms present; sports statues near stadium cheerleaders; fans cheering; stadium and fans; sports memorabilia.",
                                    },
                                    {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{base64_encoded_image}"},
                                    },
                                ]
                            }],
                        )

                    # Get the video description.
                    video_category = (response.choices[0].message.content)
                    print(f"Video category: {video_category}")

                    # Append the data to the list
                    data.append([domain, video_length, scene_number_normalized, video_description, video_category])

# Create a DataFrame from the data
df = pd.DataFrame(data, columns=['Domain', 'Length', 'Scene', 'Description', 'Category'])
df = df.sort_values(by='Scene')

now = datetime.now()
timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
df.to_excel(f'scenes_{timestamp}.xlsx', index=False, header=False)

print(f"Data has been written to 'scenes_{timestamp}.xlsx")
with open("glue.csv", "r+") as f:
    f.seek(0)
    f.truncate()
    print("Degluesion complete!")
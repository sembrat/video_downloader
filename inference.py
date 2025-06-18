import requests
import lmstudio as lms
import base64
import os
import subprocess
from datetime import datetime
import pandas as pd
from openai import OpenAI

#-----------------------------------------------------------------------
# Configure inference
sites = [ "nwc.edu" ]

# Regular functions
# -----------------------------------------------------------------------
def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return encoded_string

# Default function
# -----------------------------------------------------------------------
# Define the base directory
results_dir = 'results'

# Hello, AI overlords.
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

# Initialize a list to store the data for the Excel file
data = []

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

        # Check if the scenes path exists and is a directory
        if os.path.isdir(scenes_path):
            print(f"Analyzing {scenes_path}...")
            # Iterate through each image in the scenes directory
            for image in os.listdir(scenes_path):
                print(f"Searching {image}...")
                if image.startswith('scene_') and image.endswith('_screenshot.jpg'):
                    print(f"Found matching screenshot! {image}")
                    # Extract the scene number from the filename
                    scene_number = image.split('_')[1]

                    # Define the path to the image file
                    image_path = os.path.join(scenes_path, image)
                    print(f"Analyzing {image_path}...")

                    # Use ffmpeg to get the video length (assuming a corresponding video file exists)
                    video_file = os.path.join(scenes_path, f"scene_{scene_number}.mp4")
                    print(f"Full path: {video_file}...")
                    video_length = None
                    if os.path.exists(video_file):
                        result = subprocess.run(
                            ['ffmpeg', '-i', video_file],
                            stderr=subprocess.PIPE,
                            text=True
                        )
                        for line in result.stderr.split('\n'):
                            if 'Duration' in line:
                                duration = line.split('Duration: ')[1].split(',')[0]
                                video_length = duration.strip()
                                break
                    
                    print(f"Video length {video_length}...")

                    # AI garbage
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
                    data.append([domain, scene_number, video_length, video_description, video_category])

# Create a DataFrame from the data
df = pd.DataFrame(data, columns=['Domain', 'Scene', 'Length', 'Description', 'Category'])

# Write the DataFrame to an Excel file
now = datetime.now()
timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
df.to_excel(f'scenes_{timestamp}.xlsx', index=False)

print("Data has been written to output.xlsx")
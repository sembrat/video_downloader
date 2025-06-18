import requests
import lmstudio as lms
import base64
import os
import subprocess
import re
from datetime import datetime
import pandas as pd
from openai import OpenAI

#-----------------------------------------------------------------------
# Configure inference
sites = [ "www.iona.edu", "www.monmouth.edu",  "www.hylesanderson.edu", "www.hilbert.edu"]
screenshots_dir = 'screenshots'

# Regular functions
# -----------------------------------------------------------------------
def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return encoded_string

# Default function
# -----------------------------------------------------------------------
# Define the base directory

# Hello, AI overlords.
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

# Initialize a list to store the data for the Excel file
data = []

# First, populate sites if the argument is empty
if not sites:
    print("Pause requires an argument to detect, currently. Closing.")
    exit

# Iterate through each domain folder in the results directory
for domain in sites:
    print(f"Analyzing {domain}...")

    # Check if the domain path is a directory
    if os.path.exists(screenshots_dir):
        print(f"Analyzing {screenshots_dir}...")
        # Iterate through each image in the scenes directory
        for image in os.listdir(screenshots_dir):
            #print(f"Searching {image}...")
            #and image.endswith('_screenshot.jpg')
            if image.startswith(domain):
                print(f"Found matching screenshot! {image}")
                # Extract the scene number from the filename
                match = re.search(r'-(\w+)\.png$', image)
                if match:
                    modal = match.group(1) # Output: desktop

                # Define the path to the image file
                image_path = os.path.join(screenshots_dir, image)
                print(f"Analyzing {image_path}...")

                # AI garbage
                base64_encoded_image = image_to_base64(image_path)
                response = client.chat.completions.create(
                    model="gemma-3-4b-it-qat",
                    messages=[
                        {
                        "role": "system",
                        "content": "You are an accessibility tool searching for the presence of assistive play or pause icons on a {domain}'s {modal} webpage screenshot. Do not include any formatting markdown, or provide any introduction to the response.",
                        }, 
                        {
                        "role": "user", 
                        "content": [
                            {
                            "type": "text",
                            "text": "Locate a pause icon, or a dual play and pause icon. Return 1 if true, 0 else.",
                            },
                            {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{base64_encoded_image}"},
                            },
                        ]
                        },
                    ],
                )

                # Sniff out a pause button.
                has_pause = (response.choices[0].message.content)
                print(f"Do we have a pause button?: {has_pause}")

                if has_pause == "1":
                    base64_encoded_image = image_to_base64(image_path)
                    response_followup = client.chat.completions.create(
                        model="gemma-3-4b-it-qat",
                        messages=[
                            {
                            "role": "system",
                            "content": "You are an accessibility tool searching for the presence of assistive play or pause icons on a {domain}'s {modal} webpage screenshot. Do not include any formatting markdown, or provide any introduction to the response.",
                            }, 
                            {
                            "role": "user", 
                            "content": [
                                {
                                "type": "text",
                                "text": "Visually describe the pause icon, or a dual play and pause icon. Describe where it is located on the webpage, its visual description, and any details about the iconography",  
                                },
                                {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{base64_encoded_image}"},
                                },
                            ]
                            },
                        ],
                    )
                    describe_pause = (response_followup.choices[0].message.content)
                    print(f"Description: {describe_pause}")
                else:
                    describe_pause = ""
                # Append the data to the list
                data.append([domain, modal, has_pause, describe_pause])

# Create a DataFrame from the data
df = pd.DataFrame(data, columns=['Domain', 'Modal', 'Pause', 'Description'])

# Write the DataFrame to an Excel file
now = datetime.now()
timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
df.to_excel(f'pausey_{timestamp}.xlsx', index=False)

print("Data has been written to pausey.xlsx")
import sys
import shutil
import requests
import hashlib
import os

def md5_of_directory(directory_path):
    md5_hash = hashlib.md5()

    for root, dirs, files in sorted(os.walk(directory_path)):
        for filename in sorted(files):
            file_path = os.path.join(root, filename)
            # Include file path in hash to detect renames/moves
            md5_hash.update(file_path.encode())

            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    md5_hash.update(chunk)

    return md5_hash.hexdigest()

try:
    (scriptname, directory, orgnzbname, jobname, reportnumber, category, group, postprocstatus, url) = sys.argv
except:
    print("No commandline parameters found")
    sys.exit(1)

destination_dir = "" + "E:\\BitTorrent\\nzbs\\"

try:
    shutil.copytree(directory, destination_dir + "\\" + jobname)
    print("Directory copied successfully.")
except FileNotFoundError:
    print("Source directory not found.")
    sys.exit(1)
except PermissionError:
    print("Permission denied.")
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred: {e}")
    sys.exit(1) 

#md5 = md5_of_directory(destination_dir)
url = "http://localhost:2468/api/webhook?apikey=a1f90dc7c1c1d57fab36530f2a590badd0bc98e37045d643"
data = {
    #'infoHash': md5,
    'path': destination_dir + jobname,
    'includeSingleEpisodes': 'true'
}

response = requests.post(url, data=data)

# Optional: Check the response
if response.ok:
    print("Request successful:", response.text)
    sys.exit(0)
else:
    print("Request failed:", response.status_code, response.text)
    sys.exit(1)
sys.exit(0)
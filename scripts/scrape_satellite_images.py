import datetime
import os
import time
import requests
from datetime import datetime, date, timedelta

def download_images(start_date, end_date, out_dir):
    """
    Download DMI images from start_date to end_date
    politely (with a sleep interval) into out_dir.
    """
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    
    delta = end_date - start_date
    for i in range(delta.days + 1):
        current_date = start_date + timedelta(days=i)
        date_str = current_date.strftime('%Y%m%d')
        
        # Try both AQUA and TERRA
        for mission in ["AQUA"]:
            url = f"https://ocean.dmi.dk/arctic/images/MODIS/Uummannaq/{date_str}{mission}.jpg"
            filename = os.path.join(out_dir, f"{date_str}_{mission}.jpg")
            
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    with open(filename, 'wb') as f:
                        f.write(r.content)
                    print(f"Downloaded {url}")
                else:
                    print(f"Missing {url} (status {r.status_code})")
            except Exception as e:
                print(f"Error {e} on {url}")
            
            # Polite delay
            time.sleep(2)  # or more if needed


start_date = datetime.strptime("20100222", "%Y%m%d").date()
end_date   = datetime.strptime("20250407", "%Y%m%d").date()

download_images(start_date, end_date, "data/satellite/aqua")
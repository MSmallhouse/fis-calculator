## Run selenium and chrome driver to scrape data from cloudbytes.dev
import time
import json
import os.path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

URL = "https://www.live-timing.com/race2.php?r=248437&u=0"

def clean_name(name):
    # prevents from breaking if name has no comma for some reason
    if "," not in name:
        print(f"skipping name: {name}")
        return ""

    name = name.lower()
    name = name.split(",")
    if len(name) >= 2:
        # remove leading whitespace from first names, left over from splitting
        name[1] = name[1][1:-1]
    return name

def handler(event=None, context=None):
    chrome_options = webdriver.ChromeOptions()
    chrome_options.binary_location = "/opt/chrome/chrome"
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-dev-tools")
    chrome_options.add_argument("--no-zygote")
    chrome_options.add_argument("--single-process")
    chrome_options.add_argument("window-size=2560x1440")
    chrome_options.add_argument("--user-data-dir=/tmp/chrome-user-data")
    chrome_options.add_argument("--remote-debugging-port=9222")
    #chrome_options.add_argument("--data-path=/tmp/chrome-user-data")
    #chrome_options.add_argument("--disk-cache-dir=/tmp/chrome-user-data")

    chrome_service = Service(executable_path=r'/opt/chromedriver')

    driver = webdriver.Chrome(service=chrome_service, options=chrome_options)
    driver.get(URL)
    driver.implicitly_wait(10)


    full_names = []
    times = []
    table = driver.find_element(By.ID, "resultTable")
    rows = table.find_elements(By.CLASS_NAME, "table")
    for row in rows:
        cols = row.find_elements(By.XPATH, ".//td")
        # only get table elements rendered with all fields
        if len(cols) >= 2:
            full_names.append(cols[2].text)
            # [:-1] splice removes trailing whitespace
            time = cols[-1].text[:-1]
            # calculate time in seconds, but only for those who finished

            if not time:
                time = float(-1)
            # edge case for times under a minute
            elif ":" not in time:
                time = float(time)
            else:
                minutes = time.split(":")[0]
                seconds = time.split(":")[1]
                time = float(minutes)*60 + float(seconds)
            times.append(time)

    # 2d list of names, with each inner list of format [last_name, first_name]
    split_names = []
    for name in full_names:
        name = clean_name(name)
        # function returns "" on error
        if not name:
            continue
        split_names.append(name)

    print(len(split_names))
    print(len(times))

    # Close webdriver and chrome service
    driver.quit()
    chrome_service.stop()
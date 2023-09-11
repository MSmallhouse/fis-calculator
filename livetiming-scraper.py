# NOTE: this used for livetiming, not vola live timing
# used the following link for building/testing
# https://www.live-timing.com/race2.php?r=248437&u=0

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService

URL = 'https://www.live-timing.com/race2.php?r=248437&u=0'

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

def chrome_instance():
    # Specify the path to the Chrome WebDriver executable
    chrome_driver_path = "C:\chromedriver.exe"

    # Create a ChromeService object
    chrome_service = ChromeService(executable_path=chrome_driver_path)

    # Initialize the Chrome WebDriver with the service
    driver = webdriver.Chrome(service=chrome_service)

    driver.get(URL)

    # Wait for page to load (adjust wait time as needed)
    driver.implicitly_wait(10)
    return driver, chrome_service


driver, chrome_service = chrome_instance()

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

# Close webdriver and chrome service
driver.quit()
chrome_service.stop()
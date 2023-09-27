## Run selenium and chrome driver to scrape data from cloudbytes.dev
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import sys
import logging
import pymysql
import pymysql.cursors
import pandas as pd

URL = "https://www.live-timing.com/race2.php?r=248437&u=0"

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# configuration values
endpoint = "fis-points-database.cby1setpagel.us-east-2.rds.amazonaws.com"
username = "admin"
password = "password"
database_name = "fis_points"

# create the database connection outside of the handler to allow connections to be
# re-used by subsequent function invocations.
try:
		connection = pymysql.connect(host=endpoint, user=username, passwd=password,
							         db=database_name, connect_timeout=5,
									 cursorclass=pymysql.cursors.DictCursor)
except pymysql.MySQLError as e:
    logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
    logger.error(e)
    sys.exit()

logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")

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

    split_names_stub = split_names[0:4]
    times_stub = times[3]

    with connection:
        with connection.cursor() as cursor:
            # get df
            query = "SELECT * FROM fis_points.point_entries"
            cursor.execute(query)
            existing_data = cursor.fetchall()

            column_names = ["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints",
                            "SLpoints", "GSpoints", "SGpoints", "ACpoints"]
            existing_df = pd.DataFrame(existing_data, columns=column_names)

        # connection not autocommitted by default
        connection.commit()
        connection.close()
    
    # make names lowercase for matching
    existing_df["Firstname"] = existing_df["Firstname"].str.lower()
    existing_df["Lastname"] = existing_df["Lastname"].str.lower()

    for name in split_names_stub:
         last_name = name[0]
         first_name = name[1]
         print(f"last_name: {last_name}")
         print(f"first_name: {first_name}")
         mask = ((existing_df["Lastname"] == last_name) &
                 (existing_df["Firstname"] == first_name))
         matching_rows = existing_df[mask]
         print(matching_rows)

    # Close webdriver and chrome service
    driver.quit()
    chrome_service.stop()


    #####################
    ##    READ THIS    ##
    #####################
    # to reduce RDS usage, query database for all info just like in 
    # get-points-list program
    # then use pandas to figure out people's points info
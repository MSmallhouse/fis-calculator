## Run selenium and chrome driver to scrape data from cloudbytes.dev
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import sys
import re
import logging
import pymysql
import pymysql.cursors
import pandas as pd
import json

# TODO: implement racers as objects for easier passing around

# NOTE: get URL, EVENT, MINIMUM_PENALTY from user
# figure out EVENT_MULTIPLIER based on EVENT
# hard-coded these for now
URL = "https://www.live-timing.com/race2.php?r=253689"
EVENT = "SLpoints"
EVENT_MULTIPLIER = 730
MINIMUM_PENALTY = 23

# configuration values
ENDPOINT = "fis-points-database.cby1setpagel.us-east-2.rds.amazonaws.com"
USERNAME = "admin"
PASSWORD = "password"
DATABASE_NAME = "fis_points"

# set up logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# create the database connection outside of the handler to allow connections to be
# re-used by subsequent function invocations.
try:
        connection = pymysql.connect(host=ENDPOINT, user=USERNAME, passwd=PASSWORD,
							         db=DATABASE_NAME, connect_timeout=5,
									 cursorclass=pymysql.cursors.DictCursor)
except pymysql.MySQLError as e:
    logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
    logger.error(e)
    sys.exit()

logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")

def get_df_from_database(cursor):
    # get df of full RDS database
    query = "SELECT * FROM fis_points.point_entries"
    cursor.execute(query)
    existing_data = cursor.fetchall()

    column_names = ["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints",
                    "SLpoints", "GSpoints", "SGpoints", "ACpoints"]
    return pd.DataFrame(existing_data, columns=column_names)

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

def get_split_names(full_names):
    split_names = []
    for name in full_names:
        name = clean_name(name)
        # function returns "" on error
        if not name:
            continue
        split_names.append(name)
    return split_names

def get_times_and_full_names(driver):
    full_names = []
    times = []
    table = driver.find_element(By.ID, "resultTable")
    rows = table.find_elements(By.CLASS_NAME, "table")
    for row in rows:
        cols = row.find_elements(By.XPATH, ".//td")

        # only get table elements rendered with all fields
        if len(cols) >= 2:
            # if someone didn't start the first run they can't
            # be considered in the race penalty calclation per fis rules
            if "DNS" in cols[-3].text:
                continue
            full_names.append(cols[2].text)
            # [:-1] splice removes trailing whitespace
            time = cols[-1].text
            
            # reg ex to remove place ex: (1) and whitespace from time
            time = re.sub(r'\s*\(\d+\)$', '', time.strip())

            # calculate time in seconds, but only for those who finished
            if not time or time == "DNF" or time == "DNS":
                time = float(-1)
            # edge case for times under a minute
            elif ":" not in time:
                time = float(time)
            else:
                minutes = time.split(":")[0]
                seconds = time.split(":")[1]
                time = float(minutes)*60 + float(seconds)
            times.append(time)
    return times, full_names

def add_points_to_racer_info(existing_df, racer_info):
    # get all points, for sorting later in part A calculation
    all_points = []

    # make names lowercase for matching
    existing_df["Firstname"] = existing_df["Firstname"].str.lower()
    existing_df["Lastname"] = existing_df["Lastname"].str.lower()

    for i, name in enumerate(racer_info):
        last_name = name[0]
        first_name = name[1]

        # find racer in df by searching first and last name matches
        mask = ((existing_df["Lastname"] == last_name) &
                (existing_df["Firstname"] == first_name))
        matching_row = existing_df[mask]

        if matching_row.empty:
            # racer not found
            print(f"\n\n Racer {first_name}, {last_name}'s points not found in database\n\n")
            racer_info[i].append(-1)
        else:
            points = matching_row.iloc[0][EVENT]
            if points == -1:
                # assume racer has no points
                # TODO: could check to be sure that racer actually has no points, and check 
                        # that this works properly
                racer_info[i].append(999.99)
            else:
                racer_info[i].append(points)

            all_points.append(points)
    return racer_info, all_points

def get_A_and_C(racer_info):
    # Get A - top 5 points out of top 10 finishers
    top_ten_finishers = racer_info[:10]

    # EDGE CASE: tie for 10th
    i = 10
    while racer_info[i][2] == racer_info[9][2]:
        top_ten_finishers.append(racer_info[i])
        i += 1

    # sort top ten by points
    # first sort takes care of edge case where 2 racers have same points
    # solution: take racer w/ higher race points ie. higher index 2
    top_ten_finishers.sort(key = lambda i: i[2], reverse=True)
    top_ten_finishers.sort(key = lambda i: i[3])
    A = 0
    for finisher in top_ten_finishers[:5]:
        A += finisher[3]

    C = 0
    winner_time = racer_info[0][2]
    for finisher in top_ten_finishers[:5]:
        C += get_race_points(winner_time, finisher[2])

    return A, C

def get_B(all_points):
    # Get B - top 5 points at start
    all_points.sort()
    return sum(all_points[:5])

def get_race_points(winner_time, finisher_time):
    return ((finisher_time/winner_time) - 1) * EVENT_MULTIPLIER

def get_driver():
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
    return driver, chrome_service

def handler(event, context):
    #try:
    #    return {
    #        "statusCode": 200,
    #        "body": json.dumps("Hello from Lambda!")
    #    }
    #except Exception as e:
    #    return {
    #        "statusCode": 500,
    #        "body": json.dumps({"error": str(e)})
    #    }
    driver, chrome_service = get_driver()
    driver.get(URL)
    driver.implicitly_wait(10)

    # list of times, with -1 corresponding to no time
    times, full_names = get_times_and_full_names(driver)

    # Close webdriver and chrome service
    driver.quit()
    chrome_service.stop()

    # initialize racer_info with split names
    racer_info = get_split_names(full_names)

    # add times to racer_info
    for i, time in enumerate(times):
        racer_info[i].append(time)

    # get points from database
    with connection:
        with connection.cursor() as cursor:
            existing_df = get_df_from_database(cursor)
        # connection not autocommitted by default
        connection.commit()
    
    # racer_info of format [[last_name, first_name, time, points]]
    # NOTE: points == -1 if racer not found in database
    racer_info, all_points = add_points_to_racer_info(existing_df, racer_info)

    # re-make all_points list to reflect adding 999.99 to calculation
    all_points = []
    for racer in racer_info:
        all_points.append(racer[-1])

    A, C = get_A_and_C(racer_info)
    B = get_B(all_points)
    penalty = max((A+B-C)/10, MINIMUM_PENALTY)

    # calculated_points for returning to website
    # of form [last, first, score]
    winner_time = racer_info[0][2]
    calculated_points = []
    for racer in racer_info:
        if racer[2] == -1:
            score = -1
        else:
            score = penalty + get_race_points(winner_time, racer[2])
        score = round(score, 2)
        calculated_points.append([racer[0], racer[1], score])
    
    for racer in calculated_points:
        print(racer)

    
    # Penalty Calculation: (A+B-C)/10
    # B is top 5 points at start
    # A is top 5 points out of top 10
    # C is race points of the top 5 out of top 10

    # Race Points P = ((Tx/To) - 1) * F where:
    # To = Time of winner in seconds
    # Tx = Time of a given competitor in seconds
    # F is Event multipler
        # Downhill: F = 1250
        # Slalom: F = 730
        # Giant Slalom: F = 1010
        # Super-G: F = 1190
        # Alpine Combined: F = 1360
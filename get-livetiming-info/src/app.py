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
EVENT = "GSpoints"
# NOTE: get event_multiplier from looking at event
# hard-coded for now for simplicity
EVENT_MULTIPLIER = 1010
# NOTE: get minimum penalty from user
# hard-coded for now
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
            racer_info[i].append(-1)
        else:
            points = matching_row.iloc[0][EVENT]
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
def handler(event=None, context=None):
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

    with connection:
        with connection.cursor() as cursor:
            existing_df = get_df_from_database(cursor)

        # connection not autocommitted by default
        connection.commit()
    
    # add points to racer info
    # racer_info of format [[last_name, first_name, time, points]]
    # NOTE: points == -1 if racer not found in database
    racer_info, all_points = add_points_to_racer_info(existing_df, racer_info)

    A, C = get_A_and_C(racer_info)
    B = get_B(all_points)

    #NOTE: get minimum penalty as input
    # penalty = max of minium penalty and below calculation
    penalty = max((A+B-C)/10, MINIMUM_PENALTY)

    # for returning to website
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
    print(calculated_points)

    # EDGE CASE: 2 or more racers have 5th best points
        # racer w/ higher race points is considered
    # calculate C by race points


    # Penalty Calculation: (A+B-C)/10
    # B is top 5 points at start
    # A is top 5 points out of top 10
    # C is race points of the top 5 out of top 10
    # Any need to make sure that people in the top 5 actually start?

    # also have an input for event, since there's an event multiplier for race points
    # Race Points P = ((Tx/To) - 1) * F where:
    # To = Time of winner in seconds
    # Tx = Time of a given competitor in seconds
    # F is Event multipler
        # Downhill: F = 1250
        # Slalom: F = 730
        # Giant Slalom: F = 1010
        # Super-G: F = 1190
        # Alpine Combined: F = 1360

    # Add thing to get minimum penalty from user


    #####################
    ##    READ THIS    ##
    #####################
    # to reduce RDS usage, query database for all info just like in 
    # get-points-list program
    # then use pandas to figure out people's points info
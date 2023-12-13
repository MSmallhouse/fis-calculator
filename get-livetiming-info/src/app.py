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

class Race:
    def __init__(self, url, min_penalty, event):
        self.url = url
        self.min_penalty = int(min_penalty)

        self.event = event
        if event == "SLpoints":
            self.event_multiplier = 730
        if event == "GSpoints":
            self.event_multiplier = 1010
        if event == "SGpoints":
            self.event_multiplier = 1190
        if event == "DHpoints":
            self.event_multiplier = 1250
        
        self.competitors = []
        self.starting_racers_points = []
        self.winning_time = 0
        self.penalty = 0

class Competitor:
    def __init__(self, full_name):
        self.full_name = full_name
        self.first_name = "abc"
        self.last_name = ""
        self.time = -1
        self.fis_points = 999.99
        self.score = -1

    def __str__(self):
        return f"{self.full_name} score: {self.score}"

def get_points(race):
    # database configuration values
    ENDPOINT = "fis-points-database.cby1setpagel.us-east-2.rds.amazonaws.com"
    USERNAME = "admin"
    PASSWORD = "password"
    DATABASE_NAME = "fis_points"

    # set up logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # make database connection
    try:
        connection = pymysql.connect(host=ENDPOINT, user=USERNAME, passwd=PASSWORD,
                                    db=DATABASE_NAME, connect_timeout=5,
                                    cursorclass=pymysql.cursors.DictCursor)
    except pymysql.MySQLError as e:
        logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
        logger.error(e)
        sys.exit()
    logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")

    # set up selenium driver
    driver, chrome_service = get_driver()
    driver.get(race.url)
    driver.implicitly_wait(10)

    scrape_times_and_names(driver, race)

    # Close webdriver and chrome service
    driver.quit()
    chrome_service.stop()

    split_full_name_to_first_last(race)

    points_list_df = get_df_from_database(connection)
    add_points_to_competitors(points_list_df, race)
    race.starting_racers_points = [competitor.fis_points for competitor in race.competitors]

    A, C = get_A_and_C(race)
    B = get_B(race)
    penalty = max((A+B-C)/10, race.min_penalty)
    race.penalty = round(penalty, 2)

    for competitor in race.competitors:
        # competitor didn't finish or didn't start
        if competitor.time == -1:
            competitor.score = -1
            continue
        competitor.score = round(get_race_points(competitor, race) + race.penalty, 2)
    
    return

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
    
    # Penalty Edge cases:
    # two or more competitors ranked 10th:
        # all can be considered as top 10 for calculation
    # two or more competitors in top 10 have 5th best points:
        # person with higher race points used for penalty calculation

def scrape_times_and_names(driver, race):
    result_table = driver.find_element(By.ID, "resultTable")
    result_rows = result_table.find_elements(By.CLASS_NAME, "table")
    for result in result_rows:
        result_entry = result.find_elements(By.XPATH, ".//td")

        # only get result elements rendered with all fields
        if len(result_entry) < 3:
            continue

        # if someone didn't start the first run they can't
        # be considered in the race penalty calclation per fis rules
        if "DNS" in result_entry[-3].text:
            continue

        full_name = result_entry[2].text
        competitor = Competitor(full_name)
        competitor.time = time_to_float(result_entry[-1].text)
        race.competitors.append(competitor)

    race.winning_time = race.competitors[0].time
    return

def time_to_float(time):
    # reg ex to remove place ex: (1) and whitespace from time
    time = re.sub(r'\s*\(\d+\)$', '', time.strip())

    # calculate time in seconds, but only for those who finished
    if not time or time == "DNF" or time == "DNS":
        return -1
    # edge case for times under a minute
    elif ":" not in time:
        time = float(time)
    else:
        minutes = time.split(":")[0]
        seconds = time.split(":")[1]
        time = float(minutes)*60 + float(seconds)
    return time


def split_full_name_to_first_last(race):
    for competitor in race.competitors:
        name_segments = clean_name(competitor.full_name)
        competitor.last_name = name_segments[0]
        competitor.first_name = name_segments[1]

def clean_name(name):
    # prevents from breaking if name has no comma for some reason
    if "," not in name:
        print(f"ERROR: {name} could not be parsed correctly")
        return ["", ""]

    name = name.lower()
    name = name.split(",")
    if len(name) >= 2:
        #TODO: use strip here instead?
        # remove leading whitespace from first names, left over from splitting
        name[1] = name[1][1:-1]
    return name

def get_df_from_database(connection):
    with connection:
        with connection.cursor() as cursor:
            # get df of full RDS database
            query = "SELECT * FROM fis_points.point_entries"
            cursor.execute(query)
            existing_data = cursor.fetchall()

            column_names = ["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints",
                            "SLpoints", "GSpoints", "SGpoints", "ACpoints"]

            # connection not autocommitted by default
            connection.commit()
            cursor.close()
    return pd.DataFrame(existing_data, columns=column_names)

def add_points_to_competitors(existing_df, race):
    # lowercase for accurate matching
    existing_df["Firstname"] = existing_df["Firstname"].str.lower()
    existing_df["Lastname"] = existing_df["Lastname"].str.lower()

    for competitor in race.competitors:
        mask = ((existing_df["Lastname"] == competitor.last_name) &
                (existing_df["Firstname"] == competitor.first_name))
        matching_row = existing_df[mask]

        if matching_row.empty:
            print(f"ERROR: Racer {competitor.first_name}, {competitor.last_name}'s points not found in database")
            continue

        points = matching_row.iloc[0][race.event]
        if points == -1:
            # assume racer has no points
            # TODO: could check to be sure that racer actually has no points, and check 
                    # that this works properly
            competitor.fis_points = 999.99
        else:
            competitor.fis_points = points
    return

def get_A_and_C(race):
    top_ten_finishers = race.competitors[:10]

    # EDGE CASE: tie for 10th
    # consider all ties to have finished in the top 10 per fis rules
    i = 10
    while race.competitors[i].time == race.competitors[9].time:
        top_ten_finishers.append(race.competitors[i])
        i += 1
    
    top_ten_sorted = sorted(top_ten_finishers, key=point_sort)

    # A = top 5 points out of top 10 finishers
    A = 0
    for competitor in top_ten_sorted[:5]:
        A += competitor.fis_points

    # C = race points of top 5 ranked racers inside top 10 finishers
    C = 0
    for competitor in top_ten_sorted[:5]:
        C += get_race_points(competitor, race)
    return A, C

# sorting key - on case of tie for points, put the slower racer first per fis rules
def point_sort(competitor):
    return (competitor.fis_points, -competitor.time) # negative competitor.time to sort descending

def get_race_points(competitor, race):
    race_points = ((competitor.time/race.winning_time) - 1) * race.event_multiplier
    return round(race_points, 2)

def get_B(race):
    # B = top 5 points at start
    race.starting_racers_points.sort()
    return sum(race.starting_racers_points[:5])

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
    # TODO: build 2 more webscrapers - one for vola live timing and one for fis
            # verify that these work even as a race is live
            # add a method to Race class assigning proper scraping function
            # could even have scrapers in another file??? not sure if works with lambda

    # TODO: store not-found racers separately for displaying 
    
    #url = event["queryStringParameters"]["url"]
    #min_penalty = event["queryStringParameters"]["min-penalty"]
    #race_event = event["queryStringParameters"]["event"]
    #race = Race(url, min_penalty, race_event)
    URL = "https://www.live-timing.com/race2.php?r=253656"
    MIN_PENALTY = "15"
    EVENT = "SGpoints"
    race = Race(URL, MIN_PENALTY, EVENT)

    get_points(race)
    for competitor in race.competitors:
        print(competitor)
    try:
        return {
            "statusCode": 200,
            "body": json.dumps(race.competitors)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
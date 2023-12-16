from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

import requests
import re
import sys
import logging
import pymysql
import pymysql.cursors
import pandas as pd

class Competitor:
    def __init__(self, full_name):
        self.full_name = full_name
        self.first_name = ""
        self.last_name = ""
        self.time = -1
        self.fis_points = 1000
        self.score = -1

    def __str__(self):
        return f"{self.full_name} score: {self.score}"

def connect_to_database(race):
    race.logger = logging.getLogger()
    race.logger.setLevel(logging.INFO)

    # make database connection
    try:
        race.connection = pymysql.connect(host=race.ENDPOINT, user=race.USERNAME,
                                        passwd=race.PASSWORD,db=race.DATABASE_NAME,
                                        connect_timeout=5,
                                        cursorclass=pymysql.cursors.DictCursor)
    except pymysql.MySQLError as e:
        race.logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
        race.logger.error(e)
        sys.exit()
    race.logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")
    return

# Initialize selenium, used as webscraper to get names and race times
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

# remove whitespace and commas
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
        name[1] = name[1].strip()
    return name

def time_to_float(time):
    # reg ex to remove place ex: (1) and whitespace from time
    time = re.sub(r'\s*\(\d+\)$', '', time.strip())

    # calculate time in seconds, but only for those who finished
    if not time or time == "DNF" or time == "DNS":
        return 9999
    # edge case for times under a minute
    elif ":" not in time:
        time = float(time)
    else:
        minutes = time.split(":")[0]
        seconds = time.split(":")[1]
        time = float(minutes)*60 + float(seconds)
    return time

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

# wrapper to select correct scraper based on which website was given
def scrape_results(race):
    #TODO: add vola and fis-scraper here based on url content
    #livetiming_scraper(race)
    livetiming_scraper(race)

def livetiming_scraper(race):
    URL = "https://www.live-timing.com/includes/aj_race." + race.url.split(".")[-1]
    # only get first names, run time
    def is_valid_field(field):
        return (field.startswith("m=") or
                field.startswith("fp=") or
                field.startswith("r1") or
                field.startswith("r2") or
                field.startswith("tt="))

    r = requests.get(URL)
    content = r.text

    filtered_competitors = [field.strip() for field in content.split("|") if is_valid_field(field)]

    # split into 2d list of racers
    split_racers = []
    temp = []
    for field in filtered_competitors:
        if field[0:2] == "m=":
            split_racers.append(temp)
            temp = []
        temp.append(field)
    split_racers.append(temp)
    split_racers = split_racers[1:]

    starters = []
    for racer in split_racers:
        # only consider racers who started the first run
        if "DNS" in racer[2]:
            continue
        starters.append(racer)
    
    for starter in starters:
        # strip off "m= from name"
        full_name = starter[0][2:]
        competitor = Competitor(full_name)

        # filter for did not finish, did not start, or disqualified
        if ("tt=" not in starter[-1] or
            "DNF" in "".join(starter) or
            "DNS" in "".join(starter) or
            "DQ" in "".join(starter)):
            competitor.time = 9999
        else:
            competitor.time = time_to_float(starter[-1][3:])
        race.competitors.append(competitor)
        race.winning_time = min(race.winning_time, competitor.time)
    return

def livetiming_scraper_selenium(race):
    # set up selenium driver
    driver, chrome_service = get_driver()
    driver.get(race.url)
    driver.implicitly_wait(10)

    result_table = driver.find_element(By.ID, "resultTable")
    result_rows = result_table.find_elements(By.CLASS_NAME, "table")
    for result in result_rows:
        result_entry = result.find_elements(By.XPATH, ".//td")

        # disreguards row with an ad that shows up on webpage
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

    # Close webdriver and chrome service
    driver.quit()
    chrome_service.stop()
    return
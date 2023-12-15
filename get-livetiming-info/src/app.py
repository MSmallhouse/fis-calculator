from selenium.webdriver.common.by import By
import sys
import logging
import pymysql
import pymysql.cursors
import pandas as pd
import json

# imports from user-defined modules
from utils import get_driver
from utils import clean_name
from utils import time_to_float
from utils import get_df_from_database

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

class Race:
    def __init__(self, url, min_penalty, event):
        # race information variables
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
        
        # variabes for calculating penalty
        self.competitors = []
        self.starting_racers_points = []
        self.winning_time = 0
        self.penalty = 0

        # database configuration values
        self.ENDPOINT = "fis-points-database.cby1setpagel.us-east-2.rds.amazonaws.com"
        self.USERNAME = "admin"
        self.PASSWORD = "password"
        self.DATABASE_NAME = "fis_points"

    def get_points(self):
        self.connect_to_database()
        self.scrape_times_and_names()
        self.split_names()

        self.points_list_df = get_df_from_database(self.connection)
        self.add_points_to_competitors()
        self.starting_racers_points = [competitor.fis_points for competitor in self.competitors]

        self.calculate_penalty()


        for competitor in self.competitors:
            # competitor didn't finish or didn't start
            if competitor.time == -1:
                competitor.score = -1
                continue
            competitor.score = round(get_race_points(competitor, self) + self.penalty, 2)
        
        return
    
    def connect_to_database(self):
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)

        # make database connection
        try:
            self.connection = pymysql.connect(host=self.ENDPOINT, user=self.USERNAME,
                                         passwd=self.PASSWORD,db=self.DATABASE_NAME,
                                         connect_timeout=5,
                                         cursorclass=pymysql.cursors.DictCursor)
        except pymysql.MySQLError as e:
            self.logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
            self.logger.error(e)
            sys.exit()
        self.logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")

    def scrape_times_and_names(self):
        # set up selenium driver
        driver, chrome_service = get_driver()
        driver.get(self.url)
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
            self.competitors.append(competitor)

        self.winning_time = self.competitors[0].time

        # Close webdriver and chrome service
        driver.quit()
        chrome_service.stop()
        return

    def split_names(self):
        for competitor in self.competitors:
            name_segments = clean_name(competitor.full_name)
            competitor.last_name = name_segments[0]
            competitor.first_name = name_segments[1]

    def add_points_to_competitors(self):
        # lowercase for accurate matching
        existing_df = self.points_list_df
        existing_df["Firstname"] = existing_df["Firstname"].str.lower()
        existing_df["Lastname"] = existing_df["Lastname"].str.lower()

        for competitor in self.competitors:
            mask = ((existing_df["Lastname"] == competitor.last_name) &
                    (existing_df["Firstname"] == competitor.first_name))
            matching_row = existing_df[mask]

            if matching_row.empty:
                print(f"ERROR: Racer {competitor.first_name}, {competitor.last_name}'s points not found in database")
                continue

            points = matching_row.iloc[0][self.event]
            if points == -1:
                # assume racer has no points
                # TODO: could check to be sure that racer actually has no points, and check 
                        # that this works properly
                competitor.fis_points = 999.99
            else:
                competitor.fis_points = points
        return

    def calculate_penalty(self):
        A, C = self.get_A_and_C()
        B = self.get_B()
        penalty = max((A+B-C)/10, self.min_penalty)
        self.penalty = round(penalty, 2)

    def get_A_and_C(self):
        top_ten_finishers = self.competitors[:10]

        # EDGE CASE: tie for 10th
        # consider all ties to have finished in the top 10 per fis rules
        i = 10
        while self.competitors[i].time == self.competitors[9].time:
            top_ten_finishers.append(self.competitors[i])
            i += 1
        
        top_ten_sorted = sorted(top_ten_finishers, key=point_sort)

        # A = top 5 points out of top 10 finishers
        A = 0
        for competitor in top_ten_sorted[:5]:
            A += competitor.fis_points

        # C = race points of top 5 ranked racers inside top 10 finishers
        C = 0
        for competitor in top_ten_sorted[:5]:
            C += get_race_points(competitor, self)
        return A, C

    def get_B(self):
        # B = top 5 points at start
        self.starting_racers_points.sort()
        return sum(self.starting_racers_points[:5])

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

# sorting key - on case of tie for points, put the slower racer first per fis rules
def point_sort(competitor):
    return (competitor.fis_points, -competitor.time) # negative competitor.time to sort descending
def get_race_points(competitor, race):
    race_points = ((competitor.time/race.winning_time) - 1) * race.event_multiplier
    return round(race_points, 2)


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
    URL = "https://www.live-timing.com/race2.php?r=253738"
    MIN_PENALTY = "23"
    EVENT = "GSpoints"
    race = Race(URL, MIN_PENALTY, EVENT)

    race.get_points()
    not_finished = []
    finishers = []
    for competitor in race.competitors:
        # points = 1000 indicates not found in database
        if competitor.fis_points == 1000:
            not_finished.append(f"{competitor.full_name}: points not found in database, calculations might not be accurate")
        # score = -1 indicates did not finish or did not start
        if competitor.score != -1:
            finishers.append(competitor)

    output = [(f"{competitor.full_name}: {competitor.score}") for competitor in finishers]
    for racer in not_finished:
        output.insert(0, racer)
    try:
        return {
            "statusCode": 200,
            "body": json.dumps(output)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
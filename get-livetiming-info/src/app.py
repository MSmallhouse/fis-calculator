from selenium.webdriver.common.by import By
import json

# imports from user-defined modules
from utils import connect_to_database
from utils import scrape_results
from utils import clean_name
from utils import get_df_from_database

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
        self.winning_time = 9999
        self.penalty = 0

        # database configuration values
        self.ENDPOINT = "fis-points-database.cby1setpagel.us-east-2.rds.amazonaws.com"
        self.USERNAME = "admin"
        self.PASSWORD = "password"
        self.DATABASE_NAME = "fis_points"

    def get_points(self):
        connect_to_database(self)
        scrape_results(self)
        self.split_names()

        points_df = get_df_from_database(self.connection)
        self.add_points_to_competitors(points_df)

        starting_racers_points = [competitor.fis_points for competitor in self.competitors]
        self.calculate_penalty(starting_racers_points)
        self.assign_scores()
        return
    
    def split_names(self):
        for competitor in self.competitors:
            name_segments = clean_name(competitor.full_name)
            competitor.last_name = name_segments[0]
            competitor.first_name = name_segments[1]
        return

    def add_points_to_competitors(self, points_df):
        # lowercase for accurate matching
        points_df["Firstname"] = points_df["Firstname"].str.lower()
        points_df["Lastname"] = points_df["Lastname"].str.lower()

        for competitor in self.competitors:
            mask = ((points_df["Lastname"] == competitor.last_name) &
                    (points_df["Firstname"] == competitor.first_name))
            matching_row = points_df[mask]

            if matching_row.empty:
                print(f"ERROR: Racer {competitor.first_name}, {competitor.last_name}'s points not found in database")
                continue

            points = matching_row.iloc[0][self.event]
            if points == -1:
                # racer has not scored any points yet, assign them highest value
                competitor.fis_points = 999.99
            else:
                competitor.fis_points = points
        return

    def calculate_penalty(self, starting_racers_points):
        A, C = self.get_A_and_C()
        B = self.get_B(starting_racers_points)
        penalty = max((A+B-C)/10, self.min_penalty)
        self.penalty = round(penalty, 2)
        return

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

    def get_B(self, starting_racers_points):
        # B = top 5 points at start
        starting_racers_points.sort()
        return sum(starting_racers_points[:5])

    def assign_scores(self):
        for competitor in self.competitors:
            # competitor didn't finish or didn't start
            if competitor.time == -1:
                competitor.score = -1
                continue
            competitor.score = round(get_race_points(competitor, self) + self.penalty, 2)
        return

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
        #
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
from selenium.webdriver.common.by import By
import json

# imports from user-defined modules
from utils import connect_to_database
from utils import scrape_results

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

        starting_racers_points = []
        for competitor in self.competitors:
            if competitor.fis_points == -1:
                continue

            starting_racers_points.append(competitor.fis_points)
        self.calculate_penalty(starting_racers_points)
        self.assign_scores()
        return
    

    def calculate_penalty(self, starting_racers_points):
        A, C = self.get_A_and_C()
        B = self.get_B(starting_racers_points)
        penalty = max((A+B-C)/10, self.min_penalty)
        self.penalty = round(penalty, 2)
        return

    def get_A_and_C(self):
        self.competitors = sorted(self.competitors, key=time_sort)
        top_ten_finishers = self.competitors[:10]

        # EDGE CASE: tie for 10th
        # consider all ties to have finished in the top 10 per fis rules
        if len(self.competitors) >= 10:
            i = 10
            while self.competitors[i].time == self.competitors[9].time:
                top_ten_finishers.append(self.competitors[i])
                i += 1

        top_ten_sorted_by_points = sorted(top_ten_finishers, key=point_sort)

        # A = top 5 points out of top 10 finishers
        # C = race points of top 5 ranked racers inside top 10 finishers
        A = 0
        C = 0
        for competitor in top_ten_sorted_by_points[:5]:
            A += competitor.fis_points
            C += get_race_points(competitor, self)
        return A, C

    def get_B(self, starting_racers_points):
        #TODO: get top 5 out of seed
        # make sure to check DNS - time == 9999
        # B = top 5 points at start
        starting_racers_points.sort()
        return sum(starting_racers_points[:5])

    def assign_scores(self):
        for competitor in self.competitors:
            # competitor didn't finish or didn't start
            if competitor.time == 9999:
                competitor.score = -1
                continue
            competitor.score = round(get_race_points(competitor, self) + self.penalty, 2)
        return

def time_sort(competitor):
    return competitor.time

# sorting key - on case of tie for points, put the slower racer first per fis rules
def point_sort(competitor):
    return (competitor.fis_points, -competitor.time) # negative competitor.time to sort descending

def get_race_points(competitor, race):
    race_points = ((competitor.time/race.winning_time) - 1) * race.event_multiplier
    return round(race_points, 2)

def handler(event, context):
    #url = event["queryStringParameters"]["url"]
    #min_penalty = event["queryStringParameters"]["min-penalty"]
    #race_event = event["queryStringParameters"]["event"]
    #race = Race(url, min_penalty, race_event)
    URL = "https://vola.ussalivetiming.com/race/usa-me-sunday-river-womens-open-fis_37114.html"
    MIN_PENALTY = "23"
    EVENT = "SLpoints"
    race = Race(URL, MIN_PENALTY, EVENT)

    race.get_points()
    points_not_found = ""
    finishers = []
    for competitor in race.competitors:
        # points = 1000 indicates not found in database
        #
        if competitor.fis_points == 1000:
            # fix for Cole since he signed up late
            if competitor.full_name == "PALCHAK, Cole":
                continue

            points_not_found += competitor.full_name + ' '
        # score = -1 indicates did not finish or did not start
        if competitor.score != -1:
            finishers.append(competitor)

    output = [
        {
            "place": i+1,
            "place": "" if i > 0 and competitor.time == finishers[i-1].time else i+1,
            "name": competitor.full_name,
            "score": competitor.score,
            "points": competitor.fis_points
        }
        for i, competitor in enumerate(finishers)
    ]
    return_data = {
        "results": output,
        "notFound": points_not_found
    }
    
    try:
        return {
            "statusCode": 200,
            "body": json.dumps(return_data)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
from selenium.webdriver.common.by import By
import json
import logging

# imports from user-defined modules
from utils import connect_to_database
from utils import scrape_results

FIS_EVENT_MAXIMUMS = {
    "SLpoints": 165,
    "GSpoints": 220,
    "SGpoints": 270,
    "DHpoints": 330,
    "ACpoints": 270
}
USSA_EVENT_MAXIMUMS = {
    "SLpoints": 360,
    "GSpoints": 530,
    "SGpoints": 660,
    "DHpoints": 820,
    "ACpoints": 660
}

class Race:
    def __init__(self, url, min_penalty, event, is_fis_race):
        # race information variables
        self.url = url
        self.min_penalty = int(min_penalty)
        self.event = event
        self.is_fis_race = is_fis_race
        if event == "SLpoints":
            self.event_multiplier = 730
        if event == "GSpoints":
            self.event_multiplier = 1010
        if event == "SGpoints":
            self.event_multiplier = 1190
        if event == "DHpoints":
            self.event_multiplier = 1250
        if event == "ACpoints":
            self.event_multiplier = 1360
        
        # variabes for calculating penalty
        self.competitors = []
        self.winning_time = 9999
        self.penalty = 0

    def get_points(self):
        if "live-timing" not in self.url: # don't need to connect to database for races on livetiming
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
            # edge cases for those who finish with sufficiently high points:
            if self.is_fis_race and competitor.fis_points >= FIS_EVENT_MAXIMUMS[self.event]:
                A += FIS_EVENT_MAXIMUMS[self.event]
            elif not self.is_fis_race and competitor.fis_points >= USSA_EVENT_MAXIMUMS[self.event]:
                A += USSA_EVENT_MAXIMUMS[self.event]
            # normal case:
            else:
                A += competitor.fis_points
            C += get_race_points(competitor, self)
        return A, C
    
    def get_B(self, starting_racers_points):
        #TODO: get top 5 out of seed
        # make sure to check DNS - time == 9999
        # B = top 5 points at start
        starting_racers_points.sort()
        B = 0
        for points in starting_racers_points[:5]:
            # edge cases for those who finish with sufficiently high points:
            if self.is_fis_race and points >= FIS_EVENT_MAXIMUMS[self.event]:
                B += FIS_EVENT_MAXIMUMS[self.event]
            elif not self.is_fis_race and points >= USSA_EVENT_MAXIMUMS[self.event]:
                B += USSA_EVENT_MAXIMUMS[self.event]
            # normal case:
            else:
                B += points
        return B

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
    url = event["queryStringParameters"]["url"]
    min_penalty = event["queryStringParameters"]["min-penalty"]
    is_fis_race = True
    race_event = event["queryStringParameters"]["event"]

    if min_penalty < "0":
        is_fis_race = False
        min_penalty = "40"
    race = Race(url, min_penalty, race_event, is_fis_race)
    #URL = "https://www.live-timing.com/race2.php?r=267000"
    #MIN_PENALTY = "23"
    #EVENT = "GSpoints"
    #is_fis_race = False
    #race = Race(URL, MIN_PENALTY, EVENT, is_fis_race)

    race.get_points()
    points_not_found = ""
    finishers = []
    for competitor in race.competitors:
        # points = 1000 indicates not found in databas
        #
        if competitor.fis_points == 1000:
            points_not_found += competitor.full_name + ' '

        # vola ussa races require full name to be scrambled, restore here for nice printing
        if competitor.temp_full_name:
            competitor.full_name = competitor.temp_full_name
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
import json
import logging
import traceback

# imports from user-defined modules
from utils import connect_to_database
from utils import scrape_results
from exceptions import UserFacingException

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
    def __init__(self, url, min_penalty, adder, event, is_fis_race):
        # race information variables
        self.url = url
        self.min_penalty = int(min_penalty)
        self.adder = int(adder)
        self.event = event
        self.is_fis_race = is_fis_race
        self.is_tech_race = True
        if event == "SLpoints":
            self.event_multiplier = 730
        if event == "GSpoints":
            self.event_multiplier = 1010
        if event == "SGpoints":
            self.event_multiplier = 1190
            self.is_tech_race = False
        if event == "DHpoints":
            self.event_multiplier = 1250
            self.is_tech_race = False
        if event == "ACpoints":
            self.event_multiplier = 1360
        
        # variabes for calculating penalty
        self.competitors = []
        self.winning_time = 9999
        self.penalty = 0

        self.url_type = ''
        if 'vola' in url:
            self.url_type = 'vola'
        elif 'live-timing' in url:
            self.url_type = 'live-timing'
        else:
            self.url_type = 'fis'
        
        self.r1_times = []
        self.r2_times = []

        self.are_scores_projections = False
        self.is_startlist_only = False

    def first_run_projected_scores_adjustment(self):
        self.are_scores_projections = True
        if self.event != "SLpoints" and self.event != "GSpoints":
            self.are_scores_projections = False
            return

        # early return if any r2 times found
        for competitor in self.competitors:
            if hasattr(competitor, "r2_time"):
                self.are_scores_projections = False
                return

        for competitor in self.competitors:
            if not hasattr(competitor, "r1_time"):
                continue
            if competitor.r1_time == 9999: #dnf first run
                continue
            
            competitor.time = competitor.r1_time * 2
            self.winning_time = min(self.winning_time, competitor.time)

    def log_url_in_cloudwatch(self):
        # uses CloudWatch Embedded Metric Format logs to track how many of each url is passed
        url_clean = str(self.url).strip()
        emf_log = {
            "_aws": {
                "CloudWatchMetrics": [
                    {
                        "Namespace": "LambdaURLHits",
                        "Dimensions": [["URL"]],
                        "Metrics": [{"Name": "UrlFormSubmission", "Unit": "Count"}]
                    }
                ]
            },
            "URL": url_clean,
            "UrlFormSubmission": 1
        }
        self.logger.info(json.dumps(emf_log))
        return

    def get_points(self):
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)
        self.logger.info(f"URL PASSED: {self.url}")
        self.log_url_in_cloudwatch()
        if self.url_type != 'live-timing':
            connect_to_database(self)
        scrape_results(self)

        if self.is_startlist_only:
            self.competitors = sorted(self.competitors, key=lambda c: c.bib)
            return
            
        self.first_run_projected_scores_adjustment()

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
        #uncomment when 8 point adder gets put in, check 1st page download https://www.fis-ski.com/DB/alpine-skiing/fis-points-lists.html
        #penalty = max(((A+B-C)/10) + self.adder, self.min_penalty)
        penalty = max(((A+B-C)/10), self.min_penalty)
        self.penalty = round(penalty, 2)
        return

    def get_A_and_C(self):
        self.competitors = sorted(self.competitors, key=time_sort)
        top_ten_finishers = []
        for i in range(min(10, len(self.competitors))):
            if self.competitors[i].time == 9999:
                continue
            top_ten_finishers.append(self.competitors[i])

        # EDGE CASE: tie for 10th
        # consider all ties to have finished in the top 10 per fis rules
        if len(self.competitors) > 10:
            i = 10
            while self.competitors[i].time == self.competitors[9].time and self.competitors[i].time != 9999 and self.competitors[9].time != 9999:
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

def float_to_time_string(seconds):
    if seconds is None:
        return None
    
    minutes, secs = divmod(seconds, 60)
    if minutes:
        return f'{int(minutes)}:{secs:05.2f}'
    else:
        return f'{secs:.2f}'

def handler(event, context):
    return_data = {}

    try:
        url = event["queryStringParameters"]["url"]
        if url == 'preload':
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "preload successful"})
            }

        # put this down here so page visits don't trigger logging from the lambda function preload - only form fills
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.info(f"params: {event['queryStringParameters']}")

        min_penalty = event["queryStringParameters"]["min-penalty"].split(",")[0]
        adder = event["queryStringParameters"]["min-penalty"].split(",")[1]
        is_fis_race = True
        race_event = event["queryStringParameters"]["event"]

        if min_penalty < "0":
            is_fis_race = False
            min_penalty = "40"
        race = Race(url, min_penalty, adder, race_event, is_fis_race)
        #URL = "0827"
        #MIN_PENALTY = "60"
        #ADDER = "8"
        #EVENT = "SLpoints"
        #is_fis_race = True
        #race = Race(URL, MIN_PENALTY, ADDER, EVENT, is_fis_race)

        race.get_points()
        points_not_found = ""
        finishers = []
        for competitor in race.competitors:
            # vola ussa races require full name to be scrambled, restore here for nice printing
            if competitor.temp_full_name:
                competitor.full_name = competitor.temp_full_name

            # points = 1000 indicates not found in databas
            if competitor.fis_points == 1000:
                points_not_found += competitor.full_name + ' '

            # score = -1 indicates did not finish or did not start
            if competitor.score != -1 or race.is_startlist_only:
                finishers.append(competitor)

        output = [
            {
                "place": i+1,
                "place": "" if (i > 0 and competitor.time == finishers[i-1].time) and not race.is_startlist_only else i+1,
                "name": competitor.full_name,
                "score": competitor.score,
                "points": competitor.fis_points,
                # only include run time and ranks if they exist
                **(
                    {
                        key: value
                        for key, value in {
                            "r1_time": float_to_time_string( getattr(competitor, "r1_time", None) ),
                            "r1_rank": getattr(competitor, "r1_rank", None),
                            "r2_time": float_to_time_string( getattr(competitor, "r2_time", None) ),
                            "r2_rank": getattr(competitor, "r2_rank", None),
                            "r3_time": float_to_time_string( getattr(competitor, "r3_time", None) ),
                            "r3_rank": getattr(competitor, "r3_rank", None),
                            "time": float_to_time_string(competitor.time)
                        }.items()
                        #if race.url_type == "fis" and value is not None
                        if value is not None
                    }
                )
            }
            for i, competitor in enumerate(finishers)
        ]
        return_data = {
            "results": output,
            "event": race.event,
            "hasRunTimes": True,
            "areScoresProjections": race.are_scores_projections,
            "notFound": points_not_found,
            "hasThirdRun": 'r3_time' in output[0].keys(),
            "isStartlist": race.is_startlist_only,
        }

        return {
            "statusCode": 200,
            "body": json.dumps(return_data)
        }

    except UserFacingException as e:
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.error(f"USER RAISED ERROR: {e}\nStack Trace:\n{traceback.format_exc()}")
        return {
            "statusCode": e.status_code,
            "body": json.dumps({"error": str(e)})
        }

    except Exception as e:
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.error(f"ERROR: {e}\nStack Trace:\n{traceback.format_exc()}")

        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
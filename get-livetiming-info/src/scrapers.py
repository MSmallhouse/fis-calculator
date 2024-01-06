import requests
import re

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


def vola_scraper(race):
    def extract_race_id(url):
        race_id = url.split("_")[1]
        return race_id.split(".")[0]

    def send_request(command, run_number):
        race_id = extract_race_id(race.url)
        url = 'https://vola.ussalivetiming.com/livetiming.php?command=' + command
        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Host': 'vola.ussalivetiming.com',
            'Origin': 'https://vola.ussalivetiming.com',
            'Referer': race.url,
            'Sec-Ch-Ua': '"Google Chrome";v="117", "Not;A=Brand";v="8", "Chromium";v="117"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Linux"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
        }
        payload = {
            'command': command,
            'race_idx': race_id,
            ###TODO FOR SPEED, GET RUN 1???
            'runno': run_number,
        }

        return requests.post(url, headers=headers, data=payload)

    def extract_names_and_times():
        valid_fields = set()
        fields = send_request("GetHeatListFields", "1")
        if fields.status_code == 200:
            # extract where names and times are stored
            data = fields.json()
            fields = data['DATA']['field']
            for field in fields:
                if "Name" in field['title'] or "Time" in field['title']:
                    valid_fields.add((field['grid'], field['col']))

        values = send_request("GetHeatListValues", "1")

        #TODO: sometimes has Name, sometimes First Name and Last Name
        #NOTE: for now, assume just name
        names_and_times = []
        if values.status_code == 200:
            # get names and times 
            data = values.json()
            fields = data['DATA']['fieldvalue']
            for field in fields:
                # HTML non-breaking space, doesn't contain data so skip these
                if "&nbsp" in field['value']:
                    continue
                if (field['grid'], field['col']) in valid_fields:
                    names_and_times.append(field)
        return names_and_times

    def initialize_starting_racers():
        names_and_times = extract_names_and_times()
        racers = set() # for duplicate detection
        for i in range(0, len(names_and_times), 2):
            # only consider racers who started at least the first run
            full_name = names_and_times[i]['value']
            if "DNS" in names_and_times[i+1]['value']:
                continue
            if full_name in racers:
                continue
            competitor = Competitor(full_name)
            race.competitors.append(competitor)
            racers.add(full_name)
    
    #TODO: get run 1 info to see who started race for penalty calculation
    # if the race is not speed, get run 2 info for final calculations
    initialize_starting_racers()
    print(f"Number of starters: {len(race.competitors)}")

def livetiming_scraper(race):
    URL = "https://www.live-timing.com/includes/aj_race." + race.url.split(".")[-1]
    # only get first names, run time
    # get both runs for tech races
    def is_valid_field_tech_race(field):
        return (field.startswith("m=") or
                field.startswith("fp=") or
                field.startswith("r1") or
                field.startswith("r2") or
                field.startswith("tt="))

    # speed races only have 1 run
    def is_valid_field_speed_race(field):
        return (field.startswith("m=") or
                field.startswith("fp=") or
                field.startswith("r1") or
                field.startswith("tt="))

    r = requests.get(URL)
    content = r.text

    if race.event == "SLpoints" or race.event=="GSpoints":
        filtered_competitors = [field.strip() for field in content.split("|") if is_valid_field_tech_race(field)]
    if race.event == "SGpoints" or race.event == "DHpoints":
        filtered_competitors = [field.strip() for field in content.split("|") if is_valid_field_speed_race(field)]

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
        competitor.fis_points = int(starter[1][3:])/100
        race.competitors.append(competitor)
        race.winning_time = min(race.winning_time, competitor.time)
    return

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
import requests
import re

TIMES_AS_LETTERS = {"DNF", "DNS", "DSQ", "DQ", "Did Not Finish", "Did Not Start", "Disqualified"}

class Competitor:
    def __init__(self, full_name):
        self.full_name = full_name
        self.first_name = ""
        self.last_name = ""
        self.time = 9999
        self.fis_points = 1000
        self.score = -1
        self.start_order = 9999

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
            'runno': run_number,
        }

        return requests.post(url, headers=headers, data=payload)

    def is_numeric_field(value):
        value = value.strip()
        if value in TIMES_AS_LETTERS:
            return True
        return not any(c.isalpha() for c in value)

    # some fields include just names, but no corresponding times in the following fields
    def filter_fields_with_no_time(fields):
        fields_with_times = []
        continue_count = 0
        for i in range(0, len(fields), 1):
            # pretty awkard, but needed for conditional iteration since vola outputs data weirdly
            if continue_count != 0:
                continue_count -= 1
                continue
            if i+2 > len(fields)-1: # out of index
                continue

            if is_numeric_field(fields[i+2]['value']):
                continue_count = 2
                # append first name, last name, and time
                fields_with_times.append(fields[i])
                fields_with_times.append(fields[i+1])
                fields_with_times.append(fields[i+2])

        return fields_with_times

    # combine to full name of form "LAST first"
    def combine_first_last_name_fields(fields):
        fields = filter_fields_with_no_time(fields)

        transformed_fields = []
        for i in range(0, len(fields), 3):
            # NOTE: assumes last name is in all caps, while first name is lower-case
            # if going by the FIS standard, this will be true
            if fields[i]['value'].isupper():
                fields[i]['value'] += " " + fields[i+1]['value']
                transformed_fields.append(fields[i])
            else:
                fields[i+1]['value'] += " " + fields[i]['value']
                transformed_fields.append(fields[i+1])
            transformed_fields.append(fields[i+2])
        
        return transformed_fields

    def extract_startlist():
        #TODO: make this work...
        # sometimes names are given as full names, sometimes they are given separated by first/last
        first_last_names_separate = False
        valid_fields = set()
        # get run 1 info
        fields = send_request("GetHeatListFields", 1)
        if fields.status_code == 200:
            # extract where names and times are stored
            data = fields.json()
            fields = data['DATA']['field']
            for field in fields:
                if ("order" in field['title'].lower() or "name" in field['title'].lower() 
                    or "time" in field['title'].lower()):
                    valid_fields.add((field['grid'], field['col']))
                if "first" in field['title'].lower() or "last" in field['title'].lower():
                    first_last_names_separate = True

        values = send_request("GetHeatListValues", 1)

        names_and_start_order = []
        if values.status_code == 200:
            # get names and times 
            data = values.json()
            fields = data['DATA']['fieldvalue']
            for field in fields:
                # HTML non-breaking space, doesn't contain data so skip these
                if "&nbsp" in field['value']:
                    continue
                if (field['grid'], field['col']) in valid_fields:
                    names_and_start_order.append(field)

            if first_last_names_separate:
                names_and_start_order= combine_first_last_name_fields(names_and_start_order)

        return names_and_start_order

    def extract_names_and_times(run_number):
        # sometimes names are given as full names, sometimes they are given separated by first/last
        first_last_names_separate = False
        valid_fields = set()
        fields = send_request("GetHeatListFields", run_number)
        if fields.status_code == 200:
            # extract where names and times are stored
            data = fields.json()
            fields = data['DATA']['field']
            for field in fields:
                if "time" in field['title'].lower() or "name" in field['title'].lower():
                    valid_fields.add((field['grid'], field['col']))
                if "first" in field['title'].lower() or "last" in field['title'].lower():
                    first_last_names_separate = True

        values = send_request("GetHeatListValues", run_number)

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
                    print(f"grid: {field['grid']}  {field['value']}")

            if first_last_names_separate:
                names_and_times = combine_first_last_name_fields(names_and_times)

        return names_and_times

    def add_comma_to_full_name(name):
        split_idx = 0
        for i in range(len(name)): 
            if not name[i].isalpha() or name[i] == " ": # skip characters like "-" and whitespace
                continue
            
            # last name is in all caps, so find where transition from all caps to lowercase is
            if i > 0 and not name[i].isupper() and name[i-1].isupper():
                split_idx = i
                break # only find first change from upper to lower
            
        # assume that first letter of first name is in all caps
        split_idx -= 1
        return name[:split_idx-1] + ", " + name[split_idx:]
        

    def initialize_starting_racers():
        # TODO: FIX THIS NEXT
        # TODO: fix calculation if someone DNS's
        # set their points to be 1000
        names_and_start_order = extract_startlist()

        racers = set() # for duplicate detection
        # TODO: make this loop add start order if possible
        # to get points for only people starting in the seed
        for i in range(len(names_and_start_order)):
            # fix for now to skip start order
            if is_numeric_field(names_and_start_order[i]['value']):
                continue

            full_name = add_comma_to_full_name(names_and_start_order[i]['value'])
            if full_name in racers:
                continue

            competitor = Competitor(full_name)
            race.competitors.append(competitor)
            racers.add(full_name)
    
    def add_times_to_racers():
        names_and_times = []
        if race.event == "SGpoints" or race.event == "DHpoints":
            names_and_times = extract_names_and_times("1")
        else:
            names_and_times = extract_names_and_times("2")
        
        competitor_ids = {} 
        for i in range(len(race.competitors)):
            competitor_ids[race.competitors[i].full_name] = i

        for i in range(0, len(names_and_times), 2):
            full_name = ""
            time = 9999
            if i >= len(names_and_times) - 1: # exit before next part gives indexing error
                continue

            # times/names returned in groups of two, but no guarantee of order
            # assign correct field to name/time
            if is_numeric_field(names_and_times[i]['value']):
                time = names_and_times[i]['value']
                full_name = names_and_times[i+1]['value']
            else:
                full_name = names_and_times[i]['value']
                time = names_and_times[i+1]['value']
            
            # only assign times if started second run
            if "DNS" in time or "Did Not Start" in time:
                continue

            full_name = add_comma_to_full_name(full_name)
            if full_name in competitor_ids:
                id = competitor_ids[full_name]
                race.competitors[id].time = time_to_float(time)
                race.winning_time = min(race.winning_time, race.competitors[id].time)

    initialize_starting_racers()
    add_times_to_racers()

def livetiming_scraper(race):
    #TODO if not speed race, calculate total time by adding run 1 and run 2
    # sometimes total time displays incorrectly
    
    # request URL to get raw data from livetiming
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
        if "DNS" in racer[2] or "Did Not Start" in racer[2]:
            continue
        starters.append(racer)
    
    for starter in starters:
        # strip off "m= from name"
        full_name = starter[0][2:]
        competitor = Competitor(full_name)

        # filter for did not finish, did not start, or disqualified
        if ("tt=" not in starter[-1] or
            "".join(starter) in TIMES_AS_LETTERS):
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
    if not time or time in TIMES_AS_LETTERS:
        return 9999
    # edge case for times under a minute
    elif ":" not in time:
        time = float(time)
    else:
        minutes = time.split(":")[0]
        seconds = time.split(":")[1]
        time = float(minutes)*60 + float(seconds)
    return time
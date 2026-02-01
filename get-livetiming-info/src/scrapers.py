import requests
import re
import time
import phpserialize
from exceptions import UserFacingException

TIMES_AS_LETTERS = {"DNF", "DNS", "DSQ", "DQ", "Did Not Finish", "Did Not Start", "Disqualified"}

class Competitor:
    def __init__(self, full_name):
        self.full_name = full_name
        self.temp_full_name = ""
        self.first_name = ""
        self.last_name = ""
        self.time = 9999
        self.fis_points = 1000
        self.score = -1
        self.next_year_score = -1
        self.start_order = 9999
        self.fiscode = 0
        self.bib = -1

    def __str__(self):
        return f"{self.full_name} score: {self.score}"


def vola_scraper(race):
#TODO: To rewrite this to be more accurate, look @ following info
    # From the JS that loads the page (livepublish.timekeepter.skialp.40.0.07.min.js)
    # Startlist is stored at response["4"]
    # Results are stored response["0"]
    # heatlistfields tells where the locations of info are
    # heatlistvalues gives the actual results

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
                    #print(f"grid: {field['grid']}  {field['value']}")

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
        
    def generate_ussa_competitor_name(full_name):
        # since ussa doesn't separate out first and last names nicely
        # combine first/last names, remove non a-z characters, and order alphabetically
        return ''.join(sorted(re.sub('[^a-z]', '', full_name.lower())))


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

            full_name = ""
            temp_full_name = ""
            if race.is_fis_race:
                temp_full_name = names_and_start_order[i]['value']
                full_name = generate_ussa_competitor_name(names_and_start_order[i]['value'])
            else:
                temp_full_name = names_and_start_order[i]['value']
                full_name = generate_ussa_competitor_name(names_and_start_order[i]['value'])
            if full_name in racers:
                continue

            competitor = Competitor(full_name)
            competitor.temp_full_name = temp_full_name
            race.competitors.append(competitor)
            racers.add(full_name)
    
    def add_run_time(names_and_times, is_first_run):
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

            if race.is_fis_race:
                full_name = generate_ussa_competitor_name(full_name)
            else:
                full_name = generate_ussa_competitor_name(full_name)

            if full_name in competitor_ids:
                #print(f'time for: {full_name} : {time}')
                id = competitor_ids[full_name]
                
                #TODO: get r1, r2 ranks for tech races
                if is_first_run and race.is_tech_race:
                    r1_time = time_to_float(time)
                    race.competitors[id].r1_time = r1_time

                elif is_first_run and not race.is_tech_race:
                    race.competitors[id].time = time_to_float(time)
                    race.winning_time = min(race.winning_time, race.competitors[id].time)

                else:
                    total = time_to_float(time)
                    if hasattr(race.competitors[id], 'r1_time'):
                        r2_time = total - race.competitors[id].r1_time
                        race.competitors[id].r2_time = r2_time

                    race.competitors[id].time = total
                    race.winning_time = min(race.winning_time, race.competitors[id].time)

    def add_run_ranks():
        if not race.is_tech_race:
            return
        
        for competitor in race.competitors:
            if hasattr(competitor, "r1_time"):
                race.r1_times.append(competitor.r1_time)
            if hasattr(competitor, "r2_time"):
                race.r2_times.append(competitor.r2_time)

        race.r1_times = sorted(race.r1_times)
        race.r2_times = sorted(race.r2_times)

        for competitor in race.competitors:
            if hasattr(competitor, "r1_time"):
                competitor.r1_rank = get_rank(competitor.r1_time, race.r1_times)
            if hasattr(competitor, "r2_time"):
                competitor.r2_rank = get_rank(competitor.r2_time, race.r2_times)

    def add_times_to_racers():
        names_and_times_r1 = []
        names_and_times_r2 = []

        names_and_times_r1 = extract_names_and_times("1")
        if race.event == "SLpoints" or race.event == "GSpoints":
            names_and_times_r2 = extract_names_and_times("2")
        
        add_run_time(names_and_times_r1, is_first_run=True)
        if race.event == "SLpoints" or race.event == "GSpoints":
            add_run_time(names_and_times_r2, is_first_run=False)


    initialize_starting_racers()
    add_times_to_racers()
    add_run_ranks()

def livetiming_scraper(race):
    # request URL to get raw data from livetiming
    URL = "https://www.live-timing.com/includes/aj_race." + race.url.split(".")[-1]

    # only get first names, run time
    # get both runs for tech races
    def is_valid_field_tech_race(field):
        # do this to grab fis points if fis race, ussa points if ussa race
        points_string = "fp=" if race.is_fis_race else "up="
        return (field.startswith("m=") or
                field.startswith(f"{points_string}") or
                field.startswith("r1") or
                field.startswith("r2") or
                field.startswith("tt="))

    # speed races only have 1 run
    def is_valid_field_speed_race(field):
        # do this to grab fis points if fis race, ussa points if ussa race
        points_string = "fp=" if race.is_fis_race else "up="
        return (field.startswith("m=") or
                field.startswith(f"{points_string}") or
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
    
    r1_times = []
    r2_times = []
    for starter in starters:
        for value in starter:
            if 'r1' in value:
                r1_times.append(time_to_float( value.split('=')[1] ))
            if 'r2' in value:
                r2_times.append(time_to_float( value.split('=')[1] ))
    r1_times = sorted(r1_times)
    r2_times = sorted(r2_times)
    
    for starter in starters:
        # strip off "m= from name"
        full_name = starter[0][2:]
        competitor = Competitor(full_name)
        for value in starter:
            if 'r1' in value:
                competitor.r1_time = time_to_float( value.split('=')[1] )
                competitor.r1_rank = get_rank(competitor.r1_time, r1_times)

        # filter for did not finish, did not start, or disqualified
        if ("tt=" not in starter[-1] or
            "".join(starter[1:]) in TIMES_AS_LETTERS or
            "DQ" in "".join(starter[1:]) or
            "DNF" in "".join(starter[1:]) or
            "DNS" in "".join(starter[1:])): #edge case, sometimes time is listed as DQg35 for example, or sometimes single run time shown for combined time
            competitor.time = 9999
        else:
            total = time_to_float(starter[-1][3:])
            competitor.time = total
            if race.event == "SLpoints" or race.event == "GSpoints":
                for value in starter:
                    if 'r2' in value:
                        competitor.r2_time = time_to_float( value.split('=')[1] )
                        competitor.r2_rank = get_rank(competitor.r2_time, r2_times)

                # bug fix - sometimes total time doesn't get added as r1 + r2
                if competitor.time == competitor.r1_time or competitor.time == competitor.r2_time:
                    competitor.time = competitor.r1_time + competitor.r2_time

        competitor.fis_points = int(starter[1][3:])/100
        race.competitors.append(competitor)
        race.winning_time = min(race.winning_time, competitor.time)
    return

def fis_livetiming_scraper(race):

    if 'fis-ski' in race.url:
        match = re.search(r'lv-al(\d+)', race.url)
        CODEX = match.group(1)
    else:
        CODEX = race.url.strip()
    TIMESTAMP = int(time.time() * 1000)

    def strip_tags(raw_data):
        return re.sub(r'</?lt>', '', raw_data)
    
    # these mess up php serialization - they take up more than 1 character and make the string length count incorrect
    # just replace them with a z as a dummy character
    def remove_german_chars(data):
        replacements = {
        'ä': 'z', 'ö': 'z', 'ü': 'z', 'ß': 'z', 
        'Ä': 'Z', 'Ö': 'Z', 'Ü': 'Z',
        'é': 'z', 'É': 'Z'
        }
        pattern = re.compile("|".join(re.escape(k) for k in replacements.keys()))
        return pattern.sub(lambda m: replacements[m.group(0)], data)

    def get_server_url():
        url = f'https://live.fis-ski.com/general/serverListFull.xml?t={TIMESTAMP}'
        raw_data = session.get(url).text
        cleaned_data = strip_tags(raw_data)
        parsed_data = phpserialize.loads(cleaned_data.encode(), decode_strings=True)

        return parsed_data['servers'][0][0]
    
    def get_race_data(server_url):
        TIMESTAMP = int(time.time() * 1000)
        url = f'{server_url}/al{CODEX}/main.xml?t={TIMESTAMP}'

        response = session.get(url)
        if response.status_code == 404:
            raise UserFacingException("Race is not live or not found", status_code=404)

        raw_data = response.content.decode('utf-8')
        cleaned_data = strip_tags(raw_data)
        cleaned_data = remove_german_chars(cleaned_data)

        # note, iso-8859-1 encoding needed to correctly encode foreign characters, such as é
        return phpserialize.loads(cleaned_data.encode('iso-8859-1'), decode_strings=True)
    
    def construct_start_order_to_fiscode_map(start_order):
        if not start_order:
            return {}

        bib_to_fiscode_map = {}
        for bib, racer in enumerate(start_order.values()):
            finished = False
            for j in range(len(racer.values())):
                if 'finish' in str( racer[j] ):
                    finished = True
            fiscode = racer[0]
            bib_to_fiscode_map[bib] = {'fiscode': fiscode, 'finished': finished}
        return bib_to_fiscode_map
    
    def create_startlist(startlist, starters):
        race.is_startlist_only = True
        for bib, racer in enumerate(startlist.values()):
            fiscode = racer[0]
            starters[fiscode]['bib'] = bib
        
        for fiscode in starters:
            full_name = starters[fiscode]['full_name']
            competitor = Competitor(full_name)
            competitor.fiscode = fiscode
            competitor.bib = starters[fiscode]['bib']
            race.competitors.append(competitor)

    session = requests.Session()
    server_url = get_server_url()
    race_data = get_race_data(server_url)
    
    if (not race_data.get("result") and not race_data.get("startlist")):
        raise UserFacingException("Wait for the race to start", status_code=404)
    
    starters = {}
    entered = race_data.get("racers", [])
    for racer in entered.values():
        # format: fiscode: 
        #   { full_name : 'last_name, first_name' }
        starters[racer[0]] = {
            'full_name': f'{racer[1]}, {racer[2]}'
        }
    

    # remove entered racers listed as 'dns'
    # also remove entered racers not listed at all on the start list, sometimes they are just excluded and not listed as 'dns'
    r1_start_list = race_data.get("startlist")[0][0][0]
    started_fiscodes = []
    for racer in r1_start_list.values():
        fiscode = racer[0]
        if racer[2] == 'dns':
            continue
        started_fiscodes.append(fiscode)
    
    did_not_start = []
    for fiscode in starters.keys():
        if fiscode not in started_fiscodes:
            did_not_start.append(fiscode)
    for fiscode in did_not_start:
        starters.pop(fiscode)

    if (not race_data.get("result") and race_data.get("startlist")):
        create_startlist(race_data.get("startlist")[0][0][0], starters)
        return

    run_number = 1
    if race.event == "SGpoints" or race.event == "DHpoints":
        run_number = 0
    
    first_run_start_order = race_data.get("startlist")[0][0][0]
    r1_bib_to_fiscode_map = construct_start_order_to_fiscode_map(first_run_start_order)

    second_run_start_order = {}
    second_run_start_order = race_data.get("startlist")[0][0].get(run_number)
    r2_bib_to_fiscode_map = construct_start_order_to_fiscode_map(second_run_start_order)
    
    # get third run start order for indoor 3 run slalom races
    third_run_start_order = {}
    third_run_start_order = race_data.get("startlist")[0][0].get(2)
    r3_bib_to_fiscode_map = construct_start_order_to_fiscode_map(third_run_start_order)
    
    # get finish_location from racedef
    # for tech look for second occurance of 'finished'
    # for speed look for first occurance
    finish_location = 0
    if second_run_start_order:
        racedef = race_data.get("racedef")[0][run_number]
        for i, run_info in enumerate(racedef.values()):
            for j in range(len(run_info.values())):
                if 'finish' in str( run_info[j] ):
                    finish_location = i
    # hacky bug fix - need to get finish_location for tech races to be run after the first run (meaning second_run_start_order is false)
    # shitty code for now but remove this later if it causes issues. If not, can consolidate w/ the code above
    else:
        racedef = race_data.get("racedef")[0][0] # set run_number to 0 here since we're assuming 2nd run hasn't started
        for i, run_info in enumerate(racedef.values()):
            for j in range(len(run_info.values())):
                if 'finish' in str( run_info[j] ):
                    finish_location = i

    # add first run times
    results = race_data.get("result")[0][0]
    if not results: # bug fix - sometimes results are stored at index 1 and not index 0, could be an error when entered into fis livetiming
        results = race_data.get("result")[0][1]

    for r1_bib, result in results.items():
        if result is None:
            continue

        # with splits / intervals, a dnf can show the first two splits but no finish time
        if len(result) != finish_location + 1:
            continue

        # sometimes, : is included in time, for example: 85530:p2 or 85530:c
        if ':' in str( result[finish_location] ):
            result[finish_location] = result[finish_location].split(':')[0]
        fiscode = r1_bib_to_fiscode_map[r1_bib]['fiscode']
        
        # bug fix - sometimes weird fiscode will enter data
        if fiscode not in starters.keys():
            continue

        if r1_bib_to_fiscode_map[r1_bib]['finished']:
            starters[fiscode]['r1_time'] = round( int(result[finish_location]) / 1000, 2) # convert from miliseconds to seconds
        else:
            starters[fiscode]['result'] = 9999
    
    # add second run times
    if second_run_start_order:
        results = race_data.get("result")[0].get(run_number)
        if results:
            for r2_bib, result in results.items():
                if result is None:
                    continue

                # with splits / intervals, a dnf can show the first two splits but no finish time
                if len(result) != finish_location + 1:
                    continue

                # sometimes, : is included in time, for example: 85530:p2 or 85530:c
                if ':' in str( result[finish_location] ):
                    result[finish_location] = result[finish_location].split(':')[0]
                fiscode = r2_bib_to_fiscode_map[r2_bib]['fiscode']
                if r2_bib_to_fiscode_map[r2_bib]['finished']:
                    starters[fiscode]['result'] = round( int(result[finish_location]) / 1000, 2) # convert from miliseconds to seconds
                    if 'r1_time' in starters[fiscode].keys():
                        starters[fiscode]['r2_time'] = starters[fiscode]['result'] - starters[fiscode]['r1_time']
                else:
                    starters[fiscode]['result'] = 9999
    
    # add third run times (can refactor later but was lazy and copy/pasted from above and changed a few values)
    if third_run_start_order:
        results = race_data.get("result")[0].get(2)
        if results:
            for r3_bib, result in results.items():
                if result is None:
                    continue

                # with splits / intervals, a dnf can show the first two splits but no finish time
                if len(result) != finish_location + 1:
                    continue

                # sometimes, : is included in time, for example: 85530:p2 or 85530:c
                if ':' in str( result[finish_location] ):
                    result[finish_location] = result[finish_location].split(':')[0]
                fiscode = r3_bib_to_fiscode_map[r3_bib]['fiscode']
                if r3_bib_to_fiscode_map[r3_bib]['finished']:
                    starters[fiscode]['result'] = round( int(result[finish_location]) / 1000, 2) # convert from miliseconds to seconds
                    if 'r2_time' in starters[fiscode].keys():
                        starters[fiscode]['r3_time'] = starters[fiscode]['result'] - starters[fiscode]['r1_time'] - starters[fiscode]['r2_time']

                else:
                    starters[fiscode]['result'] = 9999
    
    r1_times = sorted([starters[f]['r1_time'] for f in starters if 'r1_time' in starters[f].keys()])
    r2_times = sorted([starters[f]['r2_time'] for f in starters if 'r2_time' in starters[f].keys()])
    r3_times = sorted([starters[f]['r3_time'] for f in starters if 'r3_time' in starters[f].keys()])

    for fiscode in starters:
        full_name = starters[fiscode]['full_name']
        competitor = Competitor(full_name)
        if 'result' in starters[fiscode].keys():
            competitor.time = starters[fiscode]['result']
        if 'r1_time' in starters[fiscode].keys():
            competitor.r1_time = starters[fiscode]['r1_time']
            competitor.r1_rank = get_rank(competitor.r1_time, r1_times)
        if 'r2_time' in starters[fiscode].keys():
            competitor.r2_time = starters[fiscode]['r2_time']
            competitor.r2_rank = get_rank(competitor.r2_time, r2_times)
        if 'r3_time' in starters[fiscode].keys():
            competitor.r3_time = starters[fiscode]['r3_time']
            competitor.r3_rank = get_rank(competitor.r3_time, r3_times)
        if 'result' not in starters[fiscode].keys() and 'r2_time' not in starters[fiscode].keys():
            competitor.time = 9999
        if third_run_start_order and 'r3_time' not in starters[fiscode].keys(): # bug fix - 3rd run dfs were getting skipped
            competitor.time = 9999
        
        competitor.fiscode = fiscode

        if competitor.time == 0: # bug fix, sometimes dnf is listed as 0 seconds
            continue
        race.competitors.append(competitor)
        race.winning_time = min(race.winning_time, competitor.time)
    return

def time_to_float(time):
    # reg ex to remove place ex: (1) and whitespace from time
    time = re.sub(r'\s*\(\d+\)$', '', time.strip())

    # calculate time in seconds, but only for those who finished
    if not time or time in TIMES_AS_LETTERS or not re.match(r'[0-9:]', time):
        return 9999
    # edge case for times under a minute
    elif ":" not in time:
        time = float(time)
    else:
        minutes = time.split(":")[0]
        seconds = time.split(":")[1]
        time = float(minutes)*60 + float(seconds)
    return time

def get_rank(time, sorted_times):
    # sometimes, time isn't found - exclude these from rank
    if time == 0 or time is None:
        return None
    
    # filter out times of zero from times not found
    filtered_times = [t for t in sorted_times if t > 0]
    return filtered_times.index(time) + 1 if time in filtered_times else None
    
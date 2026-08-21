from datetime import datetime, date
from pytz import timezone
from pypdf import PdfReader
import boto3
import sys
import requests
import zipfile
import io
import pandas as pd
import re
import traceback

from fis_points_download import update_dynamodb

POINTS_BASE_URL = "https://media.usskiandsnowboard.org/CompServices/Points/Alpine"

# points lists are only valid for competition from their "National Valid" date,
# which is published in a schedule pdf alongside the zips. a list is usually
# uploaded a couple of days before it takes effect, so the newest file on the
# server is not necessarily the one we should be using.
SCHEDULE_PATTERN = re.compile(r'(\d{4})-\d{2}_AL_List_Schedule\.pdf')
LIST_ZIP_PATTERN = re.compile(r'nlx(\d{2})(\d{2})\.zip')
SCHEDULE_ROW_PATTERN = re.compile(r'^List\s+(\d+)\s+\w+\.?\s+\d+\s+(\w+)\.?\s+(\d+)\b')
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}

# races are held in the US, so validity is judged against the eastern calendar
# date rather than the lambda's UTC clock
RACE_TIMEZONE = timezone("America/New_York")


def today_in_race_timezone():
    return datetime.now(RACE_TIMEZONE).date()


# how far past the last hit we keep probing when the directory index is gone
PROBE_GAP_TOLERANCE = 3
MAX_LIST_NUMBER = 50


def fetch_directory_listing():
    response = requests.get(f"{POINTS_BASE_URL}/", timeout=30)
    response.raise_for_status()
    return response.text


def list_exists(list_number, season_code):
    # a list that doesn't exist still answers 200, but with an html error page
    # instead of the zip, so the content type is what we have to go on
    response = requests.head(compose_list_url(list_number, season_code), timeout=15)
    return response.headers.get("content-type", "").startswith("application/zip")


def probe_available_lists(logger, today):
    # fallback for when the directory index is unavailable: walk the list
    # numbers for this season and the one before it, looking for zips
    available = {}
    # season code 27 covers the 2026-27 season, which runs from mid 2026
    likely_season = (today.year + 1 if today.month >= 5 else today.year) % 100
    for season_code in (likely_season, (likely_season - 1) % 100):
        found = set()
        misses = 0
        for list_number in range(1, MAX_LIST_NUMBER + 1):
            if list_exists(list_number, season_code):
                found.add(list_number)
                misses = 0
            elif found or list_number > PROBE_GAP_TOLERANCE:
                misses += 1
                if misses >= PROBE_GAP_TOLERANCE:
                    break
        if found:
            available[season_code] = found

    logger.error(f"ERROR: directory index unavailable, probed and found "
                 f"{ {season: sorted(lists) for season, lists in available.items()} }")
    return available


def find_available_lists(listing):
    # {season_code: set(list_numbers)} for every nlx zip on the server
    available = {}
    for list_number, season_code in LIST_ZIP_PATTERN.findall(listing):
        available.setdefault(int(season_code), set()).add(int(list_number))
    return available


def find_schedules(listing):
    # {season_start_year: filename}, e.g. {2026: "2026-27_AL_List_Schedule.pdf"}
    return {int(match.group(1)): match.group(0)
            for match in SCHEDULE_PATTERN.finditer(listing)}


def parse_schedule(pdf_bytes, season_start_year):
    # returns {list_number: national valid date}. the pdf prints months without
    # years, but the rows run in order, so the year ticks over when the month
    # goes backwards.
    text = PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()

    valid_dates = {}
    previous_month = 0
    year = season_start_year
    for line in text.splitlines():
        match = SCHEDULE_ROW_PATTERN.match(line.strip())
        if not match:
            continue

        list_number = int(match.group(1))
        month = MONTHS[match.group(2).lower().rstrip(".")]
        day = int(match.group(3))
        if month < previous_month:
            year += 1
        previous_month = month

        valid_dates[list_number] = date(year, month, day)

    return valid_dates


def fetch_schedule(logger, listing, season_code):
    # season code 27 means the 2026-27 season, which started in 2026
    season_start_year = 2000 + season_code - 1
    schedules = find_schedules(listing)
    # if the directory index is unavailable, fall back to the naming convention
    # so a valid date can still be honoured
    filename = schedules.get(
        season_start_year,
        f"{season_start_year}-{(season_start_year + 1) % 100:02d}_AL_List_Schedule.pdf")
    response = requests.get(f"{POINTS_BASE_URL}/{filename}", timeout=30)
    response.raise_for_status()
    return parse_schedule(response.content, season_start_year)


def choose_list(logger, listing, available, today):
    # across every season on the server, take the list with the most recent
    # valid date that has already arrived. this handles the early-summer overlap
    # where last season's final list is still in force.
    best = None
    for season_code, list_numbers in available.items():
        valid_dates = fetch_schedule(logger, listing, season_code)
        for list_number in list_numbers:
            valid_date = valid_dates.get(list_number)
            if valid_date is None or valid_date > today:
                continue
            if best is None or valid_date > best[0]:
                best = (valid_date, season_code, list_number)

    return best


def newest_available_list(available):
    # fallback for when the schedule can't be read: newest file on the server,
    # which may be a few days ahead of its valid date
    if not available:
        return None
    season_code = max(available)
    return (None, season_code, max(available[season_code]))


def compose_list_url(list_number, season_code):
    return f"{POINTS_BASE_URL}/nlx{list_number:02d}{season_code:02d}.zip"


def compose_download_url(logger, today=None):
    today = today or today_in_race_timezone()

    try:
        listing = fetch_directory_listing()
        available = find_available_lists(listing)
    except Exception as e:
        logger.error(f"ERROR: could not read the USSA directory index: {e}")
        listing, available = "", probe_available_lists(logger, today)

    chosen = None
    try:
        chosen = choose_list(logger, listing, available, today)
    except Exception as e:
        logger.error(f"ERROR: could not read the USSA list schedule: {e}")

    if chosen:
        valid_date, season_code, list_number = chosen
        logger.info(f"USSA: season {season_code:02d}, list {list_number:02d}, "
                    f"valid since {valid_date}")
    else:
        chosen = newest_available_list(available)
        if not chosen:
            raise Exception("no USSA points lists found on the server")
        _, season_code, list_number = chosen
        logger.error(f"ERROR: falling back to newest available list "
                     f"(season {season_code:02d}, list {list_number:02d}) - it may "
                     f"not be valid for competition yet")

    return compose_list_url(list_number, season_code)


def connect_to_dynamo_db(logger):
    try:
        client = boto3.resource('dynamodb')
        table = client.Table('ussa_points_list')
    except Exception as e:
        logger.error("ERROR: Failed to connect to DynamoDB")
        logger.error(e)
        sys.exit()
	
    logger.info("SUCCESS: Connection to DynamoDB Table succeeded")
    return table

def generate_competitor_name(full_name):
    # since ussa doesn't separate out first and last names nicely
    # combine first/last names, remove non a-z characters, and order alphabetically
    return ''.join(sorted(re.sub('[^a-z]', '', full_name.lower())))


def get_published_date(z):
    # the list carries no effective date, only the timestamp of when the files
    # were written, so this is the best staleness signal available
    dates = [zip_info.date_time for zip_info in z.infolist()]
    return datetime(*max(dates)) if dates else None


def get_points_df(logger, download_url):
    response = requests.get(download_url, timeout=60)
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        # missing lists are served as a 200 html error page, not a 404
        raise Exception(f"expected a zip at {download_url}, got {response.headers.get('content-type')}")

    # download gives a zip of 3 files, we only want 2 of them
    zip_data = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_data) as z:
        published = get_published_date(z)
        if published:
            age = (datetime.now() - published).days
            logger.info(f"USSA: list published {published:%Y-%m-%d} ({age} days ago)")

        files = z.namelist()
        mens_points = next((f for f in files if f.startswith("NLM") and f.endswith(".csv")), None)
        womens_points = next((f for f in files if f.startswith("NLW") and f.endswith(".csv")), None)

        # these csvs have no header row, so without header=None pandas would
        # consume the first athlete in each file as the column names
        mens_df = pd.read_csv( z.open(mens_points), header=None )
        womens_df = pd.read_csv( z.open(womens_points), header=None )
    
    # csv has extra data (club, birthyear,etc.) - only grab what is needed
    data_columns_to_keep = [1, 2, 4, 7, 8, 9, 10, 11]
    column_names = ["Lastname", "Firstname", "Fiscode", "DHpoints", "SLpoints", "GSpoints", "SGpoints", "ACpoints"]

    mens_df = mens_df.iloc[:, data_columns_to_keep]
    womens_df = womens_df.iloc[:, data_columns_to_keep]
    mens_df.columns = column_names
    womens_df.columns = column_names

    points_df = pd.concat([mens_df, womens_df], ignore_index=True)
    points_df['Competitorname'] = points_df.apply(lambda row: generate_competitor_name(f"{row['Firstname']}{row['Lastname']}"), axis=1)
    reordered_columns = ["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints", "SLpoints", "GSpoints", "SGpoints", "ACpoints"]
    return points_df[reordered_columns]



def ussa_points_download(logger):
    try:
        logger.info("Checking ussa points")
        download_url = compose_download_url(logger)
        table = connect_to_dynamo_db(logger)
        points_df = get_points_df(logger, download_url)

        update_dynamodb(logger, table, points_df)

    except Exception as e:
        logger.error("ERROR: error downloading ussa points")
        logger.error(f"ERROR: {e}\nStack Trace:\n{traceback.format_exc()}")
        logger.error(e)
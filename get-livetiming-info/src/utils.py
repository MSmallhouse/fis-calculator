from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

import sys
import logging
import pymysql
import pymysql.cursors
import pandas as pd
import boto3
from botocore.exceptions import ClientError

from scrapers import vola_scraper
from scrapers import livetiming_scraper

# hack fix for now, assume Filippo collini is the person from Castleton
# who is more likely to be in US races where this website will be used
FILIPPO_COLLINI_FISCODE = 6293795

def connect_to_database(race):
    race.logger = logging.getLogger()
    race.logger.setLevel(logging.INFO)

    try:
        client = boto3.resource('dynamodb')
        race.table = client.Table('points_list_dynamo_db')
    except Exception as e:
        race.logger.error("ERROR: Failed to connect to DynamoDB")
        race.logger.error(e)
        sys.exit()

    # make database connection
    #try:
    #    race.connection = pymysql.connect(host=race.ENDPOINT, user=race.USERNAME,
    #                                    passwd=race.PASSWORD,db=race.DATABASE_NAME,
    #                                    connect_timeout=5,
    #                                    cursorclass=pymysql.cursors.DictCursor)
    #except pymysql.MySQLError as e:
    #    race.logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
    #    race.logger.error(e)
    #    sys.exit()
    #race.logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")
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
# takes name in format of "LAST first"
def clean_name(name):
    # prevents from breaking if name has no comma for some reason
    if "," not in name:
        print(f"ERROR: {name} could not be parsed correctly")
        return ["", ""]

    name = name.lower()
    name = name.split(",")
    if len(name) >= 2:
        name[1] = name[1].strip()
    return name


def scan_dynamodb_table(race):
	# DynamoDB uses pagination, paginate through response to collect all data
    items = []
    response = race.table.scan()

    while 'LastEvaluatedKey' in response:
        items.extend(response['Items'])
        response = race.table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
	
    items.extend(response['Items'])
    return items

def get_df_from_database(race):
    existing_data = scan_dynamodb_table(race)
    existing_df = pd.DataFrame(existing_data)
    existing_df = existing_df[["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints", "SLpoints", "GSpoints", "SGpoints", "ACpoints"]]
	# convert to numeric in case these are stored as strings in DynamoDB
    existing_df[["DHpoints", "SLpoints", "GSpoints", "SGpoints", "ACpoints"]] = existing_df[["DHpoints", "SLpoints", "GSpoints", "SGpoints", "ACpoints"]].apply(pd.to_numeric, errors='coerce')
    #with connection:
    #    with connection.cursor() as cursor:
    #        # get df of full RDS database
    #        query = "SELECT * FROM fis_points.point_entries"
    #        cursor.execute(query)
    #        existing_data = cursor.fetchall()

    #        column_names = ["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints",
    #                        #"SLpoints", "GSpoints", "SGpoints", "ACpoints"]

    #        # connection not autocommitted by default
    #        connection.commit()
    #        cursor.close()
    #return pd.DataFrame(existing_data, columns=column_names)

    column_names = ["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints",
                    "SLpoints", "GSpoints", "SGpoints", "ACpoints"]
    return pd.DataFrame(existing_df, columns=column_names)

def add_points_to_competitors(race, points_df):
    # lowercase for accurate matching
    points_df["Firstname"] = points_df["Firstname"].str.lower().str.replace(" ", "")
    points_df["Lastname"] = points_df["Lastname"].str.lower().str.replace(" ", "")

    for competitor in race.competitors:
        mask = ((points_df["Lastname"] == competitor.last_name.replace(" ","")) &
                (points_df["Firstname"] == competitor.first_name.replace(" ","")))
        matching_row = points_df[mask]

        if matching_row.empty:
            if "vola" in race.url:
                # sometimes vola doesn't include multiple first/last names. Just try excluding these
                points_df["Lastname"] = points_df["Lastname"].str.split().str[0]
                points_df["Firstname"] = points_df["Firstname"].str.split().str[0]

                mask = ((points_df["Lastname"] == competitor.last_name.split()[0]) &
                        (points_df["Firstname"] == competitor.first_name.split()[0]))
                matching_row = points_df[mask]

                if not matching_row.empty:
                    race.logger.error(f"POSSIBLE ERROR: Racer {competitor.first_name}, {competitor.last_name}'s assigned name: {matching_row.iloc[0]['Competitorname']}")
        
        if matching_row.empty:
            race.logger.error(f"ERROR: Racer {competitor.first_name}, {competitor.last_name}'s points not found in database")
            continue
        
        if len(matching_row) > 1:
            race.logger.error(f"ERROR: name clash for dataframe row: {matching_row}")
            

        points = matching_row.iloc[0][race.event]
        if points == -1:
            # racer has not scored any points yet, assign them highest value
            competitor.fis_points = 999.99
        else:
            competitor.fis_points = points

        # patch for bug with name clash - assume correct Filippo for US races
        if competitor.full_name == "COLLINI, Filippo":
            mask = points_df['Fiscode'] == FILIPPO_COLLINI_FISCODE
            matching_row = points_df[mask]
            competitor.fis_points = matching_row.iloc[0][race.event]
            race.logger.info(f"POSSIBLE ERROR: Filippo Collini assigned points of {matching_row.iloc[0][race.event]}")

    return

def split_names(race):
    for competitor in race.competitors:
        name_segments = clean_name(competitor.full_name)
        competitor.last_name = name_segments[0]
        competitor.first_name = name_segments[1]
    return

# wrapper to select correct scraper based on which website was given
def scrape_results(race):
    if "vola" in race.url:
        vola_scraper(race)
        split_names(race)
        points_df = get_df_from_database(race)
        add_points_to_competitors(race, points_df)

    else:
        # livetiming contains points internally, so no need to add them manually from database
        livetiming_scraper(race)
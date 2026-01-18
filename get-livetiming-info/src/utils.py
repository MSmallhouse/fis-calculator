import sys
import logging
import pandas as pd
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
import time
import re

from scrapers import vola_scraper
from scrapers import livetiming_scraper
from scrapers import fis_livetiming_scraper

# hack fix for now, assume Filippo collini is the person from Castleton
# who is more likely to be in US races where this website will be used
NAME_ERROR_FISCODES = {
    "COLLINI, Filippo" : "6293795",
    "cfiiiilllnoopp" : "6293795",
    "SALA, Tommaso"    : "10001636",
    "aaalmmoosst"    : "10001636",
    "ROBINSON J., Carter" : "6534063"
}
NAME_ERROR_USSA_CODES = {}


def connect_to_database(race):
    table_name = "points_list_dynamo_db" if race.is_fis_race else "ussa_points_list"

    try:
        client = boto3.resource('dynamodb')
        race.table = client.Table(f'{table_name}')
    except Exception as e:
        race.logger.error("ERROR: Failed to connect to DynamoDB")
        race.logger.error(e)
        sys.exit()

    return

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
    items = []

    # fis livetiming provides us with Fiscodes, the keys for the table. So we only get the necessary rows, grabbing by fiscode
    if race.url_type == 'fis':
        column_string = f"Fiscode, {race.event}"

        fiscodes = [str(competitor.fiscode) for competitor in race.competitors]  # Ensure strings

        # BatchGetItem supports up to 100 keys per request, so we paginate manually
        for i in range(0, len(fiscodes), 100):
            keys = [{'Fiscode': fiscode} for fiscode in fiscodes[i:i+100]]
            response = race.table.meta.client.batch_get_item(
                RequestItems={
                    race.table.name: {
                        'Keys': keys,
                        'ProjectionExpression': column_string
                    }
                }
            )
            items.extend(response['Responses'].get(race.table.name, []))  # Collect results

    # vola livetiming doesn't provide fiscodes, so we need to grab the whole table
    else:
        column_string = f"Fiscode, Lastname, Firstname, Competitorname, {race.event}"

        # DynamoDB uses pagination, paginate through response to collect all data
        response = race.table.scan(
            ProjectionExpression=(column_string),
            Limit=1000  # Max items per page
        )

        while 'LastEvaluatedKey' in response:
            items.extend(response['Items'])
            response = race.table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        
        items.extend(response['Items'])
    return items

def get_df_from_database(race):
    existing_data = scan_dynamodb_table(race)
    existing_df = pd.DataFrame(existing_data)

	# convert to numeric in case these are stored as strings in DynamoDB
    existing_df[[f'{race.event}']] = existing_df[[f'{race.event}']].apply(pd.to_numeric, errors='coerce')

    return pd.DataFrame(existing_df)

# match full names by getting all characters, lowercasing, and sorting alphabetically
# Therefore, SMITH, John and john Sm-itH are considered the same
def preprocess_name(full_name):
    return ''.join(sorted(re.sub('[^a-z]', '', full_name.lower())))

def vola_fis_add_points_to_competitors(race, points_df):
    for competitor in race.competitors:
        competitor_processed_name = preprocess_name(competitor.full_name)
        points_df["ProcessedName"] = points_df["Competitorname"].apply(preprocess_name)

        mask = points_df["ProcessedName"] == competitor_processed_name
        matching_row = points_df[mask]

        if matching_row.empty:
            if race.is_fis_race:
                race.logger.error(f"ERROR: Racer {competitor.first_name}, {competitor.last_name}'s points not found in database")
            else:
                race.logger.error(f"ERROR: Racer {competitor.temp_full_name}'s points not found in database")
            # early exit if manual fix hasn't been given for this person that can't be found
            if competitor.full_name not in NAME_ERROR_FISCODES:
                continue

        # patch for bug with names
        if competitor.full_name in NAME_ERROR_FISCODES:
            mask = points_df['Fiscode'] == NAME_ERROR_FISCODES[preprocess_name(competitor.full_name)]
            matching_row = points_df[mask]
            competitor.fis_points = matching_row.iloc[0][race.event]
            race.logger.info(f"POSSIBLE ERROR: {competitor.full_name} assigned points of {matching_row.iloc[0][race.event]}")
        
        if len(matching_row) > 1:
            race.logger.error(f"ERROR: name clash for dataframe row: {matching_row}")
            

        points = matching_row.iloc[0][race.event]
        if points == -1:
            # racer has not scored any points yet, assign them highest value
            competitor.fis_points = 999.99
        else:
            competitor.fis_points = points
    return

def OLD_vola_fis_add_points_to_competitors(race, points_df):
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
                    race.logger.error(f"ERROR CORRECTION: Racer {competitor.first_name}, {competitor.last_name}'s assigned name: {matching_row.iloc[0]['Competitorname']}")
        
        if matching_row.empty:
            if race.is_fis_race:
                race.logger.error(f"ERROR: Racer {competitor.first_name}, {competitor.last_name}'s points not found in database")
            else:
                race.logger.error(f"ERROR: Racer {competitor.temp_full_name}'s points not found in database")
            # early exit if manual fix hasn't been given for this person that can't be found
            if competitor.full_name not in NAME_ERROR_FISCODES:
                continue

        # patch for bug with names
        if competitor.full_name in NAME_ERROR_FISCODES:
            mask = points_df['Fiscode'] == NAME_ERROR_FISCODES[competitor.full_name]
            matching_row = points_df[mask]
            competitor.fis_points = matching_row.iloc[0][race.event]
            race.logger.info(f"POSSIBLE ERROR: {competitor.full_name} assigned points of {matching_row.iloc[0][race.event]}")
        
        if len(matching_row) > 1:
            race.logger.error(f"ERROR: name clash for dataframe row: {matching_row}")
            

        points = matching_row.iloc[0][race.event]
        if points == -1:
            # racer has not scored any points yet, assign them highest value
            competitor.fis_points = 999.99
        else:
            competitor.fis_points = points
    return

def fis_livetiming_add_points_to_competitors(race, points_df):
    for competitor in race.competitors:
        mask = points_df["Fiscode"] == str( competitor.fiscode )
        matching_row = points_df[mask]
        
        if matching_row.empty:
            if race.is_fis_race:
                race.logger.error(f"ERROR: Racer {competitor.first_name}, {competitor.last_name}'s points not found in database")
            # early exit if manual fix hasn't been given for this person that can't be found
            if competitor.full_name not in NAME_ERROR_FISCODES:
                continue

        # patch for bug with names
        if competitor.full_name in NAME_ERROR_FISCODES and race.url_type != 'fis':
            mask = points_df['Fiscode'] == NAME_ERROR_FISCODES[competitor.full_name]
            matching_row = points_df[mask]
            competitor.fis_points = matching_row.iloc[0][race.event]
            race.logger.info(f"POSSIBLE ERROR: {competitor.full_name} assigned points of {matching_row.iloc[0][race.event]}")
        
        if len(matching_row) > 1:
            race.logger.error(f"ERROR: name clash for dataframe row: {matching_row}")

        points = matching_row.iloc[0][race.event]
        if points == -1:
            # racer has not scored any points yet, assign them highest value
            competitor.fis_points = 999.99
        else:
            competitor.fis_points = points
    return

def ussa_add_points_to_competitors(race, points_df):
    for competitor in race.competitors:
        mask = (points_df["Competitorname"] == competitor.full_name)
        matching_row = points_df[mask]

        if matching_row.empty:
            race.logger.error(f"ERROR: Racer {competitor.first_name}, {competitor.last_name}'s points not found in database")
            # early exit if manual fix hasn't been given for this person that can't be found
            if competitor.full_name not in NAME_ERROR_USSA_CODES:
                continue
                    # patch for bug with names
        if competitor.full_name in NAME_ERROR_FISCODES:
            mask = points_df['Fiscode'] == NAME_ERROR_FISCODES[competitor.full_name]
            matching_row = points_df[mask]
            competitor.fis_points = matching_row.iloc[0][race.event]
            race.logger.info(f"POSSIBLE ERROR: {competitor.full_name} assigned points of {matching_row.iloc[0][race.event]}")
        
        if len(matching_row) > 1:
            race.logger.error(f"ERROR: name clash for dataframe row: {matching_row}")

        points = matching_row.iloc[0][race.event]
        competitor.fis_points = points
    return

def split_names(race):
    for competitor in race.competitors:
        name_segments = clean_name(competitor.full_name)
        competitor.last_name = name_segments[0]
        competitor.first_name = name_segments[1]
    return

# wrapper to select correct scraper based on which website was given
def scrape_results(race):
    if race.url_type == 'live-timing':
        # livetiming contains points internally, so no need to add them manually from database
        livetiming_scraper(race)
    else:

        if race.url_type == 'vola':
            vola_scraper(race)
        elif race.url_type == 'fis':
            fis_livetiming_scraper(race)

        if race.is_fis_race and race.url_type != 'vola':
            split_names(race)

        points_df = get_df_from_database(race)

        if race.is_fis_race and race.url_type == 'vola':
            vola_fis_add_points_to_competitors(race, points_df)
        elif race.url_type == 'fis':
            fis_livetiming_add_points_to_competitors(race, points_df)
        else:
            ussa_add_points_to_competitors(race, points_df)
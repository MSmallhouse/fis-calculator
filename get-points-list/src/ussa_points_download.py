from datetime import datetime
import boto3
import sys
import requests
import zipfile
import io
import pandas as pd
import re
import traceback

from fis_points_download import update_dynamodb

CURRENT_SEASON = 25
DATES = {
    "11/21/2024": 11,
    "12/5/2024": 12,
    "12/19/2024": 13,
    "1/2/2025": 14,
    "1/16/2025": 15,
    "1/30/2025": 16,
    "2/20/2025": 17,
    "3/6/2025": 18,
    "3/20/2025": 19,
    "4/3/2025": 20,
    "4/17/2025": 21,
    "5/1/2025": 22,
    "6/1/2025": 23
}

def compose_download_url():
    date_objects = [(datetime.strptime(date, "%m/%d/%Y"), value) for date, value in DATES.items()]
    date_objects.sort()
    current_date = datetime.now()

    previous_value = None
    for date, value in date_objects:
        if date > current_date:
            break
        previous_value = value
    
    return f'https://media.usskiandsnowboard.org/CompServices/Points/Alpine/nlx{previous_value}{CURRENT_SEASON}.zip'

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


def get_points_df(download_url):
    response = requests.get(download_url)
    # download gives a zip of 3 files, we only want 2 of them
    zip_data = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_data) as z:
        files = z.namelist()
        mens_points = next((f for f in files if f.startswith("NLM") and f.endswith(".csv")), None)
        womens_points = next((f for f in files if f.startswith("NLW") and f.endswith(".csv")), None)

        mens_df = pd.read_csv( z.open(mens_points) )
        womens_df = pd.read_csv( z.open(womens_points) )
    
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
        download_url = compose_download_url()
        table = connect_to_dynamo_db(logger)
        points_df = get_points_df(download_url)

        update_dynamodb(logger, table, points_df)

    except Exception as e:
        logger.error("ERROR: error downloading ussa points")
        logger.error(f"ERROR: {e}\nStack Trace:\n{traceback.format_exc()}")
        logger.error(e)
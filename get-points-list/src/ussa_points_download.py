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

CURRENT_SEASON = 26
# format: date: list number
DATES = {
    "10/9/2025": "08",
    "10/23/2025": "09",
    "11/6/2025": "10",
    "11/20/2025": "11",
    "12/4/2025": "12",
    "12/18/2025": "13",
    "1/1/2026": "14",
    "1/15/2026": "15",
    "1/29/2026": "16",
    "2/5/2026": "17",
    "2/26/2026": "18",
    "3/12/2026": "19",
    "3/26/2026": "20",
    "4/9/2026": "21",
    "4/23/2026": "22",
    "6/1/2026": "23",
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
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "connection": "keep-alive",
        "cookie": "twk_uuid_56d0bc0b9849d3605c378c42=%7B%22uuid%22%3A%221.gNMeej7LJ1CHTeEEunguAbeSmNqcll2LJxbPcM3qhNmKZgpB2Ne74PJAuK0zusvRa8r2J8hoFq3aQ4Y3ERWU21cA6X9xQww5sdgK7svykV7C80aWoFJW5Hfpt9xHFB5GB%22%2C%22version%22%3A3%2C%22domain%22%3A%22usskiandsnowboard.org%22%2C%22ts%22%3A1759346424466%7D; cf_clearance=9OS6UB0Xg6nbyrKqQPV4MQEmxId1y9Jan0hLvyKUpog-1760298124-1.2.1.1-a2kxTT0DGQ9M4RBL.uXB4LrSzfUwL86ZH0RB4xRO77IZX5P4BNWjNWmLDoCo._mWh9e7SVRxO1PBk6Eds_EWvUdVl4PXrITQPr.ozDys3nJr1PxevN6hbwi8rbuNxPSGGKnbLD4yfujtCkwnvabzP0HTTxVuzUQkacgp5oEjs9vOt8MsDS6NWFBPShuEhcmC73Fmm_4A73B7fdm_vimTXQDZe1z4rncsnm5JdkHyiyM; _ga=GA1.2.297292582.1759340301; _gid=GA1.2.1320424359.1760298124; _gat_gtag_UA_109337157_1=1; _ga_5GD9E7LP4E=GS2.1.s1760298124$o3$g1$t1760298696$j60$l0$h0",
        "host": "media.usskiandsnowboard.org",
        "pragma": "no-cache",
        "referer": "https://www.usskiandsnowboard.org/",
        "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-site",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"

    }
    response = requests.get(download_url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to download file: status code {response.status_code}")

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
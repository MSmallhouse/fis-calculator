from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

import re
import pymysql
import pymysql.cursors
import pandas as pd

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

def clean_name(name):
    # prevents from breaking if name has no comma for some reason
    if "," not in name:
        print(f"ERROR: {name} could not be parsed correctly")
        return ["", ""]

    name = name.lower()
    name = name.split(",")
    if len(name) >= 2:
        #TODO: use strip here instead?
        # remove leading whitespace from first names, left over from splitting
        name[1] = name[1][1:-1]
    return name

def time_to_float(time):
    # reg ex to remove place ex: (1) and whitespace from time
    time = re.sub(r'\s*\(\d+\)$', '', time.strip())

    # calculate time in seconds, but only for those who finished
    if not time or time == "DNF" or time == "DNS":
        return -1
    # edge case for times under a minute
    elif ":" not in time:
        time = float(time)
    else:
        minutes = time.split(":")[0]
        seconds = time.split(":")[1]
        time = float(minutes)*60 + float(seconds)
    return time

def get_df_from_database(connection):
    with connection:
        with connection.cursor() as cursor:
            # get df of full RDS database
            query = "SELECT * FROM fis_points.point_entries"
            cursor.execute(query)
            existing_data = cursor.fetchall()

            column_names = ["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints",
                            "SLpoints", "GSpoints", "SGpoints", "ACpoints"]

            # connection not autocommitted by default
            connection.commit()
            cursor.close()
    return pd.DataFrame(existing_data, columns=column_names)
import datetime
from datetime import datetime as dt
from pytz import timezone
from datetime import date
import requests
from bs4 import BeautifulSoup

POINTS_PAGE_URL = "https://www.fis-ski.com/DB/alpine-skiing/fis-points-lists.html"
FILE_URL = "https://data.fis-ski.com/fis_athletes/ajax/fispointslistfunctions/export_fispointslist.html?export_csv=true&sectorcode=AL&seasoncode="

# adder of 26 to make this work, not really sure why
listid = 26

response = requests.get(POINTS_PAGE_URL)
if response.status_code != 200:
    print("Failed to fetch FIS points list webpage")

# parse html content
soup = BeautifulSoup(response.content, 'html.parser')

# get all div headings with the year, then grab the most recent one
year_divs = soup.find_all('div', {'class': 'g-xs g-sm g-md g-lg bold justify-center'})
year = year_divs[0].text

download_links = soup.find_all('a')
excel_links = []
for link in download_links:
    # count lists to get correct id for composing correct download url later
    if "Excel (csv)" in link.text:
        listid += 1

# get valid_from date to make sure this list is valid
# if not, decrement id so that download url is correct
# this is needed because lists are released on the website before they are "valid", so the most 
# recently published list is not gauranteed to always be valid
date_divs = soup.find_all('div', {'class': 'g-sm-3 g-md-3 g-lg-3 justify-left hidden-sm-down'})
valid_from_date = date_divs[0].text
valid_day = int(valid_from_date[0:2])
valid_month = int(valid_from_date[3:5])
valid_year = int(valid_from_date[6:])
valid_day_datetime = datetime.date(valid_year, valid_month, valid_day)

tz = timezone('EST')
current_datetime = dt.now(tz)
print(current_datetime.date())
if valid_day_datetime > current_datetime.date():
    print("decrementing")
    listid -= 1

# add year and listid to compose download url for the most recent list
FILE_URL += year + "&listid=" + str(listid)

# this response contains the csv with the most recent valid points list
response = requests.get(FILE_URL)
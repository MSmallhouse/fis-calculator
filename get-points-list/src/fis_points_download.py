import datetime
from datetime import datetime as dt
from pytz import timezone
from datetime import date
import requests
from bs4 import BeautifulSoup
import sys
import pandas as pd
import io
import boto3
from decimal import Decimal

def connect_to_dynamo_db(logger): 
	try:
		client = boto3.resource('dynamodb')
		table = client.Table('points_list_dynamo_db')
	except Exception as e:
		logger.error("ERROR: Failed to connect to DynamoDB")
		logger.error(e)
		sys.exit()
	
	logger.info("SUCCESS: Connection to DynamoDB Table succeeded")
	return table

def compose_download_url(logger):
	POINTS_PAGE_URL = "https://www.fis-ski.com/DB/alpine-skiing/fis-points-lists.html"
	FILE_URL = "https://data.fis-ski.com/fis_athletes/ajax/fispointslistfunctions/export_fispointslist.html?export_csv=true&sectorcode=AL&seasoncode="

	# adder of 26 to make this work, not really sure why
	listid = 65

	response = requests.get(POINTS_PAGE_URL)
	if response.status_code != 200:
		logger.info("ERROR: Failed to fetch FIS points list webpage")

	# parse html content
	soup = BeautifulSoup(response.content, 'html.parser')

	# get all div headings with the year, then grab the most recent one
	year_divs = soup.find_all('div', {'class': 'g-xs g-sm g-md g-lg bold justify-center'})
	#print(f"year_divs: {year_divs}")
	# TODO: fix ERROR later - this needs to be 2024 now but is showing 2025 as of 4/5/2024
	year = year_divs[1].text

	download_links = soup.find_all('a')
	for link in download_links:
		# count lists to get correct id for composing correct download url later
		if "Excel (csv)" in link.text:
			listid += 1

	# get valid from date to make sure this list is valid
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
	if valid_day_datetime > current_datetime.date():
		listid -= 1

	# compose download url for the most recent valid list
	return FILE_URL + "2025" + "&listid=" + str(listid)

def get_points_df(download_url):
	# this response contains the csv with the most recent points list
	response = requests.get(download_url).content
	df = pd.read_csv(io.StringIO(response.decode('utf-8')))
	df = df.filter(items=["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints",
					      "SLpoints", "GSpoints", "SGpoints", "ACpoints"])

	# competitors with no points will be labeled -1
	return df.fillna(-1)

def update_dynamodb(logger, table, df): 

	# obtain differential so that we limit dynamodb time by only inserting what is necessary
	df = filter_rows_needing_update(df, table)
	logger.info(f"UPDATES: {df.shape[0]} rows in database to be updated")

	rows = df.to_dict(orient="records")

	# DynamoDB doesn't support float, convert to Decimal
	for row in rows:
		# Fiscode must be a string for DynamoDB key
		row['Fiscode'] = str(row['Fiscode'])
		for key, value in row.items():
			if isinstance(value, float):
				row[key] = Decimal(str(value))

	responses = []
	for row in rows:
		fiscode = row.get('Fiscode')
		if not fiscode:
			logger.error("Missing 'Fiscode' in row in DynamoDB.")
			continue
            
		# Check if individual exists
		existing_item = table.get_item(Key={'Fiscode': fiscode})
            
		if 'Item' in existing_item:
		# Update existing item
			update_expression = """
				SET 
					Lastname = :lastname,
					Firstname = :firstname,
					Competitorname = :competitorname,
					DHpoints = :dhpoints,
					SLpoints = :slpoints,
					GSpoints = :gspoints,
					SGpoints = :sgpoints,
					ACpoints = :acpoints
			"""
			expression_attribute_values = {
				':lastname': row.get('Lastname', ''),
				':firstname': row.get('Firstname', ''),
				':competitorname': row.get('Competitorname', ''),
				':dhpoints': row.get('DHpoints', -1),
				':slpoints': row.get('SLpoints', -1),
				':gspoints': row.get('GSpoints', -1),
				':sgpoints': row.get('SGpoints', -1),
				':acpoints': row.get('ACpoints', -1),
			}
                
			table.update_item(
				Key={'Fiscode': fiscode},
				UpdateExpression=update_expression,
				ExpressionAttributeValues=expression_attribute_values
			)
			responses.append({'Fiscode': fiscode, 'action': 'updated'})
		else:
			# Insert new item
			table.put_item(Item=row)
			responses.append({'Fiscode': fiscode, 'action': 'inserted'})

def filter_rows_needing_update(new_df, table):
	existing_data = scan_dynamodb_table(table)
	
	# edge case to initialize empty df with correct columns if dymanodb table was empty and scan_dynamodb_table returned nothing
	existing_df = pd.DataFrame(columns=[["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints", "SLpoints", "GSpoints", "SGpoints", "ACpoints"]])
	if existing_data:
		existing_df = pd.DataFrame(existing_data)
	existing_df = existing_df[["Fiscode", "Lastname", "Firstname", "Competitorname", "DHpoints", "SLpoints", "GSpoints", "SGpoints", "ACpoints"]]
	# convert to numeric in case these are stored as strings in DynamoDB
	existing_df[["DHpoints", "SLpoints", "GSpoints", "SGpoints", "ACpoints"]] = existing_df[["DHpoints", "SLpoints", "GSpoints", "SGpoints", "ACpoints"]].apply(pd.to_numeric, errors='coerce')

	# need to convert these to strings for correct comparison
	existing_df["Fiscode"] = existing_df["Fiscode"].astype(str)
	new_df["Fiscode"] = new_df["Fiscode"].astype(str)

	# compare to get updated rows, or new rows
	updated_rows = []
	for index, new_row in new_df.iterrows():
		fiscode = new_row["Fiscode"]

		if fiscode not in existing_df["Fiscode"].values:
			# person doesn't exist, they must be added to database
			updated_rows.append(new_row)
			continue

		# person exists, see if their points need to be updated
		existing_row = existing_df[existing_df["Fiscode"] == fiscode].iloc[0]
		if not new_row.equals(existing_row):
			updated_rows.append(new_row)
	return pd.DataFrame(updated_rows)

def scan_dynamodb_table(table):
	# DynamoDB uses pagination, paginate through response to collect all data
	items = []
	response = table.scan()

	while 'LastEvaluatedKey' in response:
		items.extend(response['Items'])
		response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])

	items.extend(response['Items'])
	return items

def fis_points_download(logger):
	try:
		logger.info("Checking fis points")
		download_url = compose_download_url(logger)
		table = connect_to_dynamo_db(logger)
		points_df = get_points_df(download_url)

		update_dynamodb(logger, table, points_df)
	except Exception as e:
		logger.error("ERROR: error downloading ussa points")
		logger.error(e)
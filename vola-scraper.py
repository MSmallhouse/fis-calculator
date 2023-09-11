# NOTE: this used for livetiming, not vola live timing
# used the following link for building/testing
# https://vola.ussalivetiming.com/race/usa-co-vail-resort-colorado-ski-cup---spring-series_28226.html

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService

URL = 'https://vola.ussalivetiming.com/race/usa-co-vail-resort-colorado-ski-cup---spring-series_28226.html'

def chrome_instance():
    # Specify the path to the Chrome WebDriver executable
    chrome_driver_path = "C:\chromedriver.exe"

    # Create a ChromeService object
    chrome_service = ChromeService(executable_path=chrome_driver_path)

    # Initialize the Chrome WebDriver with the service
    driver = webdriver.Chrome(service=chrome_service)

    driver.get(URL)

    # Wait for page to load (adjust wait time as needed)
    driver.implicitly_wait(10)
    return driver, chrome_service


driver, chrome_service = chrome_instance()
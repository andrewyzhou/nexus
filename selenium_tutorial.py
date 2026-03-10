from selenium import webdriver
from selenium.webdriver.chrome.webdriver import WebDriver as Chrome
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

import time

service = Service(executable_path="./chromedriver")


driver = Chrome(service=service)

driver.get("https://google.com")

time.sleep(10)

driver.quit()



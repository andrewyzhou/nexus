import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

class NewsScraper:
    def __init__(self, headless=True):
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        self.driver.set_page_load_timeout(10)

    def scrape_yahoo_finance(self, ticker):
        """Scrape news for a specific stock ticker from Yahoo Finance."""
        url = f"https://finance.yahoo.com/quote/{ticker}/news"
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h3.clamp"))
            )
        except Exception:
            pass # Fallback to parsing whatever is already loaded
        
        # Scroll to load more news
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        
        articles = []
        for item in soup.find_all("h3", class_="clamp"):
            title = item.get_text()
            parent = item.find_parent("div")
            summary = ""
            if parent:
                p_tag = parent.find("p")
                if p_tag:
                    summary = p_tag.get_text()
            articles.append(f"{title}. {summary}")
            
        return " ".join(articles)

    def scrape_google_news(self, query):
        """Scrape news from Google News for a given query/ticker."""
        url = f"https://news.google.com/search?q={query}"
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a.JtKRv"))
            )
        except Exception:
            pass
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        articles = []
        for item in soup.find_all("a", class_="JtKRv"):
            title = item.get_text()
            if title:
                articles.append(f"{title}.")
        return " ".join(articles)

    def scrape_ft(self, query):
        """Scrape news from Financial Times for a given query/ticker."""
        url = f"https://www.ft.com/search?q={query}"
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.o-teaser__content"))
            )
        except Exception:
            pass
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        articles = []
        for item in soup.find_all("div", class_="o-teaser__content"):
            title_tag = item.find("a", class_="js-teaser-heading-link")
            if title_tag:
                title = title_tag.get_text()
                p_tag = item.find("p", class_="o-teaser__standfirst")
                summary = p_tag.get_text() if p_tag else ""
                articles.append(f"{title}. {summary}")
        return " ".join(articles)

    def scrape_berkshire(self, year="2026"):
        """Scrape news/press releases from Berkshire Hathaway."""
        url = f"https://www.berkshirehathaway.com/news/{year}news.html"
        self.driver.get(url)
        time.sleep(1)
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        text = soup.get_text(separator=" ")
        return " ".join(text.split())

    def scrape_all(self, ticker):
        """Scrape from all sources and combine text."""
        texts = []
        
        try:
            texts.append(self.scrape_yahoo_finance(ticker))
        except Exception as e:
            print(f"Failed to scrape Yahoo Finance for {ticker}: {e}")
            
        try:
            texts.append(self.scrape_google_news(ticker))
        except Exception as e:
            print(f"Failed to scrape Google News for {ticker}: {e}")
            
        try:
            texts.append(self.scrape_ft(ticker))
        except Exception as e:
            print(f"Failed to scrape FT for {ticker}: {e}")
            
        if ticker in ["BRK-B", "BRK-A", "BRK.B", "BRK.A"]:
             try:
                 texts.append(self.scrape_berkshire())
             except Exception as e:
                 print(f"Failed to scrape Berkshire for {ticker}: {e}")
                 
        return " ".join(texts)

    def close(self):
        self.driver.quit()

if __name__ == "__main__":
    scraper = NewsScraper()
    print("Scraping AAPL news from all sources...")
    text = scraper.scrape_all("AAPL")
    print(text)
    scraper.close()

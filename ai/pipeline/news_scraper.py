import asyncio
import os
import re
import aiohttp
import feedparser
import trafilatura
from datetime import datetime, timedelta
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

try:
    import yfinance as yf
except ImportError:
    yf = None


class NewsScraper:
    def __init__(
        self,
        finnhub_api_key: str | None = None,
        myft_rss_url: str | None = None,
    ) -> None:
        self.finnhub_api_key = finnhub_api_key or os.environ.get("FINNHUB_API_KEY")
        self.myft_rss_url = myft_rss_url or os.environ.get("MYFT_RSS_URL")

    def _is_relevant(self, text: str, title: str, ticker: str, company_name: str | None) -> bool:
        """Score relevance using ticker/company evidence and reject generic macro-only items."""
        if not text and not title:
            return False

        title_l = (title or "").lower()
        body_l = (text or "").lower()
        content_l = f"{title_l}\n{body_l}"

        score = 0.0
        t = (ticker or "").strip().lower()
        if t and re.search(rf"\b{re.escape(t)}\b", content_l):
            score += 0.6
        if t and re.search(rf"\b{re.escape(t)}\b", title_l):
            score += 0.25

        aliases: list[str] = []
        if company_name:
            aliases.append(company_name.strip().lower())
            aliases.extend(re.findall(r"[a-zA-Z]{3,}", company_name.lower()))

        for alias in aliases:
            if not alias:
                continue
            if alias in title_l:
                score += 0.25
            elif alias in body_l:
                score += 0.15

        # Penalize broad macro market commentary when ticker/company evidence is weak.
        macro_terms = [
            "s&p 500",
            "dow jones",
            "nasdaq composite",
            "federal reserve",
            "interest rates",
            "inflation",
            "treasury yields",
            "macro backdrop",
            "risk sentiment",
        ]
        macro_hits = sum(1 for m in macro_terms if m in content_l)
        if macro_hits >= 2 and score < 0.8:
            score -= 0.35

        if len((text or "").split()) >= 120:
            score += 0.05

        return score >= 0.55

    async def fetch_full_text(self, session: aiohttp.ClientSession, url: str | None) -> str:
        """Use Trafilatura to extract body text from an article URL."""
        if not url:
            return ""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    return ""
                html = await response.text()
                
                loop = asyncio.get_running_loop()
                text = await loop.run_in_executor(None, trafilatura.extract, html)
                return text if text else ""
        except Exception:
            return ""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_not_exception_type(ValueError),
    )
    async def fetch_yfinance_tier(
        self, session: aiohttp.ClientSession, ticker: str, company_name: str | None = None
    ) -> list[str]:
        """Tier 1: yfinance news ingestion."""
        if not yf:
            raise ValueError("yfinance not installed")

        def get_news():
            tick = yf.Ticker(ticker)
            return tick.news

        loop = asyncio.get_running_loop()
        news_items = await loop.run_in_executor(None, get_news)
        
        if not news_items:
            raise ValueError(f"No news found in yfinance for {ticker}")

        async def process_item(item):
            content = item.get("content", item)
            
            link = content.get("link")
            if not link and content.get("canonicalUrl"):
                link = content.get("canonicalUrl", {}).get("url")
            elif not link and content.get("clickThroughUrl"):
                link = content.get("clickThroughUrl", {}).get("url")
                
            title = content.get("title")
            
            publisher = content.get("publisher")
            if not publisher and content.get("provider"):
                publisher = content.get("provider", {}).get("displayName")
                
            if not link:
                return None

            text = await self.fetch_full_text(session, link)
          
            word_count = len(text.split()) if text else 0
            if word_count > 100 and self._is_relevant(text, title or "", ticker, company_name):
                return (
                    f"Title: {title}\n"
                    f"Source: {publisher}\n"
                    f"URL: {link}\n"
                    f"Text: {text}"
                )
            return None

        tasks = [process_item(item) for item in news_items[:5]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = [r for r in results if r and not isinstance(r, Exception)]
        if not valid_results:
            raise ValueError("No relevant text > 100 words could be extracted from yfinance links")
            
        return [valid_results[0]]

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),
    )
    async def fetch_rss_tier(
        self, session: aiohttp.ClientSession, ticker: str, company_name: str | None = None
    ) -> list[str]:
        """Tier 2: RSS feeds (myFT / Google News fallback)."""
        results: list[str] = []

        if self.myft_rss_url:
            try:
                async with session.get(self.myft_rss_url, timeout=10) as response:
                    if response.status == 200:
                        xml_data = await response.read()
                        feed = feedparser.parse(xml_data)
                        
                        async def process_entry(entry):
                            title = entry.title
                            link = entry.link
                            text = await self.fetch_full_text(session, link)
                            word_count = len(text.split()) if text else 0
                            
                            if word_count > 100 and self._is_relevant(text, title, ticker, company_name):
                                return (
                                    f"Title: {title}\n"
                                    f"Source: myFT\n"
                                    f"URL: {link}\n"
                                    f"Text: {text}"
                                )
                            return None
                            
                        tasks = [process_entry(e) for e in feed.entries[:5]]
                        rss_res = await asyncio.gather(*tasks, return_exceptions=True)
                        valid = [r for r in rss_res if r and not isinstance(r, Exception)]
                        if valid:
                            results.append(valid[0])
            except Exception as e:
                print(f"[RSS Tier] myFT failed: {e}")

        if not results:
            url = f"https://news.google.com/rss/search?q={ticker}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        xml_data = await response.read()
                        feed = feedparser.parse(xml_data)
                        
                        async def process_entry(entry):
                            title = entry.title
                            link = entry.link
                            text = await self.fetch_full_text(session, link)
                            word_count = len(text.split()) if text else 0
                            
                            if word_count > 100 and self._is_relevant(text, title, ticker, company_name):
                                return (
                                    f"Title: {title}\n"
                                    f"Source: Google News\n"
                                    f"URL: {link}\n"
                                    f"Text: {text}"
                                )
                            return None
                            
                        tasks = [process_entry(e) for e in feed.entries[:5]]
                        rss_res = await asyncio.gather(*tasks, return_exceptions=True)
                        valid = [r for r in rss_res if r and not isinstance(r, Exception)]
                        if valid:
                            results.append(valid[0])
            except Exception as e:
                print(f"[RSS Tier] Google News failed: {e}")
                
        if not results:
            raise ValueError(f"No relevant news found via RSS for {ticker}")
            
        return results

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),
        retry=retry_if_not_exception_type(ValueError),
    )
    async def fetch_finnhub_tier(
        self, session: aiohttp.ClientSession, ticker: str, company_name: str | None = None
    ) -> list[str]:
        """Tier 3: Finnhub."""
        if not self.finnhub_api_key:
            raise ValueError("FINNHUB_API_KEY not set")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        url = (
            f"https://finnhub.io/api/v1/company-news"
            f"?symbol={ticker}"
            f"&from={start_date.strftime('%Y-%m-%d')}"
            f"&to={end_date.strftime('%Y-%m-%d')}"
            f"&token={self.finnhub_api_key}"
        )
        
        async with session.get(url, timeout=10) as response:
            if response.status != 200:
                raise ValueError(f"Finnhub returned {response.status}")
                
            data = await response.json()
            if not data:
                raise ValueError(f"No news found in Finnhub for {ticker}")
                
            async def process_item(item):
                link = item.get("url")
                title = item.get("headline", "")
                text = await self.fetch_full_text(session, link)
                word_count = len(text.split()) if text else 0
                
                if word_count < 100:
                    text = item.get("summary", "")
                    word_count = len(text.split()) if text else 0
                    
                if word_count > 100 and self._is_relevant(text, title, ticker, company_name):
                    return (
                        f"Title: {title}\n"
                        f"Source: Finnhub API\n"
                        f"URL: {link}\n"
                        f"Text: {text}"
                    )
                return None
                
            tasks = [process_item(item) for item in data[:20]]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            valid_results = [r for r in results if r and not isinstance(r, Exception)]
            
            if not valid_results:
                raise ValueError("No relevant text > 100 words extracted from Finnhub")
                
            return [valid_results[0]]

    async def scrape_all(
        self, session: aiohttp.ClientSession, ticker: str, company_name: str | None = None
    ) -> str:
        """Run the multi-tier scraper concurrently.

        Attempts all tiers simultaneously and collects one valid article from each source.
        """
        final_articles: list[str] = []

        # Prioritize Finnhub first as requested.
        finnhub_result = await self.fetch_finnhub_tier(session, ticker, company_name)
        if isinstance(finnhub_result, list) and finnhub_result:
            final_articles.extend(finnhub_result)

        # Enrich with additional tiers (best effort).
        tasks = [
            self.fetch_yfinance_tier(session, ticker, company_name),
            self.fetch_rss_tier(session, ticker, company_name),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list) and r:
                final_articles.extend(r)

        return "\n\n---\n\n".join(final_articles)

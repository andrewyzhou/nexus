import asyncio
import os
import re
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import aiohttp
import feedparser
import trafilatura
from datetime import datetime, timedelta, timezone
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


@dataclass
class ArticleRecord:
    title: str
    source: str
    url: str
    published: str | None
    summary: str
    text: str
    score: float
    ticker: str


class NewsScraper:
    SOURCE_TRUST_WEIGHTS = {
        "reuters": 1.25,
        "bloomberg": 1.2,
        "financial times": 1.15,
        "wsj": 1.15,
        "wall street journal": 1.15,
        "cnbc": 1.1,
        "finnhub api": 1.0,
        "google news": 0.9,
        "yahoo": 0.95,
    }

    def __init__(
        self,
        finnhub_api_key: str | None = None,
        myft_rss_url: str | None = None,
    ) -> None:
        self.finnhub_api_key = finnhub_api_key or os.environ.get("FINNHUB_API_KEY")
        self.myft_rss_url = myft_rss_url or os.environ.get("MYFT_RSS_URL")

    def _canonicalize_url(self, url: str | None) -> str:
        if not url:
            return ""
        try:
            parts = urlsplit(url.strip())
            filtered_q = [
                (k, v)
                for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if not k.lower().startswith(("utm_", "fbclid", "gclid", "ocid", "cmpid"))
            ]
            new_query = urlencode(filtered_q, doseq=True)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, ""))
        except Exception:
            return (url or "").strip()

    def _coerce_datetime(self, value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1_000_000_000_000:
                ts /= 1000.0
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                return None
        if hasattr(value, "tm_year"):
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                return None
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                try:
                    return parsedate_to_datetime(raw)
                except Exception:
                    return None
        return None

    def _source_weight(self, source: str | None) -> float:
        src = (source or "").lower()
        for token, weight in self.SOURCE_TRUST_WEIGHTS.items():
            if token in src:
                return weight
        return 1.0

    def _freshness_bonus(self, published_at: datetime | None) -> float:
        if not published_at:
            return 0.0
        dt = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
        if age_hours <= 24:
            return 0.2
        if age_hours <= 72:
            return 0.1
        if age_hours <= 168:
            return 0.03
        return -0.05

    def _relevance_score(
        self,
        text: str,
        title: str,
        ticker: str,
        company_name: str | None,
        *,
        source: str | None = None,
        published_at: datetime | None = None,
    ) -> float:
        """Compute trust-weighted relevance score with strict ticker/company evidence."""
        if not text and not title:
            return -1.0

        title_l = (title or "").lower()
        body_l = (text or "").lower()
        content_l = f"{title_l}\n{body_l}"

        ticker_norm = (ticker or "").strip().lower()
        ticker_in_title = bool(ticker_norm and re.search(rf"\b{re.escape(ticker_norm)}\b", title_l))
        ticker_in_body = bool(ticker_norm and re.search(rf"\b{re.escape(ticker_norm)}\b", body_l))

        company_in_title = False
        company_in_body = False
        aliases: list[str] = []
        if company_name:
            aliases.append(company_name.strip().lower())
            aliases.extend(re.findall(r"[a-zA-Z]{3,}", company_name.lower()))
            deduped_aliases: list[str] = []
            seen: set[str] = set()
            for a in aliases:
                aa = a.strip()
                if aa and aa not in seen:
                    seen.add(aa)
                    deduped_aliases.append(aa)
            aliases = deduped_aliases

            for alias in aliases:
                if alias in title_l:
                    company_in_title = True
                if alias in body_l:
                    company_in_body = True

        # Relaxed evidence gate: heavily penalize, but do not hard reject.
        if not (ticker_in_title or ticker_in_body or company_in_title or company_in_body):
            score = -0.4
        else:
            score = 0.0

        if ticker_in_body:
            score += 0.6
        if ticker_in_title:
            score += 0.25
        if company_in_title:
            score += 0.25
        if company_in_body:
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
        if macro_hits >= 2 and not (ticker_in_title or company_in_title):
            score -= 0.2

        if len((text or "").split()) >= 120:
            score += 0.05

        score *= self._source_weight(source)
        score += self._freshness_bonus(published_at)

        return score

    def _is_relevant(
        self,
        text: str,
        title: str,
        ticker: str,
        company_name: str | None,
        *,
        source: str | None = None,
        published_at: datetime | None = None,
    ) -> bool:
        score = self._relevance_score(
            text,
            title,
            ticker,
            company_name,
            source=source,
            published_at=published_at,
        )
        return score >= 0.5

    def _to_article_record(
        self,
        *,
        ticker: str,
        title: str,
        source: str,
        url: str,
        text: str,
        score: float,
        published_at: datetime | None = None,
        summary: str = "",
    ) -> dict[str, object]:
        published = None
        if published_at is not None:
            dt = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
            published = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return asdict(
            ArticleRecord(
                title=title or "",
                source=source or "Unknown",
                url=(url or "").strip(),
                published=published,
                summary=(summary or "").strip(),
                text=(text or "").strip(),
                score=float(score or 0.0),
                ticker=ticker.upper().strip(),
            )
        )

    def _summarize_text(self, text: str, max_chars: int = 220) -> str:
        words = (text or "").split()
        if not words:
            return ""
        excerpt = " ".join(words[:35]).strip()
        if len(excerpt) > max_chars:
            excerpt = excerpt[: max_chars - 3].rstrip()
        return f"{excerpt}..." if excerpt and len(words) > 35 else excerpt

    def _serialize_article(self, article: dict[str, object]) -> str:
        if isinstance(article, str):
            return article
        return (
            f"Title: {article.get('title', '')}\n"
            f"Source: {article.get('source', 'Unknown')}\n"
            f"Published: {article.get('published', '')}\n"
            f"Summary: {article.get('summary', '')}\n"
            f"URL: {article.get('url', '')}\n"
            f"Text: {article.get('text', '')}"
        )

    def serialize_articles(self, articles: list[dict[str, object]]) -> str:
        return "\n\n---\n\n".join(self._serialize_article(article) for article in articles)

    def _legacy_block_to_article(self, article: str, ticker: str) -> dict[str, object]:
        def _match(pattern: str) -> str:
            found = re.search(pattern, article, flags=re.MULTILINE)
            return found.group(1).strip() if found else ""

        text = _match(r"^Text:\s*(.*)$")
        return self._to_article_record(
            ticker=ticker,
            title=_match(r"^Title:\s*(.*)$"),
            source=_match(r"^Source:\s*(.*)$") or "Unknown",
            url=_match(r"^URL:\s*(.*)$"),
            text=text,
            summary=self._summarize_text(text),
            score=0.0,
            published_at=self._coerce_datetime(_match(r"^Published:\s*(.*)$")),
        )

    def _select_top_candidates(
        self, candidates: list[dict[str, object]], k: int = 2
    ) -> list[dict[str, object]]:
        if not candidates:
            return []

        dedup: dict[str, dict[str, object]] = {}
        for c in candidates:
            url = self._canonicalize_url(str(c.get("url", "") or ""))
            key = url or str(c.get("title", "") or "").strip().lower()
            if not key:
                continue
            prior = dedup.get(key)
            if prior is None or float(c.get("score", 0.0) or 0.0) > float(prior.get("score", 0.0) or 0.0):
                dedup[key] = c

        ranked = sorted(dedup.values(), key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
        return ranked[: max(1, k)]

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
    ) -> list[dict[str, object]]:
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
            source_summary = (content.get("summary") or content.get("description") or "").strip()
            published_at = self._coerce_datetime(
                content.get("providerPublishTime")
                or content.get("pubDate")
                or content.get("published")
            )
                
            if not link:
                return None

            text = await self.fetch_full_text(session, link)
          
            word_count = len(text.split()) if text else 0
            if word_count > 100 and self._is_relevant(
                text,
                title or "",
                ticker,
                company_name,
                source=publisher,
                published_at=published_at,
            ):
                return self._to_article_record(
                    ticker=ticker,
                    title=title or "",
                    source=publisher or "Yahoo Finance",
                    url=link,
                    text=text,
                    published_at=published_at,
                    summary=source_summary or self._summarize_text(text),
                    score=self._relevance_score(
                        text,
                        title or "",
                        ticker,
                        company_name,
                        source=publisher,
                        published_at=published_at,
                    ),
                )
            return None

        tasks = [process_item(item) for item in news_items[:5]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = [r for r in results if isinstance(r, dict)]
        if not valid_results:
            raise ValueError("No relevant text > 100 words could be extracted from yfinance links")

        picked = self._select_top_candidates(valid_results, k=2)
        if not picked:
            raise ValueError("No relevant text > 100 words could be extracted from yfinance links")
        return picked

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),
    )
    async def fetch_rss_tier(
        self, session: aiohttp.ClientSession, ticker: str, company_name: str | None = None
    ) -> list[dict[str, object]]:
        """Tier 2: RSS feeds (myFT / Google News fallback)."""
        results: list[dict[str, object]] = []

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
                            published_at = self._coerce_datetime(
                                getattr(entry, "published_parsed", None)
                                or getattr(entry, "updated_parsed", None)
                                or getattr(entry, "published", None)
                            )
                            
                            if word_count > 100 and self._is_relevant(
                                text,
                                title,
                                ticker,
                                company_name,
                                source="myFT",
                                published_at=published_at,
                            ):
                                return self._to_article_record(
                                    ticker=ticker,
                                    title=title or "",
                                    source="myFT",
                                    url=link,
                                    text=text,
                                    published_at=published_at,
                                    summary=self._summarize_text(text),
                                    score=self._relevance_score(
                                        text,
                                        title,
                                        ticker,
                                        company_name,
                                        source="myFT",
                                        published_at=published_at,
                                    ),
                                )
                            return None
                            
                        tasks = [process_entry(e) for e in feed.entries[:5]]
                        rss_res = await asyncio.gather(*tasks, return_exceptions=True)
                        valid = [r for r in rss_res if isinstance(r, dict)]
                        if valid:
                            results.extend(self._select_top_candidates(valid, k=2))
            except Exception as e:
                print(f"[RSS Tier] myFT failed: {e}")

        if not results:
            company_clause = f' OR "{company_name}"' if company_name else ""
            query = (
                f"({ticker}{company_clause}) "
                "(earnings OR guidance OR forecast OR acquisition OR product OR sec OR lawsuit) "
                "when:3d"
            )
            url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
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
                            published_at = self._coerce_datetime(
                                getattr(entry, "published_parsed", None)
                                or getattr(entry, "updated_parsed", None)
                                or getattr(entry, "published", None)
                            )
                            
                            if word_count > 100 and self._is_relevant(
                                text,
                                title,
                                ticker,
                                company_name,
                                source="Google News",
                                published_at=published_at,
                            ):
                                return self._to_article_record(
                                    ticker=ticker,
                                    title=title or "",
                                    source="Google News",
                                    url=link,
                                    text=text,
                                    published_at=published_at,
                                    summary=self._summarize_text(text),
                                    score=self._relevance_score(
                                        text,
                                        title,
                                        ticker,
                                        company_name,
                                        source="Google News",
                                        published_at=published_at,
                                    ),
                                )
                            return None
                            
                        tasks = [process_entry(e) for e in feed.entries[:5]]
                        rss_res = await asyncio.gather(*tasks, return_exceptions=True)
                        valid = [r for r in rss_res if isinstance(r, dict)]
                        if valid:
                            results.extend(self._select_top_candidates(valid, k=2))
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
    ) -> list[dict[str, object]]:
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
                source_summary = (item.get("summary") or "").strip()
                text = await self.fetch_full_text(session, link)
                word_count = len(text.split()) if text else 0
                
                if word_count < 100:
                    text = item.get("summary", "")
                    word_count = len(text.split()) if text else 0
                    
                published_at = self._coerce_datetime(item.get("datetime"))

                if word_count > 100 and self._is_relevant(
                    text,
                    title,
                    ticker,
                    company_name,
                    source="Finnhub API",
                    published_at=published_at,
                ):
                    return self._to_article_record(
                        ticker=ticker,
                        title=title or "",
                        source="Finnhub API",
                        url=link,
                        text=text,
                        published_at=published_at,
                        summary=source_summary or self._summarize_text(text),
                        score=self._relevance_score(
                            text,
                            title,
                            ticker,
                            company_name,
                            source="Finnhub API",
                            published_at=published_at,
                        ),
                    )
                return None
                
            tasks = [process_item(item) for item in data[:20]]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            valid_results = [r for r in results if isinstance(r, dict)]
            
            if not valid_results:
                raise ValueError("No relevant text > 100 words extracted from Finnhub")

            picked = self._select_top_candidates(valid_results, k=3)
            if not picked:
                raise ValueError("No relevant text > 100 words extracted from Finnhub")
            return picked

    async def scrape_all_articles(
        self, session: aiohttp.ClientSession, ticker: str, company_name: str | None = None
    ) -> list[dict[str, object]]:
        """Run the multi-tier scraper concurrently.

        Attempts all tiers simultaneously and collects one valid article from each source.
        """
        final_articles: list[dict[str, object]] = []

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

        # Canonical URL dedupe across tiers.
        unique_articles: list[dict[str, object]] = []
        seen_urls: set[str] = set()
        for article in final_articles:
            if isinstance(article, str):
                article = self._legacy_block_to_article(article, ticker)
            canonical = self._canonicalize_url(str(article.get("url", "") or ""))
            if canonical and canonical in seen_urls:
                continue
            if canonical:
                seen_urls.add(canonical)
            unique_articles.append(article)

        return unique_articles

    async def scrape_all(
        self, session: aiohttp.ClientSession, ticker: str, company_name: str | None = None
    ) -> str:
        articles = await self.scrape_all_articles(session, ticker, company_name)
        return self.serialize_articles(articles)

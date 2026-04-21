# Yahoo Finance bulk scraper
# Scrapes company metadata (price, market cap, sector, industry, etc.) for all tickers
"""
Yahoo Finance Stock Scraper
On-demand + bulk stock data using Yahoo Finance (free, no API key).
Uses curl_cffi for browser-like TLS fingerprinting to avoid rate limits.
Async bulk mode for high throughput (~20-40 stocks/sec).

Usage:
    python scraper.py NVDA                    # single stock
    python scraper.py NVDA AAPL MSFT TSLA     # multiple stocks
    python scraper.py --file tickers.txt      # from file
    python scraper.py --test                  # test with 5 stocks

As a module:
    from scraper import StockScraper
    scraper = StockScraper()
    data = scraper.get("NVDA")
    bulk = scraper.get_bulk(["NVDA", "AAPL", "MSFT", ...])
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from threading import Lock

from curl_cffi import requests as cfreq
from curl_cffi.requests import AsyncSession

# ten_k_fetch was superseded by the sec_pipeline/ directory setup but this
# file still references it in the __main__ SEC-dump path. Keep the import
# optional so `from scraper import StockScraper` works for the hot path
# (Yahoo Finance pulls) even when ten_k_fetch.py isn't in sys.path.
ROOT = Path(__file__).resolve().parent.parent
SEC_SUPPLIERS_DIR = ROOT / "sec_pipeline" / "suppliers"
SEC_SUPPLIERS_DIR_STR = str(SEC_SUPPLIERS_DIR)
if SEC_SUPPLIERS_DIR.is_dir() and SEC_SUPPLIERS_DIR_STR not in sys.path:
    sys.path.insert(0, SEC_SUPPLIERS_DIR_STR)
try:
    from fetcher import fetch_sec_sections
except ModuleNotFoundError:
    def fetch_sec_sections(ticker):  # type: ignore
        raise RuntimeError(
            "ten_k_fetch is not installed. The scraper's SEC-sections path "
            "moved to sec_pipeline/; use that module instead."
        )


# ── Yahoo Finance API ────────────────────────────────────────────────────────

QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary"
CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"

MODULES = "price,summaryDetail,assetProfile,defaultKeyStatistics,calendarEvents"

API_HEADERS = {
    "Origin": "https://finance.yahoo.com",
    "Referer": "https://finance.yahoo.com/",
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _raw(obj, key, default=None):
    if obj is None:
        return default
    val = obj.get(key)
    if val is None:
        return default
    if isinstance(val, dict):
        return val.get("raw", val.get("fmt", default))
    return val


def _fmt(obj, key, default="--"):
    if obj is None:
        return default
    val = obj.get(key)
    if val is None:
        return default
    if isinstance(val, dict):
        return val.get("fmt", str(val.get("raw", default)))
    return str(val)


def _parse(data: dict, ticker: str) -> dict | None:
    results = data.get("quoteSummary", {}).get("result")
    if not results:
        return None

    r = results[0]
    price = r.get("price", {})
    detail = r.get("summaryDetail", {})
    profile = r.get("assetProfile", {})
    stats = r.get("defaultKeyStatistics", {})
    cal = r.get("calendarEvents", {})

    earnings_dates = cal.get("earnings", {}).get("earningsDate", [])
    earnings_date = earnings_dates[0].get("fmt", "--") if earnings_dates else "--"

    return {
        "ticker": ticker,
        "companyName": price.get("longName") or price.get("shortName", ""),
        "exchange": price.get("exchangeName", ""),
        "currency": price.get("currency", ""),
        "quoteType": price.get("quoteType", ""),

        "price": _raw(price, "regularMarketPrice"),
        "change": _raw(price, "regularMarketChange"),
        "changePercent": _raw(price, "regularMarketChangePercent"),
        "previousClose": _raw(detail, "previousClose"),
        "open": _raw(detail, "open"),
        "dayHigh": _raw(detail, "dayHigh"),
        "dayLow": _raw(detail, "dayLow"),
        "volume": _raw(detail, "volume"),
        "avgVolume": _raw(detail, "averageVolume"),
        "avgVolume10Day": _raw(detail, "averageDailyVolume10Day"),
        "marketCap": _raw(price, "marketCap"),
        "marketCapFmt": _fmt(price, "marketCap"),

        "trailingPE": _raw(detail, "trailingPE"),
        "forwardPE": _raw(detail, "forwardPE"),
        "trailingEPS": _raw(stats, "trailingEps"),
        "forwardEPS": _raw(stats, "forwardEps"),
        "pegRatio": _raw(stats, "pegRatio"),
        "priceToBook": _raw(stats, "priceToBook"),
        "priceToSales": _raw(detail, "priceToSalesTrailing12Months"),
        "enterpriseValue": _raw(stats, "enterpriseValue"),
        "enterpriseToRevenue": _raw(stats, "enterpriseToRevenue"),
        "enterpriseToEbitda": _raw(stats, "enterpriseToEbitda"),

        "fiftyTwoWeekLow": _raw(detail, "fiftyTwoWeekLow"),
        "fiftyTwoWeekHigh": _raw(detail, "fiftyTwoWeekHigh"),
        "fiftyDayAvg": _raw(detail, "fiftyDayAverage"),
        "twoHundredDayAvg": _raw(detail, "twoHundredDayAverage"),
        "beta": _raw(detail, "beta"),
        "52WeekChange": _raw(stats, "52WeekChange"),

        "dividendRate": _raw(detail, "dividendRate"),
        "dividendYield": _raw(detail, "dividendYield"),
        "exDividendDate": _fmt(cal, "exDividendDate"),
        "payoutRatio": _raw(detail, "payoutRatio"),

        "profitMargin": _raw(stats, "profitMargins"),
        "revenueGrowth": _raw(price, "revenueGrowth"),
        "returnOnEquity": _raw(stats, "returnOnEquity") if stats.get("returnOnEquity") else None,
        "bookValue": _raw(stats, "bookValue"),
        "sharesOutstanding": _raw(stats, "sharesOutstanding"),
        "floatShares": _raw(stats, "floatShares"),
        "heldByInsiders": _raw(stats, "heldPercentInsiders"),
        "heldByInstitutions": _raw(stats, "heldPercentInstitutions"),
        "shortRatio": _raw(stats, "shortRatio"),
        "earningsDate": earnings_date,

        "sector": profile.get("sector", ""),
        "industry": profile.get("industry", ""),
        "fullTimeEmployees": profile.get("fullTimeEmployees"),
        "website": profile.get("website", ""),
        "description": profile.get("longBusinessSummary", ""),
        "sections": {},
        "city": profile.get("city", ""),
        "state": profile.get("state", ""),
        "country": profile.get("country", ""),

        "bid": _raw(detail, "bid"),
        "ask": _raw(detail, "ask"),
        "bidSize": _raw(detail, "bidSize"),
        "askSize": _raw(detail, "askSize"),

        "targetMeanPrice": _raw(stats, "targetMeanPrice") or _raw(detail, "targetMeanPrice"),
        "targetHighPrice": _raw(stats, "targetHighPrice") or _raw(detail, "targetHighPrice"),
        "targetLowPrice": _raw(stats, "targetLowPrice") or _raw(detail, "targetLowPrice"),
        "recommendationKey": stats.get("recommendationKey", ""),
        "numberOfAnalysts": _raw(stats, "numberOfAnalystOpinions"),
    }


# ── Rate limiter ─────────────────────────────────────────────────────────────

class _RateLimiter:
    """Token bucket rate limiter for async requests."""

    def __init__(self, rate: float):
        self._rate = rate
        self._tokens = rate
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self._rate, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


# ── Scraper class ────────────────────────────────────────────────────────────

class StockScraper:
    """
    Yahoo Finance stock scraper. Free, no API key.
    Uses curl_cffi for browser-like TLS fingerprinting.
    Async bulk mode for high throughput.
    """

    def __init__(self):
        self._session = cfreq.Session(impersonate="chrome")
        self._crumb = None
        self._crumb_ts = 0
        self._lock = Lock()

    def _ensure_auth(self):
        with self._lock:
            if self._crumb and (time.time() - self._crumb_ts < 300):
                return
            try:
                self._session.get("https://fc.yahoo.com")
            except Exception:
                pass
            r = self._session.get(CRUMB_URL)
            r.raise_for_status()
            self._crumb = r.text.strip()
            self._crumb_ts = time.time()

    def get(self, ticker: str) -> dict | None:
        """Fetch all data for a single stock (sync)."""
        self._ensure_auth()
        ticker = ticker.upper().strip()
        r = self._session.get(
            f"{QUOTE_SUMMARY_URL}/{ticker}",
            params={"modules": MODULES, "crumb": self._crumb, "lang": "en-US", "region": "US"},
            headers=API_HEADERS,
            timeout=15,
        )
        if r.status_code == 404:
            return None
        if r.status_code in (401, 403):
            self._crumb = None
            self._ensure_auth()
            r = self._session.get(
                f"{QUOTE_SUMMARY_URL}/{ticker}",
                params={"modules": MODULES, "crumb": self._crumb, "lang": "en-US", "region": "US"},
                headers=API_HEADERS,
                timeout=15,
            )
        r.raise_for_status()
        return _parse(r.json(), ticker)

    # ── Async bulk engine ─────────────────────────────────────────────────

    async def _async_auth(self, session: AsyncSession, retries: int = 5):
        """
        Get cookies + crumb for an async session.

        Yahoo will occasionally 429 the crumb endpoint if we've hammered it.
        Back off exponentially (1s, 2s, 4s, 8s, 16s) before giving up — a
        failed auth used to crash the whole bulk run.
        """
        last_exc = None
        for attempt in range(retries + 1):
            try:
                try:
                    await session.get("https://fc.yahoo.com")
                except Exception:
                    pass
                r = await session.get(CRUMB_URL)
                if r.status_code == 429 or r.status_code >= 500:
                    raise RuntimeError(f"crumb fetch returned {r.status_code}")
                r.raise_for_status()
                return r.text.strip()
            except Exception as e:
                last_exc = e
                if attempt < retries:
                    wait = 2 ** attempt
                    print(f"  [auth] {e}, sleeping {wait}s (attempt {attempt+1}/{retries+1})", file=sys.stderr)
                    await asyncio.sleep(wait)
        raise RuntimeError(f"crumb auth failed after {retries+1} attempts: {last_exc}")

    async def _async_fetch_one(
        self, session: AsyncSession, state: dict, sem: asyncio.Semaphore,
        rate_limiter, ticker: str, retries: int = 2,
    ) -> tuple[str, dict | None]:
        """Fetch a single ticker with rate limiting + concurrency control."""
        # Yahoo URL-encodes class-share tickers with a hyphen, not a dot.
        # BRK.B / BF.B / CRD.A / MOG.A all 404 without this normalization.
        query_ticker = ticker.replace(".", "-")

        async with sem:
            await rate_limiter.acquire()
            for attempt in range(retries + 1):
                try:
                    r = await session.get(
                        f"{QUOTE_SUMMARY_URL}/{query_ticker}",
                        params={"modules": MODULES, "crumb": state["crumb"], "lang": "en-US", "region": "US"},
                        headers=API_HEADERS,
                        timeout=15,
                    )
                    if r.status_code == 404:
                        return ticker, None
                    if r.status_code == 429:
                        # Ticker-level rate limit — back off and retry.
                        if attempt < retries:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        return ticker, None
                    if r.status_code in (401, 403):
                        async with state["auth_lock"]:
                            if state["crumb"] == state.get("_last_failed_crumb"):
                                pass  # already refreshed by another task
                            else:
                                state["_last_failed_crumb"] = state["crumb"]
                                state["crumb"] = await self._async_auth(session)
                        if attempt < retries:
                            await asyncio.sleep(0.5)
                            continue
                    r.raise_for_status()
                    return ticker, _parse(r.json(), ticker)
                except Exception:
                    if attempt < retries:
                        await asyncio.sleep(0.5 + attempt)
                        continue
                    return ticker, None

    async def _run_batch(
        self,
        tickers: list[str],
        concurrency: int,
        rate_per_sec: float,
    ) -> tuple[list[dict], list[str], bool]:
        """Run a single batch with a fresh session.

        Returns (results, per_ticker_failures, auth_failed). When
        auth_failed is True, *no* tickers in the batch were actually hit
        — the caller should re-queue them for a retry pass rather than
        treating them as "not found on Yahoo."
        """
        results = []
        failed = []
        sem = asyncio.Semaphore(concurrency)
        rate_limiter = _RateLimiter(rate_per_sec)

        async with AsyncSession(impersonate="chrome") as session:
            crumb = await self._async_auth(session)
            state = {"crumb": crumb, "auth_lock": asyncio.Lock()}

            tasks = [
                self._async_fetch_one(session, state, sem, rate_limiter, t)
                for t in tickers
            ]

            for coro in asyncio.as_completed(tasks):
                ticker, data = await coro
                if data:
                    results.append(data)
                else:
                    failed.append(ticker)

        return results, failed, False

    async def _run_bulk(
        self,
        tickers: list[str],
        concurrency: int = 25,
        rate_per_sec: float = 80,
        batch_size: int = 500,
        batch_pause: float = 5.0,
        save_every: int = 500,
        output_file: str = None,
        on_progress=None,
    ) -> list[dict]:
        """Core async bulk engine. Processes in batches with fresh sessions."""
        all_results = []
        all_failed = []
        auth_skipped: list[list[str]] = []   # batches we need to retry later
        total = len(tickers)
        done = 0

        for batch_start in range(0, total, batch_size):
            batch = tickers[batch_start : batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size

            results, failed, auth_failed = await self._run_batch(batch, concurrency, rate_per_sec)

            for data in results:
                all_results.append(data)
            if auth_failed:
                auth_skipped.append(batch)   # re-queue, don't mark as failed yet
            else:
                all_failed.extend(failed)
            done += len(batch)

            if on_progress:
                ok = len(results)
                fail = len(failed) if not auth_failed else 0
                on_progress(done, total, batch_num, total_batches, ok, fail)

            if output_file and all_results:
                with open(output_file, "w") as f:
                    json.dump(all_results, f, indent=2, default=str)

            # Pause between batches (fresh session resets Yahoo's rate counter)
            if batch_start + batch_size < total:
                await asyncio.sleep(batch_pause)

        # Retry pass for batches whose crumb-auth was rate-limited. Give
        # Yahoo a longer cooldown first, shrink batch size so we're less
        # conspicuous, and try up to 3 times per batch.
        if auth_skipped:
            n = sum(len(b) for b in auth_skipped)
            print(f"\n  [retry] {len(auth_skipped)} auth-skipped batches "
                  f"({n} tickers) — cooling 30s then retrying", file=sys.stderr)
            await asyncio.sleep(30)
            retry_batch_size = max(100, batch_size // 2)
            for retry_round in range(3):
                if not auth_skipped:
                    break
                # Flatten and re-split into smaller batches
                queue = [t for batch in auth_skipped for t in batch]
                auth_skipped = []
                print(f"  [retry round {retry_round + 1}/3] "
                      f"{len(queue)} tickers in batches of {retry_batch_size}",
                      file=sys.stderr)
                for b_start in range(0, len(queue), retry_batch_size):
                    sub = queue[b_start : b_start + retry_batch_size]
                    results, failed, auth_failed = await self._run_batch(
                        sub, concurrency, rate_per_sec
                    )
                    for data in results:
                        all_results.append(data)
                    if auth_failed:
                        auth_skipped.append(sub)
                    else:
                        all_failed.extend(failed)
                    if b_start + retry_batch_size < len(queue):
                        await asyncio.sleep(batch_pause)
                if auth_skipped:
                    # Still stuck — wait longer before the next round.
                    await asyncio.sleep(30 * (retry_round + 1))
            # Anything still auth-skipped after 3 rounds is genuinely lost.
            for batch in auth_skipped:
                all_failed.extend(batch)
                print(f"  [!] {len(batch)} tickers lost to repeated auth "
                      f"failure (first: {batch[:5]})", file=sys.stderr)

        if all_failed:
            n = len(all_failed)
            sample = ", ".join(all_failed[:20])
            print(f"\n  [!] {n} failed/not found. Sample: {sample}", file=sys.stderr)
            # Persist the full failed list so we can inspect what Yahoo
            # doesn't have instead of scrolling stderr.
            try:
                failed_path = Path(__file__).resolve().parent / "failed_tickers.txt"
                failed_path.write_text("\n".join(sorted(all_failed)) + "\n")
                print(f"      full list → {failed_path}", file=sys.stderr)
            except Exception:
                pass

        return all_results

    def get_bulk(
        self,
        tickers: list[str],
        concurrency: int = 25,
        rate_per_sec: float = 80,
        batch_size: int = 500,
        batch_pause: float = 5.0,
        save_every: int = 500,
        output_file: str = None,
        on_progress=None,
    ) -> list[dict]:
        """
        Fetch data for many tickers using async concurrency.
        Processes in batches of ~500 with fresh sessions to avoid rate limits.
        ~80-100 stocks/sec effective throughput.
        """
        tickers = [t.upper().strip() for t in tickers]
        return asyncio.run(self._run_bulk(
            tickers,
            concurrency=concurrency,
            rate_per_sec=rate_per_sec,
            batch_size=batch_size,
            batch_pause=batch_pause,
            save_every=save_every,
            output_file=output_file,
            on_progress=on_progress,
        ))

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# ── CLI ──────────────────────────────────────────────────────────────────────

def _fmt_num(n):
    if n is None:
        return "--"
    if abs(n) >= 1e12:
        return f"{n/1e12:.2f}T"
    if abs(n) >= 1e9:
        return f"{n/1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"{n/1e6:.2f}M"
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def main():
    tickers = []
    output_file = None
    concurrency = None

    args = sys.argv[1:]
    if "--test" in args:
        tickers = ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN"]
        args.remove("--test")
    elif "--file" in args:
        idx = args.index("--file")
        filepath = args[idx + 1]
        tickers = [l.strip().upper() for l in Path(filepath).read_text().splitlines() if l.strip()]
        args = args[:idx] + args[idx+2:]

    if "--output" in args:
        idx = args.index("--output")
        output_file = args[idx + 1]
        args = args[:idx] + args[idx+2:]

    if "--workers" in args:
        idx = args.index("--workers")
        concurrency = int(args[idx + 1])
        args = args[:idx] + args[idx+2:]

    tickers += [t.upper() for t in args if not t.startswith("-")]

    if not tickers:
        print("Usage: python scraper.py NVDA [AAPL MSFT ...]")
        print("       python scraper.py --file tickers.txt --output data.json")
        print("       python scraper.py --test")
        print("       python scraper.py --file tickers.txt --workers 50")
        sys.exit(1)

    with StockScraper() as scraper:
        if len(tickers) == 1:
            ticker = tickers[0]
            print(f"\nFetching {ticker}...")
            start = time.time()
            data = scraper.get(ticker)
            elapsed = time.time() - start

            if not data:
                print(f"  Not found: {ticker}")
                sys.exit(1)

            print(f"\n{'=' * 60}")
            print(f"  {data['companyName']} ({data['ticker']})")
            print(f"  {data['exchange']} | {data['currency']}")
            print(f"{'=' * 60}")
            print(f"  Price:      ${data['price']}")
            print(f"  Market Cap: {_fmt_num(data['marketCap'])}")
            print(f"  PE (TTM):   {data['trailingPE']}  |  Fwd PE: {data['forwardPE']}")
            print(f"  EPS (TTM):  {data['trailingEPS']}  |  Fwd EPS: {data['forwardEPS']}")
            print(f"  Beta:       {data['beta']}")
            print(f"  52W Range:  {data['fiftyTwoWeekLow']} - {data['fiftyTwoWeekHigh']}")
            print(f"  Volume:     {_fmt_num(data['volume'])}  |  Avg: {_fmt_num(data['avgVolume'])}")
            print(f"  Sector:     {data['sector']}  |  Industry: {data['industry']}")
            emp = data.get("fullTimeEmployees")
            print(f"  Employees:  {_fmt_num(emp) if emp else '--'}")
            desc = data.get("description", "")
            print(f"\n  Description ({len(desc)} chars):")
            words = desc.split()
            line = "  "
            for w in words:
                if len(line) + len(w) + 1 > 72:
                    print(line)
                    line = "  " + w
                else:
                    line += " " + w if line.strip() else "  " + w
            if line.strip():
                print(line)

            print(f"\n  Fetched in {elapsed:.2f}s")

            if output_file:
                with open(output_file, "w") as f:
                    json.dump(data, f, indent=2, default=str)
                print(f"  Saved to {output_file}")
            else:
                print("\n--- Full JSON ---")
                print(json.dumps(data, indent=2, default=str))
        else:
            # Bulk mode (async with batching)
            c = concurrency or 25
            batch_size = 500
            out = output_file or "stock_data.json"
            n_batches = (len(tickers) + batch_size - 1) // batch_size
            print(f"\nScraping {len(tickers)} stocks ({c} concurrent, {n_batches} batches of {batch_size})...")
            start = time.time()

            def progress(done, total, batch_num, total_batches, ok, fail):
                pct = done / total * 100
                elapsed = time.time() - start
                r = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / r if r > 0 else 0
                print(
                    f"\r  Batch {batch_num}/{total_batches} done ({ok} OK, {fail} fail)  "
                    f"| [{done}/{total}] ({pct:.0f}%) "
                    f"| {r:.0f}/s | ETA {eta:.0f}s    ",
                    end="",
                    flush=True,
                )

            results = scraper.get_bulk(
                tickers,
                concurrency=c,
                batch_size=batch_size,
                batch_pause=5.0,
                save_every=500,
                output_file=out,
                on_progress=progress,
            )
            elapsed = time.time() - start

            # SEC Filings
            output_sec_dir = Path("data/raw")

            for ticker in tickers:
                sections = fetch_sec_sections(ticker)
                
                path = output_sec_dir / f"{ticker}_sections.txt"
                with open(path, "w", encoding="utf-8") as file:
                    file.write(f"{ticker}")
                    file.write("=" * 60 + "\n\n")

                    for section_name, section_text in sections.items():
                        file.write(f"--- {section_name.upper()} ---\n")
                        file.write(section_text if section_text else "[NOT FOUND]")
                        file.write("\n\n")

            # Final save
            with open(out, "w") as f:
                json.dump(results, f, indent=2, default=str)

            print(f"\n\n  Done: {len(results)}/{len(tickers)} stocks in {elapsed:.1f}s")
            print(f"  Rate: {len(results) / elapsed:.0f} stocks/sec")
            print(f"  Saved to {out}")


if __name__ == "__main__":
    main()


#python scraper/scraper.py --file scraper/all_tickers.txt --output scraper/data/processed/stock_data.json

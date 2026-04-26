"""
news_fetch.py — multi-source article fetcher feeding /summary endpoints.

Pipeline per ticker:
  yfinance + Finnhub  →  dedupe-by-canonical-URL  →  on-topic filter
                      →  resolve Finnhub redirects  →  body fetch
                      →  return [{title, url, publisher, published, image,
                                  blurb, body, ...}]

Decisions backed by a 1,193-article benchmark:
  - Whitelist > blacklist: trafilatura works on most sources; failures
    cluster on a small predictable set of paywalled / Cloudflare-blocked
    domains. Maintain BLACKLIST_HOSTS rather than a whitelist.
  - Pre-resolve finnhub.io URLs to their canonical destination — hitting
    them with high concurrency triggers 429s.
  - Drop articles that don't mention the ticker symbol or company name
    in title/blurb/body — ~23% of "news for ticker X" doesn't actually
    mention X.
  - 16 parallel workers for body fetch; p50 ~1s, p90 ~2s.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any

import psycopg2
import psycopg2.extras
import trafilatura


FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_LOOKBACK_DAYS = int(os.getenv("FINNHUB_LOOKBACK_DAYS", "7"))

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Hosts where body fetch is reliably blocked or paywalled; skip the round-trip
# and fall back to the API-supplied blurb. See benchmark in the news pipeline
# notes — these all produced 0% extraction success on ≥3 attempts.
BLACKLIST_HOSTS: set[str] = {
    "seekingalpha.com", "thestreet.com", "barrons.com", "wsj.com",
    "marketwatch.com", "ft.com", "nytimes.com", "qz.com",
    "fintel.io", "247wallst.com", "freep.com", "chartmill.com",
    "app.moby.co", "euronews.com",
}

# The Finnhub "company-news" endpoint returns redirect URLs. Requesting them
# in parallel with high concurrency burns through their rate limit; resolve
# with a small thread pool first, then apply the blacklist on the final host.
FINNHUB_REDIRECT_HOST = "finnhub.io"

# The yfinance-syndicated Bloomberg blurb is hard-capped at 500 chars and
# always ends with a "Most Read from Bloomberg" cross-promo block. Strip it
# so the prompt isn't poisoned with unrelated headlines.
_BLOOMBERG_FOOTER = re.compile(r"Most Read from Bloomberg.*$", re.DOTALL)

BODY_MIN_CHARS = 300       # extracted body shorter than this = treat as failed
BODY_MAX_CHARS = 12_000    # truncate before sending to Claude — p99 is ~12k
HTTP_TIMEOUT = 8           # seconds per body fetch
PARALLEL_BODY_WORKERS = 16
PARALLEL_REDIRECT_WORKERS = 4

ARTICLE_BODY_CACHE_TTL = timedelta(hours=24)


# ─────────────────────────── source: yfinance ─────────────────────────────

def fetch_yfinance(ticker: str) -> list[dict]:
    try:
        import yfinance as yf
    except Exception:
        return []
    try:
        items = yf.Ticker(ticker).news or []
    except Exception as e:
        print(f"[news] yfinance failed for {ticker}: {e}")
        return []

    out: list[dict] = []
    for it in items:
        c = it.get("content") or it
        title = c.get("title") or it.get("title")
        if not title:
            continue
        url = (
            (c.get("clickThroughUrl") or {}).get("url")
            or (c.get("canonicalUrl") or {}).get("url")
            or it.get("link")
        )
        if not url:
            continue
        publisher = (
            (c.get("provider") or {}).get("displayName")
            or c.get("publisher")
            or it.get("publisher")
            or ""
        )
        published = c.get("pubDate") or c.get("displayTime") or it.get("providerPublishTime")
        blurb = (c.get("summary") or c.get("description") or "").strip()
        if publisher == "Bloomberg":
            blurb = _BLOOMBERG_FOOTER.sub("", blurb).strip()

        # Image: prefer the smallest "tagged" resolution above 170×128 if present;
        # fall back to originalUrl. We surface this on the news card thumbnail.
        image = None
        thumb = c.get("thumbnail") or {}
        for r in thumb.get("resolutions") or []:
            if r.get("tag") == "170x128" and r.get("url"):
                image = r["url"]
                break
        if not image:
            image = thumb.get("originalUrl")

        out.append({
            "src": "yfinance",
            "title": title,
            "url": url,
            "publisher": publisher,
            "published": published,
            "blurb": blurb,
            "image": image,
            "content_type": c.get("contentType") or "",
            "ticker": ticker,
        })
    return out


# ─────────────────────────── source: Finnhub ──────────────────────────────

def fetch_finnhub(ticker: str, max_items: int = 30) -> list[dict]:
    if not FINNHUB_API_KEY:
        return []
    today = date.today()
    since = today - timedelta(days=FINNHUB_LOOKBACK_DAYS)
    url = (
        "https://finnhub.io/api/v1/company-news"
        f"?symbol={urllib.parse.quote(ticker)}"
        f"&from={since}&to={today}"
        f"&token={urllib.parse.quote(FINNHUB_API_KEY)}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[news] finnhub failed for {ticker}: {e}")
        return []

    out: list[dict] = []
    for a in (data or [])[:max_items]:
        u = a.get("url") or ""
        title = a.get("headline") or ""
        if not (u and title):
            continue
        ts = a.get("datetime")
        published = (
            datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if isinstance(ts, (int, float)) else None
        )
        out.append({
            "src": "finnhub",
            "title": title,
            "url": u,
            "publisher": a.get("source") or "",
            "published": published,
            "blurb": (a.get("summary") or "").strip(),
            "image": a.get("image") or None,
            "content_type": "STORY",
            "ticker": ticker,
        })
    return out


# ─────────────────────────── merge / dedupe / filter ──────────────────────

def _canonical_key(url: str) -> str:
    """Stable dedupe key. For redirector URLs (Finnhub etc.) we keep the
    full URL including the query string — different `id=` params point at
    different articles. For everything else we drop query/fragment so
    that tracking params don't fragment the cache."""
    try:
        p = urllib.parse.urlparse(url)
        host = p.netloc.lower()
        if host == FINNHUB_REDIRECT_HOST or host.endswith("." + FINNHUB_REDIRECT_HOST):
            return url
        return f"{host}{p.path.rstrip('/')}"
    except Exception:
        return url


def merge_dedupe(*lists: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for items in lists:
        for it in items:
            k = _canonical_key(it["url"])
            if k in seen:
                # Prefer entries that have an image / longer blurb
                cur = seen[k]
                if (it.get("image") and not cur.get("image")) or \
                   len(it.get("blurb") or "") > len(cur.get("blurb") or ""):
                    cur.update({k2: v for k2, v in it.items() if v})
                continue
            seen[k] = dict(it)
    return list(seen.values())


def is_on_topic(article: dict, ticker: str, company_name: str | None) -> bool:
    """Article must mention the ticker symbol or the company name somewhere
    in title/blurb/body. Blocks the ~23% of returned items that name the
    ticker only in a 'related symbols' list."""
    parts = [article.get("title", ""), article.get("blurb", ""), article.get("body", "")]
    text = " ".join(parts).lower()
    if not text.strip():
        return False
    if re.search(rf"\b{re.escape(ticker.lower())}\b", text):
        return True
    if company_name:
        # Match the head word of a multi-word name too (e.g. "JPMorgan" for
        # "JPMorgan Chase & Co"). Cheap and effective.
        head = company_name.split()[0].lower()
        if len(head) >= 4 and head in text:
            return True
        if company_name.lower() in text:
            return True
    return False


# ─────────────────────────── redirect resolution ──────────────────────────

def _resolve_one(article: dict) -> dict:
    """HEAD/GET-light to capture the post-redirect URL for a Finnhub link."""
    if FINNHUB_REDIRECT_HOST not in (article.get("url") or ""):
        return article
    try:
        req = urllib.request.Request(
            article["url"], headers={"User-Agent": UA}, method="HEAD"
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            article = {**article, "url": resp.url}
    except Exception:
        # HEAD often blocked; fall back to a tiny GET that we close right away.
        try:
            req = urllib.request.Request(article["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                article = {**article, "url": resp.url}
        except Exception:
            pass
    return article


def resolve_redirects(articles: list[dict]) -> list[dict]:
    """Mutates URLs to their canonical destination for Finnhub-redirect items."""
    needs = [i for i, a in enumerate(articles)
             if FINNHUB_REDIRECT_HOST in (a.get("url") or "")]
    if not needs:
        return articles
    with ThreadPoolExecutor(max_workers=PARALLEL_REDIRECT_WORKERS) as ex:
        futures = {ex.submit(_resolve_one, articles[i]): i for i in needs}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                articles[i] = fut.result()
            except Exception:
                pass
    return articles


# ─────────────────────────── body fetch + cache ───────────────────────────

def _host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower().lstrip("www.").replace("www.", "")
    except Exception:
        return ""


def _is_blacklisted(url: str) -> bool:
    h = _host_of(url)
    return any(h == d or h.endswith("." + d) for d in BLACKLIST_HOSTS)


def _fetch_body_uncached(url: str) -> tuple[str, str | None]:
    """Returns (status, body_or_None). status ∈ {ok, too_short, no_extract,
    http_4xx, http_5xx, error, blacklisted, video}."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            html = resp.read(2_000_000).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return (f"http_{e.code}", None)
    except Exception as e:
        return (type(e).__name__.lower(), None)

    body = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    )
    if not body:
        return ("no_extract", None)
    if len(body) < BODY_MIN_CHARS:
        return ("too_short", body)
    if len(body) > BODY_MAX_CHARS:
        body = body[:BODY_MAX_CHARS]
    return ("ok", body)


def _cache_get_bodies(conn, urls: list[str]) -> dict[str, tuple[str, str | None]]:
    if not urls:
        return {}
    cutoff = datetime.now(tz=timezone.utc) - ARTICLE_BODY_CACHE_TTL
    with conn.cursor() as cur:
        cur.execute(
            "SELECT url, status, body FROM article_bodies "
            "WHERE url = ANY(%s) AND fetched_at >= %s",
            (urls, cutoff),
        )
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def _cache_put_bodies(conn, rows: list[tuple[str, str, str | None]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO article_bodies (url, status, body, fetched_at)
            VALUES %s
            ON CONFLICT (url) DO UPDATE
               SET status = EXCLUDED.status,
                   body = EXCLUDED.body,
                   fetched_at = EXCLUDED.fetched_at
            """,
            [(u, s, b, datetime.now(tz=timezone.utc)) for u, s, b in rows],
        )
    conn.commit()


def fetch_bodies(conn, articles: list[dict]) -> list[dict]:
    """Annotate each article with `body` (str or '') and `body_status`.
    Skips blacklist + video; checks article_bodies cache; parallel fetches
    everything else; writes results back to cache."""
    # Decide skip reasons up-front
    skip_reason: dict[int, str] = {}
    for i, a in enumerate(articles):
        if (a.get("content_type") or "").upper() == "VIDEO":
            skip_reason[i] = "video"
        elif _is_blacklisted(a.get("url", "")):
            skip_reason[i] = "blacklisted"

    # Cache lookup for the rest
    fetch_idx = [i for i in range(len(articles)) if i not in skip_reason]
    fetch_urls = [articles[i]["url"] for i in fetch_idx]
    cached = _cache_get_bodies(conn, fetch_urls)

    to_fetch_idx = [i for i in fetch_idx
                    if articles[i]["url"] not in cached]
    new_rows: list[tuple[str, str, str | None]] = []

    if to_fetch_idx:
        with ThreadPoolExecutor(max_workers=PARALLEL_BODY_WORKERS) as ex:
            futures = {ex.submit(_fetch_body_uncached, articles[i]["url"]): i
                       for i in to_fetch_idx}
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    status, body = fut.result()
                except Exception as e:
                    status, body = (type(e).__name__.lower(), None)
                articles[i]["body_status"] = status
                articles[i]["body"] = body or ""
                new_rows.append((articles[i]["url"], status, body))

    # Cache hits
    for i in fetch_idx:
        if i in to_fetch_idx:
            continue
        status, body = cached[articles[i]["url"]]
        articles[i]["body_status"] = status
        articles[i]["body"] = body or ""

    # Skipped
    for i, reason in skip_reason.items():
        articles[i]["body_status"] = reason
        articles[i]["body"] = ""

    _cache_put_bodies(conn, new_rows)
    return articles


# ─────────────────────────── ranking ──────────────────────────────────────

# Source trust, copied/adapted from ai/pipeline/news_scraper.py.
SOURCE_TRUST = {
    "Reuters": 1.25, "Bloomberg": 1.20, "The Wall Street Journal": 1.15,
    "Financial Times": 1.15, "CNBC": 1.10, "Barrons.com": 1.10,
    "MarketWatch": 1.05, "Investor's Business Daily": 1.05,
    "Yahoo Finance": 1.00, "Yahoo": 1.00, "Yahoo Finance Video": 0.95,
    "Motley Fool": 0.90, "Benzinga": 0.85, "Insider Monkey": 0.80,
    "Simply Wall St.": 0.80, "Zacks": 0.85, "TheStreet": 0.85,
    "24/7 Wall St.": 0.70, "SeekingAlpha": 0.85, "Finnhub": 0.80,
}


def _published_dt(s: Any) -> datetime | None:
    if not s:
        return None
    if isinstance(s, (int, float)):
        try:
            return datetime.fromtimestamp(s, tz=timezone.utc)
        except Exception:
            return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _score(a: dict) -> float:
    pub = a.get("publisher") or ""
    trust = SOURCE_TRUST.get(pub, 0.85)

    # Freshness — exponential decay with 3-day half-life
    dt = _published_dt(a.get("published"))
    if dt is None:
        fresh = 0.5
    else:
        hours = max(0, (datetime.now(tz=timezone.utc) - dt).total_seconds() / 3600)
        fresh = 0.5 ** (hours / 72)

    # Did body fetch succeed?
    body_bonus = 0.20 if a.get("body_status") == "ok" else 0.0

    # Title mention is a stronger on-topic signal than body mention
    title = (a.get("title") or "").lower()
    tk = (a.get("ticker") or "").lower()
    title_bonus = 0.15 if tk and re.search(rf"\b{re.escape(tk)}\b", title) else 0.0

    return 0.45 * trust + 0.30 * fresh + body_bonus + title_bonus


def rank_articles(articles: list[dict], top_k: int) -> list[dict]:
    return sorted(articles, key=_score, reverse=True)[:top_k]


# ─────────────────────────── public entrypoint ────────────────────────────

def get_articles_for_ticker(
    conn,
    ticker: str,
    company_name: str | None = None,
    top_k: int = 12,
) -> list[dict]:
    """End-to-end: pull from sources, dedupe, on-topic filter, resolve
    redirects, body fetch, score & truncate. Returns the final article list
    that gets sent to Claude."""
    t0 = time.perf_counter()
    yf_items = fetch_yfinance(ticker)
    fh_items = fetch_finnhub(ticker)

    merged = merge_dedupe(yf_items, fh_items)

    # On-topic filter using API-level fields (title+blurb).
    # Body mention will reinforce in the post-fetch pass below.
    pre = [a for a in merged if is_on_topic(a, ticker, company_name)]
    # Don't strand ourselves with zero articles if the filter was too harsh.
    if not pre and merged:
        pre = merged

    pre = resolve_redirects(pre)
    # Re-dedupe after resolution: yfinance + Finnhub often point at the same
    # finance.yahoo.com canonical URL.
    pre = merge_dedupe(pre)

    pre = fetch_bodies(conn, pre)

    # Drop articles with neither a usable body nor a meaningful blurb,
    # and re-check on-topic now that body text is available. Also drop
    # anything still pointing at finnhub.io — that means redirect
    # resolution failed and the public-facing link would 404 / be a
    # generic landing page.
    final = []
    for a in pre:
        host = urllib.parse.urlparse(a.get("url") or "").netloc.lower()
        if host == FINNHUB_REDIRECT_HOST or host.endswith("." + FINNHUB_REDIRECT_HOST):
            continue
        has_body = a.get("body_status") == "ok"
        has_blurb = len(a.get("blurb") or "") >= 60
        if not (has_body or has_blurb):
            continue
        if not is_on_topic(a, ticker, company_name):
            continue
        final.append(a)

    final = rank_articles(final, top_k=top_k)

    elapsed = (time.perf_counter() - t0) * 1000
    body_ok = sum(1 for a in final if a.get("body_status") == "ok")
    print(f"[news] {ticker}: yf={len(yf_items)} fh={len(fh_items)} "
          f"merged={len(merged)} kept={len(final)} body_ok={body_ok}/{len(final)} "
          f"({elapsed:.0f}ms)")
    return final


def articles_hash(articles: list[dict]) -> str:
    """Content-addressable cache key: changes iff the URL set changes.
    This is what powers the 'don't regenerate if news hasn't changed' logic."""
    import hashlib
    keys = sorted(_canonical_key(a["url"]) for a in articles)
    return hashlib.sha256("|".join(keys).encode()).hexdigest()[:16]

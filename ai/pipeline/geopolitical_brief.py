"""
USE THIS RUN STATEMENT TO RUN THE SCRIPT:
python3 geopolitical_brief.py --score-weight-momentum 0.7
--score-weight-liquidity 0.3 --score-weight-cooccurrence 0.25


IF THERE IS AN ERROR TRY
python3 geopolitical_brief.py --skip-install --all-tracks
--export-news-edges --score-weight-momentum 0.7
--score-weight-liquidity 0.3 --score-weight-cooccurrence 0.25
"""


from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(dt: datetime | None = None) -> str:
    when = dt or _utc_now()
    return when.isoformat().replace("+00:00", "Z")


def resolve_repo_root() -> Path:
    # Prefer the nearest pyproject.toml, but gracefully fall back so importing this
    # module for tests still works in lightweight environments.
    start_points = [Path.cwd().resolve(), Path(__file__).resolve().parent]
    seen: set[Path] = set()
    for start in start_points:
        cur = start
        while cur not in seen:
            seen.add(cur)
            if (cur / "pyproject.toml").is_file():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
    return Path(__file__).resolve().parent.parent


NEXUS_ROOT = resolve_repo_root()
SRC_DIR = NEXUS_ROOT / "src"
if SRC_DIR.is_dir():
    sys.path.insert(0, str(SRC_DIR))


def install_runtime_deps() -> None:
    for req in [NEXUS_ROOT / "requirements.txt", NEXUS_ROOT / "requirements-notebooks.txt"]:
        if req.is_file():
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
                cwd=NEXUS_ROOT,
            )
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "google-genai",
            "scikit-learn",
            "python-dotenv",
            "requests",
            "feedparser",
        ]
    )


def _clean_heading(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _slugify_track(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return re.sub(r"_+", "_", s)


def _title_track_from_slug(track_id: str) -> str:
    return track_id.replace("_", " ").strip().title()


def normalize_pair(a: str, b: str) -> tuple[str, str]:
    sa, sb = (a or "").upper().strip(), (b or "").upper().strip()
    return (sa, sb) if sa <= sb else (sb, sa)


def calc_link_confidence(headlines_shared: int, source_count: int) -> float:
    # Heuristic confidence from evidence density; deterministic and bounded.
    h = min(1.0, headlines_shared / 4.0)
    s = min(1.0, source_count / 6.0)
    return round((0.6 * h) + (0.4 * s), 4)


# Track / ticker defaults
TRACK_ID = "fertilizer"
TICKER = "MOS"
MIN_HITS = 6
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


RSS_FALLBACKS = [
    ("rss_reuters_business", "https://feeds.reuters.com/reuters/businessNews"),
    ("rss_reuters_world", "https://feeds.reuters.com/reuters/worldNews"),
    ("rss_reuters_energy", "https://feeds.reuters.com/reuters/energy"),
    ("rss_cnbc_markets", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("rss_cnbc_investing", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135"),
    ("rss_marketwatch_top", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("rss_wsj_markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("rss_bbc_business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("rss_bbc_world", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("rss_bbc_middle_east", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
    ("rss_aljazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("rss_middle_east_eye", "https://www.middleeasteye.net/rss"),
    ("rss_times_of_israel", "https://www.timesofisrael.com/feed/"),
    ("rss_eia", "https://www.eia.gov/rss/todayinenergy.xml"),
    ("rss_oilprice", "https://oilprice.com/rss/main"),
    ("rss_rigzone", "https://www.rigzone.com/news/rss/rigzone_latest.aspx"),
    ("rss_usda", "https://www.usda.gov/rss/latest-releases.xml"),
    ("rss_guardian_farming", "https://www.theguardian.com/environment/farming/rss"),
    ("rss_google_ag", "https://news.google.com/rss/search?q=agriculture+farming+commodities&hl=en-US&gl=US&ceid=US:en"),
    ("rss_google_oil", "https://news.google.com/rss/search?q=oil+crude+gas+OPEC+price&hl=en-US&gl=US&ceid=US:en"),
    ("rss_google_iran", "https://news.google.com/rss/search?q=Iran+war+sanctions+Strait+Hormuz&hl=en-US&gl=US&ceid=US:en"),
    ("rss_google_ticker", f"https://news.google.com/rss/search?q={TICKER}+stock&hl=en-US&gl=US&ceid=US:en"),
]

YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"

INLINE_TRACKS = {
    "Big Tech AI Infrastructure": ["NVDA", "MSFT", "GOOGL", "AMZN", "META"],
    "Semiconductor Manufacturing & Equipment": ["ASML", "AMAT", "LRCX", "KLAC", "TSMC"],
    "Digital Payments & Fintech": ["V", "MA", "PYPL", "FI", "GPN"],
    "Cybersecurity SaaS": ["PANW", "FTNT", "CRWD", "OKTA", "ZS"],
    "Fertilizer": ["NTR", "CF", "ICL", "MOS", "YARIY"],
    "Energy & Geopolitical": ["XOM", "CVX", "OXY", "BP", "SHEL", "COP", "SLB", "HAL", "PSX", "VLO"],
}

ENERGY_EXTRA_TERMS = [
    "iran",
    "tehran",
    "hormuz",
    "strait",
    "sanctions",
    "irgc",
    "nuclear",
    "middle east",
    "persian gulf",
    "israel",
    "hamas",
    "hezbollah",
    "conflict",
    "proxy",
    "drone",
    "missile",
    "ceasefire",
    "oil",
    "crude",
    "brent",
    "wti",
    "natural gas",
    "lng",
    "opec",
    "opec+",
    "barrel",
    "refinery",
    "pipeline",
    "tanker",
    "energy",
    "petrol",
    "gasoline",
    "downstream",
    "upstream",
    "rig",
    "shale",
    "fertilizer",
    "urea",
    "ammonia",
    "potash",
]


@dataclass
class BriefRow:
    headline: str
    url: str | None
    source_id: str
    collected_at_ts: float


def norm_key(headline: str) -> str:
    return re.sub(r"\s+", " ", headline.strip().lower()[:220])


def row_matches(headline: str, terms: frozenset[str]) -> bool:
    h = headline.lower()
    return any(t and t in h for t in terms)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _normalize_nonnegative_weights(weights: list[float], fallback: list[float]) -> list[float]:
    clean = [max(0.0, float(w)) for w in weights]
    total = sum(clean)
    if total <= 0:
        fallback_total = sum(max(0.0, float(w)) for w in fallback)
        if fallback_total <= 0:
            return [1.0 / len(weights)] * len(weights)
        return [max(0.0, float(w)) / fallback_total for w in fallback]
    return [w / total for w in clean]


def _token_aliases(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z]{3,}", text or "")]


def build_alias_map(track_companies: list[dict[str, Any]], nodes_by_ticker: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for c in track_companies:
        ticker = str(c.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        pool: set[str] = {ticker.lower()}
        for token in _token_aliases(str(c.get("name", ""))):
            pool.add(token)
        node = nodes_by_ticker.get(ticker, {})
        for token in _token_aliases(str(node.get("name", ""))):
            pool.add(token)
        for alias in node.get("aliases", []) if isinstance(node.get("aliases"), list) else []:
            for token in _token_aliases(str(alias)):
                pool.add(token)
        aliases[ticker] = {x for x in pool if x not in {"company", "global", "corporation", "holdings", "group", "limited", "inc"}}
    return aliases


def company_mentioned(headline: str, ticker: str, alias_tokens: set[str]) -> bool:
    t = (ticker or "").strip().upper()
    if not t:
        return False
    if len(t) <= 2 and re.search(rf"\b{re.escape(t)}\b", headline):
        return True
    if len(t) > 2 and re.search(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![A-Za-z0-9])", headline, re.IGNORECASE):
        return True
    low = headline.lower()
    return any(tok in low for tok in alias_tokens if len(tok) >= 3)


def compute_ticker_signal_scores(
    collected: list[BriefRow],
    tickers: list[str],
    alias_map: dict[str, set[str]],
    *,
    score_weight_momentum: float,
    score_weight_liquidity: float,
) -> dict[str, dict[str, Any]]:
    """
    Post-processing signal layer:
    - momentum_score: recent mention-rate vs prior mention-rate
    - liquidity_proxy: source/url breadth + recency concentration
    - combined_score: blend for downstream ranking
    """
    n = len(collected)
    if n == 0:
        return {
            t: {
                "momentum_score": 0.0,
                "liquidity_proxy": 0.0,
                "combined_score": 0.0,
                "mentions_total": 0,
                "mentions_recent": 0,
                "unique_sources": 0,
            }
            for t in tickers
        }

    short_n = max(3, n // 3)
    prior_n = max(1, n - short_n)
    recent_rows = collected[-short_n:]
    all_source_count = max(1, len({r.source_id for r in collected}))

    wm, wl = _normalize_nonnegative_weights(
        [score_weight_momentum, score_weight_liquidity],
        [0.55, 0.45],
    )

    scores: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        alias_tokens = alias_map.get(ticker, {ticker.lower()})
        matches = [r for r in collected if company_mentioned(r.headline, ticker, alias_tokens)]
        recent_matches = [r for r in recent_rows if company_mentioned(r.headline, ticker, alias_tokens)]
        mentions_total = len(matches)
        mentions_recent = len(recent_matches)
        mentions_prior = max(0, mentions_total - mentions_recent)

        rate_recent = mentions_recent / short_n
        rate_prior = mentions_prior / prior_n
        # Center at 0.5; positive drift in recent mentions pushes toward 1.0.
        momentum_score = _clamp01(0.5 + ((rate_recent - rate_prior) * 2.0))

        unique_sources = len({r.source_id for r in matches})
        source_breadth = unique_sources / all_source_count
        url_ratio = (sum(1 for r in matches if r.url and r.url.startswith("http")) / max(1, mentions_total))
        recency_focus = mentions_recent / max(1, mentions_total)
        liquidity_proxy = _clamp01((0.6 * source_breadth) + (0.2 * url_ratio) + (0.2 * recency_focus))

        combined_score = _clamp01((wm * momentum_score) + (wl * liquidity_proxy))
        scores[ticker] = {
            "momentum_score": round(momentum_score, 4),
            "liquidity_proxy": round(liquidity_proxy, 4),
            "combined_score": round(combined_score, 4),
            "mentions_total": mentions_total,
            "mentions_recent": mentions_recent,
            "unique_sources": unique_sources,
        }

    return scores


def build_summarizer(api_key: str):
    from sklearn.feature_extraction.text import TfidfVectorizer

    try:
        from google import genai as _genai

        genai_available = True
    except ImportError:
        _genai = None
        genai_available = False

    class NewsSummarizer:
        def __init__(self, key: str | None = None):
            k = key or os.environ.get("GEMINI_API_KEY", "")
            self.client = _genai.Client(api_key=k) if (genai_available and k) else None

        def extract_keywords(self, text: str, top_n: int = 8) -> list[str]:
            if not text or not text.strip():
                return []
            cleaned = re.sub(r"[^a-zA-Z\s]", "", text).lower()
            try:
                vec = TfidfVectorizer(stop_words="english")
                matrix = vec.fit_transform([cleaned])
                names = vec.get_feature_names_out()
                scores = list(zip(range(len(names)), matrix.toarray().tolist()[0]))
                top = sorted([(names[i], s) for i, s in scores if s > 0], key=lambda x: -x[1])
                return [w for w, _ in top[:top_n]]
            except ValueError:
                return []

        def extract_context(self, text: str, keywords: list[str]) -> str:
            if not text:
                return ""
            sentences = re.split(r"(?<=[.!?]) +", text)
            hits = [s.strip() for s in sentences if any(kw in s.lower() for kw in keywords)]
            return " ".join(hits[:10])

        def generate_summary(self, context: str, label: str) -> str:
            if not self.client:
                return "No API key configured - mock sentence 1. Mock sentence 2."
            if not context:
                return "No relevant news context found. Unable to generate summary."
            prompt = (
                f"You are a financial analyst. Read the following recent news context for '{label}'. "
                f"Write exactly two sentences summarizing this news. Do not use conversational filler.\n\n"
                f"Context:\n{context}"
            )
            try:
                resp = self.client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
                return resp.text.strip().replace("\n", " ")
            except Exception as e:
                print(f"Error generating summary for {label}: {e}")
                return "Error generating summary. Please check API key."

        def summarize_ticker(self, headlines: list[str], ticker: str) -> str:
            combined = " ".join(headlines)
            keywords = self.extract_keywords(combined, top_n=8)
            context = self.extract_context(combined, keywords)
            return self.generate_summary(context, ticker)

    return NewsSummarizer(api_key)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate geopolitical brief artifacts from RSS + summarization.",
        epilog=(
            "First-time quick start:\n"
            "  python Experiments/geopolitical_brief.py --track fertilizer\n"
            "  python Experiments/geopolitical_brief.py --all-tracks --export-news-edges\n"
        ),
    )
    parser.add_argument("--track", default=TRACK_ID, help="Track id or normalized track label slug")
    parser.add_argument("--ticker", default=None, help="Primary ticker override for ticker-based feeds")
    parser.add_argument("--min-hits", type=int, default=MIN_HITS, help="Minimum matched headline target")
    parser.add_argument("--all-tracks", action="store_true", help="Generate briefs for all available tracks")
    parser.add_argument("--skip-install", action="store_true", help="Skip pip installation step")
    parser.add_argument(
        "--include-energy-terms",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include ENERGY_EXTRA_TERMS in keyword matching",
    )
    parser.add_argument("--cache-ttl-hours", type=float, default=24.0, help="RSS cache TTL in hours")
    parser.add_argument(
        "--export-news-edges",
        nargs="?",
        const="auto",
        default=None,
        help="Write Task6b-style news_cooccurrence edges JSON (optional path; default auto)",
    )
    parser.add_argument(
        "--score-weight-momentum",
        type=float,
        default=0.55,
        help="Weight for ticker momentum_score in combined ticker signal score",
    )
    parser.add_argument(
        "--score-weight-liquidity",
        type=float,
        default=0.45,
        help="Weight for ticker liquidity_proxy in combined ticker signal score",
    )
    parser.add_argument(
        "--score-weight-cooccurrence",
        type=float,
        default=0.4,
        help="Weight for headlines_shared in final link ranking_score (remaining weight uses momentum-liquidity confidence)",
    )
    return parser.parse_args()


def load_json_or_default(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_track_sources(
    selected_track_id: str,
) -> tuple[dict[str, Any] | None, dict[str, list[str]], list[dict[str, Any]]]:
    tracks_path = NEXUS_ROOT / "config" / "investment_tracks.json"
    exp_tracks_path = NEXUS_ROOT / "Experiments" / "investment_tracks.json"
    ticker_track_path = NEXUS_ROOT / "Experiments" / "ticker_track.json"

    tracks_doc = None
    for p in [tracks_path, exp_tracks_path]:
        if p.is_file():
            doc = load_json_or_default(p, {})
            if isinstance(doc, dict) and isinstance(doc.get("tracks"), list):
                tracks_doc = doc
                break

    ticker_grouped: dict[str, list[str]] = {}
    if ticker_track_path.is_file():
        ticker_track_map = load_json_or_default(ticker_track_path, {})
        if isinstance(ticker_track_map, dict):
            for ticker, label in ticker_track_map.items():
                t = str(ticker).strip().upper()
                lbl = str(label).strip()
                if t and lbl:
                    ticker_grouped.setdefault(lbl, []).append(t)

    all_tracks: list[dict[str, Any]] = []
    if tracks_doc:
        all_tracks.extend(tracks_doc["tracks"])
    elif ticker_grouped:
        for label, tickers in sorted(ticker_grouped.items()):
            all_tracks.append(
                {
                    "track_id": _slugify_track(label),
                    "label": label,
                    "keywords": [],
                    "companies": [{"ticker": t, "name": "", "size_tier": None} for t in sorted(set(tickers))],
                }
            )
    else:
        for label, tickers in INLINE_TRACKS.items():
            all_tracks.append(
                {
                    "track_id": _slugify_track(label),
                    "label": label,
                    "keywords": [],
                    "companies": [{"ticker": t, "name": "", "size_tier": None} for t in tickers],
                }
            )

    selected_track = None
    for t in all_tracks:
        if t.get("track_id") == selected_track_id:
            selected_track = t
            break
        if str(t.get("label", "")).lower() == selected_track_id.lower():
            selected_track = t
            break
        if _slugify_track(str(t.get("label", ""))) == _slugify_track(selected_track_id):
            selected_track = t
            break

    if selected_track is None:
        label = _title_track_from_slug(selected_track_id)
        tickers = INLINE_TRACKS.get(label) or INLINE_TRACKS.get("Fertilizer", [])
        selected_track = {
            "track_id": selected_track_id,
            "label": label,
            "keywords": [],
            "companies": [{"ticker": t, "name": "", "size_tier": None} for t in tickers],
        }
    return selected_track, ticker_grouped, all_tracks


def load_nodes_index() -> dict[str, dict[str, Any]]:
    paths = [
        NEXUS_ROOT / "scraper" / "data" / "processed" / "nodes.json",
        NEXUS_ROOT / "ai" / "tests" / "mock_nodes.json",
    ]
    for p in paths:
        if not p.is_file():
            continue
        data = load_json_or_default(p, [])
        if isinstance(data, list):
            idx: dict[str, dict[str, Any]] = {}
            for row in data:
                if isinstance(row, dict):
                    t = str(row.get("ticker") or row.get("id") or "").upper().strip()
                    if t:
                        idx[t] = row
            if idx:
                return idx
    return {}


def _cache_key(feed: str, source_id: str) -> str:
    return hashlib.sha1(f"{source_id}|{feed}".encode("utf-8")).hexdigest()[:16]


def load_env_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        # dotenv is optional for first-time runs; env vars still work if exported.
        pass


def get_rss_fetcher():
    """
    Returns a callable compatible with:
      fetch(feed: str, source_tag: str, timeout: float) -> list[dict]

    Prefers nexus.ingest.rss.fetch_rss_as_news_items when available, and falls back
    to a local requests+feedparser implementation for first-time users testing this
    script outside the full Nexus package layout.
    """
    try:
        from nexus.ingest.rss import fetch_rss_as_news_items as nexus_fetch  # type: ignore

        return nexus_fetch, "nexus.ingest.rss"
    except Exception:
        pass

    try:
        import feedparser  # type: ignore
        import requests  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "RSS dependencies unavailable. Install with:\n"
            f"  {sys.executable} -m pip install requests feedparser\n"
            "or run this script without --skip-install."
        ) from e

    def _fallback_fetch(feed: str, source_tag: str, timeout: float = 25.0) -> list[dict[str, Any]]:
        headers = {"User-Agent": "geopolitical-brief/1.0 (+rss fallback)"}
        resp = requests.get(feed, timeout=timeout, headers=headers)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        items: list[dict[str, Any]] = []
        for entry in parsed.entries:
            headline = _clean_heading(str(entry.get("title", "")).strip())
            if not headline:
                continue
            url = str(entry.get("link", "")).strip() or None
            items.append({"headline": headline, "url": url, "source_tag": source_tag})
        return items

    return _fallback_fetch, "requests+feedparser"


def load_health(cache_dir: Path) -> dict[str, Any]:
    return load_json_or_default(cache_dir / "source_health.json", {})


def save_health(cache_dir: Path, health: dict[str, Any]) -> None:
    (cache_dir / "source_health.json").write_text(json.dumps(health, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def source_priority_key(source_id: str, health: dict[str, Any]) -> tuple[int, int]:
    record = health.get(source_id, {}) if isinstance(health.get(source_id), dict) else {}
    failures = int(record.get("consecutive_failures", 0))
    cooldown = 1 if failures >= 3 else 0
    return (cooldown, failures)


def fetch_items_with_cache(
    fetch_func,
    feed: str,
    source_id: str,
    cache_dir: Path,
    ttl_seconds: float,
    health: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(feed, source_id)
    cache_path = cache_dir / f"rss_{key}.json"
    now_ts = time.time()

    if cache_path.is_file():
        cached = load_json_or_default(cache_path, {})
        if isinstance(cached, dict) and (now_ts - float(cached.get("fetched_at_ts", 0.0)) <= ttl_seconds):
            items = cached.get("items", [])
            if isinstance(items, list):
                return items, {
                    "source_id": source_id,
                    "feed": feed,
                    "cached": True,
                    "ok": True,
                    "error": None,
                    "fetch_latency_ms": 0,
                    "item_count": len(items),
                }

    t0 = time.perf_counter()
    try:
        items = fetch_func(feed, source_tag=source_id, timeout=25.0)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        cache_path.write_text(
            json.dumps({"fetched_at_ts": now_ts, "items": items}, ensure_ascii=False),
            encoding="utf-8",
        )
        rec = health.get(source_id, {}) if isinstance(health.get(source_id), dict) else {}
        rec["consecutive_failures"] = 0
        rec["last_success_at"] = _iso_utc()
        health[source_id] = rec
        return items if isinstance(items, list) else [], {
            "source_id": source_id,
            "feed": feed,
            "cached": False,
            "ok": True,
            "error": None,
            "fetch_latency_ms": latency_ms,
            "item_count": len(items) if isinstance(items, list) else 0,
        }
    except Exception as e:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        rec = health.get(source_id, {}) if isinstance(health.get(source_id), dict) else {}
        rec["consecutive_failures"] = int(rec.get("consecutive_failures", 0)) + 1
        rec["last_failure_at"] = _iso_utc()
        rec["last_error"] = str(e)
        health[source_id] = rec
        return [], {
            "source_id": source_id,
            "feed": feed,
            "cached": False,
            "ok": False,
            "error": str(e),
            "fetch_latency_ms": latency_ms,
            "item_count": 0,
        }


def build_news_edges(brief_json: dict[str, Any], valid_tickers: set[str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    links = brief_json.get("links", [])
    if not isinstance(links, list):
        return edges
    max_shared = 1
    for link in links:
        if isinstance(link, dict):
            max_shared = max(max_shared, int(link.get("headlines_shared", 0) or 0))

    seen: set[tuple[str, str]] = set()
    for link in links:
        if not isinstance(link, dict):
            continue
        pair = str(link.get("pair", ""))
        if " - " not in pair:
            continue
        a, b = pair.split(" - ", 1)
        src, dst = normalize_pair(a, b)
        if not src or not dst or src == dst:
            continue
        if valid_tickers and (src not in valid_tickers or dst not in valid_tickers):
            continue
        if (src, dst) in seen:
            continue
        seen.add((src, dst))
        shared = int(link.get("headlines_shared", 0) or 0)
        edges.append(
            {
                "source_id": src,
                "target_id": dst,
                "relationship_type": "news_cooccurrence",
                "weight": round(shared / max_shared, 4),
                "metadata": {
                    "headlines_shared": shared,
                    "sources": link.get("sources", []) if isinstance(link.get("sources"), list) else [],
                    "brief_track": brief_json.get("track_name", ""),
                    "brief_track_id": brief_json.get("track_id", ""),
                    "ranking_score": float(link.get("ranking_score", 0.0)),
                    "momentum_liquidity_confidence": float(link.get("momentum_liquidity_confidence", 0.0)),
                },
            }
        )
    return edges


def run_track(
    *,
    track: dict[str, Any],
    ticker_for_run: str,
    min_hits: int,
    include_energy_terms: bool,
    summarizer,
    fetch_func,
    nodes_index: dict[str, dict[str, Any]],
    cache_dir: Path,
    cache_ttl_seconds: float,
    health: dict[str, Any],
    run_id: str,
    score_weight_momentum: float,
    score_weight_liquidity: float,
    score_weight_cooccurrence: float,
) -> dict[str, Any]:
    rss_fallbacks = list(RSS_FALLBACKS)
    rss_fallbacks[-1] = (
        "rss_google_ticker",
        f"https://news.google.com/rss/search?q={ticker_for_run}+stock&hl=en-US&gl=US&ceid=US:en",
    )
    rss_fallbacks = sorted(rss_fallbacks, key=lambda s: source_priority_key(s[0], health))

    kws = [str(k).strip().lower() for k in (track.get("keywords") or []) if str(k).strip()]
    extra = [
        "monsanto",
        "bayer",
        "roundup",
        "glyphosate",
        "gmo",
        "seed",
        "seeds",
        "farm",
        "farming",
        "food",
        "crop",
        "commodities",
        "commodity",
        ticker_for_run.lower(),
    ]
    if include_energy_terms:
        extra += ENERGY_EXTRA_TERMS
    terms = frozenset(kws + extra)

    print("Track:", track["label"], "[", track["track_id"], "]")
    print("Companies:", ", ".join(f"{c['ticker']}:{c.get('name','')}" for c in track["companies"]))
    print("Term count:", len(terms))

    collected: list[BriefRow] = []
    seen: set[str] = set()
    counts: dict[str, int] = {}
    source_attempts: list[dict[str, Any]] = []

    for sid, feed in rss_fallbacks:
        if len(collected) >= min_hits:
            counts.setdefault(sid, 0)
            continue
        before = len(collected)
        items, meta = fetch_items_with_cache(
            fetch_func=fetch_func,
            feed=feed,
            source_id=sid,
            cache_dir=cache_dir,
            ttl_seconds=cache_ttl_seconds,
            health=health,
        )
        source_attempts.append(meta)
        for it in items:
            if not isinstance(it, dict):
                continue
            head = _clean_heading((it.get("headline") or "").strip())
            if len(head) < 12:
                continue
            nk = norm_key(head)
            if nk in seen or not row_matches(head, terms):
                continue
            seen.add(nk)
            u = it.get("url")
            collected.append(
                BriefRow(
                    headline=head,
                    url=u if isinstance(u, str) else None,
                    source_id=sid,
                    collected_at_ts=time.time(),
                )
            )
        counts[sid] = len(collected) - before
        print(f"{sid}: +{counts[sid]} (total {len(collected)})")

    yid = f"rss_yahoo_{ticker_for_run}"
    if len(collected) < min_hits:
        before = len(collected)
        items, meta = fetch_items_with_cache(
            fetch_func=fetch_func,
            feed=YAHOO_RSS.format(sym=ticker_for_run),
            source_id=yid,
            cache_dir=cache_dir,
            ttl_seconds=cache_ttl_seconds,
            health=health,
        )
        source_attempts.append(meta)
        for it in items:
            if not isinstance(it, dict):
                continue
            head = _clean_heading((it.get("headline") or "").strip())
            if len(head) < 8:
                continue
            nk = norm_key(head)
            if nk in seen:
                continue
            seen.add(nk)
            u = it.get("url")
            collected.append(
                BriefRow(
                    headline=head,
                    url=u if isinstance(u, str) else None,
                    source_id=yid,
                    collected_at_ts=time.time(),
                )
            )
        counts[yid] = len(collected) - before
        print(f"{yid}: +{counts[yid]} (total {len(collected)})")

    alias_map = build_alias_map(track["companies"], nodes_index)

    tracked_tickers = [str(c.get("ticker", "")).upper() for c in track["companies"] if c.get("ticker")]
    ticker_signal_scores = compute_ticker_signal_scores(
        collected,
        tracked_tickers,
        alias_map,
        score_weight_momentum=score_weight_momentum,
        score_weight_liquidity=score_weight_liquidity,
    )

    ticker_summaries: list[dict[str, Any]] = []
    for company in track["companies"]:
        ticker = str(company.get("ticker", "")).upper()
        if not ticker:
            continue
        alias_tokens = alias_map.get(ticker, {ticker.lower()})
        company_heads = [r.headline for r in collected if company_mentioned(r.headline, ticker, alias_tokens)]
        if not company_heads:
            continue
        summary = summarizer.summarize_ticker(company_heads, ticker)
        ticker_summaries.append(
            {
                "label": ticker,
                "name": company.get("name", ""),
                "track": track["label"],
                "accessed_at": _iso_utc(),
                "summary": summary,
                "signal_scores": ticker_signal_scores.get(ticker, {}),
            }
        )

    nodes = [{"id": c["ticker"], "name": c.get("name", "")} for c in track["companies"] if c.get("ticker")]
    links = []
    for i in range(len(track["companies"])):
        for j in range(i + 1, len(track["companies"])):
            a, b = track["companies"][i], track["companies"][j]
            ta, tb = str(a.get("ticker", "")).upper(), str(b.get("ticker", "")).upper()
            if not ta or not tb:
                continue
            aa = alias_map.get(ta, {ta.lower()})
            bb = alias_map.get(tb, {tb.lower()})
            ra = [r for r in collected if company_mentioned(r.headline, ta, aa)]
            rb = [r for r in collected if company_mentioned(r.headline, tb, bb)]
            both = [r for r in collected if r in ra and r in rb]
            use_rows = both if both else (ra + [r for r in rb if r not in ra])
            if not use_rows:
                continue
            pair_a, pair_b = normalize_pair(ta, tb)
            summary = " ".join(r.headline for r in use_rows[:6]).strip()
            seen_src = set()
            src: list[str] = []
            for r in use_rows[:10]:
                s = r.url if (r.url and r.url.startswith("http")) else f"{r.source_id} | {r.headline}"
                if s not in seen_src:
                    seen_src.add(s)
                    src.append(s)
            headlines_shared = len({r.headline for r in both}) if both else len({r.headline for r in use_rows})
            links.append(
                {
                    "source_id": pair_a,
                    "target_id": pair_b,
                    "pair": f"{pair_a} - {pair_b}",
                    "relationship": "both" if both else "one",
                    "summary": summary,
                    "sources": src,
                    "headlines_shared": headlines_shared,
                    "confidence": calc_link_confidence(headlines_shared=headlines_shared, source_count=len(src)),
                    "momentum_liquidity_confidence": round(
                        0.5 * calc_link_confidence(headlines_shared=headlines_shared, source_count=len(src))
                        + 0.25 * float(ticker_signal_scores.get(pair_a, {}).get("combined_score", 0.0))
                        + 0.25 * float(ticker_signal_scores.get(pair_b, {}).get("combined_score", 0.0)),
                        4,
                    ),
                }
            )

    max_shared = max((int(l.get("headlines_shared", 0) or 0) for l in links), default=1)
    w_co, w_ml = _normalize_nonnegative_weights([score_weight_cooccurrence, 1.0 - score_weight_cooccurrence], [0.4, 0.6])
    for link in links:
        shared_component = (int(link.get("headlines_shared", 0) or 0) / max_shared) if max_shared else 0.0
        ml_component = float(link.get("momentum_liquidity_confidence", 0.0))
        link["ranking_score"] = round((w_co * shared_component) + (w_ml * ml_component), 4)

    metadata = {
        "run_id": run_id,
        "generated_at": _iso_utc(),
        "sources_attempted": len(source_attempts),
        "sources_succeeded": sum(1 for x in source_attempts if x.get("ok")),
        "source_attempt_details": source_attempts,
        "cache_ttl_hours": round(cache_ttl_seconds / 3600.0, 4),
        "score_weights": {
            "momentum": score_weight_momentum,
            "liquidity": score_weight_liquidity,
            "cooccurrence": score_weight_cooccurrence,
        },
    }
    brief_json = {
        "track_name": track["label"],
        "track_id": track["track_id"],
        "last_updated": _utc_now().date().isoformat(),
        "metadata": metadata,
        "ticker_signal_scores": ticker_signal_scores,
        "nodes": nodes,
        "links": links,
    }

    return {
        "brief_json": brief_json,
        "ticker_summaries": ticker_summaries,
        "collected": collected,
        "counts": counts,
        "rss_fallbacks": rss_fallbacks,
        "terms_count": len(terms),
        "ticker_for_run": ticker_for_run,
    }


def write_outputs(
    *,
    run_result: dict[str, Any],
    track: dict[str, Any],
    min_hits: int,
    root_txt_path: Path,
    root_json_path: Path,
    root_summaries_path: Path,
    briefs_dir: Path,
    write_root_files: bool,
) -> tuple[Path, Path, Path]:
    brief_json = run_result["brief_json"]
    ticker_summaries = run_result["ticker_summaries"]
    collected: list[BriefRow] = run_result["collected"]
    counts: dict[str, int] = run_result["counts"]
    rss_fallbacks = run_result["rss_fallbacks"]
    ticker_for_run = run_result["ticker_for_run"]
    terms_count = run_result["terms_count"]

    briefs_dir.mkdir(parents=True, exist_ok=True)
    out_json_per_track = briefs_dir / f"geopolitical_brief_{_slugify_track(track['track_id'])}.json"
    out_summaries_per_track = briefs_dir / f"news_summaries_{_slugify_track(track['track_id'])}.json"

    ordered_ids = [s[0] for s in rss_fallbacks] + [f"rss_yahoo_{ticker_for_run}"]
    prov = [f"{sid}: +{counts.get(sid, 0)}" for sid in ordered_ids]
    lines = [
        "NEXUS - Demo geopolitical/ag brief (consolidated walkthrough)",
        f"Primary ticker (Yahoo RSS): {ticker_for_run}",
        f"Track: {track['label']} [{track['track_id']}]",
        f"Collected (UTC): {_iso_utc(_utc_now().replace(microsecond=0))}",
        f"Match threshold: min_hits={min_hits} | terms~{terms_count}",
        "",
        "--- Provenance (matches per source) ---",
        *[f"- {x}" for x in prov],
        "",
        "--- Matched headlines ---",
    ]
    if not collected:
        lines.append("(none after full chain)")
    else:
        for r in collected:
            lines.append(f"- [{r.source_id}] {r.headline}")
            if r.url:
                lines.append(f"  {r.url}")

    json_text = json.dumps(brief_json, indent=2, ensure_ascii=False)
    lines.extend(["", "--- JSON (same object as geopolitical_brief.json) ---", json_text, ""])
    summaries_text = json.dumps(ticker_summaries, indent=2, ensure_ascii=False)

    out_json_per_track.write_text(json_text + "\n", encoding="utf-8")
    out_summaries_per_track.write_text(summaries_text + "\n", encoding="utf-8")

    if write_root_files:
        root_txt_path.write_text("\n".join(lines), encoding="utf-8")
        root_json_path.write_text(json_text + "\n", encoding="utf-8")
        root_summaries_path.write_text(summaries_text + "\n", encoding="utf-8")

    return out_json_per_track, out_summaries_per_track, root_json_path


def main() -> None:
    args = parse_args()
    selected_track_id = str(args.track).strip() or TRACK_ID
    selected_ticker_override = str(args.ticker).strip().upper() if args.ticker else None
    selected_min_hits = max(1, int(args.min_hits))
    score_weight_momentum = float(args.score_weight_momentum)
    score_weight_liquidity = float(args.score_weight_liquidity)
    score_weight_cooccurrence = float(args.score_weight_cooccurrence)

    if not args.skip_install:
        install_runtime_deps()

    load_env_if_available()
    fetch_rss_as_news_items, fetch_backend = get_rss_fetcher()
    run_id = uuid.uuid4().hex[:12]
    print("NEXUS_ROOT:", NEXUS_ROOT)
    print(
        "Run config:",
        f"run_id={run_id}",
        f"track={selected_track_id}",
        f"ticker={selected_ticker_override or '(auto)'}",
        f"min_hits={selected_min_hits}",
        f"all_tracks={args.all_tracks}",
        f"rss_backend={fetch_backend}",
        f"weights(mom,liq,co)={score_weight_momentum:.3f},{score_weight_liquidity:.3f},{score_weight_cooccurrence:.3f}",
    )

    selected_track, _ticker_grouped, all_tracks = load_track_sources(selected_track_id)
    if args.all_tracks:
        track_runs = all_tracks
    else:
        track_runs = [selected_track] if selected_track else []

    nodes_index = load_nodes_index()
    if nodes_index:
        print(f"Loaded nodes index for alias matching: {len(nodes_index)} companies")

    cache_dir = NEXUS_ROOT / ".cache" / "geopolitical_brief"
    cache_dir.mkdir(parents=True, exist_ok=True)
    health = load_health(cache_dir)

    summarizer = build_summarizer(api_key=GEMINI_API_KEY)
    print("Summarizer ready. Gemini client:", "YES" if summarizer.client else "NO (mock mode)")

    root_txt = NEXUS_ROOT / "geopolitical_brief.txt"
    root_json = NEXUS_ROOT / "geopolitical_brief.json"
    root_summaries = NEXUS_ROOT / "news_summaries.json"
    briefs_dir = NEXUS_ROOT / "scraper" / "data" / "processed" / "briefs"

    manifest: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []
    valid_tickers = set(nodes_index.keys())

    for idx, track in enumerate(track_runs, 1):
        if not isinstance(track, dict):
            continue
        companies = [c for c in (track.get("companies") or []) if isinstance(c, dict) and c.get("ticker")]
        if not companies:
            continue
        ticker_for_run = selected_ticker_override or str(companies[0]["ticker"]).upper().strip() or TICKER

        print(f"\n=== [{idx}/{len(track_runs)}] {track.get('label','(unknown)')} ===")
        result = run_track(
            track=track,
            ticker_for_run=ticker_for_run,
            min_hits=selected_min_hits,
            include_energy_terms=bool(args.include_energy_terms),
            summarizer=summarizer,
            fetch_func=fetch_rss_as_news_items,
            nodes_index=nodes_index,
            cache_dir=cache_dir,
            cache_ttl_seconds=max(60.0, float(args.cache_ttl_hours) * 3600.0),
            health=health,
            run_id=run_id,
            score_weight_momentum=score_weight_momentum,
            score_weight_liquidity=score_weight_liquidity,
            score_weight_cooccurrence=score_weight_cooccurrence,
        )

        out_json_per_track, out_summaries_per_track, _ = write_outputs(
            run_result=result,
            track=track,
            min_hits=selected_min_hits,
            root_txt_path=root_txt,
            root_json_path=root_json,
            root_summaries_path=root_summaries,
            briefs_dir=briefs_dir,
            write_root_files=(len(track_runs) == 1),
        )
        print("Wrote:", out_json_per_track)
        print("Wrote:", out_summaries_per_track)
        if len(track_runs) == 1:
            print("Wrote:", root_txt)
            print("Wrote:", root_json)
            print("Wrote:", root_summaries)

        brief_json = result["brief_json"]
        manifest.append(
            {
                "track_id": track.get("track_id", ""),
                "track_name": track.get("label", ""),
                "brief_file": str(out_json_per_track),
                "summaries_file": str(out_summaries_per_track),
                "links": len(brief_json.get("links", [])),
                "nodes": len(brief_json.get("nodes", [])),
            }
        )
        all_edges.extend(build_news_edges(brief_json, valid_tickers=valid_tickers))

    save_health(cache_dir, health)

    if len(track_runs) > 1:
        manifest_path = briefs_dir / "geopolitical_brief_manifest.json"
        manifest_path.write_text(json.dumps({"run_id": run_id, "generated_at": _iso_utc(), "tracks": manifest}, indent=2) + "\n", encoding="utf-8")
        print("Wrote:", manifest_path)

    if args.export_news_edges is not None:
        edges_path = (
            NEXUS_ROOT / "scraper" / "data" / "processed" / "edges_news_cooccurrence.json"
            if args.export_news_edges == "auto"
            else Path(args.export_news_edges)
        )
        edges_path.parent.mkdir(parents=True, exist_ok=True)
        dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
        for e in all_edges:
            key = (e["source_id"], e["target_id"], e["relationship_type"])
            prior = dedup.get(key)
            if prior is None or float(e.get("weight", 0.0)) > float(prior.get("weight", 0.0)):
                dedup[key] = e
        edges_path.write_text(json.dumps(list(dedup.values()), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("Wrote:", edges_path, f"({len(dedup)} edges)")


if __name__ == "__main__":
    main()

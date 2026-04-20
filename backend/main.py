from flask import Flask, Blueprint, g, jsonify, request
from flask_cors import CORS
import base64
import hashlib
import json
import os
import time
import psycopg2
import psycopg2.extras
from config import DATABASE_URL

app = Flask(__name__)

# CORS allow-list. In dev we want the whole web open; in prod we pin it to
# the iPick origin so browsers from elsewhere can't call the API directly.
_cors_env = os.getenv("NEXUS_CORS_ORIGINS", "*")
if _cors_env == "*":
    CORS(app, supports_credentials=True)
else:
    CORS(
        app,
        origins=[o.strip() for o in _cors_env.split(",") if o.strip()],
        supports_credentials=True,
        allow_headers=["Authorization", "Content-Type"],
    )

# All routes live under this prefix so nginx can proxy /nexus/api/* → us while
# the client's existing app keeps owning the root. Override with
# NEXUS_API_PREFIX (e.g. "") if you want to mount at root in a bare deploy.
API_PREFIX = os.getenv("NEXUS_API_PREFIX", "/nexus/api")
api = Blueprint("nexus_api", __name__, url_prefix=API_PREFIX)

# ── Admin allowlist ─────────────────────────────────────────────────────
# Email allowlist for /nexus/api/admin/* routes. Every request to those
# paths must have a Firebase-verified token AND an email that appears in
# this list. Comma-separated, case-insensitive.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv(
        "NEXUS_ADMIN_EMAILS",
        "andrewzhou@berkeley.edu,yunhong@ipick.ai",
    ).split(",")
    if e.strip()
}


def _is_admin() -> bool:
    """True when the current request's Firebase user is in the allowlist."""
    user = getattr(g, "user", None) or {}
    email = (user.get("email") or "").lower()
    return bool(email) and email in ADMIN_EMAILS


# ── Anthropic client (optional; for /summary endpoints) ──────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
_anthropic = None
if ANTHROPIC_API_KEY:
    try:
        import anthropic
        _anthropic = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        print("[nexus] anthropic client initialized (Claude Haiku 4.5)")
    except Exception as e:
        print(f"[nexus] anthropic init failed: {e} — /summary will return empty")
else:
    print("[nexus] ANTHROPIC_API_KEY unset — /summary will return empty")


# ── In-memory TTL cache for /summary responses ───────────────────────────
# Simple dict-of-(timestamp, payload). Process-local so multiple gunicorn
# workers don't share — that's fine at this scale (~dozens of calls/day),
# worst case we do a handful of extra Anthropic calls.
_summary_cache: dict[str, tuple[float, dict]] = {}
SUMMARY_CACHE_TTL = 15 * 60  # 15 minutes


def _cache_get(key: str):
    hit = _summary_cache.get(key)
    if hit and (time.time() - hit[0]) < SUMMARY_CACHE_TTL:
        return hit[1]
    return None


def _cache_set(key: str, value: dict):
    _summary_cache[key] = (time.time(), value)


# ── Firebase auth (optional; off in dev, on in prod) ─────────────────────
# Set NEXUS_REQUIRE_AUTH=1 along with FIREBASE_CREDENTIALS (base64-encoded
# service account JSON, same format iPick's webapp uses) to gate every
# /nexus/api/* request behind a verified Firebase ID token.
REQUIRE_AUTH = os.getenv("NEXUS_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")
_fb_auth = None
if REQUIRE_AUTH:
    import firebase_admin
    from firebase_admin import credentials, auth as _fb_auth_mod  # noqa: F401
    creds_b64 = os.environ.get("FIREBASE_CREDENTIALS")
    if not creds_b64:
        raise RuntimeError(
            "NEXUS_REQUIRE_AUTH=1 but FIREBASE_CREDENTIALS is not set. "
            "Populate it with the base64-encoded Firebase service account JSON."
        )
    _creds_dict = json.loads(base64.b64decode(creds_b64))
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(_creds_dict))
    _fb_auth = _fb_auth_mod
    print(f"[nexus] firebase auth ENABLED (project: {_creds_dict.get('project_id')})")
else:
    print("[nexus] firebase auth DISABLED (set NEXUS_REQUIRE_AUTH=1 to enable)")


@api.before_request
def _gate_api():
    """Block every API request without a valid Firebase ID token when
    NEXUS_REQUIRE_AUTH is on. /nexus/api/config is the public exception so
    the frontend can bootstrap Firebase before the user is authenticated."""
    if not REQUIRE_AUTH:
        return None
    if request.method == "OPTIONS":  # CORS preflight
        return None
    if request.path.rstrip("/").endswith("/config"):
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "missing Authorization: Bearer <id_token>"}), 401
    token = auth_header.split(" ", 1)[1].strip()
    try:
        g.user = _fb_auth.verify_id_token(token)
    except Exception as e:
        return jsonify({"error": f"invalid token: {e}"}), 401

    # Second layer: /admin/* paths require the email to be in the allowlist.
    # Skips the check if auth is disabled entirely (local dev without creds).
    if "/admin/" in request.path or request.path.rstrip("/").endswith("/admin"):
        if not _is_admin():
            return jsonify({
                "error": "admin-only endpoint",
                "user_email": (getattr(g, "user", {}) or {}).get("email"),
            }), 403

    return None


@api.route("/config")
def get_config():
    """
    Public bootstrap endpoint — tells the frontend whether auth is required
    and hands back the Firebase client config so it can initialize the SDK.
    API key is safe to expose; Firebase enforces auth server-side.
    """
    return jsonify({
        "requireAuth": REQUIRE_AUTH,
        "firebase": {
            "apiKey":      os.getenv("FIREBASE_API_KEY", ""),
            "authDomain":  os.getenv("FIREBASE_AUTH_DOMAIN", ""),
            "projectId":   os.getenv("FIREBASE_PROJECT_ID", ""),
        } if REQUIRE_AUTH else None,
        "loginUrl": os.getenv("NEXUS_LOGIN_URL", "https://www.ipick.ai"),
    })


import yfinance as yf


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def track_color(track_name: str) -> str:
    """Stable pastel color for a track name (so the frontend gets consistent colors)."""
    h = int(hashlib.md5(track_name.encode()).hexdigest()[:6], 16)
    palette = [
        "#10b981", "#a78bfa", "#ec4899", "#22d3ee", "#84cc16",
        "#f97316", "#6366f1", "#06b6d4", "#d946ef", "#14b8a6",
    ]
    return palette[h % len(palette)]


def slugify(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


@api.route("/companies")
def get_companies():
    conn = get_conn()
    cursor = conn.cursor()

    limit = request.args.get("limit", default=500, type=int)
    cursor.execute("SELECT ticker, name, price FROM companies LIMIT %s", (limit,))
    rows = cursor.fetchall()
    conn.close()

    return jsonify([
        {"ticker": r[0], "name": r[1], "price": r[2]}
        for r in rows
    ])


@api.route("/companies/<ticker>")
def get_company(ticker):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ticker, name, exchange, country, sector, industry, currency,
            price, market_cap, enterprise_value, pe_ratio, eps,
            employees, website, description, created_at
        FROM companies
        WHERE ticker = %s
    """, (ticker,))

    row = cursor.fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "Company not found"}), 404

    company = {
        "ticker": row[0],
        "name": row[1],
        "exchange": row[2],
        "country": row[3],
        "sector": row[4],
        "industry": row[5],
        "currency": row[6],
        "price": row[7],
        "market_cap": row[8],
        "enterprise_value": row[9],
        "pe_ratio": row[10],
        "eps": row[11],
        "employees": row[12],
        "website": row[13],
        "description": row[14],
        "created_at": str(row[15]),
    }

    cursor.execute("""
        SELECT t.id, t.name
        FROM investment_tracks t
        JOIN company_tracks ct ON ct.track_id = t.id
        JOIN companies c ON c.id = ct.company_id
        WHERE c.ticker = %s
    """, (ticker,))
    track = cursor.fetchone()
    company["investment_track"] = {"id": track[0], "name": track[1]} if track else None

    conn.close()
    return jsonify(company)


@api.route("/companies/<ticker>/neighbors")
def get_neighbors(ticker):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT ticker FROM companies WHERE ticker = %s", (ticker,))
    if cursor.fetchone() is None:
        conn.close()
        return jsonify({"error": "Company not found"}), 404

    rel_type = request.args.get("type")
    min_weight = request.args.get("min_weight", type=float)
    max_weight = request.args.get("max_weight", type=float)
    limit = request.args.get("limit", default=50, type=int)

    conditions = ["(r.source_ticker = %s OR r.target_ticker = %s)"]
    params = [ticker, ticker]

    if rel_type:
        conditions.append("r.relationship_type = %s")
        params.append(rel_type)
    if min_weight is not None:
        conditions.append("r.weight >= %s")
        params.append(min_weight)
    if max_weight is not None:
        conditions.append("r.weight <= %s")
        params.append(max_weight)

    params.append(limit)

    cursor.execute(f"""
        SELECT r.id, r.source_ticker, r.target_ticker, r.relationship_type, r.weight, r.metadata
        FROM relationships r
        WHERE {' AND '.join(conditions)}
        ORDER BY r.weight DESC
        LIMIT %s
    """, params)

    edge_rows = cursor.fetchall()

    neighbor_tickers = set()
    for row in edge_rows:
        neighbor_tickers.add(row[1])
        neighbor_tickers.add(row[2])
    neighbor_tickers.discard(ticker)

    all_tickers = list(neighbor_tickers | {ticker})
    cursor.execute("""
        SELECT ticker, name, sector, industry, price, market_cap
        FROM companies
        WHERE ticker = ANY(%s)
    """, (all_tickers,))

    company_rows = cursor.fetchall()
    conn.close()

    nodes = [
        {"ticker": r[0], "name": r[1], "sector": r[2], "industry": r[3], "price": r[4], "market_cap": r[5]}
        for r in company_rows
    ]
    edges = [
        {"id": r[0], "source": r[1], "target": r[2], "type": r[3], "weight": r[4], "metadata": r[5]}
        for r in edge_rows
    ]

    return jsonify({"nodes": nodes, "edges": edges})


@api.route("/investment_tracks", strict_slashes=False)
def get_investment_tracks():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM investment_tracks")
    track_rows = cursor.fetchall()

    tracks = []
    for track_id, track_name in track_rows:
        cursor.execute("""
            SELECT c.ticker, c.name
            FROM companies c
            JOIN company_tracks ct ON ct.company_id = c.id
            WHERE ct.track_id = %s
        """, (track_id,))
        tracks.append({
            "name": track_name,
            "companies": [{"ticker": r[0], "name": r[1]} for r in cursor.fetchall()]
        })

    conn.close()
    return jsonify(tracks)


@api.route("/investment_tracks/<int:track_id>/companies")
def get_track_companies(track_id):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM investment_tracks WHERE id = %s", (track_id,))
    if cursor.fetchone() is None:
        conn.close()
        return jsonify({"error": "Track not found"}), 404

    cursor.execute("""
        SELECT c.ticker, c.name
        FROM companies c
        JOIN company_tracks ct ON ct.company_id = c.id
        WHERE ct.track_id = %s
    """, (track_id,))

    companies = [{"ticker": r[0], "name": r[1]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(companies)


def fetch_news_for(ticker: str, limit: int = 8) -> list:
    """Pull news headlines for a ticker via yfinance (Yahoo Finance, free)."""
    try:
        import yfinance as yf
    except Exception:
        return []
    try:
        items = yf.Ticker(ticker).news or []
    except Exception as e:
        print(f"[news] yfinance failed for {ticker}: {e}")
        return []

    out = []
    for it in items[:limit]:
        # yfinance returns either flat dicts or wrapped {content: {...}} shapes
        # depending on version — flatten both.
        c = it.get("content") or it
        title = c.get("title") or it.get("title")
        if not title:
            continue
        link = (
            (c.get("clickThroughUrl") or {}).get("url")
            or (c.get("canonicalUrl") or {}).get("url")
            or it.get("link")
        )
        publisher = (
            (c.get("provider") or {}).get("displayName")
            or c.get("publisher")
            or it.get("publisher")
        )
        published = c.get("pubDate") or it.get("providerPublishTime")
        summary = c.get("summary") or c.get("description") or ""
        out.append({
            "title": title,
            "link": link,
            "publisher": publisher,
            "published": published,
            "summary": summary,
            "ticker": ticker,
        })
    return out


@api.route("/companies/<ticker>/news")
def get_company_news(ticker):
    limit = request.args.get("limit", default=8, type=int)
    return jsonify(fetch_news_for(ticker.upper(), limit=limit))


@api.route("/tracks/<slug>/news")
def get_track_news(slug):
    """Aggregate news for the top-N companies (by market cap) in this track."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM investment_tracks")
    target = None
    for tid, name in cursor.fetchall():
        if slugify(name) == slug:
            target = (tid, name)
            break
    if target is None:
        conn.close()
        return jsonify({"error": "Track not found"}), 404

    track_id, _ = target
    top_n = request.args.get("companies", default=5, type=int)
    per_company = request.args.get("per", default=3, type=int)

    cursor.execute("""
        SELECT c.ticker
        FROM companies c
        JOIN company_tracks ct ON ct.company_id = c.id
        WHERE ct.track_id = %s
        ORDER BY COALESCE(c.market_cap, 0) DESC
        LIMIT %s
    """, (track_id, top_n))
    tickers = [r[0] for r in cursor.fetchall()]
    conn.close()

    aggregated = []
    for t in tickers:
        aggregated.extend(fetch_news_for(t, limit=per_company))
    return jsonify(aggregated)


# ── AI-summary endpoints (Claude Haiku 4.5 + native citations) ───────────
#
# The citations API returns structured references into the `documents`
# array we pass in — we give one document per news article, which lets
# the frontend scroll the exact article into view when the user clicks
# a [1] [2] [3] marker in the summary.
#
# Design notes:
#   - POST, not GET, so browser link-prefetch / prerender doesn't trigger
#     an API call (and an Anthropic bill)
#   - 15-min in-memory cache on the server. First user per ticker pays
#     the API call; the next ~dozens within 15 min are free
#   - Empty payload (not error) when ANTHROPIC_API_KEY isn't set, so the
#     frontend degrades gracefully in dev
#   - Usage logged per call so `journalctl -u nexus -f | grep summary`
#     shows live cost

def build_summary(
    articles: list[dict],
    subject: str,
    constituents: list[dict] | None = None,
) -> dict:
    """
    Turn a list of news articles into a Claude-generated summary with
    inline citations.

    Args:
        articles: each has {title, summary, link, publisher, published, ticker}.
        subject: ticker ('NVDA') or track descriptor
            ('the Advertising Agencies - China investment track').
        constituents: for track summaries, the list of companies whose news
            is aggregated in `articles`. Shape: [{ticker, name}, ...]. Without
            this the model has no way to connect a track label to the news
            documents and often refuses with 'I don't have information about X'.

    Returns:
        {
          "summary": "...", "citations": [...], "used_articles": N,
          "cached": False, "model": "..."
        }
    """
    if not _anthropic or not articles:
        return {"summary": "", "citations": [], "used_articles": 0,
                "cached": False, "model": None}

    documents = []
    for i, art in enumerate(articles):
        body_parts = []
        if art.get("title"):     body_parts.append(art["title"])
        if art.get("summary"):   body_parts.append(art["summary"])
        body = "\n\n".join(body_parts).strip()
        if not body:
            continue
        documents.append({
            "type": "document",
            "source": {
                "type": "content",
                "content": [{"type": "text", "text": body}],
            },
            "title": art.get("publisher") or f"Article {i + 1}",
            "context": f"article_index={i}; ticker={art.get('ticker', '')}",
            "citations": {"enabled": True},
        })

    if not documents:
        return {"summary": "", "citations": [], "used_articles": 0,
                "cached": False, "model": None}

    # Build the user-message prompt. For track summaries we inject the
    # constituent companies explicitly so the model knows the documents
    # ARE the track's evidence and doesn't refuse with "I don't have info
    # about <track name>."
    user_prompt_lines = []
    if constituents:
        roster = ", ".join(
            f"{c['ticker']} ({c['name']})" if c.get("name") else c["ticker"]
            for c in constituents
        )
        user_prompt_lines.append(
            f"The following news articles cover {subject}, which includes these "
            f"public companies: {roster}. Treat each article as news about one "
            f"of these companies."
        )
    user_prompt_lines.append(
        f"Summarize the recent news about {subject} in 3-5 sentences with "
        "inline citations. If multiple companies have distinct news items, "
        "a short bulleted list is appropriate."
    )
    user_prompt = "\n\n".join(user_prompt_lines)

    msg = _anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=700,
        system=(
            f"You are writing a 3-5 sentence news brief about {subject} for a "
            "retail investor. Cite every factual claim back to the source "
            "documents using the citations API. Be specific about dates and "
            "numbers when the source has them. Do not invent facts. Neutral, "
            "factual tone — no hype, no recommendations.\n\n"
            "Format with light markdown where it aids readability: "
            "**bold** for the 1-2 most important phrases per summary, "
            "and a short bulleted list if the news naturally breaks into "
            "multiple distinct items. Do NOT use headings, tables, or code "
            "blocks. Plain prose is fine when nothing stands out."
        ),
        messages=[{
            "role": "user",
            "content": [
                *documents,
                {"type": "text", "text": user_prompt},
            ],
        }],
    )

    # Walk content blocks. Each text block can have a `citations` list.
    # The SDK may expose fields as attrs (v0.x) or dict keys (rare) — handle
    # both without blowing up.
    def _get(obj, name, default=None):
        if hasattr(obj, name):
            return getattr(obj, name, default)
        if isinstance(obj, dict):
            return obj.get(name, default)
        return default

    text_parts = []
    cite_list = []
    ref_counter = 0
    for block in msg.content:
        if _get(block, "type") != "text":
            continue
        text_parts.append(_get(block, "text", ""))
        for c in (_get(block, "citations") or []):
            ref_counter += 1
            cite_list.append({
                "ref": ref_counter,
                "article_index": _get(c, "document_index"),
                "cited_text": _get(c, "cited_text"),
            })

    # Log usage (journalctl -u nexus -f | grep summary)
    try:
        usage = msg.usage
        in_tok = getattr(usage, "input_tokens", 0)
        out_tok = getattr(usage, "output_tokens", 0)
        cost_usd = (in_tok * 1 + out_tok * 5) / 1_000_000  # Haiku 4.5 pricing
        print(f"[summary] subject={subject!r} docs={len(documents)} "
              f"input={in_tok} output={out_tok} cost=${cost_usd:.4f}")
    except Exception:
        pass

    return {
        "summary": "".join(text_parts).strip(),
        "citations": cite_list,
        "used_articles": len(documents),
        "cached": False,
        "model": "claude-haiku-4-5-20251001",
    }


@api.route("/companies/<ticker>/summary", methods=["POST"])
def get_company_summary(ticker):
    ticker = ticker.upper().strip()
    cache_key = f"company:{ticker}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify({**cached, "cached": True})
    articles = fetch_news_for(ticker, limit=10)
    result = build_summary(articles, subject=ticker)
    _cache_set(cache_key, result)
    return jsonify(result)


@api.route("/tracks/<slug>/summary", methods=["POST"])
def get_track_summary(slug):
    cache_key = f"track:{slug}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify({**cached, "cached": True})

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM investment_tracks")
    target = next(((tid, name) for tid, name in cursor.fetchall()
                   if slugify(name) == slug), None)
    if target is None:
        conn.close()
        return jsonify({"error": "Track not found"}), 404
    track_id, track_name = target
    cursor.execute("""
        SELECT c.ticker, c.name FROM companies c
        JOIN company_tracks ct ON ct.company_id = c.id
        WHERE ct.track_id = %s
        ORDER BY COALESCE(c.market_cap, 0) DESC LIMIT 5
    """, (track_id,))
    constituents = [{"ticker": r[0], "name": r[1]} for r in cursor.fetchall()]
    conn.close()

    articles = []
    for c in constituents:
        articles.extend(fetch_news_for(c["ticker"], limit=3))

    result = build_summary(
        articles,
        subject=f"the {track_name} investment track",
        constituents=constituents,
    )
    _cache_set(cache_key, result)
    return jsonify(result)


@api.route("/companies/<ticker>/live")
def get_company_live(ticker):
    """Pull a fresh quote from Yahoo Finance via yfinance."""
    try:
        t = yf.Ticker(ticker.upper())
        info = t.info
    except Exception as e:
        return jsonify({"error": f"yahoo fetch failed: {e}"}), 502

    if not info or info.get("quoteType") is None:
        return jsonify({"error": "Company not found"}), 404

    change_pct = info.get("regularMarketChangePercent")
    return jsonify({
        "ticker":             ticker.upper(),
        "companyName":        info.get("longName") or info.get("shortName"),
        "description":        info.get("longBusinessSummary"),
        "sector":             info.get("sector"),
        "industry":           info.get("industry"),
        "country":            info.get("country"),
        "price":              info.get("currentPrice") or info.get("regularMarketPrice"),
        "changePercent":      change_pct / 100 if change_pct is not None else None,
        "marketCap":          info.get("marketCap"),
        "trailingPE":         info.get("trailingPE"),
        "forwardPE":          info.get("forwardPE"),
        "trailingEPS":        info.get("trailingEps"),
        "fiftyTwoWeekHigh":   info.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow":    info.get("fiftyTwoWeekLow"),
        "open":               info.get("open"),
        "previousClose":      info.get("previousClose"),
        "dayHigh":            info.get("dayHigh"),
        "dayLow":             info.get("dayLow"),
        "volume":             info.get("volume"),
        "avgVolume":          info.get("averageVolume"),
        "dividendYield":      info.get("dividendYield") / 100 if info.get("dividendYield") is not None else None,
        "beta":               info.get("beta"),
        "fullTimeEmployees":  info.get("fullTimeEmployees"),
        "website":            info.get("website"),
    })


@api.route("/tracks")
def list_tracks():
    """All investment tracks with company counts (for the track index page)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.name, COUNT(ct.company_id) AS company_count
        FROM investment_tracks t
        LEFT JOIN company_tracks ct ON ct.track_id = t.id
        GROUP BY t.id, t.name
        ORDER BY company_count DESC, t.name
    """)
    out = [
        {
            "id": tid,
            "slug": slugify(name),
            "name": name,
            "color": track_color(name),
            "company_count": count,
        }
        for tid, name, count in cursor.fetchall()
    ]
    conn.close()
    return jsonify(out)


@api.route("/tracks/<slug>")
def get_track(slug):
    """
    Detail page payload for a single investment track.
    Returns: { name, slug, color, description, market_leader, companies[] }
    Companies are sorted by market_cap desc; the top one is the market_leader.
    """
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, description FROM investment_tracks")
    target = None
    for tid, name, description in cursor.fetchall():
        if slugify(name) == slug:
            target = (tid, name, description)
            break
    if target is None:
        conn.close()
        return jsonify({"error": "Track not found"}), 404

    track_id, name, description = target

    cursor.execute("""
        SELECT c.ticker, c.name, c.sector, c.industry, c.price, c.market_cap,
               c.pe_ratio, c.eps, c.website
        FROM companies c
        JOIN company_tracks ct ON ct.company_id = c.id
        WHERE ct.track_id = %s
        ORDER BY COALESCE(c.market_cap, 0) DESC, c.ticker
    """, (track_id,))
    companies = [
        {
            "ticker": r[0], "name": r[1], "sector": r[2], "industry": r[3],
            "price": r[4], "market_cap": r[5], "pe_ratio": r[6], "eps": r[7],
            "website": r[8],
        }
        for r in cursor.fetchall()
    ]

    conn.close()
    return jsonify({
        "slug": slug,
        "name": name,
        "color": track_color(name),
        "description": description,
        "market_leader": companies[0] if companies else None,
        "companies": companies,
        "company_count": len(companies),
    })


@api.route("/graph")
def get_graph():
    """
    Aggregated graph payload consumed by the frontend.
    Shape matches frontend/data/mock.json so the D3 graph renders unchanged.
    """
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM investment_tracks ORDER BY name")
    track_rows = cursor.fetchall()
    tracks = [
        {"id": slugify(name), "label": name, "color": track_color(name)}
        for _, name in track_rows
    ]
    track_id_by_db_id = {db_id: slugify(name) for db_id, name in track_rows}

    cursor.execute("""
        SELECT c.id, c.ticker, c.name, c.sector, c.market_cap, c.price, c.description,
               COALESCE(
                 array_agg(ct.track_id) FILTER (WHERE ct.track_id IS NOT NULL),
                 ARRAY[]::int[]
               ) AS track_ids
        FROM companies c
        LEFT JOIN company_tracks ct ON ct.company_id = c.id
        GROUP BY c.id
    """)
    nodes = []
    for cid, ticker, name, sector, market_cap, price, description, track_ids in cursor.fetchall():
        slugs = [track_id_by_db_id[t] for t in track_ids if t in track_id_by_db_id]
        nodes.append({
            "id": ticker.lower(),
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "marketCap": (market_cap or 0) / 1e9,
            "price": price,
            "track": slugs[0] if slugs else "uncategorized",
            "tracks": slugs,
            "description": description or "",
        })

    cursor.execute("""
        SELECT source_ticker, target_ticker, relationship_type
        FROM relationships
    """)
    edges = [
        {"source": s.lower(), "target": t.lower(), "type": rt}
        for s, t, rt in cursor.fetchall()
    ]

    # Generate competitor edges between all companies sharing an investment track
    cursor.execute("""
        SELECT c1.ticker, c2.ticker
        FROM company_tracks ct1
        JOIN company_tracks ct2 ON ct1.track_id = ct2.track_id AND ct1.company_id < ct2.company_id
        JOIN companies c1 ON c1.id = ct1.company_id
        JOIN companies c2 ON c2.id = ct2.company_id
    """)
    edges += [
        {"source": s.lower(), "target": t.lower(), "type": "competitor"}
        for s, t in cursor.fetchall()
    ]

    conn.close()
    return jsonify({"tracks": tracks, "nodes": nodes, "edges": edges})


# ── /admin/* endpoints ───────────────────────────────────────────────────
# Gated by _gate_api() (Firebase token + NEXUS_ADMIN_EMAILS allowlist) via
# the "/admin/" path prefix check. Leaving auth off in dev means anyone on
# localhost can hit these; turning NEXUS_REQUIRE_AUTH=1 on prod restores
# the gate.

@api.route("/admin/whoami")
def admin_whoami():
    """Echo the authenticated user and whether they're admin — useful for
    the frontend to show a clear 'you are signed in as X but not authorized'
    message instead of an opaque 403 page."""
    user = getattr(g, "user", None) or {}
    return jsonify({
        "email": user.get("email"),
        "is_admin": _is_admin(),
        "allowlist": sorted(ADMIN_EMAILS),
    })


@api.route("/admin/tracks")
def admin_list_tracks():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.name, t.description, COUNT(ct.company_id) AS company_count
        FROM investment_tracks t
        LEFT JOIN company_tracks ct ON ct.track_id = t.id
        GROUP BY t.id, t.name, t.description
        ORDER BY LOWER(t.name)
    """)
    rows = [
        {"id": r[0], "name": r[1], "description": r[2], "company_count": r[3]}
        for r in cursor.fetchall()
    ]
    conn.close()
    return jsonify(rows)


@api.route("/admin/tracks/<int:track_id>", methods=["PATCH"])
def admin_update_track(track_id):
    body = request.get_json(force=True, silent=True) or {}
    new_name = (body.get("name") or "").strip()
    new_description = body.get("description")
    if not new_name and new_description is None:
        return jsonify({"error": "need at least one of 'name' or 'description'"}), 400
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM investment_tracks WHERE id = %s", (track_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "track not found"}), 404
    # Collision check on rename
    if new_name:
        cursor.execute(
            "SELECT id FROM investment_tracks WHERE LOWER(name) = LOWER(%s) AND id != %s",
            (new_name, track_id),
        )
        dup = cursor.fetchone()
        if dup:
            conn.close()
            return jsonify({
                "error": "a track with that name already exists — use merge instead",
                "collides_with_id": dup[0],
            }), 409
    sets, params = [], []
    if new_name:
        sets.append("name = %s"); params.append(new_name)
    if new_description is not None:
        sets.append("description = %s"); params.append(new_description)
    params.append(track_id)
    cursor.execute(f"UPDATE investment_tracks SET {', '.join(sets)} WHERE id = %s", params)
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": track_id, "name": new_name, "description": new_description})


@api.route("/admin/tracks/merge", methods=["POST"])
def admin_merge_tracks():
    """Body: {source_id, target_id}. Moves all company_tracks rows from
    source into target, then deletes the source track. Target keeps its
    name and description."""
    body = request.get_json(force=True, silent=True) or {}
    src_id, tgt_id = body.get("source_id"), body.get("target_id")
    if not src_id or not tgt_id or src_id == tgt_id:
        return jsonify({"error": "need source_id and target_id, and they must differ"}), 400
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM investment_tracks WHERE id IN (%s, %s)", (src_id, tgt_id))
    if len({r[0] for r in cursor.fetchall()}) != 2:
        conn.close()
        return jsonify({"error": "one or both track IDs do not exist"}), 404
    # INSERT with ON CONFLICT drops duplicates gracefully.
    cursor.execute("""
        INSERT INTO company_tracks (track_id, company_id)
        SELECT %s, company_id FROM company_tracks WHERE track_id = %s
        ON CONFLICT DO NOTHING
    """, (tgt_id, src_id))
    moved = cursor.rowcount
    cursor.execute("DELETE FROM company_tracks WHERE track_id = %s", (src_id,))
    cursor.execute("DELETE FROM investment_tracks WHERE id = %s", (src_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "moved": moved, "deleted_track_id": src_id})


@api.route("/admin/tracks/<int:track_id>", methods=["DELETE"])
def admin_delete_track(track_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM company_tracks WHERE track_id = %s", (track_id,))
    unlinked = cursor.rowcount
    cursor.execute("DELETE FROM investment_tracks WHERE id = %s", (track_id,))
    if cursor.rowcount == 0:
        conn.rollback(); conn.close()
        return jsonify({"error": "track not found"}), 404
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "unlinked_companies": unlinked})


@api.route("/admin/relationships")
def admin_list_relationships():
    """List edges touching a given ticker. Query: ?ticker=NVDA&type=ownership"""
    ticker = (request.args.get("ticker") or "").upper().strip()
    if not ticker:
        return jsonify({"error": "ticker query param required"}), 400
    rel_type = request.args.get("type")
    conn = get_conn()
    cursor = conn.cursor()
    where = ["(source_ticker = %s OR target_ticker = %s)"]
    params = [ticker, ticker]
    if rel_type:
        where.append("relationship_type = %s"); params.append(rel_type)
    cursor.execute(f"""
        SELECT id, source_ticker, target_ticker, relationship_type, weight, metadata
        FROM relationships
        WHERE {' AND '.join(where)}
        ORDER BY relationship_type, source_ticker, target_ticker
    """, params)
    out = [
        {"id": r[0], "source": r[1], "target": r[2], "type": r[3],
         "weight": r[4], "metadata": r[5]}
        for r in cursor.fetchall()
    ]
    conn.close()
    return jsonify(out)


@api.route("/admin/relationships", methods=["POST"])
def admin_create_relationship():
    body = request.get_json(force=True, silent=True) or {}
    src = (body.get("source") or "").upper().strip()
    tgt = (body.get("target") or "").upper().strip()
    rel_type = (body.get("type") or "").lower().strip()
    if not src or not tgt or not rel_type:
        return jsonify({"error": "need source, target, type"}), 400
    if src == tgt:
        return jsonify({"error": "source and target must differ"}), 400
    if rel_type not in {"competitor", "supplier", "ownership"}:
        return jsonify({"error": f"type must be competitor|supplier|ownership, got {rel_type!r}"}), 400
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO relationships (source_ticker, target_ticker, relationship_type, weight)
            VALUES (%s, %s, %s, 1.0)
            ON CONFLICT (source_ticker, target_ticker, relationship_type) DO NOTHING
            RETURNING id
        """, (src, tgt, rel_type))
        row = cursor.fetchone()
        conn.commit()
    except psycopg2.errors.ForeignKeyViolation as e:
        conn.close()
        return jsonify({"error": f"ticker not in companies table: {e}"}), 400
    conn.close()
    if not row:
        return jsonify({"error": "edge already exists"}), 409
    return jsonify({"ok": True, "id": row[0], "source": src, "target": tgt, "type": rel_type})


@api.route("/admin/relationships/<int:rel_id>", methods=["DELETE"])
def admin_delete_relationship(rel_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM relationships WHERE id = %s", (rel_id,))
    if cursor.rowcount == 0:
        conn.rollback(); conn.close()
        return jsonify({"error": "edge not found"}), 404
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deleted_id": rel_id})


# ── /admin: track↔company membership ────────────────────────────────────

@api.route("/admin/tracks/<int:track_id>/companies")
def admin_track_companies(track_id):
    """Expand a track: list every company linked to it."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.ticker, c.name, c.sector, c.market_cap
        FROM companies c
        JOIN company_tracks ct ON ct.company_id = c.id
        WHERE ct.track_id = %s
        ORDER BY COALESCE(c.market_cap, 0) DESC, c.ticker
    """, (track_id,))
    rows = [
        {"ticker": r[0], "name": r[1], "sector": r[2], "market_cap": r[3]}
        for r in cursor.fetchall()
    ]
    conn.close()
    return jsonify(rows)


@api.route("/admin/tracks/<int:track_id>/companies", methods=["POST"])
def admin_track_add_company(track_id):
    """Body: {ticker: 'NVDA'}. Links ticker → track."""
    body = request.get_json(force=True, silent=True) or {}
    ticker = (body.get("ticker") or "").upper().strip()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM companies WHERE ticker = %s", (ticker,))
    company = cursor.fetchone()
    if not company:
        conn.close()
        return jsonify({"error": f"ticker {ticker!r} not in companies table"}), 404
    cursor.execute("SELECT id FROM investment_tracks WHERE id = %s", (track_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "track not found"}), 404
    cursor.execute("""
        INSERT INTO company_tracks (track_id, company_id)
        VALUES (%s, %s) ON CONFLICT DO NOTHING
    """, (track_id, company[0]))
    linked = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "ticker": ticker, "newly_linked": linked})


@api.route("/admin/tracks/<int:track_id>/companies/<ticker>", methods=["DELETE"])
def admin_track_remove_company(track_id, ticker):
    ticker = ticker.upper().strip()
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM companies WHERE ticker = %s", (ticker,))
    company = cursor.fetchone()
    if not company:
        conn.close()
        return jsonify({"error": f"ticker {ticker!r} not found"}), 404
    cursor.execute(
        "DELETE FROM company_tracks WHERE track_id = %s AND company_id = %s",
        (track_id, company[0]),
    )
    removed = cursor.rowcount
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "ticker": ticker, "removed_links": removed})


# ── /admin: company-side views ──────────────────────────────────────────

@api.route("/admin/companies")
def admin_list_companies():
    """Paginated company list with their track membership.
    Query: ?q=<search>&limit=N&offset=N&sort=ticker|name|market_cap"""
    q = (request.args.get("q") or "").strip()
    limit = min(request.args.get("limit", default=100, type=int), 10000)
    offset = request.args.get("offset", default=0, type=int)
    sort = request.args.get("sort", default="ticker")
    order_by = {
        "ticker": "c.ticker ASC",
        "name": "c.name ASC NULLS LAST, c.ticker ASC",
        "market_cap": "COALESCE(c.market_cap, 0) DESC, c.ticker",
    }.get(sort, "c.ticker ASC")
    conn = get_conn()
    cursor = conn.cursor()
    where, params = "", []
    if q:
        where = "WHERE c.ticker ILIKE %s OR c.name ILIKE %s"
        params = [f"%{q}%", f"%{q}%"]
    cursor.execute(f"""
        SELECT c.id, c.ticker, c.name, c.sector, c.market_cap,
               COALESCE(
                 array_agg(json_build_object('id', t.id, 'name', t.name))
                 FILTER (WHERE t.id IS NOT NULL),
                 ARRAY[]::json[]
               ) AS tracks
        FROM companies c
        LEFT JOIN company_tracks ct ON ct.company_id = c.id
        LEFT JOIN investment_tracks t ON t.id = ct.track_id
        {where}
        GROUP BY c.id, c.ticker, c.name, c.sector, c.market_cap
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    """, params + [limit, offset])
    rows = [
        {
            "id": r[0], "ticker": r[1], "name": r[2], "sector": r[3],
            "market_cap": r[4], "tracks": r[5],
        }
        for r in cursor.fetchall()
    ]
    cursor.execute(f"SELECT COUNT(*) FROM companies c {where}", params)
    total = cursor.fetchone()[0]
    conn.close()
    return jsonify({"companies": rows, "total": total, "limit": limit, "offset": offset})


# ── /admin: data-quality issue reports ──────────────────────────────────

@api.route("/admin/issues/orphan-companies")
def admin_orphan_companies():
    """Companies not linked to any investment track."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.ticker, c.name, c.sector, c.market_cap
        FROM companies c
        LEFT JOIN company_tracks ct ON ct.company_id = c.id
        WHERE ct.company_id IS NULL
        ORDER BY COALESCE(c.market_cap, 0) DESC, c.ticker
    """)
    rows = [
        {"id": r[0], "ticker": r[1], "name": r[2],
         "sector": r[3], "market_cap": r[4]}
        for r in cursor.fetchall()
    ]
    conn.close()
    return jsonify(rows)


@api.route("/admin/issues/multi-track-companies")
def admin_multi_track_companies():
    """Companies linked to more than one investment track (maybe-dupes)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.ticker, c.name,
               array_agg(json_build_object('id', t.id, 'name', t.name)
                         ORDER BY t.name) AS tracks,
               COUNT(*) AS n
        FROM companies c
        JOIN company_tracks ct ON ct.company_id = c.id
        JOIN investment_tracks t ON t.id = ct.track_id
        GROUP BY c.id, c.ticker, c.name
        HAVING COUNT(*) > 1
        ORDER BY n DESC, c.ticker
    """)
    rows = [
        {"ticker": r[0], "name": r[1], "tracks": r[2], "track_count": r[3]}
        for r in cursor.fetchall()
    ]
    conn.close()
    return jsonify(rows)


@api.route("/admin/issues/empty-tracks")
def admin_empty_tracks():
    """Tracks with zero companies — leftover from renames or source-data churn."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.name
        FROM investment_tracks t
        LEFT JOIN company_tracks ct ON ct.track_id = t.id
        WHERE ct.track_id IS NULL
        ORDER BY t.name
    """)
    rows = [{"id": r[0], "name": r[1]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


app.register_blueprint(api)


# Tiny root so an ops-level `curl /nexus/api/` returns something useful instead
# of a 404 when someone is sanity-checking the deployment.
@app.route(API_PREFIX or "/", strict_slashes=False)
def _root():
    return jsonify({
        "service": "nexus",
        "prefix": API_PREFIX,
        "endpoints": sorted({str(r) for r in app.url_map.iter_rules() if "nexus_api" in r.endpoint}),
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", "5001")))

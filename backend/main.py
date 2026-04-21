from flask import (
    Flask, Blueprint, Response, g, jsonify, request, stream_with_context,
)
from flask_cors import CORS
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
import psycopg2
import psycopg2.extras
from config import DATABASE_URL

try:
    from ai.pipeline.ticker_news_service import (
        get_ticker_news_summary_sync,
        get_track_news_payload_sync,
    )
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from ai.pipeline.ticker_news_service import (
        get_ticker_news_summary_sync,
        get_track_news_payload_sync,
    )

app = Flask(__name__)

# All routes live under this prefix so nginx can proxy /nexus/api/* → us while
# the client's existing app keeps owning the root. Override with
# NEXUS_API_PREFIX (e.g. "") if you want to mount at root in a bare deploy.
API_PREFIX = os.getenv("NEXUS_API_PREFIX", "/nexus/api")
api = Blueprint("nexus_api", __name__, url_prefix=API_PREFIX)


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


_pipeline_cache: dict[str, tuple[float, dict]] = {}
PIPELINE_CACHE_TTL = 15 * 60


def _cache_get(key: str):
    hit = _pipeline_cache.get(key)
    if hit and (time.time() - hit[0]) < PIPELINE_CACHE_TTL:
        return hit[1]
    return None


def _cache_set(key: str, value: dict):
    _pipeline_cache[key] = (time.time(), value)


def _should_cache_summary_payload(payload: dict) -> bool:
    status = payload.get("status")
    return status in (None, "ok", "no_news")


# ── Anthropic client init log only ───────────────────────────────────────
# The actual client lives in summarize.py. We just log presence here so
# startup output reflects whether /summary will work.
if os.getenv("ANTHROPIC_API_KEY"):
    print("[nexus] ANTHROPIC_API_KEY present — /summary enabled (Haiku 4.5)")
else:
    print("[nexus] ANTHROPIC_API_KEY unset — /summary will return empty")


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


def _lookup_company_name(ticker: str) -> str | None:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM companies WHERE ticker = %s", (ticker,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def _get_ticker_pipeline_payload(
    ticker: str,
    *,
    company_name: str | None = None,
    news_limit: int | None = None,
    include_summary: bool = True,
) -> dict:
    normalized_ticker = ticker.upper().strip()
    mode = "summary" if include_summary else "news"
    cache_key = f"ticker-pipeline:{normalized_ticker}:{mode}:{news_limit}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    payload = get_ticker_news_summary_sync(
        normalized_ticker,
        company_name=company_name,
        news_limit=news_limit,
        include_summary=include_summary,
    )
    if _should_cache_summary_payload(payload):
        _cache_set(cache_key, payload)
    return payload


def _get_track_pipeline_payload(
    *,
    track_name: str,
    constituents: list[dict[str, str]],
    per_company: int = 3,
    include_summary: bool = True,
) -> dict:
    mode = "summary" if include_summary else "news"
    constituent_key = ",".join(
        (c.get("ticker") or "").upper().strip() for c in constituents
    )
    cache_key = f"track-pipeline:{slugify(track_name)}:{mode}:{per_company}:{constituent_key}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    payload = get_track_news_payload_sync(
        constituents,
        track_name=track_name,
        per_company=per_company,
        include_summary=include_summary,
    )
    if _should_cache_summary_payload(payload):
        _cache_set(cache_key, payload)
    return payload


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
    company["investment_track"] = {"id": track[0], "name": track[1], "slug": slugify(track[1])} if track else None

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

    # Handle competitor relationships specially: generated from shared tracks
    if rel_type == "competitor":
        cursor.execute("""
            SELECT DISTINCT c2.ticker
            FROM company_tracks ct1
            JOIN company_tracks ct2 ON ct1.track_id = ct2.track_id
            JOIN companies c1 ON c1.id = ct1.company_id
            JOIN companies c2 ON c2.id = ct2.company_id
            WHERE c1.ticker = %s AND c2.ticker != %s
            LIMIT %s
        """, (ticker, ticker, limit))
        comp_tickers = [r[0] for r in cursor.fetchall()]
        neighbor_tickers = set(comp_tickers)
        
        # Generate synthetic edge rows for competitors
        edge_rows = [
            (None, ticker, ct, "competitor", 1.0, None)  # (id, source, target, type, weight, metadata)
            for ct in comp_tickers
        ]
    else:
        # Query database relationships for non-competitor types
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


from news_fetch import articles_hash


TRACK_TOP_CONSTITUENTS = 7


def _summary_cache_get(ticker: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT generated_at, headline, bullets, sources, model "
                "FROM news_summaries WHERE ticker = %s "
                "ORDER BY generated_at DESC LIMIT 1",
                (ticker,),
            )
            row = cur.fetchone()
    if not row:
        return None
    generated_at, headline, bullets, sources, model = row
    return {
        "headline": headline,
        "bullets": bullets,
        "sources": sources,
        "model": model,
        "generated_at": generated_at.isoformat() if generated_at else None,
    }


def _summary_cache_put(ticker: str, ahash: str, payload: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_summaries
                    (ticker, articles_hash, headline, bullets, sources, model)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, articles_hash) DO UPDATE
                   SET headline = EXCLUDED.headline,
                       bullets  = EXCLUDED.bullets,
                       sources  = EXCLUDED.sources,
                       model    = EXCLUDED.model,
                       generated_at = NOW()
                """,
                (
                    ticker,
                    ahash,
                    payload["headline"],
                    psycopg2.extras.Json(payload["bullets"]),
                    psycopg2.extras.Json(payload["sources"]),
                    payload["model"],
                ),
            )
        conn.commit()


def _pipeline_news_to_card(item: dict, idx: int) -> dict:
    ticker = (item.get("ticker") or "").upper().strip()
    tickers = item.get("tickers")
    if not tickers:
        tickers = [ticker] if ticker else []
    return {
        "index": idx,
        "title": item.get("title") or "",
        "link": item.get("link") or "",
        "publisher": item.get("publisher") or "",
        "published": item.get("published") or "",
        "summary": (item.get("summary") or "")[:600],
        "image": item.get("image") or "",
        "ticker": ticker,
        "tickers": tickers,
    }


def _source_cards_hash(sources: list[dict]) -> str:
    return articles_hash(
        [{"url": s.get("link") or ""} for s in sources if (s.get("link") or "").strip()]
    )


def _citation_source_indices(citations: list[dict]) -> list[int]:
    indices: list[int] = []
    for citation in citations or []:
        idx = citation.get("article_index")
        if isinstance(idx, int):
            one_based = idx + 1
            if one_based not in indices:
                indices.append(one_based)
    return indices


def _split_summary_text(text: str) -> tuple[str, list[str]]:
    raw = (text or "").strip()
    if not raw:
        return "", []

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    bullet_lines = [
        line[2:].strip()
        for line in lines
        if line.startswith("- ") or line.startswith("* ")
    ]
    prose_lines = [
        line for line in lines if not (line.startswith("- ") or line.startswith("* "))
    ]
    if bullet_lines:
        headline = " ".join(prose_lines).strip()
        if not headline:
            headline = bullet_lines[0]
            bullet_lines = bullet_lines[1:]
        return headline, bullet_lines

    import re

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
    if len(sentences) <= 2:
        return raw, []
    headline = " ".join(sentences[:2]).strip()
    trailing = " ".join(sentences[2:]).strip()
    return headline, ([trailing] if trailing else [])


def _tickers_for_source_indices(sources: list[dict], source_indices: list[int]) -> list[str]:
    tickers: list[str] = []
    for idx in source_indices:
        pos = idx - 1
        if pos < 0 or pos >= len(sources):
            continue
        source = sources[pos]
        candidates = source.get("tickers") or ([source.get("ticker")] if source.get("ticker") else [])
        for ticker in candidates:
            if ticker and ticker not in tickers:
                tickers.append(ticker)
    return tickers


def _legacy_payload_from_pipeline(service_payload: dict, *, track: bool) -> dict:
    sources = [
        _pipeline_news_to_card(item, idx)
        for idx, item in enumerate(service_payload.get("news") or [], 1)
    ]
    headline, bullet_texts = _split_summary_text(service_payload.get("summary") or "")
    source_indices = _citation_source_indices(service_payload.get("citations") or [])

    bullets = []
    for text in bullet_texts:
        bullet = {"text": text, "source_indices": source_indices}
        if track:
            tickers = _tickers_for_source_indices(sources, source_indices)
            if tickers:
                bullet["tickers"] = tickers
        bullets.append(bullet)

    return {
        "headline": headline,
        "bullets": bullets,
        "sources": sources,
        "model": service_payload.get("model"),
        "generated_at": service_payload.get("as_of"),
        "cached": bool(service_payload.get("cached")),
        "used_articles": len(sources),
    }


def _build_company_summary_payload(
    ticker: str,
    company_name: str | None,
    *,
    force: bool,
) -> dict:
    if not force:
        cached = _summary_cache_get(ticker)
        if cached:
            return {**cached, "cached": True, "used_articles": len(cached.get("sources") or [])}

    service_payload = _get_ticker_pipeline_payload(
        ticker,
        company_name=company_name,
        news_limit=8,
        include_summary=True,
    )
    result = _legacy_payload_from_pipeline(service_payload, track=False)
    result["cached"] = False
    if result.get("headline"):
        _summary_cache_put(ticker, _source_cards_hash(result["sources"]), result)
    return result


def _ensure_company_summary(ticker: str, company_name: str | None) -> dict:
    payload = _build_company_summary_payload(ticker, company_name, force=False)
    return {**payload, "articles": payload.get("sources") or []}


def _resolve_track(slug: str, *, company_limit: int = TRACK_TOP_CONSTITUENTS):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM investment_tracks")
    target = next(((tid, name) for tid, name in cursor.fetchall() if slugify(name) == slug), None)
    if target is None:
        conn.close()
        return None, None, []
    track_id, track_name = target
    cursor.execute(
        """
        SELECT c.ticker, c.name
        FROM companies c
        JOIN company_tracks ct ON ct.company_id = c.id
        WHERE ct.track_id = %s
        ORDER BY COALESCE(c.market_cap, 0) DESC LIMIT %s
        """,
        (track_id, company_limit),
    )
    constituents = [{"ticker": r[0], "name": r[1]} for r in cursor.fetchall()]
    conn.close()
    return track_id, track_name, constituents


@api.route("/companies/<ticker>/news")
def get_company_news(ticker):
    limit = request.args.get("limit", default=8, type=int)
    ticker = ticker.upper().strip()
    service_payload = _get_ticker_pipeline_payload(
        ticker,
        company_name=_lookup_company_name(ticker),
        news_limit=limit,
        include_summary=False,
    )
    items = service_payload.get("news") or []
    return jsonify([_pipeline_news_to_card(item, idx) for idx, item in enumerate(items, 1)])


@api.route("/tracks/<slug>/news")
def get_track_news(slug):
    top_n = request.args.get("companies", default=TRACK_TOP_CONSTITUENTS, type=int)
    per_company = request.args.get("per", default=3, type=int)
    _, track_name, constituents = _resolve_track(slug, company_limit=top_n)
    if track_name is None:
        return jsonify({"error": "Track not found"}), 404

    service_payload = _get_track_pipeline_payload(
        track_name=track_name,
        constituents=constituents,
        per_company=per_company,
        include_summary=False,
    )
    items = service_payload.get("news") or []
    return jsonify([_pipeline_news_to_card(item, idx) for idx, item in enumerate(items, 1)])


@api.route("/companies/<ticker>/summary", methods=["POST"])
def get_company_summary(ticker):
    ticker = ticker.upper().strip()
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    return jsonify(_build_company_summary_payload(ticker, _lookup_company_name(ticker), force=force))


def _stream_track_summary(slug: str, track_name: str, constituents: list[dict], force: bool):
    def emit(obj):
        return json.dumps(obj, default=str) + "\n"

    yield emit({"type": "noop", "pad": "x" * 4096})
    yield emit({
        "type": "meta",
        "track": track_name,
        "constituents": [c["ticker"] for c in constituents],
    })

    cache_key = f"track:{slug}"
    if not force:
        cached = _summary_cache_get(cache_key)
        if cached:
            yield emit({"type": "cached"})
            yield emit({"type": "done", "data": {
                **cached,
                "cached": True,
                "used_articles": len(cached.get("sources") or []),
            }})
            return

    for company in constituents:
        try:
            sub = _ensure_company_summary(company["ticker"], company.get("name"))
        except Exception as e:
            print(f"[track-summary] sub failed for {company['ticker']}: {e}")
            sub = {"headline": "", "articles": []}
        yield emit({
            "type": "company",
            "ticker": company["ticker"],
            "name": company.get("name") or company["ticker"],
            "headline": sub.get("headline") or "",
            "article_count": len(sub.get("articles") or []),
        })

    yield emit({"type": "synth", "pool_size": len(constituents)})

    try:
        service_payload = _get_track_pipeline_payload(
            track_name=track_name,
            constituents=constituents,
            per_company=3,
            include_summary=True,
        )
    except Exception as e:
        yield emit({"type": "error", "message": f"synth stage: {e}"})
        return

    payload = _legacy_payload_from_pipeline(service_payload, track=True)
    payload["cached"] = False
    if payload.get("headline"):
        _summary_cache_put(cache_key, _source_cards_hash(payload["sources"]), payload)
    yield emit({"type": "done", "data": payload})


@api.route("/tracks/<slug>/summary", methods=["POST"])
def get_track_summary(slug):
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    stream = request.args.get("stream", "").lower() in ("1", "true", "yes")
    _, track_name, constituents = _resolve_track(slug)
    if track_name is None:
        return jsonify({"error": "Track not found"}), 404

    if stream:
        return Response(
            stream_with_context(_stream_track_summary(slug, track_name, constituents, force)),
            mimetype="application/x-ndjson",
            headers={"X-Accel-Buffering": "no"},
        )

    final = None
    for line in _stream_track_summary(slug, track_name, constituents, force):
        try:
            evt = json.loads(line.strip())
        except Exception:
            continue
        if evt.get("type") == "done":
            final = evt.get("data")
    return jsonify(final or {
        "headline": "",
        "bullets": [],
        "sources": [],
        "model": None,
        "generated_at": None,
        "cached": False,
        "used_articles": 0,
    })


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

    # Live enrichment: change_pct + 30d sparkline (used by the table's
    # Δ 1D and Trend columns). Falls back silently if yfinance is down,
    # in which case the columns render as "—" instead of breaking.
    syms = tuple(sorted(c["ticker"] for c in companies if c.get("ticker")))
    mkt = _fetch_track_market_data(syms)
    for c in companies:
        md = mkt.get(c["ticker"])
        if md:
            if md.get("price") is not None:
                c["price"] = md["price"]
            c["change_pct"]  = md.get("change_pct")
            c["sparkline"]   = md.get("sparkline")
            c["week52_high"] = md.get("week52_high")
            c["week52_low"]  = md.get("week52_low")

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
        SELECT c.id, c.ticker, c.name, c.sector, c.market_cap, c.price,
               COALESCE(
                 array_agg(ct.track_id) FILTER (WHERE ct.track_id IS NOT NULL),
                 ARRAY[]::int[]
               ) AS track_ids
        FROM companies c
        LEFT JOIN company_tracks ct ON ct.company_id = c.id
        GROUP BY c.id
    """)
    nodes = []
    for cid, ticker, name, sector, market_cap, price, track_ids in cursor.fetchall():
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


# ── /admin: database backup ──────────────────────────────────────────────

@api.route("/admin/backup", methods=["POST"])
def admin_backup():
    """Dump the DB to JSON and upload to S3 under backups/."""
    import subprocess
    import sys
    from pathlib import Path as _Path

    upload = request.json.get("upload", False) if request.is_json else False

    script = _Path(__file__).parent / "db" / "db_to_json.py"
    cmd = [sys.executable, str(script)]
    if upload:
        cmd.append("--upload")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            return jsonify({"ok": False, "output": output}), 500
        return jsonify({"ok": True, "output": output})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "output": "timed out after 120s"}), 504


# ── /api/recent + /api/saved (per-user lists) ────────────────────────────
# Both keyed by Firebase uid. When NEXUS_REQUIRE_AUTH is off, these endpoints
# 204 / return [] so the frontend can call them safely in dev without crashing.

RECENT_LIMIT = 30  # capped per user
ALLOWED_ITEM_TYPES = {"company", "track"}


def _current_uid() -> str | None:
    user = getattr(g, "user", None) or {}
    return user.get("uid") or user.get("user_id")


def _validate_item(body: dict) -> tuple[str, str, str] | tuple[None, None, None]:
    item_type = (body.get("item_type") or "").strip().lower()
    item_id   = (body.get("item_id") or "").strip().lower()
    label     = (body.get("label") or "").strip()
    if item_type not in ALLOWED_ITEM_TYPES or not item_id or not label:
        return None, None, None
    return item_type, item_id, label[:200]


@api.route("/recent", methods=["GET"])
def list_recent():
    uid = _current_uid()
    if not uid:
        return jsonify([])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT item_type, item_id, label, viewed_at
                FROM user_recent_views
                WHERE firebase_uid = %s
                ORDER BY viewed_at DESC
                LIMIT %s
                """,
                (uid, RECENT_LIMIT),
            )
            rows = cur.fetchall()
    return jsonify([
        {"item_type": r[0], "item_id": r[1], "label": r[2],
         "viewed_at": r[3].isoformat() if r[3] else None}
        for r in rows
    ])


@api.route("/recent", methods=["POST"])
def upsert_recent():
    uid = _current_uid()
    if not uid:
        return jsonify({"ok": True, "skipped": "no auth"})
    body = request.get_json(force=True, silent=True) or {}
    item_type, item_id, label = _validate_item(body)
    if not item_type:
        return jsonify({"error": "need item_type ('company'|'track'), item_id, label"}), 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_recent_views (firebase_uid, item_type, item_id, label, viewed_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (firebase_uid, item_type, item_id)
                DO UPDATE SET viewed_at = NOW(), label = EXCLUDED.label
                """,
                (uid, item_type, item_id, label),
            )
            # Trim to RECENT_LIMIT — keep newest, drop overflow.
            cur.execute(
                """
                DELETE FROM user_recent_views
                WHERE firebase_uid = %s
                  AND (item_type, item_id) NOT IN (
                    SELECT item_type, item_id FROM user_recent_views
                    WHERE firebase_uid = %s
                    ORDER BY viewed_at DESC LIMIT %s
                  )
                """,
                (uid, uid, RECENT_LIMIT),
            )
        conn.commit()
    return jsonify({"ok": True})


@api.route("/recent", methods=["DELETE"])
def clear_recent():
    """DELETE /api/recent          → wipe all rows for the user
       DELETE /api/recent?item_type=track&item_id=ai-chips → wipe one"""
    uid = _current_uid()
    if not uid:
        return jsonify({"ok": True, "skipped": "no auth"})
    item_type = request.args.get("item_type")
    item_id   = request.args.get("item_id")
    with get_conn() as conn:
        with conn.cursor() as cur:
            if item_type and item_id:
                cur.execute(
                    "DELETE FROM user_recent_views WHERE firebase_uid = %s "
                    "AND item_type = %s AND item_id = %s",
                    (uid, item_type.lower(), item_id.lower()),
                )
            else:
                cur.execute(
                    "DELETE FROM user_recent_views WHERE firebase_uid = %s",
                    (uid,),
                )
            removed = cur.rowcount
        conn.commit()
    return jsonify({"ok": True, "removed": removed})


@api.route("/saved", methods=["GET"])
def list_saved():
    uid = _current_uid()
    if not uid:
        return jsonify([])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT item_type, item_id, label, saved_at
                FROM user_saved_items
                WHERE firebase_uid = %s
                ORDER BY saved_at DESC
                """,
                (uid,),
            )
            rows = cur.fetchall()
    return jsonify([
        {"item_type": r[0], "item_id": r[1], "label": r[2],
         "saved_at": r[3].isoformat() if r[3] else None}
        for r in rows
    ])


@api.route("/saved", methods=["POST"])
def upsert_saved():
    uid = _current_uid()
    if not uid:
        return jsonify({"ok": True, "skipped": "no auth"})
    body = request.get_json(force=True, silent=True) or {}
    item_type, item_id, label = _validate_item(body)
    if not item_type:
        return jsonify({"error": "need item_type ('company'|'track'), item_id, label"}), 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_saved_items (firebase_uid, item_type, item_id, label)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (firebase_uid, item_type, item_id)
                DO UPDATE SET label = EXCLUDED.label
                """,
                (uid, item_type, item_id, label),
            )
        conn.commit()
    return jsonify({"ok": True})


@api.route("/saved", methods=["DELETE"])
def remove_saved():
    uid = _current_uid()
    if not uid:
        return jsonify({"ok": True, "skipped": "no auth"})
    item_type = request.args.get("item_type")
    item_id   = request.args.get("item_id")
    if not item_type or not item_id:
        return jsonify({"error": "need item_type and item_id query params"}), 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_saved_items WHERE firebase_uid = %s "
                "AND item_type = %s AND item_id = %s",
                (uid, item_type.lower(), item_id.lower()),
            )
            removed = cur.rowcount
        conn.commit()
    return jsonify({"ok": True, "removed": removed})


# ── /api/movers/<kind> (Yahoo screener, cached) ──────────────────────────
# kind ∈ {day_gainers, day_losers, most_actives}
# Cached 5 min in-process; if Yahoo 429s we serve stale or 503 silently.
#
# 'trending' was removed because Yahoo's /v1/finance/trending/US endpoint
# rate-limits aggressively (429 within minutes of every cold start). The
# screener-backed kinds above are stable.

_MOVERS_TTL = 5 * 60
_movers_cache: dict[str, tuple[float, list[dict]]] = {}
_MOVER_KINDS = {"day_gainers", "day_losers", "most_actives"}


def _fetch_screener(kind: str) -> list[dict]:
    """Wrap yf.screen() — returns up to 25 rows in the shape above."""
    res = yf.screen(kind, count=25)
    quotes = (res or {}).get("quotes") or []
    return [
        {
            "ticker":     q.get("symbol"),
            "name":       q.get("shortName") or q.get("longName") or q.get("symbol"),
            "price":      q.get("regularMarketPrice"),
            "change_pct": q.get("regularMarketChangePercent"),
        }
        for q in quotes if q.get("symbol")
    ]


@api.route("/movers/<kind>")
def get_movers(kind):
    kind = kind.lower().strip()
    if kind not in _MOVER_KINDS:
        return jsonify({"error": f"unknown mover kind {kind!r}",
                        "allowed": sorted(_MOVER_KINDS)}), 400

    hit = _movers_cache.get(kind)
    if hit and (time.time() - hit[0]) < _MOVERS_TTL:
        return jsonify({"kind": kind, "cached": True, "items": hit[1]})

    try:
        items = _fetch_screener(kind)
    except Exception as e:
        # Serve stale on failure if we have it; otherwise 503 quietly so
        # the frontend can hide the section.
        if hit:
            return jsonify({"kind": kind, "cached": True, "stale": True, "items": hit[1]})
        print(f"[nexus] movers/{kind} fetch failed: {e}")
        return jsonify({"error": "movers unavailable", "items": []}), 503

    _movers_cache[kind] = (time.time(), items)
    return jsonify({"kind": kind, "cached": False, "items": items})


# ── /api/quotes — batched live quotes (price + change_pct) ───────────────
# Frontend lazy-fetches this for the tickers visible in the sidebar so
# every company row gets a current price + day change. Per-symbol cached
# 5min in-process to keep yfinance traffic cheap.

_QUOTES_TTL = 5 * 60
_quotes_cache: dict[str, tuple[float, dict]] = {}


def _fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """Batched 2-day download → today's price and day-over-day pct change.
    yfinance.download with multiple tickers returns a multi-index DataFrame
    (top-level = field, second = ticker); with one ticker it's flat."""
    if not symbols:
        return {}
    df = yf.download(
        tickers=symbols,
        period="2d",
        interval="1d",
        group_by="ticker",
        progress=False,
        threads=True,
        auto_adjust=False,
    )
    out: dict[str, dict] = {}
    for s in symbols:
        try:
            if len(symbols) == 1:
                rows = df
            elif s in df.columns.get_level_values(0):
                rows = df[s]
            else:
                continue
            closes = rows["Close"].dropna()
            if closes.empty:
                continue
            price = float(closes.iloc[-1])
            change_pct = None
            if len(closes) >= 2:
                prev = float(closes.iloc[-2])
                if prev:
                    change_pct = (price - prev) / prev * 100
            out[s] = {"price": price, "change_pct": change_pct}
        except Exception:
            continue
    return out


# ── Track-page market data: live price + change_pct + 30d sparkline ─────
# Used by /tracks/<slug> to populate the Δ 1D and Trend columns on the
# investment-track table. Cached 10min keyed by the sorted ticker tuple
# so revisits to the same track are instant.

_TRACK_MKT_TTL = 10 * 60
_track_mkt_cache: dict[tuple, tuple[float, dict]] = {}


def _fetch_track_market_data(tickers: tuple[str, ...]) -> dict[str, dict]:
    if not tickers:
        return {}
    hit = _track_mkt_cache.get(tickers)
    if hit and (time.time() - hit[0]) < _TRACK_MKT_TTL:
        return hit[1]
    out: dict[str, dict] = {}
    try:
        # 1y for the 52w range; 30d sparkline + 1d change derive from the same frame.
        df = yf.download(
            tickers=list(tickers),
            period="1y",
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=True,
            auto_adjust=False,
        )
    except Exception as e:
        print(f"[nexus] track market data fetch failed: {e}")
        return {}
    for s in tickers:
        try:
            if len(tickers) == 1:
                rows = df
            elif s in df.columns.get_level_values(0):
                rows = df[s]
            else:
                continue
            closes = rows["Close"].dropna()
            if closes.empty:
                continue
            price = float(closes.iloc[-1])
            change_pct = None
            if len(closes) >= 2:
                prev = float(closes.iloc[-2])
                if prev:
                    change_pct = (price - prev) / prev * 100
            sparkline   = [float(v) for v in closes.tolist()[-30:]]
            week52_high = float(closes.max())
            week52_low  = float(closes.min())
            out[s] = {
                "price":       price,
                "change_pct":  change_pct,
                "sparkline":   sparkline,
                "week52_high": week52_high,
                "week52_low":  week52_low,
            }
        except Exception:
            continue
    _track_mkt_cache[tickers] = (time.time(), out)
    return out


@api.route("/quotes")
def get_quotes():
    raw = request.args.get("tickers", "")
    symbols = sorted({s.strip().upper() for s in raw.split(",") if s.strip()})
    if not symbols:
        return jsonify({})
    # Cap to a sane batch size — frontend chunks larger requests if needed.
    symbols = symbols[:200]

    now = time.time()
    out: dict[str, dict] = {}
    missing: list[str] = []
    for s in symbols:
        hit = _quotes_cache.get(s)
        if hit and (now - hit[0]) < _QUOTES_TTL:
            out[s] = hit[1]
        else:
            missing.append(s)

    if missing:
        try:
            fresh = _fetch_quotes(missing)
            for s, q in fresh.items():
                _quotes_cache[s] = (now, q)
                out[s] = q
        except Exception as e:
            print(f"[nexus] quotes fetch failed for {missing[:5]}…: {e}")

    return jsonify(out)


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

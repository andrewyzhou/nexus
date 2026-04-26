"""
summarize.py — single-call Claude summarizer with tool-use forced output.

Returns a deterministic schema:
    {
      "headline": "...",            # exactly 2 sentences, neutral analytical tone
      "bullets":  [{ "text": "...", "source_indices": [int, ...] }, ...],
      "sources":  [{ "index": 1, "title": "...", "url": "...",
                     "publisher": "...", "published": "...", "image": "..." }, ...],
      "model":    "claude-haiku-4-5-20251001"
    }

Article indices are 1-based and stable: bullet.source_indices match
sources[].index, which the frontend uses to scroll to the corresponding
news card on click (same scroll/highlight behavior as before).
"""
from __future__ import annotations

import os
from typing import Any


_anthropic = None


def _client():
    global _anthropic
    if _anthropic is not None:
        return _anthropic
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        _anthropic = anthropic.Anthropic(api_key=key)
    except Exception as e:
        print(f"[summarize] anthropic init failed: {e}")
        _anthropic = None
    return _anthropic


MODEL = "claude-haiku-4-5-20251001"

TOOL = {
    "name": "render_news_summary",
    "description": (
        "Render a structured news summary. "
        "Always emit exactly 2 sentences in `headline` and 2-5 distinct bullets, "
        "each citing 1-3 source indices."
    ),
    "input_schema": {
        "type": "object",
        "required": ["headline", "bullets"],
        "properties": {
            "headline": {
                "type": "string",
                "description": (
                    "EXACTLY two sentences. "
                    "Sentence 1: subject is the company. State the key event "
                    "or performance with a specific metric (% move, $ revenue, "
                    "EPS, dates). "
                    "Sentence 2: explain the primary driver "
                    "(earnings, AI demand, analyst action, product launch, "
                    "regulatory event, macro catalyst, etc.). "
                    "Neutral, analytical tone. No hype words "
                    "(\"soaring\", \"skyrocket\", \"stunning\"). "
                    "No filler transitions (\"however\", \"meanwhile\")."
                ),
            },
            "bullets": {
                "type": "array",
                "minItems": 2,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "required": ["text", "source_indices"],
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": (
                                "One concrete development not already stated "
                                "in the headline. Specific. No redundancy with "
                                "other bullets."
                            ),
                        },
                        "source_indices": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 3,
                            "items": {"type": "integer", "minimum": 1},
                            "description": (
                                "1-based indices of the articles directly "
                                "supporting this bullet."
                            ),
                        },
                    },
                },
            },
        },
    },
}


SYSTEM_PROMPT = (
    "You are a financial news editor producing analyst-style briefs.\n\n"
    "Given numbered articles for a company:\n"
    "1. headline: EXACTLY 2 sentences. "
    "Sentence 1 = what happened (event/performance + specific metric). "
    "Sentence 2 = why it happened (driver/catalyst). "
    "Neutral, analytical tone. No hype, no filler.\n"
    "2. bullets: 2-5 distinct, non-redundant developments NOT already covered "
    "in the headline. Each cites 1-3 source indices that directly support it. "
    "Do not invent facts.\n\n"
    "Formatting: Do not use markdown formatting other than you MAY use "
    "**bold** for the most important phrases and/or numbers per "
    "sentence/bullet (a metric, ticker, name), and *italics* for "
    "product/program names or quoted phrases.\n\n"
    "Skip articles that are generic market commentary, retirement/personal "
    "finance fluff, or only mention the company in passing. "
    "Always call the tool — never produce a free-text response."
)


def _build_user_message(ticker: str, company_name: str, articles: list[dict]) -> str:
    """Numbered article block. Use body when available, else blurb."""
    lines: list[str] = [
        f"Articles about {company_name} ({ticker}):",
        "",
    ]
    for i, a in enumerate(articles, 1):
        text = a.get("body") or a.get("blurb") or ""
        text = text.strip()
        if not text:
            continue
        lines.append(f"[{i}] {a.get('publisher') or 'unknown'} · "
                     f"{a.get('published') or ''}")
        lines.append(f"Title: {a.get('title','')}")
        lines.append(f"Content: {text}")
        lines.append("")
    return "\n".join(lines)


def summarize_news(
    ticker: str,
    company_name: str,
    articles: list[dict],
) -> dict[str, Any]:
    """Returns the rendering payload for the frontend.
    Articles list order is preserved — its index drives the citation links."""
    client = _client()

    sources = [
        {
            "index": i,
            "title": a.get("title") or "",
            "url": a.get("url") or "",
            "publisher": a.get("publisher") or "",
            "published": a.get("published") or "",
            "image": a.get("image") or "",
        }
        for i, a in enumerate(articles, 1)
    ]

    if not client or not articles:
        return {
            "headline": "",
            "bullets": [],
            "sources": sources,
            "model": MODEL,
        }

    user_msg = _build_user_message(ticker, company_name or ticker, articles)

    msg = client.messages.create(
        model=MODEL,
        max_tokens=900,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "render_news_summary"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    headline, bullets = "", []
    for block in msg.content:
        btype = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if btype != "tool_use":
            continue
        inp = getattr(block, "input", None) or (
            block.get("input") if isinstance(block, dict) else {}
        )
        headline = (inp or {}).get("headline", "") or ""
        raw_bullets = (inp or {}).get("bullets", []) or []
        for b in raw_bullets:
            if not isinstance(b, dict):
                continue
            text = b.get("text", "") or ""
            indices = [
                int(x) for x in (b.get("source_indices") or [])
                if isinstance(x, (int, float)) and 1 <= int(x) <= len(articles)
            ]
            if text and indices:
                bullets.append({"text": text, "source_indices": indices})

    try:
        usage = msg.usage
        in_tok = getattr(usage, "input_tokens", 0)
        out_tok = getattr(usage, "output_tokens", 0)
        cost = (in_tok * 1 + out_tok * 5) / 1_000_000
        print(f"[summary] ticker={ticker} articles={len(articles)} "
              f"input={in_tok} output={out_tok} cost=${cost:.4f}")
    except Exception:
        pass

    return {
        "headline": headline.strip(),
        "bullets": bullets,
        "sources": sources,
        "model": MODEL,
    }


# ─────────────────────────────────────────────────────────────────────────
# Track-level summary
#
# Tracks group 2-7 companies under a theme. We pass:
#   1. A per-constituent SCAFFOLD line (already-cached company headlines,
#      free at lookup time) so Claude has a structured starting picture
#      and won't fixate on the most-articled mega-cap.
#   2. Full numbered articles tagged with which constituent they're about.
# Bullets carry a `tickers` array (1-3 entries) so the UI can render a
# pill prefix and the user can see at a glance which companies a bullet
# concerns.
# ─────────────────────────────────────────────────────────────────────────

TRACK_TOOL = {
    "name": "render_track_summary",
    "description": (
        "Render a structured news summary for an investment track. "
        "Always emit exactly 2 sentences in `headline` (about the GROUP, "
        "not any one company) and 2-7 bullets, each tagged with 1-3 "
        "tickers and citing 1-3 source indices."
    ),
    "input_schema": {
        "type": "object",
        "required": ["headline", "bullets"],
        "properties": {
            "headline": {
                "type": "string",
                "description": (
                    "EXACTLY two sentences about the track as a whole. "
                    "Sentence 1: dominant cross-cutting development across "
                    "the constituents (cite specific tickers / numbers). "
                    "Sentence 2: the primary driver — a shared catalyst, "
                    "or a contrast (one outlier vs. the group). "
                    "Neutral analytical tone, no filler."
                ),
            },
            "bullets": {
                "type": "array",
                "minItems": 2,
                "maxItems": 7,
                "items": {
                    "type": "object",
                    "required": ["tickers", "text", "source_indices"],
                    "properties": {
                        "tickers": {
                            "type": "array",
                            "minItems": 1, "maxItems": 3,
                            "items": {"type": "string"},
                            "description": (
                                "1-3 ticker symbols this bullet is about. "
                                "Use multiple tickers ONLY when the "
                                "development genuinely involves all of "
                                "them (a shared regulatory ruling, a "
                                "merger between constituents, etc)."
                            ),
                        },
                        "text": {"type": "string"},
                        "source_indices": {
                            "type": "array",
                            "minItems": 1, "maxItems": 3,
                            "items": {"type": "integer", "minimum": 1},
                        },
                    },
                },
            },
        },
    },
}


TRACK_SYSTEM_PROMPT = (
    "You are a financial news editor producing analyst-style briefs for "
    "an investment track — a curated group of 2-7 public companies "
    "sharing a theme.\n\n"
    "Given a track name, its constituents, a per-constituent scaffold "
    "(use as a starting picture; verify and elaborate against the "
    "evidence), and numbered articles tagged with which constituent "
    "each is about:\n\n"
    "1. headline: EXACTLY 2 sentences about the GROUP, not any single "
    "company. Sentence 1 = the dominant cross-cutting development "
    "(reference specific tickers / numbers, e.g. 'Four of the five "
    "constituents posted Q1 earnings beats, lifting the group ~12% on "
    "the week'). Sentence 2 = the primary driver — a shared catalyst "
    "(AI capex, rate cycle, regulatory action) or a contrast (one "
    "outlier dragging vs. the group). Neutral analytical tone. No "
    "'however'/'meanwhile' filler.\n\n"
    "2. bullets: 2-7 distinct, non-redundant developments. Each bullet "
    "is { tickers, text, source_indices }:\n"
    "   - tickers: 1-3 ticker symbols. MOST bullets are 1 ticker. Use "
    "multiple tickers ONLY when the development genuinely covers all "
    "of them (a shared regulator action, a deal between constituents).\n"
    "   - text: lead with the substance. Specifics — numbers, dates, "
    "names. Do NOT repeat anything in the headline.\n"
    "   - source_indices: 1-3 articles directly supporting it.\n"
    "A constituent can appear in multiple bullets if genuinely newsy. "
    "A constituent with no meaningful news must NOT appear at all — "
    "skip rather than pad.\n\n"
    "Formatting: Do not use markdown formatting other than you MAY use "
    "**bold** for the most important phrases and/or numbers per "
    "sentence/bullet (a metric, ticker, name), and *italics* for "
    "product/program names or quoted phrases.\n\n"
    "Skip articles that are generic market commentary or only mention "
    "a constituent in passing. Always call the tool — never produce a "
    "free-text response."
)


def _build_track_user_message(
    track_name: str,
    constituents: list[dict],
    scaffold: dict[str, str],
    articles: list[dict],
) -> str:
    lines: list[str] = [
        f"Investment track: {track_name}",
        "Constituents: " + ", ".join(
            f"{c['ticker']} ({c.get('name') or c['ticker']})" for c in constituents
        ),
        "",
        "Per-constituent quick view (use as a starting picture; verify and",
        "elaborate against the articles below):",
        "",
    ]
    for c in constituents:
        head = (scaffold.get(c["ticker"]) or "").strip() or "No material news."
        # Compress to one line
        head = " ".join(head.split())
        lines.append(f"  {c['ticker']} — {head}")
    lines.extend(["", "Source articles (cite by [N]):", ""])
    for i, a in enumerate(articles, 1):
        text = (a.get("body") or a.get("blurb") or "").strip()
        if not text:
            continue
        lines.append(f"[{i}] {a.get('ticker','')} · {a.get('publisher') or 'unknown'} · "
                     f"{a.get('published') or ''}")
        lines.append(f"Title: {a.get('title','')}")
        lines.append(f"Content: {text}")
        lines.append("")
    return "\n".join(lines)


def summarize_track_news(
    track_name: str,
    constituents: list[dict],
    scaffold: dict[str, str],
    articles: list[dict],
) -> dict[str, Any]:
    """Same return shape as `summarize_news`, with one extra field per
    bullet: `tickers: [str, ...]`."""
    client = _client()

    valid_tickers = {c["ticker"] for c in constituents}
    sources = [
        {
            "index": i,
            "title": a.get("title") or "",
            "url": a.get("url") or "",
            "publisher": a.get("publisher") or "",
            "published": a.get("published") or "",
            "image": a.get("image") or "",
            "ticker": a.get("ticker") or "",
        }
        for i, a in enumerate(articles, 1)
    ]

    if not client or not articles:
        return {
            "headline": "",
            "bullets": [],
            "sources": sources,
            "model": MODEL,
        }

    user_msg = _build_track_user_message(track_name, constituents, scaffold, articles)

    msg = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        tools=[TRACK_TOOL],
        tool_choice={"type": "tool", "name": "render_track_summary"},
        system=TRACK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    headline, bullets = "", []
    for block in msg.content:
        btype = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if btype != "tool_use":
            continue
        inp = getattr(block, "input", None) or (
            block.get("input") if isinstance(block, dict) else {}
        )
        headline = (inp or {}).get("headline", "") or ""
        for b in (inp or {}).get("bullets", []) or []:
            if not isinstance(b, dict):
                continue
            text = b.get("text", "") or ""
            indices = [
                int(x) for x in (b.get("source_indices") or [])
                if isinstance(x, (int, float)) and 1 <= int(x) <= len(articles)
            ]
            tickers = [
                t.upper() for t in (b.get("tickers") or [])
                if isinstance(t, str) and t.upper() in valid_tickers
            ][:3]
            if text and indices and tickers:
                bullets.append({
                    "tickers": tickers,
                    "text": text,
                    "source_indices": indices,
                })

    try:
        usage = msg.usage
        in_tok = getattr(usage, "input_tokens", 0)
        out_tok = getattr(usage, "output_tokens", 0)
        cost = (in_tok * 1 + out_tok * 5) / 1_000_000
        print(f"[track-summary] track={track_name!r} constituents={len(constituents)} "
              f"articles={len(articles)} input={in_tok} output={out_tok} "
              f"cost=${cost:.4f}")
    except Exception:
        pass

    return {
        "headline": headline.strip(),
        "bullets": bullets,
        "sources": sources,
        "model": MODEL,
    }

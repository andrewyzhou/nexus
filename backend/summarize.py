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
    "Formatting: you MAY use lightweight markdown — **bold** for the single "
    "most important phrase or number per sentence/bullet (a metric, ticker, "
    "name), and *italics* for product/program names or quoted phrases. "
    "Use sparingly — at most one bold span per sentence and one per bullet. "
    "Do not use headings, links, code, or lists. Plain prose is fine when "
    "nothing stands out.\n\n"
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

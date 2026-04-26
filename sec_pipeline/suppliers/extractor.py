"""
Supplier extraction pipeline — offline LLM pass over cached SEC sections.

Reads from raw_sections/<TICKER>_sections.txt (output of fetcher.py).
Writes to suppliers.json.

Usage:
    python extractor.py
    python extractor.py --llm regex
    python extractor.py --tickers AAPL,MSFT,NVDA
"""

import json
import re
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Ollama
try:
    import ollama as _ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# Anthropic
try:
    import anthropic
    anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Gemini
try:
    from google import genai
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Gliner (https://huggingface.co/gliner-community/gliner_large-v2.5)
try:
    from gliner import GLiNER
    gliner_model = GLiNER.from_pretrained("gliner-community/gliner_large-v2.5", load_tokenizer=True)
    GLINER_AVAILABLE = True
except ImportError:
    GLINER_AVAILABLE = False

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR         = Path(__file__).parent
TICKERS_FILE     = BASE_DIR.parent / "suppliers" / "tickers.txt"
OUTPUT           = BASE_DIR / "pipeline" / "suppliers.json"
ERROR_LOG        = BASE_DIR.parent / "suppliers" / "scrape_errors.txt"
RAW_SECTIONS_DIR = BASE_DIR.parent / "suppliers" / "raw_sections"

# ─── LLM config ───────────────────────────────────────────────────────────────

LLM_MODEL = "llama3.2"
MAX_CHARS  = 8000

SYSTEM_PROMPT = (
    "You are a financial document parser specializing in supply chain analysis. "
    "You extract direct supplier and manufacturing partner names from SEC 10-K "
    "filing text. You respond ONLY in strict JSON format. "
    "You NEVER hallucinate or invent data."
)

USER_PROMPT_TEMPLATE = """Read the following SEC 10-K filing section and extract all
direct suppliers and manufacturing partners explicitly named in the text.

Rules:
- Return ONLY a valid JSON array of supplier name strings
- INCLUDE entities explicitly named as: supplier, vendor, manufacturer,
  manufacturing partner, or provider of physical goods/components/raw materials
- EXCLUDE: competitors, customers, investors, regulators, auditors, law firms,
  consultants, logistics companies (unless named as manufacturers), the filing
  company's own subsidiaries, vague references like "certain suppliers"
- Use the stock ticker if known with certainty (e.g. "ACME" for Acme
  Corporation), otherwise use the exact company name
- If zero qualifying suppliers found, return ["NONE"]
- Do NOT hallucinate — ONLY list entities explicitly named in the text

FILING COMPANY: {ticker}
SECTION: {section_name}

Text:
{text}

Respond with ONLY the JSON array, nothing else:"""

GLINER_LABELS = [
    "supplier",
    "manufacturing partner",
    "vendor",
    "contract manufacturer",
    "raw material supplier",
    "component supplier",
]

SUPPLIER_CONTEXT_KEYWORDS = [
    "supplier", "supplies", "supplied by",
    "manufacturer", "manufactured by", "contract manufacturer",
    "vendor", "procured from", "sourced from",
    "outsourcing partner", "manufacturing partner",
    "raw material", "component",
]


# ─── Error logging ────────────────────────────────────────────────────────────

def log_error(ticker, source, message):
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(f"{ticker} | {source} | {message}\n")


# ─── Raw sections parsing ─────────────────────────────────────────────────────

def load_sections(ticker):
    """Parse raw_sections/<ticker>_sections.txt into {section_name: text}."""
    path = RAW_SECTIONS_DIR / f"{ticker}_sections.txt"
    if not path.exists() or path.stat().st_size <= 10:
        return {}

    sections = {}
    current = None
    lines = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            if current:
                sections[current] = "\n".join(lines).strip()
            current = line.strip("- ").lower()
            lines = []
        else:
            lines.append(line)
    if current:
        sections[current] = "\n".join(lines).strip()

    return {k: v for k, v in sections.items() if v and v != "[NOT FOUND]"}


# ─── LLM extraction ───────────────────────────────────────────────────────────

def extract_suppliers_llm(ticker, section_name, text, llm_mode):
    if not text or len(text.strip()) < 20:
        return []

    chunk = text[:MAX_CHARS]

    if llm_mode == "regex":
        return extract_suppliers_regex(ticker, chunk)

    if llm_mode == "ollama":
        return _extract_ollama(ticker, section_name, chunk)
    
    if llm_mode == "claude":
        return _extract_claude(ticker, section_name, chunk)
    
    if llm_mode == "gemini":
        return _extract_gemini(ticker, section_name, chunk)

    if llm_mode == "gliner":
        return _extract_gliner(ticker, section_name, chunk)

    return extract_suppliers_regex(ticker, chunk)


def _extract_ollama(ticker, section_name, chunk):
    prompt = USER_PROMPT_TEMPLATE.format(
        ticker=ticker, section_name=section_name, text=chunk,
    )
    if OLLAMA_AVAILABLE:
        try:
            resp = _ollama.chat(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                format="json",
            )
            return _parse_llm_response(resp["message"]["content"])
        except Exception as e:
            log_error(ticker, "ollama", str(e))
            return extract_suppliers_regex(ticker, chunk)
    else:
        return extract_suppliers_regex(ticker, chunk)

def _extract_claude(ticker, section_name, chunk):
    if not ANTHROPIC_AVAILABLE:
        return extract_suppliers_regex(ticker, chunk)
    try:
        message = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    ticker=ticker,
                    section_name=section_name,
                    text=chunk,
                )
            }]
        )
        text_block = next((b for b in message.content if b.type == "text"), None)
        return _parse_llm_response(text_block.text if text_block else "")
    except Exception as e:
        log_error(ticker, "claude", str(e))
        return extract_suppliers_regex(ticker, chunk)


def _extract_gemini(ticker, section_name, chunk):
    if not GEMINI_AVAILABLE:
        return extract_suppliers_regex(ticker, chunk)
    try:
        response = gemini_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=USER_PROMPT_TEMPLATE.format(
                ticker=ticker,
                section_name=section_name,
                text=chunk,
            )
        )
        return _parse_llm_response(response.text)
    except Exception as e:
        log_error(ticker, "gemini", str(e))
        return extract_suppliers_regex(ticker, chunk)

def _extract_gliner(ticker, section_name, chunk):
    if not GLINER_AVAILABLE:
        return extract_suppliers_regex(ticker, chunk)
    
    try:
        entities = gliner_model.predict_entities(
            chunk,
            GLINER_LABELS,
            threshold=0.5,
        )
        
        suppliers = []
        for entity in entities:
            name  = entity["text"].strip()
            score = entity["score"]
            
            if score < 0.5:
                continue
            if len(name) < 3:
                continue
            if ticker.upper() in name.upper().split():
                continue
            
            start = max(0, entity["start"] - 150)
            end = min(len(chunk), entity["end"] + 150)
            context = chunk[start:end].lower()
            
            if any(kw in context for kw in SUPPLIER_CONTEXT_KEYWORDS):
                suppliers.append(name)
        
        return _dedup(suppliers) if suppliers else []
    
    except Exception as e:
        log_error(ticker, "gliner", str(e))
        return extract_suppliers_regex(ticker, chunk)


def _parse_llm_response(text):
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            for key in ["suppliers", "names", "results", "data"]:
                if key in parsed and isinstance(parsed[key], list):
                    return [str(x) for x in parsed[key] if x and str(x) != "NONE"]
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x and str(x) != "NONE"]
    except json.JSONDecodeError:
        pass

    match = re.search(r'\[.*?\]', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(x) for x in result if x and str(x) != "NONE"]
        except json.JSONDecodeError:
            pass
    return []


# ─── Regex fallback ───────────────────────────────────────────────────────────

_SUPPLIER_SIGNALS = re.compile(
    r'\b(?:supplier|vendor|manufacturer|manufactur(?:er|ing)\s+partner|'
    r'contract\s+manufacturer|OEM|sole[- ]source|single[- ]source|'
    r'sourced?\s+from|purchased?\s+from|procured?\s+from|'
    r'supplied?\s+by|produced?\s+by|fabricated?\s+by|assembled?\s+by|'
    r'raw\s+material\s+(?:supplier|provider)|'
    r'component\s+(?:supplier|provider|manufacturer))\b',
    re.IGNORECASE,
)

_COMPANY_NAME_RE = re.compile(
    r'\b([A-Z][A-Za-z0-9&\'\. ]{1,55}'
    r'(?:LLC|Inc\.?|Ltd\.?|Corp\.?|L\.P\.|S\.A\.|GmbH|B\.V\.|Pte\.?|'
    r'Limited|N\.A\.|plc|SE|AG|Co\.|Group|Holdings?|Technologies?|'
    r'Systems?|Solutions?|Industries|Manufacturing|Semiconductor|'
    r'Electronics?|Materials?))'
    r'\b'
)

_GENERIC_WORDS = {
    "company", "corporation", "registrant", "the", "such", "other",
    "certain", "various", "third", "party", "vendor", "supplier",
    "manufacturer", "customer", "government", "commission", "sec",
}


def extract_suppliers_regex(ticker, text):
    if not text:
        return []
    suppliers = []
    sentences = re.split(r'(?<=[.!?])\s+|\n', text)
    for sentence in sentences:
        if not _SUPPLIER_SIGNALS.search(sentence):
            continue
        for m in _COMPANY_NAME_RE.finditer(sentence):
            name = m.group(1).strip()
            if name.lower() in _GENERIC_WORDS:
                continue
            if ticker.upper() in name.upper().split():
                continue
            if len(name) < 3:
                continue
            suppliers.append(name)
    return _dedup(suppliers)


# ─── Dedup ────────────────────────────────────────────────────────────────────

def _dedup(names):
    seen = set()
    unique = []
    for n in names:
        key = n.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(n.strip())
    return unique


# ─── Per-ticker processing ────────────────────────────────────────────────────

def process_ticker(ticker, llm_mode):
    sections = load_sections(ticker)
    if not sections:
        return []

    suppliers = []
    for section_name, section_text in sections.items():
        found = extract_suppliers_llm(ticker, section_name, section_text, llm_mode)
        suppliers.extend(found)

    return _dedup(suppliers)


# ─── Persistence ──────────────────────────────────────────────────────────────

def _save(results, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("RAW_SECTIONS_DIR:", RAW_SECTIONS_DIR)
    print("Exists:", RAW_SECTIONS_DIR.exists())
    print("Files:", list(RAW_SECTIONS_DIR.glob("*_sections.txt"))[:3])

    parser = argparse.ArgumentParser(
        description="Extract suppliers from cached SEC sections (run fetcher.py first)"
    )
    parser.add_argument("--llm", choices=["ollama", "regex", "claude", "gemini", "gliner"], default="ollama")
    parser.add_argument("--tickers", default="")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = [t.strip().upper() for t in TICKERS_FILE.read_text().splitlines() if t.strip()]

    ERROR_LOG.write_text("")

    # test_ticker = "AAPL"  # or any ticker you know has a sections file
    # sections = load_sections(test_ticker)
    # print("Sections found:", list(sections.keys()))
    # print("Section lengths:", {k: len(v) for k, v in sections.items()})

    # if sections:
    #     first_section = list(sections.values())[0]
    #     print("First 200 chars:", first_section[:200])

    output_path = Path(args.output)
    if output_path.exists():
        results = json.loads(output_path.read_text())
        if not isinstance(results, dict):
            results = {}
    else:
        results = {}

    already_done = set(results.keys())
    remaining = [t for t in tickers if t not in already_done]

    avail = "available" if OLLAMA_AVAILABLE else "NOT available — using regex"
    method = f"ollama ({LLM_MODEL}) [{avail}]" if args.llm == "ollama" else "regex"

    print(f"Supplier extraction: {len(remaining)} tickers ({len(already_done)} already done)")
    print(f"  Method : {method}")
    print(f"  Output : {args.output}")
    print()

    for i, ticker in enumerate(remaining):
        try:
            suppliers = process_ticker(ticker, args.llm)
        except Exception as e:
            log_error(ticker, "main", str(e))
            suppliers = []

        results[ticker] = {"suppliers": suppliers}
        print(f"  [{i+1}/{len(remaining)}] {ticker}: {len(suppliers)} suppliers")

        if (i + 1) % 10 == 0:
            _save(results, args.output)

    results = dict(sorted(results.items()))
    _save(results, args.output)

    with_sups  = sum(1 for v in results.values() if v["suppliers"])
    total_sups = sum(len(v["suppliers"]) for v in results.values())
    errors     = ERROR_LOG.read_text().count("\n") if ERROR_LOG.exists() else 0

    print(f"\nDone!")
    print(f"  Tickers with suppliers : {with_sups}/{len(results)}")
    print(f"  Total supplier entries : {total_sups}")
    print(f"  Errors                 : {errors}")
    print(f"  Output                 : {args.output}")


if __name__ == "__main__":
    main()

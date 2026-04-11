# SeleniumAI Task 5 — Nexus Relationship Extraction

Jupyter notebook demonstrating the full **Selenium → LLM → Nexus JSON** pipeline
for the Big Tech AI Infrastructure investment track.

## Quick Start

### 1. Prerequisites

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Ollama (free local LLM)
# → https://ollama.com/download
ollama pull llama3.2   # or: ollama pull mistral
```

### 2. Enable Chrome Developer Mode (for Selenium)

1. Open **Google Chrome**
2. Go to `chrome://extensions/`
3. Toggle **Developer mode** (top right)
4. This allows Selenium's `ChromeDriverManager` to inject the driver

### 3. Environment Setup

```bash
cp .env.example .env
# Edit .env with your Task 4 Postgres credentials
```

### 4. Run the Notebook

```bash
jupyter notebook selenium_nexus.ipynb
```

Run cells **top to bottom**. Each cell is self-contained with inline explanations.

---

## Notebook Structure

| Cell | Contents |
|------|----------|
| 0 | Title & pipeline overview |
| 0a | Installs & imports |
| 1 | Configuration — investment track, Chrome driver setup |
| 2a | SEC EDGAR Selenium scraper (10-K, XPath, JS scroll) |
| 2b | Yahoo Finance News scraper (WebDriverWait, dynamic SPA) |
| 2c | Yahoo Finance Profile scraper (CSS selectors) |
| 2d | Berkshire 13F scraper (link following, table iteration) |
| 2e | Bloomberg attempt — **documented as BLOCKED** (Cloudflare) |
| 2f | SEC EDGAR JSON REST API fallback (10 req/s) |
| 2g | Run all scrapers → `raw_snippets.txt` |
| 3 | Pipeline flowchart (`matplotlib`) |
| 4 | Ollama LLM relationship extraction (prompt engineering) |
| 4b | RapidFuzz company name → ticker normalization |
| 5 | JSON assembly (`investment_track_output.json` + `final_json/{TICKER}.json`) |
| 6 | Postgres insertion stub (Task 4 DB) |
| 7 | Summary + source feedback for team |

---

## Selenium Techniques Demonstrated

| Technique | Cell |
|-----------|------|
| URL navigation + `send_keys(Keys.RETURN)` | 2a |
| `WebDriverWait` + `ExpectedConditions` | 2b |
| CSS + XPath element selection | 2a, 2c |
| `find_elements` table row iteration | 2d |
| `execute_script` JS scroll | 2a, 2d |
| Cookie/modal dismissal | 2e |
| `save_screenshot` on failure | 2e |
| `navigator.webdriver` stealth patch | 1 |
| Browser fingerprint spoofing (user-agent) | 1 |

---

## Source Feedback

| Source | Status |
|--------|--------|
| SEC EDGAR (Selenium) | ✅ Scrapable — explicit waits needed |
| SEC EDGAR JSON API | ✅ Excellent — structured, 10 req/s |
| Yahoo Finance News | ✅ Scrapable — needs 10-12s wait |
| Yahoo Finance Profile | ✅ Scrapable |
| Berkshire 13F | ✅ Scrapable |
| Bloomberg | ⛔ Blocked — Cloudflare JS challenge |
| FT Times (berkeley.edu) | ⚠️ Needs SSO cookie — test next week |

---

## Output Files

```
SeleniumAI_Task5/
├── selenium_nexus.ipynb          ← Main notebook
├── raw_snippets.txt              ← [TICKER|SOURCE] labeled raw text
├── investment_track_output.json  ← Nexus track JSON (all edges)
├── pipeline_flowchart.png        ← Visual pipeline diagram
├── final_json/
│   ├── NVDA.json
│   ├── MSFT.json
│   ├── GOOGL.json
│   ├── AMZN.json
│   ├── META.json
│   └── TSM.json
└── screenshots/                  ← Selenium failure screenshots
```

## Compatible with `andrewyzhou/nexus`

The `scraper/scraper.py` in the repo uses `curl_cffi` for Yahoo Finance metadata.
This notebook **complements** that by adding:
- Selenium-based deep scraping (full-text, news, 13F)
- LLM-powered relationship extraction
- Structured JSON output for the RDT team's Postgres schema

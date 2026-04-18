import anthropic
import json
import os
import time
from dotenv import load_dotenv
from pathlib import Path
from google import genai


load_dotenv()

# Anthropic Claude Setup
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
anthropic_client = anthropic.Anthropic()
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# Google Gemini Setup
gemini_client = genai.Client()
GEMINI_MODEL = "gemini-3-flash-preview"


LLM_SUPPLIER_EXTRACTION_PROMPT = """\
You are a financial document parser specializing in supply chain analysis.

Your ONLY job is to extract DIRECT SUPPLIERS and MANUFACTURING PARTNERS \
from the SEC 10-K filing text provided below.

=== STRICT EXTRACTION RULES ===

INCLUDE only entities that are ALL of the following:
- Explicitly named as a supplier, vendor, or manufacturing partner
- Providing physical goods, components, raw materials, or manufacturing services
- Directly supplying the filing company (not a subsidiary of the filing company)

EXCLUDE all of the following, even if mentioned near supply chain language:
- Competitors (even if they sometimes partner)
- Customers or end users
- Investors or shareholders
- Regulators or government bodies
- Professional service firms (auditors, law firms, consultants)
- Vague unnamed references like "certain suppliers" or "third-party vendors"
- Logistics or distribution companies unless explicitly named as a manufacturer
- The filing company's own subsidiaries or divisions

=== HALLUCINATION RULES ===
- NEVER invent or infer company names not explicitly written in the text
- NEVER use your training knowledge to add suppliers not mentioned in this text
- If a country is mentioned (e.g. "suppliers in Taiwan") but no company name is given, DO NOT include it
- If you are not certain a named entity is a direct supplier, exclude it
- If no qualifying suppliers are found, return an empty list — do not guess

=== OUTPUT FORMAT ===
Return ONLY a JSON object. No explanation, no preamble, no markdown backticks.
Exact format:
{{
  "ticker": "<filing company ticker>",
  "suppliers": ["<ticker or exact company name>", ...]
}}

If no suppliers found:
{{
  "ticker": "<filing company ticker>",
  "suppliers": ["NONE"]
}}

Use the stock ticker symbol if you know it with certainty (e.g. "TSM" for \
Taiwan Semiconductor Manufacturing). Otherwise use the exact company name \
as written in the text. Do not guess tickers.

=== TEXT TO ANALYZE ===
FILING COMPANY: {ticker}
SECTION: {section_name}
{section_text}
"""


def extract_suppliers_with_llm(
    section_text: str,
    ticker: str,
    section_name: str,
) -> dict:
    if not section_text or section_text.strip() == "[NOT FOUND]":
        return {"ticker": ticker, "suppliers": ["NONE"]}
    
    MAX_CHARS = 4000
    chunks = [
        section_text[i:i+MAX_CHARS]
        for i in range(0, len(section_text), MAX_CHARS)
    ]
    
    all_suppliers = []
    
    for i, chunk in enumerate(chunks):
        print(f"chunk {i+1}/{len(chunks)}")
        
        for attempt in range(3):
            try:
                message = anthropic_client.messages.create(
                    model=ANTHROPIC_MODEL,
                    max_tokens=500,
                    messages=[
                        {
                            "role": "user",
                            "content": LLM_SUPPLIER_EXTRACTION_PROMPT.format(
                                ticker=ticker,
                                section_name=section_name,
                                section_text=chunk,
                            )
                        }
                    ]
                )

                text_block = next(
                    (b for b in message.content if b.type == "text"), None
                )
                if not text_block:
                    break
                
                raw = text_block.text.strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                
                parsed = json.loads(raw)
                suppliers = parsed.get("suppliers", [])
                
                suppliers = [s for s in suppliers if s != "NONE"]
                all_suppliers.extend(suppliers)

                time.sleep(0.5)
                break

            except anthropic.RateLimitError:
                    wait = 2 ** attempt  # exponential backoff: 1s, 2s, 4s
                    print(f"Rate limit hit, waiting {wait}s (attempt {attempt+1})")
                    time.sleep(wait)
                    continue
            except json.JSONDecodeError:
                print(f"JSON parse failed, skipping chunk {i+1}")
                continue
            except anthropic.APIError as e:
                print(f"API error: {e}, waiting 2s")
                time.sleep(2)
                continue
            except Exception as e:
                print(f"API error: {e}")
                continue
    
    seen = set()
    unique = [s for s in all_suppliers if not (s in seen or seen.add(s))]
    
    return {
        "ticker": ticker,
        "suppliers": unique if unique else ["NONE"]
    }


def run_extraction_on_basket(
    raw_sections_dir: str = "../scraper/data/raw/raw_sections",
    output_path: str = "pipeline/suppliers.json"
):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    results = []
    section_files = list(Path(raw_sections_dir).glob("*_sections.txt"))
    
    for file in section_files:
        ticker = file.stem.replace("_sections", "")
        print(f"\n{ticker}")
        
        content = file.read_text(encoding="utf-8")
        sections = parse_sections_from_txt(content)
        
        ticker_suppliers = []
        
        for section_name, section_text in sections.items():
            print(f"  → {section_name}")
            result = extract_suppliers_with_llm(section_text, ticker, section_name)
            if result["suppliers"] != ["NONE"]:
                ticker_suppliers.extend(result["suppliers"])
        
        seen = set()
        unique = [s for s in ticker_suppliers if not (s in seen or seen.add(s))]
        
        results.append({
            "ticker": ticker,
            "suppliers": unique if unique else ["NONE"]
        })

        time.sleep(1)
    
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nSaved to {output_path}")
    return results


def parse_sections_from_txt(content: str) -> dict:
    """Parse the section txt files back into a dict."""
    sections = {}
    current_section = None
    current_lines = []
    
    for line in content.splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line.strip("- ").lower()
            current_lines = []
        else:
            current_lines.append(line)
    
    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()
    
    return sections


if __name__ == "__main__":
    run_extraction_on_basket()


import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from main import slugify
from scraper.scraper import _parse

def test_slugify():
    # Regular names
    assert slugify("Technology") == "technology"
    
    # Spaces, caps, dashes as described in README
    assert slugify("Ad agency - big 4") == "ad-agency---big-4"
    assert slugify("A - B") == "a---b"
    
    # Other special characters
    assert slugify("C# & C++ !!!") == "c----c"
    assert slugify("Hello_World") == "hello-world"
    
    # Trimming dashes
    assert slugify("===test===") == "test"

def test_scraper_parse_missing_data():
    # Test _parse with missing quoteSummary or result
    assert _parse({}, "AAPL") is None
    assert _parse({"quoteSummary": {"result": []}}, "AAPL") is None
    
    # Test _parse with incomplete structures (simulating Yahoo dropping data fields)
    data = {
        "quoteSummary": {
            "result": [
                {
                    "price": {"longName": "Fake Apple"},
                    # Intentionally omit summaryDetail, assetProfile, defaultKeyStatistics, calendarEvents
                }
            ]
        }
    }
    
    parsed = _parse(data, "AAPL")
    assert parsed is not None
    assert parsed["ticker"] == "AAPL"
    assert parsed["companyName"] == "Fake Apple"
    # Missing fields should default gracefully
    assert parsed["previousClose"] is None
    assert parsed["sector"] == ""
    assert parsed["dividendYield"] is None
    assert parsed["earningsDate"] == "--"

def test_scraper_parse_full_data():
    # Ensure nested dictionary extraction works as expected
    data = {
        "quoteSummary": {
            "result": [
                {
                    "price": {
                        "longName": "Fake Inc", 
                        "regularMarketPrice": {"raw": 150.0},
                        "marketCap": {"raw": 10000000, "fmt": "10M"}
                    },
                    "summaryDetail": {"previousClose": {"raw": 140.0}},
                    "assetProfile": {"sector": "Technology"},
                    "defaultKeyStatistics": {"trailingEps": {"raw": 5.0}},
                    "calendarEvents": {"earnings": {"earningsDate": [{"fmt": "2025-01-01"}]}}
                }
            ]
        }
    }
    parsed = _parse(data, "FAKE")
    assert parsed["ticker"] == "FAKE"
    assert parsed["price"] == 150.0
    assert parsed["previousClose"] == 140.0
    assert parsed["marketCap"] == 10000000
    assert parsed["marketCapFmt"] == "10M"
    assert parsed["sector"] == "Technology"
    assert parsed["trailingEPS"] == 5.0
    assert parsed["earningsDate"] == "2025-01-01"

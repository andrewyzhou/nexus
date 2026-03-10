import sqlite3
from pathlib import Path
import yfinance as yf

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "corporate_data.db"

def get_company_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    data = ticker.info
    print(data.keys())
    company = {
        "ticker": data.get("symbol"),
        "name": data.get("shortName"),
        "exchange": data.get("exchange"),
        "country": data.get("country"),
        "sector": data.get("sector"),
        "industry": data.get("industry"),
        "currency": data.get("currency"),
        "price": data.get("currentPrice"),
        "market_cap": data.get("marketCap"),
        "enterprise_value": data.get("enterpriseValue"),
        "pe_ratio": data.get("trailingPE"),
        "eps": data.get("trailingEps"),
        "employees": data.get("fullTimeEmployees"),
        "website": data.get("website"),
        "description": data.get("longBusinessSummary")
    }
    print(company)
    return company


def insert_company(company):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO companies (
        ticker, name, exchange, country, sector, industry,
        currency, price, market_cap, enterprise_value,
        pe_ratio, eps, employees, website, description
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        company["ticker"],
        company["name"],    
        company["exchange"],
        company["country"],
        company["sector"],
        company["industry"],
        company["currency"],
        company["price"],
        company["market_cap"],
        company["enterprise_value"],
        company["pe_ratio"],
        company["eps"],
        company["employees"],
        company["website"],
        company["description"]
    ))
     
    conn.commit()
    conn.close()
        
        
if __name__ == "__main__":  
    for ticker in ["AAPL", "MSFT", "GOOGL"]:
        company = get_company_data(ticker)
        print(company)
        
        try:
            insert_company(company)
            print("Inserted:", company["name"])
        except Exception as e:
            print("Skipped:", ticker, e)
BASKET_STOCKS = {
    "CLOUD_ENTERPRISE_SOFTWARE": ["CRM", "ORCL", "NOW", "ADBE", "WDAY"],
    "AI_INFRASTRUCTURE":         ["NVDA", "AMD", "INTC", "AVGO", "QCOM"],
    "BIG_TECH":                  ["AAPL", "GOOGL", "MSFT", "AMZN", "META"],
    "ENERGY_TRANSITION":         ["TSLA", "NEE", "ENPH", "FSLR"],
    "FINANCIALS":                ["JPM", "GS", "BLK"],
    "HEALTHCARE":                ["UNH", "JNJ", "PFE", "ABBV"],
}

ALL_TRACKED_TICKERS = list({
    ticker
    for tickers in BASKET_STOCKS.values()
    for ticker in tickers
})

with open("basket_tickers.txt", "w") as file:
    file.write("\n".join(ALL_TRACKED_TICKERS))
import yfinance as yf

microsoft = yf.Ticker('MSFT')

def printInfo(company):
    print(company.info['sector'])
    print(company.info['industry'])
    print(company.info['marketCap'])
    print(company.info['regularMarketPrice'])

printInfo(microsoft)
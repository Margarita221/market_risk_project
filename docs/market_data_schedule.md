# Market Data Schedule

The project now supports three standard market-data refresh profiles.

## Profiles

### 1. Daily universe refresh
Use this once per day to refresh the full working universe of MOEX instruments.

```powershell
cd C:\market_risk_project\backend
& .\.venv\Scripts\Activate.ps1
python manage.py refresh_market_data --profile daily-universe
```

Default behavior:
- markets: `shares`, `bonds`, `etf`
- mode: full import/update
- per-market limit: `400`

Recommended time:
- once per day, for example `08:30` or before a demo session

### 2. Intraday price refresh
Use this during trading hours to update prices only for instruments already saved in the database.

```powershell
cd C:\market_risk_project\backend
& .\.venv\Scripts\Activate.ps1
python manage.py refresh_market_data --profile intraday-prices
```

Default behavior:
- markets: `shares`, `bonds`, `etf`
- mode: refresh only existing instruments

Recommended frequency:
- every `30-60` minutes during trading hours

### 3. Price history snapshot
Use this to save the current instrument prices into `instrument_price_history`.

```powershell
cd C:\market_risk_project\backend
& .\.venv\Scripts\Activate.ps1
python manage.py refresh_market_data --profile history-snapshot
```

Recommended frequency:
- minimum: once per day
- better for analytics: once per hour

## Suggested operating schedule

Recommended final project schedule:

1. `daily-universe`
- once per day
- keeps the working list of shares, bonds and ETFs актуальной

2. `intraday-prices`
- every `30-60` minutes
- updates prices for instruments that are already in use

3. `history-snapshot`
- once per hour for a richer historical base
- or once per day if you want a lighter setup

## Useful overrides

Refresh only bonds and ETFs:

```powershell
python manage.py refresh_market_data --profile daily-universe --market bonds --market etf
```

Reduce the daily import size:

```powershell
python manage.py refresh_market_data --profile daily-universe --limit-per-market 150
```

Use a custom source label for history snapshots:

```powershell
python manage.py refresh_market_data --profile history-snapshot --snapshot-source DEMO
```

## Practical note

For diploma/demo use, this schedule is enough:

- refresh the universe once a day
- refresh existing prices every hour
- store history once a day or once an hour

This gives you:
- a realistic instrument catalogue
- актуальные цены for portfolio valuation
- a history table for later analytical extensions

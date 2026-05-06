import json
from datetime import datetime, time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

from django.utils import timezone

from riskapp.models import Instrument, InstrumentPriceHistory


MOEX_ISS_BASE_URL = "https://iss.moex.com/iss"
MARKET_TO_TYPE = {
    "shares": Instrument.TYPE_STOCK,
    "bonds": Instrument.TYPE_BOND,
    "etf": Instrument.TYPE_ETF,
}
MARKET_TO_SECTOR = {
    "shares": Instrument.SECTOR_EQUITIES,
    "bonds": Instrument.SECTOR_BONDS,
    "etf": Instrument.SECTOR_FUNDS,
}
TYPE_TO_MARKET = {
    Instrument.TYPE_STOCK: "shares",
    Instrument.TYPE_BOND: "bonds",
    Instrument.TYPE_ETF: "etf",
}
PRICE_FIELDS_PRIORITY = (
    "LAST",
    "MARKETPRICE",
    "LCLOSEPRICE",
    "LEGALCLOSEPRICE",
    "PREVWAPRICE",
    "PREVPRICE",
)
CURRENCY_FIELDS_PRIORITY = (
    "CURRENCYID",
    "FACEUNIT",
    "SETTLECURRENCY",
    "CURRENCY",
)
CURRENCY_ALIASES = {
    "SUR": "RUB",
}
HISTORY_PRICE_FIELDS_PRIORITY = (
    "LEGALCLOSEPRICE",
    "CLOSE",
    "MARKETPRICE",
    "LAST",
    "WAPRICE",
)
INCOME_YIELD_FIELDS_PRIORITY = (
    "COUPONPERCENT",
    "YIELD",
    "YIELDTOOFFER",
    "YIELDLASTCOUPON",
    "YIELDATPREVWAPRICE",
)
DIVIDEND_YIELD_FIELDS_PRIORITY = (
    "DIVYIELD",
    "DIVIDENDYIELD",
)


@dataclass
class MoexSyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0


@dataclass
class MoexHistorySyncStats:
    imported: int = 0
    skipped: int = 0
    instruments: int = 0


def _build_url(path: str, params: dict | None = None) -> str:
    query = urlencode(params or {})
    return f"{MOEX_ISS_BASE_URL}{path}{'?' + query if query else ''}"


def _fetch_json(path: str, params: dict | None = None) -> dict:
    url = _build_url(path, params)
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _rows_from_block(payload: dict, block_name: str) -> list[dict]:
    block = payload.get(block_name) or {}
    columns = block.get("columns", [])
    data = block.get("data", [])
    return [dict(zip(columns, row)) for row in data]


def _decimal_or_none(value) -> Decimal | None:
    if value in (None, "", 0):
        if value == 0:
            return Decimal("0")
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _extract_price(marketdata_row: dict) -> Decimal | None:
    for field in PRICE_FIELDS_PRIORITY:
        price = _decimal_or_none(marketdata_row.get(field))
        if price is not None and price >= 0:
            return price
    return None


def _extract_currency(security_row: dict, marketdata_row: dict) -> str:
    for field in CURRENCY_FIELDS_PRIORITY:
        value = security_row.get(field) or marketdata_row.get(field)
        if value:
            return CURRENCY_ALIASES.get(str(value), str(value))
    return "RUB"


def _extract_fractional_percent(*rows, fields_priority) -> Decimal | None:
    for field in fields_priority:
        for row in rows:
            if not row:
                continue
            value = _decimal_or_none(row.get(field))
            if value is not None and value >= 0:
                return (value / Decimal("100")).quantize(Decimal("0.000001"))
    return None


def _extract_coupon_yield(security_row: dict, marketdata_row: dict) -> Decimal | None:
    return _extract_fractional_percent(security_row, marketdata_row, fields_priority=INCOME_YIELD_FIELDS_PRIORITY)


def _extract_dividend_yield(security_row: dict, marketdata_row: dict) -> Decimal | None:
    return _extract_fractional_percent(security_row, marketdata_row, fields_priority=DIVIDEND_YIELD_FIELDS_PRIORITY)


def _extract_history_price(history_row: dict) -> Decimal | None:
    for field in HISTORY_PRICE_FIELDS_PRIORITY:
        price = _decimal_or_none(history_row.get(field))
        if price is not None and price >= 0:
            return price
    return None


def _parse_trade_date(history_row: dict):
    trade_date = history_row.get("TRADEDATE") or history_row.get("TRADEDATESTR")
    if not trade_date:
        return None
    try:
        return datetime.strptime(str(trade_date), "%Y-%m-%d").date()
    except ValueError:
        return None


def _history_timestamp_from_date(trade_date):
    timezone_value = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(trade_date, time(hour=12, minute=0)), timezone_value)


def fetch_market_snapshot(market: str, start: int = 0) -> list[dict]:
    payload = _fetch_json(
        f"/engines/stock/markets/{market}/securities.json",
        {
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "start": start,
        },
    )
    securities_rows = _rows_from_block(payload, "securities")
    marketdata_rows = _rows_from_block(payload, "marketdata")
    marketdata_by_secid = {row.get("SECID"): row for row in marketdata_rows}

    combined = []
    for security_row in securities_rows:
        secid = security_row.get("SECID")
        if not secid:
            continue
        marketdata_row = marketdata_by_secid.get(secid, {})
        combined.append({
            "ticker": str(secid),
            "name": security_row.get("SHORTNAME") or security_row.get("SECNAME") or str(secid),
            "currency": _extract_currency(security_row, marketdata_row),
            "current_price": _extract_price(marketdata_row),
            "coupon_yield": _extract_coupon_yield(security_row, marketdata_row),
            "dividend_yield": _extract_dividend_yield(security_row, marketdata_row),
        })
    return combined


def fetch_market_history_page(market: str, ticker: str, start: int = 0, from_date=None, till_date=None) -> list[dict]:
    params = {
        "iss.meta": "off",
        "iss.only": "history",
        "start": start,
    }
    if from_date:
        params["from"] = str(from_date)
    if till_date:
        params["till"] = str(till_date)

    payload = _fetch_json(
        f"/history/engines/stock/markets/{market}/securities/{ticker}.json",
        params,
    )
    return _rows_from_block(payload, "history")


def iter_market_history(market: str, ticker: str, from_date=None, till_date=None) -> Iterable[dict]:
    start = 0
    while True:
        rows = fetch_market_history_page(
            market=market,
            ticker=ticker,
            start=start,
            from_date=from_date,
            till_date=till_date,
        )
        if not rows:
            break
        for row in rows:
            yield row
        if len(rows) < 100:
            break
        start += len(rows)


def iter_market_snapshots(markets: Iterable[str], limit_per_market: int | None = None) -> Iterable[tuple[str, dict]]:
    for market in markets:
        start = 0
        yielded_for_market = 0
        while True:
            rows = fetch_market_snapshot(market, start=start)
            if not rows:
                break
            for row in rows:
                if limit_per_market is not None and yielded_for_market >= limit_per_market:
                    break
                yield market, row
                yielded_for_market += 1
            if limit_per_market is not None and yielded_for_market >= limit_per_market:
                break
            if len(rows) < 100:
                break
            start += len(rows)


def sync_moex_instruments(
    markets: Iterable[str],
    limit_total: int | None = None,
    limit_per_market: int | None = None,
    existing_only: bool = False,
) -> MoexSyncStats:
    stats = MoexSyncStats()
    synced = 0
    existing_tickers = set(Instrument.objects.values_list("ticker", flat=True)) if existing_only else None

    for market, row in iter_market_snapshots(markets, limit_per_market=limit_per_market):
        if limit_total is not None and synced >= limit_total:
            break

        instrument_type = Instrument.normalize_instrument_type(MARKET_TO_TYPE.get(market, market))
        price = row["current_price"]
        if price is None:
            stats.skipped += 1
            continue
        if existing_tickers is not None and row["ticker"] not in existing_tickers:
            stats.skipped += 1
            continue

        instrument_defaults = {
            "name": row["name"],
            "instrument_type": instrument_type,
            "sector": MARKET_TO_SECTOR.get(market, Instrument.infer_sector(instrument_type)),
            "currency": row["currency"],
            "current_price": price,
            "last_price_updated_at": timezone.now(),
        }
        if row.get("coupon_yield") is not None:
            instrument_defaults["coupon_yield"] = row["coupon_yield"]
        if row.get("dividend_yield") is not None:
            instrument_defaults["dividend_yield"] = row["dividend_yield"]

        instrument, created = Instrument.objects.update_or_create(
            ticker=row["ticker"],
            defaults=instrument_defaults,
        )

        InstrumentPriceHistory.objects.create(
            instrument=instrument,
            price=price,
            currency=row["currency"],
            source="MOEX",
        )

        if created:
            stats.created += 1
        else:
            stats.updated += 1

        synced += 1

    return stats


def snapshot_current_prices(source: str = "MANUAL") -> int:
    created = 0

    for instrument in Instrument.objects.all().order_by("ticker"):
        InstrumentPriceHistory.objects.create(
            instrument=instrument,
            price=instrument.current_price,
            currency=instrument.currency,
            source=source,
        )
        created += 1

    return created


def sync_moex_price_history(
    instruments: Iterable[Instrument] | None = None,
    lookback_days: int = 180,
    replace_existing: bool = False,
) -> MoexHistorySyncStats:
    history_stats = MoexHistorySyncStats()
    till_date = timezone.localdate()
    from_date = till_date - timezone.timedelta(days=max(int(lookback_days), 1))
    target_instruments = list(instruments or Instrument.objects.all().order_by("ticker"))

    for instrument in target_instruments:
        market = TYPE_TO_MARKET.get(instrument.normalized_type)
        if not market:
            history_stats.skipped += 1
            continue

        history_stats.instruments += 1
        imported_for_instrument = 0
        existing_dates = set()
        if not replace_existing:
            existing_dates = set(
                instrument.price_history.filter(
                    source="MOEX_HISTORY",
                    captured_at__date__gte=from_date,
                    captured_at__date__lte=till_date,
                ).values_list("captured_at__date", flat=True)
            )
        else:
            instrument.price_history.filter(
                source="MOEX_HISTORY",
                captured_at__date__gte=from_date,
                captured_at__date__lte=till_date,
            ).delete()

        for row in iter_market_history(market, instrument.ticker, from_date=from_date, till_date=till_date):
            trade_date = _parse_trade_date(row)
            price = _extract_history_price(row)
            if trade_date is None or price is None or trade_date in existing_dates:
                if trade_date is None or price is None:
                    history_stats.skipped += 1
                continue

            currency = _extract_currency(row, row) or instrument.currency
            history_row = InstrumentPriceHistory.objects.create(
                instrument=instrument,
                price=price,
                currency=currency,
                source="MOEX_HISTORY",
            )
            history_row.captured_at = _history_timestamp_from_date(trade_date)
            history_row.save(update_fields=["captured_at"])
            existing_dates.add(trade_date)
            imported_for_instrument += 1

        history_stats.imported += imported_for_instrument

    return history_stats

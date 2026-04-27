import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

from django.utils import timezone

from riskapp.models import Instrument


MOEX_ISS_BASE_URL = "https://iss.moex.com/iss"
MARKET_TO_TYPE = {
    "shares": "stock",
    "bonds": "bond",
    "etf": "etf",
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


@dataclass
class MoexSyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0


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
        })
    return combined


def iter_market_snapshots(markets: Iterable[str]) -> Iterable[tuple[str, dict]]:
    for market in markets:
        start = 0
        while True:
            rows = fetch_market_snapshot(market, start=start)
            if not rows:
                break
            for row in rows:
                yield market, row
            if len(rows) < 100:
                break
            start += len(rows)


def sync_moex_instruments(markets: Iterable[str], limit: int | None = None) -> MoexSyncStats:
    stats = MoexSyncStats()
    synced = 0

    for market, row in iter_market_snapshots(markets):
        if limit is not None and synced >= limit:
            break

        instrument_type = MARKET_TO_TYPE.get(market, market)
        price = row["current_price"]
        if price is None:
            stats.skipped += 1
            continue

        instrument, created = Instrument.objects.update_or_create(
            ticker=row["ticker"],
            defaults={
                "name": row["name"],
                "instrument_type": instrument_type,
                "currency": row["currency"],
                "current_price": price,
                "last_price_updated_at": timezone.now(),
            },
        )

        if created:
            stats.created += 1
        else:
            stats.updated += 1

        synced += 1

    return stats

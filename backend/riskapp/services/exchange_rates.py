from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree
from urllib.request import urlopen

from django.db.models import Q

from riskapp.models import ExchangeRate, Portfolio


CBR_DAILY_XML_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
CURRENCY_ALIASES = {
    "SUR": "RUB",
}


@dataclass
class ExchangeRateSyncStats:
    created: int = 0
    updated: int = 0


def normalize_currency_code(value):
    normalized = (value or "").strip().upper()
    return CURRENCY_ALIASES.get(normalized, normalized)


def decimal_or_none(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def fetch_cbr_daily_rates():
    with urlopen(CBR_DAILY_XML_URL, timeout=30) as response:
        payload = response.read().decode("windows-1251")

    root = ElementTree.fromstring(payload)
    rate_date = root.attrib.get("Date")
    rates = {}

    for valute in root.findall("Valute"):
        char_code = normalize_currency_code((valute.findtext("CharCode") or "").strip())
        nominal = decimal_or_none((valute.findtext("Nominal") or "1").replace(",", "."))
        value = decimal_or_none((valute.findtext("Value") or "").replace(",", "."))
        if not char_code or nominal in (None, Decimal("0")) or value is None:
            continue
        rates[char_code] = (value / nominal)

    return rate_date, rates


def upsert_exchange_rates(currencies=None, source="CBR"):
    rate_date, rates = fetch_cbr_daily_rates()
    selected = {normalize_currency_code(currency) for currency in (currencies or rates.keys()) if currency}
    selected.discard("RUB")
    stats = ExchangeRateSyncStats()

    for currency in sorted(selected):
        rate_to_rub = rates.get(currency)
        if rate_to_rub is None:
            continue

        _, created = ExchangeRate.objects.update_or_create(
            from_currency=currency,
            to_currency="RUB",
            rate_date=_parse_rate_date(rate_date),
            defaults={"rate": rate_to_rub, "source": source},
        )
        stats.created += int(created)
        stats.updated += int(not created)

        reverse_rate = (Decimal("1") / rate_to_rub)
        _, reverse_created = ExchangeRate.objects.update_or_create(
            from_currency="RUB",
            to_currency=currency,
            rate_date=_parse_rate_date(rate_date),
            defaults={"rate": reverse_rate, "source": source},
        )
        stats.created += int(reverse_created)
        stats.updated += int(not reverse_created)

    return stats


def _parse_rate_date(raw_value):
    day, month, year = raw_value.split(".")
    return f"{year}-{month}-{day}"


def get_latest_rate(from_currency, to_currency):
    source_currency = normalize_currency_code(from_currency)
    target_currency = normalize_currency_code(to_currency)

    if source_currency == target_currency:
        return Decimal("1")

    direct = ExchangeRate.objects.filter(
        from_currency=source_currency,
        to_currency=target_currency,
    ).order_by("-rate_date", "-updated_at").first()
    if direct:
        return direct.rate

    reverse = ExchangeRate.objects.filter(
        from_currency=target_currency,
        to_currency=source_currency,
    ).order_by("-rate_date", "-updated_at").first()
    if reverse:
        return Decimal("1") / reverse.rate

    if source_currency != "RUB" and target_currency != "RUB":
        source_to_rub = get_latest_rate(source_currency, "RUB")
        rub_to_target = get_latest_rate("RUB", target_currency)
        if source_to_rub and rub_to_target:
            return source_to_rub * rub_to_target

    return None


def convert_amount(amount, from_currency, to_currency):
    rate = get_latest_rate(from_currency, to_currency)
    if rate is None:
        return None
    return Decimal(str(amount)) * rate


def get_portfolio_base_currency(portfolio):
    return normalize_currency_code(getattr(portfolio, "base_currency", Portfolio.CURRENCY_RUB))


def get_required_portfolio_currencies():
    return sorted({
        normalize_currency_code(currency)
        for currency in Portfolio.objects.exclude(
            Q(base_currency="") | Q(base_currency__isnull=True)
        ).values_list("base_currency", flat=True)
    } | {
        normalize_currency_code(currency)
        for currency in ExchangeRate.objects.values_list("from_currency", flat=True)
    })

from decimal import Decimal, InvalidOperation

from django import template

from riskapp.i18n import translate


register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, key, **kwargs):
    return translate(key, context.get("ui_language", "ru"), **kwargs)


def _to_decimal(value):
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _format_decimal(value, decimals):
    decimal_value = _to_decimal(value)
    return f"{decimal_value:,.{int(decimals)}f}".replace(",", " ")


def _currency_decimals(currency_code):
    normalized = str(currency_code or "").strip().upper()
    return 2 if normalized == "RUB" else 4


@register.filter
def money_value(value, decimals=2):
    return _format_decimal(value, decimals)


@register.filter
def money_by_currency(value, currency_code):
    return _format_decimal(value, _currency_decimals(currency_code))


@register.filter
def numeric_value(value, decimals=2):
    return _format_decimal(value, decimals)


@register.filter
def percent_value(value, decimals=2):
    decimal_value = _to_decimal(value) * Decimal("100")
    return _format_decimal(decimal_value, decimals)


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    return mapping.get(key)

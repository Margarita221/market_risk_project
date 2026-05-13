from decimal import Decimal, InvalidOperation

from django import template

from riskapp.i18n import translate
from riskapp.models import Instrument, Scenario


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


@register.simple_tag(takes_context=True)
def rebalancing_label(context, value):
    language = context.get("ui_language", "ru")
    labels = {
        Scenario.REBALANCE_NONE: "Без ребалансировки" if language == "ru" else "Buy and hold",
        Scenario.REBALANCE_MONTHLY: "Ежемесячная ребалансировка" if language == "ru" else "Monthly rebalance",
        Scenario.REBALANCE_QUARTERLY: "Квартальная ребалансировка" if language == "ru" else "Quarterly rebalance",
    }
    return labels.get(value, value or "-")


@register.simple_tag(takes_context=True)
def sector_label(context, value):
    language = context.get("ui_language", "ru")
    labels = {
        Instrument.SECTOR_EQUITIES: translate("sector_equities", language),
        Instrument.SECTOR_BONDS: translate("sector_bonds", language),
        Instrument.SECTOR_FUNDS: translate("sector_funds", language),
    }
    return labels.get(value, value or "-")


@register.simple_tag(takes_context=True)
def preset_label(context, value):
    language = context.get("ui_language", "ru")
    labels = {
        Scenario.PRESET_CUSTOM: "Пользовательский" if language == "ru" else "Custom",
        Scenario.PRESET_BASE: "Базовый" if language == "ru" else "Base",
        Scenario.PRESET_OPTIMISTIC: "Оптимистичный" if language == "ru" else "Optimistic",
        Scenario.PRESET_PESSIMISTIC: "Пессимистичный" if language == "ru" else "Pessimistic",
        Scenario.PRESET_STRESS: "Стрессовый" if language == "ru" else "Stress",
        Scenario.PRESET_CRISIS: "Кризисный" if language == "ru" else "Crisis",
    }
    return labels.get(value, value or "-")


@register.simple_tag(takes_context=True)
def instrument_type_label(context, value):
    language = context.get("ui_language", "ru")
    normalized = str(value or "").strip().lower()
    labels = {
        Instrument.TYPE_STOCK: translate("instrument_type_stock", language),
        Instrument.TYPE_BOND: translate("instrument_type_bond", language),
        Instrument.TYPE_ETF: translate("instrument_type_etf", language),
    }
    return labels.get(normalized, value or "-")

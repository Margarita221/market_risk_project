from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from riskapp.models import PortfolioPosition, TradeOperation
from riskapp.services.exchange_rates import convert_amount, normalize_currency_code


BROKER_COMMISSION_RATE = Decimal("0.0003")
TRADE_SLIPPAGE_RATES = {
    "stock": Decimal("0.0012"),
    "bond": Decimal("0.0004"),
    "etf": Decimal("0.0008"),
}


@dataclass(frozen=True)
class PortfolioCashSnapshot:
    balance: Decimal
    currency: str
    reliable: bool


def _to_decimal(value, default="0"):
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


def _quantize_money(value):
    return value.quantize(Decimal("1.0000"), rounding=ROUND_HALF_UP)


def _quantize_balance(value):
    return value.quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)


def estimate_trade_commission(quantity, price_per_unit):
    gross_amount = Decimal(int(quantity)) * _to_decimal(price_per_unit)
    return (gross_amount * BROKER_COMMISSION_RATE).quantize(Decimal("1.0000"), rounding=ROUND_HALF_UP)


def estimate_trade_slippage_rate(instrument, operation_type, quantity=1):
    instrument_type = instrument.normalized_type
    base_rate = TRADE_SLIPPAGE_RATES.get(instrument_type, TRADE_SLIPPAGE_RATES["stock"])
    quantity_multiplier = Decimal("1") + min(Decimal(int(quantity)) / Decimal("100"), Decimal("1")) * Decimal("0.50")
    return (base_rate * quantity_multiplier).quantize(Decimal("1.000000"), rounding=ROUND_HALF_UP)


def estimate_trade_execution_price(instrument, operation_type, quote_price, quantity=1):
    quote_price = _to_decimal(quote_price)
    slippage_rate = estimate_trade_slippage_rate(instrument, operation_type, quantity)
    direction_multiplier = Decimal("1") + slippage_rate if operation_type == TradeOperation.TYPE_BUY else Decimal("1") - slippage_rate
    execution_price = _quantize_money(quote_price * direction_multiplier)
    return execution_price, slippage_rate


def estimate_trade_slippage_amount(quantity, quote_price, executed_price):
    quantity_decimal = Decimal(int(quantity))
    return _quantize_money(abs(_to_decimal(executed_price) - _to_decimal(quote_price)) * quantity_decimal)


def get_portfolio_cash_snapshot(portfolio):
    base_currency = normalize_currency_code(getattr(portfolio, "base_currency", "RUB"))
    balance = _to_decimal(getattr(portfolio, "initial_value", 0))
    operations = list(
        portfolio.trade_operations.select_related("instrument")
        .order_by("executed_at", "created_at", "id")
    )
    reliable = bool(operations) or not portfolio.positions.exists()

    if not operations and portfolio.positions.exists():
        inferred_cost = Decimal("0")
        for position in portfolio.positions.select_related("instrument"):
            average_cost = Decimal(position.quantity) * _to_decimal(position.average_purchase_price)
            converted_cost = convert_amount(average_cost, position.instrument.currency, base_currency)
            if converted_cost is not None:
                inferred_cost += converted_cost
        balance -= inferred_cost

    for operation in operations:
        converted_amount = convert_amount(operation.net_amount, operation.instrument.currency, base_currency)
        if converted_amount is None:
            continue
        if operation.operation_type == TradeOperation.TYPE_BUY:
            balance -= converted_amount
        else:
            balance += converted_amount

    return PortfolioCashSnapshot(
        balance=_quantize_balance(balance),
        currency=base_currency,
        reliable=reliable,
    )


@transaction.atomic
def record_trade_operation(
    *,
    user,
    portfolio,
    instrument,
    operation_type,
    quantity,
    price_per_unit,
    commission=None,
    executed_at=None,
    comment="",
):
    quantity = int(quantity)
    quote_price = _to_decimal(price_per_unit)
    price_per_unit, slippage_rate = estimate_trade_execution_price(
        instrument,
        operation_type,
        quote_price,
        quantity,
    )
    slippage_amount = estimate_trade_slippage_amount(quantity, quote_price, price_per_unit)
    commission = estimate_trade_commission(quantity, price_per_unit) if commission in (None, "") else _to_decimal(commission)
    executed_at = executed_at or timezone.now()
    cash_before = get_portfolio_cash_snapshot(portfolio)

    if quantity <= 0:
        raise ValueError("Quantity must be positive")
    if quote_price < 0:
        raise ValueError("Price must be non-negative")
    if commission < 0:
        raise ValueError("Commission must be non-negative")

    position = (
        PortfolioPosition.objects
        .select_for_update()
        .filter(portfolio=portfolio, instrument=instrument)
        .first()
    )

    realized_pnl = None
    updated_position = position
    cash_delta_in_base_currency = Decimal("0")

    if operation_type == TradeOperation.TYPE_BUY:
        if position is None:
            average_purchase_price = ((Decimal(quantity) * price_per_unit) + commission) / Decimal(quantity)
            updated_position = PortfolioPosition.objects.create(
                portfolio=portfolio,
                instrument=instrument,
                quantity=quantity,
                average_purchase_price=average_purchase_price,
            )
        else:
            old_quantity = position.quantity
            new_quantity = old_quantity + quantity
            blended_cost = (
                (Decimal(old_quantity) * position.average_purchase_price)
                + (Decimal(quantity) * price_per_unit)
                + commission
            )
            position.quantity = new_quantity
            position.average_purchase_price = blended_cost / Decimal(new_quantity)
            position.save(update_fields=["quantity", "average_purchase_price"])
            updated_position = position
        converted_cash_delta = convert_amount(
            (Decimal(quantity) * price_per_unit) + commission,
            instrument.currency,
            cash_before.currency,
        )
        if converted_cash_delta is not None:
            cash_delta_in_base_currency = -converted_cash_delta
    elif operation_type == TradeOperation.TYPE_SELL:
        if position is None or position.quantity < quantity:
            raise ValueError("Not enough quantity to sell")
        realized_pnl = (
            (Decimal(quantity) * price_per_unit)
            - commission
            - (Decimal(quantity) * position.average_purchase_price)
        )
        remaining_quantity = position.quantity - quantity
        if remaining_quantity == 0:
            position.delete()
            updated_position = None
        else:
            position.quantity = remaining_quantity
            position.save(update_fields=["quantity"])
            updated_position = position
        converted_cash_delta = convert_amount(
            (Decimal(quantity) * price_per_unit) - commission,
            instrument.currency,
            cash_before.currency,
        )
        if converted_cash_delta is not None:
            cash_delta_in_base_currency = converted_cash_delta
    else:
        raise ValueError("Unsupported operation type")

    cash_balance_after = _quantize_balance(cash_before.balance + cash_delta_in_base_currency)

    operation = TradeOperation.objects.create(
        user=user,
        portfolio=portfolio,
        instrument=instrument,
        operation_type=operation_type,
        quantity=quantity,
        quoted_price=quote_price,
        price_per_unit=price_per_unit,
        slippage_rate=slippage_rate,
        slippage_amount=slippage_amount,
        commission=commission,
        realized_pnl=realized_pnl,
        cash_balance_after=cash_balance_after,
        executed_at=executed_at,
        comment=comment,
    )
    return operation, updated_position

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from riskapp.models import PortfolioPosition, TradeOperation


BROKER_COMMISSION_RATE = Decimal("0.0003")


def _to_decimal(value, default="0"):
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


def estimate_trade_commission(quantity, price_per_unit):
    gross_amount = Decimal(int(quantity)) * _to_decimal(price_per_unit)
    return (gross_amount * BROKER_COMMISSION_RATE).quantize(Decimal("1.0000"), rounding=ROUND_HALF_UP)


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
    price_per_unit = _to_decimal(price_per_unit)
    commission = estimate_trade_commission(quantity, price_per_unit) if commission in (None, "") else _to_decimal(commission)
    executed_at = executed_at or timezone.now()

    if quantity <= 0:
        raise ValueError("Quantity must be positive")
    if price_per_unit < 0:
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
    else:
        raise ValueError("Unsupported operation type")

    operation = TradeOperation.objects.create(
        user=user,
        portfolio=portfolio,
        instrument=instrument,
        operation_type=operation_type,
        quantity=quantity,
        price_per_unit=price_per_unit,
        commission=commission,
        realized_pnl=realized_pnl,
        executed_at=executed_at,
        comment=comment,
    )
    return operation, updated_position

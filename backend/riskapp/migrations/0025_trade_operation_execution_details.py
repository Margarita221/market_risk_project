from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0024_scenario_rebalancing_frequency"),
    ]

    operations = [
        migrations.AddField(
            model_name="tradeoperation",
            name="cash_balance_after",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name="tradeoperation",
            name="quoted_price",
            field=models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=15),
        ),
        migrations.AddField(
            model_name="tradeoperation",
            name="slippage_amount",
            field=models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=15),
        ),
        migrations.AddField(
            model_name="tradeoperation",
            name="slippage_rate",
            field=models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10),
        ),
        migrations.AddConstraint(
            model_name="tradeoperation",
            constraint=models.CheckConstraint(
                condition=models.Q(("quoted_price__gte", 0)),
                name="trade_operation_quoted_price_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="tradeoperation",
            constraint=models.CheckConstraint(
                condition=models.Q(("slippage_rate__gte", 0)),
                name="trade_operation_slippage_rate_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="tradeoperation",
            constraint=models.CheckConstraint(
                condition=models.Q(("slippage_amount__gte", 0)),
                name="trade_operation_slippage_amount_gte_0",
            ),
        ),
    ]

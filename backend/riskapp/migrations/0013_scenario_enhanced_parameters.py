from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0012_instrument_last_price_updated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="market_shock",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="scenario",
            name="preset",
            field=models.CharField(
                choices=[
                    ("custom", "Custom"),
                    ("base", "Base"),
                    ("optimistic", "Optimistic"),
                    ("pessimistic", "Pessimistic"),
                    ("stress", "Stress"),
                    ("crisis", "Crisis"),
                ],
                default="custom",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="scenario",
            name="systematic_risk",
            field=models.DecimalField(decimal_places=4, default=Decimal("0.6500"), max_digits=5),
        ),
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.CheckConstraint(
                condition=models.Q(("systematic_risk__gte", 0)),
                name="scenario_systematic_risk_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.CheckConstraint(
                condition=models.Q(("systematic_risk__lte", 1)),
                name="scenario_systematic_risk_lte_1",
            ),
        ),
    ]

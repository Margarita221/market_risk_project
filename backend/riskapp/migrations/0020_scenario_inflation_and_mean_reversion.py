from decimal import Decimal

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("riskapp", "0019_exchange_rates_and_portfolio_base_currency"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="inflation_shock",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="scenario",
            name="mean_reversion_strength",
            field=models.DecimalField(decimal_places=4, default=Decimal("0.1500"), max_digits=5),
        ),
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.CheckConstraint(
                condition=Q(mean_reversion_strength__gte=0),
                name="scenario_mean_reversion_strength_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.CheckConstraint(
                condition=Q(mean_reversion_strength__lte=1),
                name="scenario_mean_reversion_strength_lte_1",
            ),
        ),
    ]

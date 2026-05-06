from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0022_alter_instrument_options_alter_instrument_created_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="instrument",
            name="coupon_yield",
            field=models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10, verbose_name="Coupon yield"),
        ),
        migrations.AddField(
            model_name="instrument",
            name="dividend_yield",
            field=models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10, verbose_name="Dividend yield"),
        ),
        migrations.AddConstraint(
            model_name="instrument",
            constraint=models.CheckConstraint(condition=models.Q(("dividend_yield__gte", 0)), name="instrument_dividend_yield_gte_0"),
        ),
        migrations.AddConstraint(
            model_name="instrument",
            constraint=models.CheckConstraint(condition=models.Q(("coupon_yield__gte", 0)), name="instrument_coupon_yield_gte_0"),
        ),
    ]

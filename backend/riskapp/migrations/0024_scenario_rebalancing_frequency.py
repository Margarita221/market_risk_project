from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0023_instrument_income_yields"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="rebalancing_frequency",
            field=models.CharField(
                choices=[
                    ("none", "Buy and hold"),
                    ("monthly", "Monthly rebalance"),
                    ("quarterly", "Quarterly rebalance"),
                ],
                default="none",
                max_length=20,
            ),
        ),
    ]

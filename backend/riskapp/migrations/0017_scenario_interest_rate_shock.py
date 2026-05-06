from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0016_fill_existing_instrument_sectors"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="interest_rate_shock",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=10),
        ),
    ]

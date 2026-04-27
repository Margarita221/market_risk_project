from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0013_scenario_enhanced_parameters"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="currency_shock",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=10),
        ),
    ]

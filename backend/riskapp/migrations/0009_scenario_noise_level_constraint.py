from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0008_portfolio_current_value_db_logic"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.CheckConstraint(
                condition=models.Q(("noise_level__gte", 0)),
                name="scenario_noise_level_gte_0",
            ),
        ),
    ]

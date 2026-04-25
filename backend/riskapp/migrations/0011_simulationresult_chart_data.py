from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0010_alter_portfolioposition_quantity"),
    ]

    operations = [
        migrations.AddField(
            model_name="simulationresult",
            name="chart_data",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

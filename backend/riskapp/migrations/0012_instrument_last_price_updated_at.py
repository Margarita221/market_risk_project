from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0011_simulationresult_chart_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="instrument",
            name="last_price_updated_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Price updated at"),
        ),
    ]

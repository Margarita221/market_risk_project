from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0014_scenario_currency_shock"),
    ]

    operations = [
        migrations.AddField(
            model_name="instrument",
            name="sector",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="Sector"),
        ),
        migrations.AddField(
            model_name="scenario",
            name="sector_shock",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="scenario",
            name="sector_target",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.CreateModel(
            name="InstrumentPriceHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("price", models.DecimalField(decimal_places=4, max_digits=15, verbose_name="Captured price")),
                ("currency", models.CharField(max_length=10, verbose_name="Captured currency")),
                ("source", models.CharField(default="MOEX", max_length=30, verbose_name="Source")),
                ("captured_at", models.DateTimeField(auto_now_add=True, verbose_name="Captured at")),
                ("instrument", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="price_history", to="riskapp.instrument")),
            ],
            options={
                "verbose_name": "Instrument price history",
                "verbose_name_plural": "Instrument price history",
                "db_table": "instrument_price_history",
                "ordering": ["-captured_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="instrumentpricehistory",
            constraint=models.CheckConstraint(condition=models.Q(("price__gte", 0)), name="instrument_price_history_price_gte_0"),
        ),
    ]

from pathlib import Path

from django.db import migrations, models


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def read_sql(filename):
    return (SQL_DIR / filename).read_text(encoding="utf-8")


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0018_normalize_instrument_types_and_sectors"),
    ]

    operations = [
        migrations.AddField(
            model_name="portfolio",
            name="base_currency",
            field=models.CharField(default="RUB", max_length=10),
        ),
        migrations.CreateModel(
            name="ExchangeRate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("from_currency", models.CharField(max_length=10, verbose_name="From currency")),
                ("to_currency", models.CharField(max_length=10, verbose_name="To currency")),
                ("rate", models.DecimalField(decimal_places=8, max_digits=18, verbose_name="Rate")),
                ("rate_date", models.DateField(verbose_name="Rate date")),
                ("source", models.CharField(default="CBR", max_length=30, verbose_name="Source")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated at")),
            ],
            options={
                "db_table": "exchange_rate",
                "ordering": ["-rate_date", "from_currency", "to_currency"],
                "verbose_name": "Exchange rate",
                "verbose_name_plural": "Exchange rates",
            },
        ),
        migrations.AddConstraint(
            model_name="exchangerate",
            constraint=models.UniqueConstraint(fields=("from_currency", "to_currency", "rate_date"), name="unique_exchange_rate_pair_date"),
        ),
        migrations.AddConstraint(
            model_name="exchangerate",
            constraint=models.CheckConstraint(condition=models.Q(rate__gt=0), name="exchange_rate_rate_gt_0"),
        ),
        migrations.RunSQL(
            sql="\n\n".join([
                read_sql("functions_exchange_rates.sql"),
                read_sql("triggers_exchange_rates.sql"),
                read_sql("initialize_portfolio_values_exchange_rates.sql"),
                read_sql("views_exchange_rates.sql"),
            ]),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

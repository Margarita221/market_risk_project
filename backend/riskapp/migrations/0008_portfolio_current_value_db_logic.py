from pathlib import Path

from django.db import migrations, models


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def read_sql(filename):
    return (SQL_DIR / filename).read_text(encoding="utf-8")


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0007_alter_portfolioposition_unique_together_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="portfolio",
            name="current_value",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
        migrations.RunSQL(
            sql="\n\n".join([
                read_sql("functions.sql"),
                read_sql("triggers.sql"),
                read_sql("initialize_portfolio_values.sql"),
                read_sql("views.sql"),
            ]),
            reverse_sql=read_sql("rollback.sql"),
        ),
    ]

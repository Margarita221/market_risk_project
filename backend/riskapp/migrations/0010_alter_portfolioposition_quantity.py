from pathlib import Path

from django.db import migrations, models


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


DROP_VIEWS_SQL = """
DROP VIEW IF EXISTS scenario_result_summary;
DROP VIEW IF EXISTS portfolio_position_summary;
DROP VIEW IF EXISTS portfolio_summary;
"""


def read_sql(filename):
    return (SQL_DIR / filename).read_text(encoding="utf-8")


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0009_scenario_noise_level_constraint"),
    ]

    operations = [
        migrations.RunSQL(
            sql=DROP_VIEWS_SQL,
            reverse_sql=read_sql("views.sql"),
        ),
        migrations.AlterField(
            model_name="portfolioposition",
            name="quantity",
            field=models.PositiveIntegerField(),
        ),
        migrations.RunSQL(
            sql=read_sql("views.sql"),
            reverse_sql=DROP_VIEWS_SQL,
        ),
    ]

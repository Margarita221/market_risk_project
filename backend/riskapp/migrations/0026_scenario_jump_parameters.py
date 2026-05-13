from decimal import Decimal

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0025_trade_operation_execution_details"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="jump_intensity",
            field=models.DecimalField(decimal_places=3, default=Decimal("0.200"), max_digits=6),
        ),
        migrations.AddField(
            model_name="scenario",
            name="jump_magnitude",
            field=models.DecimalField(decimal_places=6, default=Decimal("0.040000"), max_digits=10),
        ),
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.CheckConstraint(
                condition=Q(jump_intensity__gte=0),
                name="scenario_jump_intensity_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.CheckConstraint(
                condition=Q(jump_intensity__lte=5),
                name="scenario_jump_intensity_lte_5",
            ),
        ),
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.CheckConstraint(
                condition=Q(jump_magnitude__gte=0),
                name="scenario_jump_magnitude_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.CheckConstraint(
                condition=Q(jump_magnitude__lte=1),
                name="scenario_jump_magnitude_lte_1",
            ),
        ),
    ]

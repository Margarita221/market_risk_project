import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("riskapp", "0020_scenario_inflation_and_mean_reversion"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TradeOperation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation_type", models.CharField(choices=[("BUY", "Buy"), ("SELL", "Sell")], max_length=4)),
                ("quantity", models.PositiveIntegerField()),
                ("price_per_unit", models.DecimalField(decimal_places=4, max_digits=15)),
                ("commission", models.DecimalField(decimal_places=4, default=0, max_digits=15)),
                ("realized_pnl", models.DecimalField(blank=True, decimal_places=4, max_digits=15, null=True)),
                ("executed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("comment", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "instrument",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="trade_operations", to="riskapp.instrument"),
                ),
                (
                    "portfolio",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="trade_operations", to="riskapp.portfolio"),
                ),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="trade_operations", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "verbose_name": "Trade operation",
                "verbose_name_plural": "Trade operations",
                "db_table": "trade_operation",
                "ordering": ["-executed_at", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="tradeoperation",
            constraint=models.CheckConstraint(condition=Q(quantity__gt=0), name="trade_operation_quantity_gt_0"),
        ),
        migrations.AddConstraint(
            model_name="tradeoperation",
            constraint=models.CheckConstraint(condition=Q(price_per_unit__gte=0), name="trade_operation_price_gte_0"),
        ),
        migrations.AddConstraint(
            model_name="tradeoperation",
            constraint=models.CheckConstraint(condition=Q(commission__gte=0), name="trade_operation_commission_gte_0"),
        ),
    ]

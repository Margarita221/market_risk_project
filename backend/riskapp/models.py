from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User


class Instrument(models.Model):
    ticker = models.CharField(max_length=20, unique=True, verbose_name='Тикер')
    name = models.CharField(max_length=200, verbose_name='Наименование')
    instrument_type = models.CharField(max_length=50, verbose_name='Тип инструмента')
    currency = models.CharField(max_length=10, verbose_name='Валюта')
    current_price = models.DecimalField(max_digits=15, decimal_places=4, verbose_name='Текущая цена')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')

    class Meta:
        db_table = 'instrument'
        verbose_name = 'Финансовый инструмент'
        verbose_name_plural = 'Финансовые инструменты'
        ordering = ['ticker']
        constraints = [
            models.CheckConstraint(
                condition=Q(current_price__gte=0),
                name='instrument_current_price_gte_0'
            )
        ]

    def __str__(self):
        return f'{self.ticker} - {self.name}'


class Portfolio(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolios')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    initial_value = models.DecimalField(max_digits=15, decimal_places=2)
    current_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portfolio'
        ordering = ['created_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(initial_value__gte=0),
                name='portfolio_initial_value_gte_0'
            )
        ]

    def __str__(self):
        return self.name


class PortfolioPosition(models.Model):
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='positions'
    )
    instrument = models.ForeignKey(
        Instrument,
        on_delete=models.CASCADE
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    average_purchase_price = models.DecimalField(max_digits=15, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'portfolio_position'
        constraints = [
            models.UniqueConstraint(
                fields=['portfolio', 'instrument'],
                name='unique_portfolio_instrument'
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name='portfolio_position_quantity_gt_0'
            ),
            models.CheckConstraint(
                condition=Q(average_purchase_price__gte=0),
                name='portfolio_position_avg_price_gte_0'
            ),
        ]

    def __str__(self):
        return f"{self.portfolio} - {self.instrument}"


class Scenario(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='scenarios'
    )
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='scenarios'
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    trend = models.DecimalField(max_digits=10, decimal_places=6)
    volatility = models.DecimalField(max_digits=10, decimal_places=6)
    noise_level = models.DecimalField(max_digits=10, decimal_places=6)
    time_horizon = models.PositiveIntegerField()
    time_step = models.DecimalField(max_digits=10, decimal_places=4)
    iterations_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scenario'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(volatility__gte=0),
                name='scenario_volatility_gte_0'
            ),
            models.CheckConstraint(
                condition=Q(time_horizon__gt=0),
                name='scenario_time_horizon_gt_0'
            ),
            models.CheckConstraint(
                condition=Q(time_step__gt=0),
                name='scenario_time_step_gt_0'
            ),
            models.CheckConstraint(
                condition=Q(iterations_count__gt=0),
                name='scenario_iterations_count_gt_0'
            ),
        ]

    def __str__(self):
        return self.name


class SimulationResult(models.Model):
    scenario = models.ForeignKey(
        Scenario,
        on_delete=models.CASCADE,
        related_name='results'
    )
    execution_time = models.DateTimeField(auto_now_add=True)
    expected_return = models.DecimalField(max_digits=12, decimal_places=6)
    portfolio_volatility = models.DecimalField(max_digits=12, decimal_places=6)
    final_value = models.DecimalField(max_digits=15, decimal_places=2)
    max_drawdown = models.DecimalField(max_digits=12, decimal_places=6)
    status = models.CharField(max_length=30)
    comment = models.TextField(blank=True)

    class Meta:
        db_table = 'simulation_result'
        ordering = ['-execution_time']
        constraints = [
            models.CheckConstraint(
                condition=Q(final_value__gte=0),
                name='simulation_result_final_value_gte_0'
            ),
            models.CheckConstraint(
                condition=Q(max_drawdown__gte=0),
                name='simulation_result_max_drawdown_gte_0'
            ),
        ]

    def __str__(self):
        return f"Result #{self.id} for {self.scenario.name}"


class RiskMetric(models.Model):
    simulation_result = models.ForeignKey(
        SimulationResult,
        on_delete=models.CASCADE,
        related_name='risk_metrics'
    )
    metric_name = models.CharField(max_length=100)
    metric_value = models.DecimalField(max_digits=15, decimal_places=6)
    confidence_level = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'risk_metric'
        ordering = ['metric_name']
        constraints = [
            models.CheckConstraint(
                condition=Q(confidence_level__gte=0) | Q(confidence_level__isnull=True),
                name='risk_metric_confidence_level_gte_0_or_null'
            ),
            models.CheckConstraint(
                condition=Q(confidence_level__lte=100) | Q(confidence_level__isnull=True),
                name='risk_metric_confidence_level_lte_100_or_null'
            ),
        ]

    def __str__(self):
        return f"{self.metric_name}: {self.metric_value}"

from django.db import models
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

    def __str__(self):
        return f'{self.ticker} - {self.name}'

class Portfolio(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolios')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    initial_value = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'portfolio'
        ordering = ['created_at']

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
        unique_together = ('portfolio', 'instrument')

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

    class Meta:
        db_table = 'scenario'
        ordering = ['-created_at']

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

    def __str__(self):
        return f"Result #{self.id} for {self.scenario.name}"


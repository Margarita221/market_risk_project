from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Instrument(models.Model):
    TYPE_STOCK = "stock"
    TYPE_BOND = "bond"
    TYPE_ETF = "etf"
    TYPE_CHOICES = [
        (TYPE_STOCK, "Stock"),
        (TYPE_BOND, "Bond"),
        (TYPE_ETF, "ETF"),
    ]
    SECTOR_EQUITIES = "Equities"
    SECTOR_BONDS = "Bonds"
    SECTOR_FUNDS = "Funds"
    SECTOR_CHOICES = [
        (SECTOR_EQUITIES, "Equities"),
        (SECTOR_BONDS, "Bonds"),
        (SECTOR_FUNDS, "Funds"),
    ]

    ticker = models.CharField(max_length=20, unique=True, verbose_name="Ticker")
    name = models.CharField(max_length=200, verbose_name="Name")
    instrument_type = models.CharField(max_length=50, verbose_name="Instrument type")
    sector = models.CharField(max_length=100, blank=True, default="", verbose_name="Sector")
    currency = models.CharField(max_length=10, verbose_name="Currency")
    current_price = models.DecimalField(max_digits=15, decimal_places=4, verbose_name="Current price")
    dividend_yield = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"), verbose_name="Dividend yield")
    coupon_yield = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"), verbose_name="Coupon yield")
    last_price_updated_at = models.DateTimeField(null=True, blank=True, verbose_name="Price updated at")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created at")

    class Meta:
        db_table = "instrument"
        verbose_name = "Financial instrument"
        verbose_name_plural = "Financial instruments"
        ordering = ["ticker"]
        constraints = [
            models.CheckConstraint(
                condition=Q(current_price__gte=0),
                name="instrument_current_price_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(dividend_yield__gte=0),
                name="instrument_dividend_yield_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(coupon_yield__gte=0),
                name="instrument_coupon_yield_gte_0",
            ),
        ]

    def __str__(self):
        return f"{self.ticker} - {self.name}"

    @classmethod
    def known_sectors(cls):
        return [value for value, _ in cls.SECTOR_CHOICES]

    @classmethod
    def normalize_instrument_type(cls, value):
        normalized = (value or "").strip().lower()
        if normalized in {"stock", "share", "shares", "equity", "equities"}:
            return cls.TYPE_STOCK
        if normalized in {"bond", "bonds"}:
            return cls.TYPE_BOND
        if normalized in {"etf", "fund", "funds"}:
            return cls.TYPE_ETF
        return normalized or cls.TYPE_STOCK

    @classmethod
    def infer_sector(cls, instrument_type):
        normalized = cls.normalize_instrument_type(instrument_type)
        if normalized == cls.TYPE_BOND:
            return cls.SECTOR_BONDS
        if normalized == cls.TYPE_ETF:
            return cls.SECTOR_FUNDS
        return cls.SECTOR_EQUITIES

    @property
    def normalized_type(self):
        return self.normalize_instrument_type(self.instrument_type)

    @property
    def display_type(self):
        mapping = {
            self.TYPE_STOCK: "Stock",
            self.TYPE_BOND: "Bond",
            self.TYPE_ETF: "ETF",
        }
        return mapping.get(self.normalized_type, self.instrument_type)


class InstrumentPriceHistory(models.Model):
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="price_history")
    price = models.DecimalField(max_digits=15, decimal_places=4, verbose_name="Captured price")
    currency = models.CharField(max_length=10, verbose_name="Captured currency")
    source = models.CharField(max_length=30, default="MOEX", verbose_name="Source")
    captured_at = models.DateTimeField(auto_now_add=True, verbose_name="Captured at")

    class Meta:
        db_table = "instrument_price_history"
        verbose_name = "Instrument price history"
        verbose_name_plural = "Instrument price history"
        ordering = ["-captured_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name="instrument_price_history_price_gte_0",
            )
        ]

    def __str__(self):
        return f"{self.instrument.ticker} @ {self.price}"


class Portfolio(models.Model):
    CURRENCY_RUB = "RUB"
    CURRENCY_USD = "USD"
    CURRENCY_EUR = "EUR"
    BASE_CURRENCY_CHOICES = [
        (CURRENCY_RUB, "RUB"),
        (CURRENCY_USD, "USD"),
        (CURRENCY_EUR, "EUR"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="portfolios")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    base_currency = models.CharField(max_length=10, default=CURRENCY_RUB)
    initial_value = models.DecimalField(max_digits=15, decimal_places=2)
    current_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "portfolio"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(initial_value__gte=0),
                name="portfolio_initial_value_gte_0",
            )
        ]

    def __str__(self):
        return self.name


class ExchangeRate(models.Model):
    from_currency = models.CharField(max_length=10, verbose_name="From currency")
    to_currency = models.CharField(max_length=10, verbose_name="To currency")
    rate = models.DecimalField(max_digits=18, decimal_places=8, verbose_name="Rate")
    rate_date = models.DateField(verbose_name="Rate date")
    source = models.CharField(max_length=30, default="CBR", verbose_name="Source")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created at")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated at")

    class Meta:
        db_table = "exchange_rate"
        verbose_name = "Exchange rate"
        verbose_name_plural = "Exchange rates"
        ordering = ["-rate_date", "from_currency", "to_currency"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_currency", "to_currency", "rate_date"],
                name="unique_exchange_rate_pair_date",
            ),
            models.CheckConstraint(
                condition=Q(rate__gt=0),
                name="exchange_rate_rate_gt_0",
            ),
        ]

    def __str__(self):
        return f"{self.from_currency}/{self.to_currency} = {self.rate}"


class PortfolioPosition(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="positions")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    average_purchase_price = models.DecimalField(max_digits=15, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "portfolio_position"
        constraints = [
            models.UniqueConstraint(
                fields=["portfolio", "instrument"],
                name="unique_portfolio_instrument",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="portfolio_position_quantity_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(average_purchase_price__gte=0),
                name="portfolio_position_avg_price_gte_0",
            ),
        ]

    def __str__(self):
        return f"{self.portfolio} - {self.instrument}"


class TradeOperation(models.Model):
    TYPE_BUY = "BUY"
    TYPE_SELL = "SELL"
    TYPE_CHOICES = [
        (TYPE_BUY, "Buy"),
        (TYPE_SELL, "Sell"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trade_operations")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="trade_operations")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="trade_operations")
    operation_type = models.CharField(max_length=4, choices=TYPE_CHOICES)
    quantity = models.PositiveIntegerField()
    quoted_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    price_per_unit = models.DecimalField(max_digits=15, decimal_places=4)
    slippage_rate = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    slippage_amount = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    commission = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    realized_pnl = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    cash_balance_after = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    executed_at = models.DateTimeField(default=timezone.now)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "trade_operation"
        ordering = ["-executed_at", "-created_at"]
        verbose_name = "Trade operation"
        verbose_name_plural = "Trade operations"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="trade_operation_quantity_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(price_per_unit__gte=0),
                name="trade_operation_price_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(quoted_price__gte=0),
                name="trade_operation_quoted_price_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(slippage_rate__gte=0),
                name="trade_operation_slippage_rate_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(slippage_amount__gte=0),
                name="trade_operation_slippage_amount_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(commission__gte=0),
                name="trade_operation_commission_gte_0",
            ),
        ]

    def __str__(self):
        return f"{self.operation_type} {self.instrument.ticker} x{self.quantity}"

    @property
    def gross_amount(self):
        return Decimal(str(self.quantity)) * self.price_per_unit

    @property
    def net_amount(self):
        if self.operation_type == self.TYPE_BUY:
            return self.gross_amount + self.commission
        return self.gross_amount - self.commission


class Scenario(models.Model):
    PRESET_CUSTOM = "custom"
    PRESET_BASE = "base"
    PRESET_OPTIMISTIC = "optimistic"
    PRESET_PESSIMISTIC = "pessimistic"
    PRESET_STRESS = "stress"
    PRESET_CRISIS = "crisis"
    PRESET_CHOICES = [
        (PRESET_CUSTOM, "Custom"),
        (PRESET_BASE, "Base"),
        (PRESET_OPTIMISTIC, "Optimistic"),
        (PRESET_PESSIMISTIC, "Pessimistic"),
        (PRESET_STRESS, "Stress"),
        (PRESET_CRISIS, "Crisis"),
    ]
    REBALANCE_NONE = "none"
    REBALANCE_MONTHLY = "monthly"
    REBALANCE_QUARTERLY = "quarterly"
    REBALANCING_CHOICES = [
        (REBALANCE_NONE, "Buy and hold"),
        (REBALANCE_MONTHLY, "Monthly rebalance"),
        (REBALANCE_QUARTERLY, "Quarterly rebalance"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scenarios")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="scenarios")
    preset = models.CharField(max_length=20, choices=PRESET_CHOICES, default=PRESET_CUSTOM)
    rebalancing_frequency = models.CharField(max_length=20, choices=REBALANCING_CHOICES, default=REBALANCE_NONE)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    trend = models.DecimalField(max_digits=10, decimal_places=6)
    volatility = models.DecimalField(max_digits=10, decimal_places=6)
    noise_level = models.DecimalField(max_digits=10, decimal_places=6)
    market_shock = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    currency_shock = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    inflation_shock = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    sector_target = models.CharField(max_length=100, blank=True, default="")
    sector_shock = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    interest_rate_shock = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    jump_intensity = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0.200"))
    jump_magnitude = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0.040000"))
    systematic_risk = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.6500"))
    mean_reversion_strength = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.1500"))
    time_horizon = models.PositiveIntegerField()
    time_step = models.DecimalField(max_digits=10, decimal_places=4)
    iterations_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "scenario"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(volatility__gte=0),
                name="scenario_volatility_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(noise_level__gte=0),
                name="scenario_noise_level_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(systematic_risk__gte=0),
                name="scenario_systematic_risk_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(systematic_risk__lte=1),
                name="scenario_systematic_risk_lte_1",
            ),
            models.CheckConstraint(
                condition=Q(mean_reversion_strength__gte=0),
                name="scenario_mean_reversion_strength_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(mean_reversion_strength__lte=1),
                name="scenario_mean_reversion_strength_lte_1",
            ),
            models.CheckConstraint(
                condition=Q(jump_intensity__gte=0),
                name="scenario_jump_intensity_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(jump_intensity__lte=5),
                name="scenario_jump_intensity_lte_5",
            ),
            models.CheckConstraint(
                condition=Q(jump_magnitude__gte=0),
                name="scenario_jump_magnitude_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(jump_magnitude__lte=1),
                name="scenario_jump_magnitude_lte_1",
            ),
            models.CheckConstraint(
                condition=Q(time_horizon__gt=0),
                name="scenario_time_horizon_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(time_step__gt=0),
                name="scenario_time_step_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(iterations_count__gt=0),
                name="scenario_iterations_count_gt_0",
            ),
        ]

    def __str__(self):
        return self.name


class SimulationResult(models.Model):
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="results")
    execution_time = models.DateTimeField(auto_now_add=True)
    expected_return = models.DecimalField(max_digits=12, decimal_places=6)
    portfolio_volatility = models.DecimalField(max_digits=12, decimal_places=6)
    final_value = models.DecimalField(max_digits=15, decimal_places=2)
    max_drawdown = models.DecimalField(max_digits=12, decimal_places=6)
    status = models.CharField(max_length=30)
    comment = models.TextField(blank=True)
    chart_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "simulation_result"
        ordering = ["-execution_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(final_value__gte=0),
                name="simulation_result_final_value_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(max_drawdown__gte=0),
                name="simulation_result_max_drawdown_gte_0",
            ),
        ]

    def __str__(self):
        return f"Result #{self.id} for {self.scenario.name}"


class RiskMetric(models.Model):
    simulation_result = models.ForeignKey(
        SimulationResult,
        on_delete=models.CASCADE,
        related_name="risk_metrics",
    )
    metric_name = models.CharField(max_length=100)
    metric_value = models.DecimalField(max_digits=15, decimal_places=6)
    confidence_level = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "risk_metric"
        ordering = ["metric_name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(confidence_level__gte=0) | Q(confidence_level__isnull=True),
                name="risk_metric_confidence_level_gte_0_or_null",
            ),
            models.CheckConstraint(
                condition=Q(confidence_level__lte=100) | Q(confidence_level__isnull=True),
                name="risk_metric_confidence_level_lte_100_or_null",
            ),
        ]

    def __str__(self):
        return f"{self.metric_name}: {self.metric_value}"

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db.models import Count

from .models import (
    ExchangeRate,
    Instrument,
    InstrumentPriceHistory,
    Portfolio,
    PortfolioPosition,
    RiskMetric,
    Scenario,
    SimulationResult,
    TradeOperation,
)


admin.site.site_header = "Страница администратора Market Risk"
admin.site.site_title = "Страница администратора"
admin.site.index_title = "Управление пользователями, портфелями, сценариями и рыночными данными"


class PortfolioPositionInline(admin.TabularInline):
    model = PortfolioPosition
    extra = 0


@admin.action(description="Заблокировать выбранных пользователей")
def block_users(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.action(description="Разблокировать выбранных пользователей")
def unblock_users(modeladmin, request, queryset):
    queryset.update(is_active=True)


class MarketRiskUserAdmin(UserAdmin):
    actions = [block_users, unblock_users]
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "portfolios_count",
        "scenarios_count",
        "last_login",
    )
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(
            portfolios_total=Count("portfolios", distinct=True),
            scenarios_total=Count("scenarios", distinct=True),
        )

    @admin.display(description="Портфели", ordering="portfolios_total")
    def portfolios_count(self, obj):
        return obj.portfolios_total

    @admin.display(description="Сценарии", ordering="scenarios_total")
    def scenarios_count(self, obj):
        return obj.scenarios_total


admin.site.unregister(User)
admin.site.register(User, MarketRiskUserAdmin)


@admin.register(RiskMetric)
class RiskMetricAdmin(admin.ModelAdmin):
    list_display = ("metric_name", "metric_value", "confidence_level", "simulation_result", "calculated_at")
    search_fields = ("metric_name", "simulation_result__scenario__name")
    list_filter = ("calculated_at",)


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = (
        "ticker",
        "name",
        "instrument_type",
        "sector",
        "currency",
        "current_price",
        "dividend_yield",
        "coupon_yield",
        "last_price_updated_at",
        "created_at",
    )
    search_fields = ("ticker", "name")
    list_filter = ("instrument_type", "sector", "currency")
    ordering = ("ticker",)


@admin.register(InstrumentPriceHistory)
class InstrumentPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ("instrument", "price", "currency", "source", "captured_at")
    search_fields = ("instrument__ticker", "instrument__name", "source")
    list_filter = ("currency", "source", "captured_at")
    ordering = ("-captured_at",)


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "base_currency", "initial_value", "current_value", "created_at", "updated_at")
    readonly_fields = ("current_value", "created_at", "updated_at")
    search_fields = ("name", "user__username", "user__email")
    list_filter = ("base_currency", "created_at", "updated_at")
    inlines = [PortfolioPositionInline]


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("from_currency", "to_currency", "rate", "rate_date", "source", "updated_at")
    search_fields = ("from_currency", "to_currency", "source")
    list_filter = ("source", "rate_date", "to_currency")
    ordering = ("-rate_date", "from_currency", "to_currency")


@admin.register(PortfolioPosition)
class PortfolioPositionAdmin(admin.ModelAdmin):
    list_display = ("portfolio", "instrument", "quantity", "average_purchase_price", "created_at")
    search_fields = ("portfolio__name", "instrument__ticker", "instrument__name")
    list_filter = ("created_at", "instrument__instrument_type")


@admin.register(TradeOperation)
class TradeOperationAdmin(admin.ModelAdmin):
    list_display = (
        "executed_at",
        "portfolio",
        "instrument",
        "operation_type",
        "quantity",
        "price_per_unit",
        "commission",
        "realized_pnl",
        "user",
    )
    search_fields = ("portfolio__name", "instrument__ticker", "instrument__name", "user__username")
    list_filter = ("operation_type", "executed_at", "instrument__instrument_type")
    ordering = ("-executed_at", "-created_at")


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "portfolio",
        "preset",
        "trend",
        "volatility",
        "market_shock",
        "currency_shock",
        "sector_target",
        "sector_shock",
        "interest_rate_shock",
        "systematic_risk",
        "iterations_count",
        "created_at",
    )
    search_fields = ("name", "user__username", "portfolio__name")
    list_filter = ("created_at", "updated_at")


@admin.register(SimulationResult)
class SimulationResultAdmin(admin.ModelAdmin):
    list_display = (
        "scenario",
        "execution_time",
        "expected_return",
        "portfolio_volatility",
        "final_value",
        "max_drawdown",
        "status",
    )
    search_fields = ("scenario__name", "scenario__portfolio__name", "scenario__user__username")
    list_filter = ("status", "execution_time")

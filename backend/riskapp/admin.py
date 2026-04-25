from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db.models import Count

from .models import Instrument, Portfolio, PortfolioPosition, RiskMetric, Scenario, SimulationResult


admin.site.site_header = "Страница админа Market Risk"
admin.site.site_title = "Страница админа"
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
    list_display = ("ticker", "name", "instrument_type", "currency", "current_price", "created_at")
    search_fields = ("ticker", "name")
    list_filter = ("instrument_type", "currency")
    ordering = ("ticker",)


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "initial_value", "current_value", "created_at", "updated_at")
    readonly_fields = ("current_value", "created_at", "updated_at")
    search_fields = ("name", "user__username", "user__email")
    list_filter = ("created_at", "updated_at")
    inlines = [PortfolioPositionInline]


@admin.register(PortfolioPosition)
class PortfolioPositionAdmin(admin.ModelAdmin):
    list_display = ("portfolio", "instrument", "quantity", "average_purchase_price", "created_at")
    search_fields = ("portfolio__name", "instrument__ticker", "instrument__name")
    list_filter = ("created_at", "instrument__instrument_type")


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "portfolio", "trend", "volatility", "iterations_count", "created_at")
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

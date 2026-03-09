from django.contrib import admin
from .models import Instrument, Portfolio, PortfolioPosition, Scenario, SimulationResult


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ("ticker", "name", "instrument_type", "currency", "current_price")
    search_fields = ("ticker", "name")


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "initial_value", "created_at")


@admin.register(PortfolioPosition)
class PortfolioPositionAdmin(admin.ModelAdmin):
    list_display = ("portfolio", "instrument", "quantity", "average_purchase_price")


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "portfolio", "created_at")


@admin.register(SimulationResult)
class SimulationResultAdmin(admin.ModelAdmin):
    list_display = ("scenario", "execution_time", "expected_return", "portfolio_volatility")
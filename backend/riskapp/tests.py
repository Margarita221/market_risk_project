from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from riskapp.models import Instrument, Portfolio, PortfolioPosition, RiskMetric, Scenario, SimulationResult
from riskapp.services.simulation import run_scenario_simulation


class ScenarioSimulationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="investor", password="password")
        self.instrument = Instrument.objects.create(
            ticker="TEST",
            name="Test instrument",
            instrument_type="stock",
            currency="USD",
            current_price=Decimal("100.0000"),
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            name="Test portfolio",
            initial_value=Decimal("1000.00"),
        )
        PortfolioPosition.objects.create(
            portfolio=self.portfolio,
            instrument=self.instrument,
            quantity=Decimal("10.0000"),
            average_purchase_price=Decimal("90.0000"),
        )
        self.scenario = Scenario.objects.create(
            user=self.user,
            portfolio=self.portfolio,
            name="Base scenario",
            trend=Decimal("0.001000"),
            volatility=Decimal("0.010000"),
            noise_level=Decimal("0.001000"),
            time_horizon=10,
            time_step=Decimal("1.0000"),
            iterations_count=20,
        )

    def test_run_scenario_simulation_creates_result_and_metrics(self):
        summary = run_scenario_simulation(self.scenario.id, seed=42)

        self.assertEqual(SimulationResult.objects.count(), 1)
        self.assertEqual(summary.result.status, "completed")
        self.assertEqual(RiskMetric.objects.filter(simulation_result=summary.result).count(), 5)

    def test_run_scenario_simulation_rejects_empty_portfolio(self):
        empty_portfolio = Portfolio.objects.create(
            user=self.user,
            name="Empty portfolio",
            initial_value=Decimal("0.00"),
        )
        scenario = Scenario.objects.create(
            user=self.user,
            portfolio=empty_portfolio,
            name="Empty scenario",
            trend=Decimal("0.001000"),
            volatility=Decimal("0.010000"),
            noise_level=Decimal("0.001000"),
            time_horizon=10,
            time_step=Decimal("1.0000"),
            iterations_count=20,
        )

        with self.assertRaises(ValueError):
            run_scenario_simulation(scenario.id, seed=42)

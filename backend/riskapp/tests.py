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
            quantity=10,
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
        self.assertIn("average_path", summary.result.chart_data)
        self.assertIn("sample_paths", summary.result.chart_data)
        self.assertIn("position_paths", summary.result.chart_data)
        self.assertGreater(len(summary.result.chart_data["average_path"]), 1)
        self.assertEqual(len(summary.result.chart_data["position_paths"]), 1)

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


class RiskAppWebUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="webuser", password="password")
        self.other_user = User.objects.create_user(username="otheruser", password="password")
        self.admin_user = User.objects.create_superuser(
            username="adminuser",
            password="password",
            email="admin@example.com",
        )
        self.instrument = Instrument.objects.create(
            ticker="WEB",
            name="Web instrument",
            instrument_type="stock",
            currency="USD",
            current_price=Decimal("50.0000"),
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            name="Web portfolio",
            initial_value=Decimal("500.00"),
        )
        PortfolioPosition.objects.create(
            portfolio=self.portfolio,
            instrument=self.instrument,
            quantity=10,
            average_purchase_price=Decimal("45.0000"),
        )
        self.scenario = Scenario.objects.create(
            user=self.user,
            portfolio=self.portfolio,
            name="Web scenario",
            trend=Decimal("0.030000"),
            volatility=Decimal("0.070000"),
            noise_level=Decimal("0.005000"),
            time_horizon=30,
            time_step=Decimal("1.0000"),
            iterations_count=20,
        )
        self.other_portfolio = Portfolio.objects.create(
            user=self.other_user,
            name="Other user portfolio",
            initial_value=Decimal("200.00"),
        )
        self.other_scenario = Scenario.objects.create(
            user=self.other_user,
            portfolio=self.other_portfolio,
            name="Other user scenario",
            trend=Decimal("0.010000"),
            volatility=Decimal("0.020000"),
            noise_level=Decimal("0.001000"),
            time_horizon=15,
            time_step=Decimal("1.0000"),
            iterations_count=10,
        )

    def test_dashboard_requires_login(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_authenticated_user_can_open_dashboard(self):
        self.client.force_login(self.user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Рабочее пространство моделирования портфельных рисков")

    def test_user_can_switch_ui_language_to_english(self):
        self.client.force_login(self.user)

        self.client.get("/language/en/")
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Portfolio risk modelling workspace")

    def test_run_scenario_view_creates_result(self):
        self.client.force_login(self.user)

        response = self.client.post(f"/scenarios/{self.scenario.id}/run/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(SimulationResult.objects.filter(scenario=self.scenario).count(), 1)
        self.assertTrue(SimulationResult.objects.get(scenario=self.scenario).chart_data)

    def test_user_can_create_configured_scenario_from_portfolio(self):
        self.client.force_login(self.user)

        response = self.client.post(f"/portfolios/{self.portfolio.id}/scenarios/run/", {
            "name": "Configured scenario",
            "description": "Changed from web",
            "trend": "0.040",
            "volatility": "0.120",
            "noise_level": "0.010",
            "time_horizon": "60",
            "time_step": "1",
            "iterations_count": "30",
        })

        scenario = Scenario.objects.get(name="Configured scenario")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(scenario.portfolio, self.portfolio)
        self.assertEqual(SimulationResult.objects.filter(scenario=scenario).count(), 1)

    def test_user_can_create_portfolio_from_web(self):
        self.client.force_login(self.user)

        response = self.client.post("/portfolios/create/", {
            "name": "Created from UI",
            "description": "Created portfolio description",
        })

        portfolio = Portfolio.objects.get(name="Created from UI")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(portfolio.user, self.user)
        self.assertEqual(portfolio.initial_value, Decimal("0"))

    def test_user_can_add_position_to_portfolio_from_web(self):
        self.client.force_login(self.user)
        portfolio = Portfolio.objects.create(
            user=self.user,
            name="Position target",
            initial_value=Decimal("0.00"),
        )

        response = self.client.post(f"/portfolios/{portfolio.id}/positions/add/", {
            "instrument": self.instrument.id,
            "quantity": "3",
        })

        position = PortfolioPosition.objects.get(portfolio=portfolio, instrument=self.instrument)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(position.quantity, 3)
        self.assertEqual(position.average_purchase_price, self.instrument.current_price)

    def test_user_can_update_portfolio_from_web(self):
        self.client.force_login(self.user)

        response = self.client.post(f"/portfolios/{self.portfolio.id}/edit/", {
            "name": "Updated portfolio",
            "description": "Updated description",
        })

        self.portfolio.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.portfolio.name, "Updated portfolio")
        self.assertEqual(self.portfolio.description, "Updated description")

    def test_user_can_delete_portfolio_from_web(self):
        self.client.force_login(self.user)
        portfolio = Portfolio.objects.create(
            user=self.user,
            name="Portfolio to delete",
            initial_value=Decimal("0.00"),
        )

        response = self.client.post(f"/portfolios/{portfolio.id}/delete/")

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Portfolio.objects.filter(id=portfolio.id).exists())

    def test_user_can_update_position_quantity_from_web(self):
        self.client.force_login(self.user)
        position = PortfolioPosition.objects.get(portfolio=self.portfolio, instrument=self.instrument)

        response = self.client.post(
            f"/portfolios/{self.portfolio.id}/positions/{position.id}/update/",
            {"quantity": "7"},
        )

        position.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(position.quantity, 7)

    def test_user_can_delete_position_from_web(self):
        self.client.force_login(self.user)
        position = PortfolioPosition.objects.get(portfolio=self.portfolio, instrument=self.instrument)

        response = self.client.post(f"/portfolios/{self.portfolio.id}/positions/{position.id}/delete/")

        self.assertEqual(response.status_code, 302)
        self.assertFalse(PortfolioPosition.objects.filter(id=position.id).exists())

    def test_regular_user_cannot_open_other_user_portfolio(self):
        self.client.force_login(self.user)

        response = self.client.get(f"/portfolios/{self.other_portfolio.id}/")

        self.assertEqual(response.status_code, 404)

    def test_regular_user_cannot_run_other_user_scenario(self):
        self.client.force_login(self.user)

        response = self.client.post(f"/scenarios/{self.other_scenario.id}/run/")

        self.assertEqual(response.status_code, 404)

    def test_admin_can_open_other_user_portfolio(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(f"/portfolios/{self.other_portfolio.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Other user portfolio")

    def test_admin_can_open_admin_site(self):
        self.client.force_login(self.admin_user)

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)

    def test_regular_user_cannot_open_admin_site(self):
        self.client.force_login(self.user)

        response = self.client.get("/admin/")

        self.assertNotEqual(response.status_code, 200)

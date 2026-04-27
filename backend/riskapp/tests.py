from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from riskapp.models import Instrument, Portfolio, PortfolioPosition, RiskMetric, Scenario, SimulationResult
from riskapp.services.moex import fetch_market_snapshot, sync_moex_instruments
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
        self.bond = Instrument.objects.create(
            ticker="BOND",
            name="Test bond",
            instrument_type="bond",
            currency="RUB",
            current_price=Decimal("1000.0000"),
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
        PortfolioPosition.objects.create(
            portfolio=self.portfolio,
            instrument=self.bond,
            quantity=2,
            average_purchase_price=Decimal("980.0000"),
        )
        self.scenario = Scenario.objects.create(
            user=self.user,
            portfolio=self.portfolio,
            name="Base scenario",
            preset=Scenario.PRESET_BASE,
            trend=Decimal("0.001000"),
            volatility=Decimal("0.010000"),
            noise_level=Decimal("0.001000"),
            market_shock=Decimal("0.000000"),
            currency_shock=Decimal("0.000000"),
            systematic_risk=Decimal("0.6500"),
            time_horizon=10,
            time_step=Decimal("1.0000"),
            iterations_count=20,
        )

    def test_run_scenario_simulation_creates_result_and_metrics(self):
        summary = run_scenario_simulation(self.scenario.id, seed=42)

        self.assertEqual(SimulationResult.objects.count(), 1)
        self.assertEqual(summary.result.status, "completed")
        self.assertEqual(RiskMetric.objects.filter(simulation_result=summary.result).count(), 10)
        self.assertIn("average_path", summary.result.chart_data)
        self.assertIn("sample_paths", summary.result.chart_data)
        self.assertIn("position_paths", summary.result.chart_data)
        self.assertIn("median_final_value", summary.result.chart_data)
        self.assertIn("probability_of_loss_percent", summary.result.chart_data)
        self.assertGreater(len(summary.result.chart_data["average_path"]), 1)
        self.assertEqual(len(summary.result.chart_data["position_paths"]), 2)
        self.assertTrue(
            RiskMetric.objects.filter(
                simulation_result=summary.result,
                metric_name="Probability of Loss",
            ).exists()
        )

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
            preset=Scenario.PRESET_BASE,
            trend=Decimal("0.001000"),
            volatility=Decimal("0.010000"),
            noise_level=Decimal("0.001000"),
            market_shock=Decimal("0.000000"),
            currency_shock=Decimal("0.000000"),
            systematic_risk=Decimal("0.6500"),
            time_horizon=10,
            time_step=Decimal("1.0000"),
            iterations_count=20,
        )

        with self.assertRaises(ValueError):
            run_scenario_simulation(scenario.id, seed=42)


class MoexImportServiceTests(TestCase):
    @patch("riskapp.services.moex._fetch_json")
    def test_fetch_market_snapshot_maps_security_rows(self, mocked_fetch):
        mocked_fetch.return_value = {
            "securities": {
                "columns": ["SECID", "SHORTNAME", "FACEUNIT"],
                "data": [["SBER", "Sberbank", "SUR"]],
            },
            "marketdata": {
                "columns": ["SECID", "LAST", "MARKETPRICE"],
                "data": [["SBER", 312.45, None]],
            },
        }

        rows = fetch_market_snapshot("shares")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "SBER")
        self.assertEqual(rows[0]["name"], "Sberbank")
        self.assertEqual(rows[0]["currency"], "RUB")
        self.assertEqual(rows[0]["current_price"], Decimal("312.45"))

    @patch("riskapp.services.moex.iter_market_snapshots")
    def test_sync_moex_instruments_creates_and_updates_instruments(self, mocked_iter):
        mocked_iter.return_value = iter([
            ("shares", {"ticker": "SBER", "name": "Sberbank", "currency": "RUB", "current_price": Decimal("300.10")}),
            ("bonds", {"ticker": "OFZ26238", "name": "OFZ 26238", "currency": "RUB", "current_price": Decimal("102.55")}),
        ])

        stats = sync_moex_instruments(markets=["shares", "bonds"])

        self.assertEqual(stats.created, 2)
        self.assertEqual(stats.updated, 0)
        self.assertEqual(stats.skipped, 0)
        self.assertEqual(Instrument.objects.count(), 2)
        self.assertEqual(Instrument.objects.get(ticker="SBER").instrument_type, "stock")
        self.assertEqual(Instrument.objects.get(ticker="OFZ26238").instrument_type, "bond")
        self.assertIsNotNone(Instrument.objects.get(ticker="SBER").last_price_updated_at)


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

    def test_user_can_create_scenario_from_scenarios_page(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("riskapp:scenario_create"),
            {
                "preset": Scenario.PRESET_STRESS,
                "portfolio": self.portfolio.id,
                "name": "Scenario from form",
                "description": "Created from dedicated scenario form",
                "trend": "0.025",
                "volatility": "0.090",
                "noise_level": "0.012",
                "market_shock": "-0.010",
                "currency_shock": "-0.020",
                "systematic_risk": "0.3000",
                "time_horizon": "45",
                "time_step": "1",
                "iterations_count": "80",
            },
        )

        scenario = Scenario.objects.get(name="Scenario from form")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(scenario.user, self.user)
        self.assertEqual(scenario.portfolio, self.portfolio)
        self.assertEqual(scenario.preset, Scenario.PRESET_STRESS)
        self.assertEqual(scenario.market_shock, Decimal("-0.120000"))
        self.assertEqual(scenario.currency_shock, Decimal("-0.100000"))
        self.assertEqual(scenario.systematic_risk, Decimal("0.8500"))

    def test_user_can_update_own_scenario(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("riskapp:scenario_update", args=[self.scenario.id]),
            {
                "preset": Scenario.PRESET_CUSTOM,
                "portfolio": self.portfolio.id,
                "name": "Updated scenario",
                "description": "Updated scenario description",
                "trend": "0.055",
                "volatility": "0.110",
                "noise_level": "0.008",
                "market_shock": "-0.020",
                "currency_shock": "-0.030",
                "systematic_risk": "0.4000",
                "time_horizon": "75",
                "time_step": "1",
                "iterations_count": "120",
            },
        )

        self.scenario.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.scenario.name, "Updated scenario")
        self.assertEqual(self.scenario.time_horizon, 75)
        self.assertEqual(self.scenario.market_shock, Decimal("-0.020000"))
        self.assertEqual(self.scenario.currency_shock, Decimal("-0.030000"))
        self.assertEqual(self.scenario.systematic_risk, Decimal("0.4000"))

    def test_user_can_delete_own_scenario(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("riskapp:scenario_delete", args=[self.scenario.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Scenario.objects.filter(id=self.scenario.id).exists())

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

    def test_regular_user_cannot_edit_other_user_scenario(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("riskapp:scenario_update", args=[self.other_scenario.id]))

        self.assertEqual(response.status_code, 404)

    def test_regular_user_cannot_delete_other_user_scenario(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("riskapp:scenario_delete", args=[self.other_scenario.id]))

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

    def test_admin_site_uses_custom_title(self):
        self.client.force_login(self.admin_user)

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Страница администратора Market Risk")

    def test_signup_creates_inactive_user_and_sends_activation_email(self):
        response = self.client.post(
            reverse("riskapp:signup"),
            {
                "username": "newuser",
                "first_name": "New",
                "last_name": "User",
                "email": "newuser@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        created_user = User.objects.get(username="newuser")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(created_user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("activate", mail.outbox[0].body)

    def test_signup_shows_russian_password_mismatch_message(self):
        response = self.client.post(
            reverse("riskapp:signup"),
            {
                "username": "newuser",
                "first_name": "New",
                "last_name": "User",
                "email": "newuser@example.com",
                "password1": "StrongPass123!",
                "password2": "DifferentPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пароли не совпадают.")

    def test_activation_link_activates_user(self):
        user = User.objects.create_user(
            username="pending",
            email="pending@example.com",
            password="StrongPass123!",
            is_active=False,
        )
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        response = self.client.get(reverse("riskapp:activate_account", args=[uid, token]))

        user.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(user.is_active)

    def test_user_can_open_profile_page(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("riskapp:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user.username)

    def test_user_can_update_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("riskapp:profile"),
            {
                "first_name": "Web",
                "last_name": "User",
                "email": "webuser@example.com",
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user.first_name, "Web")
        self.assertEqual(self.user.last_name, "User")
        self.assertEqual(self.user.email, "webuser@example.com")

    def test_authenticated_user_can_open_password_change_page(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("account_password_change"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Обновление пароля")

    def test_password_reset_sends_email(self):
        self.user.email = "webuser@example.com"
        self.user.save(update_fields=["email"])

        response = self.client.post(
            reverse("account_password_reset"),
            {"email": "webuser@example.com"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/reset/", mail.outbox[0].body)

    def test_user_can_open_results_page(self):
        self.client.force_login(self.user)
        result = run_scenario_simulation(self.scenario.id, seed=42).result

        response = self.client.get(reverse("riskapp:results"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.scenario.name)
        self.assertContains(response, reverse("riskapp:result_detail", args=[result.id]))

    def test_user_can_open_instrument_catalog_for_portfolio(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("riskapp:instruments"), {"portfolio": self.portfolio.id, "query": "WEB"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Web instrument")
        self.assertContains(response, self.portfolio.name)

    def test_results_page_can_filter_by_portfolio(self):
        self.client.force_login(self.user)
        run_scenario_simulation(self.scenario.id, seed=42)

        response = self.client.get(reverse("riskapp:results"), {"portfolio": self.portfolio.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.portfolio.name)

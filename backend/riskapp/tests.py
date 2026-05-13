from datetime import datetime
from decimal import Decimal
from statistics import mean
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone

from riskapp.models import (
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
from riskapp.services.moex import fetch_market_snapshot, iter_market_snapshots, sync_moex_instruments, sync_moex_price_history
from riskapp.services.historical_calibration import calibrate_portfolio_scenario_parameters
from riskapp.services.portfolio_operations import (
    estimate_trade_commission,
    estimate_trade_execution_price,
    get_portfolio_cash_snapshot,
    record_trade_operation,
)
from riskapp.services.simulation import run_scenario_simulation


class ScenarioSimulationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="investor", password="password")
        ExchangeRate.objects.create(
            from_currency="USD",
            to_currency="RUB",
            rate=Decimal("90.00000000"),
            rate_date="2026-04-29",
        )
        ExchangeRate.objects.create(
            from_currency="RUB",
            to_currency="USD",
            rate=Decimal("0.01111111"),
            rate_date="2026-04-29",
        )
        self.instrument = Instrument.objects.create(
            ticker="TEST",
            name="Test instrument",
            instrument_type="stock",
            sector="Equities",
            currency="USD",
            current_price=Decimal("100.0000"),
        )
        self.bond = Instrument.objects.create(
            ticker="BOND",
            name="Test bond",
            instrument_type="bond",
            sector="Bonds",
            currency="RUB",
            current_price=Decimal("1000.0000"),
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            name="Test portfolio",
            base_currency="RUB",
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
            sector_target="Equities",
            sector_shock=Decimal("0.000000"),
            interest_rate_shock=Decimal("0.000000"),
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
        self.assertIn("sector_target", summary.result.chart_data)
        self.assertIn("sector_shock_percent", summary.result.chart_data)
        self.assertIn("interest_rate_shock_percent", summary.result.chart_data)
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
            sector_target="",
            sector_shock=Decimal("0.000000"),
            interest_rate_shock=Decimal("0.000000"),
            systematic_risk=Decimal("0.6500"),
            time_horizon=10,
            time_step=Decimal("1.0000"),
            iterations_count=20,
        )

        with self.assertRaises(ValueError):
            run_scenario_simulation(scenario.id, seed=42)

    def test_income_yields_support_total_return_for_stocks_and_bonds(self):
        self.instrument.dividend_yield = Decimal("0.120000")
        self.instrument.save(update_fields=["dividend_yield"])
        self.bond.coupon_yield = Decimal("0.080000")
        self.bond.save(update_fields=["coupon_yield"])
        self.scenario.trend = Decimal("0.000000")
        self.scenario.volatility = Decimal("0.000000")
        self.scenario.noise_level = Decimal("0.000000")
        self.scenario.market_shock = Decimal("0.000000")
        self.scenario.currency_shock = Decimal("0.000000")
        self.scenario.inflation_shock = Decimal("0.000000")
        self.scenario.interest_rate_shock = Decimal("0.000000")
        self.scenario.systematic_risk = Decimal("0.000000")
        self.scenario.mean_reversion_strength = Decimal("0.000000")
        self.scenario.time_horizon = 365
        self.scenario.iterations_count = 1
        self.scenario.save()

        summary = run_scenario_simulation(self.scenario.id, seed=7)

        self.assertGreater(summary.result.final_value, Decimal(str(summary.result.chart_data["start_value"])))
        position_paths = summary.result.chart_data["position_paths"]
        self.assertTrue(any(item["annual_income_yield_percent"] > 0 for item in position_paths))

    def test_rebalancing_frequency_changes_portfolio_path(self):
        self.instrument.dividend_yield = Decimal("0.000000")
        self.instrument.save(update_fields=["dividend_yield"])
        self.bond.coupon_yield = Decimal("0.000000")
        self.bond.save(update_fields=["coupon_yield"])
        self.scenario.trend = Decimal("0.120000")
        self.scenario.volatility = Decimal("0.000000")
        self.scenario.noise_level = Decimal("0.000000")
        self.scenario.market_shock = Decimal("0.000000")
        self.scenario.currency_shock = Decimal("0.000000")
        self.scenario.inflation_shock = Decimal("0.000000")
        self.scenario.interest_rate_shock = Decimal("0.000000")
        self.scenario.systematic_risk = Decimal("0.000000")
        self.scenario.mean_reversion_strength = Decimal("0.000000")
        self.scenario.time_horizon = 360
        self.scenario.iterations_count = 1
        self.scenario.rebalancing_frequency = Scenario.REBALANCE_NONE
        self.scenario.save()

        hold_summary = run_scenario_simulation(self.scenario.id, seed=11)

        self.scenario.rebalancing_frequency = Scenario.REBALANCE_MONTHLY
        self.scenario.save(update_fields=["rebalancing_frequency"])
        rebalance_summary = run_scenario_simulation(self.scenario.id, seed=11)

        self.assertNotEqual(hold_summary.result.final_value, rebalance_summary.result.final_value)
        self.assertEqual(rebalance_summary.result.chart_data["rebalancing_frequency"], Scenario.REBALANCE_MONTHLY)
        self.assertTrue(rebalance_summary.result.chart_data["rebalancing_marker_days"])
        self.assertEqual(rebalance_summary.result.chart_data["rebalancing_marker_days"][0], 30)

    def test_jump_component_adds_rare_discrete_moves(self):
        self.instrument.dividend_yield = Decimal("0.000000")
        self.instrument.save(update_fields=["dividend_yield"])
        self.bond.coupon_yield = Decimal("0.000000")
        self.bond.save(update_fields=["coupon_yield"])
        self.scenario.trend = Decimal("0.000000")
        self.scenario.volatility = Decimal("0.000000")
        self.scenario.noise_level = Decimal("0.000000")
        self.scenario.market_shock = Decimal("0.000000")
        self.scenario.currency_shock = Decimal("0.000000")
        self.scenario.inflation_shock = Decimal("0.000000")
        self.scenario.interest_rate_shock = Decimal("0.000000")
        self.scenario.systematic_risk = Decimal("0.000000")
        self.scenario.mean_reversion_strength = Decimal("0.000000")
        self.scenario.time_horizon = 360
        self.scenario.time_step = Decimal("30.0000")
        self.scenario.iterations_count = 1
        self.scenario.jump_intensity = Decimal("0.000")
        self.scenario.jump_magnitude = Decimal("0.100000")
        self.scenario.save()

        no_jump_summary = run_scenario_simulation(self.scenario.id, seed=3)

        self.scenario.jump_intensity = Decimal("5.000")
        self.scenario.save(update_fields=["jump_intensity"])
        jump_summary = run_scenario_simulation(self.scenario.id, seed=3)

        self.assertNotEqual(no_jump_summary.result.final_value, jump_summary.result.final_value)
        self.assertGreater(jump_summary.result.chart_data["average_jump_events"], 0)
        self.assertEqual(jump_summary.result.chart_data["jump_magnitude_percent"], 10.0)

    def test_same_sector_assets_move_closer_than_cross_sector_assets(self):
        reference_stock = Instrument.objects.create(
            ticker="BASE",
            name="Reference stock",
            instrument_type="stock",
            sector="Equities",
            currency="RUB",
            current_price=Decimal("100.0000"),
        )
        same_sector_peer = Instrument.objects.create(
            ticker="ALLY",
            name="Sector peer stock",
            instrument_type="stock",
            sector="Equities",
            currency="RUB",
            current_price=Decimal("100.0000"),
        )
        different_sector_stock = Instrument.objects.create(
            ticker="INDX",
            name="Different sector stock",
            instrument_type="stock",
            sector="Industrials",
            currency="RUB",
            current_price=Decimal("100.0000"),
        )
        correlation_portfolio = Portfolio.objects.create(
            user=self.user,
            name="Correlation portfolio",
            base_currency="RUB",
            initial_value=Decimal("0.00"),
        )
        PortfolioPosition.objects.create(
            portfolio=correlation_portfolio,
            instrument=reference_stock,
            quantity=5,
            average_purchase_price=Decimal("100.0000"),
        )
        PortfolioPosition.objects.create(
            portfolio=correlation_portfolio,
            instrument=same_sector_peer,
            quantity=5,
            average_purchase_price=Decimal("100.0000"),
        )
        PortfolioPosition.objects.create(
            portfolio=correlation_portfolio,
            instrument=different_sector_stock,
            quantity=5,
            average_purchase_price=Decimal("100.0000"),
        )
        correlation_scenario = Scenario.objects.create(
            user=self.user,
            portfolio=correlation_portfolio,
            name="Correlation scenario",
            preset=Scenario.PRESET_CUSTOM,
            trend=Decimal("0.000000"),
            volatility=Decimal("0.180000"),
            noise_level=Decimal("0.000000"),
            market_shock=Decimal("0.000000"),
            currency_shock=Decimal("0.000000"),
            inflation_shock=Decimal("0.000000"),
            sector_target="",
            sector_shock=Decimal("0.000000"),
            interest_rate_shock=Decimal("0.000000"),
            systematic_risk=Decimal("1.0000"),
            mean_reversion_strength=Decimal("0.000000"),
            time_horizon=90,
            time_step=Decimal("1.0000"),
            iterations_count=8,
            rebalancing_frequency=Scenario.REBALANCE_NONE,
        )
        same_sector_gaps = []
        cross_sector_gaps = []
        last_summary = None

        for seed in (5, 11, 17, 23, 29):
            summary = run_scenario_simulation(correlation_scenario.id, seed=seed)
            position_metrics = {
                item["ticker"]: item["average_values"]
                for item in summary.result.chart_data["position_paths"]
            }
            same_sector_gaps.append(mean(
                abs(a - b)
                for a, b in zip(position_metrics["ALLY"], position_metrics["BASE"])
            ))
            cross_sector_gaps.append(mean(
                abs(a - b)
                for a, b in zip(position_metrics["INDX"], position_metrics["BASE"])
            ))
            last_summary = summary

        self.assertLess(mean(same_sector_gaps), mean(cross_sector_gaps))
        self.assertEqual(
            last_summary.result.chart_data["shared_factor_mix_percent"]["market"],
            55.0,
        )


class HistoricalCalibrationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="calibration-user", password="password")
        self.stock = Instrument.objects.create(
            ticker="HCST",
            name="Historical calibration stock",
            instrument_type="stock",
            sector="Equities",
            currency="RUB",
            current_price=Decimal("120.0000"),
        )
        self.bond = Instrument.objects.create(
            ticker="HCBN",
            name="Historical calibration bond",
            instrument_type="bond",
            sector="Bonds",
            currency="RUB",
            current_price=Decimal("1010.0000"),
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            name="Historical calibration portfolio",
            base_currency="RUB",
            initial_value=Decimal("0.00"),
        )
        PortfolioPosition.objects.create(
            portfolio=self.portfolio,
            instrument=self.stock,
            quantity=8,
            average_purchase_price=Decimal("100.0000"),
        )
        PortfolioPosition.objects.create(
            portfolio=self.portfolio,
            instrument=self.bond,
            quantity=4,
            average_purchase_price=Decimal("1000.0000"),
        )

        stock_prices = [
            Decimal("100.00"),
            Decimal("101.20"),
            Decimal("102.10"),
            Decimal("103.80"),
            Decimal("104.60"),
            Decimal("106.00"),
            Decimal("107.10"),
            Decimal("108.00"),
            Decimal("109.30"),
            Decimal("110.50"),
        ]
        bond_prices = [
            Decimal("1000.00"),
            Decimal("999.40"),
            Decimal("1000.10"),
            Decimal("1000.90"),
            Decimal("1001.40"),
            Decimal("1002.10"),
            Decimal("1002.80"),
            Decimal("1003.10"),
            Decimal("1004.20"),
            Decimal("1005.00"),
        ]
        for offset, (stock_price, bond_price) in enumerate(zip(stock_prices, bond_prices)):
            captured_at = timezone.now() - timezone.timedelta(days=10 - offset)
            stock_history = InstrumentPriceHistory.objects.create(
                instrument=self.stock,
                price=stock_price,
                currency="RUB",
                source="TEST",
            )
            bond_history = InstrumentPriceHistory.objects.create(
                instrument=self.bond,
                price=bond_price,
                currency="RUB",
                source="TEST",
            )
            stock_history.captured_at = captured_at
            stock_history.save(update_fields=["captured_at"])
            bond_history.captured_at = captured_at
            bond_history.save(update_fields=["captured_at"])

    def test_calibrate_portfolio_scenario_parameters_uses_price_history(self):
        summary = calibrate_portfolio_scenario_parameters(self.portfolio, lookback_days=120)

        self.assertEqual(summary.instruments_used, 2)
        self.assertGreaterEqual(summary.observations_used, 8)
        self.assertGreater(summary.annual_trend, Decimal("0"))
        self.assertGreater(summary.annual_volatility, Decimal("0"))
        self.assertGreater(summary.noise_level, Decimal("0"))
        self.assertGreaterEqual(summary.systematic_risk, Decimal("0.1500"))
        self.assertEqual(summary.as_form_values()["preset"], Scenario.PRESET_CUSTOM)


class TradeOperationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="trader", password="password")
        self.instrument = Instrument.objects.create(
            ticker="OPS",
            name="Operation instrument",
            instrument_type="stock",
            sector="Equities",
            currency="RUB",
            current_price=Decimal("150.0000"),
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            name="Operations portfolio",
            base_currency="RUB",
            initial_value=Decimal("0.00"),
        )

    def test_buy_operation_creates_position_and_blended_average_price(self):
        record_trade_operation(
            user=self.user,
            portfolio=self.portfolio,
            instrument=self.instrument,
            operation_type=TradeOperation.TYPE_BUY,
            quantity=10,
            price_per_unit=Decimal("100.0000"),
            commission=Decimal("10.0000"),
        )
        operation, position = record_trade_operation(
            user=self.user,
            portfolio=self.portfolio,
            instrument=self.instrument,
            operation_type=TradeOperation.TYPE_BUY,
            quantity=5,
            price_per_unit=Decimal("160.0000"),
            commission=Decimal("5.0000"),
        )

        position.refresh_from_db()
        self.assertEqual(TradeOperation.objects.count(), 2)
        self.assertEqual(operation.operation_type, TradeOperation.TYPE_BUY)
        self.assertEqual(position.quantity, 15)
        self.assertGreater(position.average_purchase_price, Decimal("121.0000"))
        self.assertEqual(operation.quoted_price, Decimal("160.0000"))
        self.assertGreater(operation.price_per_unit, operation.quoted_price)
        self.assertGreater(operation.slippage_amount, Decimal("0"))
        self.assertLess(operation.cash_balance_after, Decimal("0"))

    def test_sell_operation_reduces_position_and_stores_realized_pnl(self):
        record_trade_operation(
            user=self.user,
            portfolio=self.portfolio,
            instrument=self.instrument,
            operation_type=TradeOperation.TYPE_BUY,
            quantity=10,
            price_per_unit=Decimal("100.0000"),
            commission=Decimal("0.0000"),
        )

        operation, position = record_trade_operation(
            user=self.user,
            portfolio=self.portfolio,
            instrument=self.instrument,
            operation_type=TradeOperation.TYPE_SELL,
            quantity=4,
            price_per_unit=Decimal("120.0000"),
            commission=Decimal("8.0000"),
        )

        position.refresh_from_db()
        self.assertEqual(position.quantity, 6)
        self.assertLess(operation.price_per_unit, operation.quoted_price)
        self.assertGreater(operation.slippage_amount, Decimal("0"))
        buy_operation = TradeOperation.objects.filter(
            portfolio=self.portfolio,
            instrument=self.instrument,
            operation_type=TradeOperation.TYPE_BUY,
        ).earliest("created_at")
        self.assertEqual(
            operation.realized_pnl,
            (Decimal("4") * operation.price_per_unit) - Decimal("8.0000") - (Decimal("4") * buy_operation.price_per_unit),
        )

    def test_cannot_sell_more_than_available_quantity(self):
        record_trade_operation(
            user=self.user,
            portfolio=self.portfolio,
            instrument=self.instrument,
            operation_type=TradeOperation.TYPE_BUY,
            quantity=3,
            price_per_unit=Decimal("100.0000"),
            commission=Decimal("0.0000"),
        )

        with self.assertRaises(ValueError):
            record_trade_operation(
                user=self.user,
                portfolio=self.portfolio,
                instrument=self.instrument,
                operation_type=TradeOperation.TYPE_SELL,
                quantity=4,
                price_per_unit=Decimal("110.0000"),
                commission=Decimal("0.0000"),
            )

    def test_cash_snapshot_uses_trade_journal_and_marks_legacy_positions_as_estimated(self):
        legacy_portfolio = Portfolio.objects.create(
            user=self.user,
            name="Legacy portfolio",
            base_currency="RUB",
            initial_value=Decimal("5000.00"),
        )
        PortfolioPosition.objects.create(
            portfolio=legacy_portfolio,
            instrument=self.instrument,
            quantity=10,
            average_purchase_price=Decimal("100.0000"),
        )

        snapshot = get_portfolio_cash_snapshot(legacy_portfolio)

        self.assertFalse(snapshot.reliable)
        self.assertEqual(snapshot.balance, Decimal("4000.00"))


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

    @patch("riskapp.services.moex._fetch_json")
    def test_iter_market_snapshots_loads_etf_from_equity_boards(self, mocked_fetch):
        empty_payload = {
            "securities": {
                "columns": ["SECID", "SHORTNAME", "FACEUNIT"],
                "data": [],
            },
            "marketdata": {
                "columns": ["SECID", "LAST", "MARKETPRICE"],
                "data": [],
            },
        }
        etf_payload = {
            "securities": {
                "columns": ["SECID", "SHORTNAME", "FACEUNIT"],
                "data": [["FXIT", "FinEx IT ETF", "SUR"]],
            },
            "marketdata": {
                "columns": ["SECID", "LAST", "MARKETPRICE"],
                "data": [["FXIT", 101.75, None]],
            },
        }

        def fake_fetch(path, params=None):
            if "/markets/shares/boards/TQTF/securities.json" in path:
                return etf_payload
            return empty_payload

        mocked_fetch.side_effect = fake_fetch

        rows = list(iter_market_snapshots(["etf"], limit_per_market=10))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "etf")
        self.assertEqual(rows[0][1]["ticker"], "FXIT")
        self.assertEqual(rows[0][1]["current_price"], Decimal("101.75"))

    @patch("riskapp.services.moex._fetch_json")
    def test_sync_moex_price_history_imports_historical_rows(self, mocked_fetch):
        instrument = Instrument.objects.create(
            ticker="SBER",
            name="Sberbank",
            instrument_type="stock",
            sector="Equities",
            currency="RUB",
            current_price=Decimal("312.4500"),
        )
        mocked_fetch.return_value = {
            "history": {
                "columns": ["TRADEDATE", "CLOSE", "BOARDID"],
                "data": [
                    ["2026-04-25", 300.10, "TQBR"],
                    ["2026-04-26", 301.25, "TQBR"],
                ],
            },
        }

        stats = sync_moex_price_history(instruments=[instrument], lookback_days=30)

        self.assertEqual(stats.instruments, 1)
        self.assertEqual(stats.imported, 2)
        self.assertEqual(
            InstrumentPriceHistory.objects.filter(instrument=instrument, source="MOEX_HISTORY").count(),
            2,
        )
        first_row = InstrumentPriceHistory.objects.filter(instrument=instrument, source="MOEX_HISTORY").earliest("captured_at")
        self.assertEqual(str(first_row.captured_at.date()), "2026-04-25")

    @patch("riskapp.services.moex._fetch_json")
    def test_sync_moex_price_history_imports_etf_rows_from_equity_board_history(self, mocked_fetch):
        instrument = Instrument.objects.create(
            ticker="FXIT",
            name="FinEx IT ETF",
            instrument_type="etf",
            sector="Funds",
            currency="RUB",
            current_price=Decimal("101.7500"),
        )
        empty_payload = {
            "history": {
                "columns": ["TRADEDATE", "CLOSE", "BOARDID"],
                "data": [],
            },
        }
        etf_payload = {
            "history": {
                "columns": ["TRADEDATE", "CLOSE", "BOARDID"],
                "data": [
                    ["2026-04-25", 100.25, "TQTF"],
                    ["2026-04-26", 101.10, "TQTF"],
                ],
            },
        }

        def fake_fetch(path, params=None):
            if "/history/engines/stock/markets/shares/boards/TQTF/securities/FXIT.json" in path:
                return etf_payload
            return empty_payload

        mocked_fetch.side_effect = fake_fetch

        stats = sync_moex_price_history(instruments=[instrument], lookback_days=30)

        self.assertEqual(stats.instruments, 1)
        self.assertEqual(stats.imported, 2)
        self.assertEqual(
            InstrumentPriceHistory.objects.filter(instrument=instrument, source="MOEX_HISTORY").count(),
            2,
        )

    @patch("riskapp.services.moex._fetch_json")
    def test_sync_moex_price_history_skips_existing_dates_without_replace(self, mocked_fetch):
        instrument = Instrument.objects.create(
            ticker="GAZP",
            name="Gazprom",
            instrument_type="stock",
            sector="Equities",
            currency="RUB",
            current_price=Decimal("170.0000"),
        )
        existing_history = InstrumentPriceHistory.objects.create(
            instrument=instrument,
            price=Decimal("170.0000"),
            currency="RUB",
            source="MOEX_HISTORY",
        )
        existing_history.captured_at = timezone.make_aware(datetime(2026, 4, 25, 12, 0))
        existing_history.save(update_fields=["captured_at"])
        mocked_fetch.return_value = {
            "history": {
                "columns": ["TRADEDATE", "CLOSE", "BOARDID"],
                "data": [
                    ["2026-04-25", 170.00, "TQBR"],
                    ["2026-04-26", 171.50, "TQBR"],
                ],
            },
        }

        stats = sync_moex_price_history(instruments=[instrument], lookback_days=30)

        self.assertEqual(stats.imported, 1)
        self.assertEqual(
            InstrumentPriceHistory.objects.filter(instrument=instrument, source="MOEX_HISTORY").count(),
            2,
        )

    @patch("riskapp.services.moex.iter_market_snapshots")
    def test_sync_moex_instruments_creates_and_updates_instruments(self, mocked_iter):
        mocked_iter.return_value = iter([
            ("shares", {"ticker": "SBER", "name": "Sberbank", "currency": "RUB", "current_price": Decimal("300.10"), "dividend_yield": Decimal("0.065000")}),
            ("bonds", {"ticker": "OFZ26238", "name": "OFZ 26238", "currency": "RUB", "current_price": Decimal("102.55"), "coupon_yield": Decimal("0.110000")}),
        ])

        stats = sync_moex_instruments(markets=["shares", "bonds"])

        self.assertEqual(stats.created, 2)
        self.assertEqual(stats.updated, 0)
        self.assertEqual(stats.skipped, 0)
        self.assertEqual(Instrument.objects.count(), 2)
        self.assertEqual(Instrument.objects.get(ticker="SBER").instrument_type, "stock")
        self.assertEqual(Instrument.objects.get(ticker="SBER").sector, "Equities")
        self.assertEqual(Instrument.objects.get(ticker="SBER").dividend_yield, Decimal("0.065000"))
        self.assertEqual(Instrument.objects.get(ticker="OFZ26238").instrument_type, "bond")
        self.assertEqual(Instrument.objects.get(ticker="OFZ26238").sector, "Bonds")
        self.assertEqual(Instrument.objects.get(ticker="OFZ26238").coupon_yield, Decimal("0.110000"))
        self.assertIsNotNone(Instrument.objects.get(ticker="SBER").last_price_updated_at)
        self.assertEqual(InstrumentPriceHistory.objects.count(), 2)

    @patch("riskapp.services.moex.iter_market_snapshots")
    def test_sync_moex_instruments_can_refresh_existing_only(self, mocked_iter):
        Instrument.objects.create(
            ticker="SBER",
            name="Sberbank old",
            instrument_type="stock",
            sector="Equities",
            currency="RUB",
            current_price=Decimal("250.00"),
        )
        mocked_iter.return_value = iter([
            ("shares", {"ticker": "SBER", "name": "Sberbank", "currency": "RUB", "current_price": Decimal("300.10")}),
            ("shares", {"ticker": "GAZP", "name": "Gazprom", "currency": "RUB", "current_price": Decimal("170.00")}),
        ])

        stats = sync_moex_instruments(markets=["shares"], existing_only=True)

        self.assertEqual(stats.created, 0)
        self.assertEqual(stats.updated, 1)
        self.assertEqual(stats.skipped, 1)
        self.assertEqual(Instrument.objects.count(), 1)
        self.assertEqual(Instrument.objects.get(ticker="SBER").current_price, Decimal("300.10"))

    @patch("riskapp.management.commands.refresh_market_data.upsert_exchange_rates")
    @patch("riskapp.management.commands.refresh_market_data.sync_moex_instruments")
    def test_refresh_market_data_daily_profile_uses_expected_defaults(self, mocked_sync, mocked_rates):
        call_command("refresh_market_data", profile="daily-universe")

        mocked_sync.assert_called_once_with(
            markets=["shares", "bonds", "etf"],
            limit_total=None,
            limit_per_market=400,
            existing_only=False,
        )
        mocked_rates.assert_called_once()

    @patch("riskapp.management.commands.refresh_market_data.snapshot_current_prices", return_value=3)
    def test_refresh_market_data_history_snapshot_uses_snapshot_service(self, mocked_snapshot):
        call_command("refresh_market_data", profile="history-snapshot")

        mocked_snapshot.assert_called_once_with(source="SCHEDULED")

    @patch("riskapp.management.commands.refresh_market_data.sync_moex_price_history")
    def test_refresh_market_data_historical_backfill_uses_history_sync(self, mocked_history_sync):
        mocked_history_sync.return_value.imported = 12
        mocked_history_sync.return_value.skipped = 1
        mocked_history_sync.return_value.instruments = 3

        call_command("refresh_market_data", profile="historical-backfill", history_days=120)

        mocked_history_sync.assert_called_once_with(
            lookback_days=120,
            replace_existing=False,
        )


class RiskAppWebUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="webuser", password="password")
        self.other_user = User.objects.create_user(username="otheruser", password="password")
        self.admin_user = User.objects.create_superuser(
            username="adminuser",
            password="password",
            email="admin@example.com",
        )
        ExchangeRate.objects.create(
            from_currency="USD",
            to_currency="RUB",
            rate=Decimal("90.00000000"),
            rate_date="2026-04-29",
        )
        ExchangeRate.objects.create(
            from_currency="RUB",
            to_currency="USD",
            rate=Decimal("0.01111111"),
            rate_date="2026-04-29",
        )
        self.instrument = Instrument.objects.create(
            ticker="WEB",
            name="Web instrument",
            instrument_type="stock",
            sector="Equities",
            currency="USD",
            current_price=Decimal("50.0000"),
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            name="Web portfolio",
            base_currency="RUB",
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
            market_shock=Decimal("0.000000"),
            currency_shock=Decimal("0.000000"),
            sector_target="",
            sector_shock=Decimal("0.000000"),
            interest_rate_shock=Decimal("0.000000"),
            systematic_risk=Decimal("0.6500"),
            time_horizon=30,
            time_step=Decimal("1.0000"),
            iterations_count=20,
        )
        self.other_portfolio = Portfolio.objects.create(
            user=self.other_user,
            name="Other user portfolio",
            base_currency="RUB",
            initial_value=Decimal("200.00"),
        )
        self.other_scenario = Scenario.objects.create(
            user=self.other_user,
            portfolio=self.other_portfolio,
            name="Other user scenario",
            trend=Decimal("0.010000"),
            volatility=Decimal("0.020000"),
            noise_level=Decimal("0.001000"),
            market_shock=Decimal("0.000000"),
            currency_shock=Decimal("0.000000"),
            sector_target="",
            sector_shock=Decimal("0.000000"),
            interest_rate_shock=Decimal("0.000000"),
            systematic_risk=Decimal("0.6500"),
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
                "market_shock": "0.000",
                "currency_shock": "0.000",
                "sector_target": "",
                "sector_shock": "0.000",
                "interest_rate_shock": "0.000",
                "systematic_risk": "0.6500",
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
                "rebalancing_frequency": Scenario.REBALANCE_MONTHLY,
                "name": "Scenario from form",
                "description": "Created from dedicated scenario form",
                "trend": "0.025",
                "volatility": "0.090",
                "noise_level": "0.012",
                "market_shock": "-0.010",
                "currency_shock": "-0.020",
                "sector_target": "Equities",
                "sector_shock": "-0.030",
                "interest_rate_shock": "0.070",
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
        self.assertEqual(scenario.rebalancing_frequency, Scenario.REBALANCE_MONTHLY)
        self.assertEqual(scenario.market_shock, Decimal("-0.010000"))
        self.assertEqual(scenario.currency_shock, Decimal("-0.020000"))
        self.assertEqual(scenario.sector_target, "Equities")
        self.assertEqual(scenario.sector_shock, Decimal("-0.030000"))
        self.assertEqual(scenario.interest_rate_shock, Decimal("0.070000"))
        self.assertEqual(scenario.systematic_risk, Decimal("0.3000"))

    def test_user_can_update_own_scenario(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("riskapp:scenario_update", args=[self.scenario.id]),
            {
                "preset": Scenario.PRESET_CUSTOM,
                "portfolio": self.portfolio.id,
                "rebalancing_frequency": Scenario.REBALANCE_QUARTERLY,
                "name": "Updated scenario",
                "description": "Updated scenario description",
                "trend": "0.055",
                "volatility": "0.110",
                "noise_level": "0.008",
                "market_shock": "-0.020",
                "currency_shock": "-0.030",
                "sector_target": "Funds",
                "sector_shock": "-0.040",
                "interest_rate_shock": "0.030",
                "systematic_risk": "0.4000",
                "time_horizon": "75",
                "time_step": "1",
                "iterations_count": "120",
            },
        )

        self.scenario.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.scenario.name, "Updated scenario")
        self.assertEqual(self.scenario.rebalancing_frequency, Scenario.REBALANCE_QUARTERLY)
        self.assertEqual(self.scenario.time_horizon, 75)
        self.assertEqual(self.scenario.market_shock, Decimal("-0.020000"))
        self.assertEqual(self.scenario.currency_shock, Decimal("-0.030000"))
        self.assertEqual(self.scenario.sector_target, "Funds")
        self.assertEqual(self.scenario.sector_shock, Decimal("-0.040000"))
        self.assertEqual(self.scenario.interest_rate_shock, Decimal("0.030000"))
        self.assertEqual(self.scenario.systematic_risk, Decimal("0.4000"))

    def test_user_cannot_create_scenario_with_time_step_greater_than_horizon(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("riskapp:scenario_create"),
            {
                "preset": Scenario.PRESET_CUSTOM,
                "portfolio": self.portfolio.id,
                "name": "Invalid time step scenario",
                "description": "Invalid combination",
                "trend": "0.010",
                "volatility": "0.050",
                "noise_level": "0.010",
                "market_shock": "0.000",
                "currency_shock": "0.000",
                "inflation_shock": "0.040",
                "sector_target": "",
                "sector_shock": "0.000",
                "interest_rate_shock": "0.000",
                "systematic_risk": "0.5000",
                "mean_reversion_strength": "0.1500",
                "time_horizon": "20",
                "time_step": "30",
                "iterations_count": "100",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Шаг времени не может быть больше горизонта моделирования.")
        self.assertFalse(Scenario.objects.filter(name="Invalid time step scenario").exists())

    def test_user_cannot_create_scenario_with_unrealistic_interest_rate_shock(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("riskapp:scenario_create"),
            {
                "preset": Scenario.PRESET_CUSTOM,
                "portfolio": self.portfolio.id,
                "name": "Invalid rate shock scenario",
                "description": "Invalid rate shock",
                "trend": "0.010",
                "volatility": "0.050",
                "noise_level": "0.010",
                "market_shock": "0.000",
                "currency_shock": "0.000",
                "inflation_shock": "0.040",
                "sector_target": "",
                "sector_shock": "0.000",
                "interest_rate_shock": "0.500",
                "systematic_risk": "0.5000",
                "mean_reversion_strength": "0.1500",
                "time_horizon": "120",
                "time_step": "1",
                "iterations_count": "100",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Р—РЅР°С‡РµРЅРёРµ РґРѕР»Р¶РЅРѕ Р±С‹С‚СЊ РІ РґРёР°РїР°Р·РѕРЅРµ РѕС‚ -0.10 РґРѕ 0.10.")
        self.assertFalse(Scenario.objects.filter(name="Invalid rate shock scenario").exists())

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
            "base_currency": "RUB",
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
            base_currency="RUB",
            initial_value=Decimal("0.00"),
        )

        response = self.client.post(f"/portfolios/{portfolio.id}/positions/add/", {
            "instrument": self.instrument.id,
            "quantity": "3",
        })

        position = PortfolioPosition.objects.get(portfolio=portfolio, instrument=self.instrument)
        operation = TradeOperation.objects.get(portfolio=portfolio, instrument=self.instrument)
        execution_price, _ = estimate_trade_execution_price(self.instrument, TradeOperation.TYPE_BUY, self.instrument.current_price, 3)
        expected_commission = estimate_trade_commission(3, execution_price)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(position.quantity, 3)
        expected_average_price = (((Decimal("3") * execution_price) + expected_commission) / Decimal("3")).quantize(Decimal("1.0000"))
        self.assertEqual(position.average_purchase_price, expected_average_price)
        self.assertEqual(operation.operation_type, TradeOperation.TYPE_BUY)
        self.assertEqual(operation.commission, expected_commission)
        self.assertEqual(operation.quoted_price, self.instrument.current_price)

    def test_user_can_update_portfolio_from_web(self):
        self.client.force_login(self.user)

        response = self.client.post(f"/portfolios/{self.portfolio.id}/edit/", {
            "name": "Updated portfolio",
            "description": "Updated description",
            "base_currency": "RUB",
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
            base_currency="RUB",
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

    def test_user_can_create_sell_trade_from_operation_form(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("riskapp:portfolio_operation_create", args=[self.portfolio.id]),
            {
                "operation_type": TradeOperation.TYPE_SELL,
                "instrument": self.instrument.id,
                "quantity": "4",
                "executed_at": "2026-04-30T10:15",
                "comment": "Partial exit",
            },
        )

        position = PortfolioPosition.objects.get(portfolio=self.portfolio, instrument=self.instrument)
        self.portfolio.refresh_from_db()
        sell_operation = TradeOperation.objects.filter(
            portfolio=self.portfolio,
            instrument=self.instrument,
            operation_type=TradeOperation.TYPE_SELL,
        ).latest("created_at")
        execution_price, _ = estimate_trade_execution_price(self.instrument, TradeOperation.TYPE_SELL, self.instrument.current_price, 4)
        expected_commission = estimate_trade_commission(4, execution_price)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(position.quantity, 6)
        self.assertEqual(self.portfolio.current_value, Decimal("27000.00"))
        self.assertEqual(sell_operation.commission, expected_commission)
        self.assertEqual(sell_operation.realized_pnl, (Decimal("4") * execution_price) - expected_commission - (Decimal("4") * Decimal("45.0000")))

    def test_user_cannot_sell_more_than_owned_via_operation_form(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("riskapp:portfolio_operation_create", args=[self.portfolio.id]),
            {
                "operation_type": TradeOperation.TYPE_SELL,
                "instrument": self.instrument.id,
                "quantity": "40",
                "executed_at": "2026-04-30T10:15",
                "comment": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Нельзя продать больше 10 шт.")
        self.assertFalse(
            TradeOperation.objects.filter(
                portfolio=self.portfolio,
                operation_type=TradeOperation.TYPE_SELL,
            ).exists()
        )

    def test_user_can_open_strategy_compare_page(self):
        self.client.force_login(self.user)
        second_scenario = Scenario.objects.create(
            user=self.user,
            portfolio=self.portfolio,
            name="Second scenario",
            trend=Decimal("0.015000"),
            volatility=Decimal("0.050000"),
            noise_level=Decimal("0.003000"),
            market_shock=Decimal("0.000000"),
            currency_shock=Decimal("0.000000"),
            sector_target="",
            sector_shock=Decimal("0.000000"),
            interest_rate_shock=Decimal("0.000000"),
            systematic_risk=Decimal("0.5000"),
            time_horizon=30,
            time_step=Decimal("1.0000"),
            iterations_count=15,
        )
        first_summary = run_scenario_simulation(self.scenario.id, seed=11)
        second_summary = run_scenario_simulation(second_scenario.id, seed=12)

        response = self.client.get(
            reverse("riskapp:strategy_compare"),
            {
                "portfolio": self.portfolio.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ключевые метрики по стратегиям")
        self.assertContains(response, self.scenario.name)
        self.assertContains(response, second_scenario.name)

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

    def test_instrument_catalog_can_filter_by_sector(self):
        self.client.force_login(self.user)
        Instrument.objects.create(
            ticker="BNDX",
            name="Bond instrument",
            instrument_type="bond",
            sector="Bonds",
            currency="RUB",
            current_price=Decimal("100.0000"),
        )

        response = self.client.get(reverse("riskapp:instruments"), {"sector": "Equities"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Web instrument")
        self.assertNotContains(response, "Bond instrument")

    def test_results_page_can_filter_by_portfolio(self):
        self.client.force_login(self.user)
        run_scenario_simulation(self.scenario.id, seed=42)

        response = self.client.get(reverse("riskapp:results"), {"portfolio": self.portfolio.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.portfolio.name)


def _patched_test_user_cannot_sell_more_than_owned_via_operation_form(self):
    self.client.force_login(self.user)

    response = self.client.post(
        reverse("riskapp:portfolio_operation_create", args=[self.portfolio.id]),
        {
            "operation_type": TradeOperation.TYPE_SELL,
            "instrument": self.instrument.id,
            "quantity": "40",
            "executed_at": "2026-04-30T10:15",
            "comment": "",
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, "Нельзя продать больше 10 шт.")
    self.assertFalse(
        TradeOperation.objects.filter(
            portfolio=self.portfolio,
            operation_type=TradeOperation.TYPE_SELL,
        ).exists()
    )


def _patched_test_user_can_open_strategy_compare_page(self):
    self.client.force_login(self.user)
    second_scenario = Scenario.objects.create(
        user=self.user,
        portfolio=self.portfolio,
        name="Second scenario",
        trend=Decimal("0.015000"),
        volatility=Decimal("0.050000"),
        noise_level=Decimal("0.003000"),
        market_shock=Decimal("0.000000"),
        currency_shock=Decimal("0.000000"),
        sector_target="",
        sector_shock=Decimal("0.000000"),
        interest_rate_shock=Decimal("0.000000"),
        systematic_risk=Decimal("0.5000"),
        time_horizon=30,
        time_step=Decimal("1.0000"),
        iterations_count=15,
    )
    run_scenario_simulation(self.scenario.id, seed=11)
    run_scenario_simulation(second_scenario.id, seed=12)

    response = self.client.get(
        reverse("riskapp:strategy_compare"),
        {
            "portfolio": self.portfolio.id,
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, "Ключевые показатели по всем результатам")
    self.assertContains(response, self.scenario.name)
    self.assertContains(response, second_scenario.name)


RiskAppWebUiTests.test_user_cannot_sell_more_than_owned_via_operation_form = _patched_test_user_cannot_sell_more_than_owned_via_operation_form
RiskAppWebUiTests.test_user_can_open_strategy_compare_page = _patched_test_user_can_open_strategy_compare_page


def _patched_test_user_cannot_sell_more_than_owned_via_operation_form_v2(self):
    self.client.force_login(self.user)

    response = self.client.post(
        reverse("riskapp:portfolio_operation_create", args=[self.portfolio.id]),
        {
            "operation_type": TradeOperation.TYPE_SELL,
            "instrument": self.instrument.id,
            "quantity": "40",
            "executed_at": "2026-04-30T10:15",
            "comment": "",
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, "Нельзя продать больше 10 шт.")
    self.assertFalse(
        TradeOperation.objects.filter(
            portfolio=self.portfolio,
            operation_type=TradeOperation.TYPE_SELL,
        ).exists()
    )


def _patched_test_user_can_open_strategy_compare_page_v2(self):
    self.client.force_login(self.user)
    second_scenario = Scenario.objects.create(
        user=self.user,
        portfolio=self.portfolio,
        name="Second scenario",
        trend=Decimal("0.015000"),
        volatility=Decimal("0.050000"),
        noise_level=Decimal("0.003000"),
        market_shock=Decimal("0.000000"),
        currency_shock=Decimal("0.000000"),
        sector_target="",
        sector_shock=Decimal("0.000000"),
        interest_rate_shock=Decimal("0.000000"),
        systematic_risk=Decimal("0.5000"),
        time_horizon=30,
        time_step=Decimal("1.0000"),
        iterations_count=15,
    )
    run_scenario_simulation(self.scenario.id, seed=11)
    run_scenario_simulation(second_scenario.id, seed=12)

    response = self.client.get(
        reverse("riskapp:strategy_compare"),
        {
            "portfolio": self.portfolio.id,
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, "Ключевые показатели по выбранным результатам")
    self.assertContains(response, self.scenario.name)
    self.assertContains(response, second_scenario.name)


def _patched_test_signup_creates_active_user_without_activation_email(self):
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
    self.assertRedirects(response, reverse("login"))
    self.assertTrue(created_user.is_active)
    self.assertEqual(len(mail.outbox), 0)


def _test_strategy_compare_can_filter_selected_results(self):
    self.client.force_login(self.user)
    second_scenario = Scenario.objects.create(
        user=self.user,
        portfolio=self.portfolio,
        name="Second scenario",
        trend=Decimal("0.015000"),
        volatility=Decimal("0.050000"),
        noise_level=Decimal("0.003000"),
        market_shock=Decimal("0.000000"),
        currency_shock=Decimal("0.000000"),
        sector_target="",
        sector_shock=Decimal("0.000000"),
        interest_rate_shock=Decimal("0.000000"),
        systematic_risk=Decimal("0.5000"),
        time_horizon=30,
        time_step=Decimal("1.0000"),
        iterations_count=15,
    )
    run_scenario_simulation(self.scenario.id, seed=11)
    run_scenario_simulation(second_scenario.id, seed=12)
    first_result = SimulationResult.objects.filter(scenario=self.scenario).latest("execution_time")
    second_result = SimulationResult.objects.filter(scenario=second_scenario).latest("execution_time")

    response = self.client.get(
        reverse("riskapp:strategy_compare"),
        {
            "portfolio": self.portfolio.id,
            "selection_mode": "custom",
            "results": [second_result.id],
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, second_scenario.name)
    self.assertNotContains(response, f'value="{first_result.id}" checked')
    self.assertContains(response, f'value="{second_result.id}" checked')
    self.assertContains(response, "Показать выбранные")


RiskAppWebUiTests.test_user_cannot_sell_more_than_owned_via_operation_form = _patched_test_user_cannot_sell_more_than_owned_via_operation_form_v2
RiskAppWebUiTests.test_user_can_open_strategy_compare_page = _patched_test_user_can_open_strategy_compare_page_v2
RiskAppWebUiTests.test_signup_creates_inactive_user_and_sends_activation_email = _patched_test_signup_creates_active_user_without_activation_email
RiskAppWebUiTests.test_strategy_compare_can_filter_selected_results = _test_strategy_compare_can_filter_selected_results


def _test_user_can_delete_simulation_result(self):
    self.client.force_login(self.user)
    summary = run_scenario_simulation(self.scenario.id, seed=23)

    response = self.client.post(
        reverse("riskapp:result_delete", args=[summary.result.id]),
    )

    self.assertEqual(response.status_code, 302)
    self.assertFalse(SimulationResult.objects.filter(id=summary.result.id).exists())


RiskAppWebUiTests.test_user_can_delete_simulation_result = _test_user_can_delete_simulation_result


def _test_scenario_create_can_calibrate_from_history(self):
    self.client.force_login(self.user)
    historical_prices = [
        Decimal("50.00"),
        Decimal("50.40"),
        Decimal("50.75"),
        Decimal("51.10"),
        Decimal("51.60"),
        Decimal("52.10"),
        Decimal("52.50"),
        Decimal("52.95"),
        Decimal("53.40"),
        Decimal("53.85"),
    ]
    for offset, price in enumerate(historical_prices):
        history = InstrumentPriceHistory.objects.create(
            instrument=self.instrument,
            price=price,
            currency="USD",
            source="TEST",
        )
        history.captured_at = timezone.now() - timezone.timedelta(days=10 - offset)
        history.save(update_fields=["captured_at"])

    response = self.client.post(
        reverse("riskapp:scenario_create"),
        {
            "action": "calibrate",
            "preset": Scenario.PRESET_BASE,
            "portfolio": self.portfolio.id,
            "name": "Calibrated draft",
            "description": "Historical draft",
            "trend": "0.03",
            "volatility": "0.07",
            "noise_level": "0.01",
            "market_shock": "0.00",
            "currency_shock": "0.00",
            "inflation_shock": "0.04",
            "sector_target": "",
            "sector_shock": "0.00",
            "interest_rate_shock": "0.00",
            "systematic_risk": "0.65",
            "mean_reversion_strength": "0.15",
            "time_horizon": "120",
            "time_step": "1",
            "iterations_count": "100",
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertEqual(Scenario.objects.filter(name="Calibrated draft").count(), 0)
    self.assertIn("calibration_summary", response.context)
    self.assertEqual(response.context["form"].initial["preset"], Scenario.PRESET_CUSTOM)
    self.assertGreater(response.context["calibration_summary"].annual_volatility, Decimal("0"))


RiskAppWebUiTests.test_scenario_create_can_calibrate_from_history = _test_scenario_create_can_calibrate_from_history


def _test_result_export_word_and_excel(self):
    self.client.force_login(self.user)
    summary = run_scenario_simulation(self.scenario.id, seed=31)

    word_response = self.client.get(
        reverse("riskapp:result_export", args=[summary.result.id, "word"])
    )
    excel_response = self.client.get(
        reverse("riskapp:result_export", args=[summary.result.id, "excel"])
    )

    self.assertEqual(word_response.status_code, 200)
    self.assertIn("application/msword", word_response["Content-Type"])
    self.assertIn(".doc", word_response["Content-Disposition"])
    self.assertContains(word_response, self.scenario.name)

    self.assertEqual(excel_response.status_code, 200)
    self.assertIn("application/vnd.ms-excel", excel_response["Content-Type"])
    self.assertIn(".xls", excel_response["Content-Disposition"])
    self.assertContains(excel_response, self.scenario.name)


def _test_strategy_compare_export_word(self):
    self.client.force_login(self.user)
    second_scenario = Scenario.objects.create(
        user=self.user,
        portfolio=self.portfolio,
        name="Second scenario",
        trend=Decimal("0.015000"),
        volatility=Decimal("0.050000"),
        noise_level=Decimal("0.003000"),
        market_shock=Decimal("0.000000"),
        currency_shock=Decimal("0.000000"),
        sector_target="",
        sector_shock=Decimal("0.000000"),
        interest_rate_shock=Decimal("0.000000"),
        systematic_risk=Decimal("0.5000"),
        time_horizon=30,
        time_step=Decimal("1.0000"),
        iterations_count=15,
    )
    first_summary = run_scenario_simulation(self.scenario.id, seed=41)
    second_summary = run_scenario_simulation(second_scenario.id, seed=42)

    response = self.client.get(
        reverse("riskapp:strategy_compare_export", args=["word"]),
        {
            "portfolio": self.portfolio.id,
            "selection_mode": "custom",
            "results": [first_summary.result.id, second_summary.result.id],
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertIn("application/msword", response["Content-Type"])
    self.assertContains(response, self.scenario.name)
    self.assertContains(response, second_scenario.name)


RiskAppWebUiTests.test_result_export_word_and_excel = _test_result_export_word_and_excel
RiskAppWebUiTests.test_strategy_compare_export_word = _test_strategy_compare_export_word

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import ceil, sqrt
import random
from statistics import mean, median, pstdev

from django.db import transaction

from riskapp.models import RiskMetric, Scenario, SimulationResult
from riskapp.services.exchange_rates import convert_amount, normalize_currency_code


DECIMAL_2 = Decimal("0.01")
DECIMAL_6 = Decimal("0.000001")
MAX_CHART_POINTS = 160
SAMPLE_PATHS_LIMIT = 7
CRITICAL_DRAWDOWN_LEVEL = 0.10
INSTRUMENT_TYPE_PROFILES = {
    "stock": {"trend": 1.00, "volatility": 1.10, "noise": 1.00, "inflation": 0.35},
    "bond": {"trend": 0.55, "volatility": 0.35, "noise": 0.40, "inflation": 0.85},
    "etf": {"trend": 0.90, "volatility": 0.80, "noise": 0.70, "inflation": 0.50},
}


@dataclass(frozen=True)
class SimulationSummary:
    result: SimulationResult
    metrics: list[RiskMetric]


def quantize_decimal(value, precision=DECIMAL_6):
    return Decimal(str(value)).quantize(precision, rounding=ROUND_HALF_UP)


def percentile(sorted_values, probability):
    if not sorted_values:
        return 0.0

    index = int(probability * (len(sorted_values) - 1))
    return sorted_values[index]


def calculate_max_drawdown(path_values):
    peak = path_values[0]
    max_drawdown = 0.0

    for value in path_values:
        if value > peak:
            peak = value

        if peak > 0:
            drawdown = (peak - value) / peak
            max_drawdown = max(max_drawdown, drawdown)

    return max_drawdown


def get_portfolio_start_value(scenario):
    positions = scenario.portfolio.positions.select_related("instrument")
    total = Decimal("0")
    base_currency = normalize_currency_code(scenario.portfolio.base_currency)
    for position in positions:
        raw_value = Decimal(position.quantity) * Decimal(position.instrument.current_price)
        converted = convert_amount(raw_value, position.instrument.currency, base_currency)
        if converted is None:
            raise ValueError("Missing exchange rate for portfolio currency conversion.")
        total += converted
    return total


def get_portfolio_positions(scenario):
    return list(scenario.portfolio.positions.select_related("instrument").order_by("instrument__ticker"))


def combine_paths(paths):
    return [sum(values) for values in zip(*paths)]


def downsample_path(values, max_points=MAX_CHART_POINTS):
    if len(values) <= max_points:
        return values

    last_index = len(values) - 1
    indexes = sorted({
        round(index * last_index / (max_points - 1))
        for index in range(max_points)
    })
    return [values[index] for index in indexes]


def downsample_indexes(length, max_points=MAX_CHART_POINTS):
    if length <= max_points:
        return list(range(length))

    last_index = length - 1
    return sorted({
        round(index * last_index / (max_points - 1))
        for index in range(max_points)
    })


def format_chart_path(values):
    return [float(quantize_decimal(value, DECIMAL_2)) for value in downsample_path(values)]


def format_chart_labels(values_length, step_days):
    return [
        int(round(index * step_days))
        for index in downsample_indexes(values_length)
    ]


def get_instrument_profile(position):
    return INSTRUMENT_TYPE_PROFILES.get(
        position.instrument.instrument_type,
        INSTRUMENT_TYPE_PROFILES["stock"],
    )


def get_currency_multiplier(position, currency_shock, base_currency):
    if normalize_currency_code(position.instrument.currency) == normalize_currency_code(base_currency):
        return 0.0
    return currency_shock


def get_sector_multiplier(position, sector_target, sector_shock):
    if not sector_target:
        return 0.0
    instrument_sector = (position.instrument.sector or "").strip().lower()
    if instrument_sector and instrument_sector == sector_target.strip().lower():
        return sector_shock
    return 0.0


def get_interest_rate_multiplier(position, interest_rate_shock):
    if position.instrument.instrument_type != "bond":
        return 0.0
    return -interest_rate_shock * 0.60


def get_income_yield(position):
    instrument = position.instrument
    instrument_type = instrument.normalized_type
    if instrument_type == "bond":
        return float(instrument.coupon_yield or 0)
    if instrument_type in {"stock", "etf"}:
        return float(instrument.dividend_yield or 0)
    return float(instrument.dividend_yield or 0)


def build_shock_weights(steps):
    shock_window = max(1, min(8, max(3, round(steps * 0.05))))
    raw_weights = [shock_window - index for index in range(shock_window)]
    total_weight = sum(raw_weights)
    return [weight / total_weight for weight in raw_weights]


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def build_instrument_path(
    start_value,
    profile,
    trend_per_step,
    volatility_per_step,
    noise_per_step,
    income_yield_per_step,
    market_shock,
    currency_shock,
    inflation_per_step,
    sector_shock,
    interest_rate_shock,
    systematic_risk,
    mean_reversion_strength,
    steps,
    generator,
):
    values = [start_value]
    current_value = start_value
    profile_trend = profile["trend"]
    profile_volatility = profile["volatility"]
    profile_noise = profile["noise"]
    profile_inflation = profile["inflation"]
    shock_weights = build_shock_weights(steps)
    total_initial_shock = clamp(
        market_shock + currency_shock + sector_shock + interest_rate_shock,
        -0.35,
        0.35,
    )
    target_return = trend_per_step * profile_trend
    previous_return = target_return

    for step_index in range(steps):
        market_component = generator.gauss(
            0,
            volatility_per_step * profile_volatility,
        )
        idiosyncratic_component = generator.gauss(
            0,
            volatility_per_step * profile_volatility * profile_noise,
        )
        noise_component = generator.uniform(
            -noise_per_step * profile_noise,
            noise_per_step * profile_noise,
        )
        period_return = (
            target_return
            + systematic_risk * market_component
            + (1 - systematic_risk) * idiosyncratic_component
            + noise_component
        )
        period_return += income_yield_per_step
        period_return += mean_reversion_strength * (target_return - previous_return)
        period_return -= inflation_per_step * profile_inflation
        if step_index < len(shock_weights):
            period_return += total_initial_shock * shock_weights[step_index]
        current_value = max(current_value * (1 + period_return), 0.0)
        previous_return = period_return
        values.append(current_value)

    return values


@transaction.atomic
def run_scenario_simulation(scenario_id, seed=None):
    scenario = (
        Scenario.objects
        .select_related("portfolio", "user")
        .prefetch_related("portfolio__positions__instrument")
        .get(pk=scenario_id)
    )

    positions = get_portfolio_positions(scenario)
    start_value = get_portfolio_start_value(scenario)
    if start_value <= 0:
        raise ValueError("Portfolio has no positive current value to simulate.")

    step_days = float(scenario.time_step)
    years_per_step = step_days / 365
    trend_per_step = float(scenario.trend) * years_per_step
    volatility_per_step = float(scenario.volatility) * sqrt(years_per_step)
    noise_per_step = float(scenario.noise_level) * sqrt(years_per_step)
    market_shock = float(scenario.market_shock)
    currency_shock = float(scenario.currency_shock)
    inflation_per_step = float(scenario.inflation_shock) * years_per_step
    sector_target = scenario.sector_target or ""
    sector_shock = float(scenario.sector_shock)
    interest_rate_shock = float(scenario.interest_rate_shock)
    systematic_risk = float(scenario.systematic_risk)
    mean_reversion_strength = float(scenario.mean_reversion_strength)
    steps = max(1, ceil(float(scenario.time_horizon) / step_days))
    iterations_count = int(scenario.iterations_count)
    start_value_float = float(start_value)
    generator = random.Random(seed)
    base_currency = normalize_currency_code(scenario.portfolio.base_currency)

    final_values = []
    iteration_returns = []
    max_drawdowns = []
    path_sums = [0.0] * (steps + 1)
    position_path_sums = {
        position.id: [0.0] * (steps + 1)
        for position in positions
    }
    position_sample_paths = {}
    sample_paths = []
    drawdown_path_sums = [0.0] * (steps + 1)

    for _ in range(iterations_count):
        position_paths = []

        for position in positions:
            raw_position_start_value = Decimal(position.quantity) * Decimal(position.instrument.current_price)
            converted_position_start_value = convert_amount(
                raw_position_start_value,
                position.instrument.currency,
                base_currency,
            )
            if converted_position_start_value is None:
                raise ValueError("Missing exchange rate for portfolio currency conversion.")
            position_start_value = float(converted_position_start_value)
            profile = get_instrument_profile(position)
            income_yield_per_step = get_income_yield(position) * years_per_step
            position_path = build_instrument_path(
                start_value=position_start_value,
                profile=profile,
                trend_per_step=trend_per_step,
                volatility_per_step=volatility_per_step,
                noise_per_step=noise_per_step,
                income_yield_per_step=income_yield_per_step,
                market_shock=market_shock,
                currency_shock=get_currency_multiplier(position, currency_shock, base_currency),
                inflation_per_step=inflation_per_step,
                sector_shock=get_sector_multiplier(position, sector_target, sector_shock),
                interest_rate_shock=get_interest_rate_multiplier(position, interest_rate_shock),
                systematic_risk=systematic_risk,
                mean_reversion_strength=mean_reversion_strength,
                steps=steps,
                generator=generator,
            )
            position_paths.append(position_path)

            for index, value in enumerate(position_path):
                position_path_sums[position.id][index] += value

            if position.id not in position_sample_paths:
                position_sample_paths[position.id] = position_path

        portfolio_path = combine_paths(position_paths)
        final_value = portfolio_path[-1]
        final_values.append(final_value)
        iteration_returns.append((final_value - start_value_float) / start_value_float)
        max_drawdowns.append(calculate_max_drawdown(portfolio_path))
        running_peak = portfolio_path[0]
        for index, value in enumerate(portfolio_path):
            running_peak = max(running_peak, value)
            drawdown = ((running_peak - value) / running_peak) if running_peak > 0 else 0.0
            drawdown_path_sums[index] += drawdown

        for index, value in enumerate(portfolio_path):
            path_sums[index] += value

        if len(sample_paths) < SAMPLE_PATHS_LIMIT:
            sample_paths.append(format_chart_path(portfolio_path))

    expected_return = mean(iteration_returns)
    portfolio_volatility = pstdev(iteration_returns) if len(iteration_returns) > 1 else 0.0
    average_final_value = mean(final_values)
    median_final_value = median(final_values)
    max_drawdown = max(max_drawdowns) if max_drawdowns else 0.0

    sorted_returns = sorted(iteration_returns)
    sorted_final_values = sorted(final_values)
    tail_cutoff_95 = percentile(sorted_returns, 0.05)
    value_at_risk_95 = abs(tail_cutoff_95)
    tail_returns_95 = [value for value in sorted_returns if value <= tail_cutoff_95]
    conditional_var_95 = abs(mean(tail_returns_95)) if tail_returns_95 else value_at_risk_95
    sharpe_ratio = expected_return / portfolio_volatility if portfolio_volatility else 0.0
    probability_of_loss = sum(value < 0 for value in iteration_returns) / len(iteration_returns)
    probability_of_critical_drawdown = (
        sum(value >= CRITICAL_DRAWDOWN_LEVEL for value in max_drawdowns) / len(max_drawdowns)
        if max_drawdowns
        else 0.0
    )
    percentile_5_final_value = percentile(sorted_final_values, 0.05)
    percentile_95_final_value = percentile(sorted_final_values, 0.95)

    average_path = [value / iterations_count for value in path_sums]
    average_drawdown_path = [value / iterations_count for value in drawdown_path_sums]
    best_final_value = max(final_values)
    worst_final_value = min(final_values)
    position_paths = []

    for position in positions:
        raw_position_start_value = Decimal(position.quantity) * Decimal(position.instrument.current_price)
        position_start_value = convert_amount(raw_position_start_value, position.instrument.currency, base_currency)
        if position_start_value is None:
            raise ValueError("Missing exchange rate for portfolio currency conversion.")
        average_position_path = [value / iterations_count for value in position_path_sums[position.id]]
        chart_position_path = position_sample_paths.get(position.id, average_position_path)
        final_position_value = average_position_path[-1]
        position_return = (
            (final_position_value - float(position_start_value)) / float(position_start_value)
            if position_start_value > 0
            else 0.0
        )
        annual_income_yield = get_income_yield(position)
        position_paths.append({
            "ticker": position.instrument.ticker,
            "name": position.instrument.name,
            "currency": position.instrument.currency,
            "base_currency": base_currency,
            "instrument_type": position.instrument.instrument_type,
            "quantity": position.quantity,
            "annual_income_yield_percent": float(quantize_decimal(annual_income_yield * 100)),
            "start_value": float(quantize_decimal(position_start_value, DECIMAL_2)),
            "final_value": float(quantize_decimal(final_position_value, DECIMAL_2)),
            "return_percent": float(quantize_decimal(position_return * 100)),
            "values": format_chart_path(average_position_path),
            "sample_values": format_chart_path(chart_position_path),
            "average_values": format_chart_path(average_position_path),
        })

    result = SimulationResult.objects.create(
        scenario=scenario,
        expected_return=quantize_decimal(expected_return),
        portfolio_volatility=quantize_decimal(portfolio_volatility),
        final_value=quantize_decimal(average_final_value, DECIMAL_2),
        max_drawdown=quantize_decimal(max_drawdown),
        status="completed",
        comment=(
            f"Simulated {iterations_count} iterations with {steps} steps. "
            f"Portfolio instruments move separately under a shared market factor "
            f"({quantize_decimal(systematic_risk)}), market shock {quantize_decimal(market_shock)} "
            f"currency shock {quantize_decimal(currency_shock)} for non-base-currency assets, "
            f"inflation shock {quantize_decimal(scenario.inflation_shock)} "
            f"with mean reversion {quantize_decimal(mean_reversion_strength, Decimal('0.0001'))}, "
            f"sector shock {quantize_decimal(sector_shock)} for sector '{sector_target or 'all'}', "
            f"interest-rate shock {quantize_decimal(interest_rate_shock)} for bonds, "
            f"and annual income yields from coupons or dividends."
        ),
        chart_data={
            "labels": format_chart_labels(len(average_path), step_days),
            "average_path": format_chart_path(average_path),
            "average_drawdown_path_percent": [
                float(quantize_decimal(-value * 100, DECIMAL_2))
                for value in downsample_path(average_drawdown_path)
            ],
            "sample_paths": sample_paths,
            "position_paths": position_paths,
            "start_value": float(start_value.quantize(DECIMAL_2)),
            "average_final_value": float(quantize_decimal(average_final_value, DECIMAL_2)),
            "median_final_value": float(quantize_decimal(median_final_value, DECIMAL_2)),
            "best_final_value": float(quantize_decimal(best_final_value, DECIMAL_2)),
            "worst_final_value": float(quantize_decimal(worst_final_value, DECIMAL_2)),
            "percentile_5_final_value": float(quantize_decimal(percentile_5_final_value, DECIMAL_2)),
            "percentile_95_final_value": float(quantize_decimal(percentile_95_final_value, DECIMAL_2)),
            "expected_return_percent": float(quantize_decimal(expected_return * 100)),
            "max_drawdown_percent": float(quantize_decimal(max_drawdown * 100)),
            "probability_of_loss_percent": float(quantize_decimal(probability_of_loss * 100)),
            "probability_of_critical_drawdown_percent": float(
                quantize_decimal(probability_of_critical_drawdown * 100)
            ),
            "market_shock_percent": float(quantize_decimal(market_shock * 100)),
            "currency_shock_percent": float(quantize_decimal(currency_shock * 100)),
            "inflation_shock_percent": float(quantize_decimal(float(scenario.inflation_shock) * 100)),
            "sector_target": sector_target,
            "sector_shock_percent": float(quantize_decimal(sector_shock * 100)),
            "interest_rate_shock_percent": float(quantize_decimal(interest_rate_shock * 100)),
            "systematic_risk_percent": float(quantize_decimal(systematic_risk * 100)),
            "mean_reversion_strength_percent": float(quantize_decimal(mean_reversion_strength * 100)),
            "base_currency": base_currency,
            "steps": steps,
            "iterations": iterations_count,
        },
    )

    metrics = RiskMetric.objects.bulk_create([
        RiskMetric(
            simulation_result=result,
            metric_name="VaR 95%",
            metric_value=quantize_decimal(value_at_risk_95),
            confidence_level=Decimal("95.00"),
        ),
        RiskMetric(
            simulation_result=result,
            metric_name="CVaR 95%",
            metric_value=quantize_decimal(conditional_var_95),
            confidence_level=Decimal("95.00"),
        ),
        RiskMetric(
            simulation_result=result,
            metric_name="Sharpe Ratio",
            metric_value=quantize_decimal(sharpe_ratio),
        ),
        RiskMetric(
            simulation_result=result,
            metric_name="Probability of Loss",
            metric_value=quantize_decimal(probability_of_loss),
            confidence_level=Decimal("100.00"),
        ),
        RiskMetric(
            simulation_result=result,
            metric_name="Probability of Drawdown > 10%",
            metric_value=quantize_decimal(probability_of_critical_drawdown),
            confidence_level=Decimal("100.00"),
        ),
        RiskMetric(
            simulation_result=result,
            metric_name="Median Final Value",
            metric_value=quantize_decimal(median_final_value, DECIMAL_2),
        ),
        RiskMetric(
            simulation_result=result,
            metric_name="Final Value P5",
            metric_value=quantize_decimal(percentile_5_final_value, DECIMAL_2),
            confidence_level=Decimal("5.00"),
        ),
        RiskMetric(
            simulation_result=result,
            metric_name="Final Value P95",
            metric_value=quantize_decimal(percentile_95_final_value, DECIMAL_2),
            confidence_level=Decimal("95.00"),
        ),
        RiskMetric(
            simulation_result=result,
            metric_name="Iterations",
            metric_value=Decimal(iterations_count),
        ),
        RiskMetric(
            simulation_result=result,
            metric_name="Steps",
            metric_value=Decimal(steps),
        ),
    ])

    return SimulationSummary(result=result, metrics=metrics)

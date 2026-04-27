from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import ceil, sqrt
import random
from statistics import mean, median, pstdev

from django.db import transaction

from riskapp.models import RiskMetric, Scenario, SimulationResult


DECIMAL_2 = Decimal("0.01")
DECIMAL_6 = Decimal("0.000001")
MAX_CHART_POINTS = 160
SAMPLE_PATHS_LIMIT = 7
CRITICAL_DRAWDOWN_LEVEL = 0.10
INSTRUMENT_TYPE_PROFILES = {
    "stock": {"trend": 1.00, "volatility": 1.10, "noise": 1.00},
    "bond": {"trend": 0.55, "volatility": 0.35, "noise": 0.40},
    "etf": {"trend": 0.90, "volatility": 0.80, "noise": 0.70},
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
    return sum(
        Decimal(position.quantity) * Decimal(position.instrument.current_price)
        for position in positions
    )


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


def get_currency_multiplier(position, currency_shock):
    if str(position.instrument.currency).upper() in {"RUB", "SUR"}:
        return 0.0
    return currency_shock


def build_instrument_path(
    start_value,
    profile,
    trend_per_step,
    volatility_per_step,
    noise_per_step,
    market_shock,
    currency_shock,
    systematic_risk,
    steps,
    generator,
):
    values = [start_value]
    current_value = start_value
    profile_trend = profile["trend"]
    profile_volatility = profile["volatility"]
    profile_noise = profile["noise"]

    for step_index in range(steps):
        market_component = generator.gauss(
            trend_per_step * profile_trend,
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
            systematic_risk * market_component
            + (1 - systematic_risk) * idiosyncratic_component
            + noise_component
        )
        if step_index == 0:
            period_return += market_shock + currency_shock
        current_value = max(current_value * (1 + period_return), 0.0)
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
    systematic_risk = float(scenario.systematic_risk)
    steps = max(1, ceil(float(scenario.time_horizon) / step_days))
    iterations_count = int(scenario.iterations_count)
    start_value_float = float(start_value)
    generator = random.Random(seed)

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

    for _ in range(iterations_count):
        position_paths = []

        for position in positions:
            position_start_value = float(Decimal(position.quantity) * Decimal(position.instrument.current_price))
            profile = get_instrument_profile(position)
            position_path = build_instrument_path(
                start_value=position_start_value,
                profile=profile,
                trend_per_step=trend_per_step,
                volatility_per_step=volatility_per_step,
                noise_per_step=noise_per_step,
                market_shock=market_shock,
                currency_shock=get_currency_multiplier(position, currency_shock),
                systematic_risk=systematic_risk,
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
    best_final_value = max(final_values)
    worst_final_value = min(final_values)
    position_paths = []

    for position in positions:
        position_start_value = Decimal(position.quantity) * Decimal(position.instrument.current_price)
        average_position_path = [value / iterations_count for value in position_path_sums[position.id]]
        chart_position_path = position_sample_paths.get(position.id, average_position_path)
        final_position_value = chart_position_path[-1]
        position_return = (
            (final_position_value - float(position_start_value)) / float(position_start_value)
            if position_start_value > 0
            else 0.0
        )
        position_paths.append({
            "ticker": position.instrument.ticker,
            "name": position.instrument.name,
            "currency": position.instrument.currency,
            "instrument_type": position.instrument.instrument_type,
            "quantity": position.quantity,
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
            f"and currency shock {quantize_decimal(currency_shock)} for non-RUB assets."
        ),
        chart_data={
            "labels": format_chart_labels(len(average_path), step_days),
            "average_path": format_chart_path(average_path),
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
            "systematic_risk_percent": float(quantize_decimal(systematic_risk * 100)),
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

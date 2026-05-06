from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
from math import sqrt
from statistics import mean, pstdev

from django.utils import timezone

from riskapp.models import InstrumentPriceHistory, Portfolio, Scenario
from riskapp.services.exchange_rates import convert_amount, normalize_currency_code


DECIMAL_4 = Decimal("0.0001")
DECIMAL_6 = Decimal("0.000001")
MIN_RETURN_OBSERVATIONS = 8
MIN_PAIR_OBSERVATIONS = 5


def quantize_decimal(value, precision=DECIMAL_6):
    return Decimal(str(value)).quantize(precision, rounding=ROUND_HALF_UP)


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def calculate_correlation(series_a, series_b):
    if len(series_a) != len(series_b) or len(series_a) < MIN_PAIR_OBSERVATIONS:
        return None
    mean_a = mean(series_a)
    mean_b = mean(series_b)
    covariance = sum((value_a - mean_a) * (value_b - mean_b) for value_a, value_b in zip(series_a, series_b))
    variance_a = sum((value - mean_a) ** 2 for value in series_a)
    variance_b = sum((value - mean_b) ** 2 for value in series_b)
    if variance_a <= 0 or variance_b <= 0:
        return None
    return covariance / sqrt(variance_a * variance_b)


def build_daily_return_series(history_rows):
    daily_prices = {}
    for row in history_rows:
        daily_key = timezone.localtime(row.captured_at).date()
        daily_prices[daily_key] = Decimal(row.price)

    ordered_dates = sorted(daily_prices.keys())
    if len(ordered_dates) < 2:
        return {}, None, None

    returns = {}
    previous_date = ordered_dates[0]
    previous_price = daily_prices[previous_date]
    for current_date in ordered_dates[1:]:
        current_price = daily_prices[current_date]
        if previous_price > 0:
            returns[current_date] = float((current_price / previous_price) - Decimal("1"))
        previous_date = current_date
        previous_price = current_price

    if not returns:
        return {}, None, None

    return returns, ordered_dates[0], ordered_dates[-1]


def get_current_portfolio_weights(portfolio):
    base_currency = normalize_currency_code(portfolio.base_currency)
    raw_weights = {}
    total_value = Decimal("0")

    positions = portfolio.positions.select_related("instrument").all()
    for position in positions:
        instrument = position.instrument
        current_value = Decimal(position.quantity) * Decimal(instrument.current_price)
        instrument_currency = normalize_currency_code(instrument.currency)
        converted_value = current_value
        if instrument_currency != base_currency:
            converted_value = convert_amount(current_value, instrument_currency, base_currency)
        if converted_value is None or converted_value <= 0:
            continue
        raw_weights[position.instrument_id] = converted_value
        total_value += converted_value

    if total_value <= 0:
        raise ValueError("Portfolio has no positions with convertible current value.")

    return {
        instrument_id: float(value / total_value)
        for instrument_id, value in raw_weights.items()
    }


@dataclass(frozen=True)
class HistoricalCalibrationSummary:
    lookback_days: int
    instruments_used: int
    observations_used: int
    annual_trend: Decimal
    annual_volatility: Decimal
    noise_level: Decimal
    systematic_risk: Decimal
    mean_pair_correlation: Decimal | None
    first_date: object | None
    last_date: object | None

    def as_form_values(self):
        return {
            "preset": Scenario.PRESET_CUSTOM,
            "trend": f"{self.annual_trend:.6f}",
            "volatility": f"{self.annual_volatility:.6f}",
            "noise_level": f"{self.noise_level:.6f}",
            "systematic_risk": f"{self.systematic_risk:.4f}",
        }


def calibrate_portfolio_scenario_parameters(portfolio: Portfolio, lookback_days=180):
    lookback_days = int(clamp(int(lookback_days or 180), 60, 365))
    cutoff = timezone.now() - timezone.timedelta(days=lookback_days)
    weights = get_current_portfolio_weights(portfolio)
    if not weights:
        raise ValueError("Portfolio has no positions with valid prices for calibration.")

    history_rows = (
        InstrumentPriceHistory.objects
        .filter(instrument_id__in=weights.keys(), captured_at__gte=cutoff)
        .select_related("instrument")
        .order_by("instrument_id", "captured_at")
    )

    rows_by_instrument = defaultdict(list)
    for row in history_rows:
        rows_by_instrument[row.instrument_id].append(row)

    series_by_instrument = {}
    period_starts = []
    period_ends = []
    for instrument_id, rows in rows_by_instrument.items():
        returns, series_start, series_end = build_daily_return_series(rows)
        if len(returns) < MIN_RETURN_OBSERVATIONS:
            continue
        series_by_instrument[instrument_id] = returns
        period_starts.append(series_start)
        period_ends.append(series_end)

    if not series_by_instrument:
        raise ValueError("Not enough historical price observations for calibration.")

    portfolio_returns_by_date = {}
    all_dates = sorted({
        date_value
        for series in series_by_instrument.values()
        for date_value in series.keys()
    })
    for date_value in all_dates:
        available = [
            (weights[instrument_id], series[date_value])
            for instrument_id, series in series_by_instrument.items()
            if date_value in series
        ]
        if not available:
            continue
        weight_total = sum(weight for weight, _ in available)
        if weight_total <= 0:
            continue
        portfolio_returns_by_date[date_value] = sum(
            (weight / weight_total) * return_value
            for weight, return_value in available
        )

    if len(portfolio_returns_by_date) < MIN_RETURN_OBSERVATIONS:
        raise ValueError("Not enough aligned historical observations for calibration.")

    ordered_portfolio_dates = sorted(portfolio_returns_by_date.keys())
    portfolio_returns = [portfolio_returns_by_date[date_value] for date_value in ordered_portfolio_dates]
    elapsed_days = max((ordered_portfolio_dates[-1] - ordered_portfolio_dates[0]).days, len(portfolio_returns))
    avg_gap_days = max(elapsed_days / max(len(portfolio_returns), 1), 1)
    periods_per_year = 365 / avg_gap_days

    cumulative_growth = 1.0
    for return_value in portfolio_returns:
        cumulative_growth *= (1 + return_value)

    annual_trend = clamp(cumulative_growth ** (365 / elapsed_days) - 1, -0.30, 0.30)
    annual_volatility = clamp(
        pstdev(portfolio_returns) * sqrt(periods_per_year) if len(portfolio_returns) > 1 else 0.0,
        0.01,
        0.60,
    )

    pairwise_correlations = []
    for left_id, right_id in combinations(sorted(series_by_instrument.keys()), 2):
        left_series = series_by_instrument[left_id]
        right_series = series_by_instrument[right_id]
        overlap_dates = sorted(set(left_series.keys()) & set(right_series.keys()))
        if len(overlap_dates) < MIN_PAIR_OBSERVATIONS:
            continue
        correlation = calculate_correlation(
            [left_series[date_value] for date_value in overlap_dates],
            [right_series[date_value] for date_value in overlap_dates],
        )
        if correlation is not None:
            pairwise_correlations.append(correlation)

    mean_pair_correlation = mean(pairwise_correlations) if pairwise_correlations else None
    if mean_pair_correlation is None:
        systematic_risk = 0.35 if len(series_by_instrument) == 1 else 0.45
    else:
        systematic_risk = clamp(0.15 + max(mean_pair_correlation, 0) * 0.60, 0.15, 0.85)

    weighted_residual_volatility = 0.0
    for instrument_id, series in series_by_instrument.items():
        overlap_dates = [date_value for date_value in ordered_portfolio_dates if date_value in series]
        if len(overlap_dates) < MIN_PAIR_OBSERVATIONS:
            continue
        residuals = [
            series[date_value] - portfolio_returns_by_date[date_value]
            for date_value in overlap_dates
        ]
        residual_volatility = pstdev(residuals) * sqrt(periods_per_year) if len(residuals) > 1 else 0.0
        weighted_residual_volatility += weights.get(instrument_id, 0.0) * residual_volatility

    if weighted_residual_volatility <= 0:
        weighted_residual_volatility = annual_volatility * max(0.10, 1 - systematic_risk)

    noise_level = clamp(
        max(weighted_residual_volatility * 0.45, annual_volatility * 0.08),
        0.005,
        0.120,
    )

    return HistoricalCalibrationSummary(
        lookback_days=lookback_days,
        instruments_used=len(series_by_instrument),
        observations_used=len(portfolio_returns),
        annual_trend=quantize_decimal(annual_trend, DECIMAL_6),
        annual_volatility=quantize_decimal(annual_volatility, DECIMAL_6),
        noise_level=quantize_decimal(noise_level, DECIMAL_6),
        systematic_risk=quantize_decimal(systematic_risk, DECIMAL_4),
        mean_pair_correlation=(
            quantize_decimal(mean_pair_correlation, DECIMAL_4)
            if mean_pair_correlation is not None
            else None
        ),
        first_date=min(period_starts) if period_starts else None,
        last_date=max(period_ends) if period_ends else None,
    )

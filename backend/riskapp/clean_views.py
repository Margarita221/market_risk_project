from decimal import Decimal

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from riskapp.forms import StrategyComparisonForm
from riskapp.i18n import get_request_language, translate
from riskapp.models import Instrument, Portfolio, RiskMetric, Scenario, SimulationResult
from riskapp.views import (
    build_line_chart_svg,
    build_marker_indexes,
    build_report_response,
    format_display_number,
    format_display_percent,
    get_portfolio_unit_label,
    localize_metric,
    to_decimal,
    user_scope,
)


def localized_text(language, ru, en):
    return ru if language == "ru" else en


def get_preset_label(value, language):
    labels = {
        Scenario.PRESET_CUSTOM: localized_text(language, "Пользовательский", "Custom"),
        Scenario.PRESET_BASE: localized_text(language, "Базовый", "Base"),
        Scenario.PRESET_OPTIMISTIC: localized_text(language, "Оптимистичный", "Optimistic"),
        Scenario.PRESET_PESSIMISTIC: localized_text(language, "Пессимистичный", "Pessimistic"),
        Scenario.PRESET_STRESS: localized_text(language, "Стрессовый", "Stress"),
        Scenario.PRESET_CRISIS: localized_text(language, "Кризисный", "Crisis"),
    }
    return labels.get(value, value or "-")


def get_rebalancing_label(value, language):
    labels = {
        Scenario.REBALANCE_NONE: localized_text(language, "Без ребалансировки", "Buy and hold"),
        Scenario.REBALANCE_MONTHLY: localized_text(language, "Ежемесячная ребалансировка", "Monthly rebalance"),
        Scenario.REBALANCE_QUARTERLY: localized_text(language, "Квартальная ребалансировка", "Quarterly rebalance"),
    }
    return labels.get(value, value or "-")


def get_metric_map(result):
    return {
        metric.metric_name: metric.metric_value
        for metric in result.risk_metrics.all()
    }


def format_metric_display(metric_name, metric_value, portfolio_unit_label, language):
    percent_metrics = {
        "VaR 95%",
        "CVaR 95%",
        "Probability of Loss",
        "Probability of Drawdown > 10%",
    }
    currency_metrics = {
        "Median Final Value",
        "Final Value P5",
        "Final Value P95",
    }
    count_metrics = {"Iterations", "Steps"}
    if metric_name in percent_metrics:
        return f"{format_display_percent(metric_value, 2)} {translate('unit_percent', language)}"
    if metric_name in currency_metrics:
        return f"{format_display_number(metric_value, 2)} {portfolio_unit_label}"
    if metric_name in count_metrics:
        return format_display_number(metric_value, 0)
    return format_display_number(metric_value, 4)


def get_result_distribution_context(result, language):
    chart_data = result.chart_data or {}
    portfolio_unit_label = get_portfolio_unit_label(result.scenario.portfolio, language)
    start_value = to_decimal(chart_data.get("start_value", 0))
    worst_value = to_decimal(chart_data.get("worst_final_value", result.final_value))
    best_value = to_decimal(chart_data.get("best_final_value", result.final_value))
    median_value = to_decimal(chart_data.get("median_final_value", result.final_value))
    p5_value = to_decimal(chart_data.get("percentile_5_final_value", result.final_value))
    p95_value = to_decimal(chart_data.get("percentile_95_final_value", result.final_value))
    value_span = max(best_value - worst_value, Decimal("1"))

    def marker_position(value):
        return float(((to_decimal(value) - worst_value) / value_span) * Decimal("100"))

    distribution_markers = [
        {
            "label": translate("worst_final_value", language),
            "value": format_display_number(worst_value, 2),
            "unit": portfolio_unit_label,
            "position": marker_position(worst_value),
        },
        {
            "label": "P5",
            "value": format_display_number(p5_value, 2),
            "unit": portfolio_unit_label,
            "position": marker_position(p5_value),
        },
        {
            "label": translate("median_final_value", language),
            "value": format_display_number(median_value, 2),
            "unit": portfolio_unit_label,
            "position": marker_position(median_value),
        },
        {
            "label": "P95",
            "value": format_display_number(p95_value, 2),
            "unit": portfolio_unit_label,
            "position": marker_position(p95_value),
        },
        {
            "label": translate("best_final_value", language),
            "value": format_display_number(best_value, 2),
            "unit": portfolio_unit_label,
            "position": marker_position(best_value),
        },
    ]
    distribution_range = {
        "start": format_display_number(worst_value, 2),
        "end": format_display_number(best_value, 2),
        "delta_percent": format_display_percent(
            ((best_value - start_value) / start_value) if start_value > 0 else 0,
            2,
        ),
    }
    return distribution_markers, distribution_range


def build_result_notes(result, language):
    chart_data = result.chart_data or {}
    scenario = result.scenario
    notes = [
        translate(
            "run_note_iterations_steps",
            language,
            iterations=chart_data.get("iterations", scenario.iterations_count),
            steps=chart_data.get("steps", "-"),
        ),
        localized_text(
            language,
            f"Пресет сценария: {get_preset_label(scenario.preset, language)}.",
            f"Scenario preset: {get_preset_label(scenario.preset, language)}.",
        ),
        localized_text(
            language,
            f"Режим стратегии: {get_rebalancing_label(scenario.rebalancing_frequency, language)}.",
            f"Strategy mode: {get_rebalancing_label(scenario.rebalancing_frequency, language)}.",
        ),
        translate("run_note_chart_consistency", language),
    ]
    if chart_data.get("rebalancing_marker_days"):
        notes.append(
            localized_text(
                language,
                "Пунктирные вертикальные линии на графике отмечают даты ребалансировки портфеля.",
                "Dashed vertical lines on the chart mark portfolio rebalance dates.",
            )
        )
    return notes


def build_result_context(result, language):
    portfolio_unit_label = get_portfolio_unit_label(result.scenario.portfolio, language)
    metrics = [
        localize_metric(metric, language, portfolio_unit_label)
        for metric in result.risk_metrics.order_by("metric_name")
    ]
    distribution_markers, distribution_range = get_result_distribution_context(result, language)
    chart_data = result.chart_data or {}
    return {
        "result": result,
        "ui_language": language,
        "status_label": translate("status_completed", language),
        "portfolio_unit_label": portfolio_unit_label,
        "metrics": metrics,
        "run_notes": build_result_notes(result, language),
        "distribution_markers": distribution_markers,
        "distribution_range": distribution_range,
        "risk_overview": [
            {
                "label": translate("probability_of_loss", language),
                "value": chart_data.get("probability_of_loss_percent", 0),
                "note": translate("risk_meter_loss_note", language),
            },
            {
                "label": translate("probability_of_drawdown", language),
                "value": chart_data.get("probability_of_critical_drawdown_percent", 0),
                "note": translate("risk_meter_drawdown_note", language),
            },
            {
                "label": translate("volatility", language),
                "value": float(to_decimal(result.portfolio_volatility) * Decimal("100")),
                "note": translate("risk_meter_volatility_note", language),
            },
            {
                "label": translate("systematic_risk", language),
                "value": chart_data.get("systematic_risk_percent", 0),
                "note": translate("risk_meter_systematic_note", language),
            },
        ],
    }


def result_detail(request, result_id):
    language = get_request_language(request)
    queryset = user_scope(
        request.user,
        SimulationResult.objects.select_related("scenario", "scenario__portfolio").prefetch_related("risk_metrics"),
        owner_lookup="scenario__user",
    )
    result = get_object_or_404(queryset, pk=result_id)
    context = build_result_context(result, language)
    return render(request, "riskapp/result_detail.html", context)


def result_export(request, result_id, report_format):
    language = get_request_language(request)
    if report_format not in {"pdf", "word", "excel"}:
        raise Http404("Unsupported report format")
    queryset = user_scope(
        request.user,
        SimulationResult.objects.select_related("scenario", "scenario__portfolio").prefetch_related("risk_metrics"),
        owner_lookup="scenario__user",
    )
    result = get_object_or_404(queryset, pk=result_id)
    context = build_result_context(result, language)
    chart_data = result.chart_data or {}
    marker_indexes = build_marker_indexes(chart_data.get("labels", []), chart_data.get("rebalancing_marker_days", []))
    portfolio_chart_svg = ""
    if chart_data.get("average_path"):
        portfolio_chart_svg = build_line_chart_svg(
            [{"label": result.scenario.name, "values": chart_data.get("average_path", [])}],
            marker_indexes=marker_indexes,
            percent_axis=False,
        )
    context.update(
        {
            "report_format": report_format,
            "report_generated_at": timezone.localtime(),
            "report_title": localized_text(language, "Отчёт по моделированию сценария", "Scenario simulation report"),
            "portfolio_chart_svg": portfolio_chart_svg,
            "result_summary_rows": [
                (translate("start_value", language), f"{format_display_number(chart_data.get('start_value', 0), 2)} {context['portfolio_unit_label']}"),
                (translate("average_final_value", language), f"{format_display_number(chart_data.get('average_final_value', result.final_value), 2)} {context['portfolio_unit_label']}"),
                (translate("expected_return", language), f"{format_display_percent(result.expected_return, 2)} {translate('unit_percent', language)}"),
                (translate("volatility", language), f"{format_display_percent(result.portfolio_volatility, 2)} {translate('unit_percent', language)}"),
                (translate("max_drawdown", language), f"{format_display_percent(result.max_drawdown, 2)} {translate('unit_percent', language)}"),
                (
                    "CVaR 95%",
                    next(
                        (
                            f"{metric['display_value']} {metric['unit']}"
                            for metric in context["metrics"]
                            if metric["name"] == "CVaR 95%"
                        ),
                        "-",
                    ),
                ),
            ],
        }
    )
    return build_report_response(
        template_name="riskapp/reports/result_report.html",
        context=context,
        report_format=report_format,
        filename_stem=f"scenario-result-{result.id}",
    )


def get_scenario_family_key(result):
    scenario = result.scenario
    return (
        scenario.preset,
        str(scenario.trend),
        str(scenario.volatility),
        str(scenario.noise_level),
        str(scenario.market_shock),
        str(scenario.currency_shock),
        str(scenario.inflation_shock),
        scenario.sector_target or "",
        str(scenario.sector_shock),
        str(scenario.interest_rate_shock),
        str(scenario.jump_intensity),
        str(scenario.jump_magnitude),
        str(scenario.systematic_risk),
        str(scenario.mean_reversion_strength),
        str(scenario.time_horizon),
        str(scenario.time_step),
        str(scenario.iterations_count),
    )


def build_strategy_comparison_payload(results, language):
    comparison_results = []
    chart_series = []

    for result in results:
        metric_map = get_metric_map(result)
        portfolio_unit_label = get_portfolio_unit_label(result.scenario.portfolio, language)
        average_path = (result.chart_data or {}).get("average_path", [])
        start_value = to_decimal(average_path[0] if average_path else 0)
        normalized_path = []
        for point in average_path:
            point_decimal = to_decimal(point)
            if start_value > 0:
                normalized_path.append(float(((point_decimal / start_value) - Decimal("1")) * Decimal("100")))
            else:
                normalized_path.append(0.0)

        selection_label = localized_text(
            language,
            f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%d.%m.%Y %H:%M')}",
            f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
        )
        comparison_results.append(
            {
                "id": result.id,
                "scenario_id": result.scenario_id,
                "scenario_name": result.scenario.name,
                "scenario_preset_label": get_preset_label(result.scenario.preset, language),
                "portfolio_name": result.scenario.portfolio.name,
                "execution_time": result.execution_time,
                "selection_label": selection_label,
                "portfolio_unit_label": portfolio_unit_label,
                "expected_return": result.expected_return,
                "final_value": result.final_value,
                "volatility": result.portfolio_volatility,
                "max_drawdown": result.max_drawdown,
                "probability_of_loss": metric_map.get("Probability of Loss", Decimal("0")),
                "probability_of_drawdown": metric_map.get("Probability of Drawdown > 10%", Decimal("0")),
                "var_95": metric_map.get("VaR 95%", Decimal("0")),
                "cvar_95": metric_map.get("CVaR 95%", Decimal("0")),
                "sharpe_ratio": metric_map.get("Sharpe Ratio", Decimal("0")),
                "rebalancing_frequency": result.scenario.rebalancing_frequency,
                "rebalancing_label": get_rebalancing_label(result.scenario.rebalancing_frequency, language),
                "market_signature": get_scenario_family_key(result),
            }
        )
        chart_series.append({"label": selection_label, "values": normalized_path})

    metric_specs = [
        (localized_text(language, "Средний итог", "Average final value"), "final_value"),
        (localized_text(language, "Ожидаемая доходность", "Expected return"), "expected_return"),
        (localized_text(language, "Волатильность", "Volatility"), "volatility"),
        (localized_text(language, "Максимальная просадка", "Max drawdown"), "max_drawdown"),
        (localized_text(language, "Вероятность убытка", "Probability of loss"), "probability_of_loss"),
        (localized_text(language, "Вероятность просадки > 10%", "Probability of drawdown > 10%"), "probability_of_drawdown"),
        ("VaR 95%", "var_95"),
        ("CVaR 95%", "cvar_95"),
        (localized_text(language, "Коэффициент Шарпа", "Sharpe ratio"), "sharpe_ratio"),
    ]

    comparison_rows = []
    for label, field_name in metric_specs:
        values = [
            format_metric_display(
                {
                    "final_value": "Median Final Value",
                    "expected_return": "Probability of Loss",  # placeholder bypassed below
                    "volatility": "Probability of Loss",
                    "max_drawdown": "Probability of Loss",
                    "probability_of_loss": "Probability of Loss",
                    "probability_of_drawdown": "Probability of Drawdown > 10%",
                    "var_95": "VaR 95%",
                    "cvar_95": "CVaR 95%",
                    "sharpe_ratio": "Sharpe Ratio",
                }.get(field_name, field_name),
                item[field_name],
                item["portfolio_unit_label"],
                language,
            )
            if field_name not in {"expected_return", "volatility", "max_drawdown"}
            else f"{format_display_percent(item[field_name], 2)} {translate('unit_percent', language)}"
            for item in comparison_results
        ]
        if field_name == "final_value":
            values = [
                f"{format_display_number(item['final_value'], 2)} {item['portfolio_unit_label']}"
                for item in comparison_results
            ]
        elif field_name == "sharpe_ratio":
            values = [format_display_number(item["sharpe_ratio"], 4) for item in comparison_results]
        comparison_rows.append({"label": label, "values": values})

    return comparison_results, comparison_rows, chart_series


def build_rebalancing_insights(comparison_results, language):
    grouped_results = {}
    for item in comparison_results:
        grouped_results.setdefault(item["market_signature"], []).append(item)

    insights = []
    for group_items in grouped_results.values():
        baseline = next(
            (item for item in group_items if item["rebalancing_frequency"] == Scenario.REBALANCE_NONE),
            None,
        )
        if baseline is None:
            continue
        for item in group_items:
            if item["id"] == baseline["id"]:
                continue
            insights.append(
                {
                    "scenario_name": item["scenario_name"],
                    "target_label": item["rebalancing_label"],
                    "baseline_label": baseline["rebalancing_label"],
                    "portfolio_unit_label": item["portfolio_unit_label"],
                    "final_value_delta": to_decimal(item["final_value"]) - to_decimal(baseline["final_value"]),
                    "expected_return_delta": to_decimal(item["expected_return"]) - to_decimal(baseline["expected_return"]),
                    "drawdown_delta": to_decimal(item["max_drawdown"]) - to_decimal(baseline["max_drawdown"]),
                    "loss_probability_delta": to_decimal(item["probability_of_loss"]) - to_decimal(baseline["probability_of_loss"]),
                }
            )
    return insights


def resolve_strategy_compare_state(request, language):
    portfolios_queryset = user_scope(request.user, Portfolio.objects.all())
    results_queryset = user_scope(
        request.user,
        SimulationResult.objects.select_related("scenario", "scenario__portfolio").prefetch_related("risk_metrics"),
        owner_lookup="scenario__user",
    )
    default_portfolio = None
    if request.method == "GET" and not request.GET:
        default_portfolio_id = (
            results_queryset.order_by("-execution_time")
            .values_list("scenario__portfolio_id", flat=True)
            .first()
        )
        if default_portfolio_id:
            default_portfolio = portfolios_queryset.filter(id=default_portfolio_id).first()

    form = StrategyComparisonForm(
        request.GET or None,
        portfolios_queryset=portfolios_queryset,
        language=language,
        initial={"portfolio": default_portfolio.id} if default_portfolio else None,
    )

    selected_portfolio = None
    comparison_results = []
    comparison_rows = []
    chart_series = []
    available_results = []
    selected_result_ids = set()
    selection_submitted = request.GET.get("selection_mode") == "custom"
    rebalancing_insights = []

    if form.is_bound and form.is_valid():
        selected_portfolio = form.cleaned_data["portfolio"]
    elif not form.is_bound and default_portfolio:
        selected_portfolio = default_portfolio

    if selected_portfolio is not None:
        portfolio_results = list(
            results_queryset
            .filter(scenario__portfolio=selected_portfolio)
            .order_by("scenario__name", "-execution_time", "-id")
        )
        raw_selected_ids = {
            int(value)
            for value in request.GET.getlist("results")
            if str(value).isdigit()
        }
        if selection_submitted:
            filtered_results = [result for result in portfolio_results if result.id in raw_selected_ids]
            selected_result_ids = raw_selected_ids
        else:
            filtered_results = portfolio_results
            selected_result_ids = {result.id for result in portfolio_results}

        available_results = [
            {
                "id": result.id,
                "label": localized_text(
                    language,
                    f"{result.scenario.name} · {get_rebalancing_label(result.scenario.rebalancing_frequency, language)} · {timezone.localtime(result.execution_time).strftime('%d.%m.%Y %H:%M')}",
                    f"{result.scenario.name} · {get_rebalancing_label(result.scenario.rebalancing_frequency, language)} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
                ),
                "checked": result.id in selected_result_ids,
            }
            for result in portfolio_results
        ]
        comparison_results, comparison_rows, chart_series = build_strategy_comparison_payload(filtered_results, language)
        rebalancing_insights = build_rebalancing_insights(comparison_results, language)

    return {
        "form": form,
        "ui_language": language,
        "comparison_results": comparison_results,
        "comparison_rows": comparison_rows,
        "chart_series": chart_series,
        "selected_portfolio": selected_portfolio,
        "available_results": available_results,
        "selected_result_ids": selected_result_ids,
        "selection_submitted": selection_submitted,
        "rebalancing_insights": rebalancing_insights,
    }


def strategy_compare(request):
    language = get_request_language(request)
    context = resolve_strategy_compare_state(request, language)
    return render(request, "riskapp/strategy_compare_clean.html", context)


def strategy_compare_export(request, report_format):
    language = get_request_language(request)
    if report_format not in {"pdf", "word", "excel"}:
        raise Http404("Unsupported report format")
    state = resolve_strategy_compare_state(request, language)
    if not state["comparison_results"]:
        raise Http404("No comparison results selected")
    chart_svg = build_line_chart_svg(state["chart_series"], percent_axis=True) if state["chart_series"] else ""
    context = {
        **state,
        "report_format": report_format,
        "report_generated_at": timezone.localtime(),
        "report_title": localized_text(language, "Сравнение стратегий", "Strategy comparison"),
        "chart_svg": chart_svg,
    }
    return build_report_response(
        template_name="riskapp/reports/strategy_compare_report.html",
        context=context,
        report_format=report_format,
        filename_stem=f"strategy-compare-{timezone.now().strftime('%Y%m%d-%H%M%S')}",
    )

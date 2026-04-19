from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from riskapp.models import Portfolio, PortfolioPosition, Scenario, SimulationResult
from riskapp.services.simulation import run_scenario_simulation


@login_required
def dashboard(request):
    portfolios = Portfolio.objects.filter(user=request.user)
    scenarios = Scenario.objects.filter(user=request.user)
    results = SimulationResult.objects.filter(scenario__user=request.user)

    context = {
        "portfolios_count": portfolios.count(),
        "scenarios_count": scenarios.count(),
        "results_count": results.count(),
        "total_current_value": portfolios.aggregate(total=Sum("current_value"))["total"] or 0,
        "latest_results": results.select_related("scenario", "scenario__portfolio")[:5],
        "latest_portfolios": portfolios.order_by("-updated_at")[:5],
    }
    return render(request, "riskapp/dashboard.html", context)


@login_required
def portfolio_list(request):
    portfolios = (
        Portfolio.objects
        .filter(user=request.user)
        .annotate(positions_count=Count("positions"))
        .order_by("-updated_at")
    )
    return render(request, "riskapp/portfolio_list.html", {"portfolios": portfolios})


@login_required
def portfolio_detail(request, portfolio_id):
    portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)
    positions = (
        PortfolioPosition.objects
        .filter(portfolio=portfolio)
        .select_related("instrument")
        .annotate(
            purchase_value=ExpressionWrapper(
                F("quantity") * F("average_purchase_price"),
                output_field=DecimalField(max_digits=20, decimal_places=4),
            ),
            position_value=ExpressionWrapper(
                F("quantity") * F("instrument__current_price"),
                output_field=DecimalField(max_digits=20, decimal_places=4),
            ),
        )
        .order_by("instrument__ticker")
    )
    scenarios = portfolio.scenarios.filter(user=request.user).order_by("-created_at")

    return render(request, "riskapp/portfolio_detail.html", {
        "portfolio": portfolio,
        "positions": positions,
        "scenarios": scenarios,
    })


@login_required
def scenario_list(request):
    scenarios = (
        Scenario.objects
        .filter(user=request.user)
        .select_related("portfolio")
        .annotate(results_count=Count("results"))
        .order_by("-created_at")
    )
    return render(request, "riskapp/scenario_list.html", {"scenarios": scenarios})


@login_required
def run_scenario(request, scenario_id):
    scenario = get_object_or_404(
        Scenario.objects.select_related("portfolio"),
        id=scenario_id,
        user=request.user,
    )

    if request.method != "POST":
        return redirect("riskapp:scenarios")

    try:
        summary = run_scenario_simulation(scenario.id)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("riskapp:portfolio_detail", args=[scenario.portfolio_id]))

    messages.success(request, f"Scenario '{scenario.name}' completed successfully.")
    return redirect(reverse("riskapp:result_detail", args=[summary.result.id]))


@login_required
def result_detail(request, result_id):
    result = get_object_or_404(
        SimulationResult.objects.select_related("scenario", "scenario__portfolio"),
        id=result_id,
        scenario__user=request.user,
    )
    metrics = result.risk_metrics.order_by("metric_name")
    return render(request, "riskapp/result_detail.html", {
        "result": result,
        "metrics": metrics,
    })

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from riskapp.forms import PortfolioForm, PortfolioPositionForm
from riskapp.i18n import get_request_language, normalize_language, translate
from riskapp.models import Portfolio, PortfolioPosition, Scenario, SimulationResult
from riskapp.services.simulation import run_scenario_simulation


def switch_language(request, language):
    normalized_language = normalize_language(language)
    if normalized_language != language:
        return HttpResponseBadRequest("Unsupported language")

    request.session["ui_language"] = normalized_language
    return redirect(request.META.get("HTTP_REFERER") or reverse("riskapp:dashboard"))


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
def portfolio_create(request):
    form = PortfolioForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        portfolio = form.save(commit=False)
        portfolio.user = request.user
        portfolio.initial_value = 0
        portfolio.save()
        messages.success(
            request,
            translate("portfolio_created", get_request_language(request), name=portfolio.name),
        )
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    return render(request, "riskapp/portfolio_form.html", {"form": form})


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
    position_form = PortfolioPositionForm()

    return render(request, "riskapp/portfolio_detail.html", {
        "portfolio": portfolio,
        "positions": positions,
        "scenarios": scenarios,
        "position_form": position_form,
    })


@login_required
def portfolio_add_position(request, portfolio_id):
    portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)

    if request.method != "POST":
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    form = PortfolioPositionForm(request.POST)
    if not form.is_valid():
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
            "position_form": form,
        })

    instrument = form.cleaned_data["instrument"]
    quantity = form.cleaned_data["quantity"]
    purchase_price = form.cleaned_data["average_purchase_price"] or instrument.current_price

    position, created = PortfolioPosition.objects.get_or_create(
        portfolio=portfolio,
        instrument=instrument,
        defaults={
            "quantity": quantity,
            "average_purchase_price": purchase_price,
        },
    )

    if not created:
        old_quantity = position.quantity
        new_quantity = old_quantity + quantity
        position.average_purchase_price = (
            (old_quantity * position.average_purchase_price) + (quantity * purchase_price)
        ) / new_quantity
        position.quantity = new_quantity
        position.save(update_fields=["quantity", "average_purchase_price"])

    messages.success(
        request,
        translate("position_added", get_request_language(request), ticker=instrument.ticker),
    )
    return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))


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
        message = translate("empty_portfolio_error", get_request_language(request))
        messages.error(request, message or str(exc))
        return redirect(reverse("riskapp:portfolio_detail", args=[scenario.portfolio_id]))

    messages.success(
        request,
        translate("scenario_completed", get_request_language(request), name=scenario.name),
    )
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

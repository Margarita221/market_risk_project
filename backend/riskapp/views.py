from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from riskapp.forms import PortfolioForm, PortfolioPositionForm, PortfolioPositionQuantityForm, ScenarioForm
from riskapp.i18n import get_request_language, normalize_language, translate
from riskapp.models import Portfolio, PortfolioPosition, Scenario, SimulationResult
from riskapp.services.simulation import run_scenario_simulation


def user_scope(user, queryset, owner_lookup="user"):
    if user.is_staff or user.is_superuser:
        return queryset
    return queryset.filter(**{owner_lookup: user})


def switch_language(request, language):
    normalized_language = normalize_language(language)
    if normalized_language != language:
        return HttpResponseBadRequest("Unsupported language")

    request.session["ui_language"] = normalized_language
    return redirect(request.META.get("HTTP_REFERER") or reverse("riskapp:dashboard"))


@login_required
def dashboard(request):
    portfolios = user_scope(request.user, Portfolio.objects.all())
    scenarios = user_scope(request.user, Scenario.objects.all())
    results = user_scope(request.user, SimulationResult.objects.all(), owner_lookup="scenario__user")

    context = {
        "portfolios_count": portfolios.count(),
        "scenarios_count": scenarios.count(),
        "results_count": results.count(),
        "total_current_value": portfolios.aggregate(total=Sum("current_value"))["total"] or 0,
        "latest_results": results.select_related("scenario", "scenario__portfolio")[:5],
        "latest_portfolios": portfolios.order_by("-updated_at")[:5],
    }
    return render(request, "riskapp/dashboard.html", context)


def get_portfolio_detail_context(portfolio, scenario_form=None, position_form=None):
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
    scenarios = portfolio.scenarios.order_by("-created_at")
    return {
        "portfolio": portfolio,
        "positions": positions,
        "scenarios": scenarios,
        "position_form": position_form or PortfolioPositionForm(),
        "scenario_form": scenario_form or ScenarioForm(initial={
            "name": "Base scenario",
            "trend": "0.050",
            "volatility": "0.150",
            "noise_level": "0.020",
            "time_horizon": 365,
            "time_step": 1,
            "iterations_count": 500,
        }),
    }


@login_required
def portfolio_list(request):
    portfolios = (
        user_scope(request.user, Portfolio.objects.all())
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

    return render(request, "riskapp/portfolio_form.html", {
        "form": form,
        "mode": "create",
    })


@login_required
def portfolio_update(request, portfolio_id):
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)
    form = PortfolioForm(request.POST or None, instance=portfolio)

    if request.method == "POST" and form.is_valid():
        portfolio = form.save()
        messages.success(
            request,
            translate("portfolio_updated", get_request_language(request), name=portfolio.name),
        )
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    return render(request, "riskapp/portfolio_form.html", {
        "form": form,
        "portfolio": portfolio,
        "mode": "edit",
    })


@login_required
def portfolio_delete(request, portfolio_id):
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)

    if request.method != "POST":
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    portfolio_name = portfolio.name
    portfolio.delete()
    messages.success(
        request,
        translate("portfolio_deleted", get_request_language(request), name=portfolio_name),
    )
    return redirect("riskapp:portfolios")


@login_required
def portfolio_detail(request, portfolio_id):
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)
    return render(request, "riskapp/portfolio_detail.html", get_portfolio_detail_context(portfolio))


@login_required
def portfolio_add_position(request, portfolio_id):
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)

    if request.method != "POST":
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    form = PortfolioPositionForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "riskapp/portfolio_detail.html",
            get_portfolio_detail_context(portfolio, position_form=form),
        )

    instrument = form.cleaned_data["instrument"]
    quantity = form.cleaned_data["quantity"]
    purchase_price = instrument.current_price

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
def portfolio_position_update(request, portfolio_id, position_id):
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)
    position = get_object_or_404(PortfolioPosition, id=position_id, portfolio=portfolio)

    if request.method != "POST":
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    form = PortfolioPositionQuantityForm(request.POST, instance=position)
    if form.is_valid():
        position = form.save(commit=False)
        position.save(update_fields=["quantity"])
        messages.success(
            request,
            translate(
                "position_updated",
                get_request_language(request),
                ticker=position.instrument.ticker,
            ),
        )
    else:
        messages.error(request, translate("position_update_error", get_request_language(request)))

    return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))


@login_required
def portfolio_position_delete(request, portfolio_id, position_id):
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)
    position = get_object_or_404(PortfolioPosition, id=position_id, portfolio=portfolio)

    if request.method != "POST":
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    ticker = position.instrument.ticker
    position.delete()
    messages.success(
        request,
        translate("position_deleted", get_request_language(request), ticker=ticker),
    )
    return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))


@login_required
def scenario_list(request):
    scenarios = (
        user_scope(request.user, Scenario.objects.all())
        .select_related("portfolio")
        .annotate(results_count=Count("results"))
        .order_by("-created_at")
    )
    return render(request, "riskapp/scenario_list.html", {"scenarios": scenarios})


@login_required
def portfolio_scenario_run(request, portfolio_id):
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)

    if request.method != "POST":
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    form = ScenarioForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "riskapp/portfolio_detail.html",
            get_portfolio_detail_context(portfolio, scenario_form=form),
        )

    scenario = form.save(commit=False)
    scenario.user = portfolio.user if request.user.is_staff else request.user
    scenario.portfolio = portfolio
    scenario.save()

    try:
        summary = run_scenario_simulation(scenario.id)
    except ValueError as exc:
        message = translate("empty_portfolio_error", get_request_language(request))
        messages.error(request, message or str(exc))
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    messages.success(
        request,
        translate("scenario_completed", get_request_language(request), name=scenario.name),
    )
    return redirect(reverse("riskapp:result_detail", args=[summary.result.id]))


@login_required
def run_scenario(request, scenario_id):
    scenario = get_object_or_404(
        user_scope(request.user, Scenario.objects.select_related("portfolio")),
        id=scenario_id,
    )

    if request.method != "POST":
        return redirect("riskapp:scenarios")

    if "name" in request.POST:
        form = ScenarioForm(request.POST, instance=scenario)
        if not form.is_valid():
            metrics = scenario.results.first().risk_metrics.order_by("metric_name") if scenario.results.exists() else []
            return render(request, "riskapp/result_detail.html", {
                "result": scenario.results.first(),
                "metrics": metrics,
                "scenario_form": form,
            })
        form.save()

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
        user_scope(
            request.user,
            SimulationResult.objects.select_related("scenario", "scenario__portfolio"),
            owner_lookup="scenario__user",
        ),
        id=result_id,
    )
    metrics = result.risk_metrics.order_by("metric_name")
    return render(request, "riskapp/result_detail.html", {
        "result": result,
        "metrics": metrics,
        "scenario_form": ScenarioForm(instance=result.scenario),
    })

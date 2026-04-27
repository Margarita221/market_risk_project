from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import (
    LoginView,
    PasswordChangeDoneView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.urls import reverse, reverse_lazy

from riskapp.forms import (
    LocalizedAuthenticationForm,
    LocalizedPasswordChangeForm,
    LocalizedPasswordResetForm,
    LocalizedSetPasswordForm,
    InstrumentSearchForm,
    PortfolioForm,
    PortfolioPositionForm,
    PortfolioPositionQuantityForm,
    ProfileForm,
    SCENARIO_PRESETS,
    ScenarioManagementForm,
    ScenarioForm,
    SignUpForm,
)
from riskapp.i18n import get_request_language, normalize_language, translate
from riskapp.models import Instrument, Portfolio, PortfolioPosition, Scenario, SimulationResult
from riskapp.services.simulation import run_scenario_simulation

User = get_user_model()
METRIC_TRANSLATION_KEYS = {
    "VaR 95%": "metric_var_95",
    "CVaR 95%": "metric_cvar_95",
    "Sharpe Ratio": "metric_sharpe_ratio",
    "Probability of Loss": "metric_probability_of_loss",
    "Probability of Drawdown > 10%": "metric_probability_of_drawdown",
    "Median Final Value": "metric_median_final_value",
    "Final Value P5": "metric_final_value_p5",
    "Final Value P95": "metric_final_value_p95",
    "Iterations": "metric_iterations",
    "Steps": "metric_steps",
}


class LanguageAwareFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["language"] = get_request_language(self.request)
        return kwargs


class LocalizedLoginView(LoginView):
    authentication_form = LocalizedAuthenticationForm
    template_name = "registration/login.html"


class LocalizedPasswordChangeView(LanguageAwareFormMixin, PasswordChangeView):
    form_class = LocalizedPasswordChangeForm
    template_name = "riskapp/auth/password_change_form.html"
    success_url = reverse_lazy("account_password_change_done")


class LocalizedPasswordChangeDoneView(PasswordChangeDoneView):
    template_name = "riskapp/auth/password_change_done.html"


class LocalizedPasswordResetView(LanguageAwareFormMixin, PasswordResetView):
    form_class = LocalizedPasswordResetForm
    template_name = "riskapp/auth/password_reset_form.html"
    email_template_name = "riskapp/auth/password_reset_email.html"
    subject_template_name = "riskapp/auth/password_reset_subject.txt"
    success_url = reverse_lazy("account_password_reset_done")

    def form_valid(self, form):
        self.extra_email_context = {"ui_language": get_request_language(self.request)}
        return super().form_valid(form)


class LocalizedPasswordResetDoneView(PasswordResetDoneView):
    template_name = "riskapp/auth/password_reset_done.html"


class LocalizedPasswordResetConfirmView(LanguageAwareFormMixin, PasswordResetConfirmView):
    form_class = LocalizedSetPasswordForm
    template_name = "riskapp/auth/password_reset_confirm.html"
    success_url = reverse_lazy("account_password_reset_complete")


class LocalizedPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "riskapp/auth/password_reset_complete.html"


def user_scope(user, queryset, owner_lookup="user"):
    if user.is_staff or user.is_superuser:
        return queryset
    return queryset.filter(**{owner_lookup: user})


def localize_metric(metric, language):
    return {
        "name": translate(METRIC_TRANSLATION_KEYS.get(metric.metric_name, ""), language)
        if METRIC_TRANSLATION_KEYS.get(metric.metric_name)
        else metric.metric_name,
        "value": metric.metric_value,
        "confidence_level": metric.confidence_level,
        "calculated_at": metric.calculated_at,
    }


def build_result_notes(result, language):
    chart_data = result.chart_data or {}
    scenario = result.scenario
    return [
        translate(
            "run_note_iterations_steps",
            language,
            iterations=chart_data.get("iterations", scenario.iterations_count),
            steps=chart_data.get("steps", "-"),
        ),
        translate(
            "run_note_market_structure",
            language,
            preset=scenario.get_preset_display(),
            systematic_risk=chart_data.get("systematic_risk_percent", 0),
            market_shock=chart_data.get("market_shock_percent", 0),
            currency_shock=chart_data.get("currency_shock_percent", 0),
        ),
        translate(
            "run_note_chart_consistency",
            language,
        ),
    ]


def switch_language(request, language):
    normalized_language = normalize_language(language)
    if normalized_language != language:
        return HttpResponseBadRequest("Unsupported language")

    request.session["ui_language"] = normalized_language
    return redirect(request.META.get("HTTP_REFERER") or reverse("riskapp:dashboard"))


def send_activation_email(request, user):
    language = get_request_language(request)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    activation_url = request.build_absolute_uri(
        reverse("riskapp:activate_account", args=[uid, token])
    )
    request.session["last_activation_url"] = activation_url
    subject = translate("activation_email_subject", language)
    message = translate(
        "activation_email_body",
        language,
        first_name=user.first_name or user.username,
        activation_url=activation_url,
    )
    send_mail(subject, message, None, [user.email], fail_silently=False)


def signup(request):
    if request.user.is_authenticated:
        return redirect("riskapp:dashboard")

    language = get_request_language(request)
    form = SignUpForm(request.POST or None, language=language)

    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.email = form.cleaned_data["email"]
        user.is_active = False
        user.save()
        send_activation_email(request, user)
        messages.success(
            request,
            translate("signup_success", language, email=user.email),
        )
        return redirect(f"{reverse('riskapp:activation_sent')}?email={user.email}")

    return render(request, "registration/signup.html", {"form": form})


def activation_sent(request):
    return render(
        request,
        "registration/activation_sent.html",
        {
            "email": request.GET.get("email", ""),
            "activation_url": request.session.get("last_activation_url", ""),
        },
    )


def activate_account(request, uidb64, token):
    language = get_request_language(request)

    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        return render(request, "registration/activation_invalid.html", status=400)

    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])

    messages.success(
        request,
        translate("activation_success", language, username=user.username),
    )
    return redirect("login")


@login_required
def profile(request):
    language = get_request_language(request)
    form = ProfileForm(request.POST or None, instance=request.user, language=language)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request,
            translate("profile_updated", language),
        )
        return redirect("riskapp:profile")

    context = {
        "form": form,
        "portfolios_count": user_scope(request.user, Portfolio.objects.all()).count(),
        "scenarios_count": user_scope(request.user, Scenario.objects.all()).count(),
        "results_count": user_scope(
            request.user,
            SimulationResult.objects.all(),
            owner_lookup="scenario__user",
        ).count(),
    }
    return render(request, "registration/profile.html", context)


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
            "preset": Scenario.PRESET_BASE,
            "name": "Base scenario",
            **SCENARIO_PRESETS[Scenario.PRESET_BASE],
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
def instrument_list(request):
    form = InstrumentSearchForm(request.GET or None)
    instruments = Instrument.objects.all().order_by("ticker")

    query = ""
    instrument_type = ""
    currency = ""
    price_min = None
    price_max = None
    portfolio = None
    if form.is_valid():
        query = form.cleaned_data.get("query") or ""
        instrument_type = form.cleaned_data.get("instrument_type") or ""
        currency = form.cleaned_data.get("currency") or ""
        price_min = form.cleaned_data.get("price_min")
        price_max = form.cleaned_data.get("price_max")
        portfolio_id = form.cleaned_data.get("portfolio")
        if portfolio_id:
            portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)

    if query:
        instruments = instruments.filter(Q(ticker__icontains=query) | Q(name__icontains=query))
    if instrument_type:
        instruments = instruments.filter(instrument_type=instrument_type)
    if currency:
        instruments = instruments.filter(currency__iexact=currency)
    if price_min is not None:
        instruments = instruments.filter(current_price__gte=price_min)
    if price_max is not None:
        instruments = instruments.filter(current_price__lte=price_max)

    paginator = Paginator(instruments, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    currencies = Instrument.objects.order_by("currency").values_list("currency", flat=True).distinct()
    instrument_types = Instrument.objects.order_by("instrument_type").values_list("instrument_type", flat=True).distinct()

    context = {
        "form": form,
        "page_obj": page_obj,
        "portfolio": portfolio,
        "currencies": currencies,
        "instrument_types": instrument_types,
        "query": query,
        "instrument_type": instrument_type,
        "currency": currency,
        "price_min": price_min,
        "price_max": price_max,
    }
    return render(request, "riskapp/instrument_list.html", context)


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
def result_list(request):
    portfolios = user_scope(request.user, Portfolio.objects.all()).order_by("name")
    results = user_scope(
        request.user,
        SimulationResult.objects.select_related("scenario", "scenario__portfolio"),
        owner_lookup="scenario__user",
    )

    selected_portfolio = request.GET.get("portfolio", "").strip()
    if selected_portfolio:
        results = results.filter(scenario__portfolio_id=selected_portfolio)

    context = {
        "results": results.order_by("-execution_time"),
        "portfolios": portfolios,
        "selected_portfolio": selected_portfolio,
    }
    return render(request, "riskapp/result_list.html", context)


@login_required
def scenario_create(request):
    portfolios = user_scope(request.user, Portfolio.objects.all())
    form = ScenarioManagementForm(
        request.POST or None,
        portfolios_queryset=portfolios,
        initial={
            "preset": Scenario.PRESET_BASE,
            **SCENARIO_PRESETS[Scenario.PRESET_BASE],
        },
    )

    if request.method == "POST" and form.is_valid():
        scenario = form.save(commit=False)
        scenario.user = scenario.portfolio.user
        scenario.save()
        messages.success(
            request,
            translate("scenario_created", get_request_language(request), name=scenario.name),
        )
        return redirect("riskapp:scenarios")

    return render(request, "riskapp/scenario_form.html", {
        "form": form,
        "mode": "create",
    })


@login_required
def scenario_update(request, scenario_id):
    scenario = get_object_or_404(
        user_scope(request.user, Scenario.objects.select_related("portfolio")),
        id=scenario_id,
    )
    portfolios = user_scope(request.user, Portfolio.objects.all())
    form = ScenarioManagementForm(
        request.POST or None,
        instance=scenario,
        portfolios_queryset=portfolios,
    )

    if request.method == "POST" and form.is_valid():
        scenario = form.save(commit=False)
        scenario.user = scenario.portfolio.user
        scenario.save()
        messages.success(
            request,
            translate("scenario_updated", get_request_language(request), name=scenario.name),
        )
        return redirect("riskapp:scenarios")

    return render(request, "riskapp/scenario_form.html", {
        "form": form,
        "scenario": scenario,
        "mode": "edit",
    })


@login_required
def scenario_delete(request, scenario_id):
    scenario = get_object_or_404(
        user_scope(request.user, Scenario.objects.select_related("portfolio")),
        id=scenario_id,
    )

    if request.method != "POST":
        return redirect("riskapp:scenarios")

    scenario_name = scenario.name
    scenario.delete()
    messages.success(
        request,
        translate("scenario_deleted", get_request_language(request), name=scenario_name),
    )
    return redirect("riskapp:scenarios")


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
            language = get_request_language(request)
            metrics = scenario.results.first().risk_metrics.order_by("metric_name") if scenario.results.exists() else []
            return render(request, "riskapp/result_detail.html", {
                "result": scenario.results.first(),
                "metrics": [localize_metric(metric, language) for metric in metrics],
                "run_notes": build_result_notes(scenario.results.first(), language) if scenario.results.exists() else [],
                "status_label": translate("status_completed", language),
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
    language = get_request_language(request)
    result = get_object_or_404(
        user_scope(
            request.user,
            SimulationResult.objects.select_related("scenario", "scenario__portfolio"),
            owner_lookup="scenario__user",
        ),
        id=result_id,
    )
    metrics = [localize_metric(metric, language) for metric in result.risk_metrics.order_by("metric_name")]
    return render(request, "riskapp/result_detail.html", {
        "result": result,
        "metrics": metrics,
        "run_notes": build_result_notes(result, language),
        "status_label": translate("status_completed", language),
        "scenario_form": ScenarioForm(instance=result.scenario),
    })

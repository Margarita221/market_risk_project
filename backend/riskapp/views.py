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
from decimal import Decimal, InvalidOperation

from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.urls import reverse, reverse_lazy
from django.utils import timezone

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
    StrategyComparisonForm,
    TradeOperationForm,
)
from riskapp.i18n import get_request_language, normalize_language, translate
from riskapp.models import Instrument, Portfolio, PortfolioPosition, Scenario, SimulationResult, TradeOperation
from riskapp.services.exchange_rates import convert_amount, normalize_currency_code
from riskapp.services.historical_calibration import calibrate_portfolio_scenario_parameters
from riskapp.services.portfolio_operations import estimate_trade_commission, record_trade_operation
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
PERCENT_METRIC_NAMES = {
    "VaR 95%",
    "CVaR 95%",
    "Probability of Loss",
    "Probability of Drawdown > 10%",
}
CURRENCY_METRIC_NAMES = {
    "Median Final Value",
    "Final Value P5",
    "Final Value P95",
}
COUNT_METRIC_NAMES = {
    "Iterations",
    "Steps",
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


def admin_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            return redirect("riskapp:dashboard")
        return view_func(request, *args, **kwargs)

    return wrapped


def user_scope(user, queryset, owner_lookup="user"):
    if user.is_staff or user.is_superuser:
        return queryset
    return queryset.filter(**{owner_lookup: user})


def to_decimal(value, default="0"):
    if value in (None, ""):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def quantize_for_display(value, decimals=2):
    decimals = max(int(decimals), 0)
    quantizer = Decimal("1") if decimals == 0 else Decimal(f"1.{'0' * decimals}")
    return to_decimal(value).quantize(quantizer)


def format_display_number(value, decimals=2):
    return f"{quantize_for_display(value, decimals):,.{decimals}f}".replace(",", " ")


def format_display_percent(value, decimals=2):
    return f"{quantize_for_display(to_decimal(value) * Decimal('100'), decimals):,.{decimals}f}".replace(",", " ")


def get_portfolio_unit_label(portfolio, language):
    return normalize_currency_code(getattr(portfolio, "base_currency", Portfolio.CURRENCY_RUB)) or translate("unit_rub", language)


def localize_metric(metric, language, portfolio_unit_label=None):
    metric_name = metric.metric_name
    if metric_name in PERCENT_METRIC_NAMES:
        display_value = format_display_percent(metric.metric_value, 2)
        unit = translate("unit_percent", language)
    elif metric_name in CURRENCY_METRIC_NAMES:
        display_value = format_display_number(metric.metric_value, 2)
        unit = portfolio_unit_label or translate("unit_rub", language)
    elif metric_name in COUNT_METRIC_NAMES:
        display_value = format_display_number(metric.metric_value, 0)
        unit = translate("unit_count", language)
    else:
        display_value = format_display_number(metric.metric_value, 4)
        unit = translate("unit_ratio", language)

    return {
        "name": translate(METRIC_TRANSLATION_KEYS.get(metric_name, ""), language)
        if METRIC_TRANSLATION_KEYS.get(metric_name)
        else metric_name,
        "value": metric.metric_value,
        "display_value": display_value,
        "unit": unit,
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
        translate("scenario_preset", language) + f": {scenario.get_preset_display()}.",
        translate(
            "run_note_chart_consistency",
            language,
        ),
    ]


def localized_text(language, ru, en):
    return ru if language == "ru" else en


def get_historical_calibration_lookback(raw_horizon):
    try:
        parsed = int(Decimal(str(raw_horizon)))
    except (InvalidOperation, TypeError, ValueError):
        parsed = 180
    return max(60, min(parsed, 365))


def build_historical_calibration_form(request, form_class, portfolios_queryset, instance=None):
    language = get_request_language(request)
    portfolio_id = request.POST.get("portfolio") or getattr(instance, "portfolio_id", None)
    if not portfolio_id:
        raise ValueError(
            localized_text(
                language,
                "Сначала выберите портфель, чтобы опереться на его историю цен.",
                "Select a portfolio first so calibration can use its price history.",
            )
        )

    portfolio = get_object_or_404(portfolios_queryset, id=portfolio_id)
    lookback_days = get_historical_calibration_lookback(
        request.POST.get("time_horizon") or getattr(instance, "time_horizon", 180)
    )
    try:
        calibration_summary = calibrate_portfolio_scenario_parameters(portfolio, lookback_days=lookback_days)
    except ValueError as exc:
        raw_message = str(exc)
        if "Not enough historical price observations" in raw_message or "Not enough aligned historical observations" in raw_message:
            raise ValueError(
                localized_text(
                    language,
                    "Для исторической калибровки пока не хватает накопленных снимков цен. Сначала подгрузи историю, а потом повтори попытку.",
                    "There are not enough stored price snapshots for historical calibration yet. Load more history and try again.",
                )
            ) from exc
        if "Portfolio has no positions" in raw_message:
            raise ValueError(
                localized_text(
                    language,
                    "Портфель пока не готов к калибровке: в нем нет позиций с корректной ценой и валютным пересчетом.",
                    "The portfolio is not ready for calibration yet: it has no positions with valid prices and currency conversion.",
                )
            ) from exc
        raise
    initial_data = {key: value for key, value in request.POST.items()}
    initial_data.update(calibration_summary.as_form_values())
    initial_data["portfolio"] = portfolio.id
    form = form_class(
        instance=instance,
        initial=initial_data,
        portfolios_queryset=portfolios_queryset,
        language=language,
    )
    return form, calibration_summary


def format_metric_display(metric_name, metric_value, portfolio_unit_label):
    if metric_name in PERCENT_METRIC_NAMES:
        return f"{format_display_percent(metric_value, 2)} %"
    if metric_name in CURRENCY_METRIC_NAMES:
        return f"{format_display_number(metric_value, 2)} {portfolio_unit_label}"
    if metric_name in COUNT_METRIC_NAMES:
        return f"{format_display_number(metric_value, 0)}"
    return f"{format_display_number(metric_value, 4)}"


def get_metric_map(result):
    metrics = {}
    for metric in result.risk_metrics.all():
        metrics[metric.metric_name] = metric.metric_value
    return metrics


def build_strategy_comparison_payload(results, language):
    comparison_results = []
    chart_series = []

    for result in results:
        metric_map = get_metric_map(result)
        portfolio_unit_label = get_portfolio_unit_label(result.scenario.portfolio, language)
        average_path = result.chart_data.get("average_path", [])
        start_value = to_decimal(average_path[0] if average_path else 0)
        normalized_path = []
        for point in average_path:
            point_decimal = to_decimal(point)
            if start_value > 0:
                normalized_path.append(float(((point_decimal / start_value) - Decimal("1")) * Decimal("100")))
            else:
                normalized_path.append(0.0)

        comparison_results.append({
            "id": result.id,
            "scenario_name": result.scenario.name,
            "portfolio_name": result.scenario.portfolio.name,
            "execution_time": result.execution_time,
            "selection_label": localized_text(
                language,
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
            ),
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
        })
        chart_series.append({
            "label": localized_text(
                language,
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%d.%m %H:%M')}",
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
            ),
            "values": normalized_path,
        })

    metric_specs = [
        (localized_text(language, "Средний итог", "Average final value"), "final_value", lambda item: f"{format_display_number(item['final_value'], 2)} {item['portfolio_unit_label']}"),
        (localized_text(language, "Ожидаемая доходность", "Expected return"), "expected_return", lambda item: f"{format_display_percent(item['expected_return'], 2)} %"),
        (localized_text(language, "Волатильность", "Volatility"), "volatility", lambda item: f"{format_display_percent(item['volatility'], 2)} %"),
        (localized_text(language, "Максимальная просадка", "Max drawdown"), "max_drawdown", lambda item: f"{format_display_percent(item['max_drawdown'], 2)} %"),
        (localized_text(language, "Вероятность убытка", "Probability of loss"), "probability_of_loss", lambda item: f"{format_display_percent(item['probability_of_loss'], 2)} %"),
        (localized_text(language, "Вероятность просадки > 10%", "Probability of drawdown > 10%"), "probability_of_drawdown", lambda item: f"{format_display_percent(item['probability_of_drawdown'], 2)} %"),
        ("VaR 95%", "var_95", lambda item: f"{format_display_percent(item['var_95'], 2)} %"),
        ("CVaR 95%", "cvar_95", lambda item: f"{format_display_percent(item['cvar_95'], 2)} %"),
        (localized_text(language, "Коэффициент Шарпа", "Sharpe ratio"), "sharpe_ratio", lambda item: format_display_number(item["sharpe_ratio"], 4)),
    ]
    comparison_rows = [
        {
            "label": row_label,
            "values": [formatter(item) for item in comparison_results],
        }
        for row_label, _, formatter in metric_specs
    ]
    return comparison_results, comparison_rows, chart_series


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
        user.is_active = True
        user.save()
        messages.success(
            request,
            localized_text(
                language,
                "Регистрация завершена. Теперь можно войти под своим логином и паролем.",
                "Registration completed. You can now sign in with your username and password.",
            ),
        )
        return redirect("login")

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


def get_portfolio_detail_context(portfolio, language="ru", scenario_form=None, position_form=None):
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
    recent_operations = (
        portfolio.trade_operations.select_related("instrument")
        .order_by("-executed_at", "-created_at")[:5]
    )
    base_currency = get_portfolio_unit_label(portfolio, language)
    has_missing_rates = False
    for position in positions:
        position.instrument.currency = normalize_currency_code(position.instrument.currency)
        position.position_value_converted = position.position_value if position.instrument.currency == base_currency else None
        position.purchase_value_converted = position.purchase_value if position.instrument.currency == base_currency else None
        if position.instrument.currency != base_currency:
            converted_current = convert_amount(position.position_value, position.instrument.currency, base_currency)
            converted_purchase = convert_amount(position.purchase_value, position.instrument.currency, base_currency)
            if converted_current is None or converted_purchase is None:
                has_missing_rates = True
            else:
                position.position_value_converted = converted_current
                position.purchase_value_converted = converted_purchase
    return {
        "portfolio": portfolio,
        "positions": positions,
        "scenarios": scenarios,
        "portfolio_unit_label": base_currency,
        "portfolio_has_missing_rates": has_missing_rates,
        "position_form": position_form or PortfolioPositionForm(),
        "scenario_form": scenario_form or ScenarioForm(initial={
            "preset": Scenario.PRESET_BASE,
            "name": "Base scenario",
            **SCENARIO_PRESETS[Scenario.PRESET_BASE],
        }, language=language),
        "recent_operations": recent_operations,
        "operations_count": portfolio.trade_operations.count(),
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
    return render(
        request,
        "riskapp/portfolio_detail.html",
        get_portfolio_detail_context(portfolio, language=get_request_language(request)),
    )


@login_required
def portfolio_operations(request, portfolio_id):
    language = get_request_language(request)
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)
    operations = list(
        portfolio.trade_operations.select_related("instrument", "user")
        .order_by("-executed_at", "-created_at")
    )
    portfolio_unit_label = get_portfolio_unit_label(portfolio, language)

    def convert_trade_value(value, currency_code):
        normalized_currency = normalize_currency_code(currency_code)
        decimal_value = to_decimal(value)
        if normalized_currency == portfolio_unit_label:
            return decimal_value, portfolio_unit_label
        converted_value = convert_amount(decimal_value, normalized_currency, portfolio_unit_label)
        if converted_value is None:
            return decimal_value, normalized_currency
        return converted_value, portfolio_unit_label

    operation_rows = []
    total_commission = Decimal("0")
    realized_total = Decimal("0")
    buy_count = 0
    sell_count = 0

    for operation in operations:
        instrument_currency = normalize_currency_code(operation.instrument.currency)
        gross_value, gross_unit = convert_trade_value(operation.gross_amount, instrument_currency)
        commission_value, commission_unit = convert_trade_value(operation.commission, instrument_currency)
        net_value, net_unit = convert_trade_value(operation.net_amount, instrument_currency)
        realized_value = None
        realized_unit = portfolio_unit_label
        if operation.realized_pnl is not None:
            realized_value, realized_unit = convert_trade_value(operation.realized_pnl, instrument_currency)
            realized_total += realized_value

        total_commission += commission_value
        if operation.operation_type == TradeOperation.TYPE_BUY:
            buy_count += 1
        else:
            sell_count += 1

        operation_rows.append({
            "operation": operation,
            "price_currency": instrument_currency,
            "gross_amount": gross_value,
            "gross_unit": gross_unit,
            "commission_amount": commission_value,
            "commission_unit": commission_unit,
            "net_amount": net_value,
            "net_unit": net_unit,
            "realized_pnl": realized_value,
            "realized_unit": realized_unit,
        })

    return render(request, "riskapp/operation_list.html", {
        "portfolio": portfolio,
        "operations": operations,
        "operation_rows": operation_rows,
        "portfolio_unit_label": portfolio_unit_label,
        "operations_summary": {
            "count": len(operations),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_commission": total_commission,
            "realized_total": realized_total,
        },
    })


@login_required
def portfolio_operation_create(request, portfolio_id):
    language = get_request_language(request)
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)
    requested_type = request.GET.get("type") or request.POST.get("operation_type") or TradeOperation.TYPE_SELL
    instrument_id = request.GET.get("instrument") or request.POST.get("instrument")
    selected_instrument = None

    if requested_type == TradeOperation.TYPE_BUY and request.method == "GET" and not instrument_id:
        return redirect(f"{reverse('riskapp:instruments')}?portfolio={portfolio.id}")

    if instrument_id:
        selected_instrument = get_object_or_404(Instrument, id=instrument_id)

    if request.method == "POST":
        form = TradeOperationForm(
            request.POST,
            portfolio=portfolio,
            user=request.user,
            language=language,
            initial={
                "operation_type": requested_type,
                "instrument": selected_instrument,
                "executed_at": timezone.localtime().replace(second=0, microsecond=0),
            },
        )
        if form.is_valid():
            instrument = form.cleaned_data["instrument"]
            price_per_unit = instrument.current_price
            try:
                operation, _ = record_trade_operation(
                    user=request.user,
                    portfolio=portfolio,
                    instrument=instrument,
                    operation_type=form.cleaned_data["operation_type"],
                    quantity=form.cleaned_data["quantity"],
                    price_per_unit=price_per_unit,
                    executed_at=form.cleaned_data["executed_at"],
                    comment=form.cleaned_data.get("comment", ""),
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                operation_label = "Покупка" if operation.operation_type == TradeOperation.TYPE_BUY else "Продажа"
                success_message = (
                    f"{operation_label} {operation.instrument.ticker} сохранена."
                    if language == "ru"
                    else f"The {operation.operation_type.lower()} trade for {operation.instrument.ticker} was saved."
                )
                messages.success(request, success_message)
                return redirect(request.POST.get("next") or reverse("riskapp:portfolio_operations", args=[portfolio.id]))
    else:
        form = TradeOperationForm(
            portfolio=portfolio,
            user=request.user,
            language=language,
            initial={
                "operation_type": requested_type,
                "instrument": selected_instrument,
                "executed_at": timezone.localtime().replace(second=0, microsecond=0),
            },
        )

    positions_for_sale = (
        PortfolioPosition.objects.filter(portfolio=portfolio)
        .select_related("instrument")
        .order_by("instrument__ticker")
    )
    commission_preview = None
    current_price = None
    if selected_instrument:
        current_price = selected_instrument.current_price
        quantity_preview = form.data.get("quantity") if form.is_bound else form.initial.get("quantity") or 1
        try:
            commission_preview = estimate_trade_commission(int(quantity_preview or 1), current_price)
        except (TypeError, ValueError):
            commission_preview = estimate_trade_commission(1, current_price)

    return render(request, "riskapp/operation_form.html", {
        "portfolio": portfolio,
        "form": form,
        "selected_instrument": selected_instrument,
        "requested_type": requested_type,
        "positions_for_sale": positions_for_sale,
        "commission_preview": commission_preview,
        "current_price": current_price,
    })


@login_required
def instrument_list(request):
    language = get_request_language(request)
    form = InstrumentSearchForm(request.GET or None, language=language)
    instruments = Instrument.objects.all().order_by("ticker")

    query = ""
    instrument_type = ""
    sector = ""
    currency = ""
    price_min = None
    price_max = None
    portfolio = None
    if form.is_valid():
        query = form.cleaned_data.get("query") or ""
        instrument_type = form.cleaned_data.get("instrument_type") or ""
        sector = form.cleaned_data.get("sector") or ""
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
    if sector:
        instruments = instruments.filter(sector=sector)
    if currency:
        instruments = instruments.filter(currency__iexact=currency)
    if price_min is not None:
        instruments = instruments.filter(current_price__gte=price_min)
    if price_max is not None:
        instruments = instruments.filter(current_price__lte=price_max)

    filtered_counts = {
        Instrument.TYPE_STOCK: instruments.filter(instrument_type=Instrument.TYPE_STOCK).count(),
        Instrument.TYPE_BOND: instruments.filter(instrument_type=Instrument.TYPE_BOND).count(),
        Instrument.TYPE_ETF: instruments.filter(instrument_type=Instrument.TYPE_ETF).count(),
    }

    paginator = Paginator(instruments, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    currencies = Instrument.objects.order_by("currency").values_list("currency", flat=True).distinct()
    sectors = Instrument.objects.exclude(sector="").order_by("sector").values_list("sector", flat=True).distinct()
    raw_types = Instrument.objects.order_by("instrument_type").values_list("instrument_type", flat=True).distinct()
    instrument_types = []
    for value in raw_types:
        normalized = Instrument.normalize_instrument_type(value)
        if normalized and normalized not in instrument_types:
            instrument_types.append(normalized)

    context = {
        "form": form,
        "page_obj": page_obj,
        "portfolio": portfolio,
        "currencies": currencies,
        "sectors": sectors,
        "instrument_types": instrument_types,
        "query": query,
        "instrument_type": instrument_type,
        "sector": sector,
        "currency": currency,
        "price_min": price_min,
        "price_max": price_max,
        "instrument_type_labels": {
            Instrument.TYPE_STOCK: translate("instrument_type_stock", language),
            Instrument.TYPE_BOND: translate("instrument_type_bond", language),
            Instrument.TYPE_ETF: translate("instrument_type_etf", language),
        },
        "sector_labels": {
            Instrument.SECTOR_EQUITIES: translate("sector_equities", language),
            Instrument.SECTOR_BONDS: translate("sector_bonds", language),
            Instrument.SECTOR_FUNDS: translate("sector_funds", language),
        },
        "filtered_counts": filtered_counts,
    }
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("partial") == "1":
        html = render_to_string("riskapp/partials/instrument_catalog_results.html", context, request=request)
        return JsonResponse({"html": html})
    return render(request, "riskapp/instrument_list.html", context)


@login_required
def portfolio_add_position(request, portfolio_id):
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)

    if request.method != "POST":
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    form = PortfolioPositionForm(request.POST)
    if not form.is_valid():
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "ok": False,
                "message": translate("position_add_error", get_request_language(request)),
                "errors": form.errors,
            }, status=400)
        return render(
            request,
            "riskapp/portfolio_detail.html",
            get_portfolio_detail_context(portfolio, language=get_request_language(request), position_form=form),
        )

    instrument = form.cleaned_data["instrument"]
    quantity = form.cleaned_data["quantity"]

    operation, position = record_trade_operation(
        user=request.user,
        portfolio=portfolio,
        instrument=instrument,
        operation_type=TradeOperation.TYPE_BUY,
        quantity=quantity,
        price_per_unit=instrument.current_price,
        commission=Decimal("0"),
        executed_at=timezone.now(),
        comment=localized_text(
            get_request_language(request),
            "Покупка из каталога инструментов",
            "Buy created from the instrument catalog",
        ),
    )

    messages.success(
        request,
        localized_text(
            get_request_language(request),
            f"Покупка {operation.instrument.ticker} сохранена в истории сделок.",
            f"The buy trade for {operation.instrument.ticker} was added to the trade history.",
        ),
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "message": localized_text(
                get_request_language(request),
                f"Покупка {operation.instrument.ticker} добавлена.",
                f"Buy trade for {operation.instrument.ticker} added.",
            ),
            "ticker": instrument.ticker,
            "quantity": position.quantity if position else 0,
        })

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url:
        return redirect(next_url)
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
    language = get_request_language(request)
    scenarios = (
        user_scope(request.user, Scenario.objects.all())
        .select_related("portfolio")
        .annotate(results_count=Count("results"))
    )
    query = request.GET.get("query", "").strip()
    selected_portfolio = request.GET.get("portfolio", "").strip()
    selected_preset = request.GET.get("preset", "").strip()

    if query:
        scenarios = scenarios.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(portfolio__name__icontains=query)
        )
    if selected_portfolio:
        scenarios = scenarios.filter(portfolio_id=selected_portfolio)
    if selected_preset:
        scenarios = scenarios.filter(preset=selected_preset)

    scenarios = scenarios.order_by("-updated_at", "-created_at")
    summary = scenarios.aggregate(
        avg_horizon=Avg("time_horizon"),
        avg_iterations=Avg("iterations_count"),
        total_results=Sum("results_count"),
    )
    context = {
        "scenarios": scenarios,
        "portfolios": user_scope(request.user, Portfolio.objects.all()).order_by("name"),
        "presets": Scenario.PRESET_CHOICES,
        "selected_portfolio": selected_portfolio,
        "selected_preset": selected_preset,
        "query": query,
        "scenario_summary": {
            "count": scenarios.count(),
            "avg_horizon": int(summary["avg_horizon"] or 0),
            "avg_iterations": int(summary["avg_iterations"] or 0),
            "total_results": int(summary["total_results"] or 0),
            "stress_share": (
                round(
                    (
                        scenarios.filter(
                            preset__in=[Scenario.PRESET_STRESS, Scenario.PRESET_CRISIS]
                        ).count()
                        / scenarios.count()
                    ) * 100,
                    1,
                )
                if scenarios.exists()
                else 0
            ),
        },
        "scenario_pressure": {
            "market": format_display_percent(
                scenarios.aggregate(avg=Avg("market_shock"))["avg"] or 0,
                2,
            ),
            "market_width": min(abs(float(to_decimal(scenarios.aggregate(avg=Avg("market_shock"))["avg"] or 0) * Decimal("100"))), 100),
            "currency": format_display_percent(
                scenarios.aggregate(avg=Avg("currency_shock"))["avg"] or 0,
                2,
            ),
            "currency_width": min(abs(float(to_decimal(scenarios.aggregate(avg=Avg("currency_shock"))["avg"] or 0) * Decimal("100"))), 100),
            "rate": format_display_percent(
                scenarios.aggregate(avg=Avg("interest_rate_shock"))["avg"] or 0,
                2,
            ),
            "rate_width": min(abs(float(to_decimal(scenarios.aggregate(avg=Avg("interest_rate_shock"))["avg"] or 0) * Decimal("100"))), 100),
        },
        "language": language,
    }
    return render(request, "riskapp/scenario_list.html", context)


@login_required
def result_list(request):
    language = get_request_language(request)
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
        "results_summary": {
            "count": results.count(),
            "avg_final_value": format_display_number(results.aggregate(avg=Avg("final_value"))["avg"] or 0, 2),
            "avg_return": format_display_percent(results.aggregate(avg=Avg("expected_return"))["avg"] or 0, 2),
            "avg_drawdown": format_display_percent(results.aggregate(avg=Avg("max_drawdown"))["avg"] or 0, 2),
        },
        "language": language,
    }
    return render(request, "riskapp/result_list.html", context)


@login_required
def strategy_compare(request):
    language = get_request_language(request)
    portfolios_queryset = user_scope(request.user, Portfolio.objects.all())
    results_queryset = user_scope(
        request.user,
        SimulationResult.objects.select_related("scenario", "scenario__portfolio").prefetch_related("risk_metrics"),
        owner_lookup="scenario__user",
    )
    initial = None
    if request.method == "GET" and not request.GET:
        first_portfolio_id = (
            results_queryset.order_by("-execution_time")
            .values_list("scenario__portfolio_id", flat=True)
            .first()
        )
        if first_portfolio_id:
            initial = {"portfolio": first_portfolio_id}
    form = StrategyComparisonForm(
        request.GET or None,
        portfolios_queryset=portfolios_queryset,
        language=language,
        initial=initial,
    )

    comparison_results = []
    comparison_rows = []
    chart_series = []
    selected_portfolio = None

    if form.is_bound and form.is_valid():
        selected_portfolio = form.cleaned_data["portfolio"]
        portfolio_results = results_queryset.filter(scenario__portfolio=selected_portfolio).order_by("execution_time")
        comparison_results, comparison_rows, chart_series = build_strategy_comparison_payload(portfolio_results, language)
    elif not form.is_bound and form.initial.get("portfolio"):
        selected_portfolio = portfolios_queryset.filter(id=form.initial["portfolio"]).first()
        if selected_portfolio:
            # Trigger the default comparison without forcing the user to submit an empty form first.
            request.GET = request.GET.copy()
            request.GET["portfolio"] = str(selected_portfolio.id)
            form = StrategyComparisonForm(
                request.GET,
                portfolios_queryset=portfolios_queryset,
                language=language,
            )
            if form.is_valid():
                selected_portfolio = form.cleaned_data["portfolio"]
                portfolio_results = results_queryset.filter(scenario__portfolio=selected_portfolio).order_by("execution_time")
                comparison_results, comparison_rows, chart_series = build_strategy_comparison_payload(portfolio_results, language)

    return render(request, "riskapp/strategy_compare.html", {
        "form": form,
        "comparison_results": comparison_results,
        "comparison_rows": comparison_rows,
        "chart_series": chart_series,
        "selected_portfolio": selected_portfolio,
    })


def build_strategy_comparison_payload(results, language):
    comparison_results = []
    chart_series = []

    for result in results:
        metric_map = get_metric_map(result)
        portfolio_unit_label = get_portfolio_unit_label(result.scenario.portfolio, language)
        average_path = result.chart_data.get("average_path", [])
        start_value = to_decimal(average_path[0] if average_path else 0)
        normalized_path = []
        for point in average_path:
            point_decimal = to_decimal(point)
            if start_value > 0:
                normalized_path.append(float(((point_decimal / start_value) - Decimal("1")) * Decimal("100")))
            else:
                normalized_path.append(0.0)

        timestamp_label = timezone.localtime(result.execution_time).strftime("%Y-%m-%d %H:%M")
        comparison_results.append({
            "id": result.id,
            "scenario_name": result.scenario.name,
            "portfolio_name": result.scenario.portfolio.name,
            "execution_time": result.execution_time,
            "selection_label": localized_text(
                language,
                f"{result.scenario.name} · {timestamp_label}",
                f"{result.scenario.name} · {timestamp_label}",
            ),
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
        })
        chart_series.append({
            "label": localized_text(
                language,
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%d.%m %H:%M')}",
                f"{result.scenario.name} · {timestamp_label}",
            ),
            "values": normalized_path,
        })

    metric_specs = [
        (localized_text(language, "Средний итог", "Average final value"), lambda item: f"{format_display_number(item['final_value'], 2)} {item['portfolio_unit_label']}"),
        (localized_text(language, "Ожидаемая доходность", "Expected return"), lambda item: f"{format_display_percent(item['expected_return'], 2)} %"),
        (localized_text(language, "Волатильность", "Volatility"), lambda item: f"{format_display_percent(item['volatility'], 2)} %"),
        (localized_text(language, "Максимальная просадка", "Max drawdown"), lambda item: f"{format_display_percent(item['max_drawdown'], 2)} %"),
        (localized_text(language, "Вероятность убытка", "Probability of loss"), lambda item: f"{format_display_percent(item['probability_of_loss'], 2)} %"),
        (localized_text(language, "Вероятность просадки > 10%", "Probability of drawdown > 10%"), lambda item: f"{format_display_percent(item['probability_of_drawdown'], 2)} %"),
        ("VaR 95%", lambda item: f"{format_display_percent(item['var_95'], 2)} %"),
        ("CVaR 95%", lambda item: f"{format_display_percent(item['cvar_95'], 2)} %"),
        (localized_text(language, "Коэффициент Шарпа", "Sharpe ratio"), lambda item: format_display_number(item["sharpe_ratio"], 4)),
    ]
    comparison_rows = [
        {"label": row_label, "values": [formatter(item) for item in comparison_results]}
        for row_label, formatter in metric_specs
    ]
    return comparison_results, comparison_rows, chart_series


@login_required
def strategy_compare(request):
    language = get_request_language(request)
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
    available_results = []
    selected_result_ids = set()
    selection_submitted = request.GET.get("selection_mode") == "custom"

    if form.is_bound and form.is_valid():
        selected_portfolio = form.cleaned_data["portfolio"]
    elif not form.is_bound and default_portfolio:
        selected_portfolio = default_portfolio

    if selected_portfolio is not None:
        portfolio_results = list(
            results_queryset
            .filter(scenario__portfolio=selected_portfolio)
            .order_by("scenario__name", "execution_time", "id")
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
                    f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
                    f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
                ),
                "checked": result.id in selected_result_ids,
            }
            for result in portfolio_results
        ]
        comparison_results, comparison_rows, chart_series = build_strategy_comparison_payload(filtered_results, language)

    return render(request, "riskapp/strategy_compare.html", {
        "form": form,
        "comparison_results": comparison_results,
        "comparison_rows": comparison_rows,
        "chart_series": chart_series,
        "selected_portfolio": selected_portfolio,
        "available_results": available_results,
        "selected_result_ids": selected_result_ids,
        "selection_submitted": selection_submitted,
    })


def build_strategy_comparison_payload(results, language):
    comparison_results = []
    chart_series = []

    for result in results:
        metric_map = get_metric_map(result)
        portfolio_unit_label = get_portfolio_unit_label(result.scenario.portfolio, language)
        average_path = result.chart_data.get("average_path", [])
        start_value = to_decimal(average_path[0] if average_path else 0)
        normalized_path = []
        for point in average_path:
            point_decimal = to_decimal(point)
            if start_value > 0:
                normalized_path.append(float(((point_decimal / start_value) - Decimal("1")) * Decimal("100")))
            else:
                normalized_path.append(0.0)

        timestamp_label = timezone.localtime(result.execution_time).strftime("%Y-%m-%d %H:%M")
        comparison_results.append({
            "id": result.id,
            "scenario_name": result.scenario.name,
            "portfolio_name": result.scenario.portfolio.name,
            "execution_time": result.execution_time,
            "selection_label": localized_text(
                language,
                f"{result.scenario.name} · {timestamp_label}",
                f"{result.scenario.name} · {timestamp_label}",
            ),
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
        })
        chart_series.append({
            "label": localized_text(
                language,
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%d.%m %H:%M')}",
                f"{result.scenario.name} · {timestamp_label}",
            ),
            "values": normalized_path,
        })

    metric_specs = [
        (localized_text(language, "Средний итог", "Average final value"), lambda item: f"{format_display_number(item['final_value'], 2)} {item['portfolio_unit_label']}"),
        (localized_text(language, "Ожидаемая доходность", "Expected return"), lambda item: f"{format_display_percent(item['expected_return'], 2)} %"),
        (localized_text(language, "Волатильность", "Volatility"), lambda item: f"{format_display_percent(item['volatility'], 2)} %"),
        (localized_text(language, "Максимальная просадка", "Max drawdown"), lambda item: f"{format_display_percent(item['max_drawdown'], 2)} %"),
        (localized_text(language, "Вероятность убытка", "Probability of loss"), lambda item: f"{format_display_percent(item['probability_of_loss'], 2)} %"),
        (localized_text(language, "Вероятность просадки > 10%", "Probability of drawdown > 10%"), lambda item: f"{format_display_percent(item['probability_of_drawdown'], 2)} %"),
        ("VaR 95%", lambda item: f"{format_display_percent(item['var_95'], 2)} %"),
        ("CVaR 95%", lambda item: f"{format_display_percent(item['cvar_95'], 2)} %"),
        (localized_text(language, "Коэффициент Шарпа", "Sharpe ratio"), lambda item: format_display_number(item["sharpe_ratio"], 4)),
    ]
    comparison_rows = [
        {"label": row_label, "values": [formatter(item) for item in comparison_results]}
        for row_label, formatter in metric_specs
    ]
    return comparison_results, comparison_rows, chart_series


@login_required
def strategy_compare(request):
    language = get_request_language(request)
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

    if form.is_bound and form.is_valid():
        selected_portfolio = form.cleaned_data["portfolio"]
    elif not form.is_bound and default_portfolio:
        selected_portfolio = default_portfolio

    if selected_portfolio is not None:
        portfolio_results = list(
            results_queryset
            .filter(scenario__portfolio=selected_portfolio)
            .order_by("scenario__name", "execution_time", "id")
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
                    f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
                    f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
                ),
                "checked": result.id in selected_result_ids,
            }
            for result in portfolio_results
        ]
        comparison_results, comparison_rows, chart_series = build_strategy_comparison_payload(filtered_results, language)

    return render(request, "riskapp/strategy_compare.html", {
        "form": form,
        "comparison_results": comparison_results,
        "comparison_rows": comparison_rows,
        "chart_series": chart_series,
        "selected_portfolio": selected_portfolio,
        "available_results": available_results,
        "selected_result_ids": selected_result_ids,
        "selection_submitted": selection_submitted,
    })


@login_required
def scenario_create(request):
    language = get_request_language(request)
    portfolios = user_scope(request.user, Portfolio.objects.all())
    calibration_summary = None
    default_initial = {
        "preset": Scenario.PRESET_BASE,
        **SCENARIO_PRESETS[Scenario.PRESET_BASE],
    }

    if request.method == "POST" and request.POST.get("action") == "calibrate":
        try:
            form, calibration_summary = build_historical_calibration_form(
                request,
                ScenarioManagementForm,
                portfolios,
            )
            messages.success(
                request,
                localized_text(
                    language,
                    "Историческая калибровка подставила в форму тренд, волатильность, уровень шума и долю систематического риска.",
                    "Historical calibration filled trend, volatility, noise level, and systematic risk into the form.",
                ),
            )
        except ValueError as exc:
            messages.warning(request, str(exc))
            form = ScenarioManagementForm(
                initial={**default_initial, **{key: value for key, value in request.POST.items()}},
                portfolios_queryset=portfolios,
                language=language,
            )
    else:
        form = ScenarioManagementForm(
            request.POST or None,
            portfolios_queryset=portfolios,
            language=language,
            initial=default_initial,
        )

    if request.method == "POST" and form.is_valid():
        scenario = form.save(commit=False)
        scenario.user = scenario.portfolio.user
        scenario.save()
        messages.success(
            request,
            translate("scenario_created", language, name=scenario.name),
        )
        return redirect("riskapp:scenarios")

    return render(request, "riskapp/scenario_form.html", {
        "form": form,
        "mode": "create",
        "calibration_summary": calibration_summary,
    })


@login_required
def scenario_update(request, scenario_id):
    language = get_request_language(request)
    scenario = get_object_or_404(
        user_scope(request.user, Scenario.objects.select_related("portfolio")),
        id=scenario_id,
    )
    portfolios = user_scope(request.user, Portfolio.objects.all())
    calibration_summary = None

    if request.method == "POST" and request.POST.get("action") == "calibrate":
        try:
            form, calibration_summary = build_historical_calibration_form(
                request,
                ScenarioManagementForm,
                portfolios,
                instance=scenario,
            )
            messages.success(
                request,
                localized_text(
                    language,
                    "Историческая калибровка обновила параметры сценария по накопленной истории цен портфеля.",
                    "Historical calibration refreshed scenario parameters using the portfolio price history.",
                ),
            )
        except ValueError as exc:
            messages.warning(request, str(exc))
            form = ScenarioManagementForm(
                instance=scenario,
                initial={key: value for key, value in request.POST.items()},
                portfolios_queryset=portfolios,
                language=language,
            )
    else:
        form = ScenarioManagementForm(
            request.POST or None,
            instance=scenario,
            portfolios_queryset=portfolios,
            language=language,
        )

    if request.method == "POST" and form.is_valid():
        scenario = form.save(commit=False)
        scenario.user = scenario.portfolio.user
        scenario.save()
        messages.success(
            request,
            translate("scenario_updated", language, name=scenario.name),
        )
        return redirect("riskapp:scenarios")

    return render(request, "riskapp/scenario_form.html", {
        "form": form,
        "scenario": scenario,
        "mode": "edit",
        "calibration_summary": calibration_summary,
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

    form = ScenarioForm(request.POST, language=get_request_language(request))
    if not form.is_valid():
        return render(
            request,
            "riskapp/portfolio_detail.html",
            get_portfolio_detail_context(portfolio, language=get_request_language(request), scenario_form=form),
        )

    scenario = form.save(commit=False)
    scenario.user = portfolio.user if request.user.is_staff else request.user
    scenario.portfolio = portfolio
    scenario.save()

    try:
        summary = run_scenario_simulation(scenario.id)
    except ValueError as exc:
        if "Missing exchange rate" in str(exc):
            message = translate("missing_exchange_rates_warning", get_request_language(request))
        else:
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

    try:
        summary = run_scenario_simulation(scenario.id)
    except ValueError as exc:
        if "Missing exchange rate" in str(exc):
            message = translate("missing_exchange_rates_warning", get_request_language(request))
        else:
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
    chart_data = result.chart_data or {}
    start_value = to_decimal(chart_data.get("start_value", 0))
    best_value = to_decimal(chart_data.get("best_final_value", result.final_value))
    worst_value = to_decimal(chart_data.get("worst_final_value", result.final_value))
    p5_value = to_decimal(chart_data.get("percentile_5_final_value", result.final_value))
    median_value = to_decimal(chart_data.get("median_final_value", result.final_value))
    p95_value = to_decimal(chart_data.get("percentile_95_final_value", result.final_value))
    value_span = max(best_value - worst_value, Decimal("1"))
    portfolio_unit_label = get_portfolio_unit_label(result.scenario.portfolio, language)
    metrics = [localize_metric(metric, language, portfolio_unit_label) for metric in result.risk_metrics.order_by("metric_name")]

    def marker_position(value):
        return float(((to_decimal(value) - worst_value) / value_span) * Decimal("100"))

    return render(request, "riskapp/result_detail.html", {
        "result": result,
        "metrics": metrics,
        "run_notes": build_result_notes(result, language),
        "status_label": translate("status_completed", language),
        "portfolio_unit_label": portfolio_unit_label,
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
        "distribution_markers": [
            {"label": translate("worst_final_value", language), "value": format_display_number(worst_value, 2), "unit": portfolio_unit_label, "position": marker_position(worst_value), "tone": "worst"},
            {"label": "P5", "value": format_display_number(p5_value, 2), "unit": portfolio_unit_label, "position": marker_position(p5_value), "tone": "p5"},
            {"label": translate("median_final_value", language), "value": format_display_number(median_value, 2), "unit": portfolio_unit_label, "position": marker_position(median_value), "tone": "median"},
            {"label": "P95", "value": format_display_number(p95_value, 2), "unit": portfolio_unit_label, "position": marker_position(p95_value), "tone": "p95"},
            {"label": translate("best_final_value", language), "value": format_display_number(best_value, 2), "unit": portfolio_unit_label, "position": marker_position(best_value), "tone": "best"},
        ],
        "distribution_range": {
            "start": format_display_number(worst_value, 2),
            "end": format_display_number(best_value, 2),
            "unit": portfolio_unit_label,
            "delta_percent": format_display_percent(
                ((best_value - start_value) / start_value) if start_value > 0 else 0,
                2,
            ),
        },
    })


@admin_required
def administrator_dashboard(request):
    users = (
        User.objects
        .annotate(portfolios_count=Count("portfolios", distinct=True), scenarios_count=Count("scenarios", distinct=True))
        .order_by("username")
    )
    portfolios = Portfolio.objects.select_related("user").order_by("-updated_at")
    scenarios = Scenario.objects.select_related("user", "portfolio").order_by("-created_at")
    results = SimulationResult.objects.select_related("scenario", "scenario__portfolio", "scenario__user").order_by("-execution_time")[:20]
    operations = TradeOperation.objects.select_related("portfolio", "instrument", "user").order_by("-executed_at", "-created_at")[:25]

    return render(request, "riskapp/administrator_dashboard.html", {
        "users_list": users,
        "portfolios": portfolios[:25],
        "scenarios": scenarios[:25],
        "results": results,
        "operations": operations,
    })


@admin_required
def administrator_toggle_user(request, user_id):
    if request.method != "POST":
        return redirect("riskapp:administrator_dashboard")

    target = get_object_or_404(User, id=user_id)
    if target.id != request.user.id:
        target.is_active = not target.is_active
        target.save(update_fields=["is_active"])
        messages.success(
            request,
            translate("admin_user_updated", get_request_language(request), username=target.username),
        )
    return redirect("riskapp:administrator_dashboard")


@admin_required
def administrator_delete_user(request, user_id):
    if request.method != "POST":
        return redirect("riskapp:administrator_dashboard")

    target = get_object_or_404(User, id=user_id)
    username = target.username
    if target.id != request.user.id:
        target.delete()
        messages.success(
            request,
            translate("admin_user_deleted", get_request_language(request), username=username),
        )
    return redirect("riskapp:administrator_dashboard")


@admin_required
def administrator_delete_portfolio(request, portfolio_id):
    if request.method != "POST":
        return redirect("riskapp:administrator_dashboard")

    portfolio = get_object_or_404(Portfolio, id=portfolio_id)
    name = portfolio.name
    portfolio.delete()
    messages.success(
        request,
        translate("admin_portfolio_deleted", get_request_language(request), name=name),
    )
    return redirect("riskapp:administrator_dashboard")


@admin_required
def administrator_delete_scenario(request, scenario_id):
    if request.method != "POST":
        return redirect("riskapp:administrator_dashboard")

    scenario = get_object_or_404(Scenario, id=scenario_id)
    name = scenario.name
    scenario.delete()
    messages.success(
        request,
        translate("admin_scenario_deleted", get_request_language(request), name=name),
    )
    return redirect("riskapp:administrator_dashboard")


def build_strategy_comparison_payload(results, language):
    comparison_results = []
    chart_series = []

    for result in results:
        metric_map = get_metric_map(result)
        portfolio_unit_label = get_portfolio_unit_label(result.scenario.portfolio, language)
        average_path = result.chart_data.get("average_path", [])
        start_value = to_decimal(average_path[0] if average_path else 0)
        normalized_path = []
        for point in average_path:
            point_decimal = to_decimal(point)
            if start_value > 0:
                normalized_path.append(float(((point_decimal / start_value) - Decimal("1")) * Decimal("100")))
            else:
                normalized_path.append(0.0)

        comparison_results.append({
            "id": result.id,
            "scenario_name": result.scenario.name,
            "portfolio_name": result.scenario.portfolio.name,
            "execution_time": result.execution_time,
            "selection_label": localized_text(
                language,
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
            ),
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
        })
        chart_series.append({
            "label": localized_text(
                language,
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%d.%m %H:%M')}",
                f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
            ),
            "values": normalized_path,
        })

    metric_specs = [
        (localized_text(language, "Средний итог", "Average final value"), "final_value", lambda item: f"{format_display_number(item['final_value'], 2)} {item['portfolio_unit_label']}"),
        (localized_text(language, "Ожидаемая доходность", "Expected return"), "expected_return", lambda item: f"{format_display_percent(item['expected_return'], 2)} %"),
        (localized_text(language, "Волатильность", "Volatility"), "volatility", lambda item: f"{format_display_percent(item['volatility'], 2)} %"),
        (localized_text(language, "Максимальная просадка", "Max drawdown"), "max_drawdown", lambda item: f"{format_display_percent(item['max_drawdown'], 2)} %"),
        (localized_text(language, "Вероятность убытка", "Probability of loss"), "probability_of_loss", lambda item: f"{format_display_percent(item['probability_of_loss'], 2)} %"),
        (localized_text(language, "Вероятность просадки > 10%", "Probability of drawdown > 10%"), "probability_of_drawdown", lambda item: f"{format_display_percent(item['probability_of_drawdown'], 2)} %"),
        ("VaR 95%", "var_95", lambda item: f"{format_display_percent(item['var_95'], 2)} %"),
        ("CVaR 95%", "cvar_95", lambda item: f"{format_display_percent(item['cvar_95'], 2)} %"),
        (localized_text(language, "Коэффициент Шарпа", "Sharpe ratio"), "sharpe_ratio", lambda item: format_display_number(item["sharpe_ratio"], 4)),
    ]
    comparison_rows = [
        {"label": row_label, "values": [formatter(item) for item in comparison_results]}
        for row_label, _, formatter in metric_specs
    ]
    return comparison_results, comparison_rows, chart_series


@login_required
def portfolio_operation_create(request, portfolio_id):
    language = get_request_language(request)
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)
    requested_type = request.GET.get("type") or request.POST.get("operation_type") or TradeOperation.TYPE_SELL
    instrument_id = request.GET.get("instrument") or request.POST.get("instrument")
    selected_instrument = None

    if requested_type == TradeOperation.TYPE_BUY and request.method == "GET" and not instrument_id:
        return redirect(f"{reverse('riskapp:instruments')}?portfolio={portfolio.id}")

    if instrument_id:
        selected_instrument = get_object_or_404(Instrument, id=instrument_id)

    form = TradeOperationForm(
        request.POST or None,
        portfolio=portfolio,
        user=request.user,
        language=language,
        initial={
            "operation_type": requested_type,
            "instrument": selected_instrument,
            "executed_at": timezone.localtime().replace(second=0, microsecond=0),
        },
    )

    if request.method == "POST" and form.is_valid():
        instrument = form.cleaned_data["instrument"]
        price_per_unit = instrument.current_price
        try:
            operation, _ = record_trade_operation(
                user=request.user,
                portfolio=portfolio,
                instrument=instrument,
                operation_type=form.cleaned_data["operation_type"],
                quantity=form.cleaned_data["quantity"],
                price_per_unit=price_per_unit,
                executed_at=form.cleaned_data["executed_at"],
                comment=form.cleaned_data.get("comment", ""),
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            if language == "ru":
                success_message = (
                    f"Покупка {operation.instrument.ticker} сохранена."
                    if operation.operation_type == TradeOperation.TYPE_BUY
                    else f"Продажа {operation.instrument.ticker} сохранена."
                )
            else:
                success_message = (
                    f"Buy trade for {operation.instrument.ticker} was saved."
                    if operation.operation_type == TradeOperation.TYPE_BUY
                    else f"Sell trade for {operation.instrument.ticker} was saved."
                )
            messages.success(request, success_message)
            return redirect(request.POST.get("next") or reverse("riskapp:portfolio_operations", args=[portfolio.id]))

    positions_for_sale = (
        PortfolioPosition.objects.filter(portfolio=portfolio)
        .select_related("instrument")
        .order_by("instrument__ticker")
    )
    commission_preview = None
    current_price = None
    if selected_instrument:
        current_price = selected_instrument.current_price
        quantity_preview = form.data.get("quantity") if form.is_bound else form.initial.get("quantity") or 1
        try:
            commission_preview = estimate_trade_commission(int(quantity_preview or 1), current_price)
        except (TypeError, ValueError):
            commission_preview = estimate_trade_commission(1, current_price)

    return render(request, "riskapp/operation_form.html", {
        "portfolio": portfolio,
        "form": form,
        "selected_instrument": selected_instrument,
        "requested_type": requested_type,
        "positions_for_sale": positions_for_sale,
        "commission_preview": commission_preview,
        "current_price": current_price,
    })


@login_required
def portfolio_add_position(request, portfolio_id):
    portfolio = get_object_or_404(user_scope(request.user, Portfolio.objects.all()), id=portfolio_id)

    if request.method != "POST":
        return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))

    form = PortfolioPositionForm(request.POST)
    if not form.is_valid():
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "ok": False,
                "message": translate("position_add_error", get_request_language(request)),
                "errors": form.errors,
            }, status=400)
        return render(
            request,
            "riskapp/portfolio_detail.html",
            get_portfolio_detail_context(portfolio, language=get_request_language(request), position_form=form),
        )

    instrument = form.cleaned_data["instrument"]
    quantity = form.cleaned_data["quantity"]

    operation, position = record_trade_operation(
        user=request.user,
        portfolio=portfolio,
        instrument=instrument,
        operation_type=TradeOperation.TYPE_BUY,
        quantity=quantity,
        price_per_unit=instrument.current_price,
        executed_at=timezone.now(),
        comment=localized_text(
            get_request_language(request),
            "Покупка из каталога инструментов",
            "Buy created from the instrument catalog",
        ),
    )

    messages.success(
        request,
        localized_text(
            get_request_language(request),
            f"Покупка {operation.instrument.ticker} сохранена в истории сделок.",
            f"The buy trade for {operation.instrument.ticker} was added to the trade history.",
        ),
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "message": localized_text(
                get_request_language(request),
                f"Покупка {operation.instrument.ticker} добавлена.",
                f"Buy trade for {operation.instrument.ticker} added.",
            ),
            "ticker": instrument.ticker,
            "quantity": position.quantity if position else 0,
            "commission": str(operation.commission),
        })

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url:
        return redirect(next_url)
    return redirect(reverse("riskapp:portfolio_detail", args=[portfolio.id]))


@login_required
def strategy_compare(request):
    language = get_request_language(request)
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

    if form.is_bound and form.is_valid():
        selected_portfolio = form.cleaned_data["portfolio"]
    elif not form.is_bound and default_portfolio:
        selected_portfolio = default_portfolio

    if selected_portfolio is not None:
        portfolio_results = list(
            results_queryset
            .filter(scenario__portfolio=selected_portfolio)
            .order_by("scenario__name", "execution_time", "id")
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
                    f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
                    f"{result.scenario.name} · {timezone.localtime(result.execution_time).strftime('%Y-%m-%d %H:%M')}",
                ),
                "checked": result.id in selected_result_ids,
            }
            for result in portfolio_results
        ]
        comparison_results, comparison_rows, chart_series = build_strategy_comparison_payload(filtered_results, language)

    return render(request, "riskapp/strategy_compare.html", {
        "form": form,
        "comparison_results": comparison_results,
        "comparison_rows": comparison_rows,
        "chart_series": chart_series,
        "selected_portfolio": selected_portfolio,
        "available_results": available_results,
        "selected_result_ids": selected_result_ids,
        "selection_submitted": selection_submitted,
    })

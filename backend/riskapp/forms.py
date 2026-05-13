from decimal import Decimal

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from riskapp.i18n import normalize_language, translate
from riskapp.models import Instrument, Portfolio, PortfolioPosition, Scenario, SimulationResult, TradeOperation


def build_sector_choices(language="ru", include_all=False, empty_label="---------"):
    values = list(Instrument.objects.exclude(sector="").order_by("sector").values_list("sector", flat=True).distinct())
    for sector in Instrument.known_sectors():
        if sector not in values:
            values.append(sector)
    values = sorted(value for value in values if value)
    label_map = {
        Instrument.SECTOR_EQUITIES: translate("sector_equities", language),
        Instrument.SECTOR_BONDS: translate("sector_bonds", language),
        Instrument.SECTOR_FUNDS: translate("sector_funds", language),
    }
    choices = [(value, label_map.get(value, value)) for value in values]
    if include_all:
        return [("", translate("all_sectors", language))] + choices
    return [("", empty_label)] + choices


def build_rebalancing_choices(language="ru"):
    if language == "ru":
        return [
            (Scenario.REBALANCE_NONE, "Без ребалансировки"),
            (Scenario.REBALANCE_MONTHLY, "Ежемесячная ребалансировка"),
            (Scenario.REBALANCE_QUARTERLY, "Квартальная ребалансировка"),
        ]
    return [
        (Scenario.REBALANCE_NONE, "Buy and hold"),
        (Scenario.REBALANCE_MONTHLY, "Monthly rebalance"),
        (Scenario.REBALANCE_QUARTERLY, "Quarterly rebalance"),
    ]


def validate_time_step_vs_horizon(cleaned_data, language):
    time_horizon = cleaned_data.get("time_horizon")
    time_step = cleaned_data.get("time_step")
    if time_horizon is None or time_step is None:
        return
    if Decimal(str(time_step)) > Decimal(str(time_horizon)):
        raise forms.ValidationError({
            "time_step": translate("error_time_step_gt_horizon", language),
        })


DISPLAY_DECIMALS = {
    "trend": 2,
    "volatility": 2,
    "noise_level": 2,
    "market_shock": 2,
    "currency_shock": 2,
    "inflation_shock": 2,
    "sector_shock": 2,
    "interest_rate_shock": 2,
    "jump_intensity": 2,
    "jump_magnitude": 2,
    "systematic_risk": 2,
    "mean_reversion_strength": 2,
    "time_step": 0,
}

SCENARIO_NUMERIC_LIMITS = {
    "trend": (Decimal("-0.30"), Decimal("0.30")),
    "volatility": (Decimal("0.00"), Decimal("0.60")),
    "noise_level": (Decimal("0.00"), Decimal("0.15")),
    "market_shock": (Decimal("-0.25"), Decimal("0.25")),
    "currency_shock": (Decimal("-0.20"), Decimal("0.20")),
    "inflation_shock": (Decimal("-0.05"), Decimal("0.25")),
    "sector_shock": (Decimal("-0.20"), Decimal("0.20")),
    "interest_rate_shock": (Decimal("-0.10"), Decimal("0.10")),
    "jump_intensity": (Decimal("0.00"), Decimal("5.00")),
    "jump_magnitude": (Decimal("0.00"), Decimal("0.30")),
    "systematic_risk": (Decimal("0.00"), Decimal("1.00")),
    "mean_reversion_strength": (Decimal("0.00"), Decimal("0.50")),
}


def format_decimal_for_display(value, decimals):
    if value in (None, ""):
        return value
    quantizer = Decimal("1") if decimals == 0 else Decimal(f"1.{'0' * decimals}")
    return str(Decimal(str(value)).quantize(quantizer)).replace(",", ".")


def apply_scenario_display_precision(form):
    if form.is_bound:
        return
    for field_name, decimals in DISPLAY_DECIMALS.items():
        if field_name not in form.fields:
            continue
        raw_value = form.initial.get(field_name)
        if raw_value in (None, ""):
            continue
        form.initial[field_name] = format_decimal_for_display(raw_value, decimals)


def apply_scenario_numeric_limits(form):
    for field_name, limits in SCENARIO_NUMERIC_LIMITS.items():
        if field_name not in form.fields:
            continue
        field = form.fields[field_name]
        field.min_value = limits[0]
        field.max_value = limits[1]


def validate_scenario_numeric_limits(cleaned_data, language):
    errors = {}
    for field_name, (min_value, max_value) in SCENARIO_NUMERIC_LIMITS.items():
        value = cleaned_data.get(field_name)
        if value in (None, ""):
            continue
        decimal_value = Decimal(str(value))
        if decimal_value < min_value or decimal_value > max_value:
            errors[field_name] = translate(
                "error_value_between",
                language,
                minimum=format_decimal_for_display(min_value, DISPLAY_DECIMALS.get(field_name, 2)),
                maximum=format_decimal_for_display(max_value, DISPLAY_DECIMALS.get(field_name, 2)),
            )
    if errors:
        raise forms.ValidationError(errors)

SCENARIO_FIELD_WIDGETS = {
    "description": forms.Textarea(attrs={"rows": 3}),
    "preset": forms.Select(),
    "rebalancing_frequency": forms.Select(),
    "trend": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "-0.3",
        "max": "0.3",
        "data-slider-min": "-0.3",
        "data-slider-max": "0.3",
        "data-slider-step": "0.01",
    }),
    "volatility": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "0",
        "max": "0.6",
        "data-slider-min": "0",
        "data-slider-max": "0.6",
        "data-slider-step": "0.01",
    }),
    "noise_level": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "0",
        "max": "0.15",
        "data-slider-min": "0",
        "data-slider-max": "0.15",
        "data-slider-step": "0.01",
    }),
    "market_shock": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "-0.25",
        "max": "0.25",
        "data-slider-min": "-0.25",
        "data-slider-max": "0.25",
        "data-slider-step": "0.01",
    }),
    "currency_shock": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "-0.2",
        "max": "0.2",
        "data-slider-min": "-0.2",
        "data-slider-max": "0.2",
        "data-slider-step": "0.01",
    }),
    "inflation_shock": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "-0.05",
        "max": "0.25",
        "data-slider-min": "-0.05",
        "data-slider-max": "0.25",
        "data-slider-step": "0.01",
    }),
    "sector_target": forms.Select(),
    "sector_shock": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "-0.2",
        "max": "0.2",
        "data-slider-min": "-0.2",
        "data-slider-max": "0.2",
        "data-slider-step": "0.01",
    }),
    "interest_rate_shock": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "-0.1",
        "max": "0.1",
        "data-slider-min": "-0.1",
        "data-slider-max": "0.1",
        "data-slider-step": "0.01",
    }),
    "jump_intensity": forms.NumberInput(attrs={
        "step": "0.1",
        "min": "0",
        "max": "5",
        "data-slider-min": "0",
        "data-slider-max": "5",
        "data-slider-step": "0.1",
    }),
    "jump_magnitude": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "0",
        "max": "0.3",
        "data-slider-min": "0",
        "data-slider-max": "0.3",
        "data-slider-step": "0.01",
    }),
    "systematic_risk": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "0",
        "max": "1",
        "data-slider-min": "0",
        "data-slider-max": "1",
        "data-slider-step": "0.01",
    }),
    "mean_reversion_strength": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "0",
        "max": "0.5",
        "data-slider-min": "0",
        "data-slider-max": "0.5",
        "data-slider-step": "0.01",
    }),
    "time_horizon": forms.NumberInput(attrs={
        "step": "1",
        "min": "1",
        "max": "3650",
        "data-slider-min": "1",
        "data-slider-max": "3650",
        "data-slider-step": "1",
    }),
    "time_step": forms.NumberInput(attrs={
        "step": "1",
        "min": "1",
        "max": "30",
        "data-slider-min": "1",
        "data-slider-max": "30",
        "data-slider-step": "1",
    }),
    "iterations_count": forms.NumberInput(attrs={
        "step": "10",
        "min": "10",
        "max": "5000",
        "data-slider-min": "10",
        "data-slider-max": "5000",
        "data-slider-step": "10",
    }),
}

SCENARIO_PRESETS = {
    Scenario.PRESET_BASE: {
        "rebalancing_frequency": Scenario.REBALANCE_NONE,
        "trend": "0.060000",
        "volatility": "0.120000",
        "noise_level": "0.015000",
        "market_shock": "0.000000",
        "currency_shock": "0.000000",
        "inflation_shock": "0.050000",
        "sector_target": "",
        "sector_shock": "0.000000",
        "interest_rate_shock": "0.000000",
        "jump_intensity": "0.200",
        "jump_magnitude": "0.040000",
        "systematic_risk": "0.5500",
        "mean_reversion_strength": "0.1200",
        "time_horizon": 365,
        "time_step": "1.0000",
        "iterations_count": 500,
    },
    Scenario.PRESET_OPTIMISTIC: {
        "rebalancing_frequency": Scenario.REBALANCE_NONE,
        "trend": "0.120000",
        "volatility": "0.140000",
        "noise_level": "0.015000",
        "market_shock": "0.030000",
        "currency_shock": "0.020000",
        "inflation_shock": "0.030000",
        "sector_target": "Equities",
        "sector_shock": "0.020000",
        "interest_rate_shock": "-0.010000",
        "jump_intensity": "0.250",
        "jump_magnitude": "0.050000",
        "systematic_risk": "0.5000",
        "mean_reversion_strength": "0.1000",
        "time_horizon": 365,
        "time_step": "1.0000",
        "iterations_count": 700,
    },
    Scenario.PRESET_PESSIMISTIC: {
        "rebalancing_frequency": Scenario.REBALANCE_NONE,
        "trend": "-0.030000",
        "volatility": "0.180000",
        "noise_level": "0.020000",
        "market_shock": "-0.040000",
        "currency_shock": "-0.030000",
        "inflation_shock": "0.070000",
        "sector_target": "Equities",
        "sector_shock": "-0.040000",
        "interest_rate_shock": "0.015000",
        "jump_intensity": "0.600",
        "jump_magnitude": "0.070000",
        "systematic_risk": "0.6000",
        "mean_reversion_strength": "0.1500",
        "time_horizon": 365,
        "time_step": "1.0000",
        "iterations_count": 700,
    },
    Scenario.PRESET_STRESS: {
        "rebalancing_frequency": Scenario.REBALANCE_NONE,
        "trend": "-0.070000",
        "volatility": "0.280000",
        "noise_level": "0.040000",
        "market_shock": "-0.080000",
        "currency_shock": "-0.060000",
        "inflation_shock": "0.100000",
        "sector_target": "Equities",
        "sector_shock": "-0.070000",
        "interest_rate_shock": "0.030000",
        "jump_intensity": "1.100",
        "jump_magnitude": "0.100000",
        "systematic_risk": "0.7500",
        "mean_reversion_strength": "0.1800",
        "time_horizon": 240,
        "time_step": "1.0000",
        "iterations_count": 900,
    },
    Scenario.PRESET_CRISIS: {
        "rebalancing_frequency": Scenario.REBALANCE_NONE,
        "trend": "-0.120000",
        "volatility": "0.400000",
        "noise_level": "0.060000",
        "market_shock": "-0.150000",
        "currency_shock": "-0.100000",
        "inflation_shock": "0.140000",
        "sector_target": "Equities",
        "sector_shock": "-0.120000",
        "interest_rate_shock": "0.050000",
        "jump_intensity": "1.600",
        "jump_magnitude": "0.150000",
        "systematic_risk": "0.8800",
        "mean_reversion_strength": "0.2200",
        "time_horizon": 180,
        "time_step": "1.0000",
        "iterations_count": 1000,
    },
}


def resolve_language(language=None, request=None):
    if language:
        return normalize_language(language)
    if request is not None:
        return normalize_language(request.session.get("ui_language", "ru"))
    return "ru"


def translate_password_validation_errors(error, language):
    messages = []
    for item in error.error_list:
        if item.code == "password_too_short":
            messages.append(translate("error_password_too_short", language))
        elif item.code == "password_too_common":
            messages.append(translate("error_password_too_common", language))
        elif item.code == "password_entirely_numeric":
            messages.append(translate("error_password_entirely_numeric", language))
        elif item.code == "password_too_similar":
            messages.append(translate("error_password_too_similar", language))
        else:
            messages.append(item.message)
    return messages


class SignUpForm(UserCreationForm):
    email = forms.EmailField()
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "first_name", "last_name", "email", "password1", "password2"]

    def __init__(self, *args, language="ru", **kwargs):
        super().__init__(*args, **kwargs)
        self.language = language

        self.fields["username"].help_text = ""
        self.fields["password1"].help_text = ""
        self.fields["password2"].help_text = ""

        self.fields["username"].error_messages["required"] = translate("error_username_required", language)
        self.fields["first_name"].error_messages["required"] = translate("error_first_name_required", language)
        self.fields["email"].error_messages["required"] = translate("error_email_required", language)
        self.fields["email"].error_messages["invalid"] = translate("error_email_invalid", language)
        self.fields["password1"].error_messages["required"] = translate("error_password_required", language)
        self.fields["password2"].error_messages["required"] = translate("error_password_confirm_required", language)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(translate("error_username_exists", self.language))
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(translate("error_email_exists", self.language))
        return email

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(translate("error_password_mismatch", self.language))

        if password2:
            try:
                validate_password(password2, self.instance)
            except ValidationError as exc:
                raise forms.ValidationError(translate_password_validation_errors(exc, self.language))

        return password2


class ProfileForm(forms.ModelForm):
    def __init__(self, *args, language="ru", **kwargs):
        super().__init__(*args, **kwargs)
        self.language = language
        self.fields["email"].error_messages["required"] = translate("error_email_required", language)
        self.fields["email"].error_messages["invalid"] = translate("error_email_invalid", language)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        queryset = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError(translate("error_email_exists", self.language))
        return email


class LocalizedAuthenticationForm(AuthenticationForm):
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self.language = resolve_language(request=request)
        self.fields["username"].label = translate("username", self.language)
        self.fields["password"].label = translate("password", self.language)
        self.fields["username"].error_messages["required"] = translate("error_username_required", self.language)
        self.fields["password"].error_messages["required"] = translate("error_password_required", self.language)
        self.error_messages["invalid_login"] = translate("error_invalid_login", self.language)
        self.error_messages["inactive"] = translate("error_account_inactive", self.language)


class LocalizedPasswordChangeForm(PasswordChangeForm):
    def __init__(self, user, *args, language="ru", **kwargs):
        super().__init__(user, *args, **kwargs)
        self.language = resolve_language(language=language)
        self.fields["old_password"].label = translate("old_password", self.language)
        self.fields["new_password1"].label = translate("new_password", self.language)
        self.fields["new_password2"].label = translate("password_confirm", self.language)
        self.fields["old_password"].help_text = ""
        self.fields["new_password1"].help_text = ""
        self.fields["new_password2"].help_text = ""
        self.error_messages["password_incorrect"] = translate("error_old_password_incorrect", self.language)

    def clean_new_password2(self):
        password1 = self.cleaned_data.get("new_password1")
        password2 = self.cleaned_data.get("new_password2")

        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(translate("error_password_mismatch", self.language))

        if password2:
            try:
                validate_password(password2, self.user)
            except ValidationError as exc:
                raise forms.ValidationError(translate_password_validation_errors(exc, self.language))

        return password2


class LocalizedPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, language="ru", **kwargs):
        super().__init__(*args, **kwargs)
        self.language = resolve_language(language=language)
        self.fields["email"].label = translate("email", self.language)
        self.fields["email"].error_messages["required"] = translate("error_email_required", self.language)
        self.fields["email"].error_messages["invalid"] = translate("error_email_invalid", self.language)


class LocalizedSetPasswordForm(SetPasswordForm):
    def __init__(self, user, *args, language="ru", **kwargs):
        super().__init__(user, *args, **kwargs)
        self.language = resolve_language(language=language)
        self.fields["new_password1"].label = translate("new_password", self.language)
        self.fields["new_password2"].label = translate("password_confirm", self.language)
        self.fields["new_password1"].help_text = ""
        self.fields["new_password2"].help_text = ""

    def clean_new_password2(self):
        password1 = self.cleaned_data.get("new_password1")
        password2 = self.cleaned_data.get("new_password2")

        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(translate("error_password_mismatch", self.language))

        if password2:
            try:
                validate_password(password2, self.user)
            except ValidationError as exc:
                raise forms.ValidationError(translate_password_validation_errors(exc, self.language))

        return password2


class PortfolioForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ["name", "description", "base_currency"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class PortfolioPositionForm(forms.ModelForm):
    class Meta:
        model = PortfolioPosition
        fields = ["instrument", "quantity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["instrument"].queryset = Instrument.objects.order_by("ticker")
        self.fields["quantity"].min_value = 1


class PortfolioPositionQuantityForm(forms.ModelForm):
    class Meta:
        model = PortfolioPosition
        fields = ["quantity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quantity"].min_value = 1


class TradeOperationForm(forms.ModelForm):
    def __init__(self, *args, portfolio=None, user=None, language="ru", **kwargs):
        super().__init__(*args, **kwargs)
        self.portfolio = portfolio
        self.user = user
        self.language = language

        all_instruments = Instrument.objects.order_by("ticker")
        owned_instruments = all_instruments
        if portfolio is not None:
            owned_ids = (
                PortfolioPosition.objects.filter(portfolio=portfolio)
                .values_list("instrument_id", flat=True)
            )
            owned_instruments = all_instruments.filter(id__in=owned_ids)

        self.fields["instrument"].queryset = all_instruments
        self.fields["quantity"].min_value = 1
        self.fields["executed_at"].initial = timezone.now
        if language == "ru":
            self.fields["operation_type"].choices = [
                (TradeOperation.TYPE_BUY, "Покупка"),
                (TradeOperation.TYPE_SELL, "Продажа"),
            ]
        else:
            self.fields["operation_type"].choices = TradeOperation.TYPE_CHOICES

        if language == "ru":
            self.fields["operation_type"].label = "Тип операции"
            self.fields["instrument"].label = "Инструмент"
            self.fields["quantity"].label = "Количество"
            self.fields["executed_at"].label = "Дата и время сделки"
            self.fields["comment"].label = "Комментарий"
            self.fields["comment"].help_text = "Необязательно. Можно указать причину сделки или заметку."
            self.fields["executed_at"].help_text = "Если оставить текущее значение, сделка будет считаться совершенной прямо сейчас."
        else:
            self.fields["operation_type"].label = "Operation type"
            self.fields["instrument"].label = "Instrument"
            self.fields["quantity"].label = "Quantity"
            self.fields["executed_at"].label = "Execution time"
            self.fields["comment"].label = "Comment"
            self.fields["comment"].help_text = "Optional. Use it for a trade note or rationale."
            self.fields["executed_at"].help_text = "Leave the current value to record the trade as happening now."

        if language == "ru":
            self.fields["operation_type"].choices = [
                (TradeOperation.TYPE_BUY, "Покупка"),
                (TradeOperation.TYPE_SELL, "Продажа"),
            ]
            self.fields["operation_type"].label = "Тип сделки"
            self.fields["instrument"].label = "Инструмент"
            self.fields["quantity"].label = "Количество"
            self.fields["executed_at"].label = "Дата и время сделки"
            self.fields["comment"].label = "Комментарий"
            self.fields["comment"].help_text = "Необязательно. Можно оставить заметку к сделке или кратко описать её цель."
            self.fields["executed_at"].help_text = "Если оставить текущее значение, сделка будет считаться совершённой прямо сейчас."

        operation_type = None
        if self.is_bound:
            operation_type = self.data.get(self.add_prefix("operation_type"))
        elif self.initial.get("operation_type"):
            operation_type = self.initial.get("operation_type")

        if operation_type == TradeOperation.TYPE_SELL and portfolio is not None:
            self.fields["instrument"].queryset = owned_instruments

    class Meta:
        model = TradeOperation
        fields = [
            "operation_type",
            "instrument",
            "quantity",
            "executed_at",
            "comment",
        ]
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 3}),
            "executed_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def clean(self):
        cleaned_data = super().clean()
        operation_type = cleaned_data.get("operation_type")
        instrument = cleaned_data.get("instrument")
        quantity = cleaned_data.get("quantity")

        if (
            self.portfolio is not None
            and operation_type == TradeOperation.TYPE_SELL
            and instrument is not None
            and quantity
        ):
            position = PortfolioPosition.objects.filter(
                portfolio=self.portfolio,
                instrument=instrument,
            ).first()
            if position is None:
                message = "В портфеле нет этой позиции для продажи." if self.language == "ru" else "This position is not available for selling in the portfolio."
                raise forms.ValidationError({"instrument": message})
            if quantity > position.quantity:
                message = (
                    f"Нельзя продать больше {position.quantity} шт."
                    if self.language == "ru"
                    else f"You cannot sell more than {position.quantity} units."
                )
                raise forms.ValidationError({"quantity": message})
        return cleaned_data

    def clean(self):
        cleaned_data = super().clean()
        operation_type = cleaned_data.get("operation_type")
        instrument = cleaned_data.get("instrument")
        quantity = cleaned_data.get("quantity")

        if (
            self.portfolio is not None
            and operation_type == TradeOperation.TYPE_SELL
            and instrument is not None
            and quantity
        ):
            position = PortfolioPosition.objects.filter(
                portfolio=self.portfolio,
                instrument=instrument,
            ).first()
            if position is None:
                message = (
                    "В портфеле нет этой позиции для продажи."
                    if self.language == "ru"
                    else "This position is not available for selling in the portfolio."
                )
                raise forms.ValidationError({"instrument": message})
            if quantity > position.quantity:
                message = (
                    f"Нельзя продать больше {position.quantity} шт."
                    if self.language == "ru"
                    else f"You cannot sell more than {position.quantity} units."
                )
                raise forms.ValidationError({"quantity": message})
        return cleaned_data


class StrategyComparisonForm(forms.Form):
    portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none(), required=True)

    def __init__(self, *args, portfolios_queryset=None, language="ru", **kwargs):
        super().__init__(*args, **kwargs)
        self.language = language
        queryset = (portfolios_queryset if portfolios_queryset is not None else Portfolio.objects.none()).order_by("name")
        self.fields["portfolio"].queryset = queryset
        if language == "ru":
            self.fields["portfolio"].label = "Портфель"
        else:
            self.fields["portfolio"].label = "Portfolio"

    def clean(self):
        cleaned_data = super().clean()
        portfolio = cleaned_data.get("portfolio")
        if portfolio is None:
            return cleaned_data
        results_count = SimulationResult.objects.filter(scenario__portfolio=portfolio).count()
        if results_count < 2:
            message = (
                "Для сравнения в выбранном портфеле нужно как минимум два результата моделирования."
                if self.language == "ru"
                else "The selected portfolio needs at least two simulation results to compare."
            )
            raise forms.ValidationError({"portfolio": message})
        return cleaned_data


class InstrumentSearchForm(forms.Form):
    query = forms.CharField(required=False)
    instrument_type = forms.CharField(required=False)
    sector = forms.ChoiceField(required=False, choices=())
    currency = forms.CharField(required=False)
    price_min = forms.DecimalField(required=False, min_value=0, decimal_places=2, max_digits=15)
    price_max = forms.DecimalField(required=False, min_value=0, decimal_places=2, max_digits=15)
    portfolio = forms.IntegerField(required=False, min_value=1)

    def __init__(self, *args, language="ru", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sector"].choices = build_sector_choices(language=language, include_all=True)


class ScenarioForm(forms.ModelForm):
    sector_target = forms.ChoiceField(required=False, choices=())

    def _configure_sector_choices(self):
        self.fields["sector_target"].choices = build_sector_choices(
            language=self.language,
            empty_label=translate("no_sector_shock", self.language),
        )

    def __init__(self, *args, **kwargs):
        self.language = kwargs.pop("language", "ru")
        super().__init__(*args, **kwargs)
        self._configure_sector_choices()
        self.fields["preset"].choices = build_preset_choices(self.language)
        self.fields["rebalancing_frequency"].choices = build_rebalancing_choices(self.language)
        apply_scenario_numeric_limits(self)
        apply_scenario_display_precision(self)
        for field_name in (
            "preset",
            "rebalancing_frequency",
            "market_shock",
            "currency_shock",
            "inflation_shock",
            "sector_target",
            "sector_shock",
            "interest_rate_shock",
            "jump_intensity",
            "jump_magnitude",
            "systematic_risk",
            "mean_reversion_strength",
        ):
            self.fields[field_name].required = False
        self.fields["preset"].initial = self.initial.get("preset", Scenario.PRESET_BASE)

    class Meta:
        model = Scenario
        fields = [
            "preset",
            "rebalancing_frequency",
            "name",
            "description",
            "trend",
            "volatility",
            "noise_level",
            "market_shock",
            "currency_shock",
            "inflation_shock",
            "sector_target",
            "sector_shock",
            "interest_rate_shock",
            "jump_intensity",
            "jump_magnitude",
            "systematic_risk",
            "mean_reversion_strength",
            "time_horizon",
            "time_step",
            "iterations_count",
        ]
        widgets = SCENARIO_FIELD_WIDGETS

    def clean(self):
        cleaned_data = super().clean()
        preset = cleaned_data.get("preset") or Scenario.PRESET_BASE
        cleaned_data["rebalancing_frequency"] = cleaned_data.get("rebalancing_frequency") or Scenario.REBALANCE_NONE
        cleaned_data["preset"] = preset
        self.cleaned_data["preset"] = preset
        cleaned_data["market_shock"] = cleaned_data.get("market_shock") or Decimal("0")
        cleaned_data["currency_shock"] = cleaned_data.get("currency_shock") or Decimal("0")
        cleaned_data["inflation_shock"] = cleaned_data.get("inflation_shock") or Decimal("0")
        cleaned_data["sector_target"] = cleaned_data.get("sector_target") or ""
        cleaned_data["sector_shock"] = cleaned_data.get("sector_shock") or Decimal("0")
        cleaned_data["interest_rate_shock"] = cleaned_data.get("interest_rate_shock") or Decimal("0")
        cleaned_data["jump_intensity"] = cleaned_data.get("jump_intensity") or Decimal("0.200")
        cleaned_data["jump_magnitude"] = cleaned_data.get("jump_magnitude") or Decimal("0.040000")
        cleaned_data["systematic_risk"] = cleaned_data.get("systematic_risk") or Decimal("0.6500")
        cleaned_data["mean_reversion_strength"] = cleaned_data.get("mean_reversion_strength") or Decimal("0.1500")
        validate_scenario_numeric_limits(cleaned_data, self.language)
        validate_time_step_vs_horizon(cleaned_data, self.language)
        return cleaned_data


class ScenarioManagementForm(forms.ModelForm):
    sector_target = forms.ChoiceField(required=False, choices=())

    def _configure_sector_choices(self):
        self.fields["sector_target"].choices = build_sector_choices(
            language=self.language,
            empty_label=translate("no_sector_shock", self.language),
        )

    def __init__(self, *args, portfolios_queryset=None, **kwargs):
        self.language = kwargs.pop("language", "ru")
        super().__init__(*args, **kwargs)
        self._configure_sector_choices()
        self.fields["preset"].choices = build_preset_choices(self.language)
        self.fields["rebalancing_frequency"].choices = build_rebalancing_choices(self.language)
        apply_scenario_numeric_limits(self)
        apply_scenario_display_precision(self)
        if portfolios_queryset is not None:
            self.fields["portfolio"].queryset = portfolios_queryset.order_by("name")
        for field_name in (
            "preset",
            "rebalancing_frequency",
            "market_shock",
            "currency_shock",
            "inflation_shock",
            "sector_target",
            "sector_shock",
            "interest_rate_shock",
            "jump_intensity",
            "jump_magnitude",
            "systematic_risk",
            "mean_reversion_strength",
        ):
            self.fields[field_name].required = False
        self.fields["preset"].initial = self.initial.get("preset", Scenario.PRESET_BASE)

    class Meta:
        model = Scenario
        fields = [
            "portfolio",
            "preset",
            "rebalancing_frequency",
            "name",
            "description",
            "trend",
            "volatility",
            "noise_level",
            "market_shock",
            "currency_shock",
            "inflation_shock",
            "sector_target",
            "sector_shock",
            "interest_rate_shock",
            "jump_intensity",
            "jump_magnitude",
            "systematic_risk",
            "mean_reversion_strength",
            "time_horizon",
            "time_step",
            "iterations_count",
        ]
        widgets = SCENARIO_FIELD_WIDGETS

    def clean(self):
        cleaned_data = super().clean()
        preset = cleaned_data.get("preset") or Scenario.PRESET_BASE
        cleaned_data["rebalancing_frequency"] = cleaned_data.get("rebalancing_frequency") or Scenario.REBALANCE_NONE
        cleaned_data["preset"] = preset
        self.cleaned_data["preset"] = preset
        cleaned_data["market_shock"] = cleaned_data.get("market_shock") or Decimal("0")
        cleaned_data["currency_shock"] = cleaned_data.get("currency_shock") or Decimal("0")
        cleaned_data["inflation_shock"] = cleaned_data.get("inflation_shock") or Decimal("0")
        cleaned_data["sector_target"] = cleaned_data.get("sector_target") or ""
        cleaned_data["sector_shock"] = cleaned_data.get("sector_shock") or Decimal("0")
        cleaned_data["interest_rate_shock"] = cleaned_data.get("interest_rate_shock") or Decimal("0")
        cleaned_data["jump_intensity"] = cleaned_data.get("jump_intensity") or Decimal("0.200")
        cleaned_data["jump_magnitude"] = cleaned_data.get("jump_magnitude") or Decimal("0.040000")
        cleaned_data["systematic_risk"] = cleaned_data.get("systematic_risk") or Decimal("0.6500")
        cleaned_data["mean_reversion_strength"] = cleaned_data.get("mean_reversion_strength") or Decimal("0.1500")
        validate_scenario_numeric_limits(cleaned_data, self.language)
        validate_time_step_vs_horizon(cleaned_data, self.language)
        return cleaned_data


def build_rebalancing_choices(language="ru"):
    if language == "ru":
        return [
            (Scenario.REBALANCE_NONE, "Без ребалансировки"),
            (Scenario.REBALANCE_MONTHLY, "Ежемесячная ребалансировка"),
            (Scenario.REBALANCE_QUARTERLY, "Квартальная ребалансировка"),
        ]
    return [
        (Scenario.REBALANCE_NONE, "Buy and hold"),
        (Scenario.REBALANCE_MONTHLY, "Monthly rebalance"),
        (Scenario.REBALANCE_QUARTERLY, "Quarterly rebalance"),
    ]


def build_preset_choices(language="ru"):
    if language == "ru":
        return [
            (Scenario.PRESET_CUSTOM, "Пользовательский"),
            (Scenario.PRESET_BASE, "Базовый"),
            (Scenario.PRESET_OPTIMISTIC, "Оптимистичный"),
            (Scenario.PRESET_PESSIMISTIC, "Пессимистичный"),
            (Scenario.PRESET_STRESS, "Стрессовый"),
            (Scenario.PRESET_CRISIS, "Кризисный"),
        ]
    return Scenario.PRESET_CHOICES


def build_rebalancing_choices(language="ru"):
    if language == "ru":
        return [
            (Scenario.REBALANCE_NONE, "Без ребалансировки"),
            (Scenario.REBALANCE_MONTHLY, "Ежемесячная ребалансировка"),
            (Scenario.REBALANCE_QUARTERLY, "Квартальная ребалансировка"),
        ]
    return [
        (Scenario.REBALANCE_NONE, "Buy and hold"),
        (Scenario.REBALANCE_MONTHLY, "Monthly rebalance"),
        (Scenario.REBALANCE_QUARTERLY, "Quarterly rebalance"),
    ]


def build_preset_choices(language="ru"):
    if language == "ru":
        return [
            (Scenario.PRESET_CUSTOM, "Пользовательский"),
            (Scenario.PRESET_BASE, "Базовый"),
            (Scenario.PRESET_OPTIMISTIC, "Оптимистичный"),
            (Scenario.PRESET_PESSIMISTIC, "Пессимистичный"),
            (Scenario.PRESET_STRESS, "Стрессовый"),
            (Scenario.PRESET_CRISIS, "Кризисный"),
        ]
    return list(Scenario.PRESET_CHOICES)


def build_rebalancing_choices(language="ru"):
    if language == "ru":
        return [
            (Scenario.REBALANCE_NONE, "Без ребалансировки"),
            (Scenario.REBALANCE_MONTHLY, "Ежемесячная ребалансировка"),
            (Scenario.REBALANCE_QUARTERLY, "Квартальная ребалансировка"),
        ]
    return [
        (Scenario.REBALANCE_NONE, "Buy and hold"),
        (Scenario.REBALANCE_MONTHLY, "Monthly rebalance"),
        (Scenario.REBALANCE_QUARTERLY, "Quarterly rebalance"),
    ]


def build_preset_choices(language="ru"):
    if language == "ru":
        return [
            (Scenario.PRESET_CUSTOM, "Пользовательский"),
            (Scenario.PRESET_BASE, "Базовый"),
            (Scenario.PRESET_OPTIMISTIC, "Оптимистичный"),
            (Scenario.PRESET_PESSIMISTIC, "Пессимистичный"),
            (Scenario.PRESET_STRESS, "Стрессовый"),
            (Scenario.PRESET_CRISIS, "Кризисный"),
        ]
    return list(Scenario.PRESET_CHOICES)

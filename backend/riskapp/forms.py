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

from riskapp.i18n import normalize_language, translate
from riskapp.models import Instrument, Portfolio, PortfolioPosition, Scenario

SCENARIO_FIELD_WIDGETS = {
    "description": forms.Textarea(attrs={"rows": 3}),
    "preset": forms.Select(),
    "trend": forms.NumberInput(attrs={
        "step": "0.001",
        "min": "-0.5",
        "max": "0.5",
        "data-slider-min": "-0.5",
        "data-slider-max": "0.5",
        "data-slider-step": "0.001",
    }),
    "volatility": forms.NumberInput(attrs={
        "step": "0.001",
        "min": "0",
        "max": "1",
        "data-slider-min": "0",
        "data-slider-max": "1",
        "data-slider-step": "0.001",
    }),
    "noise_level": forms.NumberInput(attrs={
        "step": "0.001",
        "min": "0",
        "max": "0.5",
        "data-slider-min": "0",
        "data-slider-max": "0.5",
        "data-slider-step": "0.001",
    }),
    "market_shock": forms.NumberInput(attrs={
        "step": "0.001",
        "min": "-0.8",
        "max": "0.8",
        "data-slider-min": "-0.8",
        "data-slider-max": "0.8",
        "data-slider-step": "0.001",
    }),
    "currency_shock": forms.NumberInput(attrs={
        "step": "0.001",
        "min": "-0.8",
        "max": "0.8",
        "data-slider-min": "-0.8",
        "data-slider-max": "0.8",
        "data-slider-step": "0.001",
    }),
    "systematic_risk": forms.NumberInput(attrs={
        "step": "0.01",
        "min": "0",
        "max": "1",
        "data-slider-min": "0",
        "data-slider-max": "1",
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
        "trend": "0.050000",
        "volatility": "0.150000",
        "noise_level": "0.020000",
        "market_shock": "0.000000",
        "currency_shock": "0.000000",
        "systematic_risk": "0.6500",
        "time_horizon": 365,
        "time_step": "1.0000",
        "iterations_count": 500,
    },
    Scenario.PRESET_OPTIMISTIC: {
        "trend": "0.120000",
        "volatility": "0.140000",
        "noise_level": "0.018000",
        "market_shock": "0.040000",
        "currency_shock": "0.030000",
        "systematic_risk": "0.6000",
        "time_horizon": 365,
        "time_step": "1.0000",
        "iterations_count": 700,
    },
    Scenario.PRESET_PESSIMISTIC: {
        "trend": "-0.040000",
        "volatility": "0.220000",
        "noise_level": "0.030000",
        "market_shock": "-0.050000",
        "currency_shock": "-0.040000",
        "systematic_risk": "0.7000",
        "time_horizon": 365,
        "time_step": "1.0000",
        "iterations_count": 700,
    },
    Scenario.PRESET_STRESS: {
        "trend": "-0.080000",
        "volatility": "0.350000",
        "noise_level": "0.050000",
        "market_shock": "-0.120000",
        "currency_shock": "-0.100000",
        "systematic_risk": "0.8500",
        "time_horizon": 240,
        "time_step": "1.0000",
        "iterations_count": 1000,
    },
    Scenario.PRESET_CRISIS: {
        "trend": "-0.180000",
        "volatility": "0.500000",
        "noise_level": "0.080000",
        "market_shock": "-0.200000",
        "currency_shock": "-0.180000",
        "systematic_risk": "0.9500",
        "time_horizon": 180,
        "time_step": "1.0000",
        "iterations_count": 1200,
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
        fields = ["name", "description"]
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


class InstrumentSearchForm(forms.Form):
    query = forms.CharField(required=False)
    instrument_type = forms.CharField(required=False)
    currency = forms.CharField(required=False)
    price_min = forms.DecimalField(required=False, min_value=0, decimal_places=2, max_digits=15)
    price_max = forms.DecimalField(required=False, min_value=0, decimal_places=2, max_digits=15)
    portfolio = forms.IntegerField(required=False, min_value=1)


class ScenarioForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("preset", "market_shock", "currency_shock", "systematic_risk"):
            self.fields[field_name].required = False
        self.fields["preset"].initial = self.initial.get("preset", Scenario.PRESET_BASE)

    class Meta:
        model = Scenario
        fields = [
            "preset",
            "name",
            "description",
            "trend",
            "volatility",
            "noise_level",
            "market_shock",
            "currency_shock",
            "systematic_risk",
            "time_horizon",
            "time_step",
            "iterations_count",
        ]
        widgets = SCENARIO_FIELD_WIDGETS

    def clean(self):
        cleaned_data = super().clean()
        preset = cleaned_data.get("preset") or Scenario.PRESET_BASE
        cleaned_data["preset"] = preset
        self.cleaned_data["preset"] = preset
        if preset and preset != Scenario.PRESET_CUSTOM:
            preset_values = SCENARIO_PRESETS.get(preset, {})
            for field_name, value in preset_values.items():
                cleaned_data[field_name] = value
                self.cleaned_data[field_name] = value
        else:
            cleaned_data["market_shock"] = cleaned_data.get("market_shock") or Decimal("0")
            cleaned_data["currency_shock"] = cleaned_data.get("currency_shock") or Decimal("0")
            cleaned_data["systematic_risk"] = cleaned_data.get("systematic_risk") or Decimal("0.6500")
        return cleaned_data


class ScenarioManagementForm(forms.ModelForm):
    def __init__(self, *args, portfolios_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if portfolios_queryset is not None:
            self.fields["portfolio"].queryset = portfolios_queryset.order_by("name")
        for field_name in ("preset", "market_shock", "currency_shock", "systematic_risk"):
            self.fields[field_name].required = False
        self.fields["preset"].initial = self.initial.get("preset", Scenario.PRESET_BASE)

    class Meta:
        model = Scenario
        fields = [
            "portfolio",
            "preset",
            "name",
            "description",
            "trend",
            "volatility",
            "noise_level",
            "market_shock",
            "currency_shock",
            "systematic_risk",
            "time_horizon",
            "time_step",
            "iterations_count",
        ]
        widgets = SCENARIO_FIELD_WIDGETS

    def clean(self):
        cleaned_data = super().clean()
        preset = cleaned_data.get("preset") or Scenario.PRESET_BASE
        cleaned_data["preset"] = preset
        self.cleaned_data["preset"] = preset
        if preset and preset != Scenario.PRESET_CUSTOM:
            preset_values = SCENARIO_PRESETS.get(preset, {})
            for field_name, value in preset_values.items():
                cleaned_data[field_name] = value
                self.cleaned_data[field_name] = value
        else:
            cleaned_data["market_shock"] = cleaned_data.get("market_shock") or Decimal("0")
            cleaned_data["currency_shock"] = cleaned_data.get("currency_shock") or Decimal("0")
            cleaned_data["systematic_risk"] = cleaned_data.get("systematic_risk") or Decimal("0.6500")
        return cleaned_data

from django import forms

from riskapp.models import Instrument, Portfolio, PortfolioPosition, Scenario


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


class ScenarioForm(forms.ModelForm):
    class Meta:
        model = Scenario
        fields = [
            "name",
            "description",
            "trend",
            "volatility",
            "noise_level",
            "time_horizon",
            "time_step",
            "iterations_count",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
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

from decimal import Decimal

from django import forms

from riskapp.models import Instrument, Portfolio, PortfolioPosition


class PortfolioForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ["name", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class PortfolioPositionForm(forms.ModelForm):
    average_purchase_price = forms.DecimalField(
        max_digits=15,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
    )

    class Meta:
        model = PortfolioPosition
        fields = ["instrument", "quantity", "average_purchase_price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["instrument"].queryset = Instrument.objects.order_by("ticker")
        self.fields["quantity"].min_value = Decimal("0.0001")

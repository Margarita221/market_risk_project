from django.db import migrations


def normalize_instruments(apps, schema_editor):
    Instrument = apps.get_model("riskapp", "Instrument")

    stock_aliases = {"stock", "share", "shares", "equity", "equities"}
    bond_aliases = {"bond", "bonds"}
    etf_aliases = {"etf", "fund", "funds"}

    for instrument in Instrument.objects.all():
        normalized_type = (instrument.instrument_type or "").strip().lower()
        if normalized_type in stock_aliases:
            instrument.instrument_type = "stock"
        elif normalized_type in bond_aliases:
            instrument.instrument_type = "bond"
        elif normalized_type in etf_aliases:
            instrument.instrument_type = "etf"
        else:
            instrument.instrument_type = normalized_type or "stock"

        if not (instrument.sector or "").strip():
            if instrument.instrument_type == "bond":
                instrument.sector = "Bonds"
            elif instrument.instrument_type == "etf":
                instrument.sector = "Funds"
            else:
                instrument.sector = "Equities"

        instrument.save(update_fields=["instrument_type", "sector"])


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0017_scenario_interest_rate_shock"),
    ]

    operations = [
        migrations.RunPython(normalize_instruments, noop_reverse),
    ]

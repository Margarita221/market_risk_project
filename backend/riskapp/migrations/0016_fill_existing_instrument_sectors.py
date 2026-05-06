from django.db import migrations


def fill_existing_instrument_sectors(apps, schema_editor):
    Instrument = apps.get_model("riskapp", "Instrument")

    sector_by_type = {
        "stock": "Equities",
        "bond": "Bonds",
        "etf": "Funds",
    }

    for instrument in Instrument.objects.filter(sector=""):
        sector = sector_by_type.get(instrument.instrument_type, "")
        if sector:
            instrument.sector = sector
            instrument.save(update_fields=["sector"])


def clear_existing_instrument_sectors(apps, schema_editor):
    Instrument = apps.get_model("riskapp", "Instrument")
    Instrument.objects.filter(sector__in=["Equities", "Bonds", "Funds"]).update(sector="")


class Migration(migrations.Migration):

    dependencies = [
        ("riskapp", "0015_sector_shock_and_price_history"),
    ]

    operations = [
        migrations.RunPython(fill_existing_instrument_sectors, clear_existing_instrument_sectors),
    ]

from django.core.management.base import BaseCommand

from riskapp.models import Instrument, Portfolio
from riskapp.services.exchange_rates import normalize_currency_code, upsert_exchange_rates


class Command(BaseCommand):
    help = "Import official exchange rates from the Bank of Russia for currencies used in the project."

    def add_arguments(self, parser):
        parser.add_argument(
            "--currency",
            action="append",
            dest="currencies",
            help="Optional currency code to sync. Can be used multiple times.",
        )

    def handle(self, *args, **options):
        currencies = options["currencies"]
        if not currencies:
            currencies = sorted({
                normalize_currency_code(code)
                for code in Instrument.objects.values_list("currency", flat=True)
                if code
            } | {
                normalize_currency_code(code)
                for code in Portfolio.objects.values_list("base_currency", flat=True)
                if code
            })

        stats = upsert_exchange_rates(currencies=currencies)
        self.stdout.write(
            self.style.SUCCESS(
                f"Exchange rates synced. Created: {stats.created}, updated: {stats.updated}."
            )
        )

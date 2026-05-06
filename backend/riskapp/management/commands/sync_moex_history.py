from django.core.management.base import BaseCommand

from riskapp.models import Instrument
from riskapp.services.moex import sync_moex_price_history


class Command(BaseCommand):
    help = "Backfill historical MOEX prices into InstrumentPriceHistory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=180,
            help="Lookback window in days for MOEX history import.",
        )
        parser.add_argument(
            "--ticker",
            action="append",
            dest="tickers",
            help="Optional ticker filter. Can be used multiple times.",
        )
        parser.add_argument(
            "--replace-existing",
            action="store_true",
            help="Replace existing MOEX_HISTORY rows inside the selected window.",
        )

    def handle(self, *args, **options):
        tickers = options.get("tickers") or []
        instruments = None
        if tickers:
            instruments = Instrument.objects.filter(ticker__in=tickers).order_by("ticker")

        stats = sync_moex_price_history(
            instruments=instruments,
            lookback_days=options["days"],
            replace_existing=options["replace_existing"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"MOEX historical import completed. "
                f"Instruments processed: {stats.instruments}. "
                f"Imported rows: {stats.imported}. "
                f"Skipped rows: {stats.skipped}."
            )
        )

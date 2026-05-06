from django.core.management.base import BaseCommand

from riskapp.services.moex import sync_moex_instruments


class Command(BaseCommand):
    help = "Import or update real instruments from the official MOEX ISS API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            choices=["full", "existing-prices"],
            default="full",
            help="full imports the universe, existing-prices refreshes only already saved instruments.",
        )
        parser.add_argument(
            "--market",
            action="append",
            dest="markets",
            choices=["shares", "bonds", "etf"],
            help="MOEX market to import. Can be used multiple times.",
        )
        parser.add_argument(
            "--limit-total",
            type=int,
            default=None,
            help="Optional total limit across all selected markets.",
        )
        parser.add_argument(
            "--limit-per-market",
            type=int,
            default=None,
            help="Optional limit applied separately inside each selected market.",
        )

    def handle(self, *args, **options):
        markets = options["markets"] or ["shares", "bonds", "etf"]
        existing_only = options["mode"] == "existing-prices"
        stats = sync_moex_instruments(
            markets=markets,
            limit_total=options["limit_total"],
            limit_per_market=options["limit_per_market"],
            existing_only=existing_only,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"MOEX sync completed in mode '{options['mode']}'. "
                f"Created: {stats.created}, updated: {stats.updated}, skipped: {stats.skipped}."
            )
        )

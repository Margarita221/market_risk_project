from django.core.management.base import BaseCommand

from riskapp.services.moex import sync_moex_instruments


class Command(BaseCommand):
    help = "Import or update real instruments from the official MOEX ISS API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--market",
            action="append",
            dest="markets",
            choices=["shares", "bonds", "etf"],
            help="MOEX market to import. Can be used multiple times.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional limit for imported instruments.",
        )

    def handle(self, *args, **options):
        markets = options["markets"] or ["shares", "bonds"]
        stats = sync_moex_instruments(markets=markets, limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                f"MOEX sync completed. Created: {stats.created}, updated: {stats.updated}, skipped: {stats.skipped}."
            )
        )

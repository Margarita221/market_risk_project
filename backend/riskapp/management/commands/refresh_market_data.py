from django.core.management.base import BaseCommand

from riskapp.models import Instrument, Portfolio
from riskapp.services.exchange_rates import normalize_currency_code, upsert_exchange_rates
from riskapp.services.moex import snapshot_current_prices, sync_moex_instruments, sync_moex_price_history


PROFILE_DEFAULTS = {
    "daily-universe": {
        "markets": ["shares", "bonds", "etf"],
        "mode": "full",
        "limit_total": None,
        "limit_per_market": 400,
        "snapshot_source": None,
        "sync_exchange_rates": True,
    },
    "intraday-prices": {
        "markets": ["shares", "bonds", "etf"],
        "mode": "existing-prices",
        "limit_total": None,
        "limit_per_market": None,
        "snapshot_source": None,
        "sync_exchange_rates": True,
    },
    "history-snapshot": {
        "markets": [],
        "mode": None,
        "limit_total": None,
        "limit_per_market": None,
        "snapshot_source": "SCHEDULED",
        "sync_exchange_rates": False,
    },
    "historical-backfill": {
        "markets": [],
        "mode": None,
        "limit_total": None,
        "limit_per_market": None,
        "snapshot_source": None,
        "sync_exchange_rates": False,
        "history_days": 180,
        "replace_existing_history": False,
    },
}


class Command(BaseCommand):
    help = "Run one of the predefined market-data refresh profiles for the project."

    def add_arguments(self, parser):
        parser.add_argument(
            "--profile",
            choices=list(PROFILE_DEFAULTS.keys()),
            required=True,
            help="Predefined market-data profile to execute.",
        )
        parser.add_argument(
            "--market",
            action="append",
            dest="markets",
            choices=["shares", "bonds", "etf"],
            help="Optional market override for sync profiles.",
        )
        parser.add_argument(
            "--limit-total",
            type=int,
            default=None,
            help="Optional total sync limit override.",
        )
        parser.add_argument(
            "--limit-per-market",
            type=int,
            default=None,
            help="Optional per-market sync limit override.",
        )
        parser.add_argument(
            "--snapshot-source",
            default=None,
            help="Optional source label override for history snapshots.",
        )
        parser.add_argument(
            "--history-days",
            type=int,
            default=None,
            help="Optional lookback window for MOEX historical backfill.",
        )
        parser.add_argument(
            "--replace-existing-history",
            action="store_true",
            help="Replace existing MOEX_HISTORY rows inside the selected lookback window.",
        )

    def handle(self, *args, **options):
        profile_name = options["profile"]
        profile = PROFILE_DEFAULTS[profile_name]

        if profile_name == "history-snapshot":
            source = options["snapshot_source"] or profile["snapshot_source"]
            created = snapshot_current_prices(source=source)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Market data profile '{profile_name}' completed. "
                    f"Created {created} history rows with source '{source}'."
                )
            )
            return

        if profile_name == "historical-backfill":
            lookback_days = options["history_days"] or profile["history_days"]
            history_stats = sync_moex_price_history(
                lookback_days=lookback_days,
                replace_existing=options["replace_existing_history"] or profile.get("replace_existing_history", False),
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Market data profile '{profile_name}' completed. "
                    f"Instruments processed: {history_stats.instruments}. "
                    f"Imported rows: {history_stats.imported}. "
                    f"Skipped rows: {history_stats.skipped}."
                )
            )
            return

        markets = options["markets"] or profile["markets"]
        mode = profile["mode"]
        existing_only = mode == "existing-prices"
        limit_total = options["limit_total"] if options["limit_total"] is not None else profile["limit_total"]
        limit_per_market = (
            options["limit_per_market"]
            if options["limit_per_market"] is not None
            else profile["limit_per_market"]
        )

        stats = sync_moex_instruments(
            markets=markets,
            limit_total=limit_total,
            limit_per_market=limit_per_market,
            existing_only=existing_only,
        )

        exchange_rate_stats = None
        if profile.get("sync_exchange_rates"):
            currencies = sorted({
                normalize_currency_code(code)
                for code in Instrument.objects.values_list("currency", flat=True)
                if code
            } | {
                normalize_currency_code(code)
                for code in Portfolio.objects.values_list("base_currency", flat=True)
                if code
            })
            exchange_rate_stats = upsert_exchange_rates(currencies=currencies)

        self.stdout.write(
            self.style.SUCCESS(
                f"Market data profile '{profile_name}' completed in mode '{mode}'. "
                f"Markets: {', '.join(markets)}. "
                f"Created: {stats.created}, updated: {stats.updated}, skipped: {stats.skipped}."
                + (
                    f" Exchange rates created: {exchange_rate_stats.created}, updated: {exchange_rate_stats.updated}."
                    if exchange_rate_stats
                    else ""
                )
            )
        )

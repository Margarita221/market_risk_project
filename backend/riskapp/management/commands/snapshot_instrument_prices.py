from django.core.management.base import BaseCommand

from riskapp.services.moex import snapshot_current_prices


class Command(BaseCommand):
    help = "Create a history snapshot from current instrument prices."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default="MANUAL",
            help="Source label stored in history rows.",
        )

    def handle(self, *args, **options):
        source = options["source"]
        created = snapshot_current_prices(source=source)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created} instrument price history rows from current prices."
            )
        )

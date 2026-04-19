from django.core.management.base import BaseCommand, CommandError

from riskapp.models import Scenario
from riskapp.services.simulation import run_scenario_simulation


class Command(BaseCommand):
    help = "Run portfolio risk simulation for a scenario."

    def add_arguments(self, parser):
        parser.add_argument("scenario_id", type=int, help="Scenario ID to simulate.")
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Optional random seed for reproducible simulation results.",
        )

    def handle(self, *args, **options):
        scenario_id = options["scenario_id"]
        seed = options["seed"]

        if not Scenario.objects.filter(pk=scenario_id).exists():
            raise CommandError(f"Scenario with id={scenario_id} does not exist.")

        try:
            summary = run_scenario_simulation(scenario_id, seed=seed)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        result = summary.result
        self.stdout.write(self.style.SUCCESS(
            f"Simulation completed. Result ID: {result.id}, "
            f"expected return: {result.expected_return}, "
            f"volatility: {result.portfolio_volatility}, "
            f"final value: {result.final_value}, "
            f"max drawdown: {result.max_drawdown}"
        ))

        for metric in summary.metrics:
            self.stdout.write(f"- {metric.metric_name}: {metric.metric_value}")

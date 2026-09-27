import math
from dataclasses import dataclass


MIN_TRIALS = 30
MIN_LOWER_BOUND = 0.90
MAX_BALANCE_FRACTION = 0.05
Z_95 = 1.96


@dataclass(frozen=True)
class Opportunity:
    name: str
    source_url: str
    entry_cost: float | None
    success_return: float | None
    failure_return: float | None
    trials: int | None
    successes: int | None
    outcomes_verified: bool = False


def wilson_lower_bound(successes: int, trials: int) -> float:
    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("Los resultados históricos no son válidos.")

    proportion = successes / trials
    z_squared = Z_95 ** 2
    denominator = 1 + z_squared / trials

    numerator = (
        proportion
        + z_squared / (2 * trials)
        - Z_95
        * math.sqrt(
            proportion * (1 - proportion) / trials
            + z_squared / (4 * trials ** 2)
        )
    )

    return numerator / denominator


def evaluate_opportunity(
    opportunity: Opportunity,
    available_balance: float,
) -> dict:
    reasons = []

    if not opportunity.name.strip():
        reasons.append("Falta identificar la oportunidad.")

    if not opportunity.source_url.startswith(
        ("https://", "http://")
    ):
        reasons.append("Falta una fuente web identificable.")

    amounts = (
        opportunity.entry_cost,
        opportunity.success_return,
        opportunity.failure_return,
    )

    if any(
        amount is None
        or not math.isfinite(amount)
        or amount < 0
        for amount in amounts
    ):
        reasons.append(
            "Faltan costo y retornos medibles en ambos escenarios."
        )

    if not opportunity.outcomes_verified:
        reasons.append(
            "No hay resultados históricos verificados por el sistema."
        )

    trials = opportunity.trials
    successes = opportunity.successes

    if (
        trials is None
        or successes is None
        or trials < MIN_TRIALS
        or successes < 0
        or successes > trials
    ):
        reasons.append(
            f"Se requieren al menos {MIN_TRIALS} resultados "
            "históricos comparables."
        )

    if reasons:
        return {
            "decision": "pendiente_evidencia",
            "lower_bound": None,
            "expected_net": None,
            "reasons": reasons,
        }

    assert trials is not None
    assert successes is not None
    assert opportunity.entry_cost is not None
    assert opportunity.success_return is not None
    assert opportunity.failure_return is not None

    lower_bound = wilson_lower_bound(successes, trials)

    expected_return = (
        lower_bound * opportunity.success_return
        + (1 - lower_bound) * opportunity.failure_return
    )
    expected_net = expected_return - opportunity.entry_cost

    if lower_bound < MIN_LOWER_BOUND:
        reasons.append(
            "El límite inferior estimado es menor que el 90 %."
        )

    if expected_net <= 0:
        reasons.append(
            "El retorno esperado conservador no supera el costo."
        )

    if opportunity.entry_cost <= 0:
        reasons.append(
            "La operación no tiene un costo de entrada válido."
        )

    if (
        not math.isfinite(available_balance)
        or available_balance <= 0
        or opportunity.entry_cost
        > available_balance * MAX_BALANCE_FRACTION
    ):
        reasons.append(
            "La operación excede el 5 % del saldo disponible."
        )

    return {
        "decision": (
            "apta_para_simulacion"
            if not reasons
            else "pendiente_evidencia"
        ),
        "lower_bound": round(lower_bound, 4),
        "expected_net": round(expected_net, 2),
        "reasons": reasons,
    }
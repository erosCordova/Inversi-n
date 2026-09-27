from typing import TypedDict

import httpx
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph

from .football_analysis import analyze_favorite_strategy
from .future_football import get_future_matches
from .history import save_exploration
from .market_analysis import analyze_market
from .market_data import MARKETS
from .paper_trading import (
    place_paper_bet,
    rule_is_valid,
    settle_paper_bets,
)


class AgentState(TypedDict):
    query: str
    source: str
    explorer: str
    reviewer: str
    decision: str
    reasons: list[str]
    steps: list[str]
    markets: list[dict]
    football: dict | None
    football_by_division: dict[str, dict]
    future_matches: list[dict]
    settled_bets: list[dict]
    placed_bets: list[dict]
    errors: list[str]


def collect_data(state: AgentState) -> dict:
    markets = []
    errors = []
    settled_bets = []

    try:
        settled_bets = settle_paper_bets()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        errors.append(
            "No se pudieron actualizar algunas apuestas: "
            f"{type(error).__name__}."
        )

    for market in MARKETS:
        try:
            markets.append(analyze_market(market))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            errors.append(
                f"{market}: datos no disponibles "
                f"({type(error).__name__})."
            )

    future_matches = []

    try:
        future_matches = get_future_matches()["matches"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        errors.append(
            "Partidos futuros: datos no disponibles "
            f"({type(error).__name__})."
        )

    divisions = ["E0"]

    for match in future_matches:
        division = match.get("division")

        if division and division not in divisions:
            divisions.append(division)

        if len(divisions) >= 4:
            break

    football_by_division = {}

    for division in divisions:
        try:
            football_by_division[division] = (
                analyze_favorite_strategy(division)
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            errors.append(
                f"Historial de fútbol {division}: "
                f"datos no disponibles ({type(error).__name__})."
            )

    return {
        "markets": markets,
        "football": football_by_division.get("E0"),
        "football_by_division": football_by_division,
        "future_matches": future_matches,
        "settled_bets": settled_bets,
        "errors": errors,
        "steps": [*state["steps"], "consultar_datos"],
    }


def reason_for_match(
    match: dict,
    analyses: dict[str, dict],
) -> str:
    analysis = analyses.get(match.get("division", ""))

    if analysis is None:
        return (
            "sin apuesta: falta obtener el historial "
            "de esta liga."
        )

    training = analysis["training"]
    validation = analysis["validation"]

    if training["bets"] < 30:
        return (
            "sin apuesta: solo hay "
            f"{training['bets']} casos históricos de esta "
            "regla en la liga; se necesitan al menos 30."
        )

    if training["net_units"] <= 0:
        return (
            "sin apuesta: la regla perdió "
            f"{abs(training['net_units']):.2f} unidades "
            "en el historial de esta liga."
        )

    if validation["bets"] < 30:
        return (
            "sin apuesta: solo hay "
            f"{validation['bets']} casos de validación; "
            "se necesitan al menos 30."
        )

    lower = validation["wilson_lower_bound"]

    if lower is None or lower < 0.90:
        return (
            "sin apuesta: la validación no respalda "
            "el umbral exigido del 90 %."
        )

    if validation["net_units"] <= 0:
        return (
            "sin apuesta: la regla perdió dinero "
            "en la validación."
        )

    if min(match["odds"].values()) > 1.30:
        return (
            "sin apuesta: ninguna cuota del partido "
            "cumple la regla."
        )

    return (
        "La regla pasó el filtro histórico. "
        "Se intentará registrar una apuesta simulada."
    )


def evaluate_data(state: AgentState) -> dict:
    lines = []
    candidates = []
    placed_bets = []

    for analysis in state["markets"]:
        market = analysis["market"]

        lines.append(
            f"{market} | {analysis['first_date']} a "
            f"{analysis['last_date']} | fuente: "
            f"{analysis['source']}"
        )

        for scenario in analysis["scenarios"]:
            days = scenario["holding_days"]
            lower = scenario["wilson_lower_bound"]
            average = scenario["average_net_return_pct"]

            lines.append(
                f"  {days} días: "
                f"{scenario['gains']}/{scenario['trials']} "
                f"con ganancia; límite histórico "
                f"{lower:.1%}; retorno promedio "
                f"{average:.2f}%."
            )

            if lower >= 0.90 and average > 0:
                candidates.append(
                    f"{market}, plazo de {days} días"
                )

    for analysis in state["football_by_division"].values():
        lines.append(
            f"Fútbol | {analysis['league']} | "
            f"fuente: {analysis['source']}"
        )
        lines.append(f"  Regla: {analysis['rule']}")

        for label, season in (
            ("Historial", analysis["training"]),
            ("Validación", analysis["validation"]),
        ):
            rate = season["win_rate"]
            rate_text = (
                f"{rate:.1%}"
                if rate is not None
                else "sin datos"
            )

            lines.append(
                f"  {label} {season['season']}: "
                f"{season['wins']}/{season['bets']} "
                f"aciertos ({rate_text}); "
                f"resultado neto "
                f"{season['net_units']:+.2f} unidades."
            )

    lines.append("PARTIDOS FUTUROS")

    if state["future_matches"]:
        for match in state["future_matches"][:12]:
            odds = match["odds"]
            analysis = state[
                "football_by_division"
            ].get(match["division"])
            reason = reason_for_match(
                match,
                state["football_by_division"],
            )

            if analysis and rule_is_valid(analysis):
                try:
                    result = place_paper_bet(match, analysis)

                    if result["placed"]:
                        placed_bets.append(result)
                        reason = (
                            "apuesta simulada registrada: "
                            f"S/ {result['stake']:.2f} "
                            f"al resultado {result['selection']} "
                            f"con cuota {result['odds']:.2f}."
                        )
                    else:
                        reason = result["reason"]
                except (ValueError, KeyError, TypeError) as error:
                    reason = (
                        "sin apuesta: no se pudo registrar "
                        f"({type(error).__name__})."
                    )
                    lines.append(reason)

            lines.append(
                f"Partido: {match['date']} | "
                f"{match['league']} | "
                f"{match['home']} vs {match['away']} | "
                f"cuotas local {odds['H']:.2f}, "
                f"empate {odds['D']:.2f}, "
                f"visitante {odds['A']:.2f} | "
                f"{reason}"
            )
    else:
        lines.append(
            "No hay partidos futuros con cuotas completas."
        )

    lines.extend(state["errors"])

    if placed_bets:
        decision = "apuesta_simulada_abierta"
        reasons = [
            f"Se registraron {len(placed_bets)} "
            "apuestas simuladas.",
            "Los resultados se actualizarán cuando "
            "aparezcan en el historial de partidos.",
        ]
    elif (
        not state["markets"]
        and not state["football_by_division"]
        and not state["future_matches"]
    ):
        decision = "sin_datos"
        reasons = [
            "No se pudieron obtener datos de las fuentes."
        ]
    elif candidates:
        decision = "pendiente_validacion"
        reasons = [
            "Pasaron el primer filtro histórico: "
            + ", ".join(candidates)
            + ".",
            "Todavía no hay una operación actual "
            "validada para usar capital.",
        ]
    else:
        decision = "sin_oportunidad_verificada"
        reasons = [
            "Ninguna regla analizada demostró "
            "el umbral exigido de ganancia neta.",
            "El agente conservó el capital simulado.",
        ]

    return {
        "source": "\n".join(lines),
        "decision": decision,
        "reasons": reasons,
        "placed_bets": placed_bets,
        "steps": [*state["steps"], "evaluar_riesgo"],
    }


def save_result(state: AgentState) -> dict:
    save_exploration(
        query=state["query"],
        sources=state["source"],
        explorer=state["explorer"],
        reviewer=state["reviewer"],
        decision=state["decision"],
        reasons=state["reasons"],
    )

    return {
        "steps": [*state["steps"], "guardar"],
    }


builder = StateGraph(AgentState)

builder.add_node("consultar_datos", RunnableLambda(collect_data))
builder.add_node("evaluar_riesgo", RunnableLambda(evaluate_data))
builder.add_node("guardar", RunnableLambda(save_result))

builder.add_edge(START, "consultar_datos")
builder.add_edge(
    "consultar_datos",
    "evaluar_riesgo",
)
builder.add_edge("evaluar_riesgo", "guardar")
builder.add_edge("guardar", END)

autonomous_graph = builder.compile()


def run_autonomous_cycle() -> dict:
    return autonomous_graph.invoke({
        "query": (
            "Evaluación autónoma de mercados: "
            "criptomonedas y fútbol"
        ),
        "source": "",
        "explorer": "",
        "reviewer": "",
        "decision": "",
        "reasons": [],
        "steps": [],
        "markets": [],
        "football": None,
        "football_by_division": {},
        "future_matches": [],
        "settled_bets": [],
        "placed_bets": [],
        "errors": [],
    })
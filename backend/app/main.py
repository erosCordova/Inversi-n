import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .autonomy import run_autonomous_cycle
from .graph import run_graph
from .history import list_explorations
from .live_paper import (
    experiment_status,
    run_experiment_cycle,
)
from .live_scores import get_live_matches
from .storage import (
    close_investment,
    get_portfolio,
    open_investment,
)


logger = logging.getLogger("replikers.autonomy")
status_lock = threading.Lock()

agent_status = {
    "enabled": True,
    "running": False,
    "last_query": None,
    "last_decision": None,
    "last_finished_at": None,
    "last_error": None,
    "experiment_last_action": None,
    "experiment_last_error": None,
}


def interval_seconds() -> int:
    try:
        value = int(
            os.getenv(
                "AUTO_INTERVAL_SECONDS",
                "3600",
            )
        )
    except ValueError:
        value = 3600

    return max(300, value)


def autonomous_worker(
    stop_event: threading.Event,
) -> None:
    if stop_event.wait(10):
        return

    while not stop_event.is_set():
        with status_lock:
            agent_status["running"] = True
            agent_status["last_error"] = None
            agent_status["experiment_last_error"] = None

        try:
            experiment = run_experiment_cycle()
            bet = experiment["placed"]

            if bet["placed"]:
                action = (
                    f"Simulación: {bet['match']} | "
                    f"S/ {bet['amount']:.2f} | "
                    f"cuota {bet['odds']:.2f}"
                )
            else:
                action = bet["reason"]

            with status_lock:
                agent_status[
                    "experiment_last_action"
                ] = action

            logger.info(
                "Ciclo experimental: %s",
                action,
            )

        except Exception as error:
            logger.exception(
                "Falló el experimento"
            )

            with status_lock:
                agent_status[
                    "experiment_last_error"
                ] = (
                    f"{type(error).__name__}: {error}"
                )

        try:
            result = run_autonomous_cycle()

            with status_lock:
                agent_status["last_query"] = (
                    result["query"]
                )
                agent_status["last_decision"] = (
                    result["decision"]
                )
                agent_status["last_finished_at"] = (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )

            logger.info(
                "Ciclo autónomo terminado: %s",
                result["decision"],
            )

        except Exception as error:
            logger.exception(
                "Falló el ciclo autónomo"
            )

            with status_lock:
                agent_status["last_error"] = (
                    f"{type(error).__name__}: {error}"
                )
                agent_status["last_finished_at"] = (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )

        finally:
            with status_lock:
                agent_status["running"] = False

        stop_event.wait(
            interval_seconds()
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = threading.Event()

    enabled = (
        os.getenv(
            "AUTO_ENABLED",
            "true",
        ).lower() == "true"
    )

    with status_lock:
        agent_status["enabled"] = enabled

    worker = None

    if enabled:
        worker = threading.Thread(
            target=autonomous_worker,
            args=(stop_event,),
            name="replikers-autonomy",
            daemon=True,
        )
        worker.start()

    try:
        yield
    finally:
        stop_event.set()

        if worker is not None:
            worker.join(timeout=2)


app = FastAPI(
    title="Replikers API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class RunRequest(BaseModel):
    query: str = Field(
        min_length=3,
        max_length=200,
    )


class OpenInvestmentRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=120,
    )
    amount: float = Field(
        ge=0.01,
        allow_inf_nan=False,
    )


class CloseInvestmentRequest(BaseModel):
    returned_amount: float = Field(
        ge=0,
        allow_inf_nan=False,
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "framework": (
            "FastAPI + LangChain + LangGraph"
        ),
        "mode": "simulacion",
    }


@app.get("/api/agent/status")
def get_agent_status():
    with status_lock:
        return {
            **agent_status,
            "interval_seconds": (
                interval_seconds()
            ),
        }


@app.get("/api/explorations")
def get_explorations():
    return list_explorations(limit=20)


@app.get("/api/portfolio")
def portfolio():
    return get_portfolio()


@app.get("/api/live-paper")
def live_paper():
    return experiment_status()


@app.get("/api/live-matches")
def live_matches():
    try:
        return get_live_matches()
    except (
        httpx.HTTPError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        ) from error


@app.post("/api/investments")
def create_investment(
    request: OpenInvestmentRequest,
):
    try:
        return open_investment(
            request.name,
            request.amount,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@app.post("/api/investments/{investment_id}/close")
def finish_investment(
    investment_id: int,
    request: CloseInvestmentRequest,
):
    try:
        return close_investment(
            investment_id,
            request.returned_amount,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@app.post("/api/run")
def run(request: RunRequest):
    return run_graph(request.query)
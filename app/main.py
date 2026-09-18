from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI

from app.errors import register_exception_handlers
from app.llm_interpreter import NoteInterpreter, OpenAIInterpreter
from app.schemas import (
    Battery,
    DirectiveInterpretation,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)
from app.service import build_contract_response


app = FastAPI(
    title="GridWise LLM Energy Optimizer",
    version="1.0.0",
    description="LLM-assisted GridWise energy scheduling and validation service.",
)
register_exception_handlers(app)


class EnvironmentInterpreter:
    """Delay provider configuration until after request validation succeeds.

    The provider client is built once on the first successful configuration and
    reused for subsequent requests. This avoids reloading the environment and
    reconstructing the HTTP client on every call, which keeps per-request latency
    (and therefore p95) dominated by the model round-trip rather than setup cost.
    Configuration errors still surface per request as a controlled 503 because
    the delegate is only cached after it is built successfully.
    """

    def __init__(self) -> None:
        self._delegate: NoteInterpreter | None = None

    def interpret_notes(
        self, notes: list[str], battery: Battery
    ) -> list[DirectiveInterpretation]:
        if self._delegate is None:
            self._delegate = OpenAIInterpreter.from_env()
        return self._delegate.interpret_notes(notes, battery)


@lru_cache
def get_interpreter() -> NoteInterpreter:
    return EnvironmentInterpreter()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
def optimize_energy(
    payload: OptimizeEnergyRequest,
    interpreter: Annotated[NoteInterpreter, Depends(get_interpreter)],
) -> OptimizeEnergyResponse:
    return build_contract_response(payload, interpreter)

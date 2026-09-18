from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI

from app.errors import register_exception_handlers
from app.llm_interpreter import OpenAIInterpreter
from app.schemas import OptimizeEnergyRequest, OptimizeEnergyResponse
from app.service import build_contract_response


app = FastAPI(
    title="GridWise LLM Energy Optimizer",
    version="0.2.0",
    description="Module 2 LLM interpreter for the BUP CSE Fest 2026 GridWise challenge.",
)
register_exception_handlers(app)


@lru_cache
def get_interpreter() -> OpenAIInterpreter:
    return OpenAIInterpreter.from_env()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
def optimize_energy(
    payload: OptimizeEnergyRequest,
    interpreter: Annotated[OpenAIInterpreter, Depends(get_interpreter)],
) -> OptimizeEnergyResponse:
    return build_contract_response(payload, interpreter)

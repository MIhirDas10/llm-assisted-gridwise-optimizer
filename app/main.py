from fastapi import FastAPI

from app.errors import register_exception_handlers
from app.schemas import OptimizeEnergyRequest, OptimizeEnergyResponse
from app.service import build_contract_response


app = FastAPI(
    title="GridWise LLM Energy Optimizer",
    version="0.1.0",
    description="Module 1 API contract for the BUP CSE Fest 2026 GridWise challenge.",
)
register_exception_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
def optimize_energy(payload: OptimizeEnergyRequest) -> OptimizeEnergyResponse:
    return build_contract_response(payload)

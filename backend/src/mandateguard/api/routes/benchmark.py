"""Read-only reproducible MandateBench report."""

from fastapi import APIRouter

from mandateguard.benchmark.runner import run_benchmark

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


@router.get("/report")
def benchmark_report() -> dict[str, object]:
    return run_benchmark()

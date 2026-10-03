"""P0 指标：先只打日志，P6 再接 Langfuse / Prometheus。"""
import logging
import time

logger = logging.getLogger("agent.metrics")


def log_usage(trace_id: str, model: str, tokens: int, latency_ms: int, **extra) -> None:
    logger.info(
        "usage trace=%s model=%s tokens=%d latency_ms=%d %s",
        trace_id,
        model,
        tokens,
        latency_ms,
        " ".join(f"{k}={v}" for k, v in extra.items()),
    )


class Timer:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    def ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)

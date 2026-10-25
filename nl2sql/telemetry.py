"""OpenTelemetry setup → OTLP → Arize Phoenix.

Safe to call even when Phoenix isn't running: exporter failures are swallowed so
telemetry never takes down a request. LiteLLM LLM spans are auto-captured via
OpenInference; we add spans around the non-LLM steps ourselves.
"""

from __future__ import annotations

from functools import lru_cache

from nl2sql.config import get_settings

_INITIALISED = False


def init_telemetry() -> None:
    global _INITIALISED
    if _INITIALISED:
        return
    _INITIALISED = True
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        s = get_settings()
        provider = TracerProvider(resource=Resource.create({"service.name": s.otel_service_name}))
        exporter = OTLPSpanExporter(endpoint=f"{s.otlp_endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # auto-instrument LiteLLM calls (per-agent spans with token/cost attrs)
        try:
            from openinference.instrumentation.litellm import LiteLLMInstrumentor

            LiteLLMInstrumentor().instrument(tracer_provider=provider)
        except Exception:  # noqa: BLE001 - optional instrumentor
            pass
    except Exception:  # noqa: BLE001 - telemetry must never break the app
        pass


@lru_cache
def tracer():
    from opentelemetry import trace

    return trace.get_tracer("nl2sql")

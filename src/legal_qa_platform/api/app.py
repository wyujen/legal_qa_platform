"""REST application boundary for chat, retrieval, feedback, and probes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from legal_qa_platform.api.schemas import (
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    ReadinessResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from legal_qa_platform.config import RuntimeSettings
from legal_qa_platform.container import ApplicationContainer
from legal_qa_platform.domain.qa import ChatRequest, ChatResponse
from legal_qa_platform.errors import (
    ConfigurationError,
    ExternalServiceError,
    LegalQaError,
    ResponseValidationError,
)
from legal_qa_platform.services.normalization import normalize_text


def _container(request: Request) -> ApplicationContainer:
    value = getattr(request.app.state, "container", None)
    if not isinstance(value, ApplicationContainer):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application dependencies are unavailable.",
        )
    return value


def create_app(
    container: ApplicationContainer | None = None,
    *,
    settings: RuntimeSettings | None = None,
    manage_lifecycle: bool = True,
) -> FastAPI:
    if container is not None and settings is not None:
        raise ValueError("Pass either container or settings, not both.")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        selected = container or ApplicationContainer.build(settings=settings)
        if manage_lifecycle:
            await selected.open()
        app.state.container = selected
        try:
            yield
        finally:
            if manage_lifecycle:
                await selected.close()

    application = FastAPI(
        title="legal_qa_platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's default body includes the rejected input. Return only an
        # allowlisted field/category summary so request text is never echoed.
        fields: list[dict[str, str]] = []
        for item in exc.errors():
            location = item.get("loc", ())
            field = ".".join(
                str(part)
                for part in location
                if str(part) not in {"body", "query", "path"}
            )
            fields.append(
                {
                    "field": field or "request",
                    "category": str(item.get("type", "invalid")),
                }
            )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "Request validation failed.",
                "category": "request_validation",
                "fields": fields,
            },
        )

    @application.exception_handler(ConfigurationError)
    async def configuration_error(
        _request: Request, exc: ConfigurationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": str(exc), "category": "configuration"},
        )

    @application.exception_handler(ExternalServiceError)
    async def external_error(
        _request: Request, exc: ExternalServiceError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": f"{exc.service} is unavailable.",
                "category": exc.category,
            },
        )

    @application.exception_handler(ResponseValidationError)
    async def model_validation_error(
        _request: Request, _exc: ResponseValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": "Model response validation failed.",
                "category": "response_validation",
            },
        )

    @application.exception_handler(LegalQaError)
    async def application_error(_request: Request, exc: LegalQaError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Application request failed.",
                "category": type(exc).__name__,
            },
        )

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="legal_qa_platform")

    @application.get(
        "/ready",
        response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse}},
    )
    async def ready(request: Request, response: Response) -> ReadinessResponse:
        checks = await _container(request).readiness()
        ready_now = all(checks.values())
        if not ready_now:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="ready" if ready_now else "not_ready",
            checks=checks,
        )

    @application.post(
        "/api/v1/chat",
        response_model=ChatResponse,
        responses={
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
        services = _container(request)
        if payload.profile != services.profile.name:
            raise HTTPException(status_code=404, detail="Unknown RAG profile.")
        try:
            return await services.qa.answer(
                payload.message,
                conversation_id=payload.conversation_id,
            )
        except ValueError as exc:
            message = str(exc)
            if "not found" in message:
                raise HTTPException(status_code=404, detail=message) from None
            if "not active" in message:
                raise HTTPException(status_code=409, detail=message) from None
            raise HTTPException(status_code=422, detail=message) from None

    @application.post(
        "/api/v1/retrieve",
        response_model=RetrieveResponse,
        responses={503: {"model": ErrorResponse}},
    )
    async def retrieve(
        request: Request,
        payload: RetrieveRequest,
    ) -> RetrieveResponse:
        services = _container(request)
        if payload.profile != services.profile.name:
            raise HTTPException(status_code=404, detail="Unknown RAG profile.")
        started = perf_counter()
        normalized = normalize_text(payload.message)
        stage_latencies: dict[str, float] = {}
        results = await services.retrieval.retrieve(
            normalized,
            stage_latencies_ms=stage_latencies,
        )
        duration_ms = max(0, round((perf_counter() - started) * 1000))
        stage_latencies["total"] = float(duration_ms)
        return RetrieveResponse(
            question=payload.message,
            normalized_question=normalized,
            profile=services.profile.name,
            retrieval_results=results,
            stage_latencies_ms=stage_latencies,
            duration_ms=duration_ms,
        )

    @application.post(
        "/api/v1/feedback",
        response_model=FeedbackResponse,
        responses={503: {"model": ErrorResponse}},
    )
    async def feedback(
        request: Request,
        payload: FeedbackRequest,
    ) -> FeedbackResponse:
        services = _container(request)
        try:
            query_id = UUID(payload.query_id)
            conversation_id = (
                UUID(payload.conversation_id) if payload.conversation_id else None
            )
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="query_id and conversation_id must be UUIDs.",
            ) from None
        if payload.rating not in {None, -1, 1}:
            raise HTTPException(status_code=422, detail="rating must be -1 or 1.")
        if (
            payload.rating is None
            and payload.category is None
            and payload.comment is None
        ):
            raise HTTPException(status_code=422, detail="Feedback is empty.")
        feedback_id = await services.repository.save_feedback(
            query_id=query_id,
            conversation_id=conversation_id,
            rating=payload.rating,
            category=payload.category,
            comment=payload.comment,
        )
        return FeedbackResponse(feedback_id=str(feedback_id))

    return application


app = create_app()

__all__ = ["app", "create_app"]

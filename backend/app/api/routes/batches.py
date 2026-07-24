"""Batch processing routes.

POST /api/v1/batches/upload     — Upload CSV file for sentiment analysis.
GET  /api/v1/batches            — Paginated batch history for the user.
GET  /api/v1/batches/{id}/status   — Batch processing status.
GET  /api/v1/batches/{id}/summary  — Sentiment distribution summary.
GET  /api/v1/batches/{id}/keywords — Top 20 keywords.
GET  /api/v1/batches/{id}/feedbacks — Paginated feedbacks with optional keyword filter.
GET  /api/v1/batches/{id}/triage   — Urgent feedbacks (score < -0.7).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status

from app.api.middleware.auth_middleware import get_current_user
from app.core.interfaces.auth_provider import AuthToken
from app.core.interfaces.nlp_provider import INLPProvider
from app.core.interfaces.storage_provider import IStorageProvider
from app.core.models.schemas import (
    BatchStatusResponse,
    BatchSummaryResponse,
    KeywordResponse,
    PaginatedResponse,
)
from app.core.services.batch_service import BatchService
from app.dependencies import get_nlp_provider, get_storage_provider

router = APIRouter(prefix="/batches", tags=["batches"])

TRIAGE_THRESHOLD: float = -0.7


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_batch(
    file: UploadFile,
    current_user: AuthToken = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage_provider),
    nlp: INLPProvider = Depends(get_nlp_provider),
) -> dict[str, str]:
    """Upload a CSV file for batch sentiment analysis.

    Validates the file and starts processing. Returns 202 with batch_id.
    Returns 422 if CSV validation fails.
    """
    filename = file.filename or "upload.csv"
    file_content = await file.read()

    batch_service = BatchService(nlp_provider=nlp, storage_provider=storage)

    try:
        result = batch_service.process_batch(
            user_id=current_user.user_id,
            filename=filename,
            file_content=file_content,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    return {"batch_id": result.batch_id, "message": "Archivo recibido y procesado"}


@router.get("", response_model=PaginatedResponse)
async def list_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    current_user: AuthToken = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage_provider),
) -> PaginatedResponse:
    """Return paginated batch history for the authenticated user.

    Batches are ordered by upload date descending (most recent first).
    """
    data = storage.get_user_batches(
        user_id=current_user.user_id, page=page, page_size=page_size
    )
    return PaginatedResponse(
        items=data["items"],
        total=data["total"],
        page=data["page"],
        page_size=data["page_size"],
        total_pages=data["total_pages"],
    )


@router.get("/{batch_id}/status", response_model=BatchStatusResponse)
async def get_batch_status(
    batch_id: str,
    current_user: AuthToken = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage_provider),
) -> BatchStatusResponse:
    """Return the processing status of a specific batch."""
    data = storage.get_user_batches(
        user_id=current_user.user_id, page=1, page_size=1000
    )
    batch_info = next(
        (b for b in data["items"] if b["id"] == batch_id), None
    )
    if batch_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lote no encontrado",
        )

    return BatchStatusResponse(
        batch_id=batch_info["id"],
        status=batch_info["status"],
        total_rows=batch_info["total_rows"],
        processed_rows=batch_info["processed_rows"],
        error_rows=batch_info["error_rows"],
        uploaded_at=batch_info["uploaded_at"],
        completed_at=batch_info.get("completed_at"),
    )


@router.get("/{batch_id}/summary", response_model=BatchSummaryResponse)
async def get_batch_summary(
    batch_id: str,
    current_user: AuthToken = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage_provider),
) -> BatchSummaryResponse:
    """Return the sentiment distribution summary for a batch."""
    _verify_batch_ownership(storage, current_user.user_id, batch_id)

    data = storage.get_batch_summary(batch_id)
    return BatchSummaryResponse(
        batch_id=data["batch_id"],
        total_feedbacks=data["total_feedbacks"],
        sentiment_distribution=data["sentiment_distribution"],
        sentiment_percentages=data["sentiment_percentages"],
        urgent_count=data["urgent_count"],
    )


@router.get("/{batch_id}/keywords", response_model=list[KeywordResponse])
async def get_batch_keywords(
    batch_id: str,
    current_user: AuthToken = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage_provider),
) -> list[KeywordResponse]:
    """Return top 20 keywords for a batch, sorted by frequency descending."""
    _verify_batch_ownership(storage, current_user.user_id, batch_id)

    keywords = storage.get_top_keywords(batch_id, limit=20)
    return [KeywordResponse(word=kw["word"], frequency=kw["frequency"]) for kw in keywords]


@router.get("/{batch_id}/feedbacks", response_model=PaginatedResponse)
async def get_batch_feedbacks(
    batch_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: Optional[str] = Query(default=None),
    current_user: AuthToken = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage_provider),
) -> PaginatedResponse:
    """Return paginated feedbacks for a batch.

    Supports optional keyword filter. Without keyword, returns all feedbacks.
    """
    _verify_batch_ownership(storage, current_user.user_id, batch_id)

    if keyword:
        data = storage.get_feedbacks_by_keyword(
            batch_id=batch_id, keyword=keyword, page=page, page_size=page_size
        )
    else:
        data = storage.get_batch_feedbacks(
            batch_id=batch_id, page=page, page_size=page_size
        )

    return PaginatedResponse(
        items=data["items"],
        total=data["total"],
        page=data["page"],
        page_size=data["page_size"],
        total_pages=data["total_pages"],
    )


@router.get("/{batch_id}/triage", response_model=PaginatedResponse)
async def get_batch_triage(
    batch_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    current_user: AuthToken = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage_provider),
) -> PaginatedResponse:
    """Return urgent feedbacks (score < -0.7), ordered by score ascending."""
    _verify_batch_ownership(storage, current_user.user_id, batch_id)

    data = storage.get_urgent_feedbacks(
        batch_id=batch_id,
        threshold=TRIAGE_THRESHOLD,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        items=data["items"],
        total=data["total"],
        page=data["page"],
        page_size=data["page_size"],
        total_pages=data["total_pages"],
    )


def _verify_batch_ownership(
    storage: IStorageProvider, user_id: str, batch_id: str
) -> None:
    """Verify that the batch belongs to the authenticated user.

    Raises 404 if the batch is not found in the user's batches.
    """
    data = storage.get_user_batches(user_id=user_id, page=1, page_size=1000)
    batch_exists = any(b["id"] == batch_id for b in data["items"])
    if not batch_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lote no encontrado",
        )

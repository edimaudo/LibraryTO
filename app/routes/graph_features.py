"""Read-only endpoints for the Relate Explorer and area-normalized activity."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.graph_enhancements import GraphUnavailable, activity_intensity_payload, explorer_snapshot, inspect_graph_nodes

router = APIRouter()


@router.get("/relate/explorer")
def relate_explorer(branch_codes: str = Query(default="", max_length=250)):
    codes = list(dict.fromkeys(code.strip() for code in branch_codes.split(",") if code.strip()))[:5]
    try:
        return explorer_snapshot(codes)
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"The Relate graph could not be explored ({type(exc).__name__}).") from exc


@router.get("/relate/inspect")
def relate_inspect_nodes(
    label: str = Query(min_length=1, max_length=120),
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=50000),
):
    try:
        return inspect_graph_nodes(label, search, limit, offset)
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"The selected graph nodes could not be inspected ({type(exc).__name__}).") from exc


@router.get("/activity-intensity")
def activity_intensity(branch_codes: str = Query(default="", max_length=250)):
    codes = list(dict.fromkeys(code.strip() for code in branch_codes.split(",") if code.strip()))[:5]
    try:
        return activity_intensity_payload(codes)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Activity intensity could not be calculated ({type(exc).__name__}).") from exc

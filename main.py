"""LibraryTO FastAPI application."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import DATA_DIR, ROOT
from app.services.analytics import (
    METRICS,
    branch_detail,
    branch_forecasts,
    compare,
    overview,
    recommend_events,
    event_filter_options,
)
from app.services.data_store import (
    branch_records,
    dataset_status,
    event_records,
    observations,
)
from app.services.relate import RelateUnavailable, ask as relate_ask, graph_status

app = FastAPI(
    title="LibraryTO",
    version="1.0.0",
    description="Explore Toronto Public Library branch information, activity and programs.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    branch_code: str | None = Field(default=None, max_length=40)


def _page(request: Request, active: str, title: str):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"active": active, "title": title},
    )


def _is_data_route(path: str) -> bool:
    """Return whether a route is intended to return structured data."""
    return (
        path in {"/overview", "/branches", "/comparisons/data", "/search", "/ask", "/status", "/health", "/events/options"}
        or path.startswith(("/branches/", "/events/recommendations", "/exports/"))
    )


@app.middleware("http")
async def read_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.method == "GET" and _is_data_route(request.url.path) and response.status_code == 200:
        response.headers.setdefault("Cache-Control", "public, max-age=300, stale-while-revalidate=600")
    return response


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    if _is_data_route(request.url.path):
        return JSONResponse(
            {"error": exc.detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request, "404.html", {"title": "Page not found"}, status_code=404
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {"title": "Something went wrong", "status_code": exc.status_code},
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    if _is_data_route(request.url.path):
        return JSONResponse({"error": "The request contains invalid values."}, status_code=422)
    return templates.TemplateResponse(
        request, "error.html", {"title": "Invalid request", "status_code": 422}, status_code=422
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return _page(request, "overview", "Overview")


@app.get("/branch-insights", response_class=HTMLResponse)
async def branch_page(request: Request):
    return _page(request, "branches", "Branch Insights")


@app.get("/comparisons", response_class=HTMLResponse)
async def comparisons_page(request: Request):
    return _page(request, "comparisons", "Branch Comparisons")


@app.get("/programs-events", response_class=HTMLResponse)
async def events_page(request: Request):
    return _page(request, "events", "Programs & Events")


@app.get("/overview")
async def overview_data():
    return overview()


@app.get("/branches")
async def list_branches():
    return branch_records()


@app.get("/branches/{code}")
async def branch_profile(code: str):
    result = branch_detail(code)
    if result is None:
        raise HTTPException(status_code=404, detail="Branch not found.")
    return result


@app.get("/branches/{code}/forecasts")
async def branch_forecast_data(code: str):
    result = branch_forecasts(code)
    if result is None:
        raise HTTPException(status_code=404, detail="Branch not found.")
    return result


@app.get("/comparisons/data")
async def comparison_data(branches: str = Query(default="", max_length=500)):
    codes = [item.strip() for item in branches.split(",") if item.strip()][:6]
    return compare(codes)


@app.get("/events/options")
async def events_options():
    return event_filter_options()


@app.get("/events/recommendations")
async def event_recommendations_data(
    interest: str = Query(default="", max_length=120),
    audience: str = Query(default="", max_length=80),
    language: str = Query(default="", max_length=80),
    event_type: str = Query(default="", max_length=80),
    branch: str = Query(default="", max_length=120),
    date: str = Query(default="", max_length=10),
    start_time: str = Query(default="", max_length=5),
    end_time: str = Query(default="", max_length=5),
    registration: str = Query(default="", max_length=20),
):
    return recommend_events({
        "interest": interest, "audience": audience, "language": language,
        "event_type": event_type, "branch": branch, "date": date,
        "start_time": start_time, "end_time": end_time, "registration": registration,
    })


@app.get("/search")
async def search_records(q: str = Query(default="", max_length=100)):
    term = q.strip().casefold()
    if len(term) < 2:
        return {"branches": [], "events": []}
    branches = []
    for branch in branch_records():
        haystack = " ".join([
            branch["name"], branch["code"], branch["address"], branch["service_tier"],
            " ".join(branch["services"]),
        ]).casefold()
        if term in haystack:
            branches.append(branch)
        if len(branches) >= 10:
            break
    events = []
    for event in event_records():
        haystack = " ".join([
            event["title"], event["location"], event["description"], event["audiences"], event["types"],
        ]).casefold()
        if term in haystack:
            events.append({key: value for key, value in event.items() if key != "raw"})
        if len(events) >= 10:
            break
    return {"branches": branches, "events": events}


@app.post("/ask")
def branch_question(payload: AskRequest):
    try:
        return relate_ask(payload.question.strip(), payload.branch_code)
    except RelateUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/status")
def application_status():
    return {
        "app": "LibraryTO",
        "data_directory": DATA_DIR.name,
        "datasets": dataset_status(),
        "relate": graph_status(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _csv_response(filename: str, headers: list[str], rows: list[list[Any]]) -> Response:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/exports/observations.csv")
async def export_observations(
    metric: str = Query(default="", max_length=30),
    branch_code: str = Query(default="", max_length=40),
):
    if metric and metric not in METRICS:
        raise HTTPException(status_code=400, detail="Unknown metric.")
    rows = [
        [item["branch_code"], item["metric"], METRICS[item["metric"]], item["year"], item["value"]]
        for item in observations(metric or None)
        if not branch_code or item["branch_code"].casefold() == branch_code.casefold()
    ]
    return _csv_response("libraryto-annual-observations.csv", ["branch_code", "metric_key", "metric", "year", "value"], rows)


@app.get("/exports/branches.csv")
async def export_branches():
    rows = []
    for item in branch_records():
        rows.append([
            item["code"], item["name"], item["address"], item["postal_code"],
            item["service_tier"], item["square_footage"], item["workstations"],
            item["lat"], item["lon"], "; ".join(item["services"]), item["website"], item["telephone"],
        ])
    return _csv_response(
        "libraryto-branches.csv",
        ["branch_code", "branch_name", "address", "postal_code", "service_tier", "square_footage", "workstations", "latitude", "longitude", "services", "website", "telephone"],
        rows,
    )


@app.get("/exports/comparisons.csv")
async def export_compare(branches: str = Query(default="", max_length=500)):
    result = compare([item.strip() for item in branches.split(",") if item.strip()][:6])
    headers = ["metric", "year", *[item["code"] for item in result["branches"]]]
    rows = []
    for metric, years in result["metrics"].items():
        for year in years:
            rows.append([METRICS[metric], year["year"], *[year["values"].get(branch["code"]) for branch in result["branches"]]])
    return _csv_response("libraryto-branch-comparison.csv", headers, rows)


@app.get("/exports/events.csv")
async def export_events(
    interest: str = "", audience: str = "", language: str = "", event_type: str = "",
    branch: str = "", date: str = "", start_time: str = "", end_time: str = "",
    registration: str = "",
):
    result = recommend_events({
        "interest": interest, "audience": audience, "language": language,
        "event_type": event_type, "branch": branch, "date": date,
        "start_time": start_time, "end_time": end_time, "registration": registration,
    })
    event_rows = result["events"]
    rows = [[
        item["id"], item["title"], item["start"], item["end"], item["location"], item["branch_code"],
        item["audiences"], item["languages"], item["types"], item["registration_status"],
        "; ".join(item["match_reasons"]), item["event_url"], item["registration_url"],
    ] for item in event_rows]
    return _csv_response(
        "libraryto-programs-and-events.csv",
        ["event_id", "title", "start", "end", "location", "branch_code", "audiences", "languages", "event_types", "registration_status", "matched_preferences", "event_url", "registration_url"],
        rows,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "app": "LibraryTO"}

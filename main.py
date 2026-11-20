"""LibraryTO FastAPI application."""
from __future__ import annotations

import csv
import re
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
from app.services.analytics import METRICS, branch_detail, branch_forecasts, compare, overview, recommend_events, event_filter_options
from app.services.data_store import branch_records, dataset_status, event_records, observations, data_revision
from app.services.relate import RelateUnavailable, ask as relate_ask, graph_status

app = FastAPI(title="LibraryTO", version="1.1.0", description="Explore Toronto Public Library branch information, activity and programs.", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
# Bump on source changes because static assets are served with immutable caching.
STATIC_VERSION = "20261120-2"


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    branch_code: str | None = Field(default=None, max_length=40)


def _graph_timestamp(value: Any, date_fallback: Any = None) -> str:
    """Render graph date/time values for non-technical users."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{10,13}", raw):
        try:
            numeric = int(raw)
            parsed = datetime.fromtimestamp(numeric / (1000 if numeric > 10**12 else 1), tz=timezone.utc)
            return parsed.strftime("%Y-%m-%d %H:%M")
        except (OverflowError, OSError, ValueError):
            return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M") if re.search(r"[T ]\d{1,2}:\d{2}", raw) else parsed.strftime("%Y-%m-%d")
    except ValueError:
        pass
    date_text = str(date_fallback or "").strip()
    if date_text:
        try:
            day = datetime.fromisoformat(date_text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                day = datetime.strptime(date_text[:10], "%Y-%m-%d").date()
            except ValueError:
                day = None
        if day:
            for pattern in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
                try:
                    clock = datetime.strptime(raw, pattern).time()
                    return f"{day.isoformat()} {clock.strftime('%H:%M')}"
                except ValueError:
                    continue
    return ""


def _scope_question_answer(answer: dict[str, Any], branch_code: str | None) -> dict[str, Any]:
    """Keep branch-Q&A results only when the graph record names the selected branch."""
    if not branch_code:
        return answer
    branch = next((item for item in branch_records() if item["code"].casefold() == branch_code.casefold()), None)
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found.")

    def normalize(value: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    def belongs(properties: Any) -> bool:
        if not isinstance(properties, dict):
            return False
        values = {normalize(key): value for key, value in properties.items()}
        code = str(values.get("branchcode") or values.get("tplbranchcode") or "").strip()
        if code and code.casefold() == branch["code"].casefold():
            return True
        branch_name = branch["name"].casefold()
        for key in ("branchname", "locationname", "location", "branch", "venuename", "venue"):
            value = str(values.get(key) or "").strip().casefold()
            if value and (value == branch_name or branch_name in value):
                return True
        return False

    evidence = answer.get("evidence") or []
    scoped = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        properties = item.get("properties") or {}
        normalized_properties = {normalize(key): value for key, value in properties.items()} if isinstance(properties, dict) else {}
        record_code = str(normalized_properties.get("branchcode") or normalized_properties.get("tplbranchcode") or "").strip()
        if record_code and record_code.casefold() != branch["code"].casefold():
            continue
        matching_connections = [
            edge for edge in (item.get("connections") or [])
            if belongs(edge.get("related_properties"))
        ]
        if not belongs(properties) and not matching_connections:
            continue
        record = dict(item)
        # Keep only relationships that explicitly point to the selected branch.
        record["connections"] = matching_connections
        scoped.append(record)
    if not scoped:
        return {
            "status": "no_branch_matches",
            "answer": f"I couldn't find graph records linked to {branch['name']} for that question. Try asking about a reported service, annual measure or program at this branch.",
            "highlights": [],
            "evidence": [],
        }

    titles = set()
    for record in scoped:
        props = {normalize(key): value for key, value in (record.get("properties") or {}).items()}
        title = next((str(props[key]).strip() for key in ("name", "title", "branchname", "servicename", "eventtitle", "programname") if props.get(key)), "")
        if title:
            titles.add(title.casefold())
    try:
        # Rebuild the summaries from branch-scoped graph records so details from
        # unassociated relationships cannot leak into this branch's answer.
        from app.services.relate import _summary_highlights
        filtered = _summary_highlights(scoped)
    except Exception:
        filtered = [item for item in (answer.get("highlights") or []) if str(item.get("title") or "").casefold() in titles]
    return {**answer, "highlights": filtered, "evidence": scoped}


def _enrich_question_answer(answer: dict[str, Any]) -> dict[str, Any]:
    """Add readable program start/end times to curated Relate result summaries."""
    highlights = answer.get("highlights") or []
    evidence = answer.get("evidence") or []
    for record in evidence:
        properties = record.get("properties") or {}
        if not isinstance(properties, dict):
            continue
        normalized = {re.sub(r"[^a-z0-9]", "", str(key).casefold()): value for key, value in properties.items()}
        labels = " ".join(str(label) for label in record.get("labels") or []).casefold()
        is_program = "event" in labels or "program" in labels or any(key.startswith(("starttime", "startdatetime", "startdatelocal")) for key in normalized)
        if not is_program:
            continue
        title = next((str(normalized[key]).strip() for key in ("title", "eventtitle", "eventname", "programname") if normalized.get(key)), "")
        target = next((item for item in highlights if title and str(item.get("title", "")).casefold() == title.casefold()), None)
        if target is None and len(highlights) == 1:
            target = highlights[0]
        if target is None:
            continue
        details = target.setdefault("details", [])
        existing = {str(item.get("label", "")).casefold() for item in details}
        start_date = normalized.get("startdatelocal") or normalized.get("startdate") or normalized.get("eventdate")
        end_date = normalized.get("enddatelocal") or normalized.get("enddate") or start_date
        for label, candidates, fallback in (
            ("Starts", ("startdatetime", "starttime", "eventdatetime"), start_date),
            ("Ends", ("enddatetime", "endtime"), end_date),
        ):
            if label.casefold() in existing:
                continue
            raw = next((normalized[key] for key in candidates if normalized.get(key) not in (None, "")), None)
            if raw is None:
                continue
            formatted = _graph_timestamp(raw, fallback)
            if formatted:
                details.append({"label": label, "value": formatted})
    # Raw graph nodes are an internal retrieval artifact, not user-facing content.
    answer.pop("evidence", None)
    return answer


def _page(request: Request, active: str, title: str):
    return templates.TemplateResponse(request, "index.html", {"active": active, "title": title, "data_revision": data_revision(), "static_version": STATIC_VERSION})


def _is_data_route(path: str) -> bool:
    return path in {"/overview", "/branches", "/comparisons/data", "/search", "/ask", "/status", "/health", "/events/options"} or path.startswith(("/branches/", "/events/recommendations", "/exports/"))


@app.middleware("http")
async def read_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.method == "GET" and response.status_code == 200:
        if _is_data_route(request.url.path):
            response.headers.setdefault("Cache-Control", "public, max-age=300, stale-while-revalidate=600")
        elif request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    return response


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    if _is_data_route(request.url.path):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    if exc.status_code == 404:
        return templates.TemplateResponse(request, "404.html", {"title": "Page not found"}, status_code=404)
    return templates.TemplateResponse(request, "error.html", {"title": "Something went wrong", "status_code": exc.status_code}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    if _is_data_route(request.url.path):
        return JSONResponse({"error": "The request contains invalid values."}, status_code=422)
    return templates.TemplateResponse(request, "error.html", {"title": "Invalid request", "status_code": 422}, status_code=422)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request): return _page(request, "overview", "Overview")


@app.get("/branch-insights", response_class=HTMLResponse)
async def branch_page(request: Request): return _page(request, "branches", "Branch Insights")


@app.get("/comparisons", response_class=HTMLResponse)
async def comparisons_page(request: Request): return _page(request, "comparisons", "Branch Comparisons")


@app.get("/programs-events", response_class=HTMLResponse)
async def events_page(request: Request): return _page(request, "events", "Programs & Events")


@app.get("/overview")
async def overview_data(): return overview()


@app.get("/branches")
async def list_branches(): return branch_records()


@app.get("/branches/{code}")
async def branch_profile(code: str):
    result = branch_detail(code)
    if result is None: raise HTTPException(status_code=404, detail="Branch not found.")
    return result


@app.get("/branches/{code}/forecasts")
async def branch_forecast_data(code: str):
    result = branch_forecasts(code)
    if result is None: raise HTTPException(status_code=404, detail="Branch not found.")
    return result


@app.get("/comparisons/data")
async def comparison_data(branches: str = Query(default="", max_length=500)):
    return compare([item.strip() for item in branches.split(",") if item.strip()][:5])


@app.get("/events/options")
async def events_options(): return event_filter_options()


@app.get("/events/recommendations")
async def event_recommendations_data(
    interest: str = Query(default="", max_length=120), audience: str = Query(default="", max_length=80),
    language: str = Query(default="", max_length=80), event_type: str = Query(default="", max_length=80),
    branch: str = Query(default="", max_length=120), date: str = Query(default="", max_length=10),
    start_time: str = Query(default="", max_length=5), end_time: str = Query(default="", max_length=5),
    registration: str = Query(default="", max_length=20),
):
    return recommend_events({"interest": interest, "audience": audience, "language": language, "event_type": event_type, "branch": branch,
                             "date": date, "start_time": start_time, "end_time": end_time, "registration": registration})


@app.get("/search")
async def search_records(q: str = Query(default="", max_length=100)):
    term = q.strip().casefold()
    if len(term) < 2: return {"branches": [], "events": []}
    branches = []
    for branch in branch_records():
        searchable = " ".join([branch["name"], branch["code"], branch["address"], branch["service_tier"], " ".join(branch["services"])]).casefold()
        if term in searchable: branches.append(branch)
        if len(branches) >= 10: break
    events = []
    for event in event_records():
        searchable = " ".join([event["title"], event["location"], event["description"], event["audiences"], event["types"]]).casefold()
        if term in searchable: events.append({key: value for key, value in event.items() if key != "raw"})
        if len(events) >= 10: break
    return {"branches": branches, "events": events}


@app.post("/ask")
def branch_question(payload: AskRequest):
    try:
        question = payload.question.strip()
        if payload.branch_code:
            selected_branch = next((item for item in branch_records() if item["code"].casefold() == payload.branch_code.casefold()), None)
            if selected_branch is None:
                raise HTTPException(status_code=404, detail="Branch not found.")
            # Include the selected branch name in the search terms as well as
            # its code, because some event/service nodes carry only the name.
            question = f"{question} {selected_branch['name']}"
        answer = relate_ask(question, payload.branch_code)
        answer = _scope_question_answer(answer, payload.branch_code)
        return _enrich_question_answer(answer)
    except RelateUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/status")
def application_status():
    return {"app": "LibraryTO", "data_directory": DATA_DIR.name, "datasets": dataset_status(), "relate": graph_status(), "generated_at": datetime.now(timezone.utc).isoformat()}


def _csv_response(filename: str, headers: list[str], rows: list[list[Any]]) -> Response:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer); writer.writerow(headers); writer.writerows(rows)
    return Response(content="\ufeff" + buffer.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/exports/observations.csv")
async def export_observations(metric: str = Query(default="", max_length=30), branch_code: str = Query(default="", max_length=40)):
    if metric and metric not in METRICS: raise HTTPException(status_code=400, detail="Unknown metric.")
    rows = [[item["branch_code"], item["metric"], METRICS[item["metric"]], item["year"], item["value"]] for item in observations(metric or None) if not branch_code or item["branch_code"].casefold() == branch_code.casefold()]
    return _csv_response("libraryto-annual-observations.csv", ["branch_code", "metric_key", "metric", "year", "value"], rows)


@app.get("/exports/branches.csv")
async def export_branches():
    rows = [[item["code"], item["name"], item["address"], item["postal_code"], item["service_tier"], item["type_of_library"], item["year_opened"], item["square_footage"], item["workstations"], item["lat"], item["lon"], "; ".join(item["services"]), item["website"], item["telephone"]] for item in branch_records()]
    return _csv_response("libraryto-branches.csv", ["branch_code", "branch_name", "address", "postal_code", "service_tier", "type_of_library", "year_opened", "square_footage", "workstations", "latitude", "longitude", "services", "website", "telephone"], rows)


@app.get("/exports/comparisons.csv")
async def export_compare(branches: str = Query(default="", max_length=500)):
    result = compare([item.strip() for item in branches.split(",") if item.strip()][:5])
    headers = ["metric", "year", *[item["code"] for item in result["branches"]]]; rows = []
    for metric, years in result["metrics"].items():
        for year in years: rows.append([METRICS[metric], year["year"], *[year["values"].get(branch["code"]) for branch in result["branches"]]])
    return _csv_response("libraryto-branch-comparison.csv", headers, rows)


@app.get("/exports/events.csv")
async def export_events(interest: str = "", audience: str = "", language: str = "", event_type: str = "", branch: str = "", date: str = "", start_time: str = "", end_time: str = "", registration: str = ""):
    result = recommend_events({"interest": interest, "audience": audience, "language": language, "event_type": event_type, "branch": branch, "date": date, "start_time": start_time, "end_time": end_time, "registration": registration})
    rows = [[item["id"], item["title"], item["start"], item["end"], item["location"], item["branch_code"], item["audiences"], item["languages"], item["types"], item["registration_status"], "; ".join(item["match_reasons"]), item["event_url"], item["registration_url"]] for item in result["events"]]
    return _csv_response("libraryto-programs-and-events.csv", ["event_id", "title", "start", "end", "location", "branch_code", "audiences", "languages", "event_types", "registration_status", "matched_preferences", "event_url", "registration_url"], rows)


@app.get("/health")
async def health(): return {"status": "ok", "app": "LibraryTO"}

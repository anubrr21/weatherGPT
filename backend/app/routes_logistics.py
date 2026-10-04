import base64
import json
import re
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from app.services import logistics, reports
from app.services.trips import TripError

router = APIRouter(tags=["logistics"])


class PlaceIn(BaseModel):
    name: str | None = Field(None, max_length=120, description="Place name, port or hub. Optional when lat and lon are given.")
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)


class ShipmentIn(BaseModel):
    ref: str | None = Field(None, max_length=80, description="Your own shipment or trip reference; returned unchanged.")
    origin: PlaceIn
    destination: PlaceIn
    vias: list[PlaceIn] = Field(default_factory=list, max_length=8)
    mode: Literal["road", "rail", "air", "sea"] = "road"
    vehicle: Literal["lcv", "hcv", "container", "tanker", "reefer"] = "hcv"
    cargo: Literal["general", "chilled", "frozen", "pharma", "produce", "moisture", "electronics", "hazmat", "livestock"] = "general"
    crew: int = Field(1, ge=1, le=2, description="Drivers on board. Two drivers remove the overnight halt.")
    depart: datetime | None = Field(None, description="Dispatch time. Times without a zone are read as India Standard Time. Omit for now.")


class FleetIn(BaseModel):
    shipments: list[ShipmentIn] = Field(..., min_length=1, max_length=logistics.MAX_FLEET)


class SiteIn(PlaceIn):
    ref: str | None = Field(None, max_length=80)
    kind: Literal["port", "airport", "hub"] = "hub"


class SitesIn(BaseModel):
    sites: list[SiteIn] = Field(..., min_length=1, max_length=logistics.MAX_SITES)


def _payload(item: BaseModel) -> dict[str, Any]:
    return item.model_dump(exclude_none=True)


async def _run(call):
    try:
        return await call
    except TripError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Logistics data unavailable: {exc}") from exc


@router.get("/api/logistics/options", summary="Modes, vehicles, cargo types, ports and hubs")
async def logistics_options():
    return logistics.options()


@router.post("/api/logistics/shipment", summary="Weather risk, weather-adjusted arrival time and dispatch advice for one shipment")
async def logistics_shipment(req: ShipmentIn):
    result = await _run(logistics.shipment(_payload(req)))
    return result | {"ref": req.ref, "brief": logistics.brief(result)}


@router.post("/api/logistics/fleet", summary="The same assessment for up to 20 shipments in one call")
async def logistics_fleet(req: FleetIn):
    return await _run(logistics.fleet([_payload(s) for s in req.shipments]))


@router.get("/api/logistics/facilities", summary="Five-day operations outlook for Indian ports, cargo airports and logistics hubs")
async def logistics_facilities(kind: str = Query("all", pattern="^(all|port|airport|hub)$")):
    return await _run(logistics.facilities(kind))


@router.post("/api/logistics/sites", summary="The same outlook for your own warehouses, plants or yards")
async def logistics_sites(req: SitesIn):
    return await _run(logistics.custom_sites([_payload(s) for s in req.sites]))


@router.get("/api/logistics/network", summary="Live weather status of India's main freight corridors")
async def logistics_network():
    return await _run(logistics.network())


class AnalysisIn(ShipmentIn):
    route: int = Field(0, ge=0, le=2, description="Which of the returned routes to analyse.")


@router.post("/api/logistics/analysis", summary="A written dispatch briefing for one shipment")
async def logistics_analysis(req: AnalysisIn):
    body = _payload(req)
    index = body.pop("route", 0)
    return await _run(logistics.analysis(body, index))


def _decode(q: str | None, model: type[BaseModel]) -> BaseModel:
    if not q:
        raise HTTPException(status_code=422, detail="This report needs the q parameter")
    try:
        raw = base64.urlsafe_b64decode(q + "=" * (-len(q) % 4)).decode("utf-8")
        return model.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="The q parameter is not a valid request") from exc


def _pdf(body: bytes, name: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:80] or "report"
    return Response(content=body, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="WeatherGPT-{safe}.pdf"', "Cache-Control": "no-store"})


@router.get("/api/logistics/report.pdf", summary="Any logistics view as a PDF report", response_class=Response)
async def logistics_report(
    kind: str = Query(..., pattern="^(shipment|fleet|network|facilities|sites)$"),
    q: str | None = Query(None, max_length=12000, description="The request body for shipment, fleet or sites, as base64url-encoded JSON."),
    route: int = Query(0, ge=0, le=2),
    analysis: bool = Query(True, description="Include the written briefing in a shipment report."),
    site_kind: str = Query("all", pattern="^(all|port|airport|hub)$"),
):
    today = datetime.now().strftime("%Y%m%d-%H%M")
    if kind == "shipment":
        req = _decode(q, ShipmentIn)
        body = _payload(req)
        result = await _run(logistics.shipment(body))
        index = min(route, len(result["routes"]) - 1)
        text = (await _run(logistics.analysis(body, index)))["text"] if analysis else None
        pdf = reports.shipment_report(result, index, text, req.ref)
        return _pdf(pdf, f"shipment-{result['origin']['name']}-{result['destination']['name']}-{today}")
    if kind == "fleet":
        req = _decode(q, FleetIn)
        return _pdf(reports.fleet_report(await _run(logistics.fleet([_payload(s) for s in req.shipments]))), f"fleet-{today}")
    if kind == "network":
        return _pdf(reports.network_report(await _run(logistics.network())), f"corridors-{today}")
    if kind == "sites":
        req = _decode(q, SitesIn)
        return _pdf(reports.facilities_report(await _run(logistics.custom_sites([_payload(s) for s in req.sites])), "Your sites"), f"sites-{today}")
    titles = {"all": "Ports, cargo airports and logistics hubs", "port": "Ports", "airport": "Cargo airports", "hub": "Logistics hubs"}
    return _pdf(reports.facilities_report(await _run(logistics.facilities(site_kind)), titles[site_kind]), f"facilities-{site_kind}-{today}")

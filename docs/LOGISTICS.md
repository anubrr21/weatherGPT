# Logistics

The Logistics workspace answers four questions for freight moving by road, rail, air or coastal sea:

1. Should this shipment go now, go with care, or wait?
2. When will it really arrive, given the weather it meets on the way?
3. Is the cargo safe in that weather?
4. Which corridors, ports, airports and hubs will be disrupted in the next few days?

The same engine sits behind the Logistics tab in the app, the chat assistant and a JSON API that other software can call.

## How a shipment is assessed

- **Route.** Road routes come from OSRM on OpenStreetMap and are scaled to the vehicle (light truck, heavy truck, container trailer, tanker, reefer). Rail follows the Indian railway network at the average freight speed of about 25 km/h. Air is the great-circle route between the nearest scheduled airports. Sea follows a coastal lane between Indian ports that passes south of Sri Lanka when a voyage links the west and east coasts.
- **Weather at the right time.** The route is sampled at up to 32 points. Each stretch is slowed by the forecast for the hour the shipment reaches it, so a delay early in the trip moves every later stretch into different weather.
- **Speed loss.** Road speed reductions in rain, fog and snow follow the ranges published by the US Federal Highway Administration road weather programme (light rain 2 to 13%, heavy rain 6 to 17%, low visibility 10 to 12%), extended for very heavy rain and dense fog. The middle of each range gives the expected arrival and the top of the range gives the latest arrival. Crosswind on high-sided vehicles is the gust component at right angles to the road.
- **Driver hours.** One driver takes a 30 minute break every 4.5 hours of driving and an 8 hour halt after 10 hours. Two drivers take a 20 minute break every 5 hours and no halt.
- **Official warnings and cyclones.** NDMA SACHET warning polygons are tested against the route, with a note when a warning expires before the shipment gets there. Active cyclones are checked against their forecast track and cone.
- **Best dispatch time.** The whole trip is re-run for every hour of the next 48 hours and the lowest-risk start is recommended when it is clearly better.
- **Where the delay comes from.** Delay is split by cause (rain, fog, wind, snow), with the distance and time each one affects, and the route is summarised stage by stage.
- **Confidence.** GFS, ECMWF and ICON are compared at the start, midway and destination for the day the shipment is there. The score also falls with lead time.
- **Written briefing.** A language model turns the computed facts into a dispatch briefing. It is given only those facts and the figures on the page do not depend on it.

## Cargo exposure

| Cargo | What is measured |
|---|---|
| Chilled, frozen | Hours above 35 °C and 40 °C outside, gap to setpoint, and whether the vehicle is refrigerated |
| Pharma (15 to 25 °C) | Hours outside the label range and the mean kinetic temperature of the outside air |
| Fresh produce | Hours at 30 °C or more and the spoilage rate relative to 20 °C (Q10 of 2.5) |
| Moisture-sensitive, electronics | Rain on an open body, hours at 85% humidity, cargo sweat and container rain from dew point |
| Flammable or hazardous | Hours in thunderstorms and at 40 °C or more |
| Livestock | Temperature-humidity index against the danger (79) and emergency (84) bands |

## Facilities

Ports, large airports and logistics hubs get a five-day outlook that counts the hours each day when work is likely to stop.

| Facility | Work stops for |
|---|---|
| Port | Gusts of 72 km/h (yard cranes; ship-to-shore cranes stop near 80 km/h), lightning, visibility under 200 m, rain of 20 mm/h, waves of 3 m at the approach |
| Airport | Visibility under 200 m, thunderstorms, gusts of 65 km/h, rain of 30 mm/h |
| Hub or warehouse | Lightning, rain of 7.6 mm/h, gusts of 60 km/h; a day with 64.5 mm of rain is flagged for flooding |

## API

Interactive reference: `/docs#/logistics` on the server.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/logistics/shipment` | One shipment in full, with a short summary under `brief` |
| POST | `/api/logistics/fleet` | Up to 20 shipments, short result for each |
| GET | `/api/logistics/network` | Status of 22 road freight corridors |
| GET | `/api/logistics/facilities?kind=all` | Ports, cargo airports and hubs (`port`, `airport`, `hub` or `all`) |
| POST | `/api/logistics/sites` | The same outlook for up to 30 of your own sites |
| GET | `/api/logistics/options` | Accepted modes, vehicles, cargo types, ports and hubs |
| POST | `/api/logistics/analysis` | The written dispatch briefing for one shipment |
| GET | `/api/logistics/report.pdf` | Any of the above as a PDF report |

```bash
curl -X POST http://localhost:8000/api/logistics/shipment \
  -H "Content-Type: application/json" \
  -d '{
    "ref": "LR-2041",
    "origin": {"name": "Pune"},
    "destination": {"name": "Hyderabad"},
    "mode": "road",
    "vehicle": "reefer",
    "cargo": "chilled",
    "crew": 1,
    "depart": "2026-10-06T21:00"
  }'
```

- A place is a name, or a `lat` and `lon`, or both.
- `depart` without a time zone is read as India Standard Time. Omit it for now.
- `ref` is returned unchanged so results can be matched to your own records.
- Results for the same route and hour are cached for 10 minutes and forecasts for 30 minutes.

## PDF reports

`GET /api/logistics/report.pdf` returns a formatted report with the summary, route map, tables and charts.

| `kind` | Other parameters |
|---|---|
| `shipment` | `q` = the shipment request as base64url-encoded JSON, `route` = which alternative (0 to 2), `analysis` = include the written briefing (default true) |
| `fleet` | `q` = `{"shipments": [...]}` as base64url-encoded JSON |
| `network` | none |
| `facilities` | `site_kind` = `all`, `port`, `airport` or `hub` |
| `sites` | `q` = `{"sites": [...]}` as base64url-encoded JSON |

Reports are set in a Latin typeface, so text in Indian scripts is not supported in them.

## Limits

- Traffic, tolls, loading time and road closures are not modelled.
- Sea legs cover Indian ports only and use a fixed coastal lane, not a routed voyage.
- Rail times use the network average freight speed, not a timetable.
- Facility thresholds are general operating limits; each port, airport and warehouse has its own.
- The free Open-Meteo forecast service is for non-commercial use and has a daily request limit. Commercial or high-volume use needs an Open-Meteo API plan or a self-hosted instance.

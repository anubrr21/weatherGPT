import argparse
import asyncio
import os
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import websockets

CITIES = [
    ("Delhi", 28.61, 77.21), ("Mumbai", 19.08, 72.88), ("Chennai", 13.08, 80.27), ("Kolkata", 22.57, 88.36),
    ("Bengaluru", 12.97, 77.59), ("Hyderabad", 17.39, 78.49), ("Jaipur", 26.91, 75.79), ("Lucknow", 26.85, 80.95),
    ("Patna", 25.59, 85.14), ("Guwahati", 26.14, 91.74), ("Bhubaneswar", 20.30, 85.82), ("Thiruvananthapuram", 8.52, 76.94),
    ("Ahmedabad", 23.02, 72.57), ("Bhopal", 23.26, 77.41), ("Srinagar", 34.08, 74.80), ("Shimla", 31.10, 77.17),
    ("Visakhapatnam", 17.69, 83.22), ("Amaravati", 16.51, 80.52), ("Bahraich", 27.57, 81.60), ("Port Blair", 11.62, 92.73),
]

MIX = [
    ("weather", 40, lambda c: ("/api/weather", {"lat": c[1], "lon": c[2]})),
    ("alerts", 20, lambda c: ("/api/alerts", {"lat": c[1], "lon": c[2]})),
    ("observations", 15, lambda c: ("/api/observations/nearby", {"lat": c[1], "lon": c[2]})),
    ("geocode", 10, lambda c: ("/api/geocode", {"q": c[0]})),
    ("reverse", 10, lambda c: ("/api/reverse", {"lat": c[1], "lon": c[2]})),
    ("health", 5, lambda c: ("/api/health", {})),
]


@dataclass
class Stats:
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    status: dict[int, int] = field(default_factory=lambda: defaultdict(int))


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def pick() -> tuple[str, str, dict]:
    name, _, build = random.choices(MIX, weights=[w for _, w, _ in MIX])[0]
    path, params = build(random.choice(CITIES))
    return name, path, params


async def warm(client: httpx.AsyncClient) -> None:
    jobs = [(name, *build(city)) for name, _, build in MIX for city in CITIES]
    unique = {(path, json.dumps(params, sort_keys=True)): (name, path, params) for name, path, params in jobs}
    gate = asyncio.Semaphore(4)

    async def one(path: str, params: dict) -> None:
        async with gate:
            try:
                await client.get(path, params=params, timeout=60)
            except httpx.HTTPError:
                pass

    started = time.perf_counter()
    await asyncio.gather(*(one(path, params) for _, path, params in unique.values()))
    print(f"warm-up: {len(unique)} distinct requests in {time.perf_counter() - started:.1f}s")


async def http_user(client: httpx.AsyncClient, stats: Stats, deadline: float, think_ms: int) -> None:
    while time.perf_counter() < deadline:
        name, path, params = pick()
        started = time.perf_counter()
        try:
            response = await client.get(path, params=params)
            elapsed = (time.perf_counter() - started) * 1000
            stats.status[response.status_code] += 1
            if response.status_code >= 400:
                stats.errors[name] += 1
            else:
                stats.latencies[name].append(elapsed)
        except httpx.HTTPError:
            stats.errors[name] += 1
        if think_ms:
            await asyncio.sleep(random.uniform(0, think_ms) / 1000)


async def _http_phase(base: str, users: int, end_epoch: float, think_ms: int) -> Stats:
    stats = Stats()
    deadline = time.perf_counter() + (end_epoch - time.time())
    limits = httpx.Limits(max_connections=users, max_keepalive_connections=users)
    async with httpx.AsyncClient(base_url=base, limits=limits, timeout=30) as client:
        await asyncio.gather(*(http_user(client, stats, deadline, think_ms) for _ in range(users)))
    return stats


def http_worker(base: str, users: int, end_epoch: float, think_ms: int) -> dict:
    cpu = time.process_time()
    began = time.time()
    stats = asyncio.run(_http_phase(base, users, end_epoch, think_ms))
    return {
        "active": time.time() - began,
        "latencies": dict(stats.latencies), "errors": dict(stats.errors), "status": dict(stats.status),
        "cpu": time.process_time() - cpu,
    }


async def ws_user(base: str, index: int, deadline: float, results: dict) -> None:
    url = base.replace("http", "ws", 1) + f"/ws?client_id=loadtest-{index:05d}"
    started = time.perf_counter()
    try:
        async with websockets.connect(url, open_timeout=15) as socket:
            json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
            results["hello_ms"].append((time.perf_counter() - started) * 1000)
            while time.perf_counter() < deadline:
                await asyncio.sleep(min(5, max(0.1, deadline - time.perf_counter())))
            await socket.send("ping")
            await asyncio.wait_for(socket.recv(), timeout=10)
            results["held"] += 1
    except Exception as exc:
        results["failed"] += 1
        results["errors"][type(exc).__name__] += 1


def report(stats: Stats, seconds: float, ws: dict | None, target_ms: float) -> dict:
    rows = []
    every = [v for values in stats.latencies.values() for v in values]
    total_ok = len(every)
    total_err = sum(stats.errors.values())
    print()
    print(f"{'endpoint':<14}{'ok':>8}{'err':>6}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}{'max ms':>10}")
    for name, _, _ in MIX:
        values = stats.latencies.get(name, [])
        row = {
            "endpoint": name, "ok": len(values), "errors": stats.errors.get(name, 0),
            "p50": round(pct(values, 50), 1), "p95": round(pct(values, 95), 1), "p99": round(pct(values, 99), 1),
            "max": round(max(values), 1) if values else 0.0,
        }
        rows.append(row)
        print(f"{name:<14}{row['ok']:>8}{row['errors']:>6}{row['p50']:>10}{row['p95']:>10}{row['p99']:>10}{row['max']:>10}")
    overall = {
        "requests": total_ok + total_err,
        "rps": round((total_ok + total_err) / seconds, 1),
        "error_rate": round(total_err / max(1, total_ok + total_err) * 100, 2),
        "p50": round(pct(every, 50), 1),
        "p95": round(pct(every, 95), 1),
        "p99": round(pct(every, 99), 1),
        "mean": round(statistics.fmean(every), 1) if every else 0.0,
    }
    print(f"{'all':<14}{total_ok:>8}{total_err:>6}{overall['p50']:>10}{overall['p95']:>10}{overall['p99']:>10}")
    print(f"\nthroughput {overall['rps']} req/s · error rate {overall['error_rate']}% · status codes {dict(stats.status)}")
    ws_summary = None
    if ws is not None:
        ws_summary = {
            "opened": len(ws["hello_ms"]), "held_to_end": ws["held"], "failed": ws["failed"],
            "hello_p50": round(pct(ws["hello_ms"], 50), 1), "hello_p95": round(pct(ws["hello_ms"], 95), 1),
            "errors": dict(ws["errors"]),
        }
        print(f"websockets: {ws_summary['opened']} opened, {ws_summary['held_to_end']} held to the end, {ws_summary['failed']} failed · hello p50 {ws_summary['hello_p50']} ms, p95 {ws_summary['hello_p95']} ms")
    passed = overall["p95"] <= target_ms and overall["error_rate"] < 1 and (ws_summary is None or ws_summary["failed"] == 0)
    print(f"\ntarget p95 ≤ {target_ms:.0f} ms and errors < 1%: {'PASS' if passed else 'FAIL'}")
    return {"overall": overall, "endpoints": rows, "websockets": ws_summary, "target_p95_ms": target_ms, "passed": passed}


async def main() -> int:
    parser = argparse.ArgumentParser(description="WeatherGPT API load test")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--ws", type=int, default=0)
    parser.add_argument("--think-ms", type=int, default=0)
    parser.add_argument("--target-p95", type=float, default=300)
    parser.add_argument("--no-warm", action="store_true")
    parser.add_argument("--procs", type=int, default=max(1, min(8, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--out")
    args = parser.parse_args()

    procs = max(1, min(args.procs, args.concurrency))
    if not args.no_warm:
        async with httpx.AsyncClient(base_url=args.base, timeout=60) as client:
            await warm(client)
    ws_results = {"hello_ms": [], "held": 0, "failed": 0, "errors": defaultdict(int)} if args.ws else None
    print(f"running {args.concurrency} HTTP users in {procs} processes" + (f" and {args.ws} WebSocket clients" if args.ws else "") + f" for {args.duration:.0f}s against {args.base}")
    shares = [args.concurrency // procs + (1 if i < args.concurrency % procs else 0) for i in range(procs)]
    end_epoch = time.time() + args.duration + 1.5
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=procs) as pool:
        futures = [loop.run_in_executor(pool, http_worker, args.base, n, end_epoch, args.think_ms) for n in shares]
        ws_tasks = [ws_user(args.base, i, time.perf_counter() + args.duration, ws_results) for i in range(args.ws)] if ws_results is not None else []
        parts, _ = await asyncio.gather(asyncio.gather(*futures), asyncio.gather(*ws_tasks))
    wall = max(part["active"] for part in parts)
    stats = Stats()
    for part in parts:
        for name, values in part["latencies"].items():
            stats.latencies[name].extend(values)
        for name, count in part["errors"].items():
            stats.errors[name] += count
        for code, count in part["status"].items():
            stats.status[int(code)] += count
    result = report(stats, wall, ws_results, args.target_p95)
    client_cpu = sum(part["cpu"] for part in parts)
    result["load_generator_cpu_pct"] = round(client_cpu / wall * 100, 1)
    print(f"load generator: {procs} processes used {client_cpu:.1f}s CPU in {wall:.1f}s ({result['load_generator_cpu_pct']}% of one core in total)")
    result["config"] = {k: v for k, v in vars(args).items() if k != "out"}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"saved {args.out}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

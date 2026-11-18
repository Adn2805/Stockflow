"""Send synchronized request bursts to a disposable StockFlow API."""

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from time import perf_counter

import httpx

from environment import Benchmark, audit, benchmark, is_consistent, metadata, seed


@dataclass(frozen=True)
class Scenario:
    name: str
    products: int
    opening: int
    requests: int
    quantities: tuple[int, ...]
    expected_statuses: dict[str, int]
    accepted_orders: int
    reserved: int
    reuse_key: bool = False


SCENARIOS = (
    Scenario("single-sku-500", 1, 100, 500, (1,), {"201": 100, "409": 400}, 100, 100),
    Scenario("multi-product", 2, 10, 32, (2, 1), {"201": 5, "409": 27}, 5, 15),
    Scenario("same-key", 1, 10, 32, (1,), {"201": 1, "200": 31}, 1, 1, True),
)


async def run_burst(target: Benchmark, scenario: Scenario) -> tuple[list[tuple[str, int | None]], float]:
    ready = asyncio.Event()
    launch = asyncio.Event()
    waiting = 0
    items = [{"product_id": index, "quantity": quantity}
             for index, quantity in enumerate(scenario.quantities, start=1)]
    limits = httpx.Limits(max_connections=scenario.requests, max_keepalive_connections=0)
    async with httpx.AsyncClient(
        base_url=target.url, headers={"Authorization": f"Bearer {target.token}"},
        limits=limits, timeout=60, trust_env=False,
    ) as client:
        async def send(index: int) -> tuple[str, int | None]:
            nonlocal waiting
            waiting += 1
            if waiting == scenario.requests:
                ready.set()
            await launch.wait()
            try:
                response = await client.post(
                    "/orders",
                    headers={"Idempotency-Key": "burst-0" if scenario.reuse_key else f"burst-{index}"},
                    json={"warehouse_id": 1, "customer_reference": "benchmark",
                          "items": items[::-1] if index % 2 else items},
                )
            except httpx.TransportError as exc:
                return type(exc).__name__, None
            if response.status_code in (200, 201):
                return str(response.status_code), response.json()["id"]
            if response.status_code == 409 and response.json().get("detail") != "Insufficient available stock":
                return "unexpected_conflict", None
            return str(response.status_code), None

        requests = [asyncio.create_task(send(index)) for index in range(scenario.requests)]
        await ready.wait()
        start = perf_counter()
        launch.set()
        return await asyncio.gather(*requests), round(perf_counter() - start, 4)


def run_scenario(scenario: Scenario, port: int) -> dict:
    with benchmark(port) as target:
        seed(target.engine, scenario.products, 1, scenario.opening)
        before = audit(target.engine)
        outcomes, seconds = asyncio.run(run_burst(target, scenario))
        after = audit(target.engine)
        statuses = dict(Counter(status for status, _ in outcomes))
        unique_ids = len({order_id for _, order_id in outcomes if order_id is not None})
        expected_items = scenario.accepted_orders * scenario.products
        passed = (
            is_consistent(before) and is_consistent(after)
            and statuses == scenario.expected_statuses
            and unique_ids == after["orders"] == after["reserved_orders"] == scenario.accepted_orders
            and after["order_items"] == expected_items
            and after["movements"] == before["movements"] + expected_items
            and after["on_hand"] == before["on_hand"] == scenario.opening * scenario.products
            and after["reserved"] == scenario.reserved
        )
        return {
            "metadata": metadata(target.engine),
            "scenario": scenario.name, "requests": scenario.requests,
            "expected_statuses": scenario.expected_statuses, "statuses": statuses,
            "unique_response_order_ids": unique_ids, "burst_seconds": seconds,
            "before": before, "after": after, "passed": passed,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=58082)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for scenario in (SCENARIOS[0], *SCENARIOS):
        result = run_scenario(scenario, args.port)
        results.append(result)
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f'{result["scenario"]}: {result["statuses"]}, passed={result["passed"]}', flush=True)
    if not all(result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

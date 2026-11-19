"""Smoke-check an approved, published read-only StockFlow demo over HTTPS."""

import argparse
import sys
from urllib.parse import urlsplit

import httpx


def https_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise argparse.ArgumentTypeError("Use a URL containing only the HTTPS origin")
    return value.rstrip("/")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify(frontend: str, api: str) -> None:
    with httpx.Client(timeout=90, follow_redirects=False) as client:
        home = client.get(frontend + "/")
        require(home.status_code == 200 and "StockFlow" in home.text, "Frontend failed its HTTPS smoke check")
        require("frame-ancestors 'none'" in home.headers.get("content-security-policy", ""),
                "Frontend security headers are missing")

        origin = {"Origin": frontend}
        health = client.get(api + "/health", headers=origin)
        require(health.status_code == 200 and health.json() == {"status": "ok"}, "API or database health check failed")
        for path in ("/products", "/inventory", "/orders", "/reports/stock-movements", "/reports/reconciliation"):
            response = client.get(api + path, headers=origin)
            require(response.status_code == 200, f"Read failed for {path}")
            require(response.headers.get("access-control-allow-origin") == frontend, f"CORS failed for {path}")
            data = response.json()
            if path == "/reports/reconciliation":
                require(data == [], "Demo inventory does not reconcile")
            else:
                require(isinstance(data, list) and bool(data), f"Synthetic data is missing for {path}")

        preflight = client.options(api + "/orders", headers=origin | {"Access-Control-Request-Method": "GET"})
        require(preflight.status_code == 200 and preflight.headers.get("access-control-allow-origin") == frontend,
                "Approved preflight failed")
        denied = client.get(api + "/inventory", headers={"Origin": "https://unapproved.invalid"})
        require("access-control-allow-origin" not in denied.headers, "Unexpected CORS origin was allowed")
        for path in ("/auth/login", "/orders", "/inventory/receipts"):
            response = client.post(api + path, json={}, headers=origin)
            require(response.status_code == 403, f"Demo read-only check failed for {path}")
    print("HTTPS, CSP, API health, CORS, synthetic reads, reconciliation, and write denial verified.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", required=True, type=https_origin)
    parser.add_argument("--api", required=True, type=https_origin)
    args = parser.parse_args()
    try:
        verify(args.frontend, args.api)
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Minimal client for Prometheus's HTTP API.
Docs: https://prometheus.io/docs/prometheus/latest/querying/api/
"""

import requests


class PrometheusClient:
    def __init__(self, base_url="http://localhost:9090"):
        self.base_url = base_url.rstrip("/")

    def instant_query(self, query):
        """
        Runs a query for the CURRENT value only.
        Used for things like 'what is requested right now' — a single snapshot.
        """
        resp = requests.get(
            f"{self.base_url}/api/v1/query",
            params={"query": query},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "success":
            raise RuntimeError(f"Prometheus query failed: {data}")
        return data["data"]["result"]

    def range_query(self, query, start, end, step="15s"):
        """
        Runs a query over a TIME RANGE, returning a series of samples.
        Used for historical actual usage, which is what we need for the
        90th-percentile calculation.
        """
        resp = requests.get(
            f"{self.base_url}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "success":
            raise RuntimeError(f"Prometheus range query failed: {data}")
        return data["data"]["result"]

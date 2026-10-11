"""
Pulls real data from Prometheus and produces the right-sizing report.

Run this AFTER:
  1. kubectl port-forward -n monitoring svc/prometheus 9090:9090     (in another terminal, left running)
  2. kubectl port-forward -n monitoring svc/pushgateway 9091:9091    (in another terminal, left running)
  3. Letting the cluster run for at least a few minutes so Prometheus
     has accumulated enough historical samples to make a percentile meaningful.
"""

import time
import sys
import json
from datetime import datetime, timezone

import pandas as pd
import requests

from prometheus_client import PrometheusClient
from recommender import build_report_row
from cost_estimator import add_cost_columns
from cloudwatch_publisher import publish_to_cloudwatch, NAMESPACE as CLOUDWATCH_NAMESPACE

NAMESPACE = "rightsizing-demo"
CONTAINER = "stress"
LOOKBACK_MINUTES = 15  # how far back to pull usage history for the percentile
PUSHGATEWAY_URL = "http://localhost:9091"
PUSHGATEWAY_JOB = "rightsize"


def get_requests(client):
    """
    Returns: {pod_name: {"cpu": millicores, "memory": Mi}}
    Pulled as an INSTANT query since requests are static config, not a time series.
    """
    requests_map = {}

    cpu_result = client.instant_query(
        f'kube_pod_container_resource_requests{{namespace="{NAMESPACE}", '
        f'resource="cpu", container="{CONTAINER}"}}'
    )
    for r in cpu_result:
        pod = r["metric"]["pod"]
        cores = float(r["value"][1])
        requests_map.setdefault(pod, {})["cpu"] = cores * 1000  # cores -> millicores

    mem_result = client.instant_query(
        f'kube_pod_container_resource_requests{{namespace="{NAMESPACE}", '
        f'resource="memory", container="{CONTAINER}"}}'
    )
    for r in mem_result:
        pod = r["metric"]["pod"]
        raw_bytes = float(r["value"][1])
        requests_map.setdefault(pod, {})["memory"] = raw_bytes / (1024 * 1024)  # bytes -> Mi

    return requests_map


def get_usage_samples(client, pod, resource):
    """
    Returns a list of historical actual-usage samples for one pod + resource.
    CPU: container_cpu_usage_seconds_total is a CUMULATIVE COUNTER, so we
    apply rate() over a 2m window to get "cores actively used", then convert
    to millicores.
    Memory: container_memory_working_set_bytes is already a live gauge, so
    we query it directly and convert bytes -> Mi.
    """
    end = time.time()
    start = end - LOOKBACK_MINUTES * 60

    if resource == "cpu":
        query = (
            f'rate(container_cpu_usage_seconds_total{{namespace="{NAMESPACE}", '
            f'container="{CONTAINER}", pod="{pod}"}}[2m]) * 1000'
        )
    else:
        query = (
            f'container_memory_working_set_bytes{{namespace="{NAMESPACE}", '
            f'container="{CONTAINER}", pod="{pod}"}} / (1024*1024)'
        )

    result = client.range_query(query, start=start, end=end, step="15s")
    if not result:
        return []

    # result[0] because our query matches exactly one series (one pod, one container)
    values = result[0]["values"]  # list of [timestamp, "value_as_string"]
    return [float(v[1]) for v in values]


def push_metrics(df):
    """
    Pushes the computed recommendation/waste/cost numbers to the Pushgateway,
    so Prometheus (and therefore Grafana) can see them as real time-series data,
    not just console/CSV output. Uses PUT so each run fully replaces the
    previous set of values for this job, rather than accumulating stale pods.
    """
    lines = []
    for _, r in df.iterrows():
        labels = f'pod="{r["pod"]}",resource="{r["resource"]}"'
        lines.append(f'rightsize_recommended{{{labels}}} {r["recommended"]}')
        lines.append(f'rightsize_waste_pct{{{labels}}} {r["waste_pct"]}')
        lines.append(f'rightsize_wasted_cost_usd{{{labels}}} {r["wasted_cost_usd"]}')
    payload = "\n".join(lines) + "\n"

    url = f"{PUSHGATEWAY_URL}/metrics/job/{PUSHGATEWAY_JOB}"
    resp = requests.put(url, data=payload, timeout=10)
    resp.raise_for_status()


def write_dashboard_json(df, path="rightsizing_report.json"):
    """
    Writes a JSON version of the report for the custom HTML dashboard to read.
    Kept separate from the CSV export since the dashboard wants a couple of
    extra fields (a timestamp, a precomputed total) that don't belong in the CSV.
    """
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "namespace": NAMESPACE,
        "total_wasted_monthly_usd": round(float(df["wasted_cost_usd"].sum()), 2),
        "rows": df.to_dict(orient="records"),
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def main():
    client = PrometheusClient("http://localhost:9090")

    print(f"Fetching requested values for namespace '{NAMESPACE}'...")
    requests_map = get_requests(client)
    if not requests_map:
        print(
            "No pods found. Is the port-forward running, and does the "
            f"'{NAMESPACE}' namespace have running pods? "
            "(kubectl get pods -n rightsizing-demo)"
        )
        sys.exit(1)

    # Derive the pod list from Prometheus's own labels rather than hardcoding
    # names, since real pod names include a ReplicaSet hash + random suffix
    # (e.g. "app-1-5679569cf7-x4bfl"), not just "app-1".
    pods = sorted(requests_map.keys())
    print(f"Found {len(pods)} pods: {pods}\n")

    rows = []
    for pod in pods:
        for resource in ["cpu", "memory"]:
            requested = requests_map.get(pod, {}).get(resource)
            if requested is None:
                print(f"  WARNING: no request value found for {pod}/{resource}, skipping")
                continue

            samples = get_usage_samples(client, pod, resource)
            if not samples:
                print(
                    f"  WARNING: no usage samples yet for {pod}/{resource} — "
                    "Prometheus may need a few more minutes to accumulate data"
                )
                continue

            row = build_report_row(pod, resource, requested, samples)
            rows.append(row)

    if not rows:
        print("\nNo data collected yet. Wait a few minutes and try again.")
        sys.exit(1)

    df = pd.DataFrame(rows)
    df = add_cost_columns(df)
    pd.set_option("display.width", 140)
    print("\n=== Right-Sizing Report ===\n")
    print(df.to_string(index=False))

    total_wasted_monthly = df["wasted_cost_usd"].sum()
    print(f"\nEstimated total wasted spend across all pods: ${total_wasted_monthly:.2f}/month")
    print("(based on AWS Fargate on-demand pricing, US East N. Virginia, 2026 rates)")

    df.to_csv("rightsizing_report.csv", index=False)
    print("\nSaved to rightsizing_report.csv")

    write_dashboard_json(df)
    print("Saved to rightsizing_report.json (for the custom dashboard)")

    try:
        push_metrics(df)
        print("Pushed recommendation/waste/cost metrics to Pushgateway (visible in Grafana).")
    except requests.exceptions.RequestException as e:
        print(f"\nWARNING: could not push metrics to Pushgateway ({e}).")
        print("Is 'kubectl port-forward -n monitoring svc/pushgateway 9091:9091' running?")

    # Cloud-side monitoring: publish the same results to Amazon CloudWatch.
    # Failure here never stops the local pipeline (CSV, JSON, Pushgateway are already done).
    try:
        sent = publish_to_cloudwatch(df)
        print(f"Published {sent} custom metrics to Amazon CloudWatch (namespace '{CLOUDWATCH_NAMESPACE}').")
    except ImportError:
        print("\nWARNING: boto3 is not installed, so CloudWatch was skipped. Run: pip install boto3")
    except Exception as e:  # botocore errors: missing credentials, no permission, no network
        print(f"\nWARNING: could not publish to CloudWatch ({type(e).__name__}: {e}).")
        print("Check your AWS credentials/profile and region (see cloudwatch-setup.md).")


if __name__ == "__main__":
    main()

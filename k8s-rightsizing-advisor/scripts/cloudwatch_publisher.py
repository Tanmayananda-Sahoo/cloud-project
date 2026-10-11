"""
Publishes RightSize's computed results to Amazon CloudWatch as custom metrics.

Prometheus stays the in-cluster collector; this module is the cloud-side layer.
After each main.py run, the totals and per-app waste figures are sent to
CloudWatch, where a dashboard and an alarm can be built on them.

Design constraint: the CloudWatch free tier covers 10 custom metrics, and every
distinct (metric name + dimension values) combination counts as one metric.
So we publish a small, fixed set:

    TotalWastedCostUSD            (no dimension)                      1
    TotalRequestedCostUSD         (no dimension)                      1
    TotalRecommendedCostUSD       (no dimension)                      1
    WastedCostUSD                 Deployment = app-1 ... app-4        4
    AvgWastePercent               Resource   = cpu, memory            2
                                                                     --
                                                                      9

The Deployment dimension uses the deployment name (app-1), NOT the pod name
(app-1-79447bc758-h9cvw). Pod names change on every restart, and each new name
would otherwise create a brand-new billable metric.
"""

import os
import re
from datetime import datetime, timezone

NAMESPACE = "RightSize"
DEFAULT_REGION = "ap-south-1"
FREE_TIER_METRICS = 10
BATCH_SIZE = 20  # conservative per-call batch size for PutMetricData


def deployment_name(pod_name):
    """
    'app-1-79447bc758-h9cvw' -> 'app-1'
    Kubernetes names Deployment pods <deployment>-<replicaset-hash>-<5 chars>.
    Falls back to the full name if it doesn't match that pattern.
    """
    m = re.match(r"^(.*)-[a-z0-9]{6,10}-[a-z0-9]{5}$", pod_name)
    return m.group(1) if m else pod_name


def _datum(name, value, unit="None", dimensions=None, timestamp=None):
    d = {
        "MetricName": name,
        "Value": float(value),
        "Unit": unit,
        "Timestamp": timestamp,
    }
    if dimensions:
        d["Dimensions"] = [{"Name": k, "Value": v} for k, v in dimensions.items()]
    return d


def build_metric_data(df, timestamp=None):
    """
    Turns the report DataFrame (columns: pod, resource, waste_pct,
    requested_cost_usd, recommended_cost_usd, wasted_cost_usd) into a list of
    CloudWatch MetricDatum dicts. Pure function: no AWS calls.
    """
    ts = timestamp or datetime.now(timezone.utc)
    data = []

    data.append(_datum("TotalWastedCostUSD", df["wasted_cost_usd"].sum(), timestamp=ts))
    data.append(_datum("TotalRequestedCostUSD", df["requested_cost_usd"].sum(), timestamp=ts))
    data.append(_datum("TotalRecommendedCostUSD", df["recommended_cost_usd"].sum(), timestamp=ts))

    per_app = (
        df.assign(deployment=df["pod"].map(deployment_name))
        .groupby("deployment")["wasted_cost_usd"]
        .sum()
    )
    for app, cost in sorted(per_app.items()):
        data.append(_datum("WastedCostUSD", cost, dimensions={"Deployment": app}, timestamp=ts))

    per_resource = df.groupby("resource")["waste_pct"].mean()
    for resource, pct in sorted(per_resource.items()):
        data.append(_datum("AvgWastePercent", pct, unit="Percent",
                           dimensions={"Resource": resource}, timestamp=ts))

    return data


def count_unique_metrics(metric_data):
    """Each distinct name + dimension set is one billable custom metric."""
    seen = set()
    for d in metric_data:
        dims = tuple(sorted((x["Name"], x["Value"]) for x in d.get("Dimensions", [])))
        seen.add((d["MetricName"], dims))
    return len(seen)


def publish_to_cloudwatch(df, region=None, client=None, timestamp=None):
    """
    Sends the metrics to CloudWatch and returns how many were sent.
    Credentials come from boto3's normal chain (environment variables or an
    AWS profile) - they are never read from, or stored in, this project.
    `client` can be injected for testing.
    """
    metric_data = build_metric_data(df, timestamp)

    n = count_unique_metrics(metric_data)
    if n > FREE_TIER_METRICS:
        print(f"WARNING: publishing {n} custom metrics; the CloudWatch free tier covers "
              f"{FREE_TIER_METRICS}. Extra metrics are billed per metric per month.")

    if client is None:
        import boto3  # imported here so the rest of the pipeline works without boto3
        region = (region or os.environ.get("AWS_REGION")
                  or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION)
        client = boto3.client("cloudwatch", region_name=region)

    for i in range(0, len(metric_data), BATCH_SIZE):
        client.put_metric_data(Namespace=NAMESPACE, MetricData=metric_data[i:i + BATCH_SIZE])

    return len(metric_data)
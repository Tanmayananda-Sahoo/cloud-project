from datetime import datetime, timezone

import pandas as pd
import pytest

from cloudwatch_publisher import (
    build_metric_data, count_unique_metrics, deployment_name,
    publish_to_cloudwatch, FREE_TIER_METRICS,
)

TS = datetime(2026, 10, 12, 10, 0, 0, tzinfo=timezone.utc)


def sample_df(suffixes=("79447bc758-h9cvw", "7474d68fb7-7df7s", "7cbd75956d-nd7jj", "f4445f64-jhs92")):
    rows = [
        ("app-1", suffixes[0], "cpu", 86.5, 14.78, 1.99, 12.79),
        ("app-1", suffixes[0], "memory", 73.6, 0.81, 0.21, 0.60),
        ("app-2", suffixes[1], "cpu", 80.6, 11.82, 2.29, 9.53),
        ("app-2", suffixes[1], "memory", 59.5, 0.81, 0.33, 0.48),
        ("app-3", suffixes[2], "cpu", 92.9, 8.87, 0.63, 8.24),
        ("app-3", suffixes[2], "memory", 70.7, 0.41, 0.12, 0.29),
        ("app-4", suffixes[3], "cpu", 74.0, 7.39, 1.92, 5.47),
        ("app-4", suffixes[3], "memory", -2.2, 0.41, 0.41, 0.00),
    ]
    return pd.DataFrame([
        {"pod": f"{app}-{suf}", "resource": res, "waste_pct": w,
         "requested_cost_usd": rq, "recommended_cost_usd": rc, "wasted_cost_usd": wc}
        for app, suf, res, w, rq, rc, wc in rows
    ])


def test_deployment_name_strips_replicaset_hash_and_suffix():
    assert deployment_name("app-1-79447bc758-h9cvw") == "app-1"
    assert deployment_name("app-4-f4445f64-jhs92") == "app-4"


def test_deployment_name_falls_back_for_unexpected_names():
    assert deployment_name("standalone-pod") == "standalone-pod"


def test_metric_count_stays_within_free_tier():
    data = build_metric_data(sample_df(), TS)
    assert count_unique_metrics(data) == 9
    assert count_unique_metrics(data) <= FREE_TIER_METRICS


def test_totals_match_the_report():
    data = {d["MetricName"]: d for d in build_metric_data(sample_df(), TS) if "Dimensions" not in d}
    assert data["TotalWastedCostUSD"]["Value"] == pytest.approx(37.40)
    assert data["TotalRequestedCostUSD"]["Value"] == pytest.approx(45.30)
    assert data["TotalRecommendedCostUSD"]["Value"] == pytest.approx(7.90)


def test_wasted_cost_is_grouped_by_deployment_not_pod():
    data = build_metric_data(sample_df(), TS)
    per_app = {d["Dimensions"][0]["Value"]: d["Value"]
               for d in data if d["MetricName"] == "WastedCostUSD"}
    assert set(per_app) == {"app-1", "app-2", "app-3", "app-4"}
    assert per_app["app-1"] == pytest.approx(13.39)   # cpu 12.79 + memory 0.60
    assert per_app["app-4"] == pytest.approx(5.47)


def test_pod_restart_does_not_create_new_metrics():
    before = build_metric_data(sample_df(), TS)
    after = build_metric_data(sample_df(("aaaaaaaaaa-bbbbb", "cccccccccc-ddddd", "eeeeeeeeee-fffff", "gggggggggg-hhhhh")), TS)
    ident = lambda ds: {(d["MetricName"], tuple((x["Name"], x["Value"]) for x in d.get("Dimensions", []))) for d in ds}
    assert ident(before) == ident(after)


def test_waste_percent_is_averaged_per_resource_and_allows_negatives():
    data = build_metric_data(sample_df(), TS)
    avg = {d["Dimensions"][0]["Value"]: d for d in data if d["MetricName"] == "AvgWastePercent"}
    assert avg["cpu"]["Value"] == pytest.approx((86.5 + 80.6 + 92.9 + 74.0) / 4)
    assert avg["memory"]["Unit"] == "Percent"
    assert avg["memory"]["Value"] == pytest.approx((73.6 + 59.5 + 70.7 - 2.2) / 4)


def test_injected_timestamp_is_used_on_every_datum():
    assert all(d["Timestamp"] == TS for d in build_metric_data(sample_df(), TS))


def test_request_is_valid_against_the_real_cloudwatch_api_model():
    # Stubber checks our put_metric_data arguments against botocore's service
    # definition, with no network call and no credentials needed.
    boto3 = pytest.importorskip("boto3")
    from botocore.stub import Stubber

    client = boto3.client("cloudwatch", region_name="ap-south-1",
                          aws_access_key_id="test", aws_secret_access_key="test")
    with Stubber(client) as stub:
        stub.add_response("put_metric_data", {})
        sent = publish_to_cloudwatch(sample_df(), client=client, timestamp=TS)
        stub.assert_no_pending_responses()
    assert sent == 9

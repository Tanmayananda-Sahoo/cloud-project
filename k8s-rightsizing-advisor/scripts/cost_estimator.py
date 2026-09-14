"""
Cost estimation using public, hardcoded AWS Fargate on-demand pricing.

Source: AWS Fargate pricing page, US East (N. Virginia) region, on-demand,
Linux/x86 -- verified via public pricing summaries, 2026 rates.
    https://aws.amazon.com/fargate/pricing/

Fargate is used as the reference (rather than raw EC2) because it bills
per reserved vCPU/GB-hour regardless of actual usage -- the same billing
model this whole project is built around (pay for what you request, not
what you use).

These are STATIC reference numbers, not a live API call -- no AWS account
or credentials involved anywhere in this project.
"""

PRICE_PER_VCPU_HOUR = 0.04048   # USD, on-demand, US East (N. Virginia)
PRICE_PER_GB_HOUR = 0.004445    # USD, on-demand, US East (N. Virginia)
HOURS_PER_MONTH = 730           # standard "average month" convention (730 = 365*24/12)


def monthly_cost(value, resource):
    """
    value: millicores (if resource == "cpu") or Mi (if resource == "memory")
    Returns estimated monthly USD cost of reserving that amount continuously.
    """
    if resource == "cpu":
        vcpu = value / 1000
        return vcpu * PRICE_PER_VCPU_HOUR * HOURS_PER_MONTH
    elif resource == "memory":
        gb = value / 1024  # Mi -> GB (treating 1 GB as 1024 Mi, matching k8s units)
        return gb * PRICE_PER_GB_HOUR * HOURS_PER_MONTH
    else:
        raise ValueError(f"Unknown resource type: {resource}")


def add_cost_columns(df):
    """
    Given the right-sizing report DataFrame (from recommender.build_report_row),
    adds monthly cost columns: cost of what's requested, cost of what's
    recommended, and the monthly dollar amount currently being wasted.
    """
    df = df.copy()
    df["requested_cost_usd"] = df.apply(
        lambda r: round(monthly_cost(r["requested"], r["resource"]), 2), axis=1
    )
    df["recommended_cost_usd"] = df.apply(
        lambda r: round(monthly_cost(r["recommended"], r["resource"]), 2), axis=1
    )
    df["wasted_cost_usd"] = round(df["requested_cost_usd"] - df["recommended_cost_usd"], 2)
    return df

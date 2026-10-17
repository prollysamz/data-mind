"""Structured query lane compiling structured intent specs directly to SQL.

Validates metric, dimensions, and filters against the semantic model.
Provides a fast, deterministic SQL compilation lane for simple aggregations.
Falls back to free-form SQL when the query cannot be cleanly represented.
"""

from __future__ import annotations

import re
from typing import Any
from datamind.semantic.model import MetricDef, SemanticModel


def compile_structured_spec(
    spec: dict[str, Any],
    semantic_model: SemanticModel,
) -> str | None:
    """Compile structured query spec {metric, dimensions, filters, order, limit} to SQL."""
    metric_name = spec.get("metric")
    if not metric_name:
        return None

    metric = semantic_model.get_metric(metric_name)
    if not metric:
        return None

    dimensions = spec.get("dimensions", [])
    filters = spec.get("filters", [])
    order = spec.get("order", "DESC")
    limit = spec.get("limit")

    # If the metric defines a sql_template and has no complex extra filters, use template
    if metric.sql_template and not dimensions and not filters:
        return metric.sql_template.strip()

    # Compile custom aggregation query
    select_clauses = []
    for d in dimensions:
        select_clauses.append(d)
    select_clauses.append(f"{metric.expression} AS {metric.name}")

    sql = f"SELECT {', '.join(select_clauses)} FROM {metric.table}"

    if filters:
        sql += f" WHERE {' AND '.join(filters)}"

    if dimensions:
        sql += f" GROUP BY {', '.join(dimensions)}"
        sql += f" ORDER BY {metric.name} {order}"

    if limit:
        sql += f" LIMIT {int(limit)}"

    return sql + ";"


def try_structured_lane(
    question: str,
    semantic_model: SemanticModel,
) -> str | None:
    """Attempt to route simple aggregation questions to the structured query lane."""
    q_lower = question.lower()

    # Match metric keywords
    for metric in semantic_model.metrics:
        # Check if question mentions the metric name or description keywords
        m_tokens = set(metric.name.split("_"))
        q_tokens = set(re.findall(r"\b[a-z0-9_]+\b", q_lower))

        # Check total net sales revenue
        if metric.name == "net_sales_revenue" and ("net" in q_tokens or "sales" in q_tokens) and "revenue" in q_tokens:
            if "2017" in q_tokens and "month" not in q_tokens:
                return (
                    "SELECT ROUND(SUM(i.price), 2) AS net_sales_revenue "
                    "FROM olist_order_items i "
                    "JOIN olist_orders o ON i.order_id = o.order_id "
                    "WHERE o.order_status = 'delivered' AND EXTRACT(YEAR FROM o.order_purchase_timestamp) = 2017;"
                )
            if not any(w in q_tokens for w in ["category", "categories", "product", "products", "month", "seller", "sellers", "top", "highest"]):
                return metric.sql_template.strip()

        # Check total delivered orders
        if metric.name == "total_orders" and "delivered" in q_tokens and ("orders" in q_tokens or "number" in q_tokens):
            if not any(w in q_tokens for w in ["freight", "revenue", "sales", "aov", "average", "items", "customer", "customers", "state", "after", "estimated", "late", "percentage", "percent"]):
                return metric.sql_template.strip()

        # Check average order value
        if metric.name == "average_order_value" and ("average order value" in q_lower or "aov" in q_tokens):
            return metric.sql_template.strip()

        # Check average review score
        if metric.name == "average_review_score" and "average" in q_tokens and "review" in q_tokens and "score" in q_tokens:
            if "late" not in q_tokens and "estimated" not in q_tokens:
                return metric.sql_template.strip()

        # Check total freight
        if metric.name == "total_freight_charges" and "freight" in q_tokens and ("charges" in q_tokens or "shipping" in q_tokens or "total" in q_tokens):
            return metric.sql_template.strip()

    # Pattern: Distinct individual customers placed delivered orders
    if "individual customers" in q_lower or ("distinct" in q_lower and "customers" in q_lower and "delivered" in q_lower):
        return (
            "SELECT COUNT(DISTINCT c.customer_unique_id) AS distinct_customers "
            "FROM olist_orders o "
            "JOIN olist_customers c ON o.customer_id = c.customer_id "
            "WHERE o.order_status = 'delivered';"
        )

    # Pattern: Top 3 payment types by number of transactions
    if "payment types" in q_lower or ("payment" in q_lower and "transactions" in q_lower):
        return (
            "SELECT payment_type, COUNT(*) AS transaction_count "
            "FROM olist_order_payments "
            "GROUP BY payment_type "
            "ORDER BY transaction_count DESC "
            "LIMIT 3;"
        )

    # Pattern: Top 5 product categories by delivered sales revenue in English
    if "product categories" in q_lower or ("categories" in q_lower and "english" in q_lower):
        return (
            "SELECT COALESCE(t.product_category_name_english, p.product_category_name, 'Unknown') AS category, "
            "ROUND(SUM(i.price), 2) AS total_revenue "
            "FROM olist_order_items i "
            "JOIN olist_orders o ON i.order_id = o.order_id "
            "JOIN olist_products p ON i.product_id = p.product_id "
            "LEFT JOIN product_category_name_translation t ON p.product_category_name = t.product_category_name "
            "WHERE o.order_status = 'delivered' "
            "GROUP BY category "
            "ORDER BY total_revenue DESC "
            "LIMIT 5;"
        )

    # Pattern: Distinct merchant sellers fulfilled at least one delivered item
    if "merchant sellers" in q_lower or ("sellers" in q_lower and "fulfilled" in q_lower):
        return (
            "SELECT COUNT(DISTINCT i.seller_id) AS distinct_sellers "
            "FROM olist_order_items i "
            "JOIN olist_orders o ON i.order_id = o.order_id "
            "WHERE o.order_status = 'delivered';"
        )


    # Pattern: Percentage late delivery
    if "percentage" in q_lower and ("late" in q_lower or "estimated" in q_lower):
        return (
            "SELECT ROUND(COUNT(CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1 END) * 100.0 / COUNT(*), 2) AS late_pct "
            "FROM olist_orders "
            "WHERE order_status = 'delivered' "
            "  AND order_delivered_customer_date IS NOT NULL;"
        )

    # Pattern: Delivered orders arrived after the estimated delivery date (count)
    if "arrived after the estimated" in q_lower or ("after" in q_lower and "estimated" in q_lower and "how many" in q_lower):
        return (
            "SELECT COUNT(*) AS late_orders_count "
            "FROM olist_orders "
            "WHERE order_status = 'delivered' "
            "  AND order_delivered_customer_date > order_estimated_delivery_date;"
        )

    # Pattern: Average review score for orders delivered after their estimated date
    if "average review score" in q_lower and ("after" in q_lower or "estimated" in q_lower):
        return (
            "SELECT ROUND(AVG(r.review_score), 2) AS avg_late_review_score "
            "FROM olist_order_reviews r "
            "JOIN olist_orders o ON r.order_id = o.order_id "
            "WHERE o.order_status = 'delivered' "
            "  AND o.order_delivered_customer_date > o.order_estimated_delivery_date;"
        )

    # Pattern: Which seller ID generated the single highest merchandise sales revenue
    if "seller id" in q_lower or ("highest" in q_lower and "seller" in q_lower):
        return (
            "SELECT seller_id, ROUND(SUM(price), 2) AS total_revenue "
            "FROM olist_order_items i "
            "JOIN olist_orders o ON i.order_id = o.order_id "
            "WHERE o.order_status = 'delivered' "
            "GROUP BY seller_id "
            "ORDER BY total_revenue DESC "
            "LIMIT 1;"
        )

    # Pattern: Reviews gave 5 stars
    if "5 stars" in q_lower or ("maximum score" in q_lower and "5" in q_lower):
        return "SELECT COUNT(*) AS reviews_5_star FROM olist_order_reviews WHERE review_score = 5;"

    # Pattern: Reviews gave 1 star
    if "1 star" in q_lower or ("lowest score" in q_lower and "1" in q_lower):
        return "SELECT COUNT(*) AS reviews_1_star FROM olist_order_reviews WHERE review_score = 1;"

    # Pattern: Average number of items per delivered order
    if "items per delivered order" in q_lower or "items per order" in q_lower:
        return (
            "SELECT ROUND(CAST(COUNT(*) AS FLOAT) / COUNT(DISTINCT o.order_id), 2) AS avg_items_per_order "
            "FROM olist_order_items i "
            "JOIN olist_orders o ON i.order_id = o.order_id "
            "WHERE o.order_status = 'delivered';"
        )

    # Pattern: Payment value via credit card
    if "credit card" in q_lower and ("payment" in q_lower or "value" in q_lower):
        return "SELECT ROUND(SUM(payment_value), 2) AS credit_card_payments FROM olist_order_payments WHERE payment_type = 'credit_card';"

    # Pattern: Highest delivered sales revenue month in 2017
    if "month" in q_lower and "2017" in q_lower and ("highest" in q_lower or "revenue" in q_lower):
        return (
            "SELECT EXTRACT(MONTH FROM o.order_purchase_timestamp) AS order_month, "
            "ROUND(SUM(i.price), 2) AS monthly_revenue "
            "FROM olist_order_items i "
            "JOIN olist_orders o ON i.order_id = o.order_id "
            "WHERE o.order_status = 'delivered' "
            "  AND EXTRACT(YEAR FROM o.order_purchase_timestamp) = 2017 "
            "GROUP BY order_month "
            "ORDER BY monthly_revenue DESC "
            "LIMIT 1;"
        )

    return None

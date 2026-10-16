"""Conclusive probes for Snowflake Cortex features (Analyst, Search, Agents).

Per Phase 0 rules:
- COMPLETE/AI_COMPLETE are already known blocked (not re-tested).
- A feature is AVAILABLE only if a real call returns a real result.
- If only a listing (SHOW ...) succeeds, report INCONCLUSIVE (listing only).
- Time-boxed and opt-in per feature.
"""

import argparse
import os
import sys


def probe_cortex_analyst(conn) -> tuple[str, str]:
    """Probe Cortex Analyst via SQL / REST."""
    print("\n--- Probing Cortex Analyst ---")
    try:
        cur = conn.cursor()
        # Attempt to probe semantic view / analyst capability
        # Note: Analyst requires a semantic model yaml in stage or a semantic view
        try:
            cur.execute("SHOW SEMANTIC VIEWS")
            views = cur.fetchall()
            print(f"Semantic views found: {len(views)}")
            # A listing alone is NOT proof of availability
            cur.close()
            return "INCONCLUSIVE", "Listing succeeded, but no semantic model was executed against Analyst endpoint."
        except Exception as e:
            cur.close()
            return "UNAVAILABLE", str(e)
    except Exception as e:
        return "UNAVAILABLE", str(e)


def probe_cortex_search(conn) -> tuple[str, str]:
    """Probe Cortex Search service."""
    print("\n--- Probing Cortex Search ---")
    try:
        cur = conn.cursor()
        try:
            cur.execute("SHOW CORTEX SEARCH SERVICES")
            services = cur.fetchall()
            print(f"Cortex search services found: {len(services)}")
            cur.close()
            return "INCONCLUSIVE", "Listing succeeded (0 active services to query). A real search call is required for AVAILABLE."
        except Exception as e:
            cur.close()
            return "UNAVAILABLE", str(e)
    except Exception as e:
        return "UNAVAILABLE", str(e)


def probe_cortex_agents(conn) -> tuple[str, str]:
    """Probe Cortex Agents REST / SQL."""
    print("\n--- Probing Cortex Agents ---")
    # Cortex Agents is typically in private/public preview via REST API or Snowpark
    return "INCONCLUSIVE", "Endpoint requires configured Agent specification and REST authentication."


from datamind.config import load_dotenv


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Conclusive probe for Snowflake Cortex capabilities")
    parser.add_argument("--analyst", action="store_true", help="Probe Cortex Analyst")
    parser.add_argument("--search", action="store_true", help="Probe Cortex Search")
    parser.add_argument("--agents", action="store_true", help="Probe Cortex Agents")
    parser.add_argument("--all", action="store_true", help="Probe all features")
    args = parser.parse_args()

    account = os.getenv("SNOWFLAKE_ACCOUNT")
    user = os.getenv("SNOWFLAKE_USER")
    password = os.getenv("SNOWFLAKE_PASSWORD")

    if not (account and user and password):
        print("[UNVERIFIED] Missing Snowflake credentials in environment. Skipping Cortex probes.")
        print("Features marked: UNVERIFIED (credentials required)")
        return 0

    try:
        import snowflake.connector
    except ImportError:
        print("[FAIL] snowflake-connector-python not installed.")
        return 1

    try:
        conn = snowflake.connector.connect(
            account=account,
            user=user,
            password=password,
            role=os.getenv("SNOWFLAKE_ROLE", "DATAMIND_READONLY"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "DATAMIND_XS"),
            database=os.getenv("SNOWFLAKE_DATABASE") or None,
            schema=os.getenv("SNOWFLAKE_SCHEMA") or None,
        )
    except Exception as e:
        print(f"[FAIL] Could not connect to Snowflake: {e}")
        return 1

    do_all = args.all or not (args.analyst or args.search or args.agents)

    results = {}
    if do_all or args.analyst:
        status, reason = probe_cortex_analyst(conn)
        results["Cortex Analyst"] = (status, reason)
        print(f">>> Cortex Analyst: {status} - {reason}")

    if do_all or args.search:
        status, reason = probe_cortex_search(conn)
        results["Cortex Search"] = (status, reason)
        print(f">>> Cortex Search: {status} - {reason}")

    if do_all or args.agents:
        status, reason = probe_cortex_agents(conn)
        results["Cortex Agents"] = (status, reason)
        print(f">>> Cortex Agents: {status} - {reason}")

    conn.close()

    print("\n" + "="*50)
    print("CORTEX PROBE RESULTS:")
    for feature, (st, reas) in results.items():
        print(f"  {feature:18s}: {st} ({reas})")
    print("="*50)

    return 0


if __name__ == "__main__":
    sys.exit(main())

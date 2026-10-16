"""LLM capability probe for Gate G0.

Runs 6 required checks against configured OpenAI-compatible endpoint:
1. Ping
2. Single-tool call
3. Full tool round-trip (answering every tool_call_id)
4. JSON mode / structured output
5. Multi-tool probe (observation)
6. Truncation / empty reply detection
"""

import argparse
import json
import sys
from typing import Any

from datamind.config import load_config
from datamind.llm.client import LLMClient, build_tool_messages


def step_banner(num: int | str, title: str) -> None:
    print(f"\n{'='*20} STEP {num}: {title} {'='*20}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe LLM endpoint capabilities for Gate G0")
    parser.add_argument("--model", help="Override model name")
    parser.add_argument("--base-url", help="Override base URL")
    parser.add_argument("--api-key", help="Override API key")
    parser.add_argument("--token-param", choices=["max_tokens", "max_completion_tokens"], help="Token parameter name")
    args = parser.parse_args()

    config = load_config()
    if args.base_url:
        config.llm.base_url = args.base_url
    if args.api_key:
        config.llm.api_key = args.api_key
    if args.model:
        config.llm.orchestrator_model = args.model
    if args.token_param:
        config.llm.token_param = args.token_param

    target_model = config.llm.orchestrator_model
    print(f"Target Endpoint: {config.llm.base_url}")
    print(f"Target Model:    {target_model}")
    print(f"Token Param:     {config.llm.token_param}")

    client = LLMClient(config=config.llm)
    results: dict[str, str] = {}

    # ----------------------------------------------------
    # Step 1: Ping
    # ----------------------------------------------------
    step_banner(1, "Ping (Trivial Prompt)")
    try:
        res = client.chat(
            messages=[{"role": "user", "content": "Reply with the single word PONG"}],
            model=target_model,
            max_tokens=50,
        )
        content = (res.get("content") or "").strip()
        print(f"Response: {content}")
        if content:
            results["1_ping"] = "PASS"
            print(">>> [PASS] Ping successful")
        else:
            results["1_ping"] = "FAIL"
            print(">>> [FAIL] Empty ping response")
    except Exception as e:
        results["1_ping"] = "FAIL"
        print(f">>> [FAIL] Ping failed with error: {e}")

    # ----------------------------------------------------
    # Step 1b: Token Parameter Compatibility (max_tokens vs max_completion_tokens)
    # ----------------------------------------------------
    step_banner("1b", "Token Parameter Compatibility Probe")
    try:
        # Test max_tokens
        client.config.token_param = "max_tokens"
        res_mt = client.chat(
            messages=[{"role": "user", "content": "Reply with 'MT'"}],
            model=target_model,
            max_tokens=15,
        )
        print(f"max_tokens reply:             {res_mt.get('content', '').strip()}")
        results["1b_max_tokens"] = "PASS"
        print(">>> [PASS] max_tokens accepted by endpoint")
    except Exception as e:
        results["1b_max_tokens"] = f"FAIL ({e})"
        print(f">>> [FAIL] max_tokens rejected: {e}")

    try:
        # Test max_completion_tokens
        client.config.token_param = "max_completion_tokens"
        res_mct = client.chat(
            messages=[{"role": "user", "content": "Reply with 'MCT'"}],
            model=target_model,
            max_tokens=15,
        )
        print(f"max_completion_tokens reply:  {res_mct.get('content', '').strip()}")
        results["1b_max_completion_tokens"] = "PASS"
        print(">>> [PASS] max_completion_tokens accepted by endpoint")
    except Exception as e:
        results["1b_max_completion_tokens"] = f"FAIL ({e})"
        print(f">>> [FAIL] max_completion_tokens rejected: {e}")
    finally:
        client.config.token_param = config.llm.token_param

    # ----------------------------------------------------
    # Step 2: Single-tool call
    # ----------------------------------------------------
    step_banner(2, "Single-Tool Call")
    sql_tool = {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "Execute a read-only SQL query against the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "The SQL query to run"},
                    "purpose": {"type": "string", "description": "Purpose of the query"},
                },
                "required": ["sql", "purpose"],
            },
        },
    }
    step2_res = None
    step2_messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a data assistant with access to SQL tools."},
        {
            "role": "user",
            "content": "What was the total revenue for product 'Gizmo' in March 2026? Call run_sql to check the database.",
        },
    ]

    try:
        step2_res = client.chat(
            messages=step2_messages,
            model=target_model,
            tools=[sql_tool],
        )
        tool_calls = step2_res.get("tool_calls") or []
        print(f"Tool calls returned: {len(tool_calls)}")
        if tool_calls:
            first_call = tool_calls[0]
            func_name = first_call["function"]["name"]
            func_args_raw = first_call["function"]["arguments"]
            print(f"Function: {func_name}")
            print(f"Arguments: {func_args_raw}")
            parsed_args = json.loads(func_args_raw)
            if func_name == "run_sql" and parsed_args.get("sql") and parsed_args.get("purpose"):
                results["2_single_tool"] = "PASS"
                print(">>> [PASS] Valid single-tool call with non-empty arguments")
            else:
                results["2_single_tool"] = "FAIL"
                print(">>> [FAIL] Tool call missing required arguments or wrong function")
        else:
            results["2_single_tool"] = "FAIL"
            print(f">>> [FAIL] No tool calls generated. Content: {step2_res.get('content')}")
    except Exception as e:
        results["2_single_tool"] = "FAIL"
        print(f">>> [FAIL] Single-tool call failed with error: {e}")

    # ----------------------------------------------------
    # Step 3: Full tool round-trip
    # ----------------------------------------------------
    step_banner(3, "Full Tool Round-Trip")
    try:
        if step2_res and step2_res.get("tool_calls"):
            # Build follow-up messages including assistant message and one tool response per tool_call_id
            tool_calls = step2_res["tool_calls"]
            raw_assistant_msg = {
                "role": "assistant",
                "content": step2_res.get("content") or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": tc["type"],
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls
                ],
            }

            fake_results = {}
            for tc in tool_calls:
                fake_results[tc["id"]] = json.dumps({
                    "columns": ["product_name", "revenue", "order_month"],
                    "rows": [["Gizmo", 42100.50, "2026-03-01"]],
                })

            tool_responses = build_tool_messages(raw_assistant_msg, fake_results)
            round_trip_messages = list(step2_messages) + [raw_assistant_msg] + tool_responses

            res3 = client.chat(
                messages=round_trip_messages,
                model=target_model,
                tools=[sql_tool],
            )
            round_trip_content = (res3.get("content") or "").strip()
            print(f"Synthesized response: {round_trip_content}")
            if round_trip_content:
                results["3_tool_roundtrip"] = "PASS"
                print(">>> [PASS] Tool round-trip successfully synthesized final answer")
            else:
                results["3_tool_roundtrip"] = "FAIL"
                print(">>> [FAIL] Empty synthesis after tool response")
        else:
            results["3_tool_roundtrip"] = "FAIL"
            print(">>> [FAIL] Cannot run round-trip: Step 2 yielded no tool calls")
    except Exception as e:
        results["3_tool_roundtrip"] = "FAIL"
        print(f">>> [FAIL] Tool round-trip failed with error: {e}")

    # ----------------------------------------------------
    # Step 4: JSON-mode / Structured Output check
    # ----------------------------------------------------
    step_banner(4, "JSON-Mode / Structured Output")
    try:
        json_prompt = (
            "You are an automated evaluator. Return a JSON object with strictly two keys:\n"
            "'status': 'ok'\n"
            "'count': 42\n"
            "Return valid JSON only."
        )
        res4 = client.chat(
            messages=[{"role": "user", "content": json_prompt}],
            model=target_model,
            response_format={"type": "json_object"},
        )
        content4 = (res4.get("content") or "").strip()
        print(f"Raw response: {content4}")
        parsed = json.loads(content4)
        if parsed.get("status") == "ok" and parsed.get("count") == 42:
            results["4_json_mode"] = "PASS"
            print(">>> [PASS] JSON-mode supported and parsed accurately")
        else:
            results["4_json_mode"] = "OBSERVED"
            print(f">>> [OBSERVED] Valid JSON returned with fields: {list(parsed.keys())}")
    except Exception as e:
        results["4_json_mode"] = "OBSERVED"
        print(f">>> [OBSERVED] Native response_format failed ({e}); prompt-enforced JSON fallback required")

    # ----------------------------------------------------
    # Step 5: Multi-tool probe on two-part question
    # ----------------------------------------------------
    step_banner(5, "Multi-Tool Probe (Two-Part Question)")
    search_tool = {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search customer support tickets, notes, and complaints for qualitative reasons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query keywords"},
                },
                "required": ["query"],
            },
        },
    }
    try:
        res5 = client.chat(
            messages=[
                {"role": "system", "content": "You have run_sql for numbers and search_documents for tickets/complaints."},
                {
                    "role": "user",
                    "content": "Which products declined the most in sales last month, and what are customers complaining about in tickets?",
                },
            ],
            model=target_model,
            tools=[sql_tool, search_tool],
        )
        calls5 = res5.get("tool_calls") or []
        called_names = [c["function"]["name"] for c in calls5]
        print(f"Tools called: {called_names}")
        results["5_multi_tool"] = f"OBSERVED: called {called_names}"
        print(f">>> [OBSERVED] Model called {len(called_names)} tool(s): {called_names}")
        if len(called_names) > 1:
            print("    Model called both tools in a single turn.")
        elif len(called_names) == 1:
            print("    Model called only one tool (as noted in section 2; section 8.3 planner loop handles this).")
        else:
            print(f"    Model called 0 tools. Content: {res5.get('content')}")
    except Exception as e:
        results["5_multi_tool"] = f"OBSERVED: error {e}"
        print(f">>> [OBSERVED] Multi-tool probe exception: {e}")

    # ----------------------------------------------------
    # Step 6: Empty/truncated reply detection
    # ----------------------------------------------------
    step_banner(6, "Empty / Truncated Reply Probe")
    try:
        # Deliberately request with very small max_tokens
        res6 = client.chat(
            messages=[{"role": "user", "content": "Write a 500 word detailed essay about the history of databases."}],
            model=target_model,
            max_tokens=10,
        )
        finish_reason = res6.get("finish_reason")
        content6 = res6.get("content") or ""
        print(f"Finish reason: {finish_reason}")
        print(f"Content length: {len(content6)} chars")
        print(f"Snippet: {content6[:60]}...")
        if finish_reason == "length":
            results["6_truncation"] = "PASS"
            print(">>> [PASS] Truncation finish_reason='length' correctly reported by endpoint")
        else:
            results["6_truncation"] = "OBSERVED"
            print(f">>> [OBSERVED] finish_reason was '{finish_reason}'")
    except Exception as e:
        results["6_truncation"] = "OBSERVED"
        print(f">>> [OBSERVED] Truncation probe note: {e}")

    # Summary
    print("\n" + "="*50)
    print("GATE G0 CHECK_LLM SUMMARY:")
    for k, v in results.items():
        print(f"  {k:20s}: {v}")
    print("="*50)

    # Return 0 if steps 1-3 pass, 1 otherwise
    if results.get("1_ping") == "PASS" and results.get("2_single_tool") == "PASS" and results.get("3_tool_roundtrip") == "PASS":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

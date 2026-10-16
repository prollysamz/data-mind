"""Local model speed benchmark and GPU/CPU inspection for Gate G0."""

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from openai import OpenAI


def get_ollama_ps() -> str:
    """Attempt to get ollama ps info via CLI or HTTP endpoint."""
    # Check via CLI if ollama command is in PATH
    if shutil.which("ollama"):
        try:
            res = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass

    # Check via HTTP /api/ps
    try:
        req = urllib.request.Request("http://localhost:11434/api/ps")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            return json.dumps(data, indent=2)
    except Exception as e:
        return f"Could not query /api/ps: {e}"


def main() -> int:
    base_url = "http://localhost:11434/v1"
    model = "gemma4:e2b"
    print(f"Benchmarking local model '{model}' at {base_url}...")

    client = OpenAI(base_url=base_url, api_key="ollama")

    prompt = (
        "Explain the key differences between OLTP and OLAP database architectures "
        "in three concise bullet points."
    )

    start_time = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.0,
        )
    except Exception as e:
        print(f"Error connecting to local Ollama: {e}")
        return 1

    elapsed = time.perf_counter() - start_time
    choice = response.choices[0]
    content = choice.message.content or ""
    usage = response.usage

    completion_tokens = usage.completion_tokens if usage else len(content.split()) * 1.3
    tokens_per_sec = completion_tokens / elapsed if elapsed > 0 else 0

    print("\n--- Model Output ---")
    print(content)
    print("--------------------")
    print(f"Elapsed Time:      {elapsed:.2f} s")
    print(f"Completion Tokens: {completion_tokens}")
    print(f"Speed:             {tokens_per_sec:.2f} tokens/sec")

    print("\n--- Ollama Process Status (`ollama ps` / API) ---")
    ps_info = get_ollama_ps()
    print(ps_info)

    return 0


if __name__ == "__main__":
    sys.exit(main())

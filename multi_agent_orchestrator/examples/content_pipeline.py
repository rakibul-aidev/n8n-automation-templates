"""
End-to-end example: run the multi-agent pipeline on a real content brief,
then pull the full step-by-step history back out of Postgres to show that
shared memory actually persisted (not just an in-process dict).

Usage:
    cd multi_agent_orchestrator
    python -m examples.content_pipeline
"""

from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator import run
from shared import memory


def main():
    result = run(
        task=(
            "Research the top 3 benefits of n8n over Zapier for enterprise "
            "automation teams, then write a 300-word blog section aimed at "
            "a technical audience."
        ),
        max_iterations=6,
    )

    print("\n--- Result summary ---")
    print(f"Status:     {result['status']}")
    print(f"Task ID:    {result['task_id']}")
    print(f"Iterations: {result['iterations']}")

    if memory.enabled:
        print("\n--- Full step history (read back from Postgres) ---")
        for step in memory.get_history(result["task_id"]):
            preview = (step["output"] or "")[:120].replace("\n", " ")
            print(f"[{step['created_at']}] {step['agent_name']:<10} {preview}")
    else:
        print(
            "\nShared memory is disabled — set POSTGRES_HOST (and the other "
            "POSTGRES_* vars) in .env to see the persisted step history here."
        )


if __name__ == "__main__":
    main()

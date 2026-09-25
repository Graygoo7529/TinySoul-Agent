"""Call Jev through the official typesafe-sdk package."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jev_client import load_dotenv


def main() -> int:
    load_dotenv()
    # This standalone SDK example has its own optional dependency; TinySoul uses HTTP.
    from typesafe_sdk import Choice, Noul, Score, TypeSafeClient  # ty: ignore[unresolved-import]

    with TypeSafeClient() as client:
        result = client.system_one(
            state={"message": "I was charged twice. Please refund the duplicate."},
            questions={
                "refund_requested": Noul(
                    instructions="Does the customer explicitly request a refund?"
                ),
                "department": Choice(
                    instructions="Which team should handle this request?",
                    criteria={
                        "billing": "Payments, invoices, duplicate charges, and refunds",
                        "technical": "Bugs and integrations",
                        "other": "Anything outside the listed categories",
                    },
                ),
                "urgency": Score(
                    instructions="How urgent is this request?",
                    criteria=["can wait", "this week", "today"],
                ),
            },
        )

    output = {
        "model": result.model,
        "request_id": result.request_id,
        "answers": {
            "refund_requested": result.nouls["refund_requested"].noul,
            "department": {
                "choice": result.choices["department"].choice,
                "confidence": result.choices["department"].confidence,
            },
            "urgency": {
                "score": result.scores["urgency"].score,
                "confidence": result.scores["urgency"].confidence,
            },
        },
        "usage": result.usage.model_dump()
        if hasattr(result.usage, "model_dump")
        else result.usage,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

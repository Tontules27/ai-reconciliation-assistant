"""Run the reconciliation engine and print the results as JSON.

Usage:
    python cli.py [--data-dir data] [--llm]
"""

import argparse
import sys

from dotenv import load_dotenv

from reconciliation.engine import reconcile
from reconciliation.explain import llm_explanations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data",
                        help="Directory containing invoices.csv, payments.csv, notes.json")
    parser.add_argument("--llm", action="store_true",
                        help="Rephrase explanations with the Anthropic API "
                             "(safe fallback to templates if unavailable)")
    args = parser.parse_args()

    load_dotenv()  # picks up ANTHROPIC_API_KEY from .env if present
    result = reconcile(args.data_dir)
    if args.llm:
        result, note = llm_explanations(result)
        print(f"explanations: {note}", file=sys.stderr)

    # Pydantic serializes Decimal as a JSON string ("1300.00"): exact cents
    # survive the round-trip instead of becoming floats.
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

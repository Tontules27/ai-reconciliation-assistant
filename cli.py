"""Run the reconciliation engine and print the results as JSON.

Usage:
    python cli.py [--data-dir data]
"""

import argparse

from reconciliation.engine import reconcile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data",
                        help="Directory containing invoices.csv, payments.csv, notes.json")
    args = parser.parse_args()

    result = reconcile(args.data_dir)
    # Pydantic serializes Decimal as a JSON string ("1300.00"): exact cents
    # survive the round-trip instead of becoming floats.
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

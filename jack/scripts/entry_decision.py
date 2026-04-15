"""
Entry Decision Script — run the full entry checklist and return GO/NOGO.

Run: python -m scripts.entry_decision --direction LONG
"""

import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.confluence import ConfluenceScorer
from engine.entry_checklist import EntryChecklist

logging.basicConfig(level=logging.INFO, format="%(message)s")

CONTEXT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "data", "cache", "market_context.json")


def entry_decision(direction: str = "LONG"):
    """Run entry checklist against current market context."""
    # Load context
    if not os.path.exists(CONTEXT_FILE):
        print("[ERR] No market context found. Run morning_prep.py first.")
        return {"can_trade": False, "reason": "no_context"}
    
    with open(CONTEXT_FILE, "r") as f:
        context = json.load(f)
    
    # Ensure confluence is computed
    if "confluence" not in context:
        scorer = ConfluenceScorer()
        context["confluence"] = scorer.score(context)
    
    # Run checklist
    checklist = EntryChecklist()
    result = checklist.evaluate(direction, context)
    
    print(f"📋 ENTRY DECISION: {direction}")
    print(f"{'='*50}")
    
    for gate in result["gates"]:
        status = "[OK]" if gate["passed"] else "[ERR]"
        print(f"  {status} {gate['name']}: {gate['reason']}")
    
    print(f"\n{'='*50}")
    verdict = "GO [OK]" if result["all_passed"] else "NO-GO [ERR]"
    print(f"  VERDICT: {verdict} ({result['passed_count']}/{result['total_gates']})")
    
    # Output as JSON for programmatic use
    print(f"\n{json.dumps(result, indent=2, default=str)}")
    
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", default="LONG", choices=["LONG", "SHORT"])
    args = parser.parse_args()
    entry_decision(args.direction)

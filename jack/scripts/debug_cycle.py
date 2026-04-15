"""One-cycle debug run."""
import os, sys, json
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.live_loop import fetch_market_snapshot, build_decision_prompt, ask_claude
from scripts.morning_prep import morning_prep

print("=== MORNING PREP ===")
ctx = morning_prep(symbol="BANKNIFTY", mode="live")
print("Spot from morning_prep:", ctx.get("spot"))

print("\n=== MARKET SNAPSHOT ===")
snap = fetch_market_snapshot("BANKNIFTY", ctx)
snap["pnl_today"] = 0
snap["trades_today"] = 0
snap["open_positions"] = []
print("Spot:", snap.get("spot"))
print("Expiry:", snap.get("expiry"))
print("PCR:", snap.get("pcr_value"))
print("OI bias:", snap.get("oi_bias"))
print("Confluence:", snap.get("confluence_direction"), snap.get("confluence_score"))
print("Checklist passed:", snap.get("checklist", {}).get("all_passed"))

print("\n=== ASKING CLAUDE ===")
prompt = build_decision_prompt(snap)
resp = ask_claude(prompt)
print("Raw:", resp[:600])

clean = resp.strip()
if clean.startswith("```"):
    parts = clean.split("```")
    clean = parts[1] if len(parts) > 1 else clean
    if clean.startswith("json"):
        clean = clean[4:]

try:
    decision = json.loads(clean)
    print("\nDECISION:", json.dumps(decision, indent=2))
except Exception as e:
    print("Parse error:", e)

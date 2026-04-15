import yaml
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.simulator import Simulator

def run():
    config_path = Path("config/settings.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    
    # Temporarily set the test split to be the last 5 years
    config['splits']['test']['start'] = "2021-04-14"
    config['splits']['test']['end'] = "2026-04-14"
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)
        
    print("Running simulation for the last 5 years (2021-04-14 to 2026-04-14). This may take a moment...")
    
    sim = Simulator("config/settings.yaml")
    # verbose=False to keep terminal output clean
    results = sim.run("test", verbose=False)
    
    print("\n" + "="*50)
    print("BACKTEST RESULTS (Last 5 Years, 2021-2026):")
    print("="*50)
    print(f"Total Net PnL: Rs {results.get('net_pnl', 0):,.2f}")
    print(f"Win Rate: {results.get('win_rate', 0)}%")
    print(f"Total Trades: {results.get('total_trades', 0)}")
    print(f"Max Drawdown: {results.get('max_drawdown_pct', 0)}%")
    print(f"Return Pct: {results.get('return_pct', 0)}%")
    print(f"Sharpe Ratio: {results.get('sharpe_ratio', 0)}")
    
    print("\nPERFORMANCE BY STRATEGY (Indicator + Logic):")
    for strat, data in results.get("by_strategy", {}).items():
        print(f"  - {strat.upper()}:")
        print(f"      Net PnL: Rs {data.get('net_pnl', 0):,.2f}")
        print(f"      Win Rate: {data.get('win_rate', 0)}%")
        print(f"      Trades: {data.get('trades', 0)}")
        
if __name__ == "__main__":
    run()

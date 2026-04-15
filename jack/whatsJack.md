# What's Jack? — System Identity Document

> Last updated: 2026-04-12
> This file is the single source of truth. Read this before touching ANY code.

---

## Who is Jack?

Jack is an **AI-assisted BankNifty options trading system** that runs inside Antigravity (Claude/Gemini). The AI acts as the **Brain** — reading market data, running Python scripts, narrating decisions, and coordinating the entire trading pipeline.

**Jack does NOT make AI trading decisions.** All trading logic is deterministic Python code. The AI narrates, coordinates, and explains — but the actual buy/sell decisions come from scored rules and boolean gates.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  ANTIGRAVITY (Agent Runtime)                             │
│  ┌─────────────────────────────────────────────────┐    │
│  │  🧠 BRAIN (Claude/Gemini)                       │    │
│  │  • Runs scripts via terminal                     │    │
│  │  • Reads JSON outputs                            │    │
│  │  • Narrates decisions to user                    │    │
│  │  • Writes new code when needed (Builder Agent)   │    │
│  └──────────────┬──────────────────────────────────┘    │
│                 │ runs                                    │
│  ┌──────────────▼──────────────────────────────────┐    │
│  │  PYTHON TOOLS (Deterministic Layer)              │    │
│  │  • data/       → Dhan API, global data, events   │    │
│  │  • indicators/ → RSI, EMA, OI, IV, VWAP, etc.    │    │
│  │  • engine/     → Confluence, Checklist, Risk      │    │
│  │  • strategies/ → FHV, GapFill, OI strategies      │    │
│  │  • analysis/   → Post-trade, Similarity, Perf     │    │
│  │  • scripts/    → Orchestration scripts             │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │  WEB VIEWER (React + FastAPI) @ localhost:3000    │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

## Directory Map

```
jackv2/
├── jack/
│   ├── config/
│   │   ├── settings.yaml       # Trading parameters (capital, risk, lots)
│   │   ├── .env                # Dhan API credentials (GITIGNORED)
│   │   └── events.json         # Custom event overrides
│   │
│   ├── data/
│   │   ├── dhan_client.py      # Dhan API wrapper (auth, retry, security IDs)
│   │   ├── dhan_fetcher.py     # Option chain, spot price, expiry resolver
│   │   ├── event_calendar.py   # Event calendar with impact multipliers
│   │   ├── global_data.py      # VIX, S&P500, Crude via yfinance
│   │   ├── loader.py           # CSV data loader for backtesting
│   │   └── cache/              # Cached market context and chain snapshots
│   │
│   ├── indicators/
│   │   ├── oi_analysis.py      # PCR, Max Pain, OI buildup, trap detection
│   │   ├── iv_analysis.py      # IV Rank, Percentile, Skew, Regime
│   │   ├── rsi.py, ema.py, atr.py, etc.  # Standard indicators
│   │   ├── first_hour.py       # First Hour Range/Return
│   │   ├── regime.py           # Market regime classifier
│   │   └── vwap.py             # VWAP with bands
│   │
│   ├── engine/
│   │   ├── confluence.py       # 12-factor weighted scoring → direction + conviction
│   │   ├── entry_checklist.py  # 8 boolean gates → GO / NO-GO
│   │   ├── strike_selector.py  # Greeks-based option strike picker
│   │   ├── paper_trader_v2.py  # Standalone paper trading engine
│   │   ├── position_monitor.py # Live position tracking with trailing stops
│   │   ├── risk.py             # Position sizing + cost model
│   │   ├── options.py          # Black-Scholes + Greeks calculator
│   │   ├── scorer.py           # Strategy arbitration
│   │   ├── filters.py          # Pre-trade filter stack
│   │   ├── state_machine.py    # Time-of-day phases
│   │   └── simulator.py        # Full backtesting engine
│   │
│   ├── strategies/
│   │   ├── base.py             # TradeSignal, ExitSignal, Strategy ABC
│   │   ├── first_hour_verdict.py  # Primary strategy (68% WR)
│   │   ├── gap_fill.py         # Gap fill mean-reversion
│   │   ├── gap_up_fade.py      # Gap up fade (needs threshold fix)
│   │   ├── bb_squeeze.py       # BB squeeze (needs percentile fix)
│   │   ├── vwap_reversion.py   # VWAP mean-reversion (needs R:R fix)
│   │   └── afternoon_breakout.py  # Afternoon breakout
│   │
│   ├── brain/
│   │   ├── market_context.py   # Central context aggregator
│   │   ├── briefing.py         # Morning briefing generator
│   │   ├── state.py            # Brain state management
│   │   └── knowledge/          # Historical analysis data
│   │       └── pending_analysis.json  # 348 days of backtest data
│   │
│   ├── analysis/
│   │   ├── similarity.py       # Historical day similarity search
│   │   ├── post_trade.py       # Edge capture analysis
│   │   ├── performance.py      # Equity curve and stats
│   │   └── journal_analyzer.py # Pattern detection from journals
│   │
│   ├── journal/
│   │   ├── logger.py           # Structured JSON trade journal
│   │   └── paper_logs/         # Paper trading logs
│   │
│   ├── scripts/                # Orchestration scripts (Brain runs these)
│   │   ├── morning_prep.py     # Full morning analysis
│   │   ├── live_check.py       # Intraday market check
│   │   ├── entry_decision.py   # Run entry checklist
│   │   ├── select_strike.py    # Pick best option strike
│   │   ├── paper_trade.py      # Place paper trade
│   │   ├── check_position.py   # Monitor open positions
│   │   ├── post_market.py      # End-of-day review
│   │   └── find_similar.py     # Historical similarity search
│   │
│   └── tests/                  # Test suite
│
└── ui/                         # React frontend + FastAPI backend
```

---

## Decision Engine Flow

```
Market Data → Indicators → Confluence Scorer → Entry Checklist → Strike Selector → Paper Trade
    │              │              │                   │                │               │
    │              │              │                   │                │               │
  Dhan API      RSI, EMA       12 factors           8 gates         Greeks-based    Virtual
  Option Chain  ATR, VWAP      weighted avg         ALL must pass   scoring          portfolio
  Global data   OI, IV         → direction          → GO/NOGO       → best strike   → track P&L
```

---

## Key Design Principles

1. **Python decides, AI narrates.** No LLM calls for trading decisions.
2. **Confluence over conviction.** Multiple confirming signals > one strong signal.
3. **Boolean gates prevent bad trades.** 8 must pass. One failure = no trade.
4. **Position sizing from risk, not conviction.** ATR-based stops → risk budget → lots.
5. **Paper first, live later.** Prove edge for 1+ weeks before any real money.
6. **Every trade is journaled.** Full context, decisions, outcomes, and learnings.

---

## Daily Workflow

| Time | Action | Script |
|------|--------|--------|
| 08:45 | Morning prep | `python -m scripts.morning_prep` |
| 09:15 | Market opens | Brain monitors |
| 10:15 | First hour check | `python -m scripts.live_check` |
| 10:15 | Entry decision | `python -m scripts.entry_decision --direction LONG` |
| 10:15 | Select strike | `python -m scripts.select_strike --direction LONG` |
| 10:15 | Place paper trade | `python -m scripts.paper_trade --action BUY --strike 52100 --type CE --premium 285` |
| Every 15m | Position check | `python -m scripts.check_position` |
| 15:30 | Post-market review | `python -m scripts.post_market` |

---

## Configuration

### Dhan API (jack/config/.env)
```
DHAN_CLIENT_ID=your_client_id_here
DHAN_ACCESS_TOKEN=your_access_token_here
TRADING_MODE=paper
```

### Trading Parameters (jack/config/settings.yaml)
```yaml
trading:
  initial_capital: 1000000
  max_risk_per_trade_pct: 0.5
  max_daily_drawdown_pct: 2.0
  max_trades_per_day: 2
market:
  instrument: BANKNIFTY
  lot_size: 15
```

---

## Status: What Works vs What's New

### ✅ Existing (Keep)
- All 20+ indicators (RSI, EMA, ATR, VWAP, MACD, etc.)
- FirstHourVerdict (68% WR, primary strategy)
- GapFill (63% WR)
- Risk manager with full Indian cost model
- Options pricer (Black-Scholes + Greeks)
- Post-trade analyzer, journal logger, performance analysis
- Web UI (React + FastAPI)

### 🆕 New (Built in Jack Pro)
- Dhan API client + data fetcher
- OI Analysis (PCR, Max Pain, buildup, traps)
- IV Analysis (rank, percentile, skew, regime)
- Event calendar with impact multipliers
- Confluence Scorer (12-factor weighted)
- Entry Checklist (8 boolean gates)
- Strike Selector v2 (Greeks-based scoring)
- Similarity Search (historical day matching)
- Market Context Builder (central aggregator)
- Paper Trading Engine v2 (standalone)
- Position Monitor (trailing stops)
- All orchestration scripts

### 🔧 Needs Fixing
- BBSqueeze (38% WR → needs multi-day percentile)
- VWAPReversion (broken R:R, 0 trades)
- GapUpFade (threshold too high)
- Expiry filter (hardcoded Wed/Thu)
- State machine (too rigid, needs dynamic router)

#!/usr/bin/env python3
"""
Jack Agent Loop CLI

This provides a single-day execution engine and state management, acting 
as the interface between the backtesting engine and the autonomous AI agent.
"""

import argparse
import sys
from brain.state import AgentState
from brain.briefing import BrainInterface

def cmd_init(args):
    AgentState.init_state(args.start, args.capital)
    print(f"Agent state initialized at {args.start} with ₹{args.capital}")

def cmd_status(args):
    state = AgentState.load()
    print(f"Current Date: {state.current_date}")
    print(f"Capital: ₹{state.capital:,.2f}")
    if state.open_position:
        print(f"Open Position: {state.open_position['direction']} {state.open_position['quantity']} units of {state.open_position['strategy']}")
    else:
        print("No open positions.")

def cmd_briefing(args):
    state = AgentState.load()
    interface = BrainInterface()
    briefing = interface.generate_morning_briefing(state.current_date)
    print(briefing)

def cmd_execute(args):
    # This runs the engine for one day using the current date in state
    from brain.interface import AgentExecutor
    state = AgentState.load()
    executor = AgentExecutor()
    results = executor.execute_day(state)
    print(f"Executed day {state.current_date}")
    print(f"Daily P&L: ₹{results.get('daily_pnl', 0):.2f}")

def cmd_advance(args):
    state = AgentState.load()
    executor = AgentExecutor()
    for _ in range(args.days):
        print(f"Advancing from {state.current_date}...")
        # A simple advance without AI intervention, uses default strategies
        executor.execute_day(state)
        state = AgentState.load() # Reload after execution updates it

def main():
    parser = argparse.ArgumentParser(description="Jack Agent Loop")
    subparsers = parser.add_subparsers(dest="command")

    p_init = subparsers.add_parser("init", help="Initialize agent state")
    p_init.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    p_init.add_argument("--capital", type=float, default=1000000)

    p_status = subparsers.add_parser("status", help="Show current state")

    p_briefing = subparsers.add_parser("briefing", help="Generate morning briefing for AI")

    p_exec = subparsers.add_parser("execute", help="Execute single day")
    
    p_adv = subparsers.add_parser("advance", help="Advance N days autonomously")
    p_adv.add_argument("--days", type=int, default=1)

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "briefing": cmd_briefing,
        "execute": cmd_execute,
        "advance": cmd_advance
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

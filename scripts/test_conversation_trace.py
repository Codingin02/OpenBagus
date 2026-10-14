#!/usr/bin/env python3
"""Trace conversational question-to-data execution for:
1. "kenapa data openbagus tidak lengkap?" -> General data coverage
2. "berapa harga saham DATA?" -> PT Remala Abadi Tbk. (ticker DATA)
3. "Analisis RATU timeframe satu hari" -> Technical analysis on EOD candles, notes quarantined financial statements.
"""

from openbagus.ai.harness.orchestrator import AgentHarness
from openbagus.ai.memory.working_context import WorkingContext

def main():
    harness = AgentHarness()

    print("=== TURN 1: Data Coverage Query ===")
    ctx1 = WorkingContext()
    r1 = harness.run("kenapa data openbagus tidak lengkap?", context=ctx1)
    print("Content:\n", r1.content)
    print("Tools executed:", [t.get("name") for t in r1.tool_calls_executed])
    print("Provider:", r1.provider_name)

    print("\n=== TURN 2: Saham DATA Query ===")
    ctx2 = WorkingContext()
    r2 = harness.run("berapa harga saham DATA?", context=ctx2)
    print("Content:\n", r2.content)
    print("Active ticker in context:", ctx2.active_ticker)
    print("Tools executed:", [t.get("name") for t in r2.tool_calls_executed])

    print("\n=== TURN 3: Analisis RATU Timeframe Satu Hari ===")
    ctx3 = WorkingContext()
    r3 = harness.run("Analisis RATU timeframe satu hari", context=ctx3)
    print("Content:\n", r3.content)
    print("Active ticker in context:", ctx3.active_ticker)
    print("Time horizon in context:", ctx3.time_horizon)
    print("Tools executed:", [t.get("name") for t in r3.tool_calls_executed])

if __name__ == "__main__":
    main()

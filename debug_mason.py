import sys
sys.path.insert(0, r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer')

from dynasty_trade_analyzer_v2 import RELIEVER_PROJECTIONS, CONSENSUS_RANKINGS

print("=" * 70)
print("RELIEVER PROJECTIONS CHECK")
print("=" * 70)

relievers = ["Mason Miller", "Ben Joyce", "Edwin Diaz", "Josh Hader"]

for name in relievers:
    if name in RELIEVER_PROJECTIONS:
        proj = RELIEVER_PROJECTIONS[name]
        rank = CONSENSUS_RANKINGS.get(name, "N/A")
        print(f"\n{name}:")
        print(f"  Consensus Rank: {rank}")
        print(f"  Projections: {proj}")
    else:
        print(f"\n{name}: NOT IN RELIEVER_PROJECTIONS")
        rank = CONSENSUS_RANKINGS.get(name, "N/A")
        print(f"  Consensus Rank: {rank}")

print("\n" + "=" * 70)
print("ALL RELIEVERS IN PROJECTIONS:")
print("=" * 70)
for name in sorted(RELIEVER_PROJECTIONS.keys()):
    print(f"  {name}")

"""
Create a patched version of load_consensus_rankings that:
1. Loads CFR player levels
2. Only includes CFR for MiLB players (A, A+, AA, AAA, CPX)
3. Excludes CFR for MLB players
"""

import re

with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Find the section where CFR is added to all_sources and the final weighting calculation
# We need to:
# 1. Add level tracking in CFR loading
# 2. Modify the weighting logic to exclude CFR for MLB players

# First, show what we're looking for
print("Current structure being modified:")
print("=" * 70)

# Find the CFR hitters section
cfr_hitters_match = re.search(r'# Load Consensus Formulated Ranks \(hitters\).*?cfr_h_ranks = \{\}.*?except Exception:', content, re.DOTALL)
if cfr_hitters_match:
    lines = cfr_hitters_match.group().split('\n')
    for line in lines[:10]:
        print(line)
    print("...")
    for line in lines[-3:]:
        print(line)

print("\n" + "=" * 70)
print("MODIFICATION STRATEGY:")
print("=" * 70)
print("""
1. Create a dictionary to track player levels from CFR
2. When loading CFR, store both rank and level
3. In the final weighting loop, check if player is MLB
4. If MLB, exclude CFR from weighted average
5. If MiLB (A/A+/AA/AAA/CPX), include CFR
""")

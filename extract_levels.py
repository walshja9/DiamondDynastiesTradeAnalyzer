"""
SOLUTION: Filter CFR by player level (MLB vs MiLB)

Problem: CFR (Consensus Formulated Ranks) is prospect-focused
- Mason Miller listed as A+ (minor league) gets CFR rank 691.5
- CFR 20% weight is killing his consensus ranking
- Result: 75.4 consensus (should be ~50 for elite closer)

Fix: Only use CFR for MiLB players (A, A+, AA, AAA, CPX)
- MLB players use: FHQ, HKB, Steamer, ZiPS only
- MiLB/Prospect players use: All sources + CFR
"""

import csv
import os
import json

script_dir = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer'

# Load CFR player levels from the CSV files
cfr_player_levels = {}

# CFR Pitchers
cfr_p_path = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")
with open(cfr_p_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        name = row.get('Name', '').strip()
        level = row.get('Level', '').strip()
        if name:
            cfr_player_levels[name] = level

# CFR Hitters
cfr_h_path = os.path.join(script_dir, "Consensus Formulated Ranks_Hitters_2026.csv")
with open(cfr_h_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        name = row.get('Name', '').strip()
        level = row.get('Level', '').strip()
        if name:
            cfr_player_levels[name] = level

# Check levels for our problem players
print("=" * 70)
print("CFR PLAYER LEVELS")
print("=" * 70)

test_players = ['Mason Miller', 'Ben Joyce', 'Edwin Diaz', 'Josh Hader', 'Chase Burns']
for name in test_players:
    level = cfr_player_levels.get(name, 'NOT IN CFR')
    print(f"{name:<20} Level: {level}")

# Save to JSON for use in the fixed load_consensus_rankings
print("\nSaving player levels to cfr_player_levels.json...")

json_path = os.path.join(script_dir, "cfr_player_levels.json")
with open(json_path, 'w') as f:
    json.dump(cfr_player_levels, f, indent=2)

print(f"Saved {len(cfr_player_levels)} players to {json_path}")

import csv
import os

script_dir = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer'

players_to_check = ["Mason Miller", "Edwin Diaz", "Josh Hader"]

print("=" * 70)
print("CHECKING RANKING SOURCES")
print("=" * 70)

# FHQ
fhq_path = os.path.join(script_dir, "Top-500 Fantasy Baseball Dynasty Rankings - FantraxHQ.csv")
print(f"\nFHQ (Top-500 Dynasty):")
with open(fhq_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        for name in players_to_check:
            if name in row.get('Player', ''):
                print(f"  {name}: Points={row.get('Points')}, Roto={row.get('Roto')}")

# HKB
hkb_path = os.path.join(script_dir, "harryknowsball_players.csv")
print(f"\nHKB (Dynasty Values):")
with open(hkb_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        for name in players_to_check:
            if name in row.get('Name', ''):
                print(f"  {name}: Rank={row.get('Rank')}, Value={row.get('Value')}")

# CFR Pitchers
cfr_pitch_path = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")
print(f"\nCFR (Pitcher Consensus):")
with open(cfr_pitch_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        for name in players_to_check:
            if name in row.get('Name', ''):
                print(f"  {name}: Avg Rank={row.get('Avg Rank')}")

# Check scout the statline
sts_path = os.path.join(script_dir, "Scout the Statline Peak Projections_ Members - MLB_Combined_Table.csv")
print(f"\nSTS (Peak Projections):")
with open(sts_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        for name in players_to_check:
            if name in row.get('Player', ''):
                print(f"  {name}: Rank={row.get('Rank')}")

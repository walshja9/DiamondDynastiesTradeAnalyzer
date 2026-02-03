import csv
import os

script_dir = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer'

# Check CFR again for Mason Miller level
cfr_p_path = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")
with open(cfr_p_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Mason Miller' in row.get('Name', ''):
            print(f"Mason Miller in CFR:")
            print(f"  Name: {row.get('Name')}")
            print(f"  Level: {row.get('Level')}")
            print(f"  Avg Rank: {row.get('Avg Rank')}")

# Check HKB for Mason Miller
hkb_path = os.path.join(script_dir, "harryknowsball_players.csv")
with open(hkb_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Mason Miller' in row.get('Name', ''):
            print(f"\nMason Miller in HKB:")
            print(f"  Rank: {row.get('Rank')}")

# Check FHQ
fhq_path = os.path.join(script_dir, "Top-500 Fantasy Baseball Dynasty Rankings - FantraxHQ.csv")
with open(fhq_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Mason Miller' in row.get('Player', ''):
            print(f"\nMason Miller in FHQ:")
            print(f"  Roto: {row.get('Roto')}")

# Check STS
sts_path = os.path.join(script_dir, "Scout the Statline Peak Projections_ Members - MLB_Combined_Table.csv")
with open(sts_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Mason Miller' in row.get('Player', ''):
            print(f"\nMason Miller in STS:")
            print(f"  Rank: {row.get('Rank')}")
            break

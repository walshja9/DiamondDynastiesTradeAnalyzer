import csv
import os

script_dir = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer'

# Check what player levels are in CFR
cfr_pitch_path = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")

levels = set()
players_by_level = {}

with open(cfr_pitch_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        level = row.get('Level', '').strip()
        levels.add(level)
        if level not in players_by_level:
            players_by_level[level] = []
        players_by_level[level].append(row.get('Name'))

print("=" * 70)
print("CFR PITCHER LEVELS")
print("=" * 70)

for level in sorted(levels):
    count = len(players_by_level[level])
    print(f"\n{level}: {count} players")
    # Show first 5
    for i, name in enumerate(players_by_level[level][:5]):
        print(f"  - {name}")
    if count > 5:
        print(f"  ... and {count-5} more")

# Check for specific players
print("\n" + "=" * 70)
print("SPECIFIC PLAYERS IN CFR")
print("=" * 70)

with open(cfr_pitch_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get('Name') in ['Ben Joyce', 'Mason Miller', 'Edwin Diaz', 'Josh Hader']:
            print(f"{row.get('Name')}: Age {row.get('Age')}, Level {row.get('Level')}, Avg Rank {row.get('Avg Rank')}")

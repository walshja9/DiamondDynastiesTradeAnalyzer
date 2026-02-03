import csv
import os

# Check if we can load ages from a CSV instead of relying on PLAYER_AGES global
# Look for common sources of player ages

script_dir = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer'

# Check if HKB has ages
hkb_path = os.path.join(script_dir, "harryknowsball_players.csv")
with open(hkb_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    header = reader.fieldnames
    print("HKB columns:", header)
    # Check a few rows
    f.seek(0)
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i < 3:
            print(f"Sample: {row.get('Name')} - Age: {row.get('Age')}")
        if i >= 2:
            break

# Check FHQ
fhq_path = os.path.join(script_dir, "Top-500 Fantasy Baseball Dynasty Rankings - FantraxHQ.csv")
with open(fhq_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    header = reader.fieldnames
    print("\nFHQ columns:", header)

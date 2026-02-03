import csv
import os

script_dir = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer'

print("=" * 70)
print("MASON MILLER - ALL SOURCES")
print("=" * 70)

# Check all projection sources
sources = {
    'Steamer Pitchers': 'fangraphs-leaderboard-projections-pitcher-steamer.csv',
    'ZiPS Pitchers': 'fangraphs-leaderboard-projections-pitcher-zips.csv',
    'STS': 'Scout the Statline Peak Projections_ Members - MLB_Combined_Table.csv',
    'PL': 'Prospects Live Top 500 Fantasy Prospects.csv',
}

for source_name, filename in sources.items():
    path = os.path.join(script_dir, filename)
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rank_col = 'Rank' if 'Rank' in next(f) else None
            
        with open(path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            found = False
            for i, row in enumerate(reader, 1):
                if 'Mason Miller' in str(row.get('Name', '')) or 'Mason Miller' in str(row.get('Player', '')):
                    print(f"\n{source_name}: Row {i}")
                    for k, v in row.items():
                        print(f"  {k}: {v}")
                    found = True
                    break
            if not found and source_name != 'PL':
                print(f"\n{source_name}: NOT FOUND")
    except Exception as e:
        print(f"\n{source_name}: ERROR - {e}")

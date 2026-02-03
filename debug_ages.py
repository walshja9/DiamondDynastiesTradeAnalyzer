import csv
import os

script_dir = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer'

# Check Mason Miller's age in CFR
cfr_p_path = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")
with open(cfr_p_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Mason Miller' in row.get('Name', ''):
            print(f"Mason Miller in CFR:")
            print(f"  Name: {row.get('Name')}")
            print(f"  Age: {row.get('Age')} (type: {type(row.get('Age'))})")
            print(f"  Level: {row.get('Level')}")
            print(f"  Avg Rank: {row.get('Avg Rank')}")
            
            # Test conversion
            age_str = row.get('Age', '')
            if age_str:
                age = float(age_str)
                print(f"  Converted age: {age}")
                print(f"  Age >= 25: {age >= 25}")

# Check Ben Joyce
cfr_pitch = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")
with open(cfr_pitch, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Ben Joyce' in row.get('Name', ''):
            print(f"\nBen Joyce in CFR:")
            print(f"  Name: {row.get('Name')}")
            print(f"  Age: {row.get('Age')}")
            print(f"  Level: {row.get('Level')}")
            print(f"  Avg Rank: {row.get('Avg Rank')}")

import csv
import os

cfr_pitch_path = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\Consensus Formulated Ranks_Pitchers_2026.csv'

print("=" * 70)
print("CFR PITCHERS - FIRST 30 ROWS")
print("=" * 70)

with open(cfr_pitch_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader, 1):
        if i <= 30:
            print(f"{i:3}. {row.get('Name'):25} Age {row.get('Age'):4} Level {row.get('Level'):6} Avg Rank {row.get('Avg Rank')}")
        else:
            break

print("\n" + "=" * 70)
print("CFR PITCHERS - ROWS AROUND MASON MILLER (row ~375)")
print("=" * 70)

with open(cfr_pitch_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader, 1):
        if 370 <= i <= 380:
            print(f"{i:3}. {row.get('Name'):25} Age {row.get('Age'):4} Level {row.get('Level'):6} Avg Rank {row.get('Avg Rank')}")
        elif i > 380:
            break

import csv
import os

script_dir = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer'

print("=" * 70)
print("MASON MILLER - SOURCE BREAKDOWN")
print("=" * 70)

# FHQ
fhq_path = os.path.join(script_dir, "Top-500 Fantasy Baseball Dynasty Rankings - FantraxHQ.csv")
fhq_rank = None
with open(fhq_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Mason Miller' in row.get('Player', ''):
            fhq_rank = int(row.get('Roto', ''))
            print(f"FHQ Roto: {fhq_rank} (weight 30%)")

# HKB
hkb_path = os.path.join(script_dir, "harryknowsball_players.csv")
hkb_rank = None
with open(hkb_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Mason Miller' in row.get('Name', ''):
            hkb_rank = int(row.get('Rank', ''))
            print(f"HKB Rank: {hkb_rank} (weight 30%)")

# CFR
cfr_p_path = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")
cfr_rank = None
cfr_level = None
with open(cfr_p_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Mason Miller' in row.get('Name', ''):
            cfr_rank = int(float(row.get('Avg Rank', '')))
            cfr_level = row.get('Level', '')
            print(f"CFR Rank: {cfr_rank}, Level: {cfr_level} (weight 20% if included)")

# Calculate what it should be if excluding CFR
if fhq_rank and hkb_rank:
    # FHQ 30%, HKB 30%, then need other sources
    # Without CFR, remaining weight = 40% split between Steamer/ZiPS (10% each) + STS (10%) + others
    # But if only FHQ and HKB have him, then:
    weighted_available = (fhq_rank * 0.30 + hkb_rank * 0.30) / (0.30 + 0.30)
    print(f"\nIf only FHQ + HKB (excluding CFR):")
    print(f"  Weighted average: ({fhq_rank} * 0.30 + {hkb_rank} * 0.30) / 0.60 = {weighted_available:.1f}")
    
# Calculate what it would be WITH CFR
if fhq_rank and hkb_rank and cfr_rank:
    # Normalized weights when all 3 present
    total_raw = fhq_rank * 0.30 + hkb_rank * 0.30 + cfr_rank * 0.20
    weight_sum = 0.80  # Only 80% if we only have these 3
    weighted_with_cfr = total_raw / weight_sum
    print(f"\nIf FHQ + HKB + CFR (including CFR):")
    print(f"  Weighted average: ({fhq_rank} * 0.30 + {hkb_rank} * 0.30 + {cfr_rank} * 0.20) / 0.80 = {weighted_with_cfr:.1f}")

print(f"\nActual consensus rank reported: 139.875")
print(f"This suggests CFR IS being included in the calculation")

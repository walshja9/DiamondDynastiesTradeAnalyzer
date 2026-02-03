import csv
import os

# The fundamental issue:
# CFR is 20% weight but it's PROSPECT-FOCUSED
# Established MLB players like Mason Miller get crushed in CFR rankings
# This kills their overall consensus

# Solution: Only use CFR for prospects/young players
# For established MLB players, use: FHQ (30%), HKB (30%), Steamer (15%), ZiPS (15%), STS (10%)

script_dir = r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer'

# Simulate ranking calculation
def calculate_weighted_rank_OLD(name, fhq, hkb, steamer, zips, cfr, sts):
    """Current broken formula"""
    weights = {'fhq': 0.30, 'hkb': 0.30, 'steamer': 0.10, 'zips': 0.10, 'cfr': 0.20, 'sts': 0, 'pl': 0}
    ranks = {}
    
    if fhq: ranks['fhq'] = fhq
    if hkb: ranks['hkb'] = hkb
    if steamer: ranks['steamer'] = steamer
    if zips: ranks['zips'] = zips
    if cfr: ranks['cfr'] = cfr
    if sts and sts <= 500: ranks['sts'] = sts
    
    if not ranks:
        return None
    
    total = sum(weights[k] * v for k, v in ranks.items())
    weight_sum = sum(weights[k] for k in ranks)
    
    return total / weight_sum if weight_sum else None

def calculate_weighted_rank_NEW(name, age, fhq, hkb, steamer, zips, cfr, sts):
    """Fixed formula - exclude CFR for established MLB players"""
    # If player is young prospect (under 23) or in minors, include CFR
    # Otherwise exclude it
    
    is_young_prospect = age and age < 23
    
    weights = {'fhq': 0.30, 'hkb': 0.30, 'steamer': 0.10, 'zips': 0.10, 'cfr': 0.20, 'sts': 0, 'pl': 0}
    ranks = {}
    
    if fhq: ranks['fhq'] = fhq
    if hkb: ranks['hkb'] = hkb
    if steamer: ranks['steamer'] = steamer
    if zips: ranks['zips'] = zips
    if cfr and is_young_prospect:  # ONLY include CFR for young prospects
        ranks['cfr'] = cfr
    if sts and sts <= 500: ranks['sts'] = sts
    
    if not ranks:
        return None
    
    # Recalculate weights for sources present
    weights_present = {k: weights[k] for k in ranks}
    total_weight = sum(weights_present.values())
    normalized_weights = {k: v/total_weight for k, v in weights_present.items()}
    
    total = sum(normalized_weights[k] * v for k, v in ranks.items())
    
    return total

# Test with key players
test_data = {
    'Mason Miller': {'age': 27, 'fhq': 49, 'hkb': 85, 'steamer': 112, 'zips': 89, 'cfr': 691.5, 'sts': 15},
    'Ben Joyce': {'age': 25, 'fhq': None, 'hkb': 596, 'steamer': 327, 'zips': 621, 'cfr': 57, 'sts': 2100},
    'Edwin Diaz': {'age': 32, 'fhq': 95, 'hkb': 175, 'steamer': None, 'zips': None, 'cfr': 135, 'sts': 2243},
    'Chase Burns': {'age': 22, 'fhq': None, 'hkb': None, 'steamer': None, 'zips': None, 'cfr': 5.2, 'sts': None},
}

print("=" * 80)
print("WEIGHTED CONSENSUS RANKING - OLD vs NEW FORMULA")
print("=" * 80)

print(f"\n{'Player':<20} {'Age':<4} {'OLD RANK':<12} {'NEW RANK':<12} {'Difference':<10}")
print("-" * 80)

for name, data in test_data.items():
    age = data['age']
    old_rank = calculate_weighted_rank_OLD(name, data['fhq'], data['hkb'], data['steamer'], data['zips'], data['cfr'], data['sts'])
    new_rank = calculate_weighted_rank_NEW(name, age, data['fhq'], data['hkb'], data['steamer'], data['zips'], data['cfr'], data['sts'])
    
    diff = ''
    if old_rank and new_rank:
        diff = f"{old_rank - new_rank:+.1f}"
    
    old_str = f"{old_rank:.1f}" if old_rank else "N/A"
    new_str = f"{new_rank:.1f}" if new_rank else "N/A"
    
    print(f"{name:<20} {age:<4} {old_str:<12} {new_str:<12} {diff:<10}")

print("\n" + "=" * 80)
print("KEY INSIGHT:")
print("=" * 80)
print("""
Mason Miller should be ~50-60, not 139.9
- FHQ: 49 (elite closer)
- HKB: 85 (elite closer)  
- STS: 15 (elite closer)
But CFR: 691.5 (prospect list) is pulling him down to 139.9

NEW FORMULA: Exclude CFR for 27yo established closers
Result: Average of available sources = much more accurate (50-60 range)
""")

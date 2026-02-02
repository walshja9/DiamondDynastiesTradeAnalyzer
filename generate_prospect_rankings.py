#!/usr/bin/env python3
"""
Generate calibrated prospect rankings from multiple external sources.
Creates a weighted average of prospect rankings from:
- MLB Pipeline Top 100 (30% weight - authoritative MLB source)
- Prospects Live Top 500 (25% weight - dynasty-focused)
- Consensus Formulated Ranks Hitters (15% weight)
- Consensus Formulated Ranks Pitchers (15% weight)
- harryknowsball (15% weight - dynasty-focused)
"""

import csv
import json
import os
from collections import defaultdict

# Configuration
MAX_PROSPECT_AGE = 25
OUTPUT_COUNT = 300

# Source weights (must sum to 1.0 when present)
SOURCE_WEIGHTS = {
    'MLB_PIPE': 0.30,  # MLB Pipeline - authoritative source
    'PL': 0.25,        # Prospects Live - dynasty-focused
    'CFR_H': 0.15,     # Consensus Formulated Ranks Hitters
    'CFR_P': 0.15,     # Consensus Formulated Ranks Pitchers
    'HKB': 0.15,       # harryknowsball - dynasty values
}

# Players to exclude (already graduated or not prospects)
EXCLUDE_PLAYERS = {
    'Ben Joyce', 'Mick Abel', 'Kazuma Okamoto', 'Munetaka Murakami',
    'Tatsuya Imai', 'Shohei Ohtani', 'Jackson Holliday', 'Paul Skenes',
    'Jackson Chourio', 'Junior Caminero', 'Elly De La Cruz', 'Gunnar Henderson',
    'Bobby Witt Jr.', 'Corbin Carroll', 'James Wood', 'Wyatt Langford',
    'Pete Crow-Armstrong', 'Julio Rodriguez', 'Ronald Acuna Jr.', 'Juan Soto',
    'Garrett Crochet', 'Chase Burns',  # Chase Burns graduated to MLB
}

def load_prospects_live(filepath):
    """Load Prospects Live Top 500 Fantasy Prospects."""
    rankings = {}
    ages = {}
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name_FG', '').strip().strip('"')
                rank = row.get('Rank', '')
                age = row.get('Age', '')
                if name and rank:
                    try:
                        rankings[name] = int(rank)
                        if age:
                            ages[name] = int(age)
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error loading Prospects Live: {e}")
    print(f"Loaded {len(rankings)} from Prospects Live")
    return rankings, ages


def load_consensus_ranks(filepath, source_name):
    """Load Consensus Formulated Ranks (row order = rank)."""
    rankings = {}
    ages = {}
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, 1):
                name = row.get('Name', '').strip()
                age = row.get('Age', '')
                if name:
                    rankings[name] = i
                    if age:
                        try:
                            ages[name] = int(age)
                        except ValueError:
                            pass
    except Exception as e:
        print(f"Error loading {source_name}: {e}")
    print(f"Loaded {len(rankings)} from {source_name}")
    return rankings, ages


def load_harryknowsball(filepath):
    """Load harryknowsball player rankings."""
    rankings = {}
    ages = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip()
                rank = row.get('Rank', '')
                age = row.get('Age', '')
                level = row.get('Level', '')
                if name and rank:
                    try:
                        # Only include minor leaguers or prospects
                        if level and level.upper() not in ['MLB', 'FA']:
                            rankings[name] = int(rank)
                        elif not level:
                            rankings[name] = int(rank)
                        if age:
                            ages[name] = float(age)
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error loading harryknowsball: {e}")
    print(f"Loaded {len(rankings)} from harryknowsball (non-MLB)")
    return rankings, ages


def load_mlb_pipeline(filepath):
    """Load MLB Pipeline Top 100 Prospects."""
    rankings = {}
    ages = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip()
                rank = row.get('Rank', '')
                age = row.get('Age', '')
                if name and rank:
                    try:
                        rankings[name] = int(rank)
                        if age:
                            ages[name] = int(age)
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error loading MLB Pipeline: {e}")
    print(f"Loaded {len(rankings)} from MLB Pipeline")
    return rankings, ages


def normalize_name(name):
    """Normalize player names for matching."""
    name = name.strip()
    name = name.replace("Jr.", "Jr").replace("Sr.", "Sr").replace("  ", " ")
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'ñ': 'n', 'ü': 'u', 'Á': 'A', 'É': 'E', 'Í': 'I',
        'Ó': 'O', 'Ú': 'U', 'Ñ': 'N'
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    return name.lower()


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load all sources
    sources = {}
    all_ages = {}

    # MLB Pipeline Top 100 (highest weight - authoritative source)
    mlb_path = os.path.join(script_dir, "mlb_pipeline_prospects.csv")
    if os.path.exists(mlb_path):
        sources['MLB_PIPE'], ages = load_mlb_pipeline(mlb_path)
        all_ages.update(ages)

    # Prospects Live
    pl_path = os.path.join(script_dir, "Prospects Live Top 500 Fantasy Prospects.csv")
    if os.path.exists(pl_path):
        sources['PL'], ages = load_prospects_live(pl_path)
        all_ages.update(ages)

    # Consensus Formulated Ranks - Hitters
    cfr_h_path = os.path.join(script_dir, "Consensus Formulated Ranks_Hitters_2026.csv")
    if os.path.exists(cfr_h_path):
        sources['CFR_H'], ages = load_consensus_ranks(cfr_h_path, "CFR Hitters")
        all_ages.update(ages)

    # Consensus Formulated Ranks - Pitchers
    cfr_p_path = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")
    if os.path.exists(cfr_p_path):
        sources['CFR_P'], ages = load_consensus_ranks(cfr_p_path, "CFR Pitchers")
        all_ages.update(ages)

    # harryknowsball
    hkb_path = os.path.join(script_dir, "harryknowsball_players.csv")
    if os.path.exists(hkb_path):
        sources['HKB'], ages = load_harryknowsball(hkb_path)
        all_ages.update(ages)

    # Build normalized name lookup for cross-matching
    normalized_to_canonical = {}
    for source_name, source_data in sources.items():
        for name in source_data.keys():
            norm = normalize_name(name)
            if norm not in normalized_to_canonical:
                normalized_to_canonical[norm] = name

    # Collect all unique prospects
    all_prospects = set()
    for source_data in sources.values():
        all_prospects.update(source_data.keys())

    print(f"\nTotal unique names across sources: {len(all_prospects)}")

    # Calculate weighted average rank for each prospect
    prospect_scores = []

    for name in all_prospects:
        if name in EXCLUDE_PLAYERS:
            continue

        # Get age (skip if over MAX_PROSPECT_AGE)
        age = all_ages.get(name, 0)
        if age > MAX_PROSPECT_AGE:
            continue

        # Get normalized name for cross-matching
        norm_name = normalize_name(name)

        # Collect ranks from each source
        weighted_sum = 0.0
        total_weight = 0.0
        source_count = 0

        for source_name, source_data in sources.items():
            rank = None

            # Try exact match
            if name in source_data:
                rank = source_data[name]
            else:
                # Try normalized match
                for src_name, src_rank in source_data.items():
                    if normalize_name(src_name) == norm_name:
                        rank = src_rank
                        break

            if rank is not None and rank <= 500:  # Filter extreme ranks
                weight = SOURCE_WEIGHTS.get(source_name, 0.1)
                weighted_sum += rank * weight
                total_weight += weight
                source_count += 1

        # Only include if found in at least 2 sources for reliable consensus
        if total_weight > 0 and source_count >= 2:
            avg_rank = weighted_sum / total_weight
            prospect_scores.append({
                'name': name,
                'avg_rank': avg_rank,
                'sources': source_count,
                'age': age
            })

    # Sort by average rank
    prospect_scores.sort(key=lambda x: x['avg_rank'])

    # Take top OUTPUT_COUNT
    top_prospects = prospect_scores[:OUTPUT_COUNT]

    # Create the prospects.json structure
    prospects_json = {}
    for i, p in enumerate(top_prospects, 1):
        prospects_json[p['name']] = i

    # Save to file
    output_path = os.path.join(script_dir, "prospects.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(prospects_json, f, indent=4)

    print(f"\n{'='*60}")
    print(f"Generated {len(prospects_json)} prospect rankings")
    print(f"Saved to: {output_path}")
    print(f"{'='*60}")

    # Print top 30 for verification
    print("\nTop 30 Prospects:")
    print("-" * 50)
    for i, p in enumerate(top_prospects[:30], 1):
        age_str = f"Age {int(p['age'])}" if p['age'] > 0 else "Age ?"
        print(f"{i:3}. {p['name']:<30} (avg rank: {p['avg_rank']:.1f}, {age_str}, {p['sources']} sources)")

    # Print ranks 31-50
    print("\nProspects 31-50:")
    print("-" * 50)
    for i, p in enumerate(top_prospects[30:50], 31):
        age_str = f"Age {int(p['age'])}" if p['age'] > 0 else "Age ?"
        print(f"{i:3}. {p['name']:<30} (avg rank: {p['avg_rank']:.1f}, {age_str})")


if __name__ == "__main__":
    main()

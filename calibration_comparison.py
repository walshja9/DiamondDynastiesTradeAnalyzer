#!/usr/bin/env python3
"""
Calibration Comparison Script
Compares our dynasty values against external ranking sources to identify gaps.
"""

import csv
import os
import sys

# Add the current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dynasty_trade_analyzer_v2 import DynastyValueCalculator, Player, HITTER_PROJECTIONS, PITCHER_PROJECTIONS

def load_fantraxhq_rankings(filepath):
    """Load FantraxHQ Top 500 Dynasty Rankings."""
    rankings = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Player', '').strip()
                roto_rank = row.get('Roto', '')
                points_rank = row.get('Points', '')
                pos = row.get('Pos.', '')
                age = row.get('Age', '')

                if name and roto_rank:
                    try:
                        rankings[name] = {
                            'roto_rank': int(roto_rank),
                            'points_rank': int(points_rank) if points_rank else None,
                            'position': pos,
                            'age': int(age) if age and age.isdigit() else None,
                            'source': 'FantraxHQ'
                        }
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error loading FantraxHQ: {e}")
    return rankings

def load_harryknowsball_rankings(filepath):
    """Load harryknowsball player rankings with values."""
    rankings = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip()
                rank = row.get('Rank', '')
                value = row.get('Value', '')
                pos = row.get('Positions', '')
                age = row.get('Age', '')

                if name and rank:
                    try:
                        rankings[name] = {
                            'rank': int(rank),
                            'value': int(value) if value else 0,
                            'position': pos,
                            'age': float(age) if age else None,
                            'source': 'harryknowsball'
                        }
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error loading harryknowsball: {e}")
    return rankings

def load_scout_statline_rankings(filepath):
    """Load Scout the Statline Peak Projections rankings."""
    rankings = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Player', '').strip()
                rank = row.get('Rank', '')
                prospect_rank = row.get('Prospect Rank', '')
                pos = row.get('Position', '')
                age = row.get('Age', '')
                level = row.get('Level', '')

                if name and rank:
                    try:
                        rankings[name] = {
                            'rank': int(rank),
                            'prospect_rank': int(prospect_rank) if prospect_rank else None,
                            'position': pos,
                            'age': int(age) if age and age.isdigit() else None,
                            'level': level,
                            'source': 'ScoutStatline'
                        }
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error loading Scout the Statline: {e}")
    return rankings

def get_our_player_values():
    """Get our calculated values for all players in projections."""
    calculator = DynastyValueCalculator()
    our_values = {}

    # Process hitters
    for name, proj in HITTER_PROJECTIONS.items():
        player = Player(name=name, position="UTIL")
        # Try to get age from the calculator's data
        try:
            value = calculator.calculate_player_value(player)
            our_values[name] = {
                'value': value,
                'type': 'hitter'
            }
        except Exception as e:
            pass

    # Process pitchers
    for name, proj in PITCHER_PROJECTIONS.items():
        if name not in our_values:  # Don't overwrite hitters (e.g., Ohtani)
            player = Player(name=name, position="SP")
            try:
                value = calculator.calculate_player_value(player)
                our_values[name] = {
                    'value': value,
                    'type': 'pitcher'
                }
            except Exception as e:
                pass

    return our_values

def normalize_name(name):
    """Normalize player names for matching."""
    # Handle common variations
    name = name.strip()
    name = name.replace("Jr.", "Jr").replace("Sr.", "Sr").replace("  ", " ")
    return name

def create_comparison_report():
    """Create a comparison report between our values and external rankings."""

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load external rankings
    fantrax_path = os.path.join(script_dir, "Top-500 Fantasy Baseball Dynasty Rankings - FantraxHQ.csv")
    harry_path = os.path.join(script_dir, "harryknowsball_players.csv")
    scout_path = os.path.join(script_dir, "Scout the Statline Peak Projections_ Members - MLB_Combined_Table.csv")

    fantrax = load_fantraxhq_rankings(fantrax_path)
    harry = load_harryknowsball_rankings(harry_path)
    scout = load_scout_statline_rankings(scout_path)

    print(f"Loaded {len(fantrax)} FantraxHQ rankings")
    print(f"Loaded {len(harry)} harryknowsball rankings")
    print(f"Loaded {len(scout)} Scout the Statline rankings")

    # Get our values
    our_values = get_our_player_values()
    print(f"Calculated {len(our_values)} player values from our system")

    # Create comparison data
    comparison = []

    # Use harryknowsball as primary (has explicit values)
    for name, harry_data in harry.items():
        our_data = our_values.get(name) or our_values.get(normalize_name(name))
        fantrax_data = fantrax.get(name) or fantrax.get(normalize_name(name))
        scout_data = scout.get(name) or scout.get(normalize_name(name))

        if our_data:
            our_value = our_data['value']
            harry_value = harry_data['value']
            harry_rank = harry_data['rank']
            fantrax_rank = fantrax_data['roto_rank'] if fantrax_data else None
            scout_rank = scout_data['rank'] if scout_data else None

            # Normalize harry value to our ~100 scale
            # Harry top = 10000, Our top = ~125
            # So multiply by 125/10000 = 0.0125
            harry_normalized = harry_value * 0.0125

            # Calculate difference
            diff = our_value - harry_normalized
            diff_pct = (diff / harry_normalized * 100) if harry_normalized > 0 else 0

            comparison.append({
                'name': name,
                'our_value': our_value,
                'harry_value': harry_value,
                'harry_normalized': harry_normalized,
                'harry_rank': harry_rank,
                'fantrax_rank': fantrax_rank,
                'scout_rank': scout_rank,
                'diff': diff,
                'diff_pct': diff_pct,
                'position': harry_data['position'],
                'type': our_data['type']
            })

    # Sort by harry rank (external consensus)
    comparison.sort(key=lambda x: x['harry_rank'])

    return comparison

def print_comparison_report(comparison, limit=100):
    """Print a formatted comparison report."""

    print("\n" + "="*140)
    print("DYNASTY VALUE CALIBRATION REPORT")
    print("Comparing our values vs external rankings (harryknowsball + FantraxHQ + Scout the Statline)")
    print("="*140)

    print(f"\n{'Rank':<5} {'Player':<25} {'Pos':<8} {'Our Val':<10} {'Harry Norm':<12} {'Diff':<10} {'Diff %':<10} {'Assessment':<15} {'Sources':<20}")
    print("-"*140)

    overvalued = []
    undervalued = []

    for p in comparison[:limit]:
        # Determine assessment
        if p['diff_pct'] > 30:
            assessment = "OVERVALUED"
            overvalued.append(p)
        elif p['diff_pct'] < -30:
            assessment = "UNDERVALUED"
            undervalued.append(p)
        elif p['diff_pct'] > 15:
            assessment = "Slightly High"
        elif p['diff_pct'] < -15:
            assessment = "Slightly Low"
        else:
            assessment = "OK"

        # Build sources string with all available rankings
        sources = []
        if p['fantrax_rank']:
            sources.append(f"FHQ#{p['fantrax_rank']}")
        if p.get('scout_rank'):
            sources.append(f"STS#{p['scout_rank']}")
        sources_str = " ".join(sources)

        print(f"{p['harry_rank']:<5} {p['name']:<25} {p['position']:<8} {p['our_value']:<10.1f} {p['harry_normalized']:<12.1f} {p['diff']:<+10.1f} {p['diff_pct']:<+10.1f}% {assessment:<15} {sources_str:<20}")

    # Summary
    print("\n" + "="*120)
    print("SUMMARY - Players needing adjustment (>30% off):")
    print("="*120)

    if overvalued:
        print(f"\nOVERVALUED ({len(overvalued)} players) - Our value too HIGH:")
        print("-"*80)
        for p in sorted(overvalued, key=lambda x: -x['diff_pct'])[:15]:
            print(f"  {p['name']:<25} Our: {p['our_value']:.1f}, Should be ~{p['harry_normalized']:.1f} ({p['diff_pct']:+.0f}%)")

    if undervalued:
        print(f"\nUNDERVALUED ({len(undervalued)} players) - Our value too LOW:")
        print("-"*80)
        for p in sorted(undervalued, key=lambda x: x['diff_pct'])[:15]:
            print(f"  {p['name']:<25} Our: {p['our_value']:.1f}, Should be ~{p['harry_normalized']:.1f} ({p['diff_pct']:+.0f}%)")

    return overvalued, undervalued

def main():
    comparison = create_comparison_report()
    overvalued, undervalued = print_comparison_report(comparison, limit=75)

    print("\n" + "="*120)
    print("RECOMMENDED ACTIONS:")
    print("="*120)

    print("\nPlayers to ADD to PROVEN_VETERAN_STARS or increase boost:")
    for p in sorted(undervalued, key=lambda x: x['diff_pct'])[:10]:
        if p['our_value'] < 90:  # Not already a superstar in our system
            suggested_boost = p['harry_normalized'] / p['our_value'] if p['our_value'] > 0 else 1.0
            print(f"  {p['name']}: current {p['our_value']:.1f} -> target ~{p['harry_normalized']:.1f} (boost ~{suggested_boost:.2f}x)")

    print("\nPlayers to REDUCE boost or check projections:")
    for p in sorted(overvalued, key=lambda x: -x['diff_pct'])[:10]:
        suggested_reduction = p['harry_normalized'] / p['our_value'] if p['our_value'] > 0 else 1.0
        print(f"  {p['name']}: current {p['our_value']:.1f} -> target ~{p['harry_normalized']:.1f} (reduce to ~{suggested_reduction:.2f}x)")

if __name__ == "__main__":
    main()

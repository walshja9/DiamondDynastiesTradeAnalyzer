#!/usr/bin/env python3
"""
Calibration Comparison Script
Compares our dynasty values against multiple external ranking sources to identify gaps.

Sources:
- Scout the Statline Peak Projections
- FantraxHQ Top 500 Dynasty Rankings
- harryknowsball dynasty values
- Fangraphs Steamer projections (hitters + pitchers)
- Fangraphs ZiPS projections (hitters + pitchers)
- Consensus Formulated Ranks (hitters + pitchers)
- Prospects Live Top 500
"""

import csv
import os
import sys
from collections import defaultdict

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
                if name and roto_rank:
                    try:
                        rankings[name] = int(roto_rank)
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error loading FantraxHQ: {e}")
    return rankings


def load_harryknowsball_rankings(filepath):
    """Load harryknowsball player rankings."""
    rankings = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip()
                rank = row.get('Rank', '')
                if name and rank:
                    try:
                        rankings[name] = int(rank)
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
                if name and rank:
                    try:
                        rankings[name] = int(rank)
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error loading Scout the Statline: {e}")
    return rankings


def load_fangraphs_hitter_projections(filepath, source_name):
    """Load Fangraphs hitter projections and rank by WAR."""
    rankings = {}
    players = []
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip().strip('"')
                war = row.get('WAR', '')
                if name and war:
                    try:
                        players.append((name, float(war)))
                    except ValueError:
                        pass
        # Sort by WAR descending and assign ranks
        players.sort(key=lambda x: -x[1])
        for i, (name, war) in enumerate(players, 1):
            rankings[name] = i
    except Exception as e:
        print(f"Error loading {source_name}: {e}")
    return rankings


def load_fangraphs_pitcher_projections(filepath, source_name):
    """Load Fangraphs pitcher projections and rank by WAR."""
    rankings = {}
    players = []
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip().strip('"')
                war = row.get('WAR', '')
                if name and war:
                    try:
                        players.append((name, float(war)))
                    except ValueError:
                        pass
        # Sort by WAR descending and assign ranks
        players.sort(key=lambda x: -x[1])
        for i, (name, war) in enumerate(players, 1):
            rankings[name] = i
    except Exception as e:
        print(f"Error loading {source_name}: {e}")
    return rankings


def load_consensus_ranks(filepath, source_name):
    """Load Consensus Formulated Ranks."""
    rankings = {}
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, 1):
                name = row.get('Name', '').strip()
                if name:
                    rankings[name] = i  # Row order = rank
    except Exception as e:
        print(f"Error loading {source_name}: {e}")
    return rankings


def load_prospects_live(filepath):
    """Load Prospects Live Top 500 Fantasy Prospects."""
    rankings = {}
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name_FG', '').strip().strip('"')
                rank = row.get('Rank', '')
                if name and rank:
                    try:
                        rankings[name] = int(rank)
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error loading Prospects Live: {e}")
    return rankings


def normalize_name(name):
    """Normalize player names for matching."""
    name = name.strip()
    # Handle common variations
    name = name.replace("Jr.", "Jr").replace("Sr.", "Sr").replace("  ", " ")
    # Handle accented characters
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'ñ': 'n', 'ü': 'u', 'Á': 'A', 'É': 'E', 'Í': 'I',
        'Ó': 'O', 'Ú': 'U', 'Ñ': 'N'
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    return name


def get_our_player_values():
    """Get our calculated values for all players in projections."""
    calculator = DynastyValueCalculator()
    our_values = {}

    # Process hitters
    for name, proj in HITTER_PROJECTIONS.items():
        player = Player(name=name, position="UTIL")
        try:
            value = calculator.calculate_player_value(player)
            our_values[name] = {
                'value': value,
                'type': 'hitter'
            }
        except Exception:
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
            except Exception:
                pass

    return our_values


def find_player_in_rankings(name, rankings_dict):
    """Try to find a player in rankings using various name formats."""
    if name in rankings_dict:
        return rankings_dict[name]

    normalized = normalize_name(name)
    if normalized in rankings_dict:
        return rankings_dict[normalized]

    # Try matching normalized versions of ranking keys
    for key, value in rankings_dict.items():
        if normalize_name(key) == normalized:
            return value

    return None


def create_comparison_report():
    """Create a comparison report between our values and all external rankings."""
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load all ranking sources
    sources = {}

    # Dynasty rankings
    sources['FHQ'] = load_fantraxhq_rankings(
        os.path.join(script_dir, "Top-500 Fantasy Baseball Dynasty Rankings - FantraxHQ.csv"))
    sources['HKB'] = load_harryknowsball_rankings(
        os.path.join(script_dir, "harryknowsball_players.csv"))
    sources['STS'] = load_scout_statline_rankings(
        os.path.join(script_dir, "Scout the Statline Peak Projections_ Members - MLB_Combined_Table.csv"))

    # Fangraphs projections (create ranks from WAR)
    sources['Steamer'] = load_fangraphs_hitter_projections(
        os.path.join(script_dir, "fangraphs-leaderboard-projections-steamer.csv"), "Steamer Hitters")
    sources['ZiPS'] = load_fangraphs_hitter_projections(
        os.path.join(script_dir, "fangraphs-leaderboard-projections-zips.csv"), "ZiPS Hitters")
    sources['Stmr-P'] = load_fangraphs_pitcher_projections(
        os.path.join(script_dir, "fangraphs-leaderboard-projections-pitcher-steamer.csv"), "Steamer Pitchers")
    sources['ZiPS-P'] = load_fangraphs_pitcher_projections(
        os.path.join(script_dir, "fangraphs-leaderboard-projections-pitcher-zips.csv"), "ZiPS Pitchers")

    # Consensus ranks
    sources['CFR-H'] = load_consensus_ranks(
        os.path.join(script_dir, "Consensus Formulated Ranks_Hitters_2026.csv"), "Consensus Hitters")
    sources['CFR-P'] = load_consensus_ranks(
        os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv"), "Consensus Pitchers")

    # Prospects
    sources['PL'] = load_prospects_live(
        os.path.join(script_dir, "Prospects Live Top 500 Fantasy Prospects.csv"))

    # Print load summary
    print("=" * 80)
    print("LOADED RANKING SOURCES")
    print("=" * 80)
    for name, data in sources.items():
        print(f"  {name:<10}: {len(data):>5} players")
    print()

    # Get our values and create our own ranking
    our_values = get_our_player_values()
    print(f"Calculated {len(our_values)} player values from our system")

    # Create our ranking (sorted by value descending)
    sorted_players = sorted(our_values.items(), key=lambda x: -x[1]['value'])
    our_rankings = {name: i for i, (name, _) in enumerate(sorted_players, 1)}

    # Build comparison data for all players in our system
    comparison = []

    for name, data in our_values.items():
        player_ranks = {}

        # Get our rank
        player_ranks['OURS'] = our_rankings[name]

        # Get rank from each source
        for source_name, source_data in sources.items():
            rank = find_player_in_rankings(name, source_data)
            if rank:
                player_ranks[source_name] = rank

        # Calculate average rank from DYNASTY sources only (FHQ, HKB)
        # These are the most reliable dynasty-specific rankings
        dynasty_sources = ['FHQ', 'HKB']
        dynasty_ranks = [player_ranks.get(s) for s in dynasty_sources if player_ranks.get(s) is not None]

        # Filter out extreme outliers (ranks > 300 are less reliable for comparison)
        dynasty_ranks = [r for r in dynasty_ranks if r <= 300]
        avg_rank = sum(dynasty_ranks) / len(dynasty_ranks) if dynasty_ranks else None

        # Also compute all-source average for reference (filtering outliers)
        all_ranks = [r for k, r in player_ranks.items() if k != 'OURS' and r is not None and r <= 500]
        avg_all = sum(all_ranks) / len(all_ranks) if all_ranks else None

        comparison.append({
            'name': name,
            'our_value': data['value'],
            'our_rank': player_ranks['OURS'],
            'ranks': player_ranks,
            'avg_external_rank': avg_rank,  # Dynasty average (FHQ + HKB)
            'avg_all_rank': avg_all,  # All sources average
            'num_sources': len(dynasty_ranks),
            'type': data['type']
        })

    # Sort by our value descending
    comparison.sort(key=lambda x: -x['our_value'])

    return comparison, sources


def print_comparison_report(comparison, sources, limit=100):
    """Print a formatted comparison report."""

    # Define which sources to show in the main table
    main_sources = ['OURS', 'FHQ', 'HKB', 'STS', 'Steamer', 'ZiPS', 'PL']

    print("\n" + "=" * 160)
    print("DYNASTY VALUE CALIBRATION REPORT")
    print("Comparing our rankings vs external sources (showing average rank)")
    print("=" * 160)

    # Header
    header = f"{'Our#':<5} {'Player':<22} {'Value':<8} {'Avg#':<6} {'Diff':<6}"
    for src in main_sources[1:]:  # Skip OURS, already shown
        header += f" {src:<6}"
    print(header)
    print("-" * 160)

    overvalued = []
    undervalued = []
    well_calibrated = []

    for p in comparison[:limit]:
        our_rank = p['our_rank']
        avg_rank = p['avg_external_rank']

        if avg_rank:
            diff = our_rank - avg_rank  # Negative = we rank higher (better) than consensus
            diff_pct = (diff / avg_rank) * 100 if avg_rank > 0 else 0

            if diff < -20 and our_rank <= 50:  # We rank much higher than consensus
                overvalued.append(p)
                assessment = "^HIGH"
            elif diff > 20 and avg_rank <= 50:  # We rank much lower than consensus
                undervalued.append(p)
                assessment = "vLOW"
            else:
                well_calibrated.append(p)
                assessment = ""
        else:
            diff = None
            assessment = ""

        # Build row
        row = f"{our_rank:<5} {p['name']:<22} {p['our_value']:<8.1f}"

        if avg_rank:
            row += f" {avg_rank:<6.0f} {diff:>+5.0f} "
        else:
            row += f" {'N/A':<6} {'':>5} "

        # Add individual source ranks
        for src in main_sources[1:]:
            rank = p['ranks'].get(src)
            if rank:
                row += f" {rank:<6}"
            else:
                row += f" {'-':<6}"

        row += f" {assessment}"
        print(row)

    # Summary
    print("\n" + "=" * 160)
    print("CALIBRATION SUMMARY")
    print("=" * 160)

    print(f"\nPlayers where we rank HIGHER than consensus (potential overvaluation):")
    print("-" * 80)
    for p in sorted(overvalued, key=lambda x: x['our_rank'] - x['avg_external_rank'])[:15]:
        diff = p['our_rank'] - p['avg_external_rank']
        print(f"  #{p['our_rank']:<3} {p['name']:<25} Value: {p['our_value']:.1f}  "
              f"Our Rank: {p['our_rank']} vs Avg: {p['avg_external_rank']:.0f} ({diff:+.0f})")

    print(f"\nPlayers where we rank LOWER than consensus (potential undervaluation):")
    print("-" * 80)
    for p in sorted(undervalued, key=lambda x: x['avg_external_rank'] - x['our_rank'])[:15]:
        diff = p['our_rank'] - p['avg_external_rank']
        print(f"  #{p['our_rank']:<3} {p['name']:<25} Value: {p['our_value']:.1f}  "
              f"Our Rank: {p['our_rank']} vs Avg: {p['avg_external_rank']:.0f} ({diff:+.0f})")

    return overvalued, undervalued


def main():
    comparison, sources = create_comparison_report()
    overvalued, undervalued = print_comparison_report(comparison, sources, limit=75)

    print("\n" + "=" * 160)
    print("RECOMMENDED FORMULA ADJUSTMENTS")
    print("=" * 160)

    if undervalued:
        print("\nPlayers to BOOST (we undervalue vs consensus):")
        for p in sorted(undervalued, key=lambda x: x['avg_external_rank'])[:10]:
            boost_factor = p['our_rank'] / p['avg_external_rank'] if p['avg_external_rank'] > 0 else 1.0
            print(f"  {p['name']:<25} Our #{p['our_rank']} -> Target #{p['avg_external_rank']:.0f} "
                  f"(boost ~{boost_factor:.2f}x)")

    if overvalued:
        print("\nPlayers to REDUCE (we overvalue vs consensus):")
        for p in sorted(overvalued, key=lambda x: x['our_rank'])[:10]:
            reduce_factor = p['avg_external_rank'] / p['our_rank'] if p['our_rank'] > 0 else 1.0
            print(f"  {p['name']:<25} Our #{p['our_rank']} -> Target #{p['avg_external_rank']:.0f} "
                  f"(reduce to ~{reduce_factor:.2f}x)")


if __name__ == "__main__":
    main()

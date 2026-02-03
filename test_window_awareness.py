"""Test enhanced window awareness calculations."""
import os
os.chdir(r"C:\Users\Alex\DiamondDynastiesTradeAnalyzer")

from app import (
    teams,
    calculate_team_needs,
    _window_analysis_cache,
    calculate_core_weighted_age,
    calculate_peak_timing,
    calculate_prospect_proximity,
    calc_player_value
)

print("=" * 70)
print("ENHANCED WINDOW AWARENESS TEST")
print("=" * 70)

# Test all teams
for team_name in sorted(teams.keys())[:6]:  # Test first 6 teams
    team = teams[team_name]

    # Calculate needs (this populates the cache)
    cat_scores, pos_depth, window = calculate_team_needs(team_name)

    print(f"\n{team_name}")
    print("-" * 50)

    if team_name in _window_analysis_cache:
        cache = _window_analysis_cache[team_name]

        print(f"  Window: {window.upper()}")
        print(f"  Combined Score: {cache['score']:.2f}")
        print(f"  Core Age (weighted): {cache['core_age']}")
        print(f"  Years in Window: {cache['peak_timing']['years_in_window']}")
        print(f"  Core Status: {cache['peak_timing']['ascending_count']} ascending, "
              f"{cache['peak_timing']['peak_count']} peak, "
              f"{cache['peak_timing']['declining_count']} declining")
        print(f"  Prospect ETA: {cache['prospect_proximity']['avg_eta']} years")
        print(f"  MLB-Ready Prospects: {cache['prospect_proximity']['mlb_ready_count']}")

        # Show score breakdown
        d = cache['details']
        print(f"  Score Breakdown: rank={d['rank_score']:.2f}, age={d['age_score']:.2f}, "
              f"peak={d['peak_score']:.2f}, prospects={d['prospect_score']:.2f}")
    else:
        print(f"  Window: {window} (no cache)")

print("\n" + "=" * 70)
print("Test complete!")

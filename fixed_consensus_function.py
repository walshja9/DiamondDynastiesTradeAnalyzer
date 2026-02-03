def load_consensus_rankings_FIXED() -> dict:
    """Load weighted consensus dynasty rankings from 10 external sources.

    FIX: Only use CFR (Consensus Formulated Ranks) for MiLB players
    - MLB players: FHQ, HKB, Steamer, ZiPS (no CFR)
    - MiLB players: FHQ, HKB, Steamer, ZiPS, CFR
    
    CFR is prospect-focused so it underranks established MLB players.
    Mason Miller at A+ gets CFR rank 691, killing his consensus.
    Solution: exclude CFR for MLB players.
    """
    import os
    import csv
    
    script_dir = os.path.dirname(os.path.abspath(__file__))

    SOURCE_WEIGHTS = {
        'FHQ': 0.30,
        'HKB': 0.30,
        'Steamer': 0.10,
        'ZiPS': 0.10,
        'CFR': 0.20,
    }

    all_sources = {}
    cfr_player_levels = {}  # Track player levels from CFR
    
    # Load FantraxHQ rankings [... existing code ...]
    # Load HKB rankings [... existing code ...]
    # Load Steamer rankings [... existing code ...]
    # Load ZiPS rankings [... existing code ...]

    # Load CFR with level tracking
    cfr_ranks = {}
    cfr_p_path = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")
    try:
        with open(cfr_p_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip()
                rank = row.get('Avg Rank', '')
                level = row.get('Level', '').strip()
                if name and rank:
                    try:
                        cfr_ranks[name] = int(float(rank))
                        cfr_player_levels[name] = level
                    except ValueError:
                        pass
    except Exception:
        pass

    cfr_h_path = os.path.join(script_dir, "Consensus Formulated Ranks_Hitters_2026.csv")
    try:
        with open(cfr_h_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip()
                rank = row.get('Avg Rank', '')
                level = row.get('Level', '').strip()
                if name and rank:
                    try:
                        cfr_ranks[name] = int(float(rank))
                        cfr_player_levels[name] = level
                    except ValueError:
                        pass
    except Exception:
        pass

    all_sources['CFR'] = cfr_ranks

    # Collect all unique player names
    all_names = set()
    for source_dict in all_sources.values():
        all_names.update(source_dict.keys())

    # Build consensus rankings with level-aware CFR filtering
    consensus_ranks = {}
    for name in all_names:
        ranks_to_use = {}
        total_weight = 0.0

        for source_name, source_dict in all_sources.items():
            if name in source_dict:
                rank = source_dict[name]
                
                # FILTER: Exclude CFR for MLB players
                if source_name == 'CFR':
                    player_level = cfr_player_levels.get(name, 'UNKNOWN')
                    # Only include CFR for MiLB players
                    if player_level in ['A', 'A+', 'AA', 'AAA', 'CPX']:
                        ranks_to_use[source_name] = (rank, SOURCE_WEIGHTS[source_name])
                        total_weight += SOURCE_WEIGHTS[source_name]
                    # Skip CFR for MLB players
                else:
                    ranks_to_use[source_name] = (rank, SOURCE_WEIGHTS[source_name])
                    total_weight += SOURCE_WEIGHTS[source_name]

        if ranks_to_use and total_weight > 0:
            weighted_sum = sum(rank * weight for rank, weight in ranks_to_use.values())
            consensus_ranks[name] = weighted_sum / total_weight

    return consensus_ranks

print("FIXED ALGORITHM:")
print("""
For each player:
  IF player in CFR:
    level = CFR['level']
    IF level in ['A', 'A+', 'AA', 'AAA', 'CPX']:
      Include CFR with 20% weight
    ELSE IF level == 'MLB':
      EXCLUDE CFR (use FHQ, HKB, Steamer, ZiPS only)
  
Result: Mason Miller gets ranked by FHQ/HKB/Steamer/ZiPS only
        (no CFR 691 killing his score)
""")

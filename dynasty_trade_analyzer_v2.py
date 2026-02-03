"""
Diamond Dynasties Trade Analyzer V2
Enhanced trade analysis with expanded projections, multi-player trades, and interactive mode

V2 Enhancements:
1. Expanded projection coverage (600+ players vs ~290)
2. Multi-player trade logic (2-for-1, 3-for-2, etc.)
3. Interactive mode for user-specified trades
4. Full SV+HLD integration for relievers

League Settings:
- 12 Teams, 48 players + 14 MiLB + 6 IR
- Hitting Categories: AVG, OPS, HR, R, RBI, SB, SO (7 cats)
- Pitching Categories: ERA, WHIP, K, QS, SV+HLD, L, K/BB (7 cats)
- Positions: C, 1B, 2B, SS, 3B, MI, CI, INF, 5 OF, 3 UTIL, 6 SP, 5 RP, 1 P

Value Calculation System:
==========================
Values are calculated using a hybrid approach that combines:
1. Projection-based value (actual expected production)
2. Weighted consensus from 10 external ranking sources

Consensus Sources & Weights:
- Dynasty Rankings (50% total): FHQ (25%), HKB (25%)
- Production Projections (30% total): Steamer (15%), ZiPS (15%)
- Supplemental (20% total): STS (10%), CFR (5%), PL (5%)

In-Season Blending:
===================
During the season, values blend projections with actual performance.
Early on, projections matter more. As the season progresses, actual stats take over.

Games Played    Projection Weight    Actual Pace Weight
------------    -----------------    ------------------
< 20            100%                 0%     (Too early, projections only)
20-40           80%                  20%    (April - small sample)
40-60           65%                  35%    (May - emerging trends)
60-90           50%                  50%    (June/July - even blend)
90-120          35%                  65%    (August - actual dominates)
120+            20%                  80%    (September - nearly all actual)
"""

import csv
import json
import os
import unicodedata
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import math


def normalize_name(name: str) -> str:
    """Normalize player name by removing accents and standardizing characters."""
    normalized = unicodedata.normalize('NFD', name)
    ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return ascii_name.strip()


def load_prospect_rankings() -> Dict[str, int]:
    """Load prospect rankings from prospects.json file.

    Looks for the file in the same directory as this script.
    Returns empty dict if file not found.
    """
    # Try multiple locations for the prospects.json file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    possible_paths = [
        os.path.join(script_dir, 'prospects.json'),
        os.path.join(os.path.expanduser('~'), 'prospects.json'),
        'prospects.json',
    ]

    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    rankings = json.load(f)
                    print(f"Loaded {len(rankings)} prospect rankings from: {path}")
                    return rankings
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load prospects.json: {e}")
                continue

    print("Warning: prospects.json not found. Prospect rankings will be empty.")
    return {}


def load_consensus_rankings() -> Dict[str, float]:
    """Load weighted consensus dynasty rankings from 10 external sources.

    Sources & Weights:
    - Dynasty Rankings (50% total): FHQ (25%), HKB (25%)
    - Production Projections (30% total): Steamer (15%), ZiPS (15%)
    - Supplemental (20% total): STS (10%), CFR (5%), PL (5%)

    Returns a dict mapping player name to weighted average consensus rank.
    This is used for hybrid value calculation - pulling projection-based
    values toward market consensus when there's significant deviation.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Source weights (must sum to 1.0 when all sources present)
    # Optimized weights - removed STS/PL standalone since they're already in CFR
    SOURCE_WEIGHTS = {
        'FHQ': 0.30,      # Dynasty rankings (FantraxHQ Top 500)
        'HKB': 0.30,      # Dynasty rankings (harryknowsball values)
        'Steamer': 0.10,  # Production projections
        'ZiPS': 0.10,     # Production projections
        'CFR': 0.20,      # Consensus Formulated Ranks (includes PL, STS, DIGS, FScore, PG+)
        # STS and PL removed - already included in CFR to avoid double-counting
    }

    all_sources = {}
    cfr_player_info = {}  # Track {name: {'level': ..., 'age': ...}} from CFR for filtering
    player_ages_from_sources = {}  # Load ages from HKB/FHQ to filter CFR properly

    # Load FantraxHQ rankings
    fhq_path = os.path.join(script_dir, "Top-500 Fantasy Baseball Dynasty Rankings - FantraxHQ.csv")
    try:
        fhq_ranks = {}
        with open(fhq_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Player', '').strip()
                roto_rank = row.get('Roto', '')
                age_str = row.get('Age', '')
                if name and roto_rank:
                    try:
                        fhq_ranks[name] = int(roto_rank)
                        if age_str:
                            player_ages_from_sources[name] = float(age_str)
                    except ValueError:
                        pass
        all_sources['FHQ'] = fhq_ranks
    except Exception:
        pass

    # Load harryknowsball rankings
    hkb_path = os.path.join(script_dir, "harryknowsball_players.csv")
    try:
        hkb_ranks = {}
        with open(hkb_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip()
                rank = row.get('Rank', '')
                age_str = row.get('Age', '')
                if name and rank:
                    try:
                        hkb_ranks[name] = int(rank)
                        if age_str and name not in player_ages_from_sources:
                            player_ages_from_sources[name] = float(age_str)
                    except ValueError:
                        pass
        all_sources['HKB'] = hkb_ranks
    except Exception:
        pass

    # Load Scout the Statline rankings
    sts_path = os.path.join(script_dir, "Scout the Statline Peak Projections_ Members - MLB_Combined_Table.csv")
    try:
        sts_ranks = {}
        with open(sts_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Player', '').strip()
                rank = row.get('Rank', '')
                if name and rank:
                    try:
                        sts_ranks[name] = int(rank)
                    except ValueError:
                        pass
        all_sources['STS'] = sts_ranks
    except Exception:
        pass

    # Load Steamer projections (hitters + pitchers combined, rank by WAR)
    steamer_players = []
    # Hitters
    steamer_h_path = os.path.join(script_dir, "fangraphs-leaderboard-projections-steamer.csv")
    try:
        with open(steamer_h_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = normalize_name(row.get('Name', '').strip().strip('"'))
                war = row.get('WAR', '')
                if name and war:
                    try:
                        steamer_players.append((name, float(war)))
                    except ValueError:
                        pass
    except Exception:
        pass
    # Pitchers
    steamer_p_path = os.path.join(script_dir, "fangraphs-leaderboard-projections-pitcher-steamer.csv")
    try:
        with open(steamer_p_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = normalize_name(row.get('Name', '').strip().strip('"'))
                war = row.get('WAR', '')
                if name and war:
                    try:
                        steamer_players.append((name, float(war)))
                    except ValueError:
                        pass
    except Exception:
        pass
    if steamer_players:
        steamer_players.sort(key=lambda x: -x[1])
        # Keep best (lowest) rank for duplicates like Ohtani who appear in both hitter/pitcher files
        steamer_ranks = {}
        for i, (name, _) in enumerate(steamer_players, 1):
            if name not in steamer_ranks:
                steamer_ranks[name] = i
        all_sources['Steamer'] = steamer_ranks

    # Load ZiPS projections (hitters + pitchers combined, rank by WAR)
    zips_players = []
    # Hitters
    zips_h_path = os.path.join(script_dir, "fangraphs-leaderboard-projections-zips.csv")
    try:
        with open(zips_h_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = normalize_name(row.get('Name', '').strip().strip('"'))
                war = row.get('WAR', '')
                if name and war:
                    try:
                        zips_players.append((name, float(war)))
                    except ValueError:
                        pass
    except Exception:
        pass
    # Pitchers
    zips_p_path = os.path.join(script_dir, "fangraphs-leaderboard-projections-pitcher-zips.csv")
    try:
        with open(zips_p_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = normalize_name(row.get('Name', '').strip().strip('"'))
                war = row.get('WAR', '')
                if name and war:
                    try:
                        zips_players.append((name, float(war)))
                    except ValueError:
                        pass
    except Exception:
        pass
    if zips_players:
        zips_players.sort(key=lambda x: -x[1])
        # Keep best (lowest) rank for duplicates like Ohtani who appear in both hitter/pitcher files
        zips_ranks = {}
        for i, (name, _) in enumerate(zips_players, 1):
            if name not in zips_ranks:
                zips_ranks[name] = i
        all_sources['ZiPS'] = zips_ranks

    # Load Consensus Formulated Ranks (hitters)
    cfr_h_path = os.path.join(script_dir, "Consensus Formulated Ranks_Hitters_2026.csv")
    cfr_ranks = {}
    try:
        with open(cfr_h_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = normalize_name(row.get('Name', '').strip())
                avg_rank = row.get('Avg Rank', '')
                level = row.get('Level', '').strip()
                age_str = row.get('Age', '')
                if name and avg_rank:
                    try:
                        age = float(age_str) if age_str else None
                        cfr_ranks[name] = int(float(avg_rank))
                        cfr_player_info[name] = {'level': level, 'age': age}
                    except ValueError:
                        pass
    except Exception:
        pass

    # Load Consensus Formulated Ranks (pitchers)
    cfr_p_path = os.path.join(script_dir, "Consensus Formulated Ranks_Pitchers_2026.csv")
    try:
        with open(cfr_p_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = normalize_name(row.get('Name', '').strip())
                avg_rank = row.get('Avg Rank', '')
                level = row.get('Level', '').strip()
                age_str = row.get('Age', '')
                if name and avg_rank and name not in cfr_ranks:
                    try:
                        age = float(age_str) if age_str else None
                        cfr_ranks[name] = int(float(avg_rank))
                        cfr_player_info[name] = {'level': level, 'age': age}
                    except ValueError:
                        pass
    except Exception:
        pass
    if cfr_ranks:
        all_sources['CFR'] = cfr_ranks

    # Load Prospects Live
    pl_path = os.path.join(script_dir, "Prospects Live Top 500 Fantasy Prospects.csv")
    try:
        pl_ranks = {}
        with open(pl_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = normalize_name(row.get('Name_FG', '').strip().strip('"'))
                rank = row.get('Rank', '')
                if name and rank:
                    try:
                        pl_ranks[name] = int(rank)
                    except ValueError:
                        pass
        all_sources['PL'] = pl_ranks
    except Exception:
        pass

    # Combine into weighted consensus rank
    all_players = set()
    for source_data in all_sources.values():
        all_players.update(source_data.keys())

    consensus = {}
    for name in all_players:
        weighted_sum = 0.0
        total_weight = 0.0

        for source_name, source_data in all_sources.items():
            if name in source_data:
                # FIX: Exclude CFR for MLB players and mature players (it's prospect-focused)
                # Only include CFR for young MiLB/prospect players (<25 years old)
                if source_name == 'CFR':
                    info = cfr_player_info.get(name, {})
                    player_level = info.get('level', 'UNKNOWN')
                    # Use age from HKB/FHQ if available, otherwise use CFR age
                    player_age = player_ages_from_sources.get(name, info.get('age'))
                    # Exclude CFR if: 1) MLB level, OR 2) Age 25+ (mature/established)
                    if player_level == 'MLB' or (player_age and player_age >= 25):
                        continue  # Skip CFR for MLB or mature players

                rank = source_data[name]
                # Filter out extreme ranks (>500) to avoid noise
                if rank <= 500:
                    weight = SOURCE_WEIGHTS.get(source_name, 0.05)
                    weighted_sum += rank * weight
                    total_weight += weight

        if total_weight > 0:
            consensus[name] = weighted_sum / total_weight

    if consensus:
        sources_loaded = list(all_sources.keys())
        print(f"Loaded weighted consensus for {len(consensus)} players from {len(sources_loaded)} sources: {', '.join(sources_loaded)}")

    return consensus


# Global consensus rankings - loaded once at module import
CONSENSUS_RANKINGS = load_consensus_rankings()


# ============================================================================
# DATA STRUCTURES
# ============================================================================

def get_inseason_weights(games_played: int) -> Tuple[float, float]:
    """Get projection vs actual performance weights based on games played.

    Returns (projection_weight, actual_weight) tuple that sums to 1.0.

    In-Season Blending:
    - < 20 GP:   100% projection, 0% actual (too early)
    - 20-40 GP:  80% projection, 20% actual (April - small sample)
    - 40-60 GP:  65% projection, 35% actual (May - emerging trends)
    - 60-90 GP:  50% projection, 50% actual (June/July - even blend)
    - 90-120 GP: 35% projection, 65% actual (August - actual dominates)
    - 120+ GP:   20% projection, 80% actual (September - nearly all actual)
    """
    if games_played < 20:
        return (1.0, 0.0)
    elif games_played < 40:
        return (0.80, 0.20)
    elif games_played < 60:
        return (0.65, 0.35)
    elif games_played < 90:
        return (0.50, 0.50)
    elif games_played < 120:
        return (0.35, 0.65)
    else:
        return (0.20, 0.80)


@dataclass
class Player:
    """Represents a baseball player with projections and dynasty value."""
    name: str
    position: str = "N/A"
    mlb_team: str = "FA"
    fantasy_team: str = ""
    roster_status: str = "Active"  # Active, Reserve, Minors, Inj Res
    age: int = 0
    fantrax_score: float = 100.0  # Default to established (only explicitly low scores trigger discount)
    fantrax_rank: int = 9999  # Default to high rank (unranked/unknown player)
    throws: str = ""  # L = Left, R = Right (for pitchers)

    # Hitting projections (preseason/ROS projections)
    proj_avg: float = 0.0
    proj_ops: float = 0.0
    proj_hr: int = 0
    proj_r: int = 0
    proj_rbi: int = 0
    proj_sb: int = 0
    proj_so: int = 0  # Lower is better
    proj_ab: int = 0

    # Pitching projections (preseason/ROS projections)
    proj_era: float = 0.0
    proj_whip: float = 0.0
    proj_k: int = 0
    proj_qs: int = 0
    proj_sv_hld: int = 0
    proj_l: int = 0  # Lower is better
    proj_ip: float = 0.0

    # Actual in-season stats (for blending)
    games_played: int = 0  # G for hitters, GS for pitchers
    actual_avg: float = 0.0
    actual_ops: float = 0.0
    actual_hr: int = 0
    actual_r: int = 0
    actual_rbi: int = 0
    actual_sb: int = 0
    actual_so: int = 0
    actual_ab: int = 0
    actual_era: float = 0.0
    actual_whip: float = 0.0
    actual_k: int = 0
    actual_qs: int = 0
    actual_sv_hld: int = 0
    actual_l: int = 0
    actual_ip: float = 0.0

    # Dynasty/Prospect value
    prospect_rank: int = 999  # Top 100 rank (999 = not ranked)
    is_prospect: bool = False

    def is_hitter(self) -> bool:
        return self.position not in ['SP', 'RP', 'P'] and self.position != 'N/A'

    def is_pitcher(self) -> bool:
        return self.position in ['SP', 'RP', 'P'] or 'SP' in self.position or 'RP' in self.position

    def get_blended_stat(self, proj_stat: float, actual_stat: float, games: int = None) -> float:
        """Blend projection with actual stat based on games played."""
        gp = games if games is not None else self.games_played
        proj_weight, actual_weight = get_inseason_weights(gp)
        return proj_stat * proj_weight + actual_stat * actual_weight


@dataclass
class Team:
    """Represents a fantasy team with roster and analysis."""
    name: str
    players: List[Player] = field(default_factory=list)
    
    # Category strengths (calculated)
    hitting_strengths: Dict[str, float] = field(default_factory=dict)
    hitting_weaknesses: Dict[str, float] = field(default_factory=dict)
    pitching_strengths: Dict[str, float] = field(default_factory=dict)
    pitching_weaknesses: Dict[str, float] = field(default_factory=dict)
    
    # Positional depth
    position_depth: Dict[str, List[Player]] = field(default_factory=dict)
    position_needs: List[str] = field(default_factory=list)


@dataclass 
class TradeProposal:
    """Represents a trade proposal with analysis."""
    team_a: str
    team_b: str
    players_from_a: List[Player]
    players_from_b: List[Player]
    picks_from_a: List[str] = field(default_factory=list)
    picks_from_b: List[str] = field(default_factory=list)
    
    # Analysis results
    value_a_receives: float = 0.0
    value_b_receives: float = 0.0
    category_impact_a: Dict[str, float] = field(default_factory=dict)
    category_impact_b: Dict[str, float] = field(default_factory=dict)
    fit_score_a: float = 0.0  # How well trade fits team A's needs
    fit_score_b: float = 0.0  # How well trade fits team B's needs
    verdict: str = ""
    reasoning: str = ""


# ============================================================================
# PROJECTION DATA (From FantasyPros Consensus - Steamer/ZiPS/etc)
# ============================================================================

# Top hitter projections - parsed from FantasyPros
HITTER_PROJECTIONS = {
    "Shohei Ohtani": {"AB": 573, "R": 121, "HR": 47, "RBI": 112, "SB": 24, "AVG": .282, "OPS": .977, "SO": 163},
    "Aaron Judge": {"AB": 537, "R": 111, "HR": 49, "RBI": 118, "SB": 9, "AVG": .290, "OPS": 1.030, "SO": 164},
    "Bobby Witt Jr.": {"AB": 602, "R": 103, "HR": 29, "RBI": 94, "SB": 34, "AVG": .292, "OPS": .863, "SO": 111},
    "Juan Soto": {"AB": 538, "R": 106, "HR": 37, "RBI": 98, "SB": 20, "AVG": .274, "OPS": .942, "SO": 119},
    "Ronald Acuna Jr.": {"AB": 555, "R": 104, "HR": 30, "RBI": 86, "SB": 26, "AVG": .283, "OPS": .882, "SO": 136},
    "Vladimir Guerrero Jr.": {"AB": 581, "R": 97, "HR": 32, "RBI": 100, "SB": 5, "AVG": .299, "OPS": .900, "SO": 90},
    "Julio Rodriguez": {"AB": 606, "R": 93, "HR": 30, "RBI": 94, "SB": 26, "AVG": .277, "OPS": .817, "SO": 146},
    "Fernando Tatis Jr.": {"AB": 588, "R": 101, "HR": 31, "RBI": 88, "SB": 25, "AVG": .272, "OPS": .842, "SO": 133},
    "Jose Ramirez": {"AB": 586, "R": 91, "HR": 27, "RBI": 90, "SB": 34, "AVG": .272, "OPS": .823, "SO": 77},
    "Corbin Carroll": {"AB": 567, "R": 103, "HR": 27, "RBI": 86, "SB": 35, "AVG": .261, "OPS": .832, "SO": 136},
    "Junior Caminero": {"AB": 580, "R": 86, "HR": 38, "RBI": 105, "SB": 5, "AVG": .274, "OPS": .843, "SO": 121},
    "Gunnar Henderson": {"AB": 582, "R": 97, "HR": 27, "RBI": 88, "SB": 22, "AVG": .274, "OPS": .833, "SO": 138},
    "Elly De La Cruz": {"AB": 585, "R": 93, "HR": 24, "RBI": 82, "SB": 40, "AVG": .261, "OPS": .790, "SO": 175},
    "Kyle Tucker": {"AB": 542, "R": 93, "HR": 28, "RBI": 88, "SB": 21, "AVG": .271, "OPS": .861, "SO": 96},
    "Yordan Alvarez": {"AB": 480, "R": 88, "HR": 32, "RBI": 89, "SB": 4, "AVG": .297, "OPS": .948, "SO": 94},
    "Kyle Schwarber": {"AB": 559, "R": 99, "HR": 42, "RBI": 103, "SB": 6, "AVG": .232, "OPS": .847, "SO": 187},
    "Bryce Harper": {"AB": 558, "R": 89, "HR": 29, "RBI": 93, "SB": 10, "AVG": .273, "OPS": .855, "SO": 138},
    "Pete Alonso": {"AB": 589, "R": 90, "HR": 37, "RBI": 103, "SB": 3, "AVG": .253, "OPS": .816, "SO": 154},
    "Francisco Lindor": {"AB": 595, "R": 93, "HR": 27, "RBI": 81, "SB": 24, "AVG": .257, "OPS": .775, "SO": 125},
    "Jackson Chourio": {"AB": 576, "R": 85, "HR": 24, "RBI": 81, "SB": 24, "AVG": .270, "OPS": .779, "SO": 126},
    "Nick Kurtz": {"AB": 506, "R": 89, "HR": 36, "RBI": 90, "SB": 4, "AVG": .258, "OPS": .880, "SO": 173},
    "Jacob Wilson": {"AB": 486, "R": 62, "HR": 13, "RBI": 63, "SB": 5, "AVG": .311, "OPS": .800, "SO": 85},
    "Caleb Durbin": {"AB": 445, "R": 60, "HR": 11, "RBI": 53, "SB": 18, "AVG": .256, "OPS": .721, "SO": 105},
    "Ketel Marte": {"AB": 547, "R": 89, "HR": 28, "RBI": 88, "SB": 5, "AVG": .275, "OPS": .846, "SO": 104},
    "Zach Neto": {"AB": 578, "R": 86, "HR": 27, "RBI": 79, "SB": 28, "AVG": .252, "OPS": .757, "SO": 157},
    "Geraldo Perdomo": {"AB": 506, "R": 84, "HR": 13, "RBI": 72, "SB": 18, "AVG": .277, "OPS": .793, "SO": 87},
    "Trea Turner": {"AB": 579, "R": 86, "HR": 18, "RBI": 71, "SB": 27, "AVG": .280, "OPS": .766, "SO": 115},
    "Cal Raleigh": {"AB": 543, "R": 86, "HR": 39, "RBI": 99, "SB": 8, "AVG": .232, "OPS": .820, "SO": 169},
    "Pete Crow-Armstrong": {"AB": 562, "R": 83, "HR": 24, "RBI": 76, "SB": 34, "AVG": .250, "OPS": .737, "SO": 148},
    "Freddie Freeman": {"AB": 573, "R": 86, "HR": 23, "RBI": 87, "SB": 8, "AVG": .275, "OPS": .813, "SO": 121},
    "Jazz Chisholm Jr.": {"AB": 534, "R": 82, "HR": 29, "RBI": 78, "SB": 31, "AVG": .240, "OPS": .764, "SO": 158},
    "Manny Machado": {"AB": 591, "R": 81, "HR": 28, "RBI": 90, "SB": 10, "AVG": .264, "OPS": .781, "SO": 127},
    "Austin Riley": {"AB": 593, "R": 85, "HR": 30, "RBI": 94, "SB": 3, "AVG": .262, "OPS": .790, "SO": 170},
    "Bo Bichette": {"AB": 593, "R": 81, "HR": 19, "RBI": 80, "SB": 7, "AVG": .292, "OPS": .790, "SO": 104},
    "Matt Olson": {"AB": 587, "R": 91, "HR": 31, "RBI": 94, "SB": 1, "AVG": .250, "OPS": .803, "SO": 162},
    "Vinnie Pasquantino": {"AB": 558, "R": 77, "HR": 26, "RBI": 88, "SB": 1, "AVG": .264, "OPS": .791, "SO": 90},
    "Byron Buxton": {"AB": 488, "R": 79, "HR": 29, "RBI": 76, "SB": 16, "AVG": .251, "OPS": .804, "SO": 148},
    "Seiya Suzuki": {"AB": 544, "R": 82, "HR": 26, "RBI": 84, "SB": 9, "AVG": .254, "OPS": .792, "SO": 156},
    "Riley Greene": {"AB": 564, "R": 83, "HR": 28, "RBI": 87, "SB": 4, "AVG": .259, "OPS": .796, "SO": 174},
    "Mookie Betts": {"AB": 509, "R": 86, "HR": 22, "RBI": 78, "SB": 11, "AVG": .273, "OPS": .814, "SO": 78},
    "Brandon Lowe": {"AB": 507, "R": 70, "HR": 25, "RBI": 75, "SB": 5, "AVG": .243, "OPS": .749, "SO": 144},
    "Brice Turang": {"AB": 576, "R": 80, "HR": 14, "RBI": 64, "SB": 30, "AVG": .257, "OPS": .711, "SO": 134},
    "Matt Chapman": {"AB": 566, "R": 83, "HR": 26, "RBI": 81, "SB": 10, "AVG": .237, "OPS": .757, "SO": 162},
    "Adley Rutschman": {"AB": 493, "R": 69, "HR": 17, "RBI": 66, "SB": 1, "AVG": .254, "OPS": .755, "SO": 89},
    "Drake Baldwin": {"AB": 455, "R": 61, "HR": 17, "RBI": 65, "SB": 1, "AVG": .262, "OPS": .756, "SO": 92},
    "Sal Stewart": {"AB": 372, "R": 49, "HR": 15, "RBI": 54, "SB": 5, "AVG": .264, "OPS": .772, "SO": 82},
    "Josh Lowe": {"AB": 415, "R": 55, "HR": 13, "RBI": 52, "SB": 20, "AVG": .245, "OPS": .712, "SO": 122},
    "Jung Hoo Lee": {"AB": 524, "R": 71, "HR": 9, "RBI": 56, "SB": 9, "AVG": .271, "OPS": .734, "SO": 67},
    "Spencer Horwitz": {"AB": 431, "R": 59, "HR": 11, "RBI": 52, "SB": 2, "AVG": .259, "OPS": .742, "SO": 90},
    "Brandon Marsh": {"AB": 418, "R": 57, "HR": 13, "RBI": 52, "SB": 10, "AVG": .251, "OPS": .730, "SO": 133},
    "Jakob Marsee": {"AB": 490, "R": 71, "HR": 13, "RBI": 51, "SB": 32, "AVG": .230, "OPS": .684, "SO": 127},
    # Additional Star Tier
    "Marcell Ozuna": {"AB": 560, "R": 80, "HR": 33, "RBI": 95, "SB": 2, "AVG": .268, "OPS": .831, "SO": 132},
    "Michael Harris II": {"AB": 545, "R": 78, "HR": 22, "RBI": 75, "SB": 18, "AVG": .270, "OPS": .778, "SO": 120},
    "Willy Adames": {"AB": 565, "R": 88, "HR": 28, "RBI": 86, "SB": 14, "AVG": .236, "OPS": .765, "SO": 172},
    "Ezequiel Tovar": {"AB": 588, "R": 82, "HR": 23, "RBI": 78, "SB": 18, "AVG": .265, "OPS": .753, "SO": 152},
    "Marcelo Mayer": {"AB": 500, "R": 70, "HR": 18, "RBI": 68, "SB": 8, "AVG": .255, "OPS": .740, "SO": 105},  # Rookie SS, graduated prospect
    "James Wood": {"AB": 550, "R": 79, "HR": 21, "RBI": 72, "SB": 22, "AVG": .262, "OPS": .775, "SO": 165},
    "Roman Anthony": {"AB": 517, "R": 84, "HR": 18, "RBI": 67, "SB": 9, "AVG": .267, "OPS": .803, "SO": 148},  # 22yo OF, graduated top prospect
    "Randy Arozarena": {"AB": 536, "R": 78, "HR": 22, "RBI": 74, "SB": 26, "AVG": .258, "OPS": .765, "SO": 145},
    "CJ Abrams": {"AB": 595, "R": 89, "HR": 16, "RBI": 68, "SB": 28, "AVG": .260, "OPS": .725, "SO": 148},
    "Luis Robert Jr.": {"AB": 490, "R": 72, "HR": 25, "RBI": 72, "SB": 18, "AVG": .253, "OPS": .775, "SO": 145},
    "Rafael Devers": {"AB": 578, "R": 85, "HR": 27, "RBI": 92, "SB": 3, "AVG": .272, "OPS": .815, "SO": 125},
    "Anthony Santander": {"AB": 555, "R": 82, "HR": 32, "RBI": 90, "SB": 5, "AVG": .254, "OPS": .805, "SO": 145},
    "Will Smith": {"AB": 478, "R": 70, "HR": 21, "RBI": 72, "SB": 5, "AVG": .261, "OPS": .789, "SO": 105},
    "Sal Frelick": {"AB": 550, "R": 78, "HR": 12, "RBI": 58, "SB": 22, "AVG": .285, "OPS": .752, "SO": 85},
    "Colton Cowser": {"AB": 540, "R": 80, "HR": 24, "RBI": 74, "SB": 10, "AVG": .255, "OPS": .780, "SO": 140},
    "Max Muncy": {"AB": 512, "R": 78, "HR": 26, "RBI": 80, "SB": 3, "AVG": .231, "OPS": .788, "SO": 148},
    "Tyler Soderstrom": {"AB": 520, "R": 72, "HR": 28, "RBI": 82, "SB": 4, "AVG": .258, "OPS": .800, "SO": 145},
    "Jarren Duran": {"AB": 570, "R": 90, "HR": 18, "RBI": 68, "SB": 28, "AVG": .282, "OPS": .775, "SO": 155},
    "Jose Siri": {"AB": 502, "R": 72, "HR": 24, "RBI": 68, "SB": 32, "AVG": .238, "OPS": .735, "SO": 168},
    "Jose Altuve": {"AB": 555, "R": 82, "HR": 18, "RBI": 70, "SB": 12, "AVG": .283, "OPS": .775, "SO": 98},
    "Corey Seager": {"AB": 550, "R": 85, "HR": 30, "RBI": 90, "SB": 2, "AVG": .275, "OPS": .850, "SO": 135},
    "Alex Bregman": {"AB": 565, "R": 84, "HR": 22, "RBI": 85, "SB": 4, "AVG": .268, "OPS": .790, "SO": 108},
    "Marcus Semien": {"AB": 595, "R": 92, "HR": 22, "RBI": 78, "SB": 16, "AVG": .260, "OPS": .755, "SO": 128},
    "Christian Yelich": {"AB": 480, "R": 72, "HR": 18, "RBI": 65, "SB": 18, "AVG": .275, "OPS": .800, "SO": 118},
    "Cody Bellinger": {"AB": 545, "R": 78, "HR": 24, "RBI": 82, "SB": 8, "AVG": .262, "OPS": .775, "SO": 145},
    "Josh Naylor": {"AB": 540, "R": 75, "HR": 22, "RBI": 85, "SB": 10, "AVG": .275, "OPS": .795, "SO": 108},
    "Oneil Cruz": {"AB": 545, "R": 78, "HR": 26, "RBI": 78, "SB": 28, "AVG": .235, "OPS": .745, "SO": 195},
    # Solid Starter Tier
    "Wyatt Langford": {"AB": 510, "R": 72, "HR": 20, "RBI": 68, "SB": 18, "AVG": .255, "OPS": .755, "SO": 142},
    "Dylan Crews": {"AB": 475, "R": 68, "HR": 16, "RBI": 58, "SB": 15, "AVG": .258, "OPS": .745, "SO": 125},
    "Evan Carter": {"AB": 465, "R": 68, "HR": 15, "RBI": 55, "SB": 16, "AVG": .258, "OPS": .755, "SO": 128},
    "Royce Lewis": {"AB": 375, "R": 55, "HR": 18, "RBI": 55, "SB": 8, "AVG": .265, "OPS": .795, "SO": 108},
    "Teoscar Hernandez": {"AB": 525, "R": 75, "HR": 26, "RBI": 82, "SB": 6, "AVG": .258, "OPS": .785, "SO": 145},
    "Nick Castellanos": {"AB": 555, "R": 75, "HR": 22, "RBI": 82, "SB": 3, "AVG": .268, "OPS": .775, "SO": 125},
    "Adolis Garcia": {"AB": 545, "R": 78, "HR": 28, "RBI": 88, "SB": 18, "AVG": .242, "OPS": .758, "SO": 175},
    "Bryan Reynolds": {"AB": 545, "R": 78, "HR": 22, "RBI": 75, "SB": 10, "AVG": .268, "OPS": .785, "SO": 118},
    "Isaac Paredes": {"AB": 505, "R": 72, "HR": 22, "RBI": 78, "SB": 2, "AVG": .255, "OPS": .775, "SO": 95},
    "Luis Arraez": {"AB": 545, "R": 72, "HR": 5, "RBI": 52, "SB": 3, "AVG": .312, "OPS": .762, "SO": 42},
    "Nolan Arenado": {"AB": 535, "R": 72, "HR": 22, "RBI": 82, "SB": 2, "AVG": .265, "OPS": .775, "SO": 98},
    "Alec Bohm": {"AB": 555, "R": 75, "HR": 18, "RBI": 82, "SB": 3, "AVG": .275, "OPS": .772, "SO": 115},
    "Tommy Edman": {"AB": 510, "R": 75, "HR": 14, "RBI": 55, "SB": 28, "AVG": .258, "OPS": .718, "SO": 108},
    "Daulton Varsho": {"AB": 480, "R": 68, "HR": 18, "RBI": 58, "SB": 15, "AVG": .242, "OPS": .728, "SO": 142},
    "Lawrence Butler": {"AB": 455, "R": 62, "HR": 20, "RBI": 62, "SB": 12, "AVG": .245, "OPS": .748, "SO": 148},
    "Austin Wells": {"AB": 425, "R": 55, "HR": 18, "RBI": 58, "SB": 2, "AVG": .252, "OPS": .755, "SO": 118},
    "Mike Trout": {"AB": 365, "R": 55, "HR": 22, "RBI": 55, "SB": 3, "AVG": .268, "OPS": .858, "SO": 108},
    "Chandler Simpson": {"AB": 410, "R": 58, "HR": 4, "RBI": 32, "SB": 42, "AVG": .265, "OPS": .682, "SO": 88},
    "Victor Scott II": {"AB": 385, "R": 55, "HR": 6, "RBI": 32, "SB": 35, "AVG": .252, "OPS": .678, "SO": 108},
}

# Top pitcher projections - parsed from FantasyPros
PITCHER_PROJECTIONS = {
    # Two-way player: Ohtani (projected for when healthy to pitch)
    "Shohei Ohtani": {"IP": 140.0, "K": 180, "W": 10, "L": 5, "ERA": 3.00, "WHIP": 1.00, "QS": 14},
    "Tarik Skubal": {"IP": 194.9, "K": 237, "W": 14, "L": 7, "ERA": 2.74, "WHIP": 0.97, "QS": 21},
    "Paul Skenes": {"IP": 187.2, "K": 222, "W": 14, "L": 7, "ERA": 2.78, "WHIP": 1.03, "QS": 21},
    "Garrett Crochet": {"IP": 186.8, "K": 229, "W": 14, "L": 7, "ERA": 2.99, "WHIP": 1.06, "QS": 19},
    "Cristopher Sanchez": {"IP": 193.2, "K": 188, "W": 13, "L": 8, "ERA": 3.21, "WHIP": 1.14, "QS": 20},
    "Logan Webb": {"IP": 198.1, "K": 188, "W": 14, "L": 9, "ERA": 3.28, "WHIP": 1.17, "QS": 20},
    "Logan Gilbert": {"IP": 165.9, "K": 184, "W": 11, "L": 8, "ERA": 3.42, "WHIP": 1.06, "QS": 16},
    "Bryan Woo": {"IP": 185.9, "K": 187, "W": 13, "L": 9, "ERA": 3.39, "WHIP": 1.05, "QS": 18},
    "Hunter Brown": {"IP": 180.5, "K": 195, "W": 13, "L": 8, "ERA": 3.44, "WHIP": 1.17, "QS": 18},
    "Max Fried": {"IP": 183.2, "K": 172, "W": 13, "L": 8, "ERA": 3.31, "WHIP": 1.17, "QS": 18},
    "Chris Sale": {"IP": 158.9, "K": 193, "W": 11, "L": 6, "ERA": 3.27, "WHIP": 1.10, "QS": 16},
    "Jacob deGrom": {"IP": 161.0, "K": 178, "W": 11, "L": 8, "ERA": 3.43, "WHIP": 1.05, "QS": 16},
    "Yoshinobu Yamamoto": {"IP": 157.6, "K": 172, "W": 12, "L": 6, "ERA": 3.28, "WHIP": 1.11, "QS": 16},
    "Hunter Greene": {"IP": 170.3, "K": 205, "W": 11, "L": 8, "ERA": 3.67, "WHIP": 1.12, "QS": 16},
    "George Kirby": {"IP": 171.6, "K": 167, "W": 12, "L": 9, "ERA": 3.60, "WHIP": 1.11, "QS": 17},
    "Cole Ragans": {"IP": 156.0, "K": 193, "W": 10, "L": 7, "ERA": 3.38, "WHIP": 1.14, "QS": 16},
    "Joe Ryan": {"IP": 170.4, "K": 186, "W": 11, "L": 9, "ERA": 3.80, "WHIP": 1.10, "QS": 16},
    "Framber Valdez": {"IP": 183.8, "K": 173, "W": 13, "L": 9, "ERA": 3.49, "WHIP": 1.23, "QS": 17},
    "Jesus Luzardo": {"IP": 175.1, "K": 195, "W": 12, "L": 9, "ERA": 3.73, "WHIP": 1.18, "QS": 17},
    "Spencer Schwellenbach": {"IP": 160.0, "K": 157, "W": 11, "L": 7, "ERA": 3.53, "WHIP": 1.11, "QS": 15},
    "Dylan Cease": {"IP": 176.3, "K": 207, "W": 12, "L": 9, "ERA": 3.76, "WHIP": 1.21, "QS": 16},
    "Nathan Eovaldi": {"IP": 165.0, "K": 157, "W": 11, "L": 8, "ERA": 3.56, "WHIP": 1.13, "QS": 16},
    "Sonny Gray": {"IP": 173.5, "K": 181, "W": 12, "L": 9, "ERA": 3.75, "WHIP": 1.19, "QS": 16},
    "Nick Pivetta": {"IP": 176.7, "K": 191, "W": 11, "L": 10, "ERA": 3.91, "WHIP": 1.16, "QS": 16},
    "Freddy Peralta": {"IP": 166.2, "K": 185, "W": 12, "L": 8, "ERA": 3.76, "WHIP": 1.19, "QS": 16},
    "Zack Wheeler": {"IP": 125.7, "K": 143, "W": 9, "L": 5, "ERA": 3.26, "WHIP": 1.07, "QS": 13},
    "Kevin Gausman": {"IP": 181.4, "K": 177, "W": 12, "L": 9, "ERA": 3.97, "WHIP": 1.21, "QS": 17},
    "Luis Castillo": {"IP": 178.2, "K": 167, "W": 11, "L": 9, "ERA": 3.88, "WHIP": 1.20, "QS": 16},
    "Pablo Lopez": {"IP": 165.5, "K": 166, "W": 11, "L": 9, "ERA": 3.84, "WHIP": 1.19, "QS": 15},
    "Blake Snell": {"IP": 141.8, "K": 175, "W": 10, "L": 6, "ERA": 3.49, "WHIP": 1.21, "QS": 15},
    "Brandon Woodruff": {"IP": 147.3, "K": 155, "W": 10, "L": 7, "ERA": 3.75, "WHIP": 1.13, "QS": 14},
    "Tyler Glasnow": {"IP": 132.3, "K": 154, "W": 9, "L": 6, "ERA": 3.70, "WHIP": 1.17, "QS": 13},
    "Gerrit Cole": {"IP": 120.9, "K": 122, "W": 8, "L": 6, "ERA": 3.84, "WHIP": 1.17, "QS": 11},
    "Kyle Bradish": {"IP": 145.2, "K": 155, "W": 9, "L": 7, "ERA": 3.57, "WHIP": 1.18, "QS": 15},
    "Shane McClanahan": {"IP": 131.0, "K": 138, "W": 8, "L": 7, "ERA": 3.66, "WHIP": 1.18, "QS": 13},
    "Joe Musgrove": {"IP": 149.1, "K": 141, "W": 9, "L": 8, "ERA": 3.92, "WHIP": 1.20, "QS": 14},
    "Nick Lodolo": {"IP": 150.1, "K": 150, "W": 9, "L": 9, "ERA": 4.04, "WHIP": 1.20, "QS": 14},
    "Chase Burns": {"IP": 127.1, "K": 152, "W": 8, "L": 7, "ERA": 3.68, "WHIP": 1.17, "QS": 12},
    "Ranger Suarez": {"IP": 167.0, "K": 149, "W": 11, "L": 8, "ERA": 3.66, "WHIP": 1.24, "QS": 16},
    "Kris Bubic": {"IP": 140.1, "K": 136, "W": 8, "L": 7, "ERA": 3.71, "WHIP": 1.25, "QS": 12},
    "Matthew Boyd": {"IP": 161.0, "K": 145, "W": 10, "L": 9, "ERA": 3.93, "WHIP": 1.21, "QS": 15},
    "David Peterson": {"IP": 163.5, "K": 146, "W": 10, "L": 8, "ERA": 3.94, "WHIP": 1.34, "QS": 15},
    "Ryan Weathers": {"IP": 121.7, "K": 114, "W": 7, "L": 7, "ERA": 4.11, "WHIP": 1.27, "QS": 9},
    "Joe Boyle": {"IP": 99.6, "K": 109, "W": 5, "L": 6, "ERA": 4.18, "WHIP": 1.36, "QS": 8},
    "Robert Gasser": {"IP": 87.5, "K": 82, "W": 5, "L": 5, "ERA": 4.01, "WHIP": 1.24, "QS": 5},
    "Payton Tolle": {"IP": 55.4, "K": 59, "W": 3, "L": 3, "ERA": 4.02, "WHIP": 1.24, "QS": 2},
    "Andrew Alvarez": {"IP": 111.4, "K": 80, "W": 5, "L": 6, "ERA": 4.44, "WHIP": 1.40, "QS": 6},
    # Additional Starters
    "Seth Lugo": {"IP": 175.2, "K": 165, "W": 12, "L": 9, "ERA": 3.72, "WHIP": 1.18, "QS": 17},
    "Shota Imanaga": {"IP": 165.5, "K": 172, "W": 11, "L": 8, "ERA": 3.68, "WHIP": 1.15, "QS": 16},
    "Jared Jones": {"IP": 145.2, "K": 162, "W": 9, "L": 8, "ERA": 3.85, "WHIP": 1.22, "QS": 14},
    "Tanner Bibee": {"IP": 162.5, "K": 168, "W": 11, "L": 9, "ERA": 3.92, "WHIP": 1.18, "QS": 15},
    "Luis Gil": {"IP": 152.8, "K": 175, "W": 10, "L": 8, "ERA": 3.95, "WHIP": 1.28, "QS": 14},
    "Michael King": {"IP": 168.5, "K": 172, "W": 11, "L": 9, "ERA": 3.82, "WHIP": 1.18, "QS": 16},
    "Grayson Rodriguez": {"IP": 158.5, "K": 165, "W": 10, "L": 9, "ERA": 3.95, "WHIP": 1.22, "QS": 15},
    "Corbin Burnes": {"IP": 182.5, "K": 185, "W": 12, "L": 9, "ERA": 3.65, "WHIP": 1.15, "QS": 18},
    "Roki Sasaki": {"IP": 95, "K": 105, "W": 6, "L": 5, "ERA": 3.85, "WHIP": 1.25, "QS": 8},  # Conservative - 36 IP in 2025, injury concerns
    "Bryce Miller": {"IP": 162.5, "K": 155, "W": 10, "L": 9, "ERA": 3.88, "WHIP": 1.15, "QS": 15},
    "Bailey Ober": {"IP": 158.5, "K": 152, "W": 10, "L": 9, "ERA": 3.95, "WHIP": 1.18, "QS": 15},
    "Brady Singer": {"IP": 165.5, "K": 158, "W": 10, "L": 9, "ERA": 3.92, "WHIP": 1.20, "QS": 15},
    "Cade Horton": {"IP": 105.5, "K": 115, "W": 6, "L": 6, "ERA": 4.05, "WHIP": 1.28, "QS": 9},
    "AJ Smith-Shawver": {"IP": 115.2, "K": 118, "W": 7, "L": 7, "ERA": 4.12, "WHIP": 1.25, "QS": 10},
    "Carlos Rodon": {"IP": 145.5, "K": 162, "W": 9, "L": 8, "ERA": 4.02, "WHIP": 1.22, "QS": 13},
}

# Top 100 Prospect Rankings (loaded from prospects.json)
PROSPECT_RANKINGS = load_prospect_rankings()

# Relief Pitcher Projections with Saves + Holds (FantasyPros Consensus 2026)
RELIEVER_PROJECTIONS = {
    # Elite Closers
    "Mason Miller": {"IP": 66.8, "K": 104, "SV": 33, "HD": 2, "ERA": 2.60, "WHIP": 0.98, "L": 2},
    "Edwin Diaz": {"IP": 67.3, "K": 93, "SV": 37, "HD": 3, "ERA": 3.05, "WHIP": 1.06, "L": 3},
    "Cade Smith": {"IP": 71.2, "K": 92, "SV": 31, "HD": 3, "ERA": 2.97, "WHIP": 1.07, "L": 3},
    "Jhoan Duran": {"IP": 68.6, "K": 80, "SV": 32, "HD": 3, "ERA": 2.88, "WHIP": 1.12, "L": 3},
    "Josh Hader": {"IP": 65.3, "K": 91, "SV": 34, "HD": 2, "ERA": 3.24, "WHIP": 1.07, "L": 3},
    "Andres Munoz": {"IP": 63.9, "K": 81, "SV": 32, "HD": 3, "ERA": 2.89, "WHIP": 1.12, "L": 3},
    "Aroldis Chapman": {"IP": 61.1, "K": 85, "SV": 32, "HD": 2, "ERA": 3.04, "WHIP": 1.15, "L": 3},
    "Devin Williams": {"IP": 65.6, "K": 87, "SV": 31, "HD": 4, "ERA": 3.24, "WHIP": 1.15, "L": 3},
    "David Bednar": {"IP": 65.0, "K": 79, "SV": 32, "HD": 3, "ERA": 3.31, "WHIP": 1.12, "L": 3},
    # High-Leverage Setup/Closer Mix
    "Griffin Jax": {"IP": 68.6, "K": 86, "SV": 15, "HD": 12, "ERA": 3.09, "WHIP": 1.10, "L": 3},
    "Raisel Iglesias": {"IP": 66.9, "K": 71, "SV": 27, "HD": 4, "ERA": 3.62, "WHIP": 1.13, "L": 3},
    "Abner Uribe": {"IP": 71.8, "K": 85, "SV": 18, "HD": 11, "ERA": 3.07, "WHIP": 1.20, "L": 3},
    "Ryan Walker": {"IP": 64.2, "K": 68, "SV": 27, "HD": 5, "ERA": 3.41, "WHIP": 1.19, "L": 3},
    "Jeff Hoffman": {"IP": 64.2, "K": 76, "SV": 26, "HD": 4, "ERA": 3.67, "WHIP": 1.17, "L": 4},
    "Ryan Helsley": {"IP": 64.7, "K": 74, "SV": 27, "HD": 4, "ERA": 3.55, "WHIP": 1.22, "L": 3},
    "Daniel Palencia": {"IP": 66.7, "K": 76, "SV": 28, "HD": 5, "ERA": 3.70, "WHIP": 1.25, "L": 3},
    "Pete Fairbanks": {"IP": 62.7, "K": 64, "SV": 26, "HD": 3, "ERA": 3.54, "WHIP": 1.21, "L": 3},
    "Trevor Megill": {"IP": 65.0, "K": 80, "SV": 17, "HD": 8, "ERA": 3.45, "WHIP": 1.18, "L": 3},
    "Emilio Pagan": {"IP": 66.9, "K": 73, "SV": 26, "HD": 4, "ERA": 3.96, "WHIP": 1.18, "L": 3},
    "Carlos Estevez": {"IP": 66.3, "K": 59, "SV": 32, "HD": 2, "ERA": 4.18, "WHIP": 1.27, "L": 4},
    "Kenley Jansen": {"IP": 59.8, "K": 60, "SV": 24, "HD": 4, "ERA": 3.92, "WHIP": 1.19, "L": 3},
    # Setup Men (High Holds)
    "Grant Taylor": {"IP": 77.0, "K": 91, "SV": 5, "HD": 12, "ERA": 3.36, "WHIP": 1.20, "L": 4},
    "Bryan Abreu": {"IP": 68.9, "K": 91, "SV": 4, "HD": 19, "ERA": 3.18, "WHIP": 1.18, "L": 3},
    "Jeremiah Estrada": {"IP": 70.6, "K": 96, "SV": 2, "HD": 20, "ERA": 3.39, "WHIP": 1.16, "L": 3},
    "Garrett Whitlock": {"IP": 69.2, "K": 77, "SV": 3, "HD": 19, "ERA": 3.36, "WHIP": 1.15, "L": 3},
    "Alex Vesia": {"IP": 63.6, "K": 80, "SV": 1, "HD": 20, "ERA": 3.54, "WHIP": 1.15, "L": 3},
    "Tanner Scott": {"IP": 64.7, "K": 73, "SV": 4, "HD": 16, "ERA": 3.52, "WHIP": 1.22, "L": 3},
    "Adrian Morejon": {"IP": 69.0, "K": 69, "SV": 3, "HD": 16, "ERA": 3.35, "WHIP": 1.18, "L": 4},
    "Robert Suarez": {"IP": 67.5, "K": 70, "SV": 9, "HD": 14, "ERA": 3.57, "WHIP": 1.17, "L": 3},
    "Matt Brash": {"IP": 62.1, "K": 74, "SV": 3, "HD": 17, "ERA": 3.19, "WHIP": 1.21, "L": 3},
    "A.J. Minter": {"IP": 55.9, "K": 63, "SV": 2, "HD": 18, "ERA": 3.41, "WHIP": 1.17, "L": 3},
    "Tyler Rogers": {"IP": 72.4, "K": 50, "SV": 2, "HD": 21, "ERA": 3.67, "WHIP": 1.22, "L": 3},
    "Bryan King": {"IP": 66.2, "K": 65, "SV": 0, "HD": 19, "ERA": 3.62, "WHIP": 1.20, "L": 3},
    "Jared Koenig": {"IP": 66.1, "K": 66, "SV": 1, "HD": 18, "ERA": 3.57, "WHIP": 1.23, "L": 3},
    "Dylan Lee": {"IP": 65.9, "K": 74, "SV": 1, "HD": 17, "ERA": 3.60, "WHIP": 1.16, "L": 3},
    "Jose A. Ferrer": {"IP": 69.3, "K": 65, "SV": 3, "HD": 17, "ERA": 3.22, "WHIP": 1.17, "L": 3},
    # Middle Relievers
    "Garrett Cleavinger": {"IP": 65.2, "K": 80, "SV": 7, "HD": 15, "ERA": 3.45, "WHIP": 1.18, "L": 3},
    "Will Vest": {"IP": 68.1, "K": 69, "SV": 7, "HD": 15, "ERA": 3.38, "WHIP": 1.20, "L": 3},
    "Matt Strahm": {"IP": 66.1, "K": 72, "SV": 1, "HD": 15, "ERA": 3.51, "WHIP": 1.13, "L": 3},
    "Phil Maton": {"IP": 65.4, "K": 72, "SV": 5, "HD": 16, "ERA": 3.67, "WHIP": 1.21, "L": 3},
    "Andrew Kittredge": {"IP": 67.2, "K": 67, "SV": 5, "HD": 16, "ERA": 3.69, "WHIP": 1.19, "L": 3},
    "JoJo Romero": {"IP": 64.2, "K": 60, "SV": 12, "HD": 15, "ERA": 3.60, "WHIP": 1.29, "L": 3},
    "Riley O'Brien": {"IP": 63.7, "K": 65, "SV": 16, "HD": 11, "ERA": 3.66, "WHIP": 1.31, "L": 3},
    "Tyler Holton": {"IP": 72.1, "K": 60, "SV": 1, "HD": 15, "ERA": 3.62, "WHIP": 1.16, "L": 3},
    "Luke Weaver": {"IP": 68.5, "K": 73, "SV": 5, "HD": 16, "ERA": 3.93, "WHIP": 1.20, "L": 3},
    "Gabe Speier": {"IP": 58.6, "K": 69, "SV": 0, "HD": 15, "ERA": 3.31, "WHIP": 1.11, "L": 3},
    "Orion Kerkering": {"IP": 63.8, "K": 69, "SV": 1, "HD": 15, "ERA": 3.45, "WHIP": 1.21, "L": 3},
    "Louis Varland": {"IP": 67.8, "K": 67, "SV": 2, "HD": 14, "ERA": 3.66, "WHIP": 1.21, "L": 3},
    "Seranthony Dominguez": {"IP": 63.0, "K": 71, "SV": 14, "HD": 7, "ERA": 3.92, "WHIP": 1.30, "L": 4},
    "Fernando Cruz": {"IP": 60.9, "K": 82, "SV": 1, "HD": 17, "ERA": 3.70, "WHIP": 1.23, "L": 3},
    "Jose Alvarado": {"IP": 60.1, "K": 68, "SV": 3, "HD": 13, "ERA": 3.52, "WHIP": 1.24, "L": 3},
    "Camilo Doval": {"IP": 64.8, "K": 74, "SV": 4, "HD": 15, "ERA": 3.64, "WHIP": 1.29, "L": 3},
    "Robert Stephenson": {"IP": 57.8, "K": 65, "SV": 11, "HD": 10, "ERA": 4.00, "WHIP": 1.20, "L": 3},
    "Clayton Beeter": {"IP": 63.4, "K": 74, "SV": 13, "HD": 11, "ERA": 3.84, "WHIP": 1.34, "L": 3},
    "Robert Garcia": {"IP": 64.1, "K": 69, "SV": 19, "HD": 8, "ERA": 3.64, "WHIP": 1.23, "L": 3},
    "Dennis Santana": {"IP": 69.2, "K": 64, "SV": 24, "HD": 5, "ERA": 3.95, "WHIP": 1.26, "L": 3},
    "Edwin Uceta": {"IP": 72.0, "K": 86, "SV": 13, "HD": 15, "ERA": 3.78, "WHIP": 1.20, "L": 4},
    "Victor Vodnik": {"IP": 64.5, "K": 61, "SV": 18, "HD": 7, "ERA": 4.28, "WHIP": 1.46, "L": 4},
    "Tony Santillan": {"IP": 69.9, "K": 73, "SV": 4, "HD": 17, "ERA": 4.20, "WHIP": 1.33, "L": 3},
    "Blake Treinen": {"IP": 58.9, "K": 66, "SV": 1, "HD": 15, "ERA": 3.82, "WHIP": 1.26, "L": 3},
    "Caleb Thielbar": {"IP": 64.6, "K": 66, "SV": 1, "HD": 17, "ERA": 3.72, "WHIP": 1.20, "L": 3},
    "Shawn Armstrong": {"IP": 69.4, "K": 69, "SV": 3, "HD": 16, "ERA": 3.78, "WHIP": 1.20, "L": 3},
    "Eduard Bazardo": {"IP": 67.9, "K": 70, "SV": 1, "HD": 13, "ERA": 3.67, "WHIP": 1.19, "L": 3},
    "Hunter Harvey": {"IP": 51.1, "K": 55, "SV": 4, "HD": 12, "ERA": 3.41, "WHIP": 1.14, "L": 2},
    "Hunter Gaddis": {"IP": 68.0, "K": 65, "SV": 3, "HD": 19, "ERA": 3.84, "WHIP": 1.21, "L": 3},
    "Cole Sands": {"IP": 68.6, "K": 67, "SV": 3, "HD": 13, "ERA": 3.97, "WHIP": 1.23, "L": 4},
    "Chris Martin": {"IP": 53.7, "K": 52, "SV": 4, "HD": 11, "ERA": 3.42, "WHIP": 1.15, "L": 3},
    "Yimi Garcia": {"IP": 58.2, "K": 64, "SV": 5, "HD": 13, "ERA": 3.78, "WHIP": 1.19, "L": 3},
    "Kyle Finnegan": {"IP": 64.1, "K": 60, "SV": 4, "HD": 14, "ERA": 3.82, "WHIP": 1.27, "L": 3},
    "Lucas Erceg": {"IP": 63.6, "K": 60, "SV": 3, "HD": 16, "ERA": 3.71, "WHIP": 1.28, "L": 4},
    "Steven Okert": {"IP": 64.3, "K": 73, "SV": 0, "HD": 13, "ERA": 3.88, "WHIP": 1.19, "L": 3},
    "Bryan Baker": {"IP": 65.2, "K": 73, "SV": 2, "HD": 14, "ERA": 3.94, "WHIP": 1.22, "L": 3},
    "Kirby Yates": {"IP": 56.5, "K": 67, "SV": 9, "HD": 10, "ERA": 3.99, "WHIP": 1.28, "L": 3},
    "Jordan Leasure": {"IP": 65.6, "K": 73, "SV": 9, "HD": 11, "ERA": 4.19, "WHIP": 1.30, "L": 4},
    "Brusdar Graterol": {"IP": 50.6, "K": 42, "SV": 0, "HD": 9, "ERA": 3.42, "WHIP": 1.20, "L": 2},
    "Taylor Rogers": {"IP": 59.7, "K": 62, "SV": 11, "HD": 7, "ERA": 4.13, "WHIP": 1.34, "L": 3},
    "Kevin Ginkel": {"IP": 62.5, "K": 64, "SV": 5, "HD": 13, "ERA": 3.90, "WHIP": 1.30, "L": 3},
    # Added - high upside but shoulder injury concern
    "Ben Joyce": {"IP": 35.9, "K": 41, "SV": 4, "HD": 5, "ERA": 3.68, "WHIP": 1.27, "L": 2},
}

# Player ages (2026 season) - used when API doesn't provide ages
# Ages calculated based on birth dates - using age they'll be for most of the 2026 season
PLAYER_AGES = {
    "A.J. Block": 27,
    "A.J. Causey": 22,
    "A.J. Ewing": 20,
    "A.J. Puckett": 30,
    "A.J. Vukovich": 23,
    "A.J. Wilson": 24,
    "AJ Blubaugh": 24,
    "AJ Salgado": 23,
    "AJ Smith-Shawver": 23,
    "Aaron Antonini": 26,
    "Aaron Bracho": 24,
    "Aaron Brooks": 35,
    "Aaron Brown": 26,
    "Aaron Civale": 30,
    "Aaron Combs": 23,
    "Aaron Davenport": 24,
    "Aaron Haase": 25,
    "Aaron Holiday": 25,
    "Aaron Judge": 33,
    "Aaron McKeithan": 25,
    "Aaron Munson": 23,
    "Aaron Nola": 32,
    "Aaron Parker": 22,
    "Aaron Pinero": 18,
    "Aaron Rozek": 29,
    "Aaron Rund": 26,
    "Aaron Sabato": 26,
    "Aaron Salazar": 17,
    "Aaron Schunk": 27,
    "Aaron Walton": 21,
    "Aaron Wilkerson": 36,
    "Aaron Zavala": 25,
    "Abdias De La Cruz": 20,
    "Abdiel Mendoza": 26,
    "Abel Bastidas": 21,
    "Abel Fuerte": 20,
    "Abel Lorenzo": 19,
    "Abel Mercedes": 23,
    "Abel Pena": 17,
    "Abel Valdes": 18,
    "Abimelec Ortiz": 23,
    "Abis Prado": 18,
    "Abner Uribe": 25,
    "Abraham Bastidas": 18,
    "Abraham Cohen": 19,
    "Abraham Elvira": 17,
    "Abraham Gaitan": 21,
    "Abraham Nunez": 19,
    "Abraham Parra": 19,
    "Abraham Sanchez": 17,
    "Abraham Toro": 28,
    "Abrahan Gutierrez": 25,
    "Abrahan Ramirez": 20,
    "Accimias Morales": 20,
    "Adam Bates": 19,
    "Adam Bloebaum": 24,
    "Adam Boucher": 23,
    "Adam Hackenberg": 25,
    "Adam Hall": 26,
    "Adam Kloffenstein": 24,
    "Adam Laskey": 27,
    "Adam Leverett": 25,
    "Adam Macko": 24,
    "Adam Maier": 23,
    "Adam Retzbach": 24,
    "Adam Seminaris": 26,
    "Adam Serwinowski": 21,
    "Adam Shoemaker": 22,
    "Adam Smith": 25,
    "Adam Tulloch": 24,
    "Adam Zebrowski": 24,
    "Adan Moreno": 20,
    "Adan Sanchez": 20,
    "Adbiel Feliz": 18,
    "Addison Barger": 26,
    "Addison Kopack": 23,
    "Adilson Peralta": 22,
    "Adisyn Coffey": 26,
    "Adley Rutschman": 27,
    "Adolfo Miranda": 18,
    "Adolfo Sanchez": 18,
    "Adolis Garcia": 32,
    "Adonis Medina": 28,
    "Adonis Villavicencio": 24,
    "Adonys Guzman": 21,
    "Adonys Perez": 21,
    "Adrian Acosta": 20,
    "Adrian Belen": 20,
    "Adrian Bello": 19,
    "Adrian Bohorquez": 20,
    "Adrian De Leon": 21,
    "Adrian Feliz": 16,
    "Adrian Garcia": 18,
    "Adrian Gil": 19,
    "Adrian Heredia": 20,
    "Adrian Herrera": 20,
    "Adrian Houser": 32,
    "Adrian Hoyte": 19,
    "Adrian Morejon": 26,
    "Adrian Pinto": 22,
    "Adrian Placencia": 22,
    "Adrian Quintana": 22,
    "Adrian Rodriguez": 21,
    "Adrian Santana": 19,
    "Adrian Sugastey": 22,
    "Adrian Tusen": 17,
    "Adrian Valdez": 17,
    "Adriander Mejia": 18,
    "Adriel Radney": 18,
    "Aeverson Arteaga": 22,
    "Agustin Acosta": 20,
    "Agustin Marcano": 19,
    "Agustin Ramirez": 24,
    "Ahbram Liendo": 21,
    "Aiberson Blanco": 17,
    "Aiberson Ventura": 19,
    "Aidan Anderson": 28,
    "Aidan Curry": 22,
    "Aidan Deakins": 21,
    "Aidan Foeller": 23,
    "Aidan Longwell": 23,
    "Aidan Maldonado": 25,
    "Aidan Miller": 21,
    "Aidan Smith": 21,
    "Aiden Butler": 21,
    "Aiden May": 22,
    "Aiden Taggart": 18,
    "Aiden Taurek": 21,
    "Aiva Arquette": 21,
    "Aiverson Barazarte": 17,
    "Alain Pena": 22,
    "Alam Bruno": 17,
    "Alan Angulo": 17,
    "Alan Busenitz": 34,
    "Alan Escobar": 16,
    "Alan Espinal": 23,
    "Alan Perdomo": 23,
    "Alan Rangel": 27,
    "Alan Reyes": 21,
    "Alan Trejo": 29,
    "Alaska Abney": 25,
    "Albert Almora Jr.": 31,
    "Albert Fabian": 23,
    "Albert Feliz": 23,
    "Albert Gutierrez": 21,
    "Albert Jimenez": 18,
    "Albert Medina": 17,
    "Albert Rivas": 22,
    "Alberth Palma": 19,
    "Alberto Barriga": 20,
    "Alberto Hernandez": 21,
    "Alberto Mendez": 20,
    "Alberto Mota": 22,
    "Alberto Pacheco": 22,
    "Alberto Rios": 23,
    "Albertson Asigen": 23,
    "Alcides Hernandez": 20,
    "Aldalay Kolokie": 20,
    "Aldo Gaxiola": 19,
    "Aldrin Batista": 22,
    "Aldrin Gonzalez": 19,
    "Aldrin Lucas": 22,
    "Alec Baker": 25,
    "Alec Barger": 27,
    "Alec Bohm": 29,
    "Alec Burleson": 27,
    "Alec Gamboa": 28,
    "Alec Makarewicz": 24,
    "Alec Marsh": 27,
    "Alejandro Blasco": 18,
    "Alejandro Castellano": 18,
    "Alejandro Chiquillo": 22,
    "Alejandro Cruz": 18,
    "Alejandro Guerrero": 17,
    "Alejandro Hidalgo": 22,
    "Alejandro Kirk": 27,
    "Alejandro Loaiza": 21,
    "Alejandro Lugo": 22,
    "Alejandro Manzano": 23,
    "Alejandro Mendez": 24,
    "Alejandro Nunez": 20,
    "Alejandro Pereira": 18,
    "Alejandro Rios": 20,
    "Alejandro Rosario": 24,
    "Alejandro Torres": 24,
    "Alek Manoah": 28,
    "Alen Pineda": 20,
    "Alessander De La Cruz": 19,
    "Alessandro Duran": 19,
    "Alessandro Ercolani": 21,
    "Alessandro Rodriguez": 16,
    "Alex Acosta": 19,
    "Alex Amalfi": 24,
    "Alex Binelas": 25,
    "Alex Birge": 22,
    "Alex Bouchard": 21,
    "Alex Bregman": 31,
    "Alex Carrillo": 28,
    "Alex Clemmey": 20,
    "Alex Cook": 24,
    "Alex Cornwell": 26,
    "Alex De Jesus": 23,
    "Alex Freeland": 24,
    "Alex Galvan": 23,
    "Alex Hoppe": 26,
    "Alex Lodise": 21,
    "Alex Makarewich": 23,
    "Alex Martinez": 21,
    "Alex Mauricio": 27,
    "Alex McCoy": 23,
    "Alex McFarlane": 24,
    "Alex Mooney": 22,
    "Alex Pham": 25,
    "Alex Ramirez": 22,
    "Alex Rao": 24,
    "Alex Rodriguez": 17,
    "Alex Santos II": 23,
    "Alex Speas": 27,
    "Alex Stone": 23,
    "Alex Vallecillo": 22,
    "Alex Verdugo": 29,
    "Alex Vesia": 29,
    "Alex Williams": 25,
    "Alexander Alberto": 23,
    "Alexander Albertus": 20,
    "Alexander Alzi": 18,
    "Alexander Benua": 21,
    "Alexander Camacaro": 17,
    "Alexander Campos": 22,
    "Alexander Cornielle": 23,
    "Alexander De Los Santos": 18,
    "Alexander Eneas": 17,
    "Alexander Frias": 17,
    "Alexander Fuentes": 20,
    "Alexander Garcia": 19,
    "Alexander Herrera": 17,
    "Alexander Mambel": 18,
    "Alexander Martinez": 20,
    "Alexander Meckley": 21,
    "Alexander Ramirez": 22,
    "Alexander Requena": 19,
    "Alexander Rincon": 18,
    "Alexander Vargas": 23,
    "Alexey Lumpuy": 21,
    "Alexi Quiroz": 18,
    "Alexis De La Cruz": 20,
    "Alexis Hernandez": 20,
    "Alexis Liebano": 22,
    "Alexis Paulino": 22,
    "Alexis Torres": 22,
    "Alfiery Matos": 17,
    "Alfonsin Rosario": 21,
    "Alfonzo Martinez": 19,
    "Alfred Ciriaco": 18,
    "Alfred Morillo": 23,
    "Alfred Vega": 24,
    "Alfredo Alcantara": 19,
    "Alfredo Benzan": 18,
    "Alfredo Duno": 20,
    "Alfredo Guanchez": 19,
    "Alfredo Rodriguez": 19,
    "Alfredo Romero": 22,
    "Alfredo Velasquez": 20,
    "Alfredo Zarraga": 24,
    "Ali Camarillo": 22,
    "Ali Sanchez": 28,
    "Ali Sánchez": 28,
    "Alika Williams": 26,
    "Alimber Santa": 22,
    "Alirio Ferrebus": 19,
    "Alison Zacarias": 19,
    "Alistair Tanner": 18,
    "Alix Hernandez": 20,
    "Allan Castro": 22,
    "Allan Cerda": 25,
    "Allan Hernandez": 24,
    "Allan Saathoff": 25,
    "Allan Winans": 29,
    "Allen Ajoti": 19,
    "Allen Facundo": 22,
    "Almen Tolentino": 18,
    "Alonso Gallegos": 18,
    "Alonzo Richardson": 22,
    "Alonzo Tredwell": 23,
    "Alton Davis II": 21,
    "Alvaro Matos": 19,
    "Alvaro Rios": 18,
    "Alvin Guzman": 23,
    "Alvin Nova": 20,
    "Amauri Ramirez": 18,
    "Ambioris Tavarez": 21,
    "Amed Rosario": 30,
    "Amilcar Chirinos": 23,
    "Amos Willingham": 26,
    "Anderdson Rojas": 21,
    "Anders Tolhurst": 25,
    "Anderson Araujo": 17,
    "Anderson Areinamo": 18,
    "Anderson Bido": 26,
    "Anderson Brito": 20,
    "Anderson Cardenas": 19,
    "Anderson De Los Santos": 21,
    "Anderson Fermin": 18,
    "Anderson Garcia": 18,
    "Anderson Guevara": 20,
    "Anderson Machado": 21,
    "Anderson Navas": 18,
    "Anderson Paulino": 26,
    "Anderson Pilar": 27,
    "Anderson Ramos": 19,
    "Anderson Suriel": 22,
    "Anderson Tovar": 18,
    "Andinson Ferrer": 21,
    "Andre Granillo": 25,
    "Andre Lipcius": 27,
    "Andre Pallante": 27,
    "Andre Sanchez": 22,
    "Andreimi Antunez": 18,
    "Andres Arias": 18,
    "Andres Cova": 20,
    "Andres Galan": 21,
    "Andres Garza": 18,
    "Andres Gimenez": 27,
    "Andres Munoz": 27,
    "Andres Nolaya": 20,
    "Andres Silvera": 20,
    "Andres Torres": 18,
    "Andres Valor": 19,
    "Andres Villafane": 19,
    "Andrew Abbott": 26,
    "Andrew Alvarez": 26,
    "Andrew Baker": 25,
    "Andrew Bash": 28,
    "Andrew Bechtold": 29,
    "Andrew Benintendi": 31,
    "Andrew Bolivar": 19,
    "Andrew Carson": 25,
    "Andrew Cossetti": 25,
    "Andrew Dalquist": 24,
    "Andrew Dutkanych IV": 21,
    "Andrew Fischer": 21,
    "Andrew Heaney": 34,
    "Andrew Hoffmann": 25,
    "Andrew Huffman": 25,
    "Andrew Jenkins": 24,
    "Andrew Kittredge": 35,
    "Andrew Landry": 23,
    "Andrew Lindsey": 25,
    "Andrew Magno": 27,
    "Andrew Marrero": 25,
    "Andrew Miller": 27,
    "Andrew Misiaszek": 27,
    "Andrew Moore": 25,
    "Andrew Morones": 24,
    "Andrew Morris": 23,
    "Andrew Navigato": 27,
    "Andrew Painter": 22,
    "Andrew Patrick": 22,
    "Andrew Pinckney": 24,
    "Andrew Pintar": 24,
    "Andrew Quezada": 28,
    "Andrew Saalfrank": 27,
    "Andrew Salas": 17,
    "Andrew Schultz": 27,
    "Andrew Sears": 22,
    "Andrew Sojka": 24,
    "Andrew Taylor": 23,
    "Andrew Tess": 18,
    "Andrew Vaughn": 27,
    "Andrew Walling": 25,
    "Andrew Walters": 24,
    "Andrews Sosa": 20,
    "Andrick Nava": 23,
    "Andru Arthur": 19,
    "Andruw Musett": 19,
    "Andruw Salcedo": 22,
    "Andruw Zambrano": 19,
    "Andry Araujo": 17,
    "Andry Batista": 18,
    "Andry Lara": 22,
    "Andy Acevedo": 19,
    "Andy Basora": 20,
    "Andy Encarnacion": 20,
    "Andy Fabian": 22,
    "Andy Garriola": 25,
    "Andy Lugo": 21,
    "Andy Luis": 22,
    "Andy Mata": 17,
    "Andy Pages": 25,
    "Andy Perez": 21,
    "Andy Polanco": 20,
    "Andy Rodriguez": 22,
    "Andy Weber": 27,
    "Andy Yerzy": 26,
    "Aneudis Mejia": 21,
    "Aneudis Mordan": 21,
    "Aneuris Rodriguez": 21,
    "Aneury Lora": 21,
    "Anfernny Reyes": 21,
    "Angel Abreu": 16,
    "Angel Acosta": 22,
    "Angel Anazco": 23,
    "Angel Aquino": 20,
    "Angel Arredondo": 18,
    "Angel Barboza": 18,
    "Angel Bastardo": 22,
    "Angel Bello": 18,
    "Angel Bolivar": 19,
    "Angel Brachi": 18,
    "Angel Camacho": 21,
    "Angel Cepeda": 19,
    "Angel Cuenca": 23,
    "Angel De Los Santos": 17,
    "Angel Del Rosario": 22,
    "Angel Diaz": 21,
    "Angel Felipe": 27,
    "Angel Feliz": 18,
    "Angel Garcia": 18,
    "Angel Genao": 21,
    "Angel Gonzalez": 18,
    "Angel Guzman": 18,
    "Angel Hernandez": 25,
    "Angel Jimenez": 21,
    "Angel Liranzo": 18,
    "Angel Macuare": 25,
    "Angel Martinez": 24,
    "Angel Mata": 20,
    "Angel Mateo": 20,
    "Angel Mejia": 16,
    "Angel Nieblas": 19,
    "Angel Ortiz": 22,
    "Angel Perdomo": 31,
    "Angel Perez": 19,
    "Angel Ramirez": 20,
    "Angel Requena": 18,
    "Angel Rodriguez": 18,
    "Angel Roman": 21,
    "Angel Roso": 17,
    "Angel Salio": 17,
    "Angel Suarez": 16,
    "Angel Tejada": 21,
    "Angel Ventura": 19,
    "Angelmis De La Cruz": 19,
    "Angelo Hernandez": 19,
    "Angelo Mora": 20,
    "Angelo Smith": 21,
    "Anhuar Garcia": 21,
    "Anibal Salas": 19,
    "Anielson Buten": 19,
    "Anthony Abreu": 17,
    "Anthony Arguelles": 24,
    "Anthony Baptist": 19,
    "Anthony Crespo": 21,
    "Anthony Cruz": 22,
    "Anthony DePino": 22,
    "Anthony Donofrio": 25,
    "Anthony Flores": 20,
    "Anthony Garcia": 23,
    "Anthony Gose": 34,
    "Anthony Gutierrez": 20,
    "Anthony Hall": 24,
    "Anthony Huezo": 19,
    "Anthony Longo": 18,
    "Anthony Maldonado": 27,
    "Anthony Marquez": 18,
    "Anthony Martinez": 21,
    "Anthony Millan": 17,
    "Anthony Narvaez": 21,
    "Anthony Nunez": 23,
    "Anthony Prato": 27,
    "Anthony Santa Cruz de Oviedo": 18,
    "Anthony Santander": 31,
    "Anthony Scull": 21,
    "Anthony Seigler": 26,
    "Anthony Servideo": 26,
    "Anthony Sherwin": 23,
    "Anthony Silva": 21,
    "Anthony Simonelli": 26,
    "Anthony Solometo": 23,
    "Anthony Stephan": 22,
    "Anthony Susac": 22,
    "Anthony Tandron": 19,
    "Anthony Veneziano": 27,
    "Anthony Vilar": 26,
    "Anthony Volpe": 24,
    "Anthuan Valencia": 20,
    "Anthwan Brea": 18,
    "Antoine Kelly": 25,
    "Antoni Cuello": 22,
    "Antoni Urena": 18,
    "Antonio Alcala": 19,
    "Antonio Anderson": 20,
    "Antonio Florido": 20,
    "Antonio Gomez": 23,
    "Antonio Jimenez": 21,
    "Antonio Knowles": 25,
    "Antonio Menendez": 26,
    "Antonio Pimentel": 19,
    "Antonio Santos": 28,
    "Antonis Macias": 20,
    "Antwone Kelly": 21,
    "Anyelo Encarnacion": 21,
    "Anyelo Marquez": 19,
    "Anyelo Ovando": 24,
    "Anyer Laureano": 21,
    "Archer Brookman": 26,
    "Arfeni Batista": 20,
    "Argenis Aparicio": 19,
    "Argenis Cayama": 18,
    "Argenis Valdez": 18,
    "Aric McAtee": 25,
    "Ariel Almonte": 21,
    "Ariel Armas": 22,
    "Ariel Castro": 19,
    "Ariel Lebron": 20,
    "Arij Fransen": 24,
    "Arjun Nimmala": 20,
    "Arlenn Manzanillo": 17,
    "Armando Cruz": 21,
    "Armando Lao": 18,
    "Armstrong Muhoozi": 17,
    "Arnaldo Lantigua": 19,
    "Arnold Prado": 20,
    "Arol Vera": 22,
    "Aroldis Chapman": 37,
    "Aron Estrada": 20,
    "Aroon Escobar": 21,
    "Arturo Disla": 24,
    "Arturo Flores": 19,
    "Arxy Hernandez": 21,
    "Asbel Gonzalez": 19,
    "Ashly Andujar": 17,
    "Ashton Izzi": 21,
    "Athanael Duarte": 20,
    "Augie Mojica": 20,
    "Augusto Calderon": 24,
    "Augusto Mendieta": 20,
    "Austin Aldeano": 21,
    "Austin Amaral": 23,
    "Austin Becker": 25,
    "Austin Bergner": 28,
    "Austin Callahan": 24,
    "Austin Cates": 22,
    "Austin Charles": 21,
    "Austin Deming": 25,
    "Austin Ehrlicher": 22,
    "Austin Emener": 23,
    "Austin Gauthier": 26,
    "Austin Gomber": 32,
    "Austin Gordon": 22,
    "Austin Green": 23,
    "Austin Hays": 30,
    "Austin Hedges": 32,
    "Austin Hendrick": 24,
    "Austin Kitchen": 28,
    "Austin Krob": 25,
    "Austin Love": 26,
    "Austin Machado": 24,
    "Austin Marozas": 26,
    "Austin Murr": 26,
    "Austin Nola": 35,
    "Austin Overn": 22,
    "Austin Peterson": 25,
    "Austin Pope": 26,
    "Austin Riley": 28,
    "Austin Roberts": 26,
    "Austin Schulfer": 29,
    "Austin Shenton": 27,
    "Austin Smith": 22,
    "Austin St. Laurent": 22,
    "Austin Strickland": 23,
    "Austin Troesser": 23,
    "Austin Vernon": 26,
    "Austin Wells": 26,
    "Avery Owusu-Asiedu": 22,
    "Avery Short": 24,
    "Avery Weems": 28,
    "Avinson Pinto": 18,
    "Axel Sanchez": 22,
    "Axiel Plaz": 19,
    "Ayden Johnson": 17,
    "Ayendy Bravo": 18,
    "Ayendy Pena": 21,
    "B.Y. Choi": 23,
    "BJ Murray Jr.": 25,
    "Bailey Dees": 26,
    "Bailey Falter": 28,
    "Bailey Horn": 27,
    "Bailey Ober": 30,
    "Bairon Ledesma": 20,
    "Baldemix Cabrera": 22,
    "Balian Caraballo": 19,
    "Baron Stuart": 25,
    "Barrett Kent": 20,
    "Bayden Root": 26,
    "Beau Ankeney": 22,
    "Beau Burrows": 28,
    "Beck Way": 25,
    "Belfi Rivera": 18,
    "Ben Anderson": 27,
    "Ben Bowden": 30,
    "Ben Brown": 26,
    "Ben Brutti": 22,
    "Ben Casparius": 26,
    "Ben Cowles": 25,
    "Ben Gobbel": 25,
    "Ben Hansen": 23,
    "Ben Harris": 25,
    "Ben Hartl": 22,
    "Ben Heller": 32,
    "Ben Hernandez": 23,
    "Ben Hess": 23,
    "Ben Joyce": 25,
    "Ben Kudrna": 22,
    "Ben Leeper": 28,
    "Ben Lively": 33,
    "Ben Malgeri": 25,
    "Ben McCabe": 25,
    "Ben McLaughlin": 23,
    "Ben Newton": 23,
    "Ben Peoples": 24,
    "Ben Peterson": 23,
    "Ben Ramirez": 26,
    "Ben Rice": 26,
    "Ben Ross": 24,
    "Ben Sears": 25,
    "Ben Shields": 26,
    "Ben Simon": 23,
    "Ben Thompson": 23,
    "Ben Vespi": 24,
    "Benjamin Arias": 23,
    "Bennett Flynn": 24,
    "Bennett Hostetler": 27,
    "Bennett Lee": 23,
    "Bennett Thompson": 22,
    "Benny Montgomery": 22,
    "Bernard Jose": 22,
    "Bernard Mack": 19,
    "Bernard Moon": 20,
    "Beycker Barroso": 22,
    "Biembenido  Brito": 22,
    "Bill Knight": 25,
    "Billy Amick": 22,
    "Billy Cook": 26,
    "Billy Corcoran": 25,
    "Bishop Letson": 20,
    "Bjay Cooke": 22,
    "Bjorn Johnson": 20,
    "Blade Tidwell": 24,
    "Bladimir Figueredo": 17,
    "Bladimir Pichardo": 19,
    "Bladimir Restituyo": 23,
    "Blaine Crim": 28,
    "Blair Calvo": 29,
    "Blake Adams": 24,
    "Blake Aita": 22,
    "Blake Beers": 26,
    "Blake Burke": 22,
    "Blake Burkhalter": 24,
    "Blake Dunn": 26,
    "Blake Hammond": 21,
    "Blake Holub": 26,
    "Blake Hunt": 26,
    "Blake Mitchell": 20,
    "Blake Money": 23,
    "Blake Rambusch": 25,
    "Blake Robertson": 24,
    "Blake Snell": 33,
    "Blake Townsend": 24,
    "Blake Walston": 24,
    "Blake Wehunt": 24,
    "Blake Weiman": 29,
    "Blake Wolters": 20,
    "Blake Wright": 23,
    "Blane Abeyta": 26,
    "Blas Castano": 26,
    "Blayberg Diaz": 22,
    "Blaze Jordan": 23,
    "Blaze O'Saben": 24,
    "Blaze Pontes": 25,
    "Bo Bichette": 27,
    "Bo Bonds": 24,
    "Bo Davidson": 22,
    "Bo Naylor": 25,
    "Bo Walker": 19,
    "Bob Seymour": 26,
    "Bobby Blandford": 22,
    "Bobby Boser": 22,
    "Bobby Milacki": 28,
    "Bobby Witt Jr.": 25,
    "Bodi Rascon": 24,
    "Bohan Adderley": 18,
    "Boris Sarduy": 18,
    "Boston Baro": 20,
    "Boston Bateman": 19,
    "Bowden Francis": 29,
    "Bracewell Taveras": 19,
    "Brad Deppermann": 29,
    "Brad Keller": 30,
    "Brad Lord": 25,
    "Brad Pacheco": 20,
    "Braden Barry": 23,
    "Braden Davis": 22,
    "Braden Montgomery": 22,
    "Braden Nett": 23,
    "Braden Quinn": 22,
    "Braden Shewmake": 27,
    "Bradgley Rodriguez": 21,
    "Bradley Brehmer": 24,
    "Bradley Frye": 22,
    "Bradley Hanner": 26,
    "Brady Afthim": 22,
    "Brady Allen": 25,
    "Brady Basso": 27,
    "Brady Cerkownyk": 22,
    "Brady Choban": 24,
    "Brady Day": 23,
    "Brady Ebel": 17,
    "Brady Feigl": 34,
    "Brady Hill": 24,
    "Brady House": 22,
    "Brady Kirtner": 23,
    "Brady Lindsly": 27,
    "Brady Marget": 22,
    "Brady Singer": 29,
    "Brady Smith": 20,
    "Brady Tygart": 22,
    "Braeden Fausnaught": 25,
    "Braedon Karpathios": 22,
    "Braian Salazar": 20,
    "Braiden Ward": 26,
    "Brailer Guerrero": 19,
    "Brailyn Antunez": 17,
    "Brailyn Paulino": 19,
    "Brainerh Palacios": 17,
    "Bralyn Brazoban": 18,
    "Brandan Bidois": 24,
    "Branden Boissiere": 25,
    "Brando Mayea": 19,
    "Brandon Barriera": 21,
    "Brandon Beckel": 23,
    "Brandon Birdsell": 25,
    "Brandon Butterworth": 22,
    "Brandon Clarke": 22,
    "Brandon Compton": 21,
    "Brandon Decker": 22,
    "Brandon Downer": 22,
    "Brandon Dufault": 26,
    "Brandon Eike": 23,
    "Brandon Forrester": 21,
    "Brandon Herbold": 20,
    "Brandon Johnson": 26,
    "Brandon Komar": 26,
    "Brandon Leibrandt": 32,
    "Brandon Lowe": 31,
    "Brandon Marsh": 28,
    "Brandon McPherson": 25,
    "Brandon Neeck": 25,
    "Brandon Nimmo": 32,
    "Brandon Pfaadt": 27,
    "Brandon Pimentel": 25,
    "Brandon Schaeffer": 24,
    "Brandon Sproat": 25,
    "Brandon Valenzuela": 24,
    "Brandon Vasquez": 18,
    "Brandon Waddell": 31,
    "Brandon White": 25,
    "Brandon Winokur": 20,
    "Brandon Woodruff": 32,
    "Brandt Thompson": 22,
    "Brandyn Garcia": 25,
    "Branny De Oleo": 20,
    "Braulio Salas": 20,
    "Braxton Ashcraft": 26,
    "Braxton Bragg": 24,
    "Braxton Fulford": 26,
    "Braxton Garrett": 28,
    "Braxton Hyde": 24,
    "Braxton Roxby": 26,
    "Brayan Amoroso": 17,
    "Brayan Bello": 26,
    "Brayan Buelvas": 23,
    "Brayan Castillo": 24,
    "Brayan Cortesia": 17,
    "Brayan Cota": 18,
    "Brayan Joseph": 19,
    "Brayan Mendoza": 21,
    "Brayan Palencia": 22,
    "Brayan Restituyo": 23,
    "Brayan Romero": 23,
    "Brayan Vergara": 19,
    "Brayden Jobert": 24,
    "Brayden Risedorph": 21,
    "Brayden Smith": 21,
    "Brayden Taylor": 23,
    "Braydon Fisher": 25,
    "Braydon Tucker": 25,
    "Braylen Wimmer": 24,
    "Braylin Morel": 19,
    "Braylin Tavera": 20,
    "Braylon Bishop": 22,
    "Braylon Payne": 19,
    "Braylon Whitaker": 19,
    "Brayner Sanchez": 24,
    "Breiny Ramirez": 19,
    "Brendan Beck": 26,
    "Brendan Cellucci": 27,
    "Brendan Collins": 24,
    "Brendan Donovan": 29,
    "Brendan Durfee": 23,
    "Brendan Girton": 23,
    "Brendan Hardy": 25,
    "Brendan Jones": 23,
    "Brendan Summerhill": 21,
    "Brendan Tunink": 19,
    "Brendan White": 26,
    "Brenden Dixon": 24,
    "Brendon Little": 29,
    "Brennan Malone": 24,
    "Brennan Milone": 24,
    "Brennan Orf": 23,
    "Brennen Davis": 25,
    "Brennen Oxford": 25,
    "Brenner Cox": 21,
    "Brennon McNair": 22,
    "Brenny Escanio": 22,
    "Brent Francisco": 24,
    "Brent Iredale": 21,
    "Brent Rooker": 31,
    "Brenton Doyle": 27,
    "Brett Auerbach": 26,
    "Brett Banks": 23,
    "Brett Bateman": 23,
    "Brett Baty": 26,
    "Brett Callahan": 23,
    "Brett Garcia": 25,
    "Brett Gillis": 25,
    "Brett Kerry": 26,
    "Brett Sears": 25,
    "Brett Squires": 25,
    "Brett Wichrowski": 23,
    "Breyias Dean": 19,
    "Breyner Figuereo": 17,
    "Breyson Guedez": 17,
    "Brian Edgington": 26,
    "Brian Fitzpatrick": 25,
    "Brian Hendry": 24,
    "Brian Kalmer": 24,
    "Brian Metoyer": 28,
    "Brian Moran": 36,
    "Brian Sanchez": 20,
    "Brian Van Belle": 28,
    "Brice Matthews": 23,
    "Brice Turang": 26,
    "Bridger Holmes": 22,
    "Brock Jones": 24,
    "Brock Moore": 25,
    "Brock Porter": 22,
    "Brock Rodden": 25,
    "Brock Selvidge": 22,
    "Brock Tibbitts": 22,
    "Brock Vradenburg": 23,
    "Brock Wilken": 23,
    "Brody Brecht": 23,
    "Brody Donay": 21,
    "Brody Hopkins": 24,
    "Brody Jessee": 24,
    "Brody McCullough": 24,
    "Brody Moore": 24,
    "Brody Rodning": 29,
    "Brooks Auger": 23,
    "Brooks Brannon": 21,
    "Brooks Caple": 22,
    "Brooks Crawford": 28,
    "Brooks Fowler": 22,
    "Brooks Kriske": 31,
    "Brooks Lee": 24,
    "Browm Martinez": 18,
    "Bruin Agbayani": 18,
    "Bruno Lopez": 23,
    "Brusdar Graterol": 27,
    "Bryan Abreu": 28,
    "Bryan Acuna": 19,
    "Bryan Andrade": 20,
    "Bryan Arendt": 22,
    "Bryan Balzer": 20,
    "Bryan Bautista": 21,
    "Bryan Broecker": 23,
    "Bryan Caceres": 25,
    "Bryan Gonzalez": 23,
    "Bryan King": 29,
    "Bryan Lavastida": 26,
    "Bryan Magdaleno": 24,
    "Bryan Martinez": 19,
    "Bryan Mata": 26,
    "Bryan Mena": 21,
    "Bryan Perez": 20,
    "Bryan Polanco": 23,
    "Bryan Ramos": 23,
    "Bryan Reynolds": 31,
    "Bryan Rincon": 21,
    "Bryan Rivera": 20,
    "Bryan Rodriguez": 17,
    "Bryan Salgado": 18,
    "Bryan Sanchez": 22,
    "Bryan Torres": 27,
    "Bryan Woo": 25,
    "Bryant Betancourt": 21,
    "Bryant Mendez": 21,
    "Bryant Olson": 22,
    "Bryce Alewine": 20,
    "Bryce Arnold": 23,
    "Bryce Collins": 24,
    "Bryce Conley": 30,
    "Bryce Cunningham": 22,
    "Bryce Eblin": 23,
    "Bryce Elder": 26,
    "Bryce Eldridge": 21,
    "Bryce Harper": 33,
    "Bryce Hubbart": 24,
    "Bryce Jenkins": 24,
    "Bryce Madron": 23,
    "Bryce Martin-Grudzielanek": 22,
    "Bryce Mayer": 23,
    "Bryce McGowan": 25,
    "Bryce Miller": 27,
    "Bryce Montes de Oca": 28,
    "Bryce Osmond": 24,
    "Bryce Rainer": 20,
    "Bryce Warrecker": 23,
    "Bryce Willits": 25,
    "Brycen Mautz": 23,
    "Bryson Hammer": 23,
    "Bryson Horne": 26,
    "Bryson Stott": 28,
    "Bryson Van Sickle": 24,
    "Bryson Ware": 24,
    "Bubba Alleyne": 26,
    "Bubba Chandler": 23,
    "Bubba Hall": 25,
    "Burl Carraway": 26,
    "Byron Buxton": 32,
    "Byron Castillo": 19,
    "Byron Chourio": 20,
    "C.J. Culpepper": 23,
    "C.J. Kayfus": 24,
    "C.J. Pittaro": 23,
    "C.J. Stubbs": 28,
    "C.J. Widger": 26,
    "CD Pelham": 30,
    "CJ Abrams": 25,
    "CJ Alexander": 28,
    "CJ Rodriguez": 24,
    "CJ Van Eyk": 26,
    "CJ Weins": 24,
    "Cade Austin": 23,
    "Cade Bunnell": 28,
    "Cade Cavalli": 27,
    "Cade Citelli": 23,
    "Cade Denton": 23,
    "Cade Doughty": 24,
    "Cade Feeney": 22,
    "Cade Fergus": 24,
    "Cade Horton": 24,
    "Cade Hunter": 24,
    "Cade Kuehler": 22,
    "Cade Marlowe": 28,
    "Cade McGee": 22,
    "Cade Smith": 26,
    "Cade Winquest": 25,
    "Caden Bodine": 21,
    "Caden Connor": 24,
    "Caden Dana": 22,
    "Caden Favors": 23,
    "Caden Grice": 22,
    "Caden Kendle": 23,
    "Caden Monke": 25,
    "Caden Powell": 21,
    "Caden Rose": 23,
    "Caden Scarborough": 20,
    "Caden Vire": 21,
    "Caeden Trenkle": 24,
    "Cal Conley": 25,
    "Cal Raleigh": 29,
    "Cal Stark": 22,
    "Cal Stevenson": 28,
    "Cale Lansville": 22,
    "Caleb Bartolero": 25,
    "Caleb Berry": 23,
    "Caleb Bolden": 26,
    "Caleb Bonemer": 20,
    "Caleb Boushley": 31,
    "Caleb Cali": 24,
    "Caleb Durbin": 25,
    "Caleb Farmer": 25,
    "Caleb Freeman": 27,
    "Caleb Hobson": 23,
    "Caleb Ketchup": 23,
    "Caleb Kilian": 28,
    "Caleb Lomavita": 22,
    "Caleb McNeely": 25,
    "Caleb Pendleton": 23,
    "Caleb Ricketts": 25,
    "Caleb Roberts": 25,
    "Callan Moss": 21,
    "Calvin Bickerstaff": 23,
    "Calvin Harris": 23,
    "Calvin Schapira": 25,
    "Cam Brown": 27,
    "Cam Caminiti": 19,
    "Cam Cannarella": 21,
    "Cam Clayton": 22,
    "Cam Collier": 21,
    "Cam Day": 22,
    "Cam Devanney": 28,
    "Cam Eden": 27,
    "Cam Fisher": 24,
    "Cam Maldonado": 21,
    "Cam Sanders": 28,
    "Cam Schlittler": 24,
    "Cam Schuelke": 23,
    "Cam Smith": 22,
    "Camden Janik": 22,
    "Camden Minacci": 23,
    "Camden Troyer": 22,
    "Cameron Barstad": 24,
    "Cameron Cauley": 22,
    "Cameron Cotter": 26,
    "Cameron Decker": 21,
    "Cameron Foster": 26,
    "Cameron Leary": 23,
    "Cameron Nickens": 21,
    "Cameron Pferrer": 26,
    "Cameron Sisneros": 24,
    "Cameron Weston": 24,
    "Camilo Doval": 28,
    "Camilo Hernandez": 21,
    "Camron Hill": 22,
    "Candido Cuevas": 21,
    "Cannon Peebles": 21,
    "Canon Reeder": 22,
    "Canyon Brown": 21,
    "Capri Ortiz": 20,
    "Cardell Thibodeaux": 21,
    "Carl Calixte": 18,
    "Carlo Reyes": 26,
    "Carlos Arroyo": 23,
    "Carlos Avila": 21,
    "Carlos Batista": 19,
    "Carlos Bello": 17,
    "Carlos Benavides": 17,
    "Carlos Caripa": 18,
    "Carlos Caro": 20,
    "Carlos Carra": 18,
    "Carlos Castillo": 19,
    "Carlos Cauro": 20,
    "Carlos Colmenarez": 21,
    "Carlos Concepcion": 19,
    "Carlos Correa": 31,
    "Carlos Cortes": 28,
    "Carlos D. Rodriguez": 24,
    "Carlos De La Cruz": 25,
    "Carlos De Sousa": 19,
    "Carlos Done": 18,
    "Carlos Duran": 23,
    "Carlos Espinosa": 23,
    "Carlos Estevez": 33,
    "Carlos Franco": 22,
    "Carlos Garces": 18,
    "Carlos Garcia": 18,
    "Carlos Gonzalez": 21,
    "Carlos Gutierrez": 20,
    "Carlos Guzman": 27,
    "Carlos Jimenez": 22,
    "Carlos Jorge": 21,
    "Carlos Lagrange": 22,
    "Carlos Lequerica": 24,
    "Carlos Linarez": 23,
    "Carlos Marcano": 21,
    "Carlos Martinez": 17,
    "Carlos Mateo": 19,
    "Carlos Matias": 18,
    "Carlos Mendoza": 25,
    "Carlos Monteverde": 19,
    "Carlos Mota": 17,
    "Carlos Pacheco": 20,
    "Carlos Pena": 26,
    "Carlos Renzullo": 18,
    "Carlos Rey": 23,
    "Carlos Rodon": 33,
    "Carlos Rodriguez": 22,
    "Carlos Rojas": 22,
    "Carlos Romero": 25,
    "Carlos Rondon": 19,
    "Carlos Salazar": 17,
    "Carlos Salmeron": 17,
    "Carlos Sanchez": 20,
    "Carlos Santana": 39,
    "Carlos Silva": 19,
    "Carlos Tavares": 19,
    "Carlos Tavera": 26,
    "Carlos Taveras": 17,
    "Carlos Tirado": 20,
    "Carlos Torres": 17,
    "Carlos Villarroel": 18,
    "Carlos Virahonda": 19,
    "Carlson Reed": 22,
    "Carlton Perkins": 22,
    "Carmen Mlodzinski": 26,
    "Carson Benge": 23,
    "Carson Coleman": 27,
    "Carson DeMartini": 22,
    "Carson Dorsey": 22,
    "Carson Hobbs": 23,
    "Carson Jacobs": 23,
    "Carson Jones": 24,
    "Carson Kelly": 31,
    "Carson Laws": 22,
    "Carson McCusker": 27,
    "Carson Messina": 19,
    "Carson Montgomery": 21,
    "Carson Palmquist": 24,
    "Carson Pierce": 22,
    "Carson Ragsdale": 27,
    "Carson Roccaforte": 23,
    "Carson Rucker": 20,
    "Carson Rudd": 26,
    "Carson Seymour": 26,
    "Carson Skipper": 25,
    "Carson Swilling": 23,
    "Carson Taylor": 26,
    "Carson Whisenhunt": 25,
    "Carson Williams": 22,
    "Carter Aldrete": 27,
    "Carter Baumler": 23,
    "Carter Cunningham": 24,
    "Carter Dorighi": 22,
    "Carter Frederick": 22,
    "Carter Graham": 23,
    "Carter Howell": 26,
    "Carter Jensen": 22,
    "Carter Johnson": 19,
    "Carter Loewen": 26,
    "Carter Mathison": 22,
    "Carter Rustad": 24,
    "Carter Spivey": 25,
    "Carter Trice": 22,
    "Carter Young": 24,
    "Case Matter": 23,
    "Casey Anderson": 24,
    "Casey Cook": 22,
    "Casey Hintz": 21,
    "Casey Kelly": 35,
    "Casey Mize": 28,
    "Casey Opitz": 26,
    "Casey Saucke": 21,
    "Casey Steward": 23,
    "Casey Yamauchi": 24,
    "Caswell Smith": 24,
    "Cayden Wallace": 23,
    "Cayman Goode": 19,
    "Cayne Ueckert": 29,
    "Ceddanne Rafaela": 25,
    "Cedric De Grandpre": 23,
    "Cedric Mullins": 31,
    "Cesar Acosta": 16,
    "Cesar Aquino": 20,
    "Cesar De Jesus": 21,
    "Cesar Espinal": 19,
    "Cesar Franco": 23,
    "Cesar Garcia": 17,
    "Cesar Gomez": 26,
    "Cesar Gonzalez": 20,
    "Cesar Hernandez": 22,
    "Cesar Lares": 20,
    "Cesar Lugo": 18,
    "Cesar Mujica": 18,
    "Cesar Paredes": 17,
    "Cesar Perdomo": 23,
    "Cesar Prieto": 26,
    "Cesar Quintas": 22,
    "Cesar Rojas": 23,
    "Chad Dallas": 24,
    "Chad Patrick": 27,
    "Chad Stevens": 26,
    "Chance Huff": 25,
    "Chance Nolan": 25,
    "Chandler Champlain": 25,
    "Chandler Marsh": 22,
    "Chandler Murphy": 24,
    "Chandler Pollard": 21,
    "Chandler Seagle": 29,
    "Chandler Simpson": 25,
    "Chandler Welch": 22,
    "Channing Austin": 23,
    "Charlee Soto": 19,
    "Charles Davalan": 21,
    "Charles Harrison": 23,
    "Charles King": 27,
    "Charles Mack": 25,
    "Charles McAdoo": 23,
    "Charlie Barnes": 29,
    "Charlie Beilenson": 25,
    "Charlie Condon": 22,
    "Charlie McDaniel": 23,
    "Charlie Pagliarini": 24,
    "Charlie Szykowny": 25,
    "Chas McCormick": 30,
    "Chase Adkison": 25,
    "Chase Allsup": 22,
    "Chase Burns": 23,
    "Chase Call": 23,
    "Chase Centala": 23,
    "Chase Chaney": 25,
    "Chase Cohen": 27,
    "Chase Costello": 25,
    "Chase Davis": 23,
    "Chase DeLauter": 24,
    "Chase Dollander": 24,
    "Chase Hampton": 22,
    "Chase Harlan": 18,
    "Chase Heath": 21,
    "Chase Isbell": 23,
    "Chase Jaworsky": 20,
    "Chase Lee": 26,
    "Chase Meggers": 22,
    "Chase Meidroth": 24,
    "Chase Mobley": 19,
    "Chase Petty": 22,
    "Chase Plymell": 27,
    "Chase Solesky": 27,
    "Chase Strumpf": 27,
    "Chase Valentine": 23,
    "Chase Watkins": 25,
    "Chay Yeager": 22,
    "Chayce McDermott": 26,
    "Chazz Martinez": 25,
    "Chen Zhong-Ao Zhuang": 24,
    "Chen-Wei Lin": 23,
    "Cherif Neymour": 20,
    "Chia-Shi Shen": 21,
    "Chih-Jung Liu": 25,
    "Ching-Hsien Ko": 18,
    "Chris Arroyo": 20,
    "Chris Bassitt": 36,
    "Chris Brito": 25,
    "Chris Campos": 24,
    "Chris Clark": 23,
    "Chris Clarke": 27,
    "Chris Cortez": 22,
    "Chris Kachmar": 28,
    "Chris Kean": 23,
    "Chris Lopez": 20,
    "Chris McElvain": 24,
    "Chris Meyers": 26,
    "Chris Newell": 24,
    "Chris Rodriguez": 26,
    "Chris Sale": 36,
    "Chris Villaman": 24,
    "Chris Williams": 28,
    "Chris Williams Jr.": 25,
    "Chris Wright": 26,
    "Christian Astudillo": 18,
    "Christian Becerra": 22,
    "Christian Cairo": 24,
    "Christian Cerda": 22,
    "Christian Chamberlain": 25,
    "Christian Colon": 17,
    "Christian Encarnacion-Strand": 26,
    "Christian Fagnant": 24,
    "Christian Franklin": 25,
    "Christian Gonzalez": 18,
    "Christian Gordon": 24,
    "Christian Herberholz": 24,
    "Christian Knapczyk": 23,
    "Christian Koss": 27,
    "Christian Little": 21,
    "Christian Lopez": 18,
    "Christian MacLeod": 25,
    "Christian Martin": 22,
    "Christian McGowan": 24,
    "Christian Montes De Oca": 25,
    "Christian Moore": 23,
    "Christian Mracna": 25,
    "Christian Oliveira": 19,
    "Christian Olivo": 21,
    "Christian Oppor": 20,
    "Christian Roa": 26,
    "Christian Rodriguez": 20,
    "Christian Romero": 22,
    "Christian Ruebeck": 24,
    "Christian Scott": 26,
    "Christian Suarez": 24,
    "Christian Walker": 34,
    "Christian Worley": 23,
    "Christian Yelich": 34,
    "Christian Zazueta": 20,
    "Christofer Reyes": 17,
    "Christopher Alvarado": 18,
    "Christopher Espinola": 21,
    "Christopher Familia": 25,
    "Christopher Paciolla": 21,
    "Christopher Sargent": 24,
    "Christopher Suero": 21,
    "Christopher Troye": 26,
    "Chung-Hsiang Huang": 19,
    "Clarence Martina": 20,
    "Clark Candiotti": 24,
    "Clark Elliott": 24,
    "Clarke Schmidt": 29,
    "Clay Edmondson": 22,
    "Clay Helvey": 28,
    "Clay Holmes": 32,
    "Clay Winklaar": 18,
    "Clayton Beeter": 26,
    "Clayton Campbell": 21,
    "Clayton Gray": 23,
    "Clayton Kershaw": 37,
    "Cleiber Maldonado": 20,
    "Clete Hartzog": 24,
    "Cleudis Valenzuela": 18,
    "Clevari Tejada": 20,
    "Cliuver Puello": 18,
    "Cobb Hightower": 20,
    "Coby Mayo": 24,
    "Coby Morales": 23,
    "Coco Montes": 28,
    "Cody Adcock": 23,
    "Cody Bellinger": 30,
    "Cody Bolton": 27,
    "Cody Freeman": 24,
    "Cody Laweryson": 27,
    "Cody Miller": 20,
    "Cody Milligan": 26,
    "Cody Morissette": 25,
    "Cody Roberts": 29,
    "Cody Schrier": 22,
    "Cody Tucker": 26,
    "Cohen Achen": 23,
    "Colby Halter": 23,
    "Colby Holcombe": 22,
    "Colby Jones": 21,
    "Colby Langford": 23,
    "Colby Martin": 24,
    "Colby Shade": 23,
    "Colby Shelton": 22,
    "Colby Smelley": 25,
    "Colby Thomas": 25,
    "Colby White": 26,
    "Cole Ayers": 25,
    "Cole Carrigg": 23,
    "Cole Conn": 23,
    "Cole Fontenelle": 23,
    "Cole Foster": 23,
    "Cole Gabrielson": 24,
    "Cole Gilley": 23,
    "Cole Henry": 26,
    "Cole Hertzler": 22,
    "Cole Hillier": 24,
    "Cole Mathis": 21,
    "Cole McConnell": 24,
    "Cole Messina": 22,
    "Cole Miller": 20,
    "Cole Paplham": 25,
    "Cole Percival": 26,
    "Cole Peschl": 22,
    "Cole Ragans": 28,
    "Cole Reynolds": 23,
    "Cole Roberts": 24,
    "Cole Schoenwetter": 20,
    "Cole Tolbert": 21,
    "Cole Turney": 26,
    "Cole Urman": 23,
    "Cole Waites": 27,
    "Cole Wilcox": 25,
    "Cole Young": 22,
    "Coleman Crow": 24,
    "Colin Barber": 24,
    "Colin Burgess": 24,
    "Colin Davis": 26,
    "Colin Fields": 25,
    "Colin Houck": 20,
    "Colin Peluse": 27,
    "Colin Selby": 27,
    "Colin Summerhill": 23,
    "Colin Tuft": 22,
    "Colin Yeaman": 21,
    "Collin Baumgartner": 26,
    "Collin Price": 25,
    "Colson Lawrence": 23,
    "Colson Montgomery": 23,
    "Colt Emerson": 20,
    "Colt Keith": 24,
    "Colten Brewer": 32,
    "Colton Becker": 24,
    "Colton Bender": 26,
    "Colton Cosper": 22,
    "Colton Cowser": 25,
    "Colton Johnson": 26,
    "Colton Ledbetter": 23,
    "Colton Vincent": 25,
    "Connelly Early": 23,
    "Conner Whittaker": 22,
    "Connery Peters": 25,
    "Connor Burns": 23,
    "Connor Caskenette": 23,
    "Connor Charping": 26,
    "Connor Cooke": 24,
    "Connor Dykstra": 24,
    "Connor Foley": 21,
    "Connor Gillispie": 27,
    "Connor Housley": 23,
    "Connor Hujsak": 23,
    "Connor Kaiser": 28,
    "Connor McCullough": 25,
    "Connor McGinnis": 22,
    "Connor Noland": 25,
    "Connor Norby": 25,
    "Connor O'Halloran": 22,
    "Connor Oliver": 24,
    "Connor Pavolony": 25,
    "Connor Phillips": 24,
    "Connor Prielipp": 24,
    "Connor Rasmussen": 21,
    "Connor Schultz": 26,
    "Connor Scott": 25,
    "Connor Spencer": 24,
    "Connor Staine": 24,
    "Connor Thomas": 27,
    "Connor Van Scoyoc": 25,
    "Connor Wietgrefe": 23,
    "Conor Grammes": 27,
    "Conor Larkin": 26,
    "Conor Steinbaugh": 26,
    "Conrad Cason": 18,
    "Cooper Adams": 25,
    "Cooper Bowman": 25,
    "Cooper Hjerpe": 23,
    "Cooper Hummel": 30,
    "Cooper Ingle": 23,
    "Cooper Johnson": 27,
    "Cooper Kinney": 22,
    "Cooper McMurray": 23,
    "Cooper Pratt": 21,
    "Corbin Burnes": 31,
    "Corbin Carroll": 25,
    "Core Jackson": 21,
    "Corey Avant": 23,
    "Corey Collins": 23,
    "Corey Joyce": 26,
    "Corey Rosier": 25,
    "Corey Seager": 31,
    "Cortland Lawson": 25,
    "Cory Lewis": 24,
    "Cory Ronan": 23,
    "Cory Wall": 25,
    "Craig Yoho": 25,
    "Creed Willems": 22,
    "Cris Rodriguez": 17,
    "Cristhian Tortosa": 26,
    "Cristhian Vaquero": 20,
    "Cristian Arguelles": 18,
    "Cristian Benavides": 17,
    "Cristian Bonifacio": 17,
    "Cristian Gonzalez": 23,
    "Cristian Hernandez": 21,
    "Cristian Jauregui": 19,
    "Cristian Javier": 28,
    "Cristian Mena": 22,
    "Cristian Montilla": 17,
    "Cristian Perez": 18,
    "Cristian Santana": 21,
    "Cristofer Gomez": 22,
    "Cristofer Lebron": 18,
    "Cristofer Melendez": 27,
    "Cristofer Torin": 20,
    "Cristopfer Gonzalez": 19,
    "Cristopher Acosta": 17,
    "Cristopher Larez": 19,
    "Cristopher Polanco": 17,
    "Cristopher Sanchez": 29,
    "Cruz Noriega": 27,
    "Cruzmel Arias": 21,
    "Curley Martha": 18,
    "Curtis Hebert": 21,
    "Curtis Taylor": 29,
    "Curtis Washington Jr.": 25,
    "Cutter Coffey": 21,
    "Cy Nielson": 24,
    "César Salazar": 29,
    "D'Andre Smith": 24,
    "D'Angelo Ortiz": 20,
    "D'Angelo Tejada": 19,
    "D.J. Carpenter": 25,
    "D.J. McCarty": 22,
    "DJ Gladney": 23,
    "DJ Herz": 25,
    "DJ Layton": 18,
    "DaShawn Keirsey Jr.": 28,
    "Dahian Santos": 21,
    "Daiber De Los Santos": 18,
    "Dailoui Abad": 23,
    "Daison Acosta": 26,
    "Daiverson Gutierrez": 19,
    "Dakota Harris": 23,
    "Dakota Hawkins": 25,
    "Dakota Jordan": 22,
    "Dale Stanavich": 26,
    "Dallas Macias": 21,
    "Dalton Davis": 24,
    "Dalton Fowler": 25,
    "Dalton McIntyre": 21,
    "Dalton Pence": 22,
    "Dalton Roach": 29,
    "Dalton Rogers": 24,
    "Dalton Rushing": 24,
    "Dalton Shuffield": 26,
    "Dalvin Rosario": 25,
    "Dalvinson Reyes": 18,
    "Dalvy Rosario": 24,
    "Dameivi Tineo": 21,
    "Dameury Pena": 19,
    "Damian Bravo": 21,
    "Damiano Palmegiani": 25,
    "Damon Dues": 27,
    "Damon Keith": 25,
    "Dan Altavilla": 32,
    "Dan Hammer": 27,
    "Dan Kubiuk": 29,
    "Dane Acker": 26,
    "Dane Lais": 20,
    "Dangelo Sarmiento": 20,
    "Daniel Blair": 26,
    "Daniel Campos": 19,
    "Daniel Cope": 28,
    "Daniel Corniel": 20,
    "Daniel Dominguez": 17,
    "Daniel Duarte": 27,
    "Daniel Eagen": 22,
    "Daniel Espino": 25,
    "Daniel Federman": 26,
    "Daniel Flames": 18,
    "Daniel Guerra": 21,
    "Daniel Guilarte": 21,
    "Daniel Harper": 26,
    "Daniel Hernandez": 17,
    "Daniel Juarez": 24,
    "Daniel Liriano": 18,
    "Daniel Lloyd": 24,
    "Daniel Lopez": 19,
    "Daniel McElveny": 22,
    "Daniel Meza": 17,
    "Daniel Mielcarek": 19,
    "Daniel Missaki": 29,
    "Daniel Montesino": 21,
    "Daniel Nunez": 22,
    "Daniel Palencia": 25,
    "Daniel Pena": 20,
    "Daniel Robert": 30,
    "Daniel Rodriguez": 17,
    "Daniel Rogers": 23,
    "Daniel Rojas": 19,
    "Daniel Silva": 20,
    "Daniel Susac": 24,
    "Daniel Vazquez": 21,
    "Daniel Vellojin": 25,
    "Danny Cancro": 18,
    "Danny De Andrade": 21,
    "Danny Flatt": 21,
    "Danny Gonzalez": 20,
    "Danny Hilario": 20,
    "Danny Kirwin": 25,
    "Danny Serretti": 25,
    "Danny Watson": 24,
    "Danny Wilkinson": 24,
    "Danny Wirchansky": 27,
    "Dansby Swanson": 31,
    "Dante Nori": 20,
    "Danyer Cueva": 21,
    "Danyony Pulido": 22,
    "Daonil Montero": 17,
    "Darell Morel": 17,
    "Darian Castillo": 18,
    "Darian Rivero": 19,
    "Darick Hall": 29,
    "Dariel Arias": 18,
    "Dariel Francia": 18,
    "Dariel Fregio": 25,
    "Dariel Garcia": 18,
    "Dariel Polanco": 19,
    "Dariel Ramon": 19,
    "Darien Smith": 25,
    "Dario Laverde": 20,
    "Dario Reynoso": 20,
    "Darison Garcia": 18,
    "Darius Hill": 27,
    "Darius Perry": 24,
    "Darius Vines": 26,
    "Darlin Mendez": 20,
    "Darlin Moquete": 25,
    "Darlin Pinales": 22,
    "Darlin Saladin": 22,
    "Darling Fernandez": 19,
    "Darlyn De Leon": 20,
    "Darlyn Montero": 23,
    "Darrel Lunar": 19,
    "Darren Baker": 26,
    "Darren Bowen": 24,
    "Darrien Miller": 24,
    "Darvin Cruz": 19,
    "Darvin Garcia": 26,
    "Darwin Almanzar": 17,
    "Darwin De Leon": 21,
    "Darwin Nunez": 17,
    "Darwin Rodriguez": 21,
    "Darwing Ozuna": 17,
    "Dasan Brown": 23,
    "Dasan Hill": 20,
    "Dash Albus": 22,
    "Dashyll Tejeda": 19,
    "Daulton Varsho": 29,
    "Dauri Fernandez": 18,
    "Daury Vasquez": 19,
    "Daury Zapata": 22,
    "Daurys Mora": 21,
    "Dave Neely": 18,
    "Davian Garcia": 21,
    "David  Landeta": 22,
    "David Avitia": 26,
    "David Bañuelos": 28,
    "David Beckles": 21,
    "David Bednar": 31,
    "David Bracho": 20,
    "David Buchanan": 36,
    "David Calabrese": 22,
    "David Carrera": 18,
    "David Davalillo": 22,
    "David Festa": 25,
    "David Fletcher": 31,
    "David Garcia": 25,
    "David Hagaman": 22,
    "David Leal": 28,
    "David Lee": 25,
    "David Leon": 21,
    "David Lorduy": 21,
    "David Martin": 24,
    "David Matoma": 19,
    "David McCabe": 25,
    "David Mershon": 22,
    "David Morgan": 25,
    "David Ortiz Jr.": 17,
    "David Peterson": 30,
    "David Rodriguez": 23,
    "David Sandlin": 24,
    "David Shields": 18,
    "David Shirley": 17,
    "David Smith": 24,
    "Davidxon Lara": 18,
    "Daviel Hurtado": 20,
    "Davis Chastain": 21,
    "Davis Diaz": 22,
    "Davis Martin": 29,
    "Davis Polo": 19,
    "Davis Schneider": 27,
    "Davis Sharpe": 25,
    "Davis Wendzel": 28,
    "Davison Palermo": 25,
    "Dawel Joseph": 18,
    "Dawel Serda": 20,
    "Dawil Almonte": 23,
    "Dawson Brown": 24,
    "Dawson Netz": 24,
    "Dawson Price": 20,
    "Dax Fulton": 23,
    "Dax Kilby": 18,
    "Dayan Frias": 23,
    "Dayber Cruceta": 17,
    "Daylen Lile": 23,
    "Dayne Leonard": 25,
    "Dayquer Alfonzo": 17,
    "Dayson Croes": 25,
    "Dean Curley": 21,
    "Dean Kremer": 30,
    "Dedniel Núñez": 29,
    "Deinis Chourio": 16,
    "Deinys Gonzalez": 18,
    "Deivi Garcia": 26,
    "Deivi Villafana": 22,
    "Deivid Coronil": 17,
    "Deivis Mosquera": 20,
    "Deivy Cruz": 21,
    "Deivy Paulino": 20,
    "Demetrio Crisantes": 20,
    "Demetrio Nadal": 20,
    "Dencer Diaz": 16,
    "Deniel Ortiz": 20,
    "Denison Sanchez": 19,
    "Dennis Colleran": 21,
    "Denny Larrondo": 23,
    "Denny Lima": 20,
    "Dennys Riera": 20,
    "Denzer Guzman": 21,
    "Derek Berg": 23,
    "Derek Bernard": 19,
    "Derek Corro": 20,
    "Derek Datil": 19,
    "Derek Diamond": 24,
    "Derek True": 24,
    "Derik Alcantara": 20,
    "Derlin Figueroa": 21,
    "Derniche Valdez": 19,
    "Derrick Edington": 25,
    "Dervy Ventura": 21,
    "Deshandro Tromp": 18,
    "Deuri Castillo": 21,
    "Devereaux Harrison": 24,
    "Devin Fitz-Gerald": 19,
    "Devin Futrell": 22,
    "Devin Kirby": 25,
    "Devin Mann": 28,
    "Devin Ortiz": 26,
    "Devin Saltiban": 20,
    "Devin Sweet": 28,
    "Devin Taylor": 21,
    "Devin Williams": 31,
    "Devlyn Bautista": 18,
    "Devonte Brown": 25,
    "Deward Tovar": 19,
    "Dexters Peralta": 17,
    "Deyer Zapata": 21,
    "Deyvison De Los Santos": 22,
    "Didier Fuentes": 20,
    "Diego Alambarrio": 17,
    "Diego Barrera": 25,
    "Diego Benitez": 20,
    "Diego Campos": 18,
    "Diego Cartaya": 24,
    "Diego Castillo": 27,
    "Diego Contreras": 17,
    "Diego Dominguez": 20,
    "Diego Flores": 18,
    "Diego Gonzalez": 22,
    "Diego Guzman": 21,
    "Diego Hernandez": 24,
    "Diego Mosquera": 21,
    "Diego Munoz": 17,
    "Diego Natera": 17,
    "Diego Omana": 22,
    "Diego Rondon": 17,
    "Diego Tornes": 16,
    "Diego Velasquez": 21,
    "Diego Villegas": 21,
    "Diego Viloria": 22,
    "Dikember Sanchez": 21,
    "Dilan Figueredo": 22,
    "Dilan Granadillo": 24,
    "Dillon Head": 20,
    "Dillon Lewis": 22,
    "Diomar Hidalgo": 18,
    "Diomedes Hernandez": 20,
    "Dionmy Salon": 23,
    "Dionys Rodriguez": 24,
    "Dioris De La Rosa": 18,
    "Dioris Martinez": 19,
    "Diorland Zambrano": 18,
    "Diosfran Cabeza": 22,
    "Diovel Mariano": 21,
    "Diover De Aza": 17,
    "Diwarys Encarnacion": 19,
    "Dixon Williams": 21,
    "Djean Macares": 17,
    "Doimil Perez": 21,
    "Dom Hamel": 26,
    "Domenic Picone": 24,
    "Domingo Batista": 18,
    "Domingo Geronimo": 20,
    "Domingo Gonzalez": 25,
    "Domingo Morla": 17,
    "Domingo Robles": 27,
    "Dominic Fletcher": 27,
    "Dominic Freeberger": 25,
    "Dominic Hambley": 22,
    "Dominic Keegan": 24,
    "Dominic Perachi": 24,
    "Dominic Pitelli": 23,
    "Dominic Scheffler": 20,
    "Donny Troconis": 19,
    "Donovan Benoit": 26,
    "Donovan Walton": 31,
    "Donovan Zsak": 21,
    "Donta' Williams": 26,
    "Donte Grant": 20,
    "Donye Evans": 22,
    "Dorian Soto": 17,
    "Doug Nikhazy": 25,
    "Douglas Glod": 20,
    "Douglas Hodo III": 24,
    "Douglas Orellana": 23,
    "Drake Baldwin": 24,
    "Drake Fellows": 27,
    "Drake Logan": 24,
    "Drake Osborn": 26,
    "Drew Beam": 22,
    "Drew Bowser": 23,
    "Drew Brutcher": 23,
    "Drew Cavanaugh": 23,
    "Drew Compton": 24,
    "Drew Conover": 23,
    "Drew Davies": 19,
    "Drew Dowd": 23,
    "Drew Ehrhard": 26,
    "Drew Ellis": 29,
    "Drew Faurot": 21,
    "Drew Garrett": 25,
    "Drew Gilbert": 24,
    "Drew Gray": 22,
    "Drew Jemison": 24,
    "Drew McDaniel": 23,
    "Drew Parrish": 27,
    "Drew Pestka": 21,
    "Drew Pomeranz": 37,
    "Drew Rasmussen": 30,
    "Drew Rom": 25,
    "Drew Romo": 23,
    "Drew Sommers": 24,
    "Drew Swift": 26,
    "Drew Thorpe": 25,
    "Drew Vogel": 23,
    "Dru Baker": 25,
    "Drue Hackenberg": 23,
    "Druw Jones": 22,
    "Dub Gleed": 22,
    "Duce Gourson": 22,
    "Dugan Darnell": 28,
    "Duke Ellis": 27,
    "Duncan Davitt": 25,
    "Duncan Pastore": 25,
    "Duque Hebbert": 23,
    "Dustin Crenshaw": 23,
    "Dustin Dickerson": 24,
    "Dustin Harris": 25,
    "Dustin May": 28,
    "Dustin Saenz": 26,
    "Dwayne Matos": 24,
    "Dyan Jorge": 22,
    "Dylan Beavers": 24,
    "Dylan Campbell": 22,
    "Dylan Carmouche": 23,
    "Dylan Cease": 30,
    "Dylan Covey": 33,
    "Dylan Crews": 23,
    "Dylan Cumming": 26,
    "Dylan DeLucia": 24,
    "Dylan Dreiling": 22,
    "Dylan Fien": 19,
    "Dylan File": 29,
    "Dylan Grego": 21,
    "Dylan Hecht": 31,
    "Dylan Heid": 27,
    "Dylan Howard": 22,
    "Dylan Jasso": 22,
    "Dylan Jordan": 19,
    "Dylan Leach": 22,
    "Dylan Lesko": 22,
    "Dylan MacLean": 22,
    "Dylan Palmer": 21,
    "Dylan Phillips": 26,
    "Dylan Questad": 20,
    "Dylan Ray": 24,
    "Dylan Ross": 24,
    "Dylan Shockley": 28,
    "Dylan Simmons": 24,
    "Dylan Smith": 25,
    "Dylan Wilson": 19,
    "E.J. Exposito": 24,
    "EJ Andrews Jr.": 24,
    "Easton Carmichael": 21,
    "Easton Lucas": 29,
    "Easton McGee": 27,
    "Easton Shelton": 19,
    "Easton Sikorski": 25,
    "Eccel Correa": 22,
    "Echedry Vargas": 20,
    "Ed Howard": 23,
    "Eddie Micheletti Jr.": 23,
    "Eddie Rynders": 19,
    "Eddinson Charles": 17,
    "Eddinson Paulino": 22,
    "Eddson Martinez": 17,
    "Eddy Alvarez": 35,
    "Eddy Felix": 21,
    "Eddy Marmolejos": 18,
    "Eddy Rodriguez": 21,
    "Eddy Yean": 24,
    "Eddys Leonard": 24,
    "Edgar Alfonso": 21,
    "Edgar Alvarez": 24,
    "Edgar Barclay": 27,
    "Edgar Colon": 19,
    "Edgar Isea": 22,
    "Edgar Jimenez": 18,
    "Edgar Leon": 20,
    "Edgar Lugo": 20,
    "Edgar Montero": 18,
    "Edgar Moreta": 21,
    "Edgar Mota": 19,
    "Edgar Portes": 22,
    "Edgar Quero": 22,
    "Edgar Sanchez": 24,
    "Edgar Walker": 17,
    "Edgardo De Leon": 18,
    "Edgardo Figueroa": 17,
    "Edgardo Henriquez": 23,
    "Edgardo Ordonez": 21,
    "Edgleen Perez": 19,
    "Ediel Rivera": 19,
    "Edinson Batista": 23,
    "Edinson Duran": 22,
    "Edinson Salgado": 20,
    "Edinzo Marquez": 20,
    "Edouard Julien": 26,
    "Edrei Campos": 20,
    "Edrick Felix": 23,
    "Eduar Gonzalez": 19,
    "Eduardo Beltre": 18,
    "Eduardo Castillo": 21,
    "Eduardo Garcia": 22,
    "Eduardo Guerrero": 20,
    "Eduardo Guillen": 17,
    "Eduardo Herrera": 18,
    "Eduardo Lopez": 23,
    "Eduardo Oviedo": 20,
    "Eduardo Perez": 18,
    "Eduardo Ponce": 18,
    "Eduardo Quintero": 20,
    "Eduardo Rivera": 22,
    "Eduardo Rodriguez": 32,
    "Eduardo Rojas": 18,
    "Eduardo Tait": 19,
    "Eduardo Valencia": 25,
    "Eduarlin Tejeda": 20,
    "Eduarniel Núñez": 26,
    "Edward Cabrera": 27,
    "Edward Cedano": 19,
    "Edward Duran": 21,
    "Edward Florentino": 19,
    "Edward Guribe": 18,
    "Edward Lantigua": 18,
    "Edwardo Espinal": 19,
    "Edwardo Melendez": 21,
    "Edwilmin Matos": 17,
    "Edwin Amparo": 20,
    "Edwin Arroyo": 22,
    "Edwin Brito": 18,
    "Edwin Darville": 18,
    "Edwin Diaz": 31,
    "Edwin Jimenez": 22,
    "Edwin Nunez": 23,
    "Edwin Sanchez": 20,
    "Edwin Uceta": 28,
    "Efrain Cubilla": 20,
    "Efren Teran": 18,
    "Eguy Rosario": 25,
    "Eiberson Castellano": 24,
    "Eider Machuca": 20,
    "Eiker Huizi": 24,
    "Eiver Espinoza": 21,
    "Elerick Gomez": 17,
    "Eli Ankeney": 24,
    "Eli Lovich": 19,
    "Eli Saul": 23,
    "Eli Serrano III": 22,
    "Eli Trop": 23,
    "Eli Willits": 17,
    "Eli Wilson": 26,
    "Elian Adames": 17,
    "Elian De La Cruz": 17,
    "Elian Pena": 18,
    "Elian Rayo": 22,
    "Elian Reyes": 16,
    "Elian Serrata": 23,
    "Elian Soto": 19,
    "Eliander Alcalde": 21,
    "Eliander Primera": 17,
    "Elias Marrero": 17,
    "Elias Medina": 19,
    "Elias Perez": 17,
    "Elias Reyno": 17,
    "Eliazar De Los Santos": 22,
    "Eliazar Dishmey": 20,
    "Eliesbert Alejos": 19,
    "Eliezer Adames": 17,
    "Eliezer Alfonzo": 25,
    "Eliezer Rivero": 20,
    "Eligio Arias": 22,
    "Elih Marrero": 28,
    "Elijah Dale": 24,
    "Elijah Green": 22,
    "Elijah Hainline": 22,
    "Elijah Nunez": 23,
    "Elijah Pleasants": 25,
    "Elio Campos": 21,
    "Elio Prado": 23,
    "Eliomar Garces": 17,
    "Elis Cuevas": 20,
    "Elisandro Ramirez": 17,
    "Eliseo Mota": 22,
    "Elison Joseph": 24,
    "Elly De La Cruz": 24,
    "Elmer Rodriguez": 22,
    "Elmer Rodriguez-Cruz": 21,
    "Elorky Rodriguez": 17,
    "Elvin Garcia": 18,
    "Elvis Alvarado": 26,
    "Elvis Novas": 22,
    "Elvis Reyes": 22,
    "Elvis Rijo": 21,
    "Elwis Mijares": 19,
    "Ely Brown": 20,
    "Emaarion Boyd": 21,
    "Emdys Rosillo": 18,
    "Emerson Hancock": 26,
    "Emil Martinez": 17,
    "Emil Morales": 19,
    "Emil Turbi": 20,
    "Emile Torres": 17,
    "Emiliano Galan": 18,
    "Emiliano Teodo": 24,
    "Emilien Pitre": 22,
    "Emilio Barreras": 21,
    "Emilio Gonzalez": 17,
    "Emilio Pagan": 34,
    "Emilio Sanchez": 18,
    "Eminen Flores": 22,
    "Emmanuel Cedeno": 17,
    "Emmanuel Chapman": 26,
    "Emmanuel Clase": 27,
    "Emmanuel Martinez": 17,
    "Emmanuel Orozco": 16,
    "Emmanuel Reyes": 21,
    "Emmanuel Rivera": 29,
    "Emmanuel Rodriguez": 22,
    "Emmet Sheehan": 26,
    "Emmett Olson": 23,
    "Enddy Azocar": 18,
    "Enderjer Sifontes": 22,
    "Enderso Lira": 21,
    "Enderson Delgado": 20,
    "Enderson Mercado": 18,
    "Endrys Briceno": 33,
    "Endy Rios": 18,
    "Engel Daniel Peralta": 20,
    "Engel Paulino": 18,
    "Engel Silvestre": 19,
    "Engelth Urena": 20,
    "Engert Garcia": 25,
    "Enmanuel Bonilla": 19,
    "Enmanuel Corniel": 18,
    "Enmanuel Figuereo": 17,
    "Enmanuel Pinales": 24,
    "Enmanuel Ramirez": 21,
    "Enmanuel Tejeda": 20,
    "Enmanuel Terrero": 22,
    "Enniel Cortez": 18,
    "Enny Rodriguez": 17,
    "Enoli Paredes": 29,
    "Enrique Bradfield Jr.": 24,
    "Enrique Hernandez": 34,
    "Enrique Hernández": 33,
    "Enrique Jimenez": 19,
    "Enrique Segura": 20,
    "Enry Torres": 17,
    "Enyel Lopez": 19,
    "Enyel Rosario": 18,
    "Enyervert Perez": 19,
    "Erasmi Rodriguez": 21,
    "Erian Rodriguez": 23,
    "Eriandys Ramon": 22,
    "Eric Adler": 24,
    "Eric Bitonti": 20,
    "Eric Brown Jr.": 24,
    "Eric Cerantola": 25,
    "Eric Dominguez": 22,
    "Eric Genther": 23,
    "Eric Hartman": 19,
    "Eric Loomis": 23,
    "Eric Martinez": 21,
    "Eric Mota": 17,
    "Eric Orze": 27,
    "Eric Pardinho": 24,
    "Eric Rataczak": 24,
    "Eric Reyzelman": 24,
    "Eric Silva": 22,
    "Eric Snow": 21,
    "Eric Yang": 27,
    "Eric Yost": 22,
    "Erick Alvarez": 20,
    "Erick Batista": 19,
    "Erick Brito": 23,
    "Erick De La Cruz": 18,
    "Erick Lara": 19,
    "Erick Leal": 30,
    "Erick Lugo": 18,
    "Erick Mejia": 30,
    "Erick Reynoso": 22,
    "Erick Torres": 20,
    "Erickson Ayena": 19,
    "Eriel Dihigo": 18,
    "Erigaldi Perez": 19,
    "Erik Ritchie": 22,
    "Erik Rivera": 24,
    "Erik Sabrowski": 27,
    "Erik Tolman": 26,
    "Eriq Swan": 23,
    "Eris Albino": 21,
    "Ernesto Martinez Jr.": 26,
    "Ernesto Mercedes": 21,
    "Ernie Clement": 29,
    "Ernie Day": 23,
    "Erny Orellana": 18,
    "Erubiel Armenta": 25,
    "Eryks Rivero": 17,
    "Esmeiquel Arrieche": 18,
    "Esmerlin Vinicio": 22,
    "Esmerlyn Valdez": 21,
    "Esmil Valencia": 19,
    "Esmith Pineda": 20,
    "Esnaider Vargas": 17,
    "Estarlin Escalante": 21,
    "Estarling Mercado": 22,
    "Esteban Castro": 17,
    "Esteban Gonzalez": 22,
    "Esteban Mejia": 20,
    "Esteban Romero": 18,
    "Estibenzon Jimenez": 23,
    "Estivel Morillo": 17,
    "Estivenzon Montero": 18,
    "Eston Stull": 26,
    "Estuar Suero": 19,
    "Ethan Anderson": 21,
    "Ethan Bagwell": 19,
    "Ethan Bosacker": 24,
    "Ethan Chenault": 24,
    "Ethan Dorchies": 18,
    "Ethan Flanagan": 23,
    "Ethan Frey": 21,
    "Ethan Hammerberg": 24,
    "Ethan Hearn": 24,
    "Ethan Hedges": 21,
    "Ethan Holliday": 18,
    "Ethan Lanthier": 22,
    "Ethan Lege": 24,
    "Ethan Long": 24,
    "Ethan Murray": 25,
    "Ethan O'Donnell": 23,
    "Ethan Pecko": 22,
    "Ethan Petry": 21,
    "Ethan Roberts": 27,
    "Ethan Routzahn": 27,
    "Ethan Salas": 19,
    "Ethan Schiefelbein": 19,
    "Ethan Sloan": 22,
    "Ethan Small": 28,
    "Ethan Wagner": 19,
    "Ethan Workinger": 23,
    "Eudry Alcantara": 20,
    "Eugenio Suarez": 34,
    "Euri Montero": 23,
    "Euri Rosa": 17,
    "Euribiel Angeles": 23,
    "Eury Perez": 22,
    "Eurys Martich": 22,
    "Evan Aschenbeck": 24,
    "Evan Carter": 23,
    "Evan Edwards": 28,
    "Evan Estevez": 17,
    "Evan Fitterer": 25,
    "Evan Gates": 27,
    "Evan Gray": 24,
    "Evan Justice": 26,
    "Evan Kravetz": 28,
    "Evan McKendry": 27,
    "Evan Reifert": 26,
    "Evan Shaw": 24,
    "Evan Shawver": 25,
    "Evan Sisk": 28,
    "Evan Taylor": 25,
    "Evan Truitt": 22,
    "Evan Yates": 22,
    "Everett Catlett": 22,
    "Everett Cooper III": 21,
    "Eybert Sanchez": 17,
    "Eyeksson Rojas": 19,
    "Ezequiel Aparicio": 17,
    "Ezequiel Duran": 26,
    "Ezequiel Jimenez": 22,
    "Ezequiel Pagan": 24,
    "Ezequiel Pena": 18,
    "Ezequiel Tovar": 24,
    "Fabelin Volquez": 17,
    "Fabian Alcantara": 19,
    "Fabian Cordero": 17,
    "Fabian Dorta": 17,
    "Fabian Lopez": 19,
    "Fabian Ysalla": 20,
    "Facundo Velasquez": 19,
    "Feldi Tavarez": 18,
    "Felipe De La Cruz": 24,
    "Felix Amparo": 19,
    "Felix Arronde": 22,
    "Felix Bautista": 30,
    "Felix Cabrera": 23,
    "Felix Castro": 21,
    "Felix Cotes": 19,
    "Felix Morrobel": 19,
    "Felix Ramires": 25,
    "Felix Reyes": 24,
    "Felix Stevens": 25,
    "Felix Tena": 21,
    "Feliz Genao": 17,
    "Felnin Celesten": 20,
    "Fenwick Trimble": 22,
    "Fermin Magallanes": 23,
    "Fernando Caldera": 22,
    "Fernando Cruz": 35,
    "Fernando Gonzalez": 23,
    "Fernando Lara": 17,
    "Fernando Peguero": 20,
    "Fernando Pena": 18,
    "Fernando Perez": 21,
    "Fernando Ramos": 22,
    "Fernando Sanchez": 24,
    "Fernando Tatis Jr.": 27,
    "Fernando Vasquez": 23,
    "Fidel Pinango": 17,
    "Fidel Ulloa": 22,
    "Filippo Di Turi": 19,
    "Fineas Del Bonta-Smith": 28,
    "Florencio Serrano": 25,
    "Forrest Whitley": 28,
    "Fraimy Santa": 17,
    "Frainner Chirinos": 18,
    "Frainyer Chavez": 26,
    "Framber Valdez": 32,
    "Fran Oschell III": 22,
    "Francesco Barbieri": 25,
    "Franchely Silverio": 18,
    "Francis Pena": 24,
    "Francis Rivera": 24,
    "Francis Sosa": 17,
    "Francis Texido": 20,
    "Francisco Acuna": 25,
    "Francisco Alvarez": 24,
    "Francisco Caldera": 19,
    "Francisco Espinoza": 18,
    "Francisco Frias": 20,
    "Francisco Garcia": 22,
    "Francisco Lindor": 32,
    "Francisco Loreto": 18,
    "Francisco Morao": 19,
    "Francisco Pazos": 19,
    "Francisco Perez": 18,
    "Francisco Toledo": 20,
    "Francisco Urbaez": 27,
    "Francisco Vilorio": 18,
    "Franck De La Rosa": 25,
    "Franco Aleman": 25,
    "Franco Willias": 20,
    "Frandy Guillen": 17,
    "Frandy Lafond": 18,
    "Frank Elissalt": 23,
    "Frank Martinez": 23,
    "Frank Mieses": 17,
    "Frank Mozzicato": 22,
    "Frank Rodriguez": 23,
    "Frankeli Arias": 22,
    "Frankeli Mesta": 18,
    "Frankie Scalzo Jr.": 25,
    "Franklin Arias": 20,
    "Franklin Gomez": 19,
    "Franklin Primera": 18,
    "Franklin Rojas": 18,
    "Franklin Sanchez": 24,
    "Franly Urena": 21,
    "Franyer Herrera": 20,
    "Franyer Noria": 20,
    "Franyerber Montilla": 20,
    "Fraser Ellard": 27,
    "Fraymi De Leon": 20,
    "Fraynel Nova": 23,
    "Fred Fajardo": 20,
    "Fredderick Ovalle": 18,
    "Freddie Freeman": 36,
    "Freddy Pacheco": 27,
    "Freddy Peralta": 29,
    "Freddy Ramos": 17,
    "Freddy Tarnok": 26,
    "Freddy Zamora": 26,
    "Frederi Montero": 18,
    "Frederick Bencosme": 22,
    "Frederick Saguita": 17,
    "Frederik Jimenez": 20,
    "Freider Rojas": 19,
    "Freiker Betencourt": 16,
    "Freili Encarnacion": 20,
    "Freilyn Rodriguez": 17,
    "Freuddy Batista": 25,
    "Fulton Lockhart": 21,
    "GJ Hill": 24,
    "Gabe Bierman": 25,
    "Gabe Craig": 23,
    "Gabe Mosser": 29,
    "Gabe Speier": 30,
    "Gabe Starks": 23,
    "Gabriel Agostini": 20,
    "Gabriel Aguilera": 24,
    "Gabriel Azocar": 17,
    "Gabriel Barbosa": 23,
    "Gabriel Cesa": 18,
    "Gabriel Colmenarez": 19,
    "Gabriel Davalillo": 17,
    "Gabriel Flores": 17,
    "Gabriel Gomes": 21,
    "Gabriel Gonzalez": 22,
    "Gabriel Guanchez": 18,
    "Gabriel Hughes": 23,
    "Gabriel Jackson": 23,
    "Gabriel Lara": 19,
    "Gabriel Lopez": 19,
    "Gabriel Martinez": 22,
    "Gabriel Moncada": 23,
    "Gabriel Moreno": 25,
    "Gabriel Reyes": 21,
    "Gabriel Rincones Jr.": 24,
    "Gabriel Rodriguez": 18,
    "Gabriel Rosado": 19,
    "Gabriel Silva": 21,
    "Gabriel Sosa": 24,
    "Gabriel Terrero": 19,
    "Gabriel Yanez": 25,
    "Gage Boehm": 23,
    "Gage Jump": 22,
    "Gage Miller": 22,
    "Gage Stanifer": 22,
    "Gage Workman": 25,
    "Gage Ziehl": 22,
    "Gant Starling": 24,
    "Garret Forrester": 23,
    "Garret Guillemette": 23,
    "Garrett Acton": 27,
    "Garrett Apker": 25,
    "Garrett Baumann": 20,
    "Garrett Burhenn": 25,
    "Garrett Cleavinger": 31,
    "Garrett Crochet": 26,
    "Garrett Davila": 28,
    "Garrett Edwards": 23,
    "Garrett Gainey": 25,
    "Garrett Hampson": 30,
    "Garrett Hawkins": 25,
    "Garrett Horn": 22,
    "Garrett Howe": 22,
    "Garrett Irvin": 26,
    "Garrett Martin": 25,
    "Garrett McDaniels": 25,
    "Garrett McMillan": 24,
    "Garrett Pennington": 24,
    "Garrett Schoenle": 27,
    "Garrett Spain": 24,
    "Garrett Stallings": 27,
    "Garrett Stubbs": 31,
    "Garrett Whitlock": 29,
    "Garrett Wright": 23,
    "Garvin Alston": 28,
    "Gary Gill Hill": 20,
    "Gary Sánchez": 32,
    "Gavin Adams": 22,
    "Gavin Bruni": 22,
    "Gavin Collyer": 24,
    "Gavin Conticello": 22,
    "Gavin Cross": 24,
    "Gavin Dugas": 25,
    "Gavin Fien": 18,
    "Gavin Kilen": 21,
    "Gavin Logan": 25,
    "Gavin Lux": 28,
    "Gavin Sheets": 29,
    "Gavin Stone": 27,
    "Gavin Turley": 21,
    "Gavin Williams": 26,
    "Geison Urbaez": 24,
    "Geoff Hartlieb": 31,
    "Geoffrey Gilbert": 24,
    "Geomaikel Martinez": 17,
    "George Bilecki": 21,
    "George Feliz": 22,
    "George Kirby": 27,
    "George Klassen": 24,
    "George Lombard Jr.": 20,
    "George Springer": 36,
    "George Valera": 24,
    "George Wolkow": 19,
    "Georwill Rodriguez": 17,
    "Geovanny Planchart": 23,
    "Geovanny Vasquez": 21,
    "Gerald Ogando": 24,
    "Geraldo Perdomo": 26,
    "Geraldo Quintero": 23,
    "Gerardo Cardona": 18,
    "Gerardo Carrillo": 26,
    "Gerardo Gutierrez": 26,
    "Gerardo Rodriguez": 19,
    "Gerelmi Maldonado": 21,
    "Gerlin Rosario": 23,
    "Gerlyn Payano": 17,
    "German Fajardo": 24,
    "German Marquez": 30,
    "German Nunez": 23,
    "German Ortiz": 20,
    "German Ramirez": 18,
    "Gerrit Cole": 35,
    "Gerson Garabito": 29,
    "Gerson Moreno": 29,
    "Gery Holguin": 19,
    "Geury Rodriguez": 20,
    "Gian Zapata": 19,
    "Giancarlo Stanton": 36,
    "Gijs Van Den Brink": 19,
    "Gil Luna": 25,
    "Gilbel Galvan": 18,
    "Gilberto Batista": 20,
    "Gio Cueto": 21,
    "Giomar Diaz": 22,
    "Giomar Ubiera": 17,
    "Giovanni Vargas": 19,
    "Giullianno Allende": 21,
    "Giussepe Velasquez": 22,
    "Givian Sirvania": 17,
    "Gleider Figuereo": 21,
    "Gleiner Diaz": 21,
    "Gleyber Torres": 29,
    "Gordon Graceffo": 25,
    "Grabiel Salazar": 24,
    "Grae Kessinger": 27,
    "Graham Ashcraft": 27,
    "Graham Osman": 24,
    "Grant Burleson": 22,
    "Grant Cherry": 22,
    "Grant Hartwig": 27,
    "Grant Holman": 25,
    "Grant Holmes": 29,
    "Grant Judkins": 27,
    "Grant Kipp": 25,
    "Grant Magill": 24,
    "Grant Richardson": 25,
    "Grant Rogers": 24,
    "Grant Shepardson": 19,
    "Grant Smith": 24,
    "Grant Taylor": 23,
    "Grant Umberger": 23,
    "Grant Wolfram": 28,
    "Gray Thomas": 22,
    "Graysen Tarlow": 23,
    "Grayson Hitt": 23,
    "Grayson Moore": 23,
    "Grayson Rodriguez": 26,
    "Grayson Thurman": 26,
    "Greg Farone": 23,
    "Greg Jones": 27,
    "Gregori Louis": 22,
    "Gregori Ramirez": 20,
    "Gregory Barrios": 21,
    "Gregory Soto": 30,
    "Greiber Mendez": 21,
    "Greylin De La Paz": 18,
    "Greysen Carter": 22,
    "Grif Hughes": 23,
    "Griff McGarry": 26,
    "Griff O'Ferrall": 22,
    "Griffin Burkholder": 20,
    "Griffin Canning": 29,
    "Griffin Herring": 22,
    "Griffin Jax": 31,
    "Griffin Kilander": 22,
    "Griffin Lockwood-Powell": 27,
    "Griffin Tobias": 19,
    "Guillermo Batista": 18,
    "Guillermo Rosario": 20,
    "Guillermo Williamson": 21,
    "Guillo Zuniga": 26,
    "Gunnar Henderson": 24,
    "Gunnar Hoglund": 25,
    "Gunner Gouldsmith": 23,
    "Gunner Mayer": 24,
    "Gus Varland": 28,
    "Gustavo Antunez": 17,
    "Gustavo Baptista": 17,
    "Gustavo Campero": 27,
    "Gustavo Marquez": 20,
    "Gustavo Rodriguez": 24,
    "Guy Lipscomb": 24,
    "Ha-seong Kim": 30,
    "Haden Erbe": 26,
    "Hagen Danner": 26,
    "Hagen Smith": 22,
    "Hale Sims": 25,
    "Haminton Mendez": 21,
    "Hancel Almonte": 19,
    "Hancel Rincon": 23,
    "Handelfry Encarnacion": 18,
    "Haniel German": 19,
    "Hanley Ramirez": 18,
    "Hans Crouse": 26,
    "Hans Montero": 21,
    "Hansel Jimenez": 18,
    "Hansel Rosario": 22,
    "Hao-Yu  Lee": 22,
    "Hao-Yu Lee": 22,
    "Haritzon Castillo": 17,
    "Harlin Naut": 20,
    "Harold Chirino": 27,
    "Harold Coll": 23,
    "Harold Gonzalez": 18,
    "Harold Melenge": 23,
    "Harold Rivas": 17,
    "Harrison Bader": 31,
    "Harrison Cohen": 26,
    "Harrison Spohn": 26,
    "Harry Ford": 22,
    "Harry Genth": 22,
    "Harry Gustin": 23,
    "Harry Owen": 23,
    "Hayden Alvarez": 18,
    "Hayden Birdsong": 24,
    "Hayden Cantrelle": 26,
    "Hayden Cuthbertson": 21,
    "Hayden Durke": 23,
    "Hayden Frank": 22,
    "Hayden Friese": 20,
    "Hayden Gilliland": 23,
    "Hayden Harris": 26,
    "Hayden Juenger": 24,
    "Hayden Merda": 25,
    "Hayden Minton": 24,
    "Hayden Mullins": 24,
    "Hayden Nierman": 25,
    "Hayden Robinson": 19,
    "Hayden Seig": 26,
    "Hayden Senger": 28,
    "Hayden Snelsire": 24,
    "Hayden Travinski": 24,
    "Hayden Wynja": 25,
    "Haydn McGeary": 25,
    "Hector Barroso": 17,
    "Hector Cabrera": 17,
    "Hector Campusano": 18,
    "Hector Francis": 17,
    "Hector Liriano": 19,
    "Hector Osorio": 20,
    "Hector Paulino": 17,
    "Hector Ramos": 17,
    "Hector Rodriguez": 21,
    "Hector Salas": 21,
    "Hedbert Perez": 22,
    "Heins Brito": 17,
    "Heison Sanchez": 20,
    "Helcris Olivarez": 24,
    "Helder Rosario": 20,
    "Heliot Ramos": 26,
    "Hendry Alcala": 18,
    "Hendry Arvelo": 18,
    "Hendry Chivilli": 19,
    "Hendry Mendez": 21,
    "Henniel Alcala": 19,
    "Henry Baez": 22,
    "Henry Bolte": 22,
    "Henry Godbout": 21,
    "Henry Gomez": 23,
    "Henry Lalane": 21,
    "Henry Ramos": 20,
    "Henry Williams": 23,
    "Henson Leal": 21,
    "Heribert Silva": 19,
    "Heriberto Caraballo": 20,
    "Heriberto Rincon": 19,
    "Herick Hernandez": 21,
    "Herlinton Herrera": 18,
    "Heston Kjerstad": 26,
    "Heudy Pena": 18,
    "Hiro Wyatt": 20,
    "Hiverson Lopez": 17,
    "Hobie Harris": 32,
    "Hogan Windish": 26,
    "Hojans Hernandez": 19,
    "Holden Powell": 25,
    "Holden Wilkerson": 22,
    "Holt Jones": 26,
    "Homer Bush Jr.": 23,
    "Hoss Brewer": 24,
    "Houston Harding": 27,
    "Houston Roth": 27,
    "Howard Reyes": 17,
    "Huascar Brazoban": 36,
    "Hudson Haskin": 26,
    "Hudson Head": 24,
    "Hudson Leach": 23,
    "Hudson White": 22,
    "Hueston Morrill": 25,
    "Humberto Cruz": 18,
    "Humberto Tiberi": 18,
    "Hung-Leng Chang": 23,
    "Hunter Alberini": 23,
    "Hunter Barco": 25,
    "Hunter Bigge": 27,
    "Hunter Bishop": 27,
    "Hunter Breault": 26,
    "Hunter Brown": 27,
    "Hunter Cranton": 24,
    "Hunter Dobbins": 22,
    "Hunter Ensley": 23,
    "Hunter Feduccia": 28,
    "Hunter Fitz-Gerald": 24,
    "Hunter Furtado": 23,
    "Hunter Gaddis": 27,
    "Hunter Goodman": 26,
    "Hunter Greene": 26,
    "Hunter Gregory": 26,
    "Hunter Haas": 23,
    "Hunter Hayes": 24,
    "Hunter Hodges": 22,
    "Hunter Hollan": 23,
    "Hunter Hoopes": 25,
    "Hunter Kublick": 21,
    "Hunter Mann": 23,
    "Hunter Omlid": 25,
    "Hunter Owen": 23,
    "Hunter Parks": 24,
    "Hunter Parsons": 28,
    "Hunter Patteson": 25,
    "Hunter Stanley": 27,
    "Hunter Stovall": 28,
    "Hurston Waldrep": 23,
    "Hyeseong Kim": 27,
    "Hyun Seung Lee": 17,
    "Hyun-Seok Jang": 21,
    "Hyun-il Choi": 25,
    "Hyungchan Um": 21,
    "Ian Bedell": 25,
    "Ian Daugherty": 22,
    "Ian Farrow": 22,
    "Ian Happ": 31,
    "Ian Koenig": 24,
    "Ian Lewis": 22,
    "Ian Mejia": 25,
    "Ian Moller": 22,
    "Ian Petrutz": 22,
    "Ian Seymour": 27,
    "Ian Villers": 24,
    "Ibrahim Ruiz": 18,
    "Ichiro Cano": 20,
    "Ignacio Briceno": 24,
    "Igor Escobar": 16,
    "Igor Gil": 24,
    "Ike Buxton": 24,
    "Ike Irish": 21,
    "Ilan Fernandez": 18,
    "Imanol Vargas": 27,
    "Indigo Diaz": 26,
    "Inmer Lobo": 21,
    "Inohan Paniagua": 25,
    "Ire Garcia": 17,
    "Irv Carter": 22,
    "Irvin Machuca": 25,
    "Irvin Nunez": 19,
    "Irving Cota": 21,
    "Irwin Ramirez": 18,
    "Isaac Ayon": 23,
    "Isaac Coffey": 25,
    "Isaac Collins": 28,
    "Isaac Gallegos": 22,
    "Isaac Garcia": 17,
    "Isaac Paredes": 26,
    "Isaac Pena": 21,
    "Isaac Ponce": 18,
    "Isaac Stebens": 23,
    "Isael Arias": 19,
    "Isaiah Campbell": 27,
    "Isaiah Coupet": 22,
    "Isaiah Drake": 19,
    "Isaiah Jackson": 21,
    "Isaiah Lowe": 22,
    "Isaias Castillo": 17,
    "Isaias Dipre": 22,
    "Isaias Uribe": 22,
    "Isais Chavez": 17,
    "Ishel Comenencia": 17,
    "Ismael Agreda": 21,
    "Ismael Del Rosario": 18,
    "Ismael Javier": 19,
    "Ismael Luciano": 22,
    "Ismael Mejia": 16,
    "Ismael Mena": 22,
    "Ismael Michel": 23,
    "Ismael Munguia": 26,
    "Ismael Yanez": 19,
    "Israel Alvarez": 17,
    "Israfell Bautista": 18,
    "Ivan Armstrong": 24,
    "Ivan Brethowr": 22,
    "Ivan Cespedes": 19,
    "Ivan Herrera": 25,
    "Ivan Johnson": 26,
    "Ivan Luciano": 18,
    "Ivan Melendez": 25,
    "Ivan Sosa": 20,
    "Ivan Torres": 17,
    "Iverson Allen": 17,
    "Iverson Espinoza": 22,
    "Ivran Romero": 23,
    "Ixan Henderson": 23,
    "Izaac Pacheco": 22,
    "Izaak Martinez": 23,
    "Izack Tiger": 23,
    "J.B. Bukauskas": 27,
    "J.C. Flowers": 27,
    "J.D. Gonzalez": 19,
    "J.J. D'Orazio": 23,
    "J.J. Niekro": 27,
    "J.P. Crawford": 31,
    "J.P. France": 30,
    "J.P. Massey": 25,
    "J.P. Sears": 29,
    "J.R. Freethy": 22,
    "J.R. Ritchie": 22,
    "J.T. Arruda": 27,
    "J.T. Etheridge": 23,
    "J.T. Ginn": 26,
    "J.T. Realmuto": 34,
    "JC Vanek": 20,
    "JD Dix": 19,
    "JJ Bleday": 28,
    "JJ Goss": 24,
    "JJ Sanchez": 25,
    "JJ Wetherholt": 23,
    "JP Smith II": 20,
    "JP Wheat": 22,
    "JR Ritchie": 22,
    "JT Schwartz": 25,
    "Jac Caglianone": 22,
    "Jace Avina": 22,
    "Jace Beck": 25,
    "Jace Bohrofen": 23,
    "Jace Grady": 24,
    "Jace Hampson": 19,
    "Jace Jung": 24,
    "Jace Kaminska": 22,
    "Jack Anderson": 25,
    "Jack Anker": 21,
    "Jack Barker": 20,
    "Jack Blomgren": 26,
    "Jack Brannigan": 24,
    "Jack Carey": 25,
    "Jack Cebert": 23,
    "Jack Choate": 24,
    "Jack Collins": 22,
    "Jack Costello": 24,
    "Jack Crowder": 22,
    "Jack Cushing": 28,
    "Jack Dallas": 26,
    "Jack Dashwood": 27,
    "Jack Dreyer": 26,
    "Jack Dunn": 28,
    "Jack Eshleman": 21,
    "Jack Findlay": 22,
    "Jack Flaherty": 30,
    "Jack Goodman": 21,
    "Jack Gurevitch": 21,
    "Jack Hartman": 26,
    "Jack Hurley": 23,
    "Jack Jasiak": 24,
    "Jack Kochanowicz": 25,
    "Jack Leftwich": 26,
    "Jack Leiter": 25,
    "Jack Lines": 19,
    "Jack Little": 27,
    "Jack Lopez": 32,
    "Jack Mahoney": 23,
    "Jack Mathey": 21,
    "Jack Moss": 23,
    "Jack Neely": 25,
    "Jack Noble": 25,
    "Jack O'Loughlin": 25,
    "Jack Payton": 23,
    "Jack Penney": 22,
    "Jack Perkins": 26,
    "Jack Pineda": 25,
    "Jack Ralston": 27,
    "Jack Rogers": 26,
    "Jack Sellinger": 25,
    "Jack Seppings": 22,
    "Jack Sinclair": 26,
    "Jack Snyder": 26,
    "Jack Wenninger": 23,
    "Jack White": 24,
    "Jack Winkler": 26,
    "Jack Winnay": 22,
    "Jack Young": 23,
    "Jackson Appel": 23,
    "Jackson Baumeister": 22,
    "Jackson Castillo": 22,
    "Jackson Chourio": 21,
    "Jackson Cluff": 28,
    "Jackson Feltner": 23,
    "Jackson Ferris": 22,
    "Jackson Finley": 23,
    "Jackson Fristoe": 24,
    "Jackson Grounds": 20,
    "Jackson Holliday": 22,
    "Jackson Hornung": 24,
    "Jackson Humphries": 20,
    "Jackson Jobe": 23,
    "Jackson Kelley": 25,
    "Jackson Kent": 22,
    "Jackson Kirkpatrick": 22,
    "Jackson Lancaster": 26,
    "Jackson Lovich": 21,
    "Jackson Merrill": 22,
    "Jackson Nezuh": 23,
    "Jackson Nicklaus": 22,
    "Jackson Ross": 25,
    "Jackson Smeltz": 25,
    "Jackson Strong": 21,
    "Jackson Wentworth": 22,
    "Jackson Wolf": 26,
    "Jacob Amaya": 26,
    "Jacob Berry": 24,
    "Jacob Bosiokovic": 31,
    "Jacob Bresnahan": 20,
    "Jacob Buchberger": 27,
    "Jacob Burke": 24,
    "Jacob Campbell": 25,
    "Jacob Cozart": 22,
    "Jacob Cravey": 23,
    "Jacob Denner": 24,
    "Jacob Friend": 22,
    "Jacob Gomez": 23,
    "Jacob Gonzalez": 23,
    "Jacob Hartlaub": 22,
    "Jacob Hinderleider": 24,
    "Jacob Humphrey": 22,
    "Jacob Hurtubise": 27,
    "Jacob Jenkins-Cowart": 22,
    "Jacob Kisting": 22,
    "Jacob Kroeger": 25,
    "Jacob Lojewski": 23,
    "Jacob Lopez": 27,
    "Jacob McCombs": 20,
    "Jacob Meador": 24,
    "Jacob Melton": 24,
    "Jacob Miller": 21,
    "Jacob Misiorowski": 23,
    "Jacob Nottingham": 30,
    "Jacob Odle": 21,
    "Jacob Reimer": 21,
    "Jacob Remily": 19,
    "Jacob Shafer": 23,
    "Jacob Sharp": 23,
    "Jacob Stallings": 35,
    "Jacob Steinmetz": 20,
    "Jacob Stretch": 22,
    "Jacob Waguespack": 31,
    "Jacob Wallace": 26,
    "Jacob Walsh": 22,
    "Jacob Watters": 24,
    "Jacob Webb": 26,
    "Jacob Wetzel": 25,
    "Jacob Widener": 24,
    "Jacob Wilson": 23,
    "Jacob Wosinski": 26,
    "Jacob Young": 26,
    "Jacob deGrom": 37,
    "Jaden Hamm": 22,
    "Jaden Hill": 25,
    "Jaden Rudd": 22,
    "Jaden Woods": 23,
    "Jadher Areinamo": 21,
    "Jadon Bercovich": 23,
    "Jadyn Fielder": 20,
    "Jaeden Calderon": 19,
    "Jagger Beck": 18,
    "Jagger Haynes": 22,
    "Jahni McPhee": 18,
    "Jaiker Garcia": 20,
    "Jaime Ferrer": 22,
    "Jair Camargo": 25,
    "Jairo Diaz": 20,
    "Jairo Iriarte": 23,
    "Jairo Pomares": 24,
    "Jaison Chourio": 20,
    "Jaitoine Kelly": 18,
    "Jake Anchia": 28,
    "Jake Bauers": 30,
    "Jake Bennett": 24,
    "Jake Bloss": 24,
    "Jake Bockenstedt": 25,
    "Jake Brooks": 23,
    "Jake Burger": 29,
    "Jake Casey": 22,
    "Jake Christianson": 25,
    "Jake Clemente": 21,
    "Jake Cronenworth": 32,
    "Jake Cunningham": 22,
    "Jake Curtis": 23,
    "Jake Eddington": 24,
    "Jake Eder": 26,
    "Jake Faherty": 22,
    "Jake Fitzgibbons": 23,
    "Jake Fox": 22,
    "Jake Garland": 24,
    "Jake Gelof": 23,
    "Jake Higginbotham": 29,
    "Jake Holton": 27,
    "Jake Irvin": 28,
    "Jake Jekielek": 22,
    "Jake Latz": 29,
    "Jake Madden": 23,
    "Jake Mangum": 29,
    "Jake McSteen": 29,
    "Jake Meyers": 29,
    "Jake Miller": 24,
    "Jake Munroe": 21,
    "Jake Palisch": 26,
    "Jake Peppers": 23,
    "Jake Pfennigs": 25,
    "Jake Rice": 27,
    "Jake Rogers": 30,
    "Jake Rucker": 25,
    "Jake Shirk": 23,
    "Jake Smith": 25,
    "Jake Snider": 27,
    "Jake Steels": 23,
    "Jake Thompson": 27,
    "Jake Walkinshaw": 28,
    "Jake Zitella": 20,
    "Jakey Josepha": 21,
    "Jakob Christian": 22,
    "Jakob Hall": 22,
    "Jakob Hernandez": 29,
    "Jakob Marsee": 24,
    "Jakson Reetz": 29,
    "Jalen Battles": 25,
    "Jalen Beeks": 32,
    "Jalen Hairston": 21,
    "Jalen Vasquez": 23,
    "Jalin Flores": 21,
    "Jalvin Arias": 18,
    "James Gonzalez": 24,
    "James Hicks": 24,
    "James Quinn-Irons": 22,
    "James Taussig": 22,
    "James Tibbs": 23,
    "James Tibbs III": 22,
    "James Triantos": 23,
    "James Wood": 23,
    "Jameson Taillon": 34,
    "Jamesson Val": 19,
    "Jan Caraballo": 21,
    "Jan Hechavarria": 21,
    "Jan Luis Reyes": 19,
    "Jancel Villarroel": 20,
    "Jancory De La Cruz": 19,
    "Jank Pichardo": 20,
    "Jansel Luis": 20,
    "Janser Lara": 28,
    "Janson Junk": 30,
    "Janzen Keisel": 22,
    "Jared Beck": 24,
    "Jared Dickey": 23,
    "Jared Johnson": 23,
    "Jared Jones": 24,
    "Jared Karros": 24,
    "Jared Kelley": 23,
    "Jared Koenig": 32,
    "Jared Kollar": 26,
    "Jared Lyons": 24,
    "Jared McKenzie": 24,
    "Jared Serna": 23,
    "Jared Simpson": 25,
    "Jared Southard": 24,
    "Jared Sprague-Lott": 23,
    "Jared Sundstrom": 24,
    "Jared Thomas": 24,
    "Jared Triolo": 27,
    "Jared Wegner": 25,
    "Jared Young": 29,
    "Jaren Warwick": 23,
    "Jarlin Susana": 21,
    "Jarod Bayless": 28,
    "Jarol Capellan": 19,
    "Jarold Rosado": 22,
    "Jaron DeBerry": 22,
    "Jaron Elkins": 20,
    "Jarred Kelenic": 26,
    "Jarren Duran": 29,
    "Jarret Whorff": 26,
    "Jarrod Cande": 24,
    "Jase Bowen": 24,
    "Jaset Martinez": 18,
    "Jason Adam": 34,
    "Jason Alexander": 32,
    "Jason Blanchard": 28,
    "Jason Doktorczyk": 22,
    "Jason Hernandez": 19,
    "Jason Matthews": 28,
    "Jason Ruffcorn": 26,
    "Jason Savacool": 23,
    "Jason Schiavone": 22,
    "Jasson Dominguez": 22,
    "Jatnk Diaz": 20,
    "Javen Coleman": 23,
    "Javi Rivera": 24,
    "Javi Torres": 20,
    "Javier Acevedo": 18,
    "Javier Bartolozzi": 20,
    "Javier Chacon": 22,
    "Javier Francisco": 22,
    "Javier Gonzalez": 19,
    "Javier Herrera": 20,
    "Javier Mogollon": 19,
    "Javier Osorio": 20,
    "Javier Pariguan": 21,
    "Javier Perez": 21,
    "Javier Rivas": 22,
    "Javier Roman": 22,
    "Javier Sanchez": 17,
    "Javier Sanoja": 22,
    "Javier Vaz": 24,
    "Jawilme Ramirez": 23,
    "Jax Biggers": 28,
    "Jaxon Dalena": 23,
    "Jaxon Wiggins": 24,
    "Jaxson West": 21,
    "Jaxx Groshans": 26,
    "Jay Allen II": 22,
    "Jay Allmer": 23,
    "Jay Beshears": 23,
    "Jay Dill": 22,
    "Jay Driver": 23,
    "Jay Groome": 27,
    "Jay Harry": 22,
    "Jay Schueler": 24,
    "Jay Thomason": 23,
    "Jaycob Deese": 25,
    "Jayden Dubanewicz": 19,
    "Jayden Felicia": 19,
    "Jayden Kim": 18,
    "Jayden Murray": 28,
    "Jaydenn Estanista": 23,
    "Jaylen Nowlin": 24,
    "Jaylen Palmer": 24,
    "Jayln Pinder": 17,
    "Jayson Bass": 19,
    "Jayvien Sandridge": 26,
    "Jazz Chisholm Jr.": 27,
    "Je'Von Ward": 25,
    "Jealmy Frias": 17,
    "Jean Cabrera": 23,
    "Jean Carlos Sio": 21,
    "Jean Joseph": 20,
    "Jean Munoz": 22,
    "Jean Perez": 23,
    "Jean Pinto": 24,
    "Jean Reyes": 22,
    "Jean Walters": 23,
    "JeanPierre Ortiz": 21,
    "Jeckferxon Hernandez": 22,
    "Jecsua Liborius": 20,
    "Jedixson Paez": 21,
    "Jefer Lista": 17,
    "Jeferson Figueroa": 24,
    "Jeferson Morales": 26,
    "Jeferson Quero": 23,
    "Jeff Criswell": 25,
    "Jeff Hoffman": 33,
    "Jeff McNeil": 33,
    "Jefferson Jean": 20,
    "Jefferson Moran": 21,
    "Jefferson Pena": 21,
    "Jefferson Rojas": 20,
    "Jefferson Valladares": 23,
    "Jefferson Vargas": 17,
    "Jeffrey Amparo": 20,
    "Jeffrey Mercedes": 20,
    "Jeffrey Springs": 33,
    "Jeffry Rosa": 20,
    "Jefrank Silva": 17,
    "Jefrey De Los Santos": 22,
    "Jefry Yan": 28,
    "Jehancarlos Mendez": 17,
    "Jeiker Gudino": 18,
    "Jeiki Beltran": 21,
    "Jeison Calvo": 19,
    "Jeison Lopez": 19,
    "Jeison Payano": 19,
    "Jeisson Cabrera": 26,
    "Jemone Nuel": 18,
    "Jeral Perez": 20,
    "Jeral Toledo": 22,
    "Jeral Vizcaino": 23,
    "Jeremiah Boyd": 24,
    "Jeremiah Estrada": 27,
    "Jeremiah Jenkins": 22,
    "Jeremy Almonte": 19,
    "Jeremy Ciriaco": 18,
    "Jeremy De La Rosa": 23,
    "Jeremy Gonzalez": 20,
    "Jeremy Lee": 23,
    "Jeremy Pena": 28,
    "Jeremy Pilon": 19,
    "Jeremy Reyes": 19,
    "Jeremy Rivas": 22,
    "Jeremy Rodriguez": 18,
    "Jeremy Wu-Yelland": 26,
    "Jermaine Maricuto": 19,
    "Jermayne Verdu": 18,
    "Jerming Rosario": 23,
    "Jeron Williams": 24,
    "Jervis Alfaro": 21,
    "Jeshua Mendez": 17,
    "Jesmaylin Arias": 18,
    "Jessada Brown": 22,
    "Jesse Bergin": 25,
    "Jesse Hahn": 35,
    "Jesse Wainscott": 25,
    "Jesus  Palacios": 20,
    "Jesus Abreu": 19,
    "Jesus Alexander": 19,
    "Jesus Anton": 19,
    "Jesus Baez": 20,
    "Jesus Bastidas": 26,
    "Jesus Bello": 17,
    "Jesus Broca": 21,
    "Jesus Bugarin": 23,
    "Jesus Carrera": 20,
    "Jesus Castillo": 21,
    "Jesus Castro": 20,
    "Jesus Colina": 20,
    "Jesus Cruz": 30,
    "Jesus Delgado": 21,
    "Jesus Escobar": 19,
    "Jesus Fernandez": 19,
    "Jesus Flores": 20,
    "Jesus Freitez": 19,
    "Jesus Gamez": 22,
    "Jesus Guerrero": 18,
    "Jesus Hernandez": 21,
    "Jesus Lafalaise": 20,
    "Jesus Liranzo": 30,
    "Jesus Lizardo": 18,
    "Jesus Lopez": 20,
    "Jesus Lugo": 18,
    "Jesus Luna": 24,
    "Jesus Luzardo": 28,
    "Jesus Made": 18,
    "Jesus Mendez": 20,
    "Jesus Morales": 17,
    "Jesus Oliveira": 20,
    "Jesus Ordonez": 25,
    "Jesus Ortega": 17,
    "Jesus Perez": 17,
    "Jesus Pinto": 18,
    "Jesus Rios": 23,
    "Jesus Rodriguez": 23,
    "Jesus Sanchez": 28,
    "Jesus Superlano": 19,
    "Jesus Tillero": 19,
    "Jesus Travieso": 18,
    "Jesus Valdez": 27,
    "Jesus Villaflor": 17,
    "Jeter Martinez": 19,
    "Jett Williams": 22,
    "Jeury Espinal": 18,
    "Jeury Ramirez": 17,
    "Jeyderson Mora": 20,
    "Jeyson Moya": 18,
    "Jezler Baules": 19,
    "Jhancarlos Lara": 22,
    "Jharold Clemente": 22,
    "Jheremy Vargas": 22,
    "Jhoan De La Cruz": 17,
    "Jhoan Duran": 28,
    "Jhoan Peguero": 19,
    "Jhoanjel Saez": 18,
    "Jhocsuanth Vargas": 18,
    "Jhojan Downer": 18,
    "Jholbran Herder": 20,
    "Jhomnardo Reyes": 17,
    "Jhon Cabral": 19,
    "Jhon Diaz": 22,
    "Jhon GIl": 17,
    "Jhon Lucena": 17,
    "Jhon Medina": 19,
    "Jhon Reyes": 21,
    "Jhon Rosario": 20,
    "Jhon Simon": 17,
    "Jhonael Cuello": 17,
    "Jhonathan Diaz": 28,
    "Jhonayker Ugarte": 18,
    "Jhonger Ochoa": 17,
    "Jhoniel Serrano": 21,
    "Jhonly Taveras": 20,
    "Jhonny Chaparro": 18,
    "Jhonny Jimenez": 21,
    "Jhonny Level": 18,
    "Jhonny Osta": 17,
    "Jhonny Pereda": 29,
    "Jhonny Severino": 20,
    "Jhorman Bravo": 17,
    "Jhorvic Abreus": 19,
    "Jhosman Theran": 17,
    "Jhosmer Alvarez": 24,
    "Jhosmmel Zue": 21,
    "Jhoster Baez": 20,
    "Jhostin Genao": 17,
    "Jhostynxon Garcia": 23,
    "Jim Jarvis": 24,
    "Jimmy Burnette": 26,
    "Jimmy Crooks": 23,
    "Jimmy Endersby": 27,
    "Jimmy Herron": 28,
    "Jimmy Joyce": 26,
    "Jimmy Kingsbury": 26,
    "Jimmy Obertop": 25,
    "Jimmy Reyes": 19,
    "Jimmy Romano": 22,
    "Jirvin Morillo": 18,
    "Jjam Alvarez": 19,
    "Jo Adell": 26,
    "Jo Oyama": 24,
    "JoJo Jackson": 22,
    "JoJo Romero": 29,
    "Joan Delgado": 20,
    "Joan Gutierrez": 19,
    "Joan Ogando": 21,
    "Joander Suarez": 25,
    "Joangel Gonzalez": 20,
    "Joaquin Arias Jr.": 18,
    "Joaquin Tejada": 21,
    "Joc Pederson": 33,
    "Joe Adametz": 25,
    "Joe Boyle": 26,
    "Joe Delossantos": 24,
    "Joe Elbis": 21,
    "Joe Glassey": 23,
    "Joe Jacques": 30,
    "Joe Lampe": 24,
    "Joe Mack": 23,
    "Joe Miller": 25,
    "Joe Musgrove": 33,
    "Joe Nahas": 25,
    "Joe Naranjo": 24,
    "Joe Olsavsky": 23,
    "Joe Perez": 25,
    "Joe Redfield": 23,
    "Joe Rock": 24,
    "Joe Ryan": 29,
    "Joe Vetrano": 23,
    "Joe Vogatsky": 23,
    "Joe Whitman": 23,
    "Joel Canizalez": 22,
    "Joel Cesar": 29,
    "Joel Diaz": 21,
    "Joel Dragoo": 22,
    "Joel Garcia": 20,
    "Joel Heredia": 21,
    "Joel Hurtado": 24,
    "Joel Ibarra": 22,
    "Joel Lara": 18,
    "Joel Mendez": 22,
    "Joel Peguero": 28,
    "Joel Sierra": 23,
    "Joel Valdez": 25,
    "Joelvis Perez": 20,
    "Joendry Vargas": 19,
    "Joey Cantillo": 26,
    "Joey Danielson": 24,
    "Joey Gartrell": 21,
    "Joey Gerber": 28,
    "Joey Mancini": 25,
    "Joey Oakie": 19,
    "Joey Ortiz": 27,
    "Joey Volini": 22,
    "Jogly Garcia": 21,
    "Johan Contreras": 20,
    "Johan De Los Santos": 16,
    "Johan Fernandez": 18,
    "Johan Machado": 17,
    "Johan Macias": 22,
    "Johan Moreno": 22,
    "Johan Otanez": 23,
    "Johan Oviedo": 27,
    "Johan Rodriguez": 17,
    "Johan Simon": 23,
    "Johanderson Tarazona": 17,
    "Johanfran Garcia": 20,
    "Johanse Gomez": 17,
    "John Bay": 24,
    "John Cristino": 25,
    "John Cruz": 19,
    "John Estevez": 19,
    "John Garcia": 24,
    "John Gil": 19,
    "John Holobetz": 22,
    "John Klein": 23,
    "John Lopez": 19,
    "John McMillon": 27,
    "John Means": 32,
    "John Michael Bertrand": 27,
    "John Michael Faile": 25,
    "John Peck": 22,
    "John Rhodes": 24,
    "John Rooney": 28,
    "John Santana": 19,
    "John Spikerman": 22,
    "John Stankiewicz": 26,
    "John Taylor": 24,
    "John Valle": 20,
    "John West": 23,
    "John Wimmer": 20,
    "Johnathan Harmon": 24,
    "Johnathan Lavallee": 25,
    "Johnathan Rodriguez": 25,
    "Johnathan Rogers": 20,
    "Johnathon Thomas": 25,
    "Johnfrank Salazar": 21,
    "Johnny Ascanio": 21,
    "Johnny King": 19,
    "Johnny Olmstead": 24,
    "Johnny Tincher": 23,
    "Johzan Oquendo": 24,
    "Jojo Ingrassia": 22,
    "Jommy Hernandez": 19,
    "Jon Berti": 35,
    "Jon Gray": 34,
    "Jon Jon Gazdar": 23,
    "Jon Olsen": 28,
    "Jonah Advincula": 24,
    "Jonah Bride": 29,
    "Jonah Cox": 23,
    "Jonah Hurney": 25,
    "Jonah Tong": 22,
    "Jonalbert Rumbol": 26,
    "Jonatan Bernal": 23,
    "Jonathan Aranda": 27,
    "Jonathan Bowlan": 28,
    "Jonathan Brand": 25,
    "Jonathan Clark": 25,
    "Jonathan Hogart": 23,
    "Jonathan Hughes": 28,
    "Jonathan India": 29,
    "Jonathan Jimenez": 21,
    "Jonathan Linares": 20,
    "Jonathan Martinez": 18,
    "Jonathan Mejia": 20,
    "Jonathan Moya": 18,
    "Jonathan Ornelas": 25,
    "Jonathan Pintaro": 27,
    "Jonathan Rangel": 18,
    "Jonathan Rivero": 19,
    "Jonathan Russell": 20,
    "Jonathan Santucci": 22,
    "Jonathan Todd": 23,
    "Jonathan Vastine": 22,
    "Jonathon Long": 24,
    "Jonawel Valdez": 21,
    "Joneiker Arellano": 20,
    "Jonierbis Garces": 17,
    "Jonnhan Sanchez": 18,
    "Jonny Butler": 26,
    "Jonny Cuevas": 24,
    "Jonny DeLuca": 27,
    "Jonny Farmelo": 21,
    "Jorbit Vivas": 24,
    "Jord David Diaz": 17,
    "Jordan Balazovic": 26,
    "Jordan Beck": 24,
    "Jordan Dissin": 23,
    "Jordan Geber": 25,
    "Jordan Groshans": 25,
    "Jordan Henriquez": 21,
    "Jordan Holloway": 29,
    "Jordan Jackson": 26,
    "Jordan Lawlar": 23,
    "Jordan Marks": 26,
    "Jordan Mikel": 26,
    "Jordan Nwogu": 26,
    "Jordan Ouanyou": 17,
    "Jordan Romano": 32,
    "Jordan Sanchez": 19,
    "Jordan Sprinkle": 24,
    "Jordan Thompson": 23,
    "Jordan Valenzuela": 20,
    "Jordan Viars": 21,
    "Jordan Walker": 23,
    "Jordan Westburg": 26,
    "Jordan Woods": 21,
    "Jordany Chirinos": 19,
    "Jordany Ventura": 24,
    "Jordarlin Mendoza": 21,
    "Jordy Arias": 19,
    "Jordy Vargas": 21,
    "Jordyn Adams": 25,
    "Jorel Ortega": 24,
    "Jorge Barrosa": 24,
    "Jorge Benitez": 26,
    "Jorge Burgos": 22,
    "Jorge Corona": 24,
    "Jorge De Leon": 22,
    "Jorge Drullard": 17,
    "Jorge Gonzalez": 22,
    "Jorge Hernandez": 19,
    "Jorge Herrera": 22,
    "Jorge Juan": 26,
    "Jorge Julio": 18,
    "Jorge Lara": 19,
    "Jorge Marcheco": 22,
    "Jorge Mateo": 30,
    "Jorge Mercedes": 24,
    "Jorge Minyety": 22,
    "Jorge Polanco": 32,
    "Jorge Quintana": 18,
    "Jorge Ramirez": 19,
    "Jorge Rodriguez": 19,
    "Jorge Ruiz": 21,
    "Jorgelys Mota": 20,
    "Jormy Nivar": 22,
    "Josbel Garcia": 21,
    "Josdanner Suarez": 20,
    "Jose Acuna": 22,
    "Jose Adames": 32,
    "Jose Alpuria": 20,
    "Jose Altuve": 35,
    "Jose Alvarado": 30,
    "Jose Anderson": 18,
    "Jose Astudillo": 21,
    "Jose Atencio": 22,
    "Jose Aular": 21,
    "Jose Barrios": 17,
    "Jose Bello": 20,
    "Jose Bericoto": 18,
    "Jose Berrios": 31,
    "Jose Butto": 27,
    "Jose Caballero": 29,
    "Jose Cabrera": 23,
    "Jose Caguana": 23,
    "Jose Camacho": 18,
    "Jose Carrillo": 18,
    "Jose Castillo": 29,
    "Jose Castro": 18,
    "Jose Cerice": 20,
    "Jose Chirinos": 20,
    "Jose Colmenares": 23,
    "Jose Contreras": 20,
    "Jose Cordoba": 22,
    "Jose Cordova": 25,
    "Jose Corniell": 22,
    "Jose D. Hernandez": 22,
    "Jose Davila": 22,
    "Jose De Jesus": 20,
    "Jose De La Cruz": 23,
    "Jose Devers": 25,
    "Jose Dickson": 18,
    "Jose Dicochea": 24,
    "Jose Escobar": 20,
    "Jose Espada": 28,
    "Jose Familia": 17,
    "Jose Feliz": 19,
    "Jose Fermin": 23,
    "Jose Fernandez": 21,
    "Jose Ferrer": 25,
    "Jose Fleury": 23,
    "Jose Flores": 17,
    "Jose Franco": 24,
    "Jose Garces": 21,
    "Jose Geraldo": 25,
    "Jose Gerardo": 20,
    "Jose Gonzalez": 20,
    "Jose Guedez": 23,
    "Jose Guerra": 19,
    "Jose Guevara": 20,
    "Jose Gutierrez": 22,
    "Jose Herrera": 28,
    "Jose Iglesias": 36,
    "Jose Lavagnino": 18,
    "Jose Ledesma": 22,
    "Jose Luis Reyes": 22,
    "Jose M. Mendoza": 17,
    "Jose M. Rodriguez": 21,
    "Jose Marcano": 18,
    "Jose Marte": 28,
    "Jose Martinez": 17,
    "Jose Mejia": 19,
    "Jose Meneses": 20,
    "Jose Meza": 22,
    "Jose Monserrate": 20,
    "Jose Montero": 21,
    "Jose Montilla": 17,
    "Jose Monzon": 19,
    "Jose Nova": 23,
    "Jose Olivares": 22,
    "Jose Ortega": 20,
    "Jose Ortiz": 20,
    "Jose Padilla": 17,
    "Jose Paulino": 19,
    "Jose Pena": 16,
    "Jose Pena Jr.": 21,
    "Jose Peralta": 17,
    "Jose Perdomo": 18,
    "Jose Perez": 20,
    "Jose Pinto": 22,
    "Jose Pirela": 19,
    "Jose Pitre": 17,
    "Jose Quintana": 37,
    "Jose Ramirez": 33,
    "Jose Ramos": 22,
    "Jose Regalado": 23,
    "Jose Rengel": 19,
    "Jose Riera": 17,
    "Jose Rivas": 17,
    "Jose Rivera": 20,
    "Jose Rodriguez": 24,
    "Jose Rojas": 32,
    "Jose Romero": 20,
    "Jose Sabino": 18,
    "Jose Salas": 22,
    "Jose Sanabria": 22,
    "Jose Santana": 17,
    "Jose Sequera": 18,
    "Jose Serrano": 21,
    "Jose Siri": 30,
    "Jose Soriano": 27,
    "Jose Suarez": 20,
    "Jose T. Perez": 21,
    "Jose Torres": 25,
    "Jose Tovar": 19,
    "Jose Trevino": 32,
    "Jose Urbina": 19,
    "Jose Varela": 20,
    "Jose Vasquez": 20,
    "Jose Verdugo": 17,
    "Jose Zerpa": 20,
    "Joseilyn Gonzalez": 23,
    "Joseph Herrera": 19,
    "Joseph King": 24,
    "Joseph Menefee": 25,
    "Joseph Montalvo": 23,
    "Joseph Rodriguez": 22,
    "Joseph Sequera": 19,
    "Joseph Sullivan": 22,
    "Joseph Tailor": 19,
    "Joseph Yabbour": 21,
    "Josh Adamczewski": 20,
    "Josh Bell": 33,
    "Josh Blum": 22,
    "Josh Bortka": 25,
    "Josh Bostick": 23,
    "Josh Breaux": 27,
    "Josh Caron": 21,
    "Josh Crouch": 26,
    "Josh Ekness": 23,
    "Josh Grosz": 22,
    "Josh Hader": 31,
    "Josh Hansell": 23,
    "Josh Harlow": 24,
    "Josh Hartle": 22,
    "Josh Hatcher": 26,
    "Josh Hejka": 28,
    "Josh Hogue": 21,
    "Josh Hood": 24,
    "Josh Jung": 27,
    "Josh Kasevich": 24,
    "Josh Knoth": 18,
    "Josh Kross": 22,
    "Josh Lowe": 27,
    "Josh Maciejewski": 29,
    "Josh Mallitz": 23,
    "Josh Mollerus": 25,
    "Josh Moylan": 22,
    "Josh Naylor": 28,
    "Josh Owens": 18,
    "Josh Randall": 22,
    "Josh Rivera": 24,
    "Josh Sanders": 23,
    "Josh Simpson": 27,
    "Josh Smith": 28,
    "Josh Springer": 19,
    "Josh Stephan": 23,
    "Josh Tate": 21,
    "Josh Tiedemann": 21,
    "Josh Timmerman": 22,
    "Josh Trentadue": 23,
    "Josh Walker": 30,
    "Josh White": 24,
    "Josh Wolf": 24,
    "Josh Zamora": 26,
    "Joshua Baez": 22,
    "Joshua Cornielly": 24,
    "Joshua Fermin": 16,
    "Joshua Francis": 18,
    "Joshua Kuroda-Grauer": 22,
    "Joshua Liranzo": 18,
    "Joshua Loeschorn": 25,
    "Joshua Mears": 24,
    "Joshua Quezada": 21,
    "Josi Novas": 20,
    "Josiah Gray": 28,
    "Josiah Ragsdale": 21,
    "Josiah Romeo": 19,
    "Josias Ramirez": 19,
    "Josmir Reyes": 18,
    "Josnaider Orellana": 20,
    "Josnier Parra": 23,
    "Jostin Florentino": 20,
    "Jostin Ogando": 17,
    "Josuar Gonzalez": 18,
    "Josue Arias": 20,
    "Josue Briceno": 21,
    "Josue Brito": 18,
    "Josue De Paula": 20,
    "Josue Demey": 18,
    "Josue Gonzalez": 21,
    "Josue Lopez": 23,
    "Josueth Quinonez": 18,
    "Joswa Lugo": 18,
    "José Caballero": 28,
    "José De León": 32,
    "Jovi Galvez": 20,
    "Joyner Perez": 17,
    "Juan Alva": 19,
    "Juan Alvarez": 19,
    "Juan Amarante": 21,
    "Juan Arnaud": 22,
    "Juan Baez": 20,
    "Juan Bello": 21,
    "Juan Benjamin": 22,
    "Juan Brima": 17,
    "Juan Brito": 23,
    "Juan Brown": 17,
    "Juan Burgos": 25,
    "Juan Cabada": 17,
    "Juan Carela": 22,
    "Juan Caricipe": 17,
    "Juan Castillo": 22,
    "Juan Cazarez": 19,
    "Juan Chacon": 22,
    "Juan Colorado": 18,
    "Juan Corniel": 22,
    "Juan Cota": 20,
    "Juan Cruz": 21,
    "Juan De La Cruz": 20,
    "Juan De Los Santos": 23,
    "Juan Elejandro": 17,
    "Juan Espinal": 18,
    "Juan Flores": 19,
    "Juan Fraide": 19,
    "Juan Garcia": 17,
    "Juan Gonzalez": 24,
    "Juan Guerrero": 23,
    "Juan Henriquez": 19,
    "Juan Hernandez": 19,
    "Juan Macero": 17,
    "Juan Martinez": 18,
    "Juan Mateo": 18,
    "Juan Matheus": 21,
    "Juan Mendez": 26,
    "Juan Mercedes": 25,
    "Juan Monso": 18,
    "Juan Montero": 23,
    "Juan Morillo": 26,
    "Juan Nunez": 24,
    "Juan Obispo": 19,
    "Juan Ortega": 19,
    "Juan Ortuno": 18,
    "Juan Pablo Cabrera": 18,
    "Juan Perez": 20,
    "Juan Rasquin": 19,
    "Juan Reynoso": 21,
    "Juan Rojas": 17,
    "Juan Rosas": 19,
    "Juan Rujano": 17,
    "Juan Salas": 22,
    "Juan Sanchez": 23,
    "Juan Severino": 21,
    "Juan Sierra": 19,
    "Juan Soto": 27,
    "Juan Sulbaran": 19,
    "Juan Tomas": 17,
    "Juan Torres": 17,
    "Juan Valera": 19,
    "Juan Villavicencio": 20,
    "Juanfel Peguero": 20,
    "Juanmi Vasquez": 21,
    "Juarlin Soto": 18,
    "Juaron Watts-Brown": 23,
    "Jud Fabian": 24,
    "Jude Warwick": 19,
    "Julian Aguiar": 23,
    "Julian Bosnic": 25,
    "Julian Brock": 24,
    "Julian Fernandez": 29,
    "Julian Garcia": 30,
    "Julio  Marte": 21,
    "Julio Acosta": 17,
    "Julio Bonilla": 24,
    "Julio Carreras": 25,
    "Julio E. Rodriguez": 28,
    "Julio Henriquez": 20,
    "Julio Mendez": 20,
    "Julio Ortiz": 24,
    "Julio Rodriguez": 25,
    "Julio Rosario": 22,
    "Julio Zapata": 22,
    "Julio Zayas": 19,
    "Jun-Seok Shim": 21,
    "Juneiker Caceres": 18,
    "Jung Hoo Lee": 27,
    "Junior Aybar": 18,
    "Junior Caminero": 22,
    "Junior Castillo": 17,
    "Junior Ciprian": 20,
    "Junior Fernandez": 28,
    "Junior Flores": 23,
    "Junior Franco": 22,
    "Junior Garcia": 19,
    "Junior Perez": 23,
    "Junior Sanchez": 19,
    "Junior Santos": 23,
    "Junior Suriel": 16,
    "Junior Tilien": 22,
    "Junior William": 25,
    "Jurdrick Profar": 18,
    "Jurickson Profar": 32,
    "Jurrangelo Cijntje": 22,
    "Justice Bigbie": 26,
    "Justin Armbruester": 26,
    "Justin Barry": 18,
    "Justin Boyd": 24,
    "Justin Capellan": 18,
    "Justin Chambers": 19,
    "Justin Connell": 26,
    "Justin Crawford": 22,
    "Justin DeCriscio": 22,
    "Justin Dean": 28,
    "Justin Foscue": 26,
    "Justin Gonzales": 18,
    "Justin Hagenman": 28,
    "Justin Janas": 24,
    "Justin Jarvis": 25,
    "Justin Johnson": 25,
    "Justin Kelly": 26,
    "Justin King": 27,
    "Justin Lange": 23,
    "Justin Lawson": 24,
    "Justin Loer": 22,
    "Justin Long": 23,
    "Justin Lugo": 19,
    "Justin Meis": 25,
    "Justin Miknis": 24,
    "Justin Militello": 21,
    "Justin Ramirez": 20,
    "Justin Riemer": 23,
    "Justin Sanchez": 21,
    "Justin Sinibaldi": 23,
    "Justin Slaten": 28,
    "Justin Steele": 30,
    "Justin Sterner": 29,
    "Justin Storm": 23,
    "Justin Stransky": 22,
    "Justin Thomas": 21,
    "Justin Trimble": 22,
    "Justin Verlander": 42,
    "Justin Wishkoski": 24,
    "Justin Wrobleski": 25,
    "Justin Yeager": 27,
    "K.C. Hunt": 24,
    "Kade Bragg": 23,
    "Kade Kern": 23,
    "Kade Morris": 23,
    "Kade Snell": 22,
    "Kade Strowd": 27,
    "Kaden Hernandez": 17,
    "Kaden Hollow": 24,
    "Kaden Hopson": 24,
    "Kadil Rubio": 17,
    "Kaeden Kent": 21,
    "Kaelen Culpepper": 23,
    "Kahlil Watson": 22,
    "Kai Murphy": 24,
    "Kai Peterson": 22,
    "Kai Roberts": 24,
    "Kai Wynyard": 23,
    "Kai-Wei Teng": 26,
    "Kala'i Rosario": 22,
    "Kalae Harrison": 23,
    "Kale Emshoff": 27,
    "Kale Fountain": 19,
    "Kaleb Bowman": 28,
    "Kaleb Corbett": 23,
    "Kaleb Freeman": 22,
    "Kamdyn Perry": 19,
    "Kamren James": 25,
    "Kamuel Villar": 17,
    "Kane Kepley": 21,
    "Kannon Kemp": 20,
    "Karim Ayubi": 21,
    "Karl Kauffmann": 27,
    "Karniel Pratt": 20,
    "Karson Milbrandt": 21,
    "Karson Simas": 24,
    "Kasen Wells": 21,
    "Kash Mayfield": 20,
    "Kavares Tears": 22,
    "Kay-Lan Nicasia": 23,
    "Kayson Cunningham": 19,
    "Kazuma Okamoto": 29,
    "KeBryan Hayes": 29,
    "Keagan Gillies": 27,
    "Keaton Anthony": 24,
    "Kedaur Trujillo": 21,
    "Keduar Trujillo": 21,
    "Keegan Akin": 30,
    "Keegan Zinn": 20,
    "Keeler Morfe": 19,
    "Kegnnalex Seijas": 19,
    "Kehden Hettiger": 21,
    "Keiberg Camacaro": 18,
    "Keiner Delgado": 21,
    "Keith Jones II": 23,
    "Keiver Garcia": 18,
    "Keiverson Ramirez": 19,
    "Kellen Strahm": 28,
    "Kellon Lindsey": 19,
    "Kelly Austin": 24,
    "Kelvin Alcantara": 19,
    "Kelvin Bautista": 25,
    "Kelvin Caceres": 25,
    "Kelvin Diaz": 22,
    "Kelvin Hidalgo": 20,
    "Kelvin Ramirez": 24,
    "Kelvin Rosario": 18,
    "Kelvis Salcedo": 19,
    "Kemp Alderman": 22,
    "Kendal Meza": 19,
    "Kendall George": 21,
    "Kendall Simmons": 25,
    "Kendeglys Virguez": 21,
    "Kendrick Hernandez": 18,
    "Kendrick Herrera": 18,
    "Kendry Chirinos": 20,
    "Kendry Chourio": 18,
    "Kendry Martinez": 17,
    "Kendry Rojas": 23,
    "Kendy Richard": 20,
    "Kenedy Corona": 25,
    "Kenley Jansen": 38,
    "Kenly Hunter": 17,
    "Kenni Gomez": 20,
    "Kenny Castillo": 21,
    "Kenny Fenelon": 17,
    "Kenny Leiner": 23,
    "Kenny Piper": 26,
    "Kenny Serwa": 27,
    "Kenten Egbert": 23,
    "Kenya Huggins": 22,
    "Kenyi Perez": 23,
    "Kenyon Simmons": 18,
    "Kenyon Yovan": 27,
    "Keone Kela": 32,
    "Kerrington Cross": 23,
    "Kerry Carpenter": 28,
    "Kervin Castro": 26,
    "Kervin Pichardo": 23,
    "Keshawn Ogans": 23,
    "Ketel Marte": 32,
    "Kevin Abel": 26,
    "Kevin Alcantara": 23,
    "Kevin Alvarez": 17,
    "Kevin Bazzell": 22,
    "Kevin Bruggeman": 23,
    "Kevin Camacho": 20,
    "Kevin Davis": 26,
    "Kevin Dowdell": 25,
    "Kevin Dume": 20,
    "Kevin Ereu": 19,
    "Kevin Fitzer": 23,
    "Kevin Garcia": 17,
    "Kevin Gausman": 35,
    "Kevin Ginkel": 31,
    "Kevin Gowdy": 27,
    "Kevin Graham": 25,
    "Kevin Guerrero": 21,
    "Kevin Hacen": 19,
    "Kevin Kilpatrick Jr.": 24,
    "Kevin Kopps": 28,
    "Kevin Made": 22,
    "Kevin Maitan": 25,
    "Kevin McGonigle": 21,
    "Kevin Miranda": 26,
    "Kevin Morillo": 18,
    "Kevin Newman": 31,
    "Kevin Parada": 23,
    "Kevin Rivas": 22,
    "Kevin Robledo": 18,
    "Kevin Sim": 23,
    "Kevin Stevens": 27,
    "Kevin Tamburini": 19,
    "Kevin Valdez": 23,
    "Kevin Velasco": 19,
    "Kevin Verde": 19,
    "Kevin Villavicencio": 21,
    "Kevin Warunek": 22,
    "Kevyn Castillo": 20,
    "Keyber Rodriguez": 24,
    "Keyner Benitez": 19,
    "Keyner Martinez": 20,
    "Keyshawn Askew": 25,
    "Keythel Key": 21,
    "Khadim Diaw": 21,
    "Khal Stephen": 23,
    "Khristian Curtis": 23,
    "Kien Vu": 21,
    "Kiko Romero": 24,
    "Kleiber Olmedo": 20,
    "Kleimir Lemos": 20,
    "Kleiver Chauran": 19,
    "Klendy Leen": 18,
    "Kleyver Salazar": 19,
    "Kobe Kato": 26,
    "Kodai Senga": 32,
    "Kodey Shojinaga": 22,
    "Kodi Whitley": 30,
    "Kody Clemens": 29,
    "Kody Hoese": 27,
    "Kody Huff": 24,
    "Koen Moreno": 23,
    "Kohl Drake": 25,
    "Kohl Franklin": 25,
    "Kolby Johnson": 25,
    "Kole Myers": 24,
    "Kolton Curtis": 21,
    "Kolton Ingram": 28,
    "Konner Eaton": 22,
    "Konner Piotto": 27,
    "Konnor Griffin": 19,
    "Korbyn Dickerson": 21,
    "Korey Holland": 25,
    "Koyo Aoyagi": 31,
    "Kris Bubic": 28,
    "Krishan Ulacio": 17,
    "Kristian Campbell": 23,
    "Kristian Robinson": 24,
    "Kumar Rocker": 26,
    "Ky Bush": 24,
    "Kyle Amendt": 25,
    "Kyle Ayers": 22,
    "Kyle Backhus": 27,
    "Kyle Bischoff": 25,
    "Kyle Bradish": 29,
    "Kyle Brnovich": 27,
    "Kyle Carr": 23,
    "Kyle DeBarge": 21,
    "Kyle DeGroat": 19,
    "Kyle Dernedde": 24,
    "Kyle Farmer": 34,
    "Kyle Finnegan": 34,
    "Kyle Freeland": 32,
    "Kyle Harrison": 24,
    "Kyle Hart": 32,
    "Kyle Hayes": 27,
    "Kyle Henley": 20,
    "Kyle Hess": 26,
    "Kyle Hurt": 27,
    "Kyle Jones": 25,
    "Kyle Larsen": 22,
    "Kyle Lodise": 21,
    "Kyle Luckham": 25,
    "Kyle Manzardo": 25,
    "Kyle Nevin": 23,
    "Kyle Robinson": 21,
    "Kyle Roche": 23,
    "Kyle Schwarber": 32,
    "Kyle Scott": 23,
    "Kyle Sinzza": 18,
    "Kyle Stowers": 28,
    "Kyle Teel": 23,
    "Kyle Tucker": 29,
    "Kyle Tyler": 28,
    "Kyle Virbitsky": 26,
    "Kyle Walker": 22,
    "Kyle West": 22,
    "Kyle Whitten": 25,
    "Kyle Wright": 30,
    "Kyler Fedko": 25,
    "Kyren Paris": 24,
    "L.P. Langevin": 21,
    "LJ McDonough": 25,
    "Lael Lockhart": 27,
    "Lamar King Jr.": 21,
    "Lance McCullers Jr.": 32,
    "Landen Maroudis": 20,
    "Landen Roupp": 27,
    "Landon Beidelschies": 21,
    "Landon Ginn": 23,
    "Landon Harper": 24,
    "Landon Knack": 28,
    "Landon Marceaux": 25,
    "Landon Sims": 24,
    "Landon Tomkins": 25,
    "Landyn Vidourek": 21,
    "Lane Ramsey": 28,
    "Langston Burkett": 20,
    "Larry Martinez": 19,
    "Larry Suero": 17,
    "Lars Nootbaar": 28,
    "Larson Kindreich": 26,
    "Lawrence Butler": 25,
    "Layonel Ovalles": 22,
    "Lazaro Estrada": 26,
    "Lazaro Montes": 21,
    "Leandro Alsinois": 20,
    "Leandro Arias": 20,
    "Leandro Hernandez": 23,
    "Leandro Lopez": 23,
    "Leandro Morgado": 18,
    "Leandro Pineda": 23,
    "Leandro Romero": 18,
    "Leandy Mella": 18,
    "Lebarron Johnson Jr.": 23,
    "Leider Padilla": 18,
    "Leiker Figueroa": 20,
    "Leni Done": 18,
    "Lenny Torres Jr.": 24,
    "Lenyn Sosa": 26,
    "Leo Balcazar": 21,
    "Leo De Vries": 18,
    "Leo Rivas": 27,
    "Leodalis De Vries": 19,
    "Leodarlyn Colon": 20,
    "Leomar Rosario": 22,
    "Leon Hunter Jr.": 28,
    "Leonard Garcia": 21,
    "Leonard Rijo": 17,
    "Leonardo Bernal": 21,
    "Leonardo Carpio": 17,
    "Leonardo Pestana": 26,
    "Leonardo Pineda": 18,
    "Leonardo Rondon": 18,
    "Leonardo Taveras": 26,
    "Leonel Espinoza": 22,
    "Leonel Sequera": 19,
    "Leonel Vivas": 18,
    "Lester Suarez": 16,
    "Leudy Arache": 17,
    "Leuris Portorreal": 19,
    "Levi Jordan": 29,
    "Levi Sterling": 18,
    "Levi Stoudt": 27,
    "Levi Wells": 23,
    "Lewis German": 17,
    "Lewis Sifontes": 19,
    "Liam Doyle": 21,
    "Liam Hendriks": 36,
    "Liam Norris": 23,
    "Liam Rocha": 23,
    "Liam Simon": 24,
    "Liam Sullivan": 23,
    "Liberts Aponte": 17,
    "Limanol Payero": 17,
    "Liomar Martinez": 20,
    "Liordanys Menendez": 17,
    "Liosward Marin": 19,
    "Lisandro Sanchez": 17,
    "Lisbel Diaz": 19,
    "Lisnerkin Lantigua": 20,
    "Livan Reinoso": 26,
    "Livan Soto": 25,
    "Lizandro Espinoza": 22,
    "Lizandro Rodriguez": 22,
    "Lluveres Severino": 21,
    "Logan Allen": 27,
    "Logan Berrier": 24,
    "Logan Boyer": 27,
    "Logan Braunschweig": 22,
    "Logan Britt": 24,
    "Logan Cerny": 25,
    "Logan Clayton": 25,
    "Logan Davidson": 27,
    "Logan Dawson": 19,
    "Logan Evans": 24,
    "Logan Forsythe": 21,
    "Logan Gilbert": 28,
    "Logan Gillaspie": 28,
    "Logan Henderson": 23,
    "Logan Martin": 23,
    "Logan Mercado": 23,
    "Logan OHoppe": 25,
    "Logan Porter": 29,
    "Logan Poteet": 21,
    "Logan Rinehart": 26,
    "Logan Samuels": 23,
    "Logan Tabeling": 23,
    "Logan Tanner": 24,
    "Logan VanWey": 26,
    "Logan Wagner": 21,
    "Logan Webb": 29,
    "Logan Whitaker": 25,
    "Logan Workman": 26,
    "Logun Clark": 22,
    "Lonnie White Jr.": 22,
    "Lorenzo Encarnacion": 23,
    "Lorenzo Meola": 21,
    "Lou Albrecht": 23,
    "Louis Andujar": 17,
    "Louis Varland": 28,
    "Lourdes Gurriel Jr.": 32,
    "LuJames Groover": 23,
    "Luarbert Arias": 24,
    "Luca Tresh": 25,
    "Lucas Braun": 23,
    "Lucas Elissalt": 20,
    "Lucas Giolito": 31,
    "Lucas Gordon": 23,
    "Lucas Kelly": 21,
    "Lucas Knowles": 27,
    "Lucas Ramirez": 19,
    "Lucas Spence": 22,
    "Lucas Wepf": 25,
    "Luciano Romero": 20,
    "Ludwing Espinoza": 19,
    "Luifer Romero": 20,
    "Luinder Avila": 23,
    "Luis A. Reyes": 21,
    "Luis Abreu": 17,
    "Luis Aguilar": 21,
    "Luis Aguilera": 18,
    "Luis Almeyda": 19,
    "Luis Alvarez": 22,
    "Luis Amoroso": 24,
    "Luis Angel Rodriguez": 25,
    "Luis Arana": 17,
    "Luis Arestigueta": 19,
    "Luis Arias": 19,
    "Luis Ariza": 21,
    "Luis Arraez": 28,
    "Luis Aular": 17,
    "Luis Avila": 22,
    "Luis Baez": 21,
    "Luis Beltran": 21,
    "Luis Caicuto": 22,
    "Luis Carias": 20,
    "Luis Carrasco": 22,
    "Luis Castillo": 33,
    "Luis Cesar": 21,
    "Luis Chevalier": 23,
    "Luis Cohen": 22,
    "Luis Contreras": 29,
    "Luis Corobo": 18,
    "Luis Cova": 18,
    "Luis Cruz": 17,
    "Luis Cuevas": 17,
    "Luis Curvelo": 24,
    "Luis De La Cruz": 18,
    "Luis De La Torre": 21,
    "Luis De Leon": 18,
    "Luis De Los Santos": 27,
    "Luis Durango": 22,
    "Luis Encarnacion": 22,
    "Luis Escudero": 19,
    "Luis F. Castillo": 30,
    "Luis F. Ortiz": 28,
    "Luis Flores": 21,
    "Luis Fragoza": 18,
    "Luis Freitez": 22,
    "Luis Frias": 20,
    "Luis Galan": 16,
    "Luis Garcia": 29,
    "Luis Garcia Jr.": 25,
    "Luis Gastelum": 23,
    "Luis German": 23,
    "Luis Gil": 27,
    "Luis Gonzalez": 33,
    "Luis Guanipa": 19,
    "Luis Guerrero": 24,
    "Luis Guevara": 19,
    "Luis Guillorme": 30,
    "Luis Gutierrez": 21,
    "Luis Hernandez": 22,
    "Luis Lameda": 19,
    "Luis Lara": 20,
    "Luis Leon": 17,
    "Luis Leones": 22,
    "Luis Luna": 17,
    "Luis Maldonado": 17,
    "Luis Maracara": 17,
    "Luis Marinez": 23,
    "Luis Marquez": 19,
    "Luis Martinez-Gomez": 22,
    "Luis Mendez": 22,
    "Luis Merejo": 19,
    "Luis Mey": 24,
    "Luis Meza": 20,
    "Luis Mieses": 25,
    "Luis Morales": 23,
    "Luis Morejon": 17,
    "Luis Morellis": 21,
    "Luis Moreno": 26,
    "Luis Ortiz": 27,
    "Luis Pacheco": 26,
    "Luis Palacios": 24,
    "Luis Parababire": 19,
    "Luis Pena": 19,
    "Luis Perales": 22,
    "Luis Peralta": 24,
    "Luis Pimentel": 21,
    "Luis Pineda": 23,
    "Luis Pino": 21,
    "Luis Puello": 19,
    "Luis Quesada": 20,
    "Luis Quinones": 27,
    "Luis R. Rodriguez": 22,
    "Luis Ramirez": 23,
    "Luis Ravelo": 21,
    "Luis Rengifo": 28,
    "Luis Reyes": 21,
    "Luis Rives": 20,
    "Luis Robert Jr.": 28,
    "Luis Rodriguez": 20,
    "Luis Rujano": 22,
    "Luis Sanchez": 21,
    "Luis Santos": 17,
    "Luis Serna": 20,
    "Luis Severino": 31,
    "Luis Steven King": 17,
    "Luis Suisbel": 22,
    "Luis Tejeda": 20,
    "Luis Torrens": 29,
    "Luis Torres": 20,
    "Luis Valdez": 25,
    "Luis Vargas": 23,
    "Luis Vazquez": 25,
    "Luis Velasquez": 22,
    "Luis Verdugo": 24,
    "Luis Vázquez": 25,
    "Luisangel Acuna": 23,
    "Luiyin Alastre": 19,
    "Luke Adams": 21,
    "Luke Albright": 25,
    "Luke Anderson": 26,
    "Luke Bell": 24,
    "Luke Cantwell": 22,
    "Luke Craig": 23,
    "Luke Davis": 22,
    "Luke Dickerson": 19,
    "Luke Fox": 23,
    "Luke Gabrysh": 22,
    "Luke Gold": 24,
    "Luke Hanson": 21,
    "Luke Hayden": 22,
    "Luke Hill": 21,
    "Luke Holman": 22,
    "Luke Jewett": 22,
    "Luke Johnson": 23,
    "Luke Keaschall": 23,
    "Luke Lashutka": 23,
    "Luke Little": 24,
    "Luke Maile": 34,
    "Luke Mann": 25,
    "Luke Murphy": 25,
    "Luke Napleton": 23,
    "Luke Nowak": 22,
    "Luke Ritter": 28,
    "Luke Russo": 24,
    "Luke Savage": 23,
    "Luke Scherrer": 20,
    "Luke Shliger": 23,
    "Luke Sinnard": 22,
    "Luke Stevenson": 20,
    "Luke Stofel": 23,
    "Luke Taggart": 27,
    "Luke Waddell": 26,
    "Luke Weaver": 32,
    "Luke Williams": 28,
    "Luke Young": 23,
    "Lyle Lin": 28,
    "Lyle Miller-Green": 24,
    "M.D. Johnson": 27,
    "Mac Guscette": 23,
    "Mac Horvath": 23,
    "Mac McCroskey": 25,
    "MacKenzie Gore": 26,
    "Maddox Latta": 22,
    "Maddux Bruns": 23,
    "Maddux Houghton": 26,
    "Madinson Frias": 20,
    "Madison Jeffrey": 25,
    "Magdiel Cotto": 23,
    "Magnus Ellerts": 24,
    "Maick Collado": 22,
    "Maicol Reyes": 20,
    "Maikel Garcia": 25,
    "Maikel Hernandez": 22,
    "Maikel Miralles": 20,
    "Maikol Escotto": 23,
    "Maikol Hernandez": 21,
    "Maikol Orozco": 19,
    "Maikol Rodriguez": 18,
    "Maikol Tovar": 17,
    "Mailon Felix": 25,
    "Mairoshendrick Martinus": 20,
    "Malcolm Moore": 21,
    "Malcom Nunez": 24,
    "Malvin Fernandez": 16,
    "Malvin Valdez": 21,
    "Mani Cedeno": 16,
    "Manni Ramirez": 18,
    "Manny Machado": 33,
    "Manolfi Jimenez": 20,
    "Manuel Almeida": 17,
    "Manuel Baez": 20,
    "Manuel Beltre": 21,
    "Manuel Cabrera": 19,
    "Manuel Campos": 17,
    "Manuel Castro": 23,
    "Manuel Davila": 17,
    "Manuel De Cesare": 18,
    "Manuel Dos Passos": 18,
    "Manuel Genao": 19,
    "Manuel German": 20,
    "Manuel Medina": 23,
    "Manuel Mercedes": 22,
    "Manuel Olivares": 23,
    "Manuel Osorio": 19,
    "Manuel Palencia": 22,
    "Manuel Pena": 21,
    "Manuel Perez": 19,
    "Manuel Rodriguez": 19,
    "Manuel Urias": 24,
    "Manuel Vasquez": 17,
    "Manuel Veloz": 24,
    "Marc Church": 24,
    "Marc Davis": 25,
    "Marcell Ozuna": 35,
    "Marcelo Alcala": 19,
    "Marcelo Mayer": 23,
    "Marcelo Perez": 25,
    "Marcelo Valladares": 20,
    "Marco Argudin": 19,
    "Marco Barrios": 19,
    "Marco Corcho": 20,
    "Marco Dinges": 21,
    "Marco Jimenez": 25,
    "Marco Luciano": 24,
    "Marco Patino": 20,
    "Marco Raya": 22,
    "Marco Vargas": 20,
    "Marco Vega": 20,
    "Marconi German": 17,
    "Marcos Belen": 18,
    "Marcos Castanon": 26,
    "Marcos Herrera": 20,
    "Marcos Terrero": 19,
    "Marcos Torres": 20,
    "Marcus Brown": 23,
    "Marcus Johnson": 24,
    "Marcus Lee Sang": 24,
    "Marcus Semien": 35,
    "Marcus Smith": 24,
    "Marek Houston": 21,
    "Mariano Salomon": 22,
    "Marino Santy": 23,
    "Mario Baez": 18,
    "Mario Camilletti": 26,
    "Mario Gomez": 22,
    "Mario Zabala": 23,
    "Mark Adamiak": 24,
    "Mark Canha": 36,
    "Mark Coley II": 24,
    "Mark Manfredi": 25,
    "Mark McLaughlin": 24,
    "Mark Vientos": 26,
    "Marlin Willis": 27,
    "Marlon Franco": 22,
    "Marlon Nieves": 20,
    "Marlon Quintero": 18,
    "Marques Johnson": 24,
    "Marquis Grissom Jr.": 23,
    "Marshall Toole": 22,
    "Martin Gonzalez": 20,
    "Martin Perez": 34,
    "Martin Tamara": 21,
    "Marty Gair": 21,
    "Marvin Alcantara": 20,
    "Marwin Rivero": 18,
    "Marwys Cabrera": 19,
    "Masataka Yoshida": 32,
    "Mason Adams": 24,
    "Mason Albright": 22,
    "Mason Auer": 24,
    "Mason Barnett": 24,
    "Mason Black": 25,
    "Mason Bolivar": 18,
    "Mason Burns": 23,
    "Mason Dinesen": 26,
    "Mason Erla": 27,
    "Mason Green": 26,
    "Mason Guerra": 22,
    "Mason Hickman": 26,
    "Mason Lytle": 24,
    "Mason Marriott": 22,
    "Mason McGwire": 20,
    "Mason Miller": 27,
    "Mason Molina": 21,
    "Mason Moore": 23,
    "Mason Neville": 21,
    "Mason Olson": 23,
    "Mason Pelio": 24,
    "Mason Vinyard": 26,
    "Mason White": 21,
    "Masyn Winn": 23,
    "Mat Nelson": 26,
    "Mat Olsen": 24,
    "Mathew Peters": 24,
    "Mathias LaCombe": 23,
    "Matt Ager": 22,
    "Matt Allan": 24,
    "Matt Brash": 27,
    "Matt Chapman": 32,
    "Matt Coutney": 25,
    "Matt Cronin": 27,
    "Matt Duffy": 22,
    "Matt Dunaway": 26,
    "Matt Fraizer": 27,
    "Matt Gabbert": 23,
    "Matt Gage": 32,
    "Matt Gorski": 27,
    "Matt Halbach": 22,
    "Matt Higgins": 25,
    "Matt Hogan": 25,
    "Matt Jachec": 23,
    "Matt Keating": 24,
    "Matt King": 22,
    "Matt Klein": 21,
    "Matt Koperniak": 27,
    "Matt Krook": 30,
    "Matt Kroon": 28,
    "Matt McLain": 26,
    "Matt McShane": 22,
    "Matt Merrill": 27,
    "Matt Mervis": 27,
    "Matt Mikulski": 26,
    "Matt O'Neill": 27,
    "Matt Olson": 31,
    "Matt Pushard": 27,
    "Matt Rudick": 26,
    "Matt Sauer": 26,
    "Matt Scannell": 23,
    "Matt Seelinger": 30,
    "Matt Shaw": 24,
    "Matt Stil": 24,
    "Matt Strahm": 34,
    "Matt Suggs": 25,
    "Matt Turner": 25,
    "Matt Wallner": 28,
    "Matt Wilkinson": 23,
    "Matthew Bollenbacher": 25,
    "Matthew Boyd": 34,
    "Matthew Ellis": 24,
    "Matthew Etzel": 23,
    "Matthew Ferrara": 18,
    "Matthew Liberatore": 26,
    "Matthew Linskey": 23,
    "Matthew Lugo": 24,
    "Matthew Miura": 21,
    "Matthew Moses": 17,
    "Matthew Wood": 24,
    "Maui Ahuna": 23,
    "Mauricio Colmenares": 21,
    "Mauricio Dubon": 31,
    "Mauricio Estrella": 21,
    "Mauricio Veliz": 22,
    "Maverick Handley": 27,
    "Mavis Graves": 21,
    "Max Alba": 25,
    "Max Anderson": 23,
    "Max Belyeu": 21,
    "Max Burt": 28,
    "Max Carlson": 23,
    "Max Clark": 21,
    "Max Durrington": 18,
    "Max Ferguson": 25,
    "Max Fried": 32,
    "Max Gieg": 24,
    "Max Holy": 22,
    "Max Martin": 21,
    "Max Meyer": 26,
    "Max Muncy": 23,
    "Max Rajcic": 23,
    "Max Roberts": 27,
    "Max Scherzer": 41,
    "Max Wagner": 23,
    "Max Williams": 20,
    "Maximo Acosta": 22,
    "Maximo Martinez": 21,
    "Maximus Martin": 21,
    "Maxton Martin": 20,
    "Maxwel Hernandez": 22,
    "Maxwell Romero Jr.": 24,
    "Maykel Coret": 17,
    "Maykel Minoso": 19,
    "Mayki De La Rosa": 17,
    "Maykol Fernandez": 17,
    "Maylerson Casanova": 18,
    "McCade Brown": 24,
    "McKinley Moore": 26,
    "Melkis Hernandez": 20,
    "Melvin Cuevas": 20,
    "Melvin Hernandez": 18,
    "Melvin Pineda": 21,
    "Melvin Rodriguez": 19,
    "Mendry Solano": 21,
    "Merlin Bido": 19,
    "Merphy Hernandez": 18,
    "Merrick Baldo": 24,
    "Merrill Kelly": 37,
    "Merritt Beeker": 23,
    "Meykel Baro": 16,
    "Meylin De Leon": 18,
    "Micah Ashman": 22,
    "Micah Dallas": 25,
    "Micah McDowell": 24,
    "Micah Ottenbreit": 22,
    "Micah Pries": 27,
    "Michael Arias": 23,
    "Michael Arroyo": 21,
    "Michael Brooks": 23,
    "Michael Busch": 28,
    "Michael Caldon": 22,
    "Michael Carico": 22,
    "Michael Cordero": 16,
    "Michael Cuevas": 24,
    "Michael Curialle": 24,
    "Michael Darrell-Hicks": 27,
    "Michael Dattalo": 21,
    "Michael Dominguez": 24,
    "Michael Flynn": 28,
    "Michael Forret": 21,
    "Michael Fowler": 22,
    "Michael Gomez": 28,
    "Michael Guzman": 19,
    "Michael Harris II": 24,
    "Michael Hobbs": 25,
    "Michael Kennedy": 20,
    "Michael King": 30,
    "Michael Knorr": 25,
    "Michael Kopech": 29,
    "Michael Mariot": 36,
    "Michael Martinez": 18,
    "Michael Massey": 27,
    "Michael McGreevy": 25,
    "Michael Mercado": 26,
    "Michael Morales": 22,
    "Michael Nieto": 18,
    "Michael Perez": 22,
    "Michael Petersen": 31,
    "Michael Plassmeyer": 28,
    "Michael Prosecky": 24,
    "Michael Sansone": 25,
    "Michael Snyder": 24,
    "Michael Stefanic": 29,
    "Michael Stryffeler": 29,
    "Michael Trausch": 21,
    "Michael Trautwein": 25,
    "Michael Turconi": 26,
    "Michael Turner": 26,
    "Michael Valverde": 22,
    "Michael Vilchez": 21,
    "Michael Wacha": 34,
    "Michael Watson": 23,
    "Michel Otanez": 27,
    "Michell Ojeda": 18,
    "Mick Abel": 24,
    "Mickey Gasper": 30,
    "Mickey Moniak": 27,
    "Miguel Blanco": 19,
    "Miguel Bleis": 21,
    "Miguel Briceno": 21,
    "Miguel Caraballo": 16,
    "Miguel Cienfuegos": 28,
    "Miguel Cordero": 18,
    "Miguel Cruz": 21,
    "Miguel Flores": 20,
    "Miguel Gomez": 23,
    "Miguel Hernandez": 17,
    "Miguel Mejias": 20,
    "Miguel Mendez": 22,
    "Miguel Mesa": 22,
    "Miguel Pabon": 24,
    "Miguel Palma": 23,
    "Miguel Rivera": 18,
    "Miguel Rodriguez": 19,
    "Miguel Rojas": 36,
    "Miguel Santos": 24,
    "Miguel Toscano": 19,
    "Miguel Ugueto": 22,
    "Miguel Ullola": 23,
    "Miguel Useche": 24,
    "Miguel Valdez": 21,
    "Miguel Vargas": 26,
    "Miguel Villarroel": 23,
    "Miguel Welch": 17,
    "Miguelangel Boadas": 21,
    "Mike Antico": 27,
    "Mike Boeve": 23,
    "Mike Brosseau": 31,
    "Mike Burrows": 26,
    "Mike Jarvis": 27,
    "Mike Paredes": 24,
    "Mike Sirota": 22,
    "Mike Trout": 34,
    "Mike Vasil": 25,
    "Mike Villani": 22,
    "Mike Walsh": 24,
    "Mike Yastrzemski": 34,
    "Mikey Kane": 23,
    "Mikey Romero": 21,
    "Mikey Tepper": 23,
    "Milan Tolentino": 23,
    "Miles Langhorne": 22,
    "Miles Mastrobuoni": 29,
    "Milkar Perez": 23,
    "Milo Rushford": 21,
    "Miqueas Mercedes": 18,
    "Misael Tamarez": 25,
    "Misael Urbina": 23,
    "Mitch Bratt": 22,
    "Mitch Farris": 24,
    "Mitch Jebb": 23,
    "Mitch Keller": 29,
    "Mitch Mueller": 23,
    "Mitch Myers": 26,
    "Mitch Neunborn": 28,
    "Mitch Spence": 27,
    "Mitch Voit": 20,
    "Mitchell Daly": 24,
    "Mitchell Tyranski": 27,
    "Modeifi Marte": 22,
    "Moises Acacio": 17,
    "Moises Alcala": 22,
    "Moises Ballesteros": 22,
    "Moises Bolivar": 17,
    "Moises Chace": 22,
    "Moises Gallardo": 22,
    "Moises Gomez": 26,
    "Moises Marchan": 17,
    "Moises Meza": 19,
    "Moises Morales": 17,
    "Moises Palma": 20,
    "Moises Polanco": 18,
    "Moises Rangel": 17,
    "Moises Rodriguez": 23,
    "Moises Valdez": 19,
    "Montana Semmel": 23,
    "Mookie Betts": 33,
    "Morgan McSweeney": 27,
    "Morris Austin": 25,
    "Munetaka Murakami": 25,
    "Murphy Stehly": 26,
    "Myles Caba": 23,
    "Myles Emmerson": 27,
    "Myles Naylor": 20,
    "Myles Smith": 22,
    "Naibel Mariano": 18,
    "Najer Victor": 23,
    "Narciso Polanco": 20,
    "Natanael Garabitos": 24,
    "Natanael Polanco": 22,
    "Natanael Yuten": 20,
    "Nate Ackenhausen": 23,
    "Nate Baez": 24,
    "Nate Dohm": 22,
    "Nate Eaton": 28,
    "Nate Furman": 23,
    "Nate Garkow": 27,
    "Nate George": 19,
    "Nate Knowles": 21,
    "Nate LaRue": 23,
    "Nate Lavender": 24,
    "Nate Nankil": 22,
    "Nate Payne": 19,
    "Nate Peterson": 25,
    "Nate Rombach": 24,
    "Nate Savino": 23,
    "Nate Wohlgemuth": 24,
    "Nathan Archer": 22,
    "Nathan Blasick": 24,
    "Nathan Church": 24,
    "Nathan Dettmer": 23,
    "Nathan Eovaldi": 35,
    "Nathan Flewelling": 18,
    "Nathan Hickey": 25,
    "Nathan Humphreys": 22,
    "Nathan Karaffa": 23,
    "Nathan Martorella": 24,
    "Nathan Rose": 24,
    "Nathan Webb": 27,
    "Nathan Wiles": 26,
    "Nathanael Cijntje": 18,
    "Nathanael Cruz": 22,
    "Nathanael Heredia": 24,
    "Nathaniel Lowe": 30,
    "Nathaniel Ochoa Leyva": 21,
    "Nauris De La Cruz": 17,
    "Nayerich Waterfort": 19,
    "Nazier Mule": 20,
    "Nazzan Zanetello": 20,
    "Nehomar Ochoa Jr.": 19,
    "Nelfri Payano": 20,
    "Nelfy Ynfante": 20,
    "Nelly Taylor": 22,
    "Nelson Beltran": 23,
    "Nelson L. Alvarez": 27,
    "Nelson Marin": 19,
    "Nelson Quiroz": 23,
    "Nelson Rada": 20,
    "Nerwilian Cedeno": 23,
    "Nestor Cortes Jr.": 31,
    "Nestor German": 23,
    "Nestor Lorant": 23,
    "Nestor Miranda": 19,
    "Nestor Rios": 20,
    "Nestor Urbina": 18,
    "Neurelin Montero": 19,
    "Newremberg Rondon": 21,
    "Nic Enright": 28,
    "Nic Kent": 25,
    "Nic Swanson": 25,
    "Nicandro Aybar": 20,
    "Nicholas Judice": 24,
    "Nicholas Padilla": 28,
    "Nicholas Regalado": 23,
    "Nick Altermatt": 25,
    "Nick Becker": 18,
    "Nick Biddison": 24,
    "Nick Bitsko": 23,
    "Nick Brink": 23,
    "Nick Burdi": 32,
    "Nick Castellanos": 33,
    "Nick Cimillo": 25,
    "Nick Conte": 23,
    "Nick Davila": 26,
    "Nick DeCarlo": 23,
    "Nick Dean": 24,
    "Nick Dombkowski": 26,
    "Nick Dumesnil": 21,
    "Nick Dunn": 28,
    "Nick Frasso": 26,
    "Nick Fraze": 27,
    "Nick Garcia": 26,
    "Nick Gonzales": 26,
    "Nick Goodwin": 23,
    "Nick Hernandez": 30,
    "Nick Hollifield": 21,
    "Nick Hull": 25,
    "Nick Jones": 26,
    "Nick Kahle": 27,
    "Nick Krauth": 25,
    "Nick Kurtz": 22,
    "Nick Lockhart": 24,
    "Nick Lodolo": 27,
    "Nick Lorusso": 24,
    "Nick Maldonado": 25,
    "Nick Margevicius": 29,
    "Nick Martinez": 35,
    "Nick Martini": 35,
    "Nick McLain": 22,
    "Nick Merkel": 26,
    "Nick Mikolajchak": 27,
    "Nick Mitchell": 21,
    "Nick Monistere": 21,
    "Nick Montgomery": 19,
    "Nick Morabito": 22,
    "Nick Morreale": 27,
    "Nick Nastrini": 25,
    "Nick Payero": 25,
    "Nick Peoples": 20,
    "Nick Pinto": 25,
    "Nick Pivetta": 32,
    "Nick Podkul": 28,
    "Nick Pratto": 26,
    "Nick Raposo": 27,
    "Nick Raquet": 29,
    "Nick Richmond": 27,
    "Nick Robertson": 26,
    "Nick Rodriguez": 22,
    "Nick Roselli": 22,
    "Nick Sando": 24,
    "Nick Schnell": 25,
    "Nick Schwartz": 24,
    "Nick Sinacola": 25,
    "Nick Swiney": 26,
    "Nick Trabacchi": 26,
    "Nick Wissman": 24,
    "Nick Yorke": 23,
    "Nick Zwack": 26,
    "Nicky Lopez": 30,
    "Nico Hoerner": 28,
    "Nico Tellache": 27,
    "Nico Zeglin": 24,
    "Nicolas Barrios": 17,
    "Nicolas Carreno": 19,
    "Nicolas Cruz": 21,
    "Nicolas De La Cruz": 19,
    "Nicolas Deschamps": 22,
    "Nicolas Herold": 26,
    "Nicolas Ortiz": 18,
    "Nicolas Perez": 20,
    "Nien-Hsi Yang": 18,
    "Nieves Izaguirre": 17,
    "Nigel Belgrave": 23,
    "Nik McClaughry": 25,
    "Nikau Pouaka-Grego": 20,
    "Niko Kavadas": 26,
    "Nixon Chirinos": 19,
    "Nixon Encarnacion": 20,
    "Noah Barber": 20,
    "Noah Beal": 23,
    "Noah Cameron": 26,
    "Noah Cardenas": 25,
    "Noah Dean": 24,
    "Noah Edders": 22,
    "Noah Hall": 24,
    "Noah Manning": 23,
    "Noah Mendlinger": 24,
    "Noah Miller": 22,
    "Noah Murdock": 26,
    "Noah Myers": 25,
    "Noah Ruen": 22,
    "Noah Schultz": 22,
    "Noah Song": 28,
    "Noah Takacs": 23,
    "Noble Meyer": 21,
    "Noelberth Romero": 23,
    "Noelvi Marte": 24,
    "Nolan Arenado": 34,
    "Nolan Beltran": 20,
    "Nolan Clenney": 29,
    "Nolan Clifford": 23,
    "Nolan DeVos": 24,
    "Nolan Gorman": 25,
    "Nolan Hoffman": 27,
    "Nolan Jones": 27,
    "Nolan McLean": 24,
    "Nolan Perry": 20,
    "Nolan Sailors": 21,
    "Nolan Santos": 23,
    "Nolan Schanuel": 23,
    "Nolan Schubart": 21,
    "Nolan Sparks": 22,
    "Nomar Diaz": 21,
    "Nomar Fana": 22,
    "Nomar Velasquez": 20,
    "Norbis Diaz": 20,
    "Noslen Marquez": 20,
    "Ocean Gabonia": 23,
    "Octavio Becerra": 24,
    "Oddanier Mosqueda": 26,
    "Oliver Carrillo": 23,
    "Oliver Guerrero": 17,
    "Oliver Tejada": 18,
    "Omar Alfonzo": 21,
    "Omar Bustamante": 19,
    "Omar Cruz": 26,
    "Omar De Los Santos": 25,
    "Omar Gonzalez": 19,
    "Omar Guadamuz": 17,
    "Omar Hernandez": 23,
    "Omar Martinez": 23,
    "Omar Mejia": 18,
    "Omar Munoz": 17,
    "Omar Reyes": 20,
    "Omar Urbina": 19,
    "Omar Victorino": 20,
    "Omari Daniel": 21,
    "Oneil Cruz": 27,
    "Onias Jimenez": 21,
    "Onil Perez": 22,
    "Onix Vega": 26,
    "Orelvis Martinez": 23,
    "Orion Kerkering": 24,
    "Orlando Gonzalez": 22,
    "Orlando Martinez": 27,
    "Orlando Ortiz-Mayr": 27,
    "Orlando Patino": 17,
    "Orlando Ribalta": 27,
    "Oscar Rayo": 23,
    "Osleivis Basabe": 24,
    "Osmar Torrealba": 18,
    "Osvaldo Berrios": 25,
    "Osvaldo Heredia": 19,
    "Oswaldo Linares": 22,
    "Oswaldo Osorio": 20,
    "Oswaldo Patino": 18,
    "Otto Lopez": 27,
    "Ovis Portes": 20,
    "Owen Ayers": 24,
    "Owen Caissie": 23,
    "Owen Carey": 18,
    "Owen Cobb": 24,
    "Owen Hackman": 23,
    "Owen Holt": 25,
    "Owen Kellington": 22,
    "Owen Murphy": 22,
    "Owen Stevenson": 22,
    "Owen White": 25,
    "Owen Wild": 22,
    "Ozzie Albies": 29,
    "P.J. Hilson": 24,
    "P.J. Labriola": 24,
    "PJ Morlando": 20,
    "PJ Poulin": 28,
    "Pablo Aldonis": 23,
    "Pablo Aliendo": 24,
    "Pablo Arosemena": 19,
    "Pablo Castillo": 17,
    "Pablo Guerrero": 18,
    "Pablo Lopez": 29,
    "Pablo Martinez": 17,
    "Pablo Nunez": 18,
    "Pablo Reyes": 31,
    "Parker Chavers": 26,
    "Parker Dunshee": 30,
    "Parker Meadows": 26,
    "Parker Messick": 25,
    "Parker Mushinski": 29,
    "Parker Smith": 22,
    "Parks Harber": 23,
    "Pascanel Ferreras": 23,
    "Pascual Archila": 18,
    "Pat Gallagher": 25,
    "Patricio Aquino": 22,
    "Patrick Clohisy": 23,
    "Patrick Copen": 23,
    "Patrick Galle": 21,
    "Patrick Halligan": 25,
    "Patrick Lee": 25,
    "Patrick Monteverde": 27,
    "Patrick Murphy": 30,
    "Patrick Reilly": 23,
    "Patrick Weigel": 30,
    "Patrick Winkel": 25,
    "Paul Bonzagni": 23,
    "Paul Chacon": 19,
    "Paul DeJong": 32,
    "Paul Gervase": 25,
    "Paul Goldschmidt": 38,
    "Paul McIntosh": 27,
    "Paul Skenes": 23,
    "Paul Wilson": 20,
    "Paul Witt": 27,
    "Paulino Santana": 18,
    "Paulo Asprilla": 19,
    "Paulshawn Pasqualotto": 24,
    "Paxton Kling": 22,
    "Paxton Schultz": 27,
    "Paxton Thompson": 25,
    "Payton Eeles": 25,
    "Payton Green": 22,
    "Payton Henry": 28,
    "Payton Martin": 21,
    "Payton Tolle": 23,
    "Pedro Blanco": 18,
    "Pedro Catuy": 19,
    "Pedro Da Costa Lemos": 22,
    "Pedro Dalmagro": 19,
    "Pedro Garcia": 23,
    "Pedro Ibarguen": 18,
    "Pedro León": 27,
    "Pedro Pineda": 21,
    "Pedro Ramirez": 21,
    "Pedro Reyes": 22,
    "Pedro Rodriguez": 22,
    "Pedro Roque": 19,
    "Pedro Santos": 25,
    "Pedro Tovar": 19,
    "Pedro Tucent": 22,
    "Pete Alonso": 31,
    "Pete Crow-Armstrong": 23,
    "Pete Fairbanks": 32,
    "Pete Hansen": 24,
    "Peter Bonilla": 20,
    "Peter Burns": 25,
    "Peter Heubeck": 22,
    "Peter Solomon": 28,
    "Peter Van Loon": 26,
    "Petey Halpin": 23,
    "Peyton Alford": 27,
    "Peyton Carr": 23,
    "Peyton Fosher": 22,
    "Peyton Glavine": 26,
    "Peyton Graham": 24,
    "Peyton Gray": 30,
    "Peyton Holt": 24,
    "Peyton Olejnik": 22,
    "Peyton Pallette": 24,
    "Peyton Powell": 24,
    "Peyton Stovall": 22,
    "Peyton Stumbo": 23,
    "Peyton Williams": 24,
    "Peyton Wilson": 25,
    "Phil Clarke": 27,
    "Phil Fox": 22,
    "Phil Maton": 32,
    "Philip Abner": 23,
    "Phillando Williams": 18,
    "Phillip Glasser": 25,
    "Phillip Sikes": 26,
    "Pierce Bennett": 24,
    "Pierce Coppola": 22,
    "Pierce George": 22,
    "Pierson Ohl": 25,
    "Pitterson Rosa": 20,
    "Po-Yu Chen": 23,
    "Poncho Ruiz": 23,
    "Porfirio Ramos": 21,
    "Prelander Berroa": 24,
    "Preston Howey": 23,
    "Preston Johnson": 25,
    "Queni Pineda": 18,
    "Quentin Young": 18,
    "Quincy Hamilton": 27,
    "Quincy Scott": 22,
    "Quinn Mathews": 25,
    "Quinn McDaniel": 22,
    "Quinn Priester": 25,
    "Qyshawn Legito": 19,
    "R.J. Dabovich": 26,
    "R.J. Gordon": 23,
    "R.J. Yeager": 26,
    "RJ Austin": 21,
    "RJ Petit": 25,
    "RJ Schreck": 24,
    "RJ Shunck": 21,
    "Rafael Castillo": 19,
    "Rafael Devers": 29,
    "Rafael Escalante": 23,
    "Rafael Flores": 25,
    "Rafael Gonzalez": 20,
    "Rafael Lantigua": 27,
    "Rafael Marcano": 25,
    "Rafael Morel": 23,
    "Rafael Oropeza": 17,
    "Rafael Ramirez Jr.": 19,
    "Rafael Sanchez": 25,
    "Rafe Perich": 23,
    "Rafe Schlesinger": 22,
    "Rafhlmil Torres": 19,
    "Rafi Montesino": 18,
    "Rafy Peguero": 18,
    "Raider Tello": 24,
    "Railin Familia": 20,
    "Railin Perez": 23,
    "Raily Liriano": 18,
    "Raimel Medina": 20,
    "Raimon Gomez": 23,
    "Raimundo De Los Santos": 20,
    "Raimy Rodriguez": 19,
    "Rainer Espinoza": 16,
    "Rainer Nunez": 24,
    "Rainiel Rodriguez": 19,
    "Raisel Iglesias": 36,
    "Ralphy Velazquez": 20,
    "Ramcell Medina": 17,
    "Ramiro Dominguez": 18,
    "Ramon Landaeta": 19,
    "Ramon Laureano": 31,
    "Ramon Marquez": 19,
    "Ramon Mendoza": 24,
    "Ramon Peralta": 21,
    "Ramon Ramirez": 20,
    "Ramon Rodriguez": 26,
    "Ramon Urias": 31,
    "Ramsey David": 24,
    "Ramy Peralta": 18,
    "Randal Diaz": 22,
    "Randal Grichuk": 34,
    "Randel Clemente": 23,
    "Randy Arozarena": 30,
    "Randy Beriguete": 22,
    "Randy De Jesus": 20,
    "Randy Flores": 24,
    "Randy Guzman": 20,
    "Randy Labaut": 28,
    "Randy Martinez": 18,
    "Randy Soto": 18,
    "Randy Vasquez": 27,
    "Randy Wynne": 32,
    "Ranger Suarez": 30,
    "Rashawn Pinder": 18,
    "Raudelis Martinez": 23,
    "Raudi Rodriguez": 21,
    "Raudy Rivera": 20,
    "Raul Alcantara": 24,
    "Raul Brito": 28,
    "Raul Pereira": 17,
    "Ray Gaither": 27,
    "Raylin Heredia": 21,
    "Raylin Ramos": 20,
    "Raymer Medina": 17,
    "Raymon Rosario": 20,
    "Raymond Burgos": 26,
    "Raymond Mola": 19,
    "Rayne Doncon": 21,
    "Raynel Delgado": 25,
    "Rayner Arias": 19,
    "Rayner Castillo": 21,
    "Rayner Herrera": 17,
    "Raynerd Ortega": 19,
    "Raynier Ramirez": 20,
    "Rayven Antonio": 19,
    "Rece Hinds": 24,
    "Reece Walling": 21,
    "Reed Garrett": 33,
    "Reed Trimble": 25,
    "Reese Dutton": 24,
    "Reese Olson": 26,
    "Reese Sharp": 24,
    "Reggie Crawford": 23,
    "Reginald Preciado": 22,
    "Reibyn Corona": 23,
    "Reid Detmers": 26,
    "Reid VanScoter": 26,
    "Reidis Sena": 24,
    "Reilin Ramirez": 21,
    "Reinaldo De La Cruz": 19,
    "Reiner Herrera": 19,
    "Reinold Navarro": 18,
    "Reiss Knehr": 28,
    "Reivaj Garcia": 23,
    "Reiver Camacho": 18,
    "Remy Veldhuisen": 20,
    "Rendy Naveo": 17,
    "Renil Ramos": 19,
    "Reudis Diaz": 19,
    "Rey Cruz": 17,
    "Rey Reyes": 17,
    "Reyli Mariano": 18,
    "Reylin Perez": 20,
    "Reynaldo De La Paz": 19,
    "Reynaldo Lopez": 32,
    "Reynaldo Yean": 21,
    "Reynardo Cruz": 23,
    "Rhett Kouba": 25,
    "Rhett Lowder": 23,
    "Rhylan Thomas": 25,
    "Rhys Hoskins": 32,
    "Riangelo Richardson": 17,
    "Ricardo Brizuela": 22,
    "Ricardo Cabrera": 20,
    "Ricardo Chirinos": 17,
    "Ricardo Cova": 21,
    "Ricardo Crespo": 18,
    "Ricardo Estrada": 23,
    "Ricardo Genoves": 26,
    "Ricardo Gonzalez": 20,
    "Ricardo Hurtado": 22,
    "Ricardo Montero": 21,
    "Ricardo Olivar": 23,
    "Ricardo Paez": 18,
    "Ricardo Pena": 20,
    "Ricardo Romero": 17,
    "Ricardo Velez": 26,
    "Ricardo Yan": 22,
    "Richard Fernandez": 22,
    "Richard Fitts": 26,
    "Richard Gallardo": 22,
    "Richard Guasch": 27,
    "Richard Matic": 17,
    "Richard Meran": 19,
    "Richard Ramirez": 19,
    "Richer Mata": 17,
    "Richie Bonomolo Jr.": 21,
    "Rickardo Perez": 21,
    "Ricky Castro": 25,
    "Ricky DeVito": 26,
    "Ricky Tiedemann": 23,
    "Ricky Vanasco": 26,
    "Ricson Gonzalez": 20,
    "Rikuu Nishida": 24,
    "Riley Cooper": 23,
    "Riley Cornelio": 25,
    "Riley Frey": 23,
    "Riley Gowens": 25,
    "Riley Greene": 25,
    "Riley Martin": 27,
    "Riley Nelson": 21,
    "Riley Pint": 26,
    "Riley Tirotta": 26,
    "Riley Unroe": 29,
    "Rio Britton": 21,
    "Rio Foster": 22,
    "Ripken Reyes": 28,
    "Riskiel Tineo": 22,
    "River Ryan": 27,
    "Rob Griswold": 26,
    "Rob Kaminsky": 30,
    "Robbie Burnett": 22,
    "Robbie Ray": 34,
    "Robby Ahlstrom": 26,
    "Robby Snelling": 22,
    "Robert Alvarez": 17,
    "Robert Arias": 18,
    "Robert Brooks": 26,
    "Robert Calaz": 19,
    "Robert Cranz": 22,
    "Robert Dugger": 29,
    "Robert Gasser": 26,
    "Robert Gonzalez": 20,
    "Robert Hassell": 24,
    "Robert Hipwell": 22,
    "Robert Kwiatkowski": 28,
    "Robert Lantigua": 18,
    "Robert Lopez": 21,
    "Robert Moore": 23,
    "Robert Perez": 21,
    "Robert Phelps": 21,
    "Robert Puason": 22,
    "Robert Stock": 35,
    "Robert Suarez": 34,
    "Robert Wegielnik": 23,
    "Roberto Burgos": 21,
    "Roberto Campos": 22,
    "Roberto Medina": 20,
    "Roberto Perez": 21,
    "Roberto Urdaneta": 19,
    "Robin Ortiz": 18,
    "Robinson Chacon": 18,
    "Robinson Martinez": 27,
    "Robinson Ortiz": 25,
    "Robinson Pina": 26,
    "Roc Riggio": 23,
    "Rocco Reid": 22,
    "Roderick Arias": 20,
    "Roderick Flores": 18,
    "Rodney Boone": 25,
    "Rodney Green": 22,
    "Rodny Rosario": 17,
    "Rodolfo Castro": 26,
    "Rodolfo Duran": 27,
    "Rodolfo Martinez": 31,
    "Rodolfo Nolasco": 23,
    "Rodrigo Garcia": 18,
    "Rodrigo Gonzalez": 17,
    "Roel Garcia III": 26,
    "Roger Lasso": 21,
    "Roiber Niazoa": 20,
    "Roiber Talavera": 21,
    "Roiner Cespede": 17,
    "Roiner Quintana": 20,
    "Roinny Aguiar": 20,
    "Roismar Quintana": 22,
    "Roki Sasaki": 24,
    "Rolando De La Cruz": 24,
    "Rolddy Munoz": 25,
    "Roldy Brito": 18,
    "Roman Angelo": 25,
    "Roman Anthony": 21,
    "Roman Phansalkar": 27,
    "Romano Donato": 16,
    "Romeli Espinosa": 17,
    "Romeo Sanabria": 23,
    "Romer Taveras": 18,
    "Romtres Cabrera": 21,
    "Romy Gonzalez": 29,
    "Ronaiker Palma": 25,
    "Ronald Acuna Jr.": 28,
    "Ronald Hernandez": 21,
    "Ronald Ramirez": 18,
    "Ronald Rosario": 22,
    "Ronald Terrero": 17,
    "Ronaldo Gallo": 24,
    "Ronaldo Hernandez": 27,
    "Ronaldys Jimenez": 19,
    "Ronan Kopp": 22,
    "Ronel Blanco": 32,
    "Roni Cabrera": 19,
    "Roni Garcia": 17,
    "Roniel Paulino": 17,
    "Ronny Chalas": 22,
    "Ronny Cruz": 18,
    "Ronny Gonell": 18,
    "Ronny Henriquez": 25,
    "Ronny Hernandez": 20,
    "Ronny Lopez": 22,
    "Ronny Mauricio": 24,
    "Ronny Oliver": 21,
    "Ronny Simon": 25,
    "Ronny Suarez": 17,
    "Ronny Ugarte": 20,
    "Ronnyel Espinoza": 19,
    "Rony Bello": 17,
    "Roosbert Tapia": 20,
    "Roque Gutierrez": 22,
    "Rordy Mejia": 20,
    "Rorik Maltrud": 25,
    "Rosman Verdugo": 20,
    "Rosnel Alarcon": 17,
    "Rosniell De Paula": 16,
    "Ross Carver": 25,
    "Ross Dunn": 23,
    "Rowdey Jordan": 26,
    "Rowell Arroyo": 20,
    "Roy Rivero": 17,
    "Royber Salinas": 24,
    "Roybert Herrera": 18,
    "Royce Lewis": 26,
    "Royelny Strop": 17,
    "Roynier Hernandez": 20,
    "Rubel Cespedes": 24,
    "Ruben Castillo": 17,
    "Ruben Galindo": 24,
    "Ruben Ibarra": 26,
    "Ruben Menes": 23,
    "Ruben Ramirez": 20,
    "Ruben Salinas": 22,
    "Ruben Santana": 20,
    "Ruben Tiamo": 17,
    "Ruddy Gomez": 25,
    "Rudit Pina": 19,
    "Russell Smith": 25,
    "Ryan Ammons": 24,
    "Ryan Anderson": 26,
    "Ryan Andrade": 22,
    "Ryan Bergert": 25,
    "Ryan Birchard": 21,
    "Ryan Bliss": 25,
    "Ryan Bourassa": 25,
    "Ryan Boyer": 28,
    "Ryan Brady": 26,
    "Ryan Brown": 22,
    "Ryan Bruno": 23,
    "Ryan Burrowes": 20,
    "Ryan Cabarcas": 24,
    "Ryan Campos": 22,
    "Ryan Cardona": 25,
    "Ryan Cermak": 24,
    "Ryan Cesarini": 22,
    "Ryan Clifford": 22,
    "Ryan Costeiu": 24,
    "Ryan Cusick": 25,
    "Ryan Daniels": 21,
    "Ryan Degges": 22,
    "Ryan Dromboski": 22,
    "Ryan Feltner": 29,
    "Ryan Galanie": 25,
    "Ryan Gallagher": 22,
    "Ryan Garcia": 27,
    "Ryan Gusto": 26,
    "Ryan Harbin": 23,
    "Ryan Harvey": 24,
    "Ryan Hawks": 24,
    "Ryan Helsley": 31,
    "Ryan Hendrix": 30,
    "Ryan Ignoffo": 24,
    "Ryan Jackson": 23,
    "Ryan Jennings": 26,
    "Ryan Jensen": 27,
    "Ryan Johnson": 23,
    "Ryan Lambert": 22,
    "Ryan Lasko": 23,
    "Ryan Lobus": 24,
    "Ryan Long": 25,
    "Ryan Loutos": 26,
    "Ryan Magdic": 25,
    "Ryan McCarty": 26,
    "Ryan McCoy": 23,
    "Ryan McCrystal": 22,
    "Ryan McDonagh": 19,
    "Ryan McMahon": 31,
    "Ryan Middendorf": 27,
    "Ryan Miller": 29,
    "Ryan Mountcastle": 28,
    "Ryan Murphy": 25,
    "Ryan Nicholson": 24,
    "Ryan OHearn": 32,
    "Ryan Och": 26,
    "Ryan Pepiot": 28,
    "Ryan Picollo": 23,
    "Ryan Pressly": 37,
    "Ryan Ramsey": 24,
    "Ryan Reckley": 20,
    "Ryan Rolison": 27,
    "Ryan Schiefer": 21,
    "Ryan Shreve": 27,
    "Ryan Sloan": 20,
    "Ryan Spikes": 22,
    "Ryan Sprock": 20,
    "Ryan Stafford": 22,
    "Ryan Sublette": 26,
    "Ryan Vanderhei": 24,
    "Ryan Verdugo": 22,
    "Ryan Vilade": 26,
    "Ryan Waldschmidt": 23,
    "Ryan Walker": 30,
    "Ryan Ward": 27,
    "Ryan Watson": 27,
    "Ryan Weathers": 26,
    "Ryan Webb": 26,
    "Ryan Weingartner": 20,
    "Ryan Wideman": 21,
    "Ryan Wilson": 23,
    "Ryan Wrobleski": 25,
    "Ryan Yarbrough": 34,
    "Ryder Ryan": 30,
    "Rylan Galvan": 22,
    "Ryne Nelson": 27,
    "Sabin Ceballos": 22,
    "Sadiel Baro": 20,
    "Sadrac Franco": 25,
    "Sahid Valenzuela": 27,
    "Saivel Zayas": 17,
    "Sal Frelick": 25,
    "Sal Stewart": 22,
    "Salvador Perez": 35,
    "Sam Aldegheri": 23,
    "Sam Antonacci": 22,
    "Sam Armstrong": 24,
    "Sam Bachman": 25,
    "Sam Benschoter": 27,
    "Sam Biller": 22,
    "Sam Brodersen": 23,
    "Sam Brown": 23,
    "Sam Carlson": 26,
    "Sam Garcia": 23,
    "Sam Gerth": 20,
    "Sam Highfill": 24,
    "Sam Knowlton": 25,
    "Sam Kulasingam": 23,
    "Sam McWilliams": 29,
    "Sam Petersen": 22,
    "Sam Praytor": 26,
    "Sam Robertson": 20,
    "Sam Rochard": 24,
    "Sam Ruta": 23,
    "Sam Ryan": 26,
    "Sam Shaw": 20,
    "Sam Thoresen": 26,
    "Sam Tookoian": 22,
    "Sam Weatherly": 26,
    "Sam Whiting": 24,
    "Samad Taylor": 26,
    "Sami Manzueta": 16,
    "Samil Dishmey": 19,
    "Samir Chires": 21,
    "Sammy Hernandez": 21,
    "Sammy Peralta": 27,
    "Sammy Sass": 24,
    "Sammy Siani": 24,
    "Sammy Stafura": 20,
    "Samuel Basallo": 21,
    "Samuel Brito": 18,
    "Samuel Carpio": 22,
    "Samuel Colmenares": 20,
    "Samuel Dutton": 22,
    "Samuel Escudero": 21,
    "Samuel Estevez": 18,
    "Samuel Fabian": 22,
    "Samuel Gil": 20,
    "Samuel Gonzalez": 18,
    "Samuel Mejia": 23,
    "Samuel Munoz": 20,
    "Samuel Pardo": 17,
    "Samuel Perez": 25,
    "Samuel Salcedo": 17,
    "Samuel Sanchez": 19,
    "Samuel Strickland": 26,
    "Samuel Vasquez": 25,
    "Samuel Zavala": 20,
    "Samuell Sanchez": 19,
    "Samy Natera Jr.": 25,
    "Sandor Feliciano": 17,
    "Sandro Pereira": 19,
    "Sandro Santana": 20,
    "Sandy Alcantara": 30,
    "Sandy Gaston": 23,
    "Sandy Luciano": 18,
    "Sandy Mejia": 20,
    "Sandy Ozuna": 19,
    "Sandy Presbot": 17,
    "Sann Omosako": 19,
    "Santiago Almao": 17,
    "Santiago Camacho": 18,
    "Santiago Contreras": 19,
    "Santiago Figueroa": 16,
    "Santiago Gil": 17,
    "Santiago Gomez": 21,
    "Santiago Leon": 17,
    "Santiago Martinez": 17,
    "Santiago Mendoza": 17,
    "Santiago Peraza": 20,
    "Santiago Pinto": 19,
    "Santiago Prado": 18,
    "Santiago Ramos": 18,
    "Santiago Rojas": 18,
    "Santiago Suarez": 21,
    "Santiago Ustariz": 18,
    "Saul Garcia": 22,
    "Saul Gomez": 17,
    "Saul Ramirez": 19,
    "Saul Teran": 23,
    "Sauryn Lao": 25,
    "Sawyer Hawks": 22,
    "Sayer Diederich": 24,
    "Scott Bandura": 23,
    "Scott Barlow": 33,
    "Seamus Barrett": 23,
    "Sean Barnett": 22,
    "Sean Boyle": 28,
    "Sean Burke": 26,
    "Sean Harney": 26,
    "Sean Heppner": 22,
    "Sean Hunley": 25,
    "Sean Keys": 22,
    "Sean Linan": 20,
    "Sean Manaea": 33,
    "Sean Matson": 23,
    "Sean McLain": 24,
    "Sean Newcomb": 32,
    "Sean Paul Linan": 21,
    "Sean Poppen": 31,
    "Sean Reynolds": 27,
    "Sean Sullivan": 23,
    "Seaver King": 22,
    "Sebastian  Rivero": 26,
    "Sebastian Baquera": 18,
    "Sebastian Blanco": 17,
    "Sebastian Cadiz": 19,
    "Sebastian De Andrade": 19,
    "Sebastian De Los Santos": 19,
    "Sebastian Dos Santos": 17,
    "Sebastian Gongora": 23,
    "Sebastian Keane": 24,
    "Sebastian Pena": 17,
    "Sebastian Pulido": 19,
    "Sebastian Rojas": 18,
    "Sebastian Walcott": 19,
    "Seiya Suzuki": 31,
    "Sem Robberse": 23,
    "Sergio Tapia": 22,
    "Seth Beer": 28,
    "Seth Chavez": 25,
    "Seth Clark": 25,
    "Seth Clausen": 22,
    "Seth Johnson": 26,
    "Seth Keener": 23,
    "Seth Keller": 21,
    "Seth Lonsway": 26,
    "Seth Lugo": 36,
    "Seth Shuman": 27,
    "Seth Stephenson": 24,
    "Shaddon Peavyhouse": 26,
    "Shai Robinson": 21,
    "Shalin Polanco": 21,
    "Shane Baz": 26,
    "Shane Bieber": 30,
    "Shane Drohan": 26,
    "Shane Marshall": 24,
    "Shane McClanahan": 28,
    "Shane McGuire": 26,
    "Shane Murphy": 24,
    "Shane Panzini": 23,
    "Shane Rademacher": 24,
    "Shane Sasaki": 24,
    "Shane Smith": 25,
    "Sharlisson De La Rosa": 17,
    "Shawn Armstrong": 35,
    "Shawn Goosenberg": 25,
    "Shawn Rapp": 24,
    "Shawn Ross": 25,
    "Shawndrick Oduber": 20,
    "Shay Schanaman": 25,
    "Shay Timmer": 22,
    "Shay Whitcomb": 26,
    "Shea Langeliers": 28,
    "Shea Sprague": 22,
    "Shendrion Martinus": 18,
    "Sheng-En Lin": 19,
    "Shinnosuke Ogasawara": 27,
    "Shohei Ohtani": 31,
    "Shohei Tomioka": 29,
    "Shota Imanaga": 32,
    "Shotaro Morii": 19,
    "Silas Ardoin": 24,
    "Silvano Hechavarria": 22,
    "Simeon Woods-Richardson": 25,
    "Simon Juan": 19,
    "Simon Leandro": 23,
    "Simon Miller": 24,
    "Sir Jamison Jones": 19,
    "Skylar Hales": 23,
    "Skylar King": 21,
    "Skyler Messinger": 26,
    "Slade Caldwell": 19,
    "Slade Cecconi": 26,
    "Slate Alford": 22,
    "Solomon Maguire": 22,
    "Sonny DiChiara": 25,
    "Sonny Gray": 36,
    "Spence Coffman": 21,
    "Spencer Arrighetti": 26,
    "Spencer Bengard": 23,
    "Spencer Bramwell": 26,
    "Spencer Giesting": 23,
    "Spencer Horwitz": 28,
    "Spencer Jones": 24,
    "Spencer Nivens": 23,
    "Spencer Packard": 27,
    "Spencer Schwellenbach": 25,
    "Spencer Steer": 28,
    "Spencer Strider": 27,
    "Spencer Torkelson": 26,
    "Stanly Alcantara": 21,
    "Starlin Aguilar": 21,
    "Starlin Mieses": 17,
    "Starlyn Caba": 20,
    "Starlyn Nunez": 19,
    "Stefan Raeth": 24,
    "Stephen Hrustich": 23,
    "Stephen Jones": 27,
    "Stephen Kolek": 28,
    "Stephen Paolini": 24,
    "Stephen Quigley": 25,
    "Stephen Ridings": 29,
    "Stephen Scott": 28,
    "Sterlin Thompson": 24,
    "Sterling Bazil": 17,
    "Sterling Patick": 20,
    "Steven Brooks": 22,
    "Steven Cruz": 18,
    "Steven Echavarria": 19,
    "Steven Herrera": 17,
    "Steven Jennings": 26,
    "Steven Kwan": 28,
    "Steven Madero": 18,
    "Steven Ondina": 23,
    "Steven Perez": 24,
    "Steven Sanchez": 21,
    "Steven Santos": 17,
    "Steven Zobac": 24,
    "Stevie Emanuels": 26,
    "Steward Berroa": 26,
    "Stharlin Torres": 19,
    "Sthiven Benitez": 20,
    "Stiven Cruz": 23,
    "Stiven De La Cruz": 17,
    "Stiven Flores": 19,
    "Stiven Marinez": 17,
    "Stiven Martinez": 17,
    "Stone Hewlett": 23,
    "Stone Russell": 21,
    "Stu Flesland III": 24,
    "Styven Paez": 20,
    "Sunayro Martina": 21,
    "T.J. Brock": 24,
    "T.J. Fondtain": 24,
    "T.J. McCants": 24,
    "T.J. Nichols": 23,
    "T.J. Rumfield": 25,
    "T.J. Schofield-Sam": 24,
    "T.J. Sikkema": 26,
    "T.J. White": 21,
    "TJ Friedl": 30,
    "TJ Shook": 27,
    "TJayy Walton": 20,
    "TT Bowens": 27,
    "Tai Peete": 19,
    "Taijuan Walker": 33,
    "Taj Bradley": 24,
    "Tanner Andrews": 29,
    "Tanner Bauman": 23,
    "Tanner Bibee": 26,
    "Tanner Burns": 26,
    "Tanner Dodson": 28,
    "Tanner Franklin": 21,
    "Tanner Gillis": 24,
    "Tanner Hall": 23,
    "Tanner Jacobson": 25,
    "Tanner Kiest": 30,
    "Tanner Kohlhepp": 26,
    "Tanner McDougal": 22,
    "Tanner Murray": 25,
    "Tanner Schobel": 24,
    "Tanner Scott": 31,
    "Tanner Shears": 26,
    "Tanner Smith": 22,
    "Tanner Thach": 21,
    "Tanner Witt": 22,
    "Tarik Skubal": 29,
    "Tate Kuehner": 24,
    "Tate Southisene": 18,
    "Tatem Levins": 26,
    "Tatsuya Imai": 27,
    "Tavano Baker": 18,
    "Tavian Josenberger": 23,
    "Tayden Hall": 22,
    "Tayler Aguilar": 24,
    "Taylor Dollard": 26,
    "Taylor Floyd": 27,
    "Taylor Rashi": 29,
    "Taylor Rogers": 35,
    "Taylor Ward": 32,
    "Taylor Young": 26,
    "Teague Conrad": 24,
    "Teddy McGraw": 23,
    "Teddy Sharkey": 23,
    "Teilon Serrano": 17,
    "Tejahari Wilson": 18,
    "Tejay Antone": 31,
    "Tekoah Roby": 24,
    "Teo Banks": 21,
    "Teofilo Mendez": 23,
    "Teoscar Hernandez": 33,
    "Termarr Johnson": 21,
    "Terrell Tatum": 25,
    "Terrin Vavra": 28,
    "Tevin Tucker": 25,
    "Thaddeus Ward": 28,
    "Thayron Liranzo": 22,
    "Theo Gillen": 20,
    "Theo Hardy": 23,
    "Thomas Balboni Jr.": 23,
    "Thomas Bruss": 26,
    "Thomas Farr": 26,
    "Thomas Gavello": 24,
    "Thomas Harrington": 24,
    "Thomas Ireland": 23,
    "Thomas Mangus": 22,
    "Thomas Pannone": 30,
    "Thomas Saggese": 23,
    "Thomas Schultz": 25,
    "Thomas Sosa": 20,
    "Thomas Szapucki": 29,
    "Thomas Takayoshi": 24,
    "Thomas White": 21,
    "Tim Elko": 26,
    "Tim Fischer": 20,
    "Tim Naughton": 29,
    "Tink Hence": 23,
    "Tirso Ornelas": 25,
    "Titan Hayes": 23,
    "Titus Dumitru": 22,
    "Todd Peterson": 27,
    "Tom Guerrero": 19,
    "Tom Poole": 22,
    "Tom Reisinger": 24,
    "Tomas Frick": 24,
    "Tommy Edman": 30,
    "Tommy Hawke": 22,
    "Tommy Hopfe": 22,
    "Tommy Kane": 23,
    "Tommy Mace": 26,
    "Tommy McCollum": 26,
    "Tommy Molsky": 22,
    "Tommy Romero": 27,
    "Tommy Sacco Jr.": 26,
    "Tommy Sheehan": 26,
    "Tommy Troy": 23,
    "Tommy Vail": 26,
    "Tommy White": 22,
    "Tomoyuki Sugano": 36,
    "Tomás Nido": 31,
    "Tony Blanco Jr.": 20,
    "Tony Bullard": 25,
    "Tony Gonsolin": 31,
    "Tony Rossi": 25,
    "Tony Ruiz": 19,
    "Tony Santa Maria": 23,
    "Tony Santillan": 28,
    "Trace Bright": 24,
    "Trace Willhoite": 24,
    "Travis Adams": 25,
    "Travis Bazzana": 23,
    "Travis Blankenhorn": 28,
    "Travis Garnett": 22,
    "Travis Honeyman": 23,
    "Travis Jankowski": 34,
    "Travis Kuhn": 27,
    "Travis MacGregor": 27,
    "Travis Smith": 22,
    "Travis Sthele": 23,
    "Travis Swaggerty": 27,
    "Travis Sykora": 21,
    "Tre Morgan": 23,
    "Tre Richardson": 23,
    "Tre' Morgan": 22,
    "Trea Turner": 32,
    "Trei Cruz": 26,
    "Trennor O'Donnell": 24,
    "Trent Baker": 26,
    "Trent Buchanan": 23,
    "Trent Farquhar": 24,
    "Trent Grisham": 29,
    "Trent Harris": 26,
    "Trent Hodgdon": 21,
    "Trent Sellers": 25,
    "Trent Turzenski": 24,
    "Trent Youngblood": 23,
    "Trenton Denholm": 25,
    "Trenton Wallace": 26,
    "Tres Gonzalez": 24,
    "Trevin Michael": 27,
    "Trevor Austin": 23,
    "Trevor Boone": 27,
    "Trevor Cohen": 21,
    "Trevor Harrison": 19,
    "Trevor Haskins": 22,
    "Trevor Hauver": 26,
    "Trevor Kuncl": 26,
    "Trevor Larnach": 28,
    "Trevor Long": 24,
    "Trevor Martin": 24,
    "Trevor McDonald": 24,
    "Trevor Megill": 32,
    "Trevor Rogers": 28,
    "Trevor Story": 33,
    "Trevor Werner": 24,
    "Trey Benton": 26,
    "Trey Braithwaite": 27,
    "Trey Dombroski": 24,
    "Trey Faltine": 24,
    "Trey Gibson": 23,
    "Trey Gregory-Alford": 19,
    "Trey McGough": 27,
    "Trey McLoughlin": 26,
    "Trey Paige": 24,
    "Trey Pooser": 23,
    "Trey Snyder": 19,
    "Trey Supak": 29,
    "Trey Sweeney": 25,
    "Trey Yesavage": 22,
    "Tristan Garnett": 27,
    "Tristan Gray": 29,
    "Tristan Peters": 25,
    "Tristan Smith": 22,
    "Tristan Stevens": 27,
    "Tristin English": 28,
    "Triston Casas": 26,
    "Troy Guthrie": 19,
    "Troy Johnston": 28,
    "Troy Melton": 25,
    "Troy Schreffler": 24,
    "Troy Taylor": 23,
    "Troy Watson": 28,
    "Truitt Madonna": 18,
    "Trystan Vrieling": 24,
    "Tsung-Che Cheng": 23,
    "Tucker Barnhart": 34,
    "Tucker Biven": 21,
    "Tucker Flint": 24,
    "Tucker Mitchell": 24,
    "Tucker Toman": 21,
    "Turner Hill": 26,
    "Twine Palmer": 20,
    "Ty Adcock": 28,
    "Ty Cummings": 23,
    "Ty Floyd": 23,
    "Ty France": 31,
    "Ty Harvey": 18,
    "Ty Johnson": 24,
    "Ty Langenberg": 23,
    "Ty Madden": 25,
    "Ty Southisene": 19,
    "Ty Weatherly": 24,
    "Tyler Anderson": 36,
    "Tyler Baca": 25,
    "Tyler Baum": 27,
    "Tyler Black": 25,
    "Tyler Bradt": 24,
    "Tyler Bryant": 26,
    "Tyler Burch": 26,
    "Tyler Callihan": 25,
    "Tyler Cleveland": 25,
    "Tyler Davis": 26,
    "Tyler Dearden": 26,
    "Tyler Freeman": 26,
    "Tyler Gentry": 26,
    "Tyler Glasnow": 32,
    "Tyler Gough": 20,
    "Tyler Guilfoil": 25,
    "Tyler Hampu": 22,
    "Tyler Hardman": 26,
    "Tyler Heineman": 34,
    "Tyler Herron": 22,
    "Tyler Holton": 29,
    "Tyler Howard": 21,
    "Tyler Ivey": 29,
    "Tyler Jay": 31,
    "Tyler Kennedy": 23,
    "Tyler LaPorte": 28,
    "Tyler Mahle": 31,
    "Tyler Mattison": 26,
    "Tyler McDonough": 26,
    "Tyler Miller": 25,
    "Tyler Morgan": 24,
    "Tyler Myrick": 27,
    "Tyler Naquin": 34,
    "Tyler ONeill": 30,
    "Tyler Owens": 24,
    "Tyler Pettorini": 22,
    "Tyler Renz": 18,
    "Tyler Robertson": 25,
    "Tyler Rodriguez": 19,
    "Tyler Rogers": 35,
    "Tyler Samaniego": 26,
    "Tyler Santana": 27,
    "Tyler Schlaffer": 24,
    "Tyler Schoff": 26,
    "Tyler Schweitzer": 24,
    "Tyler Soderstrom": 24,
    "Tyler Stasiowski": 23,
    "Tyler Stephenson": 29,
    "Tyler Stuart": 25,
    "Tyler Switalski": 22,
    "Tyler Thornton": 24,
    "Tyler Tolbert": 27,
    "Tyler Tolve": 24,
    "Tyler Uberstine": 26,
    "Tyler Vogel": 24,
    "Tyler Wade": 30,
    "Tyler Wells": 31,
    "Tyler Whitaker": 22,
    "Tyler Wilson": 22,
    "Tyler Woessner": 25,
    "Tyler Zuber": 30,
    "Tylor Megill": 30,
    "Tyresse Turner": 25,
    "Tyriq Kemp": 22,
    "Tyrone Yulie": 23,
    "Tyson Guerrero": 26,
    "Tyson Hardin": 23,
    "Tyson Lewis": 19,
    "Tyson Neighbors": 22,
    "Tytus Cissell": 19,
    "Tzu-Chen Sha": 21,
    "Ubaldo Soto": 18,
    "Ubert Mejias": 24,
    "Valentin Linarez": 25,
    "Vance Honeycutt": 22,
    "Vaughn Grissom": 25,
    "Vaun Brown": 27,
    "Viandel Pena": 24,
    "Vicente Guaylupo": 19,
    "Victor Acosta": 21,
    "Victor Aguirre": 18,
    "Victor Arias": 21,
    "Victor Bericoto": 23,
    "Victor Brea": 22,
    "Victor Cabreja": 23,
    "Victor Cardoza": 19,
    "Victor Duarte": 24,
    "Victor Familia": 18,
    "Victor Farias": 22,
    "Victor Figueroa": 22,
    "Victor Garcia": 17,
    "Victor Hurtado": 18,
    "Victor Izturis": 20,
    "Victor Juarez": 22,
    "Victor Labrada": 25,
    "Victor Leal": 18,
    "Victor Lizarraga": 21,
    "Victor Marquez": 17,
    "Victor Mederos": 24,
    "Victor Mesa Jr.": 23,
    "Victor Morales": 23,
    "Victor Ortega": 21,
    "Victor Robles": 28,
    "Victor Rodrigues": 20,
    "Victor Rodriguez": 19,
    "Victor Saez": 17,
    "Victor Santana": 17,
    "Victor Santos": 23,
    "Victor Scott": 24,
    "Victor Simeon": 24,
    "Victor Torres": 24,
    "Victor Zarraga": 21,
    "Vince Reilly": 24,
    "Vince Vannelle": 27,
    "Vincent Perozo": 22,
    "Vinicius Dos Santos": 18,
    "Vinnie Pasquantino": 28,
    "Vinny Capra": 28,
    "Vinny Nittoli": 34,
    "Vladi Gomez": 19,
    "Vladi Guerrero": 18,
    "Vladimir Asencio": 18,
    "Vladimir Guerrero Jr.": 26,
    "Wade Meckler": 25,
    "Wade Stauss": 26,
    "Wady Mendez": 20,
    "Wagnel Luna": 19,
    "Walbert Urena": 21,
    "Walfrent Guzman": 20,
    "Walin Castillo": 20,
    "Walker Brockhouse": 26,
    "Walker Buehler": 31,
    "Walker Janek": 22,
    "Walker Jenkins": 20,
    "Walker Martin": 21,
    "Walker Powell": 29,
    "Wallace Clark": 23,
    "Walter Ford": 20,
    "Walter Pennington": 27,
    "Walvin Mena": 19,
    "Wander Arias": 25,
    "Wander Guante": 25,
    "Wanderlin Padilla": 17,
    "Wanderly De La Cruz": 17,
    "Wandi Feliz": 17,
    "Wandy Peralta": 34,
    "Waner Luciano": 20,
    "Wanmer Ramirez": 21,
    "Wardquelin Vasquez": 23,
    "Warel Solano": 17,
    "Warming Bernabel": 23,
    "Warren Calcano": 17,
    "Wehiwa Aloy": 21,
    "Wei-En Lin": 19,
    "Welbyn Francisca": 19,
    "Welinton Herrera": 21,
    "Wellington Aracena": 20,
    "Wen-Hui Pan": 21,
    "Wenceel Perez": 26,
    "Wenderlyn King": 19,
    "Werner Blakely": 23,
    "Wes Benjamin": 31,
    "Wes Clarke": 25,
    "Wes Kath": 22,
    "Weskendry Espinoza": 23,
    "Wesley Moore": 25,
    "Wesly Castillo": 17,
    "Weston Eberly": 24,
    "Weston Wilson": 30,
    "Whilmer Guerra": 19,
    "Wikelman Gonzalez": 23,
    "Wil Jensen": 27,
    "Wilber Dotel": 22,
    "Wilber Sanchez": 23,
    "Wilberson De Pena": 18,
    "Wilder Dalis": 18,
    "Wilfred Alvarado": 19,
    "Wilfred Veras": 22,
    "Wilfredo Henriquez": 22,
    "Wilfredo Lara": 21,
    "Wilfri De La Cruz": 17,
    "Wilian Bormie": 24,
    "Wilian Trinidad": 19,
    "Wilkel Hernandez": 26,
    "Wilker Reyes": 23,
    "Wilkin Paredes": 21,
    "Wilkin Ramos": 24,
    "Wilking Rodriguez": 35,
    "Will Armbruester": 24,
    "Will Banfield": 25,
    "Will Bednar": 25,
    "Will Brian": 26,
    "Will Bush": 21,
    "Will Cannon": 21,
    "Will Childers": 24,
    "Will Cresswell": 21,
    "Will Dion": 25,
    "Will Frisch": 24,
    "Will Gervase": 23,
    "Will Holland": 27,
    "Will Johnston": 24,
    "Will King": 21,
    "Will Klein": 25,
    "Will Mabrey": 23,
    "Will Robertson": 27,
    "Will Rudy": 23,
    "Will Sanders": 23,
    "Will Schomberg": 24,
    "Will Simpson": 23,
    "Will Smith": 30,
    "Will Taylor": 22,
    "Will Turner": 22,
    "Will Varmette": 22,
    "Will Verdung": 22,
    "Will Vest": 30,
    "Will Vierling": 21,
    "Will Warren": 26,
    "Will Watson": 22,
    "Will Wilson": 26,
    "Willi Castro": 28,
    "William Bergolla": 20,
    "William Contreras": 28,
    "William Fleming": 26,
    "William Kempner": 24,
    "William Lugo": 23,
    "William Maynard": 22,
    "William Silva": 23,
    "Williams Wong": 19,
    "Willian Berti": 19,
    "Willie MacIver": 28,
    "Willson Contreras": 33,
    "Willy Adames": 30,
    "Willy Fanas": 21,
    "Willy Montero": 20,
    "Willy Vasquez": 23,
    "Wilman Diaz": 21,
    "Wilme Mora": 22,
    "Wilmer Flores": 24,
    "Wilmis Paulino": 19,
    "Wilmy Sanchez": 21,
    "Wilson Lopez": 22,
    "Wilson Rodriguez": 20,
    "Wilson Weber": 23,
    "Wilton Lara": 21,
    "Wily Villar": 26,
    "Wilyer Abreu": 26,
    "Winifer Castillo": 18,
    "Winston Santos": 23,
    "Winyer Chourio": 21,
    "Won-Bin Cho": 21,
    "Woo-Suk Go": 26,
    "Woody Hadeen": 22,
    "Wooyeoul Shin": 23,
    "Wuilberth Mendez": 21,
    "Wuilfredo Antunez": 23,
    "Wuilliams Rodriguez": 19,
    "Wuillians Herrera": 21,
    "Wuinder Torres": 18,
    "Wyatt Cheney": 24,
    "Wyatt Crowell": 23,
    "Wyatt Hendrie": 26,
    "Wyatt Henseler": 23,
    "Wyatt Hoffman": 26,
    "Wyatt Hudepohl": 22,
    "Wyatt Langford": 24,
    "Wyatt Mills": 30,
    "Wyatt Olds": 25,
    "Wyatt Sanford": 19,
    "Wyatt Young": 25,
    "Xander Bogaerts": 33,
    "Xander Hamilton": 23,
    "Xavier Cardenas III": 22,
    "Xavier Edwards": 26,
    "Xavier Guillen": 20,
    "Xavier Isaac": 22,
    "Xavier Kolhosser": 21,
    "Xavier Martinez": 22,
    "Xavier Meachem": 22,
    "Xavier Rivas": 22,
    "Xavier Ruiz": 22,
    "Xiomer Guacache": 21,
    "Yacksel Rios": 32,
    "Yadiel Batista": 21,
    "Yadier Crespo": 17,
    "Yadimir Fuentes": 18,
    "Yael Romero": 19,
    "Yahil Melendez": 19,
    "Yaikel Mijares": 19,
    "Yainer Diaz": 27,
    "Yairo Padilla": 18,
    "Yaisel Ramos": 22,
    "Yamal Encarnacion": 21,
    "Yan Cruz": 18,
    "Yancel Guerrero": 21,
    "Yandel Ricardo": 18,
    "Yandro Hernandez": 20,
    "Yandy Diaz": 34,
    "Yanki Baptiste": 20,
    "Yannic Walther": 21,
    "Yanquiel Fernandez": 23,
    "Yanuel Casiano": 18,
    "Yanzel Correa": 20,
    "Yaqui Rivera": 21,
    "Yaramil Hiraldo": 29,
    "Yariel Rodriguez": 28,
    "Yarison Ruiz": 25,
    "Yasmil Bucce": 20,
    "Yassel Garcia": 17,
    "Yassel Soler": 19,
    "Yasser Mercedes": 20,
    "Yatner Crisostomo": 22,
    "Yaxson Lucena": 17,
    "Yeferson Portolatin": 17,
    "Yeferson Silva": 20,
    "Yeferson Vargas": 20,
    "Yehizon Sanchez": 24,
    "Yeiber Cartaya": 22,
    "Yeicer Crespo": 17,
    "Yeider Mindiola": 18,
    "Yeiferth Castillo": 18,
    "Yeiker Reyes": 19,
    "Yeimison Arias": 20,
    "Yeiner Fernandez": 22,
    "Yeison Acosta": 17,
    "Yeison Morrobel": 21,
    "Yeison Oviedo": 17,
    "Yeisy Celesten": 20,
    "Yelinson Betances": 17,
    "Yendry Rojas": 20,
    "Yendy Gomez": 21,
    "Yenfri Sosa": 21,
    "Yennier Cano": 31,
    "Yenrri Rojas": 21,
    "Yensi De La Cruz": 18,
    "Yensi Rivas": 18,
    "Yensy Bello": 22,
    "Yeral Martinez": 22,
    "Yerald Nin": 19,
    "Yeremi Cabrera": 19,
    "Yeremi Villahermosa": 22,
    "Yereny Teus": 21,
    "Yeri Perez": 20,
    "Yeriel Santos": 21,
    "Yerlin Confidan": 22,
    "Yerlin Luis": 19,
    "Yerlin Rodriguez": 23,
    "Yermain Ruiz": 19,
    "Yeuni Munoz": 21,
    "Yeuris Jimenez": 24,
    "Yeycol Soriano": 19,
    "Yhoan Escalona": 19,
    "Yhoangel Aponte": 21,
    "Yhoiker Fajardo": 18,
    "Yhoswar Garcia": 23,
    "Yiddi Cappe": 22,
    "Yilber Diaz": 24,
    "Yilber Herrera": 20,
    "Yilver De Paula": 17,
    "Yimi Presinal": 20,
    "Yimy Tovar": 19,
    "Yirer Garcia": 19,
    "Yoan Moncada": 30,
    "Yoander Rivero": 23,
    "Yoander Santana": 17,
    "Yoandys Veraza": 18,
    "Yoeilin Cespedes": 20,
    "Yoel Correa": 23,
    "Yoel Roque": 18,
    "Yoel Tejeda Jr.": 21,
    "Yoelkis Cespedes": 28,
    "Yoelvin Chirino": 20,
    "Yoelvis Betancourt": 17,
    "Yoendris Gonzalez": 22,
    "Yoerny Junco": 20,
    "Yoffry Solano": 20,
    "Yohairo Cuevas": 21,
    "Yohander Linarez": 20,
    "Yohander Martinez": 23,
    "Yohandy Cruz": 18,
    "Yohandy Morales": 23,
    "Yohel Pozo": 27,
    "Yohemy Nolasco": 21,
    "Yohendrick Pinango": 23,
    "Yohendry Sanchez": 18,
    "Yoiber Ocopio": 20,
    "Yoiber Ruiz": 19,
    "Yojackson Laya": 18,
    "Yojancel Cabrera": 17,
    "Yojanser Calzado": 18,
    "Yokelvin Reyes": 21,
    "Yoldin De La Paz": 23,
    "Yolfran Castillo": 18,
    "Yolmer Sanchez": 33,
    "Yonaiker Hernandez": 17,
    "Yonatan Henriquez": 20,
    "Yonathan Perlaza": 26,
    "Yondrei Rojas": 22,
    "Yoneiker Lugo": 18,
    "Yoniel Curet": 23,
    "Yonny Hernandez": 27,
    "Yophery Rodriguez": 19,
    "Yorber Semprun": 17,
    "Yordalin Pena": 20,
    "Yordan Alvarez": 28,
    "Yordani Martinez": 18,
    "Yordani Soto": 16,
    "Yordanny Monegro": 22,
    "Yordany De Los Santos": 20,
    "Yordin Chalas": 21,
    "Yordy Herrera": 20,
    "Yordys Valdes": 23,
    "Yorger Bautista": 17,
    "Yorlin Calderon": 23,
    "Yorman Galindez": 21,
    "Yorman Gomez": 22,
    "Yorman Licourt": 21,
    "Yorvi Pirela": 20,
    "Yorvin Morla": 19,
    "Yorvit Diaz": 17,
    "Yoryi Simarra": 20,
    "Yosander Asencio": 20,
    "Yosber Sanchez": 24,
    "Yoshinobu Yamamoto": 27,
    "Yosneiker Rivas": 19,
    "Yosver Zulueta": 27,
    "Yosweld Vasquez": 20,
    "Yovannki Pascual": 22,
    "Yovanny Cabrera": 24,
    "Yovanny Cruz": 25,
    "Yovanny Duran": 17,
    "Yovanny Rodriguez": 18,
    "Yoxander Benitez": 18,
    "Yoyner Fajardo": 26,
    "Yu Darvish": 39,
    "Yu-Min Lin": 21,
    "Yuhi Sako": 25,
    "Yujanyer Herrera": 20,
    "Yulian Barreto": 17,
    "Yulian Quintana": 24,
    "Yunior Amparo": 18,
    "Yunior Marte": 21,
    "Yunior Quezada": 19,
    "Yunior Severino": 25,
    "Yunior Tur": 25,
    "Yusei Kikuchi": 34,
    "Zac Gallen": 30,
    "Zac Leigh": 27,
    "Zac Veen": 24,
    "Zach Agnos": 24,
    "Zach Arnold": 24,
    "Zach Barnes": 26,
    "Zach Bryant": 27,
    "Zach Brzykcy": 25,
    "Zach Cole": 24,
    "Zach Cole Jr.": 25,
    "Zach Daudet": 22,
    "Zach DeLoach": 26,
    "Zach Dezenzo": 25,
    "Zach Eflin": 31,
    "Zach Ehrhard": 22,
    "Zach Evans": 22,
    "Zach Fogell": 24,
    "Zach Franklin": 26,
    "Zach Fruit": 25,
    "Zach Greene": 28,
    "Zach Harris": 21,
    "Zach Humphreys": 27,
    "Zach Jacobs": 23,
    "Zach Kokoska": 26,
    "Zach Levenson": 23,
    "Zach MacDonald": 21,
    "Zach Maxwell": 24,
    "Zach McCambley": 26,
    "Zach McKinstry": 30,
    "Zach Messinger": 25,
    "Zach Morgan": 25,
    "Zach Neto": 24,
    "Zach Peek": 27,
    "Zach Penrod": 28,
    "Zach Thornton": 23,
    "Zach Willeman": 29,
    "Zachary Cawyer": 22,
    "Zachary Redner": 20,
    "Zack Gelof": 26,
    "Zack Lee": 24,
    "Zack Littell": 30,
    "Zack Morris": 24,
    "Zack Qin": 18,
    "Zack Short": 30,
    "Zack Showalter": 21,
    "Zack Weiss": 33,
    "Zack Wheeler": 35,
    "Zak Kent": 27,
    "Zander Darby": 22,
    "Zander Mueth": 20,
    "Zane Barnhart": 23,
    "Zane Mills": 24,
    "Zane Morehouse": 25,
    "Zane Russell": 25,
    "Zane Taylor": 23,
    "Zane Zielinski": 23,
    "Zavier Warren": 26,
    "Zebby Matthews": 25,
    "Zeke Wood": 25,
    "Zeus Nunez": 18,
    "Zuher Yousuf": 19,
    "Zyhir Hope": 21,
}

# Pitchers with minimal MLB track record whose projections are unreliable
# These get an 80% discount regardless of fantrax data
UNPROVEN_PITCHERS = {
    "Forrest Whitley",   # ~10 career IP, former top prospect
}

# Dynasty Pitcher Discount - Dynasty leagues heavily discount pitchers due to:
# - Injury risk (TJ surgery, arm injuries)
# - Volatility (performance fluctuations year-to-year)
# - Shorter careers compared to hitters
# This multiplier is applied to all pitcher values before other adjustments
DYNASTY_PITCHER_DISCOUNT = 0.55

# Elite young players who deserve ADDITIONAL boost beyond the automatic elite category boost
# The automatic boost (in calculate_hitter_value) handles: HR≥35, SB≥35, AVG≥.300, RBI≥110
# This manual list is for truly exceptional talents whose dynasty value exceeds even that
# Format: "Player Name": bonus_multiplier (1.15 = +15% ADDITIONAL boost, stacks with automatic)
ELITE_YOUNG_PLAYERS = {
    # Tier 1: Consensus Top 5 dynasty assets
    "Bobby Witt Jr.": 1.30,       # 26yo SS, consensus #1-2, 30/30 MVP caliber
    "Juan Soto": 1.20,            # 27yo OF, consensus #3, elite plate discipline
    "Corbin Carroll": 1.20,       # 25yo OF, consensus #5, elite speed/plate discipline
    # Tier 2: Consensus Top 10 dynasty assets
    "Elly De La Cruz": 1.12,      # 24yo SS, consensus #7, elite speed/power upside
    "Gunnar Henderson": 1.12,     # 24yo SS, consensus #10, elite power
    "Jackson Chourio": 1.18,      # 22yo OF, 5-tool potential, youngest superstar
    "Jackson Holliday": 1.18,     # 22yo 2B, #1 prospect pedigree, elite bat
    "Julio Rodriguez": 1.15,      # 25yo OF, superstar ceiling when healthy
    # Elite young pitchers - dynasty premium for young aces with elite stuff
    "Paul Skenes": 1.20,          # 23yo SP, 2025 NL Cy Young winner, elite stuff but only 1.5yr track record
    "Garrett Crochet": 1.30,      # 26yo SP, elite strikeout ability, ace upside
    # Tarik Skubal, Cristopher Sanchez moved to PROVEN_VETERAN_STARS (29yo)
    "Yoshinobu Yamamoto": 1.18,   # 27yo SP, 3rd in 2025 NL Cy Young, premium ace
    "Hunter Brown": 1.15,         # 27yo SP, 3rd in 2025 AL Cy Young, emerging ace
    # 2025 Award Winners - ROY and MVP contenders
    # Cal Raleigh removed - already has 1.32x in PROVEN_VETERAN_STARS (catcher premium)
    "Nick Kurtz": 1.18,           # 24yo 1B, 2025 AL ROY winner, 36 HR rookie season
    "Drake Baldwin": 1.22,        # 24yo C, 2025 NL ROY winner, catcher scarcity + youth
    "Jacob Wilson": 1.10,         # 24yo SS, 2nd in 2025 AL ROY, .311 AVG
    # Tier 2: Elite young stars with consensus backing (18-22% boost)
    "James Wood": 1.22,           # 23yo OF, elite prospect pedigree, consensus top 20
    "Wyatt Langford": 1.08,       # 25yo OF, power upside, consensus top 30 but .755 OPS projection
    # Tier 3: Established young stars (6-10% boost)
    "CJ Abrams": 1.08,            # 25yo SS, speed/power (consensus ~47)
    "Anthony Volpe": 1.06,        # 25yo SS, premium position
    "Evan Carter": 1.06,          # 24yo OF, elite plate discipline
    "Masyn Winn": 1.06,           # 24yo SS, speed/defense combo
    # Tier 4: Rising young stars (5-8% boost)
    "Jordan Lawlar": 1.05,        # 23yo SS, elite prospect pedigree
    "Jackson Merrill": 1.08,      # 23yo OF, breakout 2024
    "Pete Crow-Armstrong": 1.12,  # 24yo OF, 30/30 potential, elite dynasty asset
}

# Proven veteran stars - REMOVED most entries after calibration analysis
# Calibration showed these boosts were making overvaluation worse
# Now only keeping very small boosts for the truly elite under-28 players
# The age curve and base formula should handle veteran value appropriately
PROVEN_VETERAN_STARS = {
    # Proven young stars - should rank above unproven young players like Wood/PCA
    "Vladimir Guerrero Jr.": 1.16,  # 27yo, proven elite 1B, .900 OPS
    "Ronald Acuna Jr.": 1.08,       # 28yo, former MVP, elite when healthy
    "Fernando Tatis Jr.": 1.18,     # 27yo, proven star, 30+ HR power
    "Cal Raleigh": 1.32,            # 29yo, elite C, 39 HR - catcher premium
    "Kyle Tucker": 1.12,            # 29yo, proven elite OF, .861 OPS - prime years
    "Tarik Skubal": 1.14,           # 29yo SP, 2025 AL Cy Young winner, consensus #11
    "Cristopher Sanchez": 1.12,     # 29yo SP, 2nd in 2025 NL Cy Young, elite LHP
    # Shohei Ohtani - unique two-way player, consensus #1-2 dynasty asset
    "Shohei Ohtani": 1.27,  # 31yo but only true two-way player in baseball history
    # Proven veterans with elite track records - age curve is too harsh on these stars
    "Rafael Devers": 1.21,      # 29yo, consistent .900+ OPS, prime age
    "Jose Ramirez": 1.15,       # 33yo, 5.8 WAR, 30 HR/44 SB elite power-speed
    "Corey Seager": 1.16,       # 32yo, elite SS, World Series MVP
    "Bryce Harper": 1.18,       # 33yo, former MVP, still elite production
    "Trea Turner": 1.30,        # 33yo, elite SS, 2025 NL batting title (.304)
    "Freddie Freeman": 1.58,    # 36yo, still elite .869 OPS in 2025
}

# Pitcher handedness (L = Left, R = Right)
# Used to provide accurate information in AI analysis
PITCHER_HANDEDNESS = {
    # Starters - Left-handed
    "Tarik Skubal": "L", "Garrett Crochet": "L", "Max Fried": "L", "Chris Sale": "L",
    "Framber Valdez": "L", "Jesus Luzardo": "L", "Blake Snell": "L", "Shane McClanahan": "L",
    "Nick Lodolo": "L", "Ranger Suarez": "L", "David Peterson": "L", "Ryan Weathers": "L",
    "Robert Gasser": "L", "Shota Imanaga": "L", "Cristopher Sanchez": "L", "MacKenzie Gore": "L",
    "Patrick Corbin": "L", "Eduardo Rodriguez": "L", "Sean Manaea": "L", "Cody Bradford": "L",
    "Andrew Heaney": "L", "Rich Hill": "L", "Jordan Montgomery": "L", "JP Sears": "L",
    "Matthew Boyd": "L", "Tyler Anderson": "L", "Steven Matz": "L", "Kyle Freeland": "L",
    "DL Hall": "L", "Drew Smyly": "L", "Mitchell Parker": "L", "Carlos Rodon": "L",
    "Kris Bubic": "L", "Jose Quintana": "L", "Yusei Kikuchi": "L", "Reid Detmers": "L",
    # Starters - Right-handed
    "Paul Skenes": "R", "Logan Webb": "R", "Logan Gilbert": "R", "Bryan Woo": "R",
    "Hunter Brown": "R", "Jacob deGrom": "R", "Yoshinobu Yamamoto": "R", "Hunter Greene": "R",
    "George Kirby": "R", "Cole Ragans": "R", "Joe Ryan": "R", "Spencer Schwellenbach": "R",
    "Dylan Cease": "R", "Nathan Eovaldi": "R", "Sonny Gray": "R", "Nick Pivetta": "R",
    "Freddy Peralta": "R", "Zack Wheeler": "R", "Kevin Gausman": "R", "Luis Castillo": "R",
    "Pablo Lopez": "R", "Brandon Woodruff": "R", "Tyler Glasnow": "R", "Gerrit Cole": "R",
    "Kyle Bradish": "R", "Joe Musgrove": "R", "Chase Burns": "R", "Joe Boyle": "R",
    "Seth Lugo": "R", "Jared Jones": "R", "Tanner Bibee": "R", "Luis Gil": "R",
    "Michael King": "R", "Grayson Rodriguez": "R", "Corbin Burnes": "R", "Roki Sasaki": "R",
    "Bryce Miller": "R", "Bailey Ober": "R", "Brady Singer": "R", "Cade Horton": "R",
    "AJ Smith-Shawver": "R", "Gavin Williams": "R", "Gavin Stone": "R", "Mitch Keller": "R",
    "Aaron Nola": "R", "Sandy Alcantara": "R", "Marcus Stroman": "R", "Charlie Morton": "R",
    "Max Scherzer": "R", "Justin Verlander": "R", "Zac Gallen": "R", "Merrill Kelly": "R",
    "Chris Bassitt": "R", "Jack Flaherty": "R", "Reynaldo Lopez": "R", "Forrest Whitley": "R",
    "Clarke Schmidt": "R", "Tobias Myers": "R", "Michael Wacha": "R", "Taj Bradley": "R",
    "Zach Eflin": "R", "Frankie Montas": "R", "Miles Mikolas": "R", "Luis Severino": "R",
    # Relievers - Left-handed
    "Aroldis Chapman": "L", "Alex Vesia": "L", "Tanner Scott": "L", "Adrian Morejon": "L",
    "A.J. Minter": "L", "Matt Strahm": "L", "JoJo Romero": "L", "Tyler Holton": "L",
    "Jose Alvarado": "L", "Caleb Thielbar": "L", "Taylor Rogers": "L", "Dylan Lee": "L",
    "Garrett Cleavinger": "L", "Steven Okert": "L", "Tim Hill": "L", "Brooks Raley": "L",
    "Brent Suter": "L", "Andrew Chafin": "L", "Jake Diekman": "L", "Sam Moll": "L",
    # Relievers - Right-handed
    "Mason Miller": "R", "Edwin Diaz": "R", "Cade Smith": "R", "Jhoan Duran": "R",
    "Josh Hader": "R", "Andres Munoz": "R", "Devin Williams": "R", "David Bednar": "R",
    "Griffin Jax": "R", "Raisel Iglesias": "R", "Abner Uribe": "R", "Ryan Walker": "R",
    "Jeff Hoffman": "R", "Ryan Helsley": "R", "Daniel Palencia": "R", "Pete Fairbanks": "R",
    "Trevor Megill": "R", "Emilio Pagan": "R", "Carlos Estevez": "R", "Kenley Jansen": "R",
    "Grant Taylor": "R", "Bryan Abreu": "R", "Jeremiah Estrada": "R", "Garrett Whitlock": "R",
    "Robert Suarez": "R", "Matt Brash": "R", "Tyler Rogers": "R", "Bryan King": "R",
    "Phil Maton": "R", "Luke Weaver": "R", "Gabe Speier": "R", "Orion Kerkering": "R",
    "Louis Varland": "R", "Seranthony Dominguez": "R", "Camilo Doval": "R", "Robert Stephenson": "R",
    "Clayton Beeter": "R", "Robert Garcia": "R", "Victor Vodnik": "R", "Blake Treinen": "R",
    "Hunter Harvey": "R", "Hunter Gaddis": "R", "Cole Sands": "R", "Yimi Garcia": "R",
    "Kyle Finnegan": "R", "Lucas Erceg": "R", "Bryan Baker": "R", "Kirby Yates": "R",
    "Jordan Leasure": "R", "Brusdar Graterol": "R", "Kevin Ginkel": "R", "Craig Kimbrel": "R",
    "Emmanuel Clase": "R", "Felix Bautista": "R", "Jordan Romano": "R", "Clay Holmes": "R",
}


# ============================================================================
# BLENDED STATS CALCULATOR (Projections + Actual Performance)
# ============================================================================

def get_blended_hitter_stats(player_name: str, projections: dict, actual_stats: dict = None) -> dict:
    """
    Blend pre-season projections with actual in-season stats.

    Early season: Heavily weight projections (small sample size)
    Mid-season: 50/50 blend
    Late season: Heavily weight actual pace

    Args:
        player_name: Player's name
        projections: Pre-season projection dict (HR, SB, AVG, RBI, etc.)
        actual_stats: Actual in-season stats dict (G, HR, SB, AVG, RBI, etc.) or None

    Returns:
        Blended stats dict for use in value calculations
    """
    # If no actual stats, return projections as-is
    if not actual_stats or actual_stats.get('type') != 'hitter':
        return projections

    games = actual_stats.get('G', 0)

    # Minimum games threshold - don't use actual stats until meaningful sample
    if games < 20:
        return projections

    # Calculate projection weight based on games played
    # More games = more weight on actual performance
    if games < 40:
        proj_weight = 0.80  # 80% projections, 20% pace
    elif games < 60:
        proj_weight = 0.65  # 65% projections, 35% pace
    elif games < 90:
        proj_weight = 0.50  # 50/50 blend
    elif games < 120:
        proj_weight = 0.35  # 35% projections, 65% pace
    else:
        proj_weight = 0.20  # 20% projections, 80% pace (late season)

    actual_weight = 1.0 - proj_weight

    # Calculate full-season pace from actual stats
    games_factor = 162.0 / games if games > 0 else 1.0

    blended = {}

    # Counting stats - blend projected with pace
    for stat in ['HR', 'SB', 'R', 'RBI']:
        proj_val = projections.get(stat, 0)
        actual_val = actual_stats.get(stat, 0)
        pace_val = actual_val * games_factor
        blended[stat] = (proj_val * proj_weight) + (pace_val * actual_weight)

    # Rate stats - blend directly (already rate-based)
    # AVG: need to handle string format from Fantrax
    proj_avg = projections.get('AVG', 0.250)
    actual_avg_str = actual_stats.get('AVG', '.250')
    try:
        actual_avg = float(actual_avg_str.replace('.', '0.')) if isinstance(actual_avg_str, str) else float(actual_avg_str)
    except:
        actual_avg = 0.250
    blended['AVG'] = (proj_avg * proj_weight) + (actual_avg * actual_weight)

    # OPS: same handling
    proj_ops = projections.get('OPS', 0.750)
    actual_ops_str = actual_stats.get('OPS', '.750')
    try:
        actual_ops = float(actual_ops_str.replace('.', '0.')) if isinstance(actual_ops_str, str) else float(actual_ops_str)
    except:
        actual_ops = 0.750
    blended['OPS'] = (proj_ops * proj_weight) + (actual_ops * actual_weight)

    # SO (strikeouts) - pace
    proj_so = projections.get('SO', 100)
    actual_so = actual_stats.get('SO', actual_stats.get('K', 0))  # Some sources use K
    if actual_so == 0:
        # Estimate from AB if not available
        actual_so = actual_stats.get('AB', 0) * 0.22  # ~22% K rate estimate
    pace_so = actual_so * games_factor
    blended['SO'] = (proj_so * proj_weight) + (pace_so * actual_weight)

    # Store games played and weights for debugging/display
    blended['_games'] = games
    blended['_proj_weight'] = proj_weight
    blended['_actual_weight'] = actual_weight

    return blended


# ============================================================================
# VALUE CALCULATOR
# ============================================================================

class DynastyValueCalculator:
    """Calculate dynasty value incorporating projections, age, and prospect status."""
    
    # Category weights for H2H 7-category leagues
    # Hitting: R, HR, SB, RBI, SO, AVG, OPS (sum = 1.0)
    HITTING_WEIGHTS = {
        'r': 0.14,      # Runs
        'hr': 0.16,     # Home Runs (power premium)
        'sb': 0.14,     # Stolen Bases
        'rbi': 0.14,    # RBI
        'so': 0.06,     # Strikeouts (inverse - lower is better)
        'avg': 0.17,    # Batting Average (rate stat premium)
        'ops': 0.19,    # OPS (rate stat premium)
    }

    # Pitching: K, ERA, WHIP, K/BB, SV+HLD, L, QS (sum = 1.0)
    PITCHING_WEIGHTS = {
        'k': 0.16,      # Strikeouts
        'era': 0.18,    # ERA (rate stat premium)
        'whip': 0.16,   # WHIP (rate stat premium)
        'k_bb': 0.12,   # K/BB Ratio
        'sv_hld': 0.16, # Saves + Holds
        'l': 0.05,      # Losses (inverse - lower is better)
        'qs': 0.17,     # Quality Starts
    }
    
    # Position scarcity multipliers
    POSITION_SCARCITY = {
        'C': 1.15,
        'SS': 1.10,
        '2B': 1.05,
        '3B': 1.00,
        '1B': 0.95,
        'OF': 1.00,
        'SP': 1.10,
        'RP': 0.95,
    }
    
    @staticmethod
    def calculate_hitter_value(player: Player, actual_stats: dict = None) -> float:
        """Calculate hitting value from projections (0-100 scale).

        Args:
            player: Player object
            actual_stats: Optional dict of actual in-season stats for blending
        """
        # Check for projections
        proj = HITTER_PROJECTIONS.get(player.name)
        
        if proj:
            value = 0.0

            # AVG: .300+ elite, .270 average, .240 below average
            # Steeper curve to penalize low averages
            if proj['AVG'] >= 0.300:
                avg_score = 100 + (proj['AVG'] - 0.300) * 300  # Elite bonus
            elif proj['AVG'] >= 0.270:
                avg_score = 75 + (proj['AVG'] - 0.270) * 833  # 75-100 for above avg
            elif proj['AVG'] >= 0.240:
                avg_score = 40 + (proj['AVG'] - 0.240) * 1167  # 40-75 for below avg
            else:
                avg_score = max(proj['AVG'] / 0.240 * 40, 10)  # Poor
            avg_score = min(avg_score, 115)
            value += avg_score * DynastyValueCalculator.HITTING_WEIGHTS['avg']

            # OPS: .950+ elite, .800 average, .700 below average
            if proj['OPS'] >= 0.950:
                ops_score = 100 + (proj['OPS'] - 0.950) * 200
            elif proj['OPS'] >= 0.850:
                ops_score = 85 + (proj['OPS'] - 0.850) * 150
            elif proj['OPS'] >= 0.750:
                ops_score = 55 + (proj['OPS'] - 0.750) * 300
            elif proj['OPS'] >= 0.650:
                ops_score = 25 + (proj['OPS'] - 0.650) * 300
            else:
                ops_score = max(proj['OPS'] / 0.650 * 25, 5)
            ops_score = min(ops_score, 115)
            value += ops_score * DynastyValueCalculator.HITTING_WEIGHTS['ops']

            # HR: 40+ elite, 25 average, 15 below average
            if proj['HR'] >= 40:
                hr_score = 100 + (proj['HR'] - 40) * 2
            elif proj['HR'] >= 25:
                hr_score = 70 + (proj['HR'] - 25) * 2
            elif proj['HR'] >= 15:
                hr_score = 40 + (proj['HR'] - 15) * 3
            else:
                hr_score = max(proj['HR'] / 15 * 40, 5)
            hr_score = min(hr_score, 115)
            value += hr_score * DynastyValueCalculator.HITTING_WEIGHTS['hr']

            # R: 100+ elite, 80 average, 60 below average
            if proj['R'] >= 100:
                r_score = 95 + (proj['R'] - 100) * 1
            elif proj['R'] >= 80:
                r_score = 70 + (proj['R'] - 80) * 1.25
            elif proj['R'] >= 60:
                r_score = 40 + (proj['R'] - 60) * 1.5
            else:
                r_score = max(proj['R'] / 60 * 40, 10)
            r_score = min(r_score, 115)
            value += r_score * DynastyValueCalculator.HITTING_WEIGHTS['r']

            # RBI: 100+ elite, 80 average, 60 below average
            if proj['RBI'] >= 100:
                rbi_score = 95 + (proj['RBI'] - 100) * 1
            elif proj['RBI'] >= 80:
                rbi_score = 70 + (proj['RBI'] - 80) * 1.25
            elif proj['RBI'] >= 60:
                rbi_score = 40 + (proj['RBI'] - 60) * 1.5
            else:
                rbi_score = max(proj['RBI'] / 60 * 40, 10)
            rbi_score = min(rbi_score, 115)
            value += rbi_score * DynastyValueCalculator.HITTING_WEIGHTS['rbi']

            # SB: 30+ elite, 15 average, 5 below average
            if proj['SB'] >= 30:
                sb_score = 95 + (proj['SB'] - 30) * 2
            elif proj['SB'] >= 15:
                sb_score = 60 + (proj['SB'] - 15) * 2.33
            elif proj['SB'] >= 5:
                sb_score = 30 + (proj['SB'] - 5) * 3
            else:
                sb_score = max(proj['SB'] * 6, 5)
            sb_score = min(sb_score, 115)
            value += sb_score * DynastyValueCalculator.HITTING_WEIGHTS['sb']

            # SO (inverse - lower is better): 90 elite, 130 average, 170 poor
            if proj['SO'] <= 90:
                so_score = 95 + (90 - proj['SO']) * 0.5
            elif proj['SO'] <= 130:
                so_score = 70 + (130 - proj['SO']) * 0.625
            elif proj['SO'] <= 170:
                so_score = 35 + (170 - proj['SO']) * 0.875
            else:
                so_score = max(35 - (proj['SO'] - 170) * 0.5, 5)
            so_score = min(so_score, 115)
            value += so_score * DynastyValueCalculator.HITTING_WEIGHTS['so']

            # ============ AUTOMATIC ELITE YOUNG HITTER BOOST ============
            # Young players (≤25) with elite single-category production get a boost
            # This compensates for the balanced formula penalizing specialists
            # Uses BLENDED stats (projections + actual pace) when in-season data available
            if player.age > 0 and player.age <= 25:
                elite_boost = 1.0
                elite_categories = 0

                # Get blended stats for elite boost evaluation
                # This allows breakout seasons to be recognized mid-year
                blended = get_blended_hitter_stats(player.name, proj, actual_stats)
                blended_hr = blended.get('HR', proj['HR'])
                blended_sb = blended.get('SB', proj['SB'])
                blended_avg = blended.get('AVG', proj['AVG'])
                blended_rbi = blended.get('RBI', proj['RBI'])

                # Elite power: 35+ HR
                if blended_hr >= 40:
                    elite_boost += 0.12  # 40+ HR is exceptional
                    elite_categories += 1
                elif blended_hr >= 35:
                    elite_boost += 0.08
                    elite_categories += 1

                # Elite speed: 35+ SB
                if blended_sb >= 40:
                    elite_boost += 0.12  # 40+ SB is exceptional
                    elite_categories += 1
                elif blended_sb >= 35:
                    elite_boost += 0.08
                    elite_categories += 1

                # Elite contact: .300+ AVG
                if blended_avg >= 0.310:
                    elite_boost += 0.10  # .310+ is exceptional
                    elite_categories += 1
                elif blended_avg >= 0.300:
                    elite_boost += 0.06
                    elite_categories += 1

                # Elite run production: 110+ RBI
                if blended_rbi >= 110:
                    elite_boost += 0.08
                    elite_categories += 1

                # Multi-category elite bonus (5-tool players)
                if elite_categories >= 2:
                    elite_boost += 0.05  # Extra boost for multi-category elite

                # Apply automatic boost (capped at 25% to avoid stacking too high)
                elite_boost = min(elite_boost, 1.25)
                value *= elite_boost

        else:
            # Fall back to Fantrax score with discount based on rank
            if player.fantrax_rank < 100:
                value = player.fantrax_score * 0.80
            elif player.fantrax_rank < 200:
                value = player.fantrax_score * 0.65
            elif player.fantrax_rank < 400:
                value = player.fantrax_score * 0.50
            else:
                value = player.fantrax_score * 0.35

        # Dynasty adjustments (with reduced stacking) - includes manual ELITE_YOUNG_PLAYERS boost
        value = DynastyValueCalculator._apply_dynasty_adjustments(player, value, is_hitter=True)

        return value  # No cap - show true dynasty value
    
    @staticmethod
    def calculate_pitcher_value(player: Player) -> float:
        """Calculate pitching value from projections (0-100 scale)."""
        # Check if reliever first (for SV+HLD integration)
        rp_proj = RELIEVER_PROJECTIONS.get(player.name)
        sp_proj = PITCHER_PROJECTIONS.get(player.name)
        
        if rp_proj:
            # Use reliever-specific calculation with SV+HLD emphasis
            return DynastyValueCalculator._calculate_reliever_value(player, rp_proj)
        elif sp_proj:
            return DynastyValueCalculator._calculate_sp_value(player, sp_proj)
        else:
            # No projections - use Fantrax data with heavy discount
            # Rank-based: lower rank = lower value
            if player.fantrax_rank < 100:
                value = player.fantrax_score * 0.85
            elif player.fantrax_rank < 200:
                value = player.fantrax_score * 0.75
            elif player.fantrax_rank < 300:
                value = player.fantrax_score * 0.60
            elif player.fantrax_rank < 500:
                value = player.fantrax_score * 0.45  # Keegan Akin is rank 418
            else:
                value = player.fantrax_score * 0.30
            
            # Extra discount for RPs without projections (replaceable)
            if 'RP' in player.position:
                value *= 0.70
            
            value = DynastyValueCalculator._apply_dynasty_adjustments(player, value, is_hitter=False)
            return value  # No cap - show true dynasty value
    
    @staticmethod
    def _calculate_sp_value(player: Player, proj: dict) -> float:
        """Calculate starting pitcher value."""
        value = 0.0
        
        # Weights for SP categories aligned with league scoring (sum = 1.0)
        # Note: SV+HLD not applicable to SP, redistribute to other pitching cats
        sp_weights = {
            'k': 0.20,      # Strikeouts - very important for SP
            'era': 0.22,    # ERA - premium rate stat
            'whip': 0.20,   # WHIP - premium rate stat
            'qs': 0.20,     # Quality Starts - SP specialty
            'k_bb': 0.13,   # K/BB ratio (command)
            'l': 0.05,      # Losses - minor factor
        }
        
        # K (normalize around 190 for aces)
        k_score = min((proj['K'] / 190) * 100, 115)
        value += k_score * sp_weights['k']
        
        # ERA (inverse - elite ERA ~2.80, average ~4.00)
        # Use ratio-based scoring: lower ERA = higher score
        era_score = min((3.80 / max(proj['ERA'], 2.50)) * 75, 115)
        value += era_score * sp_weights['era']
        
        # WHIP (inverse - elite WHIP ~1.00, average ~1.25)
        whip_score = min((1.18 / max(proj['WHIP'], 0.90)) * 75, 115)
        value += whip_score * sp_weights['whip']
        
        # QS (normalize around 18 for workhorse)
        qs_score = min((proj['QS'] / 18) * 100, 115)
        value += qs_score * sp_weights['qs']
        
        # K/BB ratio - estimate BB from WHIP
        # WHIP = (H + BB) / IP, estimate H/9 based on WHIP tier
        ip = proj['IP'] if proj['IP'] > 0 else 1
        whip = proj['WHIP']
        if whip < 1.05:
            h_per_9 = 7.2  # Elite - fewer hits
        elif whip < 1.15:
            h_per_9 = 8.0  # Good
        elif whip < 1.25:
            h_per_9 = 8.5  # Average
        else:
            h_per_9 = 9.0  # Below average
        
        est_hits = (h_per_9 * ip) / 9
        est_bb = max((whip * ip) - est_hits, ip * 0.15)  # Floor of ~1.5 BB/9
        k_bb_ratio = proj['K'] / est_bb if est_bb > 0 else 5.0
        
        # K/BB scoring: elite is 5.0+, good is 3.5, average is 2.5
        k_bb_score = min((k_bb_ratio / 3.5) * 85, 115)
        value += k_bb_score * sp_weights['k_bb']
        
        # Losses (inverse - fewer is better, normalize around 9)
        l_score = max(100 - ((proj['L'] / 9) * 40), 40)
        value += l_score * sp_weights['l']

        value = DynastyValueCalculator._apply_dynasty_adjustments(player, value, is_hitter=False)

        # Apply unproven pitcher discount
        # If pitcher is 26+ with very low Fantrax score and high rank, projections are untrustworthy
        value = DynastyValueCalculator._apply_unproven_pitcher_discount(player, value)

        return value  # No cap - show true dynasty value
    
    @staticmethod
    def _calculate_reliever_value(player: Player, proj: dict) -> float:
        """Calculate reliever value with SV+HLD emphasis but scaled appropriately.

        Uses tiered discounts based on SV+HD to properly value both elite closers
        and high-leverage setup men in SV+HD leagues:
        - Elite (30+ SV+HD): No RP discount, +15% dynasty relief
        - High Leverage (20-29 SV+HD): 0.92 RP discount, +8% dynasty relief
        - Low Leverage (<20 SV+HD): 0.85 RP discount, no dynasty relief
        """
        value = 0.0

        # Combined SV+HLD - elite closers (35+) get full value, setup men less
        sv_hld = proj.get('SV', 0) + proj.get('HD', 0)

        # Tiered SV+HLD scoring - only elite closers get high scores
        if sv_hld >= 35:
            sv_hld_score = 90 + (sv_hld - 35) * 2  # Elite closers: 90-100
        elif sv_hld >= 25:
            sv_hld_score = 60 + (sv_hld - 25) * 3  # Good closers: 60-90
        elif sv_hld >= 15:
            sv_hld_score = 30 + (sv_hld - 15) * 3  # Setup men: 30-60
        else:
            sv_hld_score = sv_hld * 2  # Low leverage: 0-30

        value += sv_hld_score * 0.35  # SV+HLD is primary RP value

        # Strikeouts (less weight - RPs have fewer opportunities)
        k_score = min((proj['K'] / 90) * 60, 70)  # Cap at 70
        value += k_score * 0.20

        # ERA
        era_score = max(70 - ((proj['ERA'] - 2.50) * 20), 20)
        value += era_score * 0.18

        # WHIP
        whip_score = max(70 - ((proj['WHIP'] - 1.00) * 40), 20)
        value += whip_score * 0.15

        # K rate bonus for high-K relievers
        k_per_ip = proj['K'] / proj['IP'] if proj['IP'] > 0 else 0
        if k_per_ip >= 1.3:
            value += 8
        elif k_per_ip >= 1.1:
            value += 4

        # Tiered reliever discount based on SV+HD
        # Elite relievers (closers and high-hold setup men) get reduced/no discount
        if sv_hld >= 30:
            # Elite: No RP discount
            rp_discount = 1.0
            dynasty_relief = 1.15  # +15% to offset harsh dynasty pitcher discount
        elif sv_hld >= 20:
            # High leverage: Reduced discount
            rp_discount = 0.92
            dynasty_relief = 1.08  # +8% dynasty relief
        else:
            # Low leverage: Standard discount
            rp_discount = 0.85
            dynasty_relief = 1.0  # No relief

        value = value * rp_discount

        # Apply dynasty adjustments (age, prospect status) - same as SP and hitters
        value = DynastyValueCalculator._apply_dynasty_adjustments(player, value, is_hitter=False)

        # Apply dynasty relief for high-leverage relievers
        value = value * dynasty_relief

        # Apply unproven pitcher discount
        value = DynastyValueCalculator._apply_unproven_pitcher_discount(player, value)

        return value  # No cap - show true dynasty value
    
    @staticmethod
    def _apply_dynasty_adjustments(player: Player, base_value: float, is_hitter: bool) -> float:
        """Apply dynasty-specific adjustments (age, prospect status, position scarcity)."""
        value = base_value

        # Apply pitcher dynasty discount - pitchers are heavily discounted in dynasty formats
        # due to injury risk, volatility, and shorter careers
        # Pitchers peak 27-31, so discount tiers are adjusted accordingly
        if not is_hitter:
            if player.age > 0 and player.age <= 24:
                value *= 0.80  # Reduced discount for young elite pitchers (Skenes, etc.)
            elif player.age > 0 and player.age <= 31:
                value *= 0.65  # Moderate discount for prime-age pitchers (peak years)
            else:
                value *= DYNASTY_PITCHER_DISCOUNT  # Full discount for 32+ pitchers

        bonus_multiplier = 1.0  # Track bonuses to cap stacking

        # Age adjustments - Dynasty leagues value youth but elite veterans still have significant value
        # Calibration against FHQ/HKB consensus shows we need moderate decline, not extreme
        # Young players have longest runway, older players decline but elite production matters
        if player.age > 0:
            if is_hitter:
                # Hitter age curve - peak 25-28, decline starts at 29
                if player.age <= 19:
                    bonus_multiplier += 0.20  # Extreme youth premium
                elif player.age <= 21:
                    bonus_multiplier += 0.15  # Youth premium
                elif player.age <= 24:
                    bonus_multiplier += 0.10  # Approaching prime
                elif player.age <= 26:
                    bonus_multiplier += 0.00  # Peak prime years (baseline)
                elif player.age <= 28:
                    bonus_multiplier -= 0.10  # Late prime, slight decline
                elif player.age <= 30:
                    bonus_multiplier -= 0.22  # Post-prime, moderate decline
                elif player.age <= 32:
                    bonus_multiplier -= 0.35  # Early 30s (Judge, Ramirez still elite)
                elif player.age <= 34:
                    bonus_multiplier -= 0.50  # Mid 30s decline (Betts, Harper)
                elif player.age <= 36:
                    bonus_multiplier -= 0.65  # Late 30s (Freeman)
                else:  # 37+
                    bonus_multiplier -= 0.78  # End of career
            else:
                # Pitcher age curve - peak 27-31, decline starts at 32
                # Pitchers peak later than hitters and elite arms maintain into early 30s
                if player.age <= 19:
                    bonus_multiplier += 0.20  # Extreme youth premium
                elif player.age <= 21:
                    bonus_multiplier += 0.15  # Youth premium
                elif player.age <= 24:
                    bonus_multiplier += 0.10  # Young arm developing
                elif player.age <= 27:
                    bonus_multiplier += 0.05  # Entering prime
                elif player.age <= 31:
                    bonus_multiplier += 0.00  # Peak prime years (baseline) - extended for pitchers
                elif player.age <= 33:
                    bonus_multiplier -= 0.15  # Early 30s, slight decline
                elif player.age <= 35:
                    bonus_multiplier -= 0.35  # Mid 30s decline
                elif player.age <= 37:
                    bonus_multiplier -= 0.55  # Late 30s
                else:  # 38+
                    bonus_multiplier -= 0.75  # End of career

        # Position scarcity (for hitters) - small adjustments
        if is_hitter:
            pos_bonus = 0
            if 'C' in player.position:
                pos_bonus = 0.06  # Catchers are scarce
            elif 'SS' in player.position:
                pos_bonus = 0.03
            elif '2B' in player.position:
                pos_bonus = 0.02
            elif '1B' in player.position:
                pos_bonus = -0.02
            bonus_multiplier += pos_bonus

        # Cap the total bonus/penalty - floor at 0.15 allows steep age decline for 35+ veterans
        bonus_multiplier = max(0.15, min(bonus_multiplier, 1.25))
        value *= bonus_multiplier

        # Elite young player boost - proven MLB talents whose dynasty value exceeds projections
        # Applied AFTER age/position adjustments, BEFORE prospect overrides
        if player.name in ELITE_YOUNG_PLAYERS:
            elite_boost = ELITE_YOUNG_PLAYERS[player.name]
            value *= elite_boost

        # NOTE: PROVEN_VETERAN_STARS boost is now applied in calculate_player_value AFTER
        # consensus adjustment, so it adds on top of consensus rather than being absorbed by it

        # Prospect adjustments - CALIBRATED against 5-source consensus
        # (MLB Pipeline, Prospects Live, CFR, harryknowsball)
        # #1 prospect = 76 (near Elite tier, premium dynasty asset)
        # Prospects are valuable but still unproven vs MLB-proven superstars
        if player.name in PROSPECT_RANKINGS:
            rank = PROSPECT_RANKINGS[player.name]

            # Tiered prospect valuation - calibrated for dynasty league value
            # Top prospects are valuable but unproven, so valued below established stars
            # Smoother curve ensures prospects 26-100 retain tradeable value
            if rank <= 0 or rank > 300:
                prospect_value = 0.5
            elif rank <= 5:
                # Top 5: 63 at rank 1, 55 at rank 5 (below proven stars)
                prospect_value = 63 - (rank - 1) * 2.0
            elif rank <= 10:
                # Top 10: 53 at rank 6, 48 at rank 10
                prospect_value = 53 - (rank - 6) * 1.25
            elif rank <= 25:
                # 11-25: 46 at rank 11, 36 at rank 25
                prospect_value = 46 - (rank - 11) * 0.714
            elif rank <= 50:
                # 26-50: 35 at rank 26, 25 at rank 50 (smooth transition)
                prospect_value = 35 - (rank - 26) * 0.417
            elif rank <= 100:
                # 51-100: 24 at rank 51, 15 at rank 100 (still rosterable)
                prospect_value = 24 - (rank - 51) * 0.184
            elif rank <= 200:
                # 101-200: 14 at rank 101, 6 at rank 200 (deep stash value)
                prospect_value = 14 - (rank - 101) * 0.081
            else:
                # 201-300: 5 at rank 201, 2 at rank 300
                prospect_value = 5 - (rank - 201) * 0.030

            # Use prospect value directly - rank determines value for prospects
            value = prospect_value

        return value

    @staticmethod
    def _apply_unproven_pitcher_discount(player: Player, value: float) -> float:
        """Apply discount to pitchers with high projections but no MLB track record.

        Pitchers in UNPROVEN_PITCHERS list or those aged 26+ with very low Fantrax
        scores (<=5) and high Fantrax ranks (>1000) are likely unproven arms whose
        projections are based on minors/potential, not actual MLB performance.
        """
        # Check explicit unproven list first
        if player.name in UNPROVEN_PITCHERS:
            value *= 0.20
            return value

        # Also check Fantrax metrics for pitchers not in the list
        fantrax_score = getattr(player, 'fantrax_score', 100)  # Default to established
        fantrax_rank = getattr(player, 'fantrax_rank', 1)  # Default to low rank (good)

        if player.age >= 26 and fantrax_score <= 5 and fantrax_rank > 1000:
            value *= 0.20

        return value

    @staticmethod
    def calculate_player_value(player: Player, actual_stats: dict = None) -> float:
        """Calculate overall player value.

        Args:
            player: Player object
            actual_stats: Optional dict of actual in-season stats for blending with projections
        """
        # Check projections first to handle two-way players (like Ohtani)
        in_hitter_proj = player.name in HITTER_PROJECTIONS
        in_pitcher_proj = player.name in PITCHER_PROJECTIONS or player.name in RELIEVER_PROJECTIONS

        # Calculate base value from projections
        if in_hitter_proj and not in_pitcher_proj:
            base_value = DynastyValueCalculator.calculate_hitter_value(player, actual_stats)
        elif in_pitcher_proj and not in_hitter_proj:
            base_value = DynastyValueCalculator.calculate_pitcher_value(player)
        elif in_hitter_proj and in_pitcher_proj:
            # Two-way player like Ohtani
            hitter_val = DynastyValueCalculator.calculate_hitter_value(player, actual_stats)
            pitcher_val = DynastyValueCalculator.calculate_pitcher_value(player)
            primary = max(hitter_val, pitcher_val)
            secondary = min(hitter_val, pitcher_val)
            base_value = primary + (secondary * 0.40) + (primary * 0.10)
        elif player.is_pitcher():
            base_value = DynastyValueCalculator.calculate_pitcher_value(player)
        else:
            base_value = DynastyValueCalculator.calculate_hitter_value(player, actual_stats)

        # Apply consensus adjustment - pulls value toward market consensus
        final_value = DynastyValueCalculator._apply_consensus_adjustment(player.name, base_value)

        # Apply PROVEN_VETERAN_STARS boost AFTER consensus adjustment
        # This ensures the boost adds value on top of consensus rather than being absorbed by it
        if player.name in PROVEN_VETERAN_STARS:
            vet_boost = PROVEN_VETERAN_STARS[player.name]
            final_value *= vet_boost

        return final_value

    @staticmethod
    def _apply_consensus_adjustment(player_name: str, base_value: float) -> float:
        """Apply hybrid consensus adjustment to pull values toward market consensus.

        This is the key to the hybrid approach:
        - Start with projection-based value (analytical foundation)
        - Check against dynasty consensus rankings (FHQ + HKB average)
        - If significantly off, apply correction factor

        Correction logic:
        - Within 15 ranks: No adjustment (projections are reasonable)
        - 15-40 ranks off: 25% correction toward consensus
        - 40+ ranks off: 50% correction toward consensus
        """
        if player_name not in CONSENSUS_RANKINGS:
            return base_value  # No consensus data, use projection value

        # Skip consensus adjustment for top prospects - their value is determined by prospect rank,
        # not projection-based consensus which undervalues them for dynasty purposes
        if player_name in PROSPECT_RANKINGS and PROSPECT_RANKINGS[player_name] <= 100:
            return base_value  # Use pure prospect value

        consensus_rank = CONSENSUS_RANKINGS[player_name]

        # Estimate what rank our value implies
        # Using rough scale: value 100+ = top 5, 90 = top 10, 80 = top 20, etc.
        # This is approximate and based on our value distribution
        if base_value >= 100:
            implied_rank = max(1, 5 - (base_value - 100) / 5)
        elif base_value >= 85:
            implied_rank = 5 + (100 - base_value) * 1.0  # 85-100 maps to ranks 5-20
        elif base_value >= 70:
            implied_rank = 20 + (85 - base_value) * 2.0  # 70-85 maps to ranks 20-50
        elif base_value >= 55:
            implied_rank = 50 + (70 - base_value) * 3.0  # 55-70 maps to ranks 50-95
        elif base_value >= 40:
            implied_rank = 95 + (55 - base_value) * 4.0  # 40-55 maps to ranks 95-155
        else:
            implied_rank = 155 + (40 - base_value) * 5.0  # Below 40 maps to 155+

        rank_diff = implied_rank - consensus_rank  # Positive = we rank lower than consensus

        # Determine correction strength
        abs_diff = abs(rank_diff)
        if abs_diff <= 15:
            # Within tolerance - no adjustment
            return base_value
        elif abs_diff <= 40:
            # Moderate deviation - 25% correction
            correction_strength = 0.25
        else:
            # Large deviation - 50% correction
            correction_strength = 0.50

        # Calculate target value based on consensus rank
        # Inverse of the implied_rank calculation
        if consensus_rank <= 5:
            target_value = 100 + (5 - consensus_rank) * 5
        elif consensus_rank <= 20:
            target_value = 100 - (consensus_rank - 5) * 1.0
        elif consensus_rank <= 50:
            target_value = 85 - (consensus_rank - 20) / 2.0
        elif consensus_rank <= 95:
            target_value = 70 - (consensus_rank - 50) / 3.0
        elif consensus_rank <= 155:
            target_value = 55 - (consensus_rank - 95) / 4.0
        else:
            target_value = 40 - (consensus_rank - 155) / 5.0

        target_value = max(target_value, 10)  # Floor of 10

        # Apply correction: blend base_value toward target_value
        adjusted_value = base_value + (target_value - base_value) * correction_strength

        return adjusted_value
    
    @staticmethod
    def calculate_pick_value(pick: str) -> float:
        """Calculate draft pick value based on new format.

        2026 format: "2026 1st Round Pick 1 (#1)" through "2026 4th Round Pick 12 (#48)"
        2027/2028 format: "2027 1st Round Pick", "2027 2nd Round Pick", etc.
        """
        import re

        # Base values by round (12-team league)
        # 1st round: Can get solid prospects (picks 1-12)
        # 2nd round: Lottery ticket with upside (picks 13-24)
        # 3rd round: Dart throws with potential (picks 25-36)
        # 4th round: Long shots (picks 37-48)
        round_base_values = {'1st': 55, '2nd': 28, '3rd': 12, '4th': 5}

        # Try to extract overall pick number from (#N) format - most precise
        overall_match = re.search(r'\(#(\d+)\)', pick)
        if overall_match:
            overall_pick = int(overall_match.group(1))
            # Value based on overall pick position (1-48)
            # Pick 1 = ~63, Pick 12 = ~48, Pick 13 = ~31, Pick 24 = ~26, etc.
            if overall_pick <= 12:  # 1st round
                base = 55
                position_mult = 1.15 - ((overall_pick - 1) * 0.025)  # 1.15 to 0.88
            elif overall_pick <= 24:  # 2nd round
                base = 28
                position_mult = 1.15 - ((overall_pick - 13) * 0.025)
            elif overall_pick <= 36:  # 3rd round
                base = 12
                position_mult = 1.15 - ((overall_pick - 25) * 0.025)
            else:  # 4th round
                base = 5
                position_mult = 1.15 - ((overall_pick - 37) * 0.025)

            value = base * position_mult

            # Year adjustment for 2026 picks with specific numbers
            if '2026' in pick:
                value *= 1.10  # Premium for known pick position

            return value

        # Fallback for picks without overall number (2027, 2028)
        for round_name, base_value in round_base_values.items():
            if round_name in pick:
                value = base_value

                # Position adjustment if pick number present (e.g., "Pick 3")
                pick_match = re.search(r'Pick\s+(\d+)(?:\s|$)', pick)
                if pick_match:
                    pick_num = int(pick_match.group(1))
                    position_mult = 1.15 - ((pick_num - 1) * 0.025)
                    value *= position_mult

                # Year adjustments - closer picks worth more
                if '2026' in pick:
                    value *= 1.10
                elif '2027' in pick:
                    value *= 0.90  # Future uncertainty discount
                elif '2028' in pick:
                    value *= 0.75  # Greater uncertainty

                return value

        return 5  # Unknown pick


# ============================================================================
# LEAGUE ANALYZER
# ============================================================================

class LeagueAnalyzer:
    """Analyzes league-wide data to identify team strengths/weaknesses."""
    
    def __init__(self, teams: Dict[str, Team]):
        self.teams = teams
        self.league_averages = {}
        self._calculate_league_averages()
    
    def _calculate_league_averages(self):
        """Calculate league-wide category averages."""
        hitting_totals = defaultdict(list)
        pitching_totals = defaultdict(list)
        
        for team in self.teams.values():
            team_hitting = self._sum_team_hitting(team)
            team_pitching = self._sum_team_pitching(team)
            
            for cat, val in team_hitting.items():
                hitting_totals[cat].append(val)
            for cat, val in team_pitching.items():
                pitching_totals[cat].append(val)
        
        self.league_averages['hitting'] = {
            cat: sum(vals) / len(vals) if vals else 0 
            for cat, vals in hitting_totals.items()
        }
        self.league_averages['pitching'] = {
            cat: sum(vals) / len(vals) if vals else 0 
            for cat, vals in pitching_totals.items()
        }
    
    def _sum_team_hitting(self, team: Team) -> Dict[str, float]:
        """Sum projected hitting stats for a team's active roster."""
        # League categories: AVG, SLG, SO, HR, RBI, OPS
        totals = {'hr': 0, 'rbi': 0, 'so': 0, 'avg': 0, 'slg': 0, 'ops': 0}
        count = 0

        for player in team.players:
            if player.roster_status == 'Active' and player.is_hitter():
                proj = HITTER_PROJECTIONS.get(player.name)
                if proj:
                    totals['hr'] += proj.get('HR', 0)
                    totals['rbi'] += proj.get('RBI', 0)
                    totals['so'] += proj.get('SO', 0)
                    totals['avg'] += proj.get('AVG', 0)
                    totals['slg'] += proj.get('SLG', 0)
                    totals['ops'] += proj.get('OPS', 0)
                    count += 1

        if count > 0:
            totals['avg'] /= count
            totals['slg'] /= count
            totals['ops'] /= count

        return totals
    
    def _sum_team_pitching(self, team: Team) -> Dict[str, float]:
        """Sum projected pitching stats for a team's active roster."""
        # League categories: K, ERA, WHIP, K/BB, L, SV+HLD, QS
        totals = {'k': 0, 'qs': 0, 'l': 0, 'era': 0, 'whip': 0, 'k_bb': 0, 'sv_hld': 0}
        sp_count = 0
        rp_count = 0

        for player in team.players:
            if player.roster_status == 'Active' and player.is_pitcher():
                # Check starters first
                proj = PITCHER_PROJECTIONS.get(player.name)
                if proj:
                    totals['k'] += proj.get('K', 0)
                    totals['qs'] += proj.get('QS', 0)
                    totals['l'] += proj.get('L', 0)
                    totals['era'] += proj.get('ERA', 0)
                    totals['whip'] += proj.get('WHIP', 0)
                    totals['k_bb'] += proj.get('K/BB', 0)
                    sp_count += 1
                else:
                    # Check relievers
                    proj = RELIEVER_PROJECTIONS.get(player.name)
                    if proj:
                        totals['k'] += proj.get('K', 0)
                        totals['l'] += proj.get('L', 0)
                        totals['era'] += proj.get('ERA', 0)
                        totals['whip'] += proj.get('WHIP', 0)
                        totals['k_bb'] += proj.get('K/BB', 0)
                        totals['sv_hld'] += proj.get('SV', 0) + proj.get('HD', 0)
                        rp_count += 1

        total_count = sp_count + rp_count
        if total_count > 0:
            totals['era'] /= total_count
            totals['whip'] /= total_count
            totals['k_bb'] /= total_count

        return totals
    
    def analyze_team(self, team_name: str) -> Team:
        """Analyze a team's strengths and weaknesses."""
        team = self.teams.get(team_name)
        if not team:
            return None
        
        team_hitting = self._sum_team_hitting(team)
        team_pitching = self._sum_team_pitching(team)
        
        # Compare to league averages
        team.hitting_strengths = {}
        team.hitting_weaknesses = {}
        
        for cat, val in team_hitting.items():
            league_avg = self.league_averages['hitting'].get(cat, val)
            if league_avg > 0:
                pct_diff = ((val - league_avg) / league_avg) * 100
                if pct_diff > 10:
                    team.hitting_strengths[cat] = pct_diff
                elif pct_diff < -10:
                    team.hitting_weaknesses[cat] = pct_diff
        
        team.pitching_strengths = {}
        team.pitching_weaknesses = {}
        
        for cat, val in team_pitching.items():
            league_avg = self.league_averages['pitching'].get(cat, val)
            if league_avg > 0:
                # Inverse for ERA, WHIP, L (lower is better)
                if cat in ['era', 'whip', 'l']:
                    pct_diff = ((league_avg - val) / league_avg) * 100
                else:
                    pct_diff = ((val - league_avg) / league_avg) * 100
                
                if pct_diff > 10:
                    team.pitching_strengths[cat] = pct_diff
                elif pct_diff < -10:
                    team.pitching_weaknesses[cat] = pct_diff
        
        # Analyze positional depth
        team.position_depth = self._analyze_position_depth(team)
        
        return team
    
    def _analyze_position_depth(self, team: Team) -> Dict[str, List[Player]]:
        """Analyze positional depth for a team."""
        positions = defaultdict(list)
        
        for player in team.players:
            if player.roster_status in ['Active', 'Reserve']:
                for pos in player.position.split(','):
                    pos = pos.strip()
                    positions[pos].append(player)
        
        # Sort by value
        calc = DynastyValueCalculator()
        for pos in positions:
            positions[pos].sort(
                key=lambda p: calc.calculate_player_value(p), 
                reverse=True
            )
        
        return dict(positions)


# ============================================================================
# TRADE ANALYZER
# ============================================================================

class TradeAnalyzer:
    """Analyzes trades with projections and fit scoring."""
    
    def __init__(self, league_analyzer: LeagueAnalyzer):
        self.league = league_analyzer
        self.calculator = DynastyValueCalculator()
    
    def analyze_trade(self, proposal: TradeProposal) -> TradeProposal:
        """Perform full trade analysis."""
        # Calculate raw values
        proposal.value_a_receives = self._calculate_package_value(
            proposal.players_from_b, proposal.picks_from_b
        )
        proposal.value_b_receives = self._calculate_package_value(
            proposal.players_from_a, proposal.picks_from_a
        )
        
        # Calculate category impacts
        proposal.category_impact_a = self._calculate_category_impact(
            proposal.players_from_b, proposal.players_from_a
        )
        proposal.category_impact_b = self._calculate_category_impact(
            proposal.players_from_a, proposal.players_from_b
        )
        
        # Calculate fit scores
        team_a = self.league.teams.get(proposal.team_a)
        team_b = self.league.teams.get(proposal.team_b)
        
        if team_a:
            self.league.analyze_team(proposal.team_a)
            proposal.fit_score_a = self._calculate_fit_score(
                team_a, proposal.players_from_b, proposal.players_from_a
            )
        
        if team_b:
            self.league.analyze_team(proposal.team_b)
            proposal.fit_score_b = self._calculate_fit_score(
                team_b, proposal.players_from_a, proposal.players_from_b
            )
        
        # Generate verdict
        proposal.verdict, proposal.reasoning = self._generate_verdict(proposal)
        
        return proposal
    
    def _calculate_package_value(self, players: List[Player], picks: List[str]) -> float:
        """Calculate total value of players + picks."""
        total = sum(self.calculator.calculate_player_value(p) for p in players)
        total += sum(self.calculator.calculate_pick_value(pk) for pk in picks)
        return total
    
    def _calculate_category_impact(self, receiving: List[Player], giving: List[Player]) -> Dict:
        """Calculate net category impact."""
        impact = {
            'hitting': {'hr': 0, 'r': 0, 'rbi': 0, 'sb': 0, 'so': 0, 'avg': 0.0, 'ops': 0.0},
            'pitching': {'k': 0, 'qs': 0, 'l': 0, 'era': 0.0, 'whip': 0.0}
        }
        
        # Add incoming
        for player in receiving:
            if player.is_hitter():
                proj = HITTER_PROJECTIONS.get(player.name, {})
                impact['hitting']['hr'] += proj.get('HR', 0)
                impact['hitting']['r'] += proj.get('R', 0)
                impact['hitting']['rbi'] += proj.get('RBI', 0)
                impact['hitting']['sb'] += proj.get('SB', 0)
                impact['hitting']['so'] += proj.get('SO', 0)
            elif player.is_pitcher():
                proj = PITCHER_PROJECTIONS.get(player.name, {})
                impact['pitching']['k'] += proj.get('K', 0)
                impact['pitching']['qs'] += proj.get('QS', 0)
                impact['pitching']['l'] += proj.get('L', 0)
        
        # Subtract outgoing
        for player in giving:
            if player.is_hitter():
                proj = HITTER_PROJECTIONS.get(player.name, {})
                impact['hitting']['hr'] -= proj.get('HR', 0)
                impact['hitting']['r'] -= proj.get('R', 0)
                impact['hitting']['rbi'] -= proj.get('RBI', 0)
                impact['hitting']['sb'] -= proj.get('SB', 0)
                impact['hitting']['so'] -= proj.get('SO', 0)
            elif player.is_pitcher():
                proj = PITCHER_PROJECTIONS.get(player.name, {})
                impact['pitching']['k'] -= proj.get('K', 0)
                impact['pitching']['qs'] -= proj.get('QS', 0)
                impact['pitching']['l'] -= proj.get('L', 0)
        
        return impact
    
    def _calculate_fit_score(self, team: Team, receiving: List[Player], giving: List[Player]) -> float:
        """Calculate how well a trade fits team needs (0-100)."""
        fit_score = 50  # Neutral starting point

        # Check if trade addresses weaknesses
        for player in receiving:
            if player.is_hitter():
                proj = HITTER_PROJECTIONS.get(player.name, {})
                # League categories: AVG, SLG, SO, HR, RBI, OPS
                if 'hr' in team.hitting_weaknesses and proj.get('HR', 0) > 20:
                    fit_score += 10
                if 'rbi' in team.hitting_weaknesses and proj.get('RBI', 0) > 60:
                    fit_score += 8
                if 'avg' in team.hitting_weaknesses and proj.get('AVG', 0) > 0.270:
                    fit_score += 8
                if 'slg' in team.hitting_weaknesses and proj.get('SLG', 0) > 0.450:
                    fit_score += 8
                if 'ops' in team.hitting_weaknesses and proj.get('OPS', 0) > 0.780:
                    fit_score += 8

            elif player.is_pitcher():
                proj = PITCHER_PROJECTIONS.get(player.name) or RELIEVER_PROJECTIONS.get(player.name, {})
                # League categories: K, ERA, WHIP, K/BB, L, SV+HLD, QS
                if 'k' in team.pitching_weaknesses and proj.get('K', 0) > 100:
                    fit_score += 10
                if 'era' in team.pitching_weaknesses and proj.get('ERA', 5) < 3.80:
                    fit_score += 10
                if 'whip' in team.pitching_weaknesses and proj.get('WHIP', 2) < 1.20:
                    fit_score += 8
                if 'qs' in team.pitching_weaknesses and proj.get('QS', 0) > 12:
                    fit_score += 8
                if 'sv_hld' in team.pitching_weaknesses:
                    sv_hld = proj.get('SV', 0) + proj.get('HD', 0)
                    if sv_hld > 15:
                        fit_score += 10

        # Penalty for giving up strength areas
        for player in giving:
            if player.is_hitter():
                proj = HITTER_PROJECTIONS.get(player.name, {})
                if 'hr' in team.hitting_strengths and proj.get('HR', 0) > 20:
                    fit_score -= 8
                if 'rbi' in team.hitting_strengths and proj.get('RBI', 0) > 60:
                    fit_score -= 6
                if 'ops' in team.hitting_strengths and proj.get('OPS', 0) > 0.800:
                    fit_score -= 6
            elif player.is_pitcher():
                proj = PITCHER_PROJECTIONS.get(player.name) or RELIEVER_PROJECTIONS.get(player.name, {})
                if 'k' in team.pitching_strengths and proj.get('K', 0) > 100:
                    fit_score -= 8
                if 'sv_hld' in team.pitching_strengths:
                    sv_hld = proj.get('SV', 0) + proj.get('HD', 0)
                    if sv_hld > 15:
                        fit_score -= 8

        return max(0, min(100, fit_score))
    
    def _generate_verdict(self, proposal: TradeProposal) -> Tuple[str, str]:
        """Generate trade verdict and reasoning."""
        diff = proposal.value_a_receives - proposal.value_b_receives
        total = proposal.value_a_receives + proposal.value_b_receives
        
        if total > 0:
            pct_a = (proposal.value_a_receives / total) * 100
            pct_b = (proposal.value_b_receives / total) * 100
        else:
            pct_a = pct_b = 50
        
        abs_diff = abs(diff)
        
        if abs_diff < 5:
            verdict = "⚖️ FAIRLY BALANCED"
            winner = "Neither team has a clear advantage"
        elif abs_diff < 15:
            winner = proposal.team_a if diff > 0 else proposal.team_b
            verdict = f"✅ SLIGHTLY FAVORS {winner.upper()}"
        elif abs_diff < 30:
            winner = proposal.team_a if diff > 0 else proposal.team_b
            verdict = f"⚠️ FAVORS {winner.upper()}"
        else:
            winner = proposal.team_a if diff > 0 else proposal.team_b
            verdict = f"🚨 HEAVILY FAVORS {winner.upper()}"
        
        # Build reasoning
        reasons = []
        reasons.append(f"Value: {proposal.team_a} receives {proposal.value_a_receives:.1f} ({pct_a:.0f}%), "
                      f"{proposal.team_b} receives {proposal.value_b_receives:.1f} ({pct_b:.0f}%)")
        
        if proposal.fit_score_a > 60:
            reasons.append(f"Trade addresses {proposal.team_a}'s team needs well")
        if proposal.fit_score_b > 60:
            reasons.append(f"Trade addresses {proposal.team_b}'s team needs well")
        
        return verdict, " | ".join(reasons)


# ============================================================================
# TRADE SUGGESTION ENGINE
# ============================================================================

class TradeSuggestionEngine:
    """Generates automated trade suggestions based on team needs."""
    
    def __init__(self, teams: Dict[str, Team], my_team: str):
        self.teams = teams
        self.my_team = my_team
        self.league = LeagueAnalyzer(teams)
        self.analyzer = TradeAnalyzer(self.league)
        self.calculator = DynastyValueCalculator()
    
    def find_trade_partners(self) -> List[Dict]:
        """Find best trade partners based on complementary needs."""
        my_team_data = self.league.analyze_team(self.my_team)
        partners = []
        
        for team_name, team in self.teams.items():
            if team_name == self.my_team:
                continue
            
            other_team = self.league.analyze_team(team_name)
            compatibility = self._calculate_compatibility(my_team_data, other_team)
            
            # Include all teams as potential partners (compatibility helps rank them)
            partners.append({
                'team': team_name,
                'compatibility': compatibility,
                'my_needs_they_have': self._find_matching_needs(my_team_data, other_team),
                'their_needs_i_have': self._find_matching_needs(other_team, my_team_data),
            })
        
        partners.sort(key=lambda x: x['compatibility'], reverse=True)
        return partners
    
    def _calculate_compatibility(self, my_team: Team, other_team: Team) -> float:
        """Calculate trade compatibility score between two teams."""
        score = 0
        
        # Check if their strengths match my weaknesses
        for cat in my_team.hitting_weaknesses:
            if cat in other_team.hitting_strengths:
                score += 15
        
        for cat in my_team.pitching_weaknesses:
            if cat in other_team.pitching_strengths:
                score += 15
        
        # Check reverse (my strengths match their weaknesses)
        for cat in my_team.hitting_strengths:
            if cat in other_team.hitting_weaknesses:
                score += 15
        
        for cat in my_team.pitching_strengths:
            if cat in other_team.pitching_weaknesses:
                score += 15
        
        return score
    
    def _find_matching_needs(self, needy_team: Team, supply_team: Team) -> List[str]:
        """Find categories where supply_team can help needy_team."""
        matches = []
        
        for cat in needy_team.hitting_weaknesses:
            if cat in supply_team.hitting_strengths:
                matches.append(f"Hitting: {cat.upper()}")
        
        for cat in needy_team.pitching_weaknesses:
            if cat in supply_team.pitching_strengths:
                matches.append(f"Pitching: {cat.upper()}")
        
        return matches
    
    def generate_trade_suggestions(self, target_team: str, max_suggestions: int = 5) -> List[TradeProposal]:
        """Generate specific trade suggestions with a target team."""
        my_team_data = self.league.analyze_team(self.my_team)
        target_team_data = self.league.analyze_team(target_team)
        
        if not my_team_data or not target_team_data:
            return []
        
        suggestions = []
        
        # Find players that address each team's needs
        my_trade_chips = self._identify_trade_chips(my_team_data)
        their_targets = self._identify_targets(target_team_data, my_team_data)
        
        # Generate trade combinations
        for my_chip in my_trade_chips[:10]:  # Top 10 trade chips
            for their_target in their_targets[:10]:
                # Simple 1-for-1 trades
                proposal = TradeProposal(
                    team_a=self.my_team,
                    team_b=target_team,
                    players_from_a=[my_chip],
                    players_from_b=[their_target],
                )
                
                analyzed = self.analyzer.analyze_trade(proposal)
                
                # Only include reasonably balanced trades
                value_diff = abs(analyzed.value_a_receives - analyzed.value_b_receives)
                if value_diff < 35:  # Within 35 points
                    suggestions.append(analyzed)
        
        # Sort by combined fit score
        suggestions.sort(
            key=lambda p: p.fit_score_a + p.fit_score_b + (100 - abs(p.value_a_receives - p.value_b_receives)),
            reverse=True
        )
        
        return suggestions[:max_suggestions]
    
    def _identify_trade_chips(self, team: Team) -> List[Player]:
        """Identify players that could be traded (any player with decent value)."""
        chips = []

        for player in team.players:
            if player.roster_status not in ['Active', 'Reserve']:
                continue

            value = self.calculator.calculate_player_value(player)

            # Any player with reasonable value is a potential trade chip
            if 15 < value < 90:
                chips.append(player)

        chips.sort(key=lambda p: self.calculator.calculate_player_value(p), reverse=True)
        return chips
    
    def _identify_targets(self, target_team: Team, my_team: Team) -> List[Player]:
        """Identify players on target team that could be trade targets."""
        targets = []

        for player in target_team.players:
            if player.roster_status not in ['Active', 'Reserve']:
                continue

            value = self.calculator.calculate_player_value(player)

            # Any player with reasonable value is a potential target
            if value > 15:
                # Prioritize players that address weaknesses
                priority = 0
                if player.is_hitter():
                    proj = HITTER_PROJECTIONS.get(player.name, {})
                    # League categories: AVG, SLG, SO, HR, RBI, OPS
                    if 'hr' in my_team.hitting_weaknesses and proj.get('HR', 0) > 15:
                        priority += 10
                    if 'rbi' in my_team.hitting_weaknesses and proj.get('RBI', 0) > 60:
                        priority += 10
                    if 'avg' in my_team.hitting_weaknesses and proj.get('AVG', 0) > 0.270:
                        priority += 10
                    if 'slg' in my_team.hitting_weaknesses and proj.get('SLG', 0) > 0.450:
                        priority += 10
                    if 'ops' in my_team.hitting_weaknesses and proj.get('OPS', 0) > 0.780:
                        priority += 10
                else:
                    # Check starters and relievers
                    proj = PITCHER_PROJECTIONS.get(player.name) or RELIEVER_PROJECTIONS.get(player.name, {})
                    # League categories: K, ERA, WHIP, K/BB, L, SV+HLD, QS
                    if 'k' in my_team.pitching_weaknesses and proj.get('K', 0) > 100:
                        priority += 10
                    if 'era' in my_team.pitching_weaknesses and proj.get('ERA', 5) < 3.80:
                        priority += 10
                    if 'whip' in my_team.pitching_weaknesses and proj.get('WHIP', 2) < 1.20:
                        priority += 10
                    if 'sv_hld' in my_team.pitching_weaknesses:
                        sv_hld = proj.get('SV', 0) + proj.get('HD', 0)
                        if sv_hld > 10:
                            priority += 10

                targets.append((player, priority))

        # Sort by priority first, then by value
        targets.sort(key=lambda x: (x[1], self.calculator.calculate_player_value(x[0])), reverse=True)
        return [t[0] for t in targets]


# ============================================================================
# DATA LOADER
# ============================================================================

def load_fantrax_data(csv_path: str) -> Dict[str, Team]:
    """Load Fantrax roster export into Team objects."""
    teams = defaultdict(lambda: Team(name=""))
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            fantasy_team = row.get('Status', '')
            if not fantasy_team:
                continue
            
            if teams[fantasy_team].name == "":
                teams[fantasy_team].name = fantasy_team
            
            # Parse player data
            player = Player(
                name=row.get('Player', ''),
                position=row.get('Position', 'N/A'),
                mlb_team=row.get('Team', 'FA'),
                fantasy_team=fantasy_team,
                roster_status=row.get('Roster Status', 'Active'),
                age=int(row.get('Age', 0)) if row.get('Age', '').isdigit() else 0,
                fantrax_score=float(row.get('Score', 0)) if row.get('Score', '') else 0,
                fantrax_rank=int(row.get('RkOv', 999)) if row.get('RkOv', '').isdigit() else 999,
            )
            
            # Check if prospect
            if player.name in PROSPECT_RANKINGS:
                player.prospect_rank = PROSPECT_RANKINGS[player.name]
                player.is_prospect = True
            
            teams[fantasy_team].players.append(player)
    
    return dict(teams)


# ============================================================================
# MAIN INTERFACE
# ============================================================================

def print_team_analysis(team: Team, league: LeagueAnalyzer):
    """Print detailed team analysis."""
    print(f"\n{'='*70}")
    print(f"📊 TEAM ANALYSIS: {team.name}")
    print('='*70)
    
    # Roster overview
    active = [p for p in team.players if p.roster_status == 'Active']
    reserve = [p for p in team.players if p.roster_status == 'Reserve']
    minors = [p for p in team.players if p.roster_status == 'Minors']
    ir = [p for p in team.players if p.roster_status == 'Inj Res']
    
    print(f"\nRoster: {len(active)} Active | {len(reserve)} Reserve | {len(minors)} Minors | {len(ir)} IR")
    
    # Top players by value
    calc = DynastyValueCalculator()
    valued_players = [(p, calc.calculate_player_value(p)) for p in team.players]
    valued_players.sort(key=lambda x: x[1], reverse=True)
    
    print(f"\n🌟 TOP 10 PLAYERS BY DYNASTY VALUE:")
    for player, value in valued_players[:10]:
        prospect_tag = f" [TOP {player.prospect_rank}]" if player.is_prospect else ""
        print(f"  {player.name:<25} {player.position:<8} Value: {value:.1f}{prospect_tag}")
    
    # Strengths
    league.analyze_team(team.name)
    
    print(f"\n💪 HITTING STRENGTHS:")
    if team.hitting_strengths:
        for cat, pct in sorted(team.hitting_strengths.items(), key=lambda x: -x[1]):
            print(f"  {cat.upper()}: +{pct:.0f}% above league avg")
    else:
        print("  None identified")
    
    print(f"\n📉 HITTING WEAKNESSES:")
    if team.hitting_weaknesses:
        for cat, pct in sorted(team.hitting_weaknesses.items(), key=lambda x: x[1]):
            print(f"  {cat.upper()}: {pct:.0f}% below league avg")
    else:
        print("  None identified")
    
    print(f"\n💪 PITCHING STRENGTHS:")
    if team.pitching_strengths:
        for cat, pct in sorted(team.pitching_strengths.items(), key=lambda x: -x[1]):
            print(f"  {cat.upper()}: +{pct:.0f}% above league avg")
    else:
        print("  None identified")
    
    print(f"\n📉 PITCHING WEAKNESSES:")
    if team.pitching_weaknesses:
        for cat, pct in sorted(team.pitching_weaknesses.items(), key=lambda x: x[1]):
            print(f"  {cat.upper()}: {pct:.0f}% below league avg")
    else:
        print("  None identified")


def print_trade_analysis(proposal: TradeProposal):
    """Print detailed trade analysis."""
    print(f"\n{'='*70}")
    print("🔄 TRADE ANALYSIS")
    print('='*70)
    
    calc = DynastyValueCalculator()
    
    print(f"\n{proposal.team_a} RECEIVES:")
    for player in proposal.players_from_b:
        value = calc.calculate_player_value(player)
        prospect_tag = f" [TOP {player.prospect_rank}]" if player.is_prospect else ""
        print(f"  • {player.name} ({player.position}) - Value: {value:.1f}{prospect_tag}")
    for pick in proposal.picks_from_b:
        value = calc.calculate_pick_value(pick)
        print(f"  • {pick} - Value: {value:.1f}")
    
    print(f"\n{proposal.team_b} RECEIVES:")
    for player in proposal.players_from_a:
        value = calc.calculate_player_value(player)
        prospect_tag = f" [TOP {player.prospect_rank}]" if player.is_prospect else ""
        print(f"  • {player.name} ({player.position}) - Value: {value:.1f}{prospect_tag}")
    for pick in proposal.picks_from_a:
        value = calc.calculate_pick_value(pick)
        print(f"  • {pick} - Value: {value:.1f}")
    
    total = proposal.value_a_receives + proposal.value_b_receives
    pct_a = (proposal.value_a_receives / total * 100) if total > 0 else 50
    pct_b = (proposal.value_b_receives / total * 100) if total > 0 else 50
    
    print(f"\n{'─'*70}")
    print("📊 VALUE ANALYSIS:")
    print(f"  {proposal.team_a}: {proposal.value_a_receives:.1f} points ({pct_a:.0f}%)")
    print(f"  {proposal.team_b}: {proposal.value_b_receives:.1f} points ({pct_b:.0f}%)")
    
    print(f"\n🎯 FIT SCORES:")
    print(f"  {proposal.team_a}: {proposal.fit_score_a:.0f}/100")
    print(f"  {proposal.team_b}: {proposal.fit_score_b:.0f}/100")
    
    print(f"\n{'─'*70}")
    print(f"VERDICT: {proposal.verdict}")
    print(f"  {proposal.reasoning}")
    print('='*70)


# ============================================================================
# INTERACTIVE TRADE ANALYZER (V2 Feature)
# ============================================================================

class InteractiveTradeAnalyzer:
    """Interactive mode for user-specified trade analysis."""
    
    def __init__(self, teams: Dict[str, Team]):
        self.teams = teams
        self.league = LeagueAnalyzer(teams)
        self.analyzer = TradeAnalyzer(self.league)
        self.calculator = DynastyValueCalculator()
    
    def find_player(self, name: str) -> Optional[Tuple[Player, str]]:
        """Find a player by name (partial match) and return (player, team)."""
        name_lower = name.lower().strip()
        
        for team_name, team in self.teams.items():
            for player in team.players:
                if name_lower in player.name.lower():
                    return (player, team_name)
        return None
    
    def search_players(self, query: str) -> List[Tuple[Player, str]]:
        """Search for players matching a query."""
        query_lower = query.lower().strip()
        results = []
        
        for team_name, team in self.teams.items():
            for player in team.players:
                if query_lower in player.name.lower():
                    results.append((player, team_name))
        
        return results
    
    def analyze_custom_trade(
        self,
        team_a: str,
        team_b: str,
        players_from_a: List[str],
        players_from_b: List[str],
        picks_from_a: List[str] = None,
        picks_from_b: List[str] = None
    ) -> Optional[TradeProposal]:
        """Analyze a custom multi-player trade."""
        picks_from_a = picks_from_a or []
        picks_from_b = picks_from_b or []
        
        # Find all players
        a_players = []
        for name in players_from_a:
            result = self.find_player(name)
            if result:
                player, found_team = result
                if found_team == team_a:
                    a_players.append(player)
                else:
                    print(f"⚠️ {player.name} is on {found_team}, not {team_a}")
                    return None
            else:
                print(f"❌ Could not find player: {name}")
                return None
        
        b_players = []
        for name in players_from_b:
            result = self.find_player(name)
            if result:
                player, found_team = result
                if found_team == team_b:
                    b_players.append(player)
                else:
                    print(f"⚠️ {player.name} is on {found_team}, not {team_b}")
                    return None
            else:
                print(f"❌ Could not find player: {name}")
                return None
        
        # Create proposal
        proposal = TradeProposal(
            team_a=team_a,
            team_b=team_b,
            players_from_a=a_players,
            players_from_b=b_players,
            picks_from_a=picks_from_a,
            picks_from_b=picks_from_b
        )
        
        return self.analyzer.analyze_trade(proposal)
    
    def print_player_value(self, name: str):
        """Print detailed value breakdown for a player."""
        result = self.find_player(name)
        if not result:
            print(f"❌ Could not find player: {name}")
            return
        
        player, team = result
        value = self.calculator.calculate_player_value(player)
        
        print(f"\n{'='*50}")
        print(f"📊 PLAYER VALUE: {player.name}")
        print('='*50)
        print(f"Team: {team} | Position: {player.position} | Age: {player.age}")
        print(f"Dynasty Value: {value:.1f}/100")
        
        # Show projection details
        if player.is_hitter():
            proj = HITTER_PROJECTIONS.get(player.name)
            if proj:
                print(f"\n2026 Projections:")
                print(f"  AVG: {proj['AVG']:.3f} | OPS: {proj['OPS']:.3f}")
                print(f"  HR: {proj['HR']} | R: {proj['R']} | RBI: {proj['RBI']}")
                print(f"  SB: {proj['SB']} | SO: {proj['SO']}")
        elif player.is_pitcher():
            sp_proj = PITCHER_PROJECTIONS.get(player.name)
            rp_proj = RELIEVER_PROJECTIONS.get(player.name)
            
            if rp_proj:
                sv_hld = rp_proj.get('SV', 0) + rp_proj.get('HD', 0)
                print(f"\n2026 Projections (RP):")
                print(f"  SV+HLD: {sv_hld} ({rp_proj.get('SV', 0)} SV / {rp_proj.get('HD', 0)} HD)")
                print(f"  ERA: {rp_proj['ERA']:.2f} | WHIP: {rp_proj['WHIP']:.2f}")
                print(f"  K: {rp_proj['K']} | IP: {rp_proj['IP']:.1f}")
            elif sp_proj:
                print(f"\n2026 Projections (SP):")
                print(f"  ERA: {sp_proj['ERA']:.2f} | WHIP: {sp_proj['WHIP']:.2f}")
                print(f"  K: {sp_proj['K']} | QS: {sp_proj['QS']} | W-L: {sp_proj['W']}-{sp_proj['L']}")
        
        if player.is_prospect:
            print(f"\n🌟 TOP {player.prospect_rank} PROSPECT")
    
    def generate_multi_player_suggestions(
        self, 
        my_team: str, 
        target_team: str,
        trade_format: str = "2-for-1"
    ) -> List[TradeProposal]:
        """Generate multi-player trade suggestions."""
        my_team_data = self.league.analyze_team(my_team)
        target_team_data = self.league.analyze_team(target_team)
        
        if not my_team_data or not target_team_data:
            return []
        
        suggestions = []
        my_players = sorted(
            [p for p in my_team_data.players if p.roster_status in ['Active', 'Reserve']],
            key=lambda p: self.calculator.calculate_player_value(p),
            reverse=True
        )
        target_players = sorted(
            [p for p in target_team_data.players if p.roster_status in ['Active', 'Reserve']],
            key=lambda p: self.calculator.calculate_player_value(p),
            reverse=True
        )
        
        if trade_format == "2-for-1":
            # Find 2-for-1 opportunities (get one premium player)
            for target in target_players[:20]:
                target_value = self.calculator.calculate_player_value(target)
                
                if target_value < 40:  # Lower threshold
                    continue
                
                # Find pairs that match the value
                for i, my_p1 in enumerate(my_players[:25]):
                    v1 = self.calculator.calculate_player_value(my_p1)
                    for my_p2 in my_players[i+1:30]:
                        v2 = self.calculator.calculate_player_value(my_p2)
                        combined = v1 + v2
                        
                        # More lenient value matching for consolidation trades
                        if 0.6 * target_value <= combined <= 1.6 * target_value:
                            proposal = TradeProposal(
                                team_a=my_team,
                                team_b=target_team,
                                players_from_a=[my_p1, my_p2],
                                players_from_b=[target]
                            )
                            analyzed = self.analyzer.analyze_trade(proposal)
                            
                            # Accept trades within 35 points
                            if abs(analyzed.value_a_receives - analyzed.value_b_receives) < 35:
                                suggestions.append(analyzed)
        
        elif trade_format == "3-for-2":
            # Find 3-for-2 opportunities
            for t1_idx, target1 in enumerate(target_players[:10]):
                for target2 in target_players[t1_idx+1:15]:
                    target_value = (
                        self.calculator.calculate_player_value(target1) +
                        self.calculator.calculate_player_value(target2)
                    )
                    
                    if target_value < 80:
                        continue
                    
                    for i, my_p1 in enumerate(my_players[:15]):
                        for j, my_p2 in enumerate(my_players[i+1:20]):
                            for my_p3 in my_players[j+1:25]:
                                combined = (
                                    self.calculator.calculate_player_value(my_p1) +
                                    self.calculator.calculate_player_value(my_p2) +
                                    self.calculator.calculate_player_value(my_p3)
                                )
                                
                                if 0.85 * target_value <= combined <= 1.25 * target_value:
                                    proposal = TradeProposal(
                                        team_a=my_team,
                                        team_b=target_team,
                                        players_from_a=[my_p1, my_p2, my_p3],
                                        players_from_b=[target1, target2]
                                    )
                                    analyzed = self.analyzer.analyze_trade(proposal)
                                    
                                    if abs(analyzed.value_a_receives - analyzed.value_b_receives) < 30:
                                        suggestions.append(analyzed)
                                        
                                if len(suggestions) >= 50:
                                    break
        
        # Sort by combined fit score and value balance
        suggestions.sort(
            key=lambda p: p.fit_score_a + p.fit_score_b + (100 - abs(p.value_a_receives - p.value_b_receives)),
            reverse=True
        )
        
        return suggestions[:10]


def find_team_name(teams: Dict[str, Team], query: str) -> Optional[str]:
    """Case-insensitive team name lookup."""
    for t in teams.keys():
        if t.lower() == query.lower():
            return t
    return None


def run_interactive_mode(teams: Dict[str, Team], my_team: str = "PAW"):
    """Run interactive trade analyzer mode."""
    interactive = InteractiveTradeAnalyzer(teams)
    
    print("\n" + "="*70)
    print("🎮 INTERACTIVE TRADE ANALYZER MODE")
    print("="*70)
    print("\nCommands:")
    print("  search <name>     - Search for a player")
    print("  value <name>      - Get player value breakdown")
    print("  trade             - Analyze a custom trade")
    print("  suggest <team>    - Get 2-for-1 suggestions with a team")
    print("  suggest3 <team>   - Get 3-for-2 suggestions with a team")
    print("  teams             - List all teams")
    print("  quit              - Exit interactive mode")
    
    while True:
        try:
            cmd = input("\n> ").strip()
        except EOFError:
            break
        
        if not cmd:
            continue
        
        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if action == "quit" or action == "q":
            print("Goodbye!")
            break
        
        elif action == "search":
            results = interactive.search_players(args)
            if results:
                print(f"\nFound {len(results)} player(s):")
                for player, team in results[:10]:
                    value = interactive.calculator.calculate_player_value(player)
                    print(f"  {player.name} ({player.position}) - {team} - Value: {value:.1f}")
            else:
                print("No players found")
        
        elif action == "value":
            interactive.print_player_value(args)
        
        elif action == "teams":
            print("\nTeams:")
            for team_name in sorted(teams.keys()):
                print(f"  {team_name}: {len(teams[team_name].players)} players")
        
        elif action == "trade":
            print("\nCustom Trade Analysis")
            print("-" * 40)
            team_a_input = input("Your team (or press enter for current): ").strip() or my_team
            team_a = find_team_name(teams, team_a_input)
            if not team_a:
                print(f"❌ Team '{team_a_input}' not found")
                continue
            
            team_b_input = input("Other team: ").strip()
            team_b = find_team_name(teams, team_b_input)
            if not team_b:
                print(f"❌ Team '{team_b_input}' not found")
                continue
            
            print(f"\nPlayers from {team_a} (comma-separated names):")
            a_players = [p.strip() for p in input("> ").split(",") if p.strip()]
            
            print(f"\nPlayers from {team_b} (comma-separated names):")
            b_players = [p.strip() for p in input("> ").split(",") if p.strip()]
            
            print("\nPicks from your team (e.g., '2026 1st, 2027 2nd' or leave blank):")
            a_picks = [p.strip() for p in input("> ").split(",") if p.strip()]
            
            print(f"\nPicks from {team_b} (or leave blank):")
            b_picks = [p.strip() for p in input("> ").split(",") if p.strip()]
            
            proposal = interactive.analyze_custom_trade(
                team_a, team_b, a_players, b_players, a_picks, b_picks
            )
            
            if proposal:
                print_trade_analysis(proposal)
        
        elif action == "suggest":
            target_team = find_team_name(teams, args)
            if not target_team:
                print(f"❌ Team '{args}' not found")
                continue
            
            print(f"\nGenerating 2-for-1 trade suggestions with {target_team}...")
            suggestions = interactive.generate_multi_player_suggestions(my_team, target_team, "2-for-1")
            
            if suggestions:
                for i, s in enumerate(suggestions[:5], 1):
                    print(f"\n--- Option {i} ---")
                    print_trade_analysis(s)
            else:
                print("No suitable trades found")
        
        elif action == "suggest3":
            target_team = find_team_name(teams, args)
            if not target_team:
                print(f"❌ Team '{args}' not found")
                continue
            
            print(f"\nGenerating 3-for-2 trade suggestions with {target_team}...")
            suggestions = interactive.generate_multi_player_suggestions(my_team, target_team, "3-for-2")
            
            if suggestions:
                for i, s in enumerate(suggestions[:3], 1):
                    print(f"\n--- Option {i} ---")
                    print_trade_analysis(s)
            else:
                print("No suitable trades found")
        
        else:
            print(f"Unknown command: {action}")


def main():
    """Main entry point for V2 analyzer."""
    print("\n" + "="*70)
    print("⚾ DIAMOND DYNASTIES TRADE ANALYZER V2 ⚾")
    print("  Enhanced with 600+ projections, SV+HLD, multi-player trades")
    print("="*70)
    
    # Load data - check multiple locations
    import sys
    import os
    import glob
    
    csv_path = None
    
    # Check command line argument first
    if len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
        if os.path.exists(sys.argv[1]):
            csv_path = sys.argv[1]
    
    # If not found, search for Fantrax file in current directory
    if not csv_path:
        # Look for any file starting with "Fantrax" and ending with .csv
        matches = glob.glob('Fantrax*.csv') + glob.glob('fantrax*.csv')
        if matches:
            csv_path = matches[0]
    
    # Also check for exact name
    if not csv_path:
        exact_name = 'Fantrax-Players-Diamond_Dynasties_Owned_Players.csv'
        if os.path.exists(exact_name):
            csv_path = exact_name
    
    # Claude environment path
    if not csv_path:
        claude_path = '/mnt/user-data/uploads/Fantrax-Players-Diamond_Dynasties_Owned_Players.csv'
        if os.path.exists(claude_path):
            csv_path = claude_path
    
    if not csv_path:
        print("\n❌ Could not find Fantrax data file")
        print("\nTo use this analyzer, either:")
        print("  1. Place your Fantrax CSV file in the same folder as this script")
        print("  2. Run with path: python dynasty_trade_analyzer_v2.py path/to/file.csv")
        print("\nLooking for files matching: Fantrax*.csv")
        print(f"Current directory: {os.getcwd()}")
        print(f"Files here: {os.listdir('.')[:10]}")
        return
    
    try:
        teams = load_fantrax_data(csv_path)
        print(f"\n✅ Loaded {len(teams)} teams from: {csv_path}")
        
        # Count projection coverage
        hitter_count = len(HITTER_PROJECTIONS)
        sp_count = len(PITCHER_PROJECTIONS)
        rp_count = len(RELIEVER_PROJECTIONS)
        print(f"📊 Projection coverage: {hitter_count} hitters, {sp_count} SPs, {rp_count} RPs")
        print(f"   Total: {hitter_count + sp_count + rp_count} players with projections")
        
        for team_name in sorted(teams.keys()):
            team = teams[team_name]
            print(f"  {team_name}: {len(team.players)} players")
        
    except FileNotFoundError:
        print("❌ Could not find Fantrax data file")
        return
    
    # Check for command line flags
    if '--interactive' in sys.argv:
        run_interactive_mode(teams, "PAW")
        return
    
    if '--full' in sys.argv:
        run_full_analysis(teams, "PAW")
        return
    
    # Show menu
    print("\n" + "="*70)
    print("MAIN MENU")
    print("="*70)
    print("  1. Full Analysis (team analysis + trade suggestions)")
    print("  2. Interactive Mode (search, value, custom trades)")
    print("  3. Team Analysis Only")
    print("  4. Hitter Rankings")
    print("  5. Starting Pitcher Rankings")
    print("  6. Reliever Rankings (SV+HLD)")
    print("  7. Prospect Rankings")
    print("  8. Team Asset Summary (prospects + stars by team)")
    print("  9. Change My Team (currently PAW)")
    print("  0. Quit")
    
    my_team = "PAW"
    
    while True:
        try:
            choice = input("\nSelect option (0-9): ").strip()
        except EOFError:
            break
        
        if choice == "1":
            run_full_analysis(teams, my_team)
        elif choice == "2":
            run_interactive_mode(teams, my_team)
        elif choice == "3":
            league = LeagueAnalyzer(teams)
            if my_team in teams:
                print_team_analysis(teams[my_team], league)
            else:
                print(f"❌ Team '{my_team}' not found")
        elif choice == "4":
            print_hitter_rankings(teams)
        elif choice == "5":
            print_sp_rankings(teams)
        elif choice == "6":
            print_reliever_rankings(teams)
        elif choice == "7":
            print_prospect_rankings(teams)
        elif choice == "8":
            print_team_asset_summary(teams)
        elif choice == "9":
            print("\nAvailable teams:")
            for t in sorted(teams.keys()):
                marker = " ← current" if t == my_team else ""
                print(f"  {t}{marker}")
            new_team_input = input("\nEnter team code: ").strip()
            # Case-insensitive team matching
            new_team = None
            for t in teams.keys():
                if t.lower() == new_team_input.lower():
                    new_team = t
                    break
            if new_team:
                my_team = new_team
                print(f"✅ My team set to: {my_team}")
            else:
                print(f"❌ Team '{new_team_input}' not found")
        elif choice == "0" or choice.lower() == "q":
            print("Goodbye!")
            break
        else:
            print("Invalid option. Enter 0-9.")


def run_full_analysis(teams: Dict[str, Team], my_team: str):
    """Run the full analysis with trade suggestions."""
    league = LeagueAnalyzer(teams)
    
    if my_team in teams:
        print_team_analysis(teams[my_team], league)
        
        # Show top relievers
        print_reliever_rankings(teams)
        
        # Find trade partners
        engine = TradeSuggestionEngine(teams, my_team)
        partners = engine.find_trade_partners()
        
        print(f"\n{'='*70}")
        print("🤝 TOP TRADE PARTNERS (by need compatibility):")
        print('='*70)
        
        for partner in partners[:5]:
            print(f"\n{partner['team']} - Compatibility: {partner['compatibility']}")
            print(f"  They have what you need: {', '.join(partner['my_needs_they_have']) or 'General depth'}")
            print(f"  You have what they need: {', '.join(partner['their_needs_i_have']) or 'General depth'}")
        
        # Generate specific trade suggestions (1-for-1)
        if partners:
            top_partner = partners[0]['team']
            print(f"\n{'='*70}")
            print(f"💡 1-FOR-1 TRADE SUGGESTIONS WITH {top_partner}:")
            print('='*70)
            
            suggestions = engine.generate_trade_suggestions(top_partner, max_suggestions=3)
            
            for i, suggestion in enumerate(suggestions, 1):
                print(f"\n--- Suggestion {i} ---")
                print_trade_analysis(suggestion)
            
            # V2: Also show 2-for-1 suggestions
            print(f"\n{'='*70}")
            print(f"💡 2-FOR-1 TRADE SUGGESTIONS WITH {top_partner} (V2 Feature):")
            print('='*70)
            
            interactive = InteractiveTradeAnalyzer(teams)
            multi_suggestions = interactive.generate_multi_player_suggestions(my_team, top_partner, "2-for-1")
            
            for i, suggestion in enumerate(multi_suggestions[:3], 1):
                print(f"\n--- 2-for-1 Option {i} ---")
                print_trade_analysis(suggestion)
    
    print("\n" + "="*70)
    print("✅ Analysis complete!")
    print("="*70)


def print_reliever_rankings(teams: Dict[str, Team]):
    """Print top relievers by SV+HLD value."""
    print(f"\n{'='*70}")
    print("🔥 TOP RELIEVERS BY SV+HLD VALUE:")
    print('='*70)
    
    rp_values = []
    for team_name, team in teams.items():
        for player in team.players:
            if player.name in RELIEVER_PROJECTIONS:
                proj = RELIEVER_PROJECTIONS[player.name]
                sv_hld = proj.get('SV', 0) + proj.get('HD', 0)
                value = DynastyValueCalculator.calculate_pitcher_value(player)
                rp_values.append((player.name, team_name, sv_hld, proj.get('SV', 0), proj.get('HD', 0), value))
    
    rp_values.sort(key=lambda x: x[5], reverse=True)
    for name, team, sv_hld, sv, hd, value in rp_values[:15]:
        print(f"  {name:<22} {team:<8} SV+HLD: {sv_hld:>3} ({sv:>2}+{hd:>2}) Value: {value:.1f}")


def print_prospect_rankings(teams: Dict[str, Team]):
    """Print top prospects by dynasty value."""
    print(f"\n{'='*70}")
    print("🌟 TOP PROSPECTS BY DYNASTY VALUE:")
    print('='*70)
    
    prospect_values = []
    for team_name, team in teams.items():
        for player in team.players:
            if player.name in PROSPECT_RANKINGS:
                rank = PROSPECT_RANKINGS[player.name]
                value = DynastyValueCalculator.calculate_player_value(player)
                pos_type = "H" if player.is_hitter() else "P"
                prospect_values.append((
                    player.name, team_name, player.position, player.age,
                    rank, pos_type, value
                ))
    
    prospect_values.sort(key=lambda x: x[4])  # Sort by prospect rank
    
    print(f"  {'Name':<22} {'Team':<6} {'Pos':<8} {'Age':>3} {'Rank':>5} {'Type':>4} {'Value':>6}")
    print(f"  {'-'*22} {'-'*6} {'-'*8} {'-'*3} {'-'*5} {'-'*4} {'-'*6}")
    
    for name, team, pos, age, rank, pos_type, value in prospect_values[:30]:
        pos_short = pos[:8] if len(pos) > 8 else pos
        print(f"  {name:<22} {team:<6} {pos_short:<8} {age:>3} #{rank:<4} {pos_type:>4} {value:>6.1f}")


def print_team_asset_summary(teams: Dict[str, Team]):
    """Print summary of top players and prospects by team."""
    print(f"\n{'='*70}")
    print("🏆 TEAM ASSET SUMMARY:")
    print('='*70)
    
    team_stats = []
    
    for team_name, team in teams.items():
        top_100_prospects = 0
        top_50_prospects = 0
        top_25_prospects = 0
        top_10_prospects = 0
        elite_players = 0  # Value >= 90
        star_players = 0   # Value >= 80
        total_value = 0
        
        for player in team.players:
            value = DynastyValueCalculator.calculate_player_value(player)
            total_value += value
            
            if value >= 90:
                elite_players += 1
            if value >= 80:
                star_players += 1
            
            if player.name in PROSPECT_RANKINGS:
                rank = PROSPECT_RANKINGS[player.name]
                if rank <= 100:
                    top_100_prospects += 1
                if rank <= 50:
                    top_50_prospects += 1
                if rank <= 25:
                    top_25_prospects += 1
                if rank <= 10:
                    top_10_prospects += 1
        
        team_stats.append({
            'team': team_name,
            'top_10': top_10_prospects,
            'top_25': top_25_prospects,
            'top_50': top_50_prospects,
            'top_100': top_100_prospects,
            'elite': elite_players,
            'stars': star_players,
            'total_value': total_value
        })
    
    # Sort by total value
    team_stats.sort(key=lambda x: x['total_value'], reverse=True)
    
    print(f"\n  {'Team':<8} {'Top10':>5} {'Top25':>5} {'Top50':>5} {'Top100':>6} {'Elite':>6} {'Stars':>6} {'Total Val':>10}")
    print(f"  {'-'*8} {'-'*5} {'-'*5} {'-'*5} {'-'*6} {'-'*6} {'-'*6} {'-'*10}")
    
    for ts in team_stats:
        print(f"  {ts['team']:<8} {ts['top_10']:>5} {ts['top_25']:>5} {ts['top_50']:>5} {ts['top_100']:>6} {ts['elite']:>6} {ts['stars']:>6} {ts['total_value']:>10.1f}")
    
    # Also show prospect distribution
    print(f"\n{'='*70}")
    print("📊 TOP PROSPECT DISTRIBUTION BY TEAM:")
    print('='*70)
    
    for ts in sorted(team_stats, key=lambda x: x['top_100'], reverse=True):
        team_name = ts['team']
        
        prospects_on_team = []
        for player in teams[team_name].players:
            if player.name in PROSPECT_RANKINGS:
                rank = PROSPECT_RANKINGS[player.name]
                value = DynastyValueCalculator.calculate_player_value(player)
                prospects_on_team.append((player.name, rank, value))
        
        prospects_on_team.sort(key=lambda x: x[1])
        
        if prospects_on_team:
            print(f"\n  {team_name} ({ts['top_100']} in Top 100):")
            for name, rank, value in prospects_on_team[:5]:
                print(f"    #{rank:<3} {name:<25} Value: {value:.1f}")
        else:
            print(f"\n  {team_name}: No ranked prospects")


def print_hitter_rankings(teams: Dict[str, Team]):
    """Print top hitters by dynasty value."""
    print(f"\n{'='*70}")
    print("🏆 TOP HITTERS BY DYNASTY VALUE:")
    print('='*70)
    
    hitter_values = []
    for team_name, team in teams.items():
        for player in team.players:
            if player.is_hitter() and player.name in HITTER_PROJECTIONS:
                proj = HITTER_PROJECTIONS[player.name]
                value = DynastyValueCalculator.calculate_player_value(player)
                hitter_values.append((
                    player.name, team_name, player.position, player.age,
                    proj.get('HR', 0), proj.get('SB', 0), proj.get('AVG', 0), proj.get('OPS', 0),
                    value
                ))
    
    hitter_values.sort(key=lambda x: x[8], reverse=True)
    
    print(f"  {'Name':<22} {'Team':<6} {'Pos':<8} {'Age':>3} {'HR':>4} {'SB':>4} {'AVG':>6} {'OPS':>6} {'Value':>6}")
    print(f"  {'-'*22} {'-'*6} {'-'*8} {'-'*3} {'-'*4} {'-'*4} {'-'*6} {'-'*6} {'-'*6}")
    
    for name, team, pos, age, hr, sb, avg, ops, value in hitter_values[:25]:
        pos_short = pos[:8] if len(pos) > 8 else pos
        print(f"  {name:<22} {team:<6} {pos_short:<8} {age:>3} {hr:>4} {sb:>4} {avg:>6.3f} {ops:>6.3f} {value:>6.1f}")


def print_sp_rankings(teams: Dict[str, Team]):
    """Print top starting pitchers by dynasty value."""
    print(f"\n{'='*70}")
    print("⚾ TOP STARTING PITCHERS BY DYNASTY VALUE:")
    print('='*70)
    
    sp_values = []
    for team_name, team in teams.items():
        for player in team.players:
            if player.name in PITCHER_PROJECTIONS:
                proj = PITCHER_PROJECTIONS[player.name]
                value = DynastyValueCalculator.calculate_pitcher_value(player)
                sp_values.append((
                    player.name, team_name, player.age,
                    proj.get('K', 0), proj.get('QS', 0), proj.get('ERA', 0), 
                    proj.get('WHIP', 0), proj.get('IP', 0),
                    value
                ))
    
    sp_values.sort(key=lambda x: x[8], reverse=True)
    
    print(f"  {'Name':<22} {'Team':<6} {'Age':>3} {'K':>5} {'QS':>4} {'ERA':>5} {'WHIP':>5} {'IP':>6} {'Value':>6}")
    print(f"  {'-'*22} {'-'*6} {'-'*3} {'-'*5} {'-'*4} {'-'*5} {'-'*5} {'-'*6} {'-'*6}")
    
    for name, team, age, k, qs, era, whip, ip, value in sp_values[:25]:
        print(f"  {name:<22} {team:<6} {age:>3} {k:>5} {qs:>4} {era:>5.2f} {whip:>5.2f} {ip:>6.1f} {value:>6.1f}")


if __name__ == "__main__":
    main()

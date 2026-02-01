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
"""

import csv
import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import math


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

# ============================================================================
# DATA STRUCTURES
# ============================================================================

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

    # Hitting projections
    proj_avg: float = 0.0
    proj_ops: float = 0.0
    proj_hr: int = 0
    proj_r: int = 0
    proj_rbi: int = 0
    proj_sb: int = 0
    proj_so: int = 0  # Lower is better
    proj_ab: int = 0
    
    # Pitching projections
    proj_era: float = 0.0
    proj_whip: float = 0.0
    proj_k: int = 0
    proj_qs: int = 0
    proj_sv_hld: int = 0
    proj_l: int = 0  # Lower is better
    proj_ip: float = 0.0
    
    # Dynasty/Prospect value
    prospect_rank: int = 999  # Top 100 rank (999 = not ranked)
    is_prospect: bool = False
    
    def is_hitter(self) -> bool:
        return self.position not in ['SP', 'RP', 'P'] and self.position != 'N/A'
    
    def is_pitcher(self) -> bool:
        return self.position in ['SP', 'RP', 'P'] or 'SP' in self.position or 'RP' in self.position


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
    "Ketel Marte": {"AB": 547, "R": 89, "HR": 28, "RBI": 88, "SB": 5, "AVG": .275, "OPS": .846, "SO": 104},
    "Zach Neto": {"AB": 578, "R": 86, "HR": 27, "RBI": 79, "SB": 28, "AVG": .252, "OPS": .757, "SO": 157},
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
    "Mookie Betts": {"AB": 557, "R": 88, "HR": 22, "RBI": 79, "SB": 9, "AVG": .268, "OPS": .797, "SO": 76},
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
    "James Wood": {"AB": 550, "R": 79, "HR": 21, "RBI": 72, "SB": 22, "AVG": .262, "OPS": .775, "SO": 165},
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
    "Roki Sasaki": {"IP": 145.5, "K": 168, "W": 10, "L": 7, "ERA": 3.45, "WHIP": 1.08, "QS": 15},
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
}

# Player ages (2026 season) - used when API doesn't provide ages
# Ages calculated based on birth dates - using age they'll be for most of the 2026 season
PLAYER_AGES = {
    # Elite Young Hitters (born 2000-2004)
    "Elly De La Cruz": 24,      # Born Jan 11, 2002
    "Bobby Witt Jr.": 26,       # Born June 14, 2000
    "Gunnar Henderson": 24,     # Born June 29, 2001
    "Jackson Holliday": 22,     # Born Dec 4, 2003
    "Jackson Chourio": 22,      # Born March 11, 2004
    "Julio Rodriguez": 25,      # Born Dec 29, 2000
    "Jackson Merrill": 23,      # Born April 19, 2003
    "James Wood": 23,           # Born Sept 17, 2002
    "Roman Anthony": 22,        # Born May 13, 2004
    "Junior Caminero": 23,      # Born July 5, 2003
    "Jasson Dominguez": 23,     # Born Feb 7, 2003
    "Jordan Walker": 24,        # Born May 22, 2002
    "Colt Keith": 24,           # Born Aug 14, 2001
    "Pete Crow-Armstrong": 24,  # Born March 25, 2002
    "Evan Carter": 24,          # Born Aug 29, 2002
    "Dylan Crews": 24,          # Born Feb 20, 2002
    "Wyatt Langford": 25,       # Born Nov 15, 2001
    "Masyn Winn": 24,           # Born March 21, 2002
    "Brooks Lee": 24,           # Born Feb 1, 2002
    "Spencer Jones": 24,        # Born May 3, 2002
    "Jordan Lawlar": 23,        # Born July 18, 2002
    "Colton Cowser": 25,        # Born March 20, 2000
    "Wilyer Abreu": 25,         # Born June 24, 2000
    "Nolan Schanuel": 24,       # Born Feb 14, 2002
    "Michael Toglia": 26,       # Born Aug 16, 2000
    "Andy Pages": 24,           # Born Dec 9, 2001
    "Tyler Soderstrom": 24,     # Born Nov 24, 2001
    # Established Star Hitters
    "Corey Seager": 32, "Shohei Ohtani": 31, "Juan Soto": 27, "Mookie Betts": 33,
    "Freddie Freeman": 36, "Kyle Tucker": 29, "Jose Ramirez": 33, "Trea Turner": 33,
    "Aaron Judge": 34, "Ronald Acuna Jr.": 28, "Yordan Alvarez": 29, "Fernando Tatis Jr.": 27,
    "Riley Greene": 25, "Bo Bichette": 28, "Triston Casas": 26, "Christian Walker": 34,
    "Matt Olson": 32, "Michael Harris II": 25, "Marcell Ozuna": 35, "Marcus Semien": 35,
    "Francisco Lindor": 32, "Jake Burger": 28, "Anthony Volpe": 25, "Ozzie Albies": 29,
    "Brice Turang": 26, "Vinnie Pasquantino": 28, "Lars Nootbaar": 28, "Jack Suwinski": 28,
    "Jacob Young": 27, "JJ Bleday": 27, "Leody Taveras": 27, "Kerry Carpenter": 27,
    "Mike Trout": 34, "Vladimir Guerrero Jr.": 27, "Corbin Carroll": 25, "Bryce Harper": 33,
    "Jazz Chisholm Jr.": 28, "Ketel Marte": 32, "CJ Abrams": 25, "Luis Robert Jr.": 27,
    "Rafael Devers": 29, "Anthony Santander": 31, "Will Smith": 31, "Sal Frelick": 25,
    "Max Muncy": 35, "Jarren Duran": 28, "Jose Siri": 29, "Jose Altuve": 36,
    "Alex Bregman": 32, "Christian Yelich": 34, "Cody Bellinger": 30, "Josh Naylor": 28,
    "Oneil Cruz": 27, "Royce Lewis": 27, "Teoscar Hernandez": 33, "Nick Castellanos": 34,
    "Adolis Garcia": 33, "Bryan Reynolds": 31, "Isaac Paredes": 27, "Luis Arraez": 29,
    "Nolan Arenado": 35, "Alec Bohm": 29, "Tommy Edman": 30, "Daulton Varsho": 29,
    "Lawrence Butler": 25, "Austin Wells": 25, "Logan O'Hoppe": 26, "Chandler Simpson": 25, "Victor Scott II": 25,
    "Shea Langeliers": 27, "Ceddanne Rafaela": 25, "Ke'Bryan Hayes": 29, "Ryan O'Hearn": 31,
    "Jose Caballero": 28,
    # Elite Pitchers (ages verified for 2026 season)
    "Tarik Skubal": 29, "Paul Skenes": 23, "Garrett Crochet": 26, "Cristopher Sanchez": 29,  # Skenes: May 29, 2002
    "Logan Webb": 29, "Logan Gilbert": 29, "Bryan Woo": 26, "Hunter Brown": 27,  # Woo: Jan 30, 2000
    "Max Fried": 32, "Chris Sale": 37, "Jacob deGrom": 38, "Yoshinobu Yamamoto": 27,
    "Hunter Greene": 26, "George Kirby": 28, "Cole Ragans": 28, "Joe Ryan": 29,  # Greene: Aug 6, 1999
    "Framber Valdez": 32, "Jesus Luzardo": 28, "Spencer Schwellenbach": 25, "Dylan Cease": 30,  # Schwellenbach: May 31, 2000
    "Nathan Eovaldi": 36, "Sonny Gray": 36, "Nick Pivetta": 33, "Freddy Peralta": 30,
    "Zack Wheeler": 36, "Kevin Gausman": 35, "Luis Castillo": 33, "Pablo Lopez": 30,
    "Blake Snell": 33, "Brandon Woodruff": 33, "Tyler Glasnow": 32, "Gerrit Cole": 35,
    "Kyle Bradish": 29, "Shane McClanahan": 28, "Joe Musgrove": 33, "Nick Lodolo": 27,  # Lodolo: Feb 5, 1998
    "Chase Burns": 23, "Ranger Suarez": 30, "Kris Bubic": 28, "Matthew Boyd": 35,  # Burns: Jan 16, 2003
    "David Peterson": 30, "Ryan Weathers": 26, "Joe Boyle": 26, "Robert Gasser": 26,
    "Payton Tolle": 26, "Andrew Alvarez": 23, "Seth Lugo": 36, "Shota Imanaga": 32,  # Imanaga: Sept 1, 1993
    "Jared Jones": 24, "Tanner Bibee": 26, "Luis Gil": 27, "Michael King": 30,  # Jones: Aug 6, 2001, Bibee: Mar 5, 1999
    "Grayson Rodriguez": 26, "Corbin Burnes": 31, "Roki Sasaki": 24, "Bryce Miller": 27,  # Rodriguez: Nov 16, 1999, Sasaki: Nov 3, 2001, Miller: Aug 23, 1998
    "Bailey Ober": 30, "Brady Singer": 29, "Cade Horton": 24, "AJ Smith-Shawver": 23,  # Horton: Aug 20, 2001, Smith-Shawver: Nov 20, 2002
    "Carlos Rodon": 33,
    # Unproven pitchers with high prospect pedigree but minimal MLB track record
    "Forrest Whitley": 27,  # Born Sept 15, 1997 - only ~10 career IP
    "Davis Martin": 28,     # Born Sept 4, 1997 - limited MLB innings
    # Relievers (ages verified for 2026 season)
    "Mason Miller": 27, "Edwin Diaz": 32, "Cade Smith": 26, "Jhoan Duran": 28,  # Mason Miller: Aug 24, 1998, Duran: Jan 8, 1998
    "Josh Hader": 32, "Andres Munoz": 27, "Aroldis Chapman": 38, "Devin Williams": 31,  # Munoz: Jan 16, 1999
    "David Bednar": 30, "Griffin Jax": 30, "Raisel Iglesias": 36, "Abner Uribe": 25,
    "Ryan Walker": 28, "Jeff Hoffman": 33, "Ryan Helsley": 31, "Daniel Palencia": 26,
    "Pete Fairbanks": 32, "Trevor Megill": 32, "Emilio Pagan": 34, "Carlos Estevez": 33,
    "Kenley Jansen": 38, "Grant Taylor": 26, "Bryan Abreu": 28, "Jeremiah Estrada": 27,
    "Garrett Whitlock": 29, "Alex Vesia": 29, "Tanner Scott": 30, "Adrian Morejon": 27,
    "Robert Suarez": 35, "Matt Brash": 26, "A.J. Minter": 32, "Tyler Rogers": 34,
    "Bryan King": 27, "Jared Koenig": 30, "Dylan Lee": 30, "Jose A. Ferrer": 25,
    "Garrett Cleavinger": 30, "Will Vest": 29, "Matt Strahm": 32, "Phil Maton": 33,
    "Andrew Kittredge": 36, "JoJo Romero": 28, "Riley O'Brien": 30, "Tyler Holton": 28,
    "Luke Weaver": 32, "Gabe Speier": 31, "Orion Kerkering": 25, "Louis Varland": 28,
    "Seranthony Dominguez": 31, "Fernando Cruz": 36, "Jose Alvarado": 30, "Camilo Doval": 28,
    "Robert Stephenson": 33, "Clayton Beeter": 26, "Robert Garcia": 27, "Dennis Santana": 29,
    "Edwin Uceta": 28, "Victor Vodnik": 27, "Tony Santillan": 29, "Blake Treinen": 38,
    "Caleb Thielbar": 38, "Shawn Armstrong": 36, "Eduard Bazardo": 31, "Hunter Harvey": 31,
    "Hunter Gaddis": 27, "Cole Sands": 29, "Chris Martin": 40, "Yimi Garcia": 35,
    "Kyle Finnegan": 33, "Lucas Erceg": 31, "Steven Okert": 35, "Bryan Baker": 32,
    "Kirby Yates": 37, "Jordan Leasure": 27, "Brusdar Graterol": 27, "Taylor Rogers": 34,
    "Kevin Ginkel": 30,
}

# Pitchers with minimal MLB track record whose projections are unreliable
# These get an 80% discount regardless of fantrax data
UNPROVEN_PITCHERS = {
    "Forrest Whitley",   # ~10 career IP, former top prospect
}

# Elite young players who deserve ADDITIONAL boost beyond the automatic elite category boost
# The automatic boost (in calculate_hitter_value) handles: HR≥35, SB≥35, AVG≥.300, RBI≥110
# This manual list is for truly exceptional talents whose dynasty value exceeds even that
# Format: "Player Name": bonus_multiplier (1.15 = +15% ADDITIONAL boost, stacks with automatic)
ELITE_YOUNG_PLAYERS = {
    # Tier 1: Generational/MVP-caliber young superstars (20%+ additional boost)
    "Elly De La Cruz": 1.20,      # 24yo SS, elite speed/power combo, 40+ SB, 25+ HR upside
    "Bobby Witt Jr.": 1.20,       # 26yo SS, 30/30 caliber, MVP candidate
    "Gunnar Henderson": 1.20,     # 24yo SS, elite power, future MVP
    "Julio Rodriguez": 1.15,      # 25yo OF, superstar ceiling when healthy
    "Corbin Carroll": 1.15,       # 25yo OF, elite speed/plate discipline
    "Jackson Chourio": 1.18,      # 22yo OF, 5-tool potential, youngest superstar
    "Jackson Holliday": 1.18,     # 22yo 2B, #1 prospect pedigree, elite bat
    # Tier 2: Established young stars (15% boost)
    "CJ Abrams": 1.15,            # 25yo SS, breakout speed/power
    "Anthony Volpe": 1.12,        # 25yo SS, premium position, solid production
    "Michael Harris II": 1.15,    # 25yo OF, elite defense + bat
    "Riley Greene": 1.12,         # 25yo OF, consistent production, high floor
    "Evan Carter": 1.12,          # 24yo OF, elite plate discipline
    "Masyn Winn": 1.12,           # 24yo SS, speed/defense combo
    "Colton Cowser": 1.10,        # 25yo OF, balanced offensive profile
    # Tier 3: Rising young stars (10% boost)
    "Jordan Lawlar": 1.10,        # 23yo SS, elite prospect pedigree
    "Jackson Merrill": 1.12,      # 23yo OF, breakout 2024
    "Wyatt Langford": 1.10,       # 25yo OF, power upside
    "Pete Crow-Armstrong": 1.10,  # 24yo OF, elite CF defense
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
        """Calculate reliever value with SV+HLD emphasis but scaled appropriately."""
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
        
        # Reliever discount - only elite closers should approach SP value
        # This caps most relievers well below top starters
        value = value * 0.85

        # Apply dynasty adjustments (age, prospect status) - same as SP and hitters
        value = DynastyValueCalculator._apply_dynasty_adjustments(player, value, is_hitter=False)

        # Apply unproven pitcher discount
        value = DynastyValueCalculator._apply_unproven_pitcher_discount(player, value)

        return value  # No cap - show true dynasty value
    
    @staticmethod
    def _apply_dynasty_adjustments(player: Player, base_value: float, is_hitter: bool) -> float:
        """Apply dynasty-specific adjustments (age, prospect status, position scarcity)."""
        value = base_value
        bonus_multiplier = 1.0  # Track bonuses to cap stacking

        # Age adjustments - Dynasty leagues value youth heavily, older players decline steeply
        # Young players have longest runway, older players are rental value only
        # Prime years (25-29) hold full value, decline starts at 30+
        if player.age > 0:
            # Same curve for hitters and pitchers in dynasty
            if player.age <= 19:
                bonus_multiplier += 0.20  # Extreme youth premium
            elif player.age <= 21:
                bonus_multiplier += 0.15  # Youth premium
            elif player.age <= 24:
                bonus_multiplier += 0.10  # Approaching prime
            elif player.age <= 29:
                bonus_multiplier += 0.00  # Peak prime years (baseline)
            elif player.age <= 31:
                bonus_multiplier -= 0.10  # Late prime, still valuable
            elif player.age <= 33:
                bonus_multiplier -= 0.25  # Early 30s decline
            elif player.age <= 35:
                bonus_multiplier -= 0.45  # Mid 30s decline
            elif player.age <= 37:
                bonus_multiplier -= 0.65  # Late 30s steep decline
            else:  # 38+
                bonus_multiplier -= 0.80  # End of career

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

        # Cap the total bonus/penalty - lowered floor to allow steep age decline
        bonus_multiplier = max(0.20, min(bonus_multiplier, 1.25))
        value *= bonus_multiplier

        # Elite young player boost - proven MLB talents whose dynasty value exceeds projections
        # Applied AFTER age/position adjustments, BEFORE prospect overrides
        if player.name in ELITE_YOUNG_PLAYERS:
            elite_boost = ELITE_YOUNG_PLAYERS[player.name]
            value *= elite_boost

        # Prospect adjustments - aligned with new dynasty value tiers
        # Top prospects are valuable dynasty assets with high upside
        if player.name in PROSPECT_RANKINGS:
            rank = PROSPECT_RANKINGS[player.name]

            # Tiered prospect valuation (aligned with Superstar 90+, Elite 75+, Star 60+, Solid 40+)
            if rank <= 0 or rank > 300:
                prospect_value = 0.5
            elif rank <= 5:
                # Top 5: 90 at rank 1, 80 at rank 5 (SUPERSTAR/ELITE)
                prospect_value = 90 - (rank - 1) * 2.5
            elif rank <= 10:
                # Top 10: 78 at rank 6, 70 at rank 10 (ELITE/STAR)
                prospect_value = 78 - (rank - 6) * 1.6
            elif rank <= 25:
                # 11-25: 68 at rank 11, 53 at rank 25 (STAR/SOLID)
                prospect_value = 68 - (rank - 11) * 1.07
            elif rank <= 50:
                # 26-50: 52 at rank 26, 35 at rank 50 (SOLID)
                prospect_value = 52 - (rank - 26) * 0.68
            elif rank <= 100:
                # 51-100: 34 at rank 51, 15 at rank 100 (SOLID/DEPTH)
                prospect_value = 34 - (rank - 51) * 0.39
            elif rank <= 200:
                # 101-200: 14 at rank 101, 5 at rank 200 (DEPTH)
                prospect_value = 14 - (rank - 101) * 0.09
            else:
                # 201-300: 4.5 at rank 201, 1 at rank 300 (DEPTH)
                prospect_value = 4.5 - (rank - 201) * 0.035

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

        # If in hitter projections only, calculate as hitter
        if in_hitter_proj and not in_pitcher_proj:
            return DynastyValueCalculator.calculate_hitter_value(player, actual_stats)
        # If in pitcher projections only, calculate as pitcher
        elif in_pitcher_proj and not in_hitter_proj:
            return DynastyValueCalculator.calculate_pitcher_value(player)
        # If in both (true two-way player like Ohtani), combine values with premium
        # Two-way players are extraordinarily valuable - they provide dual production in one roster spot
        elif in_hitter_proj and in_pitcher_proj:
            hitter_val = DynastyValueCalculator.calculate_hitter_value(player, actual_stats)
            pitcher_val = DynastyValueCalculator.calculate_pitcher_value(player)
            # Take higher value as base, add 40% of secondary value, plus 10% two-way premium
            primary = max(hitter_val, pitcher_val)
            secondary = min(hitter_val, pitcher_val)
            two_way_value = primary + (secondary * 0.40) + (primary * 0.10)
            return two_way_value  # Can exceed 100 for exceptional two-way players
        # Fall back to position-based detection
        elif player.is_pitcher():
            return DynastyValueCalculator.calculate_pitcher_value(player)
        else:
            return DynastyValueCalculator.calculate_hitter_value(player, actual_stats)
    
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

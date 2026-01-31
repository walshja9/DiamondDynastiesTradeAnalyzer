"""
Diamond Dynasties Trade Analyzer - Web Version
Designed for deployment on Render, Railway, or similar platforms.
"""

import os
import json
from flask import Flask, request, jsonify, Response
from itertools import combinations

# Import from the core analyzer module
from dynasty_trade_analyzer_v2 import (
    load_fantrax_data,
    LeagueAnalyzer,
    TradeAnalyzer,
    InteractiveTradeAnalyzer,
    TradeSuggestionEngine,
    DynastyValueCalculator,
    TradeProposal,
    Player,
    Team,
    HITTER_PROJECTIONS,
    PITCHER_PROJECTIONS,
    RELIEVER_PROJECTIONS,
    PROSPECT_RANKINGS,
    PLAYER_AGES,
)

# Fantrax API imports
try:
    from fantraxapi import FantraxAPI
    FANTRAX_AVAILABLE = True
except ImportError:
    FANTRAX_AVAILABLE = False
    print("Warning: fantraxapi not installed. API refresh will be unavailable.")

# ============================================================================
# CONFIGURATION
# ============================================================================

FANTRAX_LEAGUE_ID = os.environ.get("FANTRAX_LEAGUE_ID", "3iibc548mhhszwor")

# Team rivalries - bidirectional matchups for enhanced analysis
TEAM_RIVALRIES = {
    "Rocket City Trash Pandas": "Alaskan Bullworms",
    "Alaskan Bullworms": "Rocket City Trash Pandas",
    "Colt 45s": "Sugar Land Space Cowboys",
    "Sugar Land Space Cowboys": "Colt 45s",
    "Pawtucket Red Sox": "Danville Dairy Daddies",
    "Danville Dairy Daddies": "Pawtucket Red Sox",
    "Boston Beaneaters": "Akron Rubberducks",
    "Akron Rubberducks": "Boston Beaneaters",
    "Kalamazoo Celery Pickers": "Hartford Yard Goats",
    "Hartford Yard Goats": "Kalamazoo Celery Pickers",
    "Hershey Bears": "Modesto Nuts",
    "Modesto Nuts": "Hershey Bears",
}

# Historical rivalry H2H records (2025 season)
# Format: {team_name: {"record": "W-L-T", "h2h": "W-L-T", "rival_record": "W-L-T", "rival_h2h": "W-L-T"}}
RIVALRY_HISTORY = {
    "Danville Dairy Daddies": {"record": "14-13-1", "h2h": "1-0-1", "rival_record": "13-14-1", "rival_h2h": "0-1-1"},
    "Pawtucket Red Sox": {"record": "13-14-1", "h2h": "0-1-1", "rival_record": "14-13-1", "rival_h2h": "1-0-1"},
    "Akron Rubberducks": {"record": "10-16-2", "h2h": "0-2", "rival_record": "16-10-2", "rival_h2h": "2-0"},
    "Boston Beaneaters": {"record": "16-10-2", "h2h": "2-0", "rival_record": "10-16-2", "rival_h2h": "0-2"},
    "Alaskan Bullworms": {"record": "5-23", "h2h": "0-2", "rival_record": "23-5", "rival_h2h": "2-0"},
    "Rocket City Trash Pandas": {"record": "23-5", "h2h": "2-0", "rival_record": "5-23", "rival_h2h": "0-2"},
    "Colt 45s": {"record": "19-9", "h2h": "2-0", "rival_record": "9-19", "rival_h2h": "0-2"},
    "Sugar Land Space Cowboys": {"record": "9-19", "h2h": "0-2", "rival_record": "19-9", "rival_h2h": "2-0"},
    "Hartford Yard Goats": {"record": "15-13", "h2h": "2-0", "rival_record": "13-15", "rival_h2h": "0-2"},
    "Kalamazoo Celery Pickers": {"record": "13-15", "h2h": "0-2", "rival_record": "15-13", "rival_h2h": "2-0"},
    "Modesto Nuts": {"record": "16-10-2", "h2h": "1-1", "rival_record": "10-16-2", "rival_h2h": "1-1"},
    "Hershey Bears": {"record": "10-16-2", "h2h": "1-1", "rival_record": "16-10-2", "rival_h2h": "1-1"},
}

# ============================================================================
# GM PHILOSOPHY & TEAM PERSONALITY SYSTEM
# ============================================================================

GM_PHILOSOPHIES = {
    "win_now": {
        "name": "Win-Now Contender",
        "description": "Aggressive buyer willing to pay premium for proven talent.",
        "prospect_trade_penalty": 0.15,
        "proven_talent_bonus": 0.20,
        "age_tolerance": 34,
        "risk_tolerance": 0.7
    },
    "dynasty_builder": {
        "name": "Dynasty Builder",
        "description": "Focuses on building sustainable success through young talent.",
        "prospect_trade_penalty": -0.25,
        "proven_talent_bonus": -0.10,
        "age_tolerance": 28,
        "risk_tolerance": 0.4
    },
    "balanced": {
        "name": "Balanced Approach",
        "description": "Evaluates trades purely on value, balancing present and future.",
        "prospect_trade_penalty": 0.0,
        "proven_talent_bonus": 0.0,
        "age_tolerance": 31,
        "risk_tolerance": 0.5
    },
    "value_seeker": {
        "name": "Value Seeker",
        "description": "Opportunistic trader who buys low and sells high.",
        "prospect_trade_penalty": 0.05,
        "proven_talent_bonus": -0.05,
        "age_tolerance": 30,
        "risk_tolerance": 0.6
    },
    "prospect_hoarder": {
        "name": "Prospect Hoarder",
        "description": "Extremely protective of prospects. Only trades young talent for overpays.",
        "prospect_trade_penalty": -0.35,
        "proven_talent_bonus": -0.15,
        "age_tolerance": 26,
        "risk_tolerance": 0.3
    }
}

# ASSISTANT GM PERSONALITIES - Unique AI advisor for each team
# ============================================================================
ASSISTANT_GMS = {
    "Akron Rubber Ducks": {
        "name": "Stretch McGee",
        "title": "Assistant GM",
        "philosophy": "value_seeker",
        "personality": "Resilient and opportunistic. Bounces back from setbacks and always finds value where others don't see it.",
        "catchphrases": [
            "Flexibility wins championships.",
            "Every setback is a setup for a comeback.",
            "The market always overcorrects - be ready.",
            "Patience is just aggression waiting for the right moment."
        ],
        "trade_style": "Buy low, sell high. Loves targeting slumping players and selling hot streaks.",
        "priorities": ["value_arbitrage", "buy_low_candidates", "sell_high_windows"],
        "risk_tolerance": 0.65,
        "preferred_categories": ["R", "RBI", "QS"]
    },
    "Alaskan Bullworms": {
        "name": "Frosty Carlson",
        "title": "Assistant GM",
        "philosophy": "dynasty_builder",
        "personality": "Cold, calculating, and endlessly patient. Plays the long game while others chase quick wins.",
        "catchphrases": [
            "Winter is coming for everyone else's roster.",
            "Prospects are like permafrost - valuable when preserved.",
            "Let them overpay now. We'll own the future.",
            "The coldest take is usually the right one."
        ],
        "trade_style": "Accumulate young assets. Never panic. Let desperation come to you.",
        "priorities": ["prospect_acquisition", "young_talent", "draft_picks"],
        "risk_tolerance": 0.35,
        "preferred_categories": ["SB", "K", "K/BB"]
    },
    "Boston Beaneaters": {
        "name": "Old School O'Brien",
        "title": "Assistant GM",
        "philosophy": "win_now",
        "personality": "Traditional baseball man who values proven track records over projections. Championship or bust.",
        "catchphrases": [
            "Prospects are just lottery tickets with good PR.",
            "Give me the guy who's done it, not the guy who might.",
            "You can't win with potential.",
            "Championships aren't won in the future."
        ],
        "trade_style": "Aggressive acquirer of established talent. Will pay premium for proven winners.",
        "priorities": ["proven_production", "veteran_leadership", "playoff_experience"],
        "risk_tolerance": 0.75,
        "preferred_categories": ["HR", "RBI", "QS"]
    },
    "Colt 45s": {
        "name": "Trigger Thompson",
        "title": "Assistant GM",
        "philosophy": "win_now",
        "personality": "Shoot first, ask questions later. Bold, aggressive, and unafraid to make the big move.",
        "catchphrases": [
            "Fortune favors the bold.",
            "You miss 100% of the trades you don't make.",
            "While they're thinking, we're winning.",
            "The best defense is a overwhelming offense."
        ],
        "trade_style": "Fast, decisive moves. First to market on emerging opportunities.",
        "priorities": ["impact_bats", "elite_arms", "championship_windows"],
        "risk_tolerance": 0.85,
        "preferred_categories": ["HR", "SB", "SV+HLD"]
    },
    "Danville Dairy Daddies": {
        "name": "The Milkman Morrison",
        "title": "Assistant GM",
        "philosophy": "balanced",
        "personality": "Reliable, consistent, delivers value day in and day out. No flashy moves, just steady excellence.",
        "catchphrases": [
            "Consistency is the secret ingredient.",
            "We deliver value, rain or shine.",
            "No need to be fancy when fundamentals work.",
            "Trust the process, enjoy the cream rising to the top."
        ],
        "trade_style": "Methodical evaluation. Fair deals that make sense for both sides.",
        "priorities": ["roster_balance", "category_coverage", "sustainable_value"],
        "risk_tolerance": 0.50,
        "preferred_categories": ["R", "RBI", "ERA"]
    },
    "Hartford Yard GOATS": {
        "name": "Billy Gruff",
        "title": "Assistant GM",
        "philosophy": "prospect_hoarder",
        "personality": "Stubborn protector of the farm system. Won't be pushed around in negotiations.",
        "catchphrases": [
            "Nobody crosses this bridge without paying toll.",
            "My prospects aren't for sale... unless you're overpaying.",
            "I've seen your offer. Now triple it.",
            "You want my young talent? What's your firstborn worth?"
        ],
        "trade_style": "Hard bargainer. Extracts maximum value. Rarely parts with prospects.",
        "priorities": ["farm_system_protection", "prospect_development", "fair_value_plus"],
        "risk_tolerance": 0.30,
        "preferred_categories": ["K", "WHIP", "SB"]
    },
    "Hershey Bears": {
        "name": "Sweet Deal Henderson",
        "title": "Assistant GM",
        "philosophy": "value_seeker",
        "personality": "Makes every trade a little sweeter for both sides. Master of win-win negotiations.",
        "catchphrases": [
            "Let me sweeten the pot for you.",
            "Good trades should taste like victory for everyone.",
            "The best deals leave both sides smiling.",
            "A little extra never hurt anybody."
        ],
        "trade_style": "Creative dealmaker. Finds hidden value and sweeteners to close deals.",
        "priorities": ["creative_packages", "mutual_value", "relationship_building"],
        "risk_tolerance": 0.55,
        "preferred_categories": ["RBI", "R", "K"]
    },
    "Kalamazoo Celery Pickers": {
        "name": "Fresh Fitzgerald",
        "title": "Assistant GM",
        "philosophy": "dynasty_builder",
        "personality": "Loves crunchy young prospects. Believes in organic roster growth over quick fixes.",
        "catchphrases": [
            "Fresh talent beats stale veterans every time.",
            "We're growing something special here.",
            "Age is more than a number - it's a trajectory.",
            "Plant seeds now, harvest championships later."
        ],
        "trade_style": "Youth-focused acquisitions. Sell veterans for maximum prospect return.",
        "priorities": ["young_players", "upside_potential", "age_curves"],
        "risk_tolerance": 0.40,
        "preferred_categories": ["SB", "R", "K"]
    },
    "Modesto Nuts": {
        "name": "Nutty Nichols",
        "title": "Assistant GM",
        "philosophy": "value_seeker",
        "personality": "Unpredictable and unconventional. Makes bold moves that seem crazy until they work.",
        "catchphrases": [
            "Sanity is overrated in this business.",
            "The craziest trade is the one you didn't make.",
            "They called me nuts. Then they called me champion.",
            "Normal gets you normal results."
        ],
        "trade_style": "Outside-the-box thinking. Contrarian moves. High volatility, high reward.",
        "priorities": ["contrarian_plays", "overlooked_value", "bold_moves"],
        "risk_tolerance": 0.80,
        "preferred_categories": ["HR", "SV+HLD", "SO"]
    },
    "Pawtucket Red Sox": {
        "name": "Paw Patterson",
        "title": "Assistant GM",
        "philosophy": "dynasty_builder",
        "personality": "Patient farm system developer. Believes in growing talent from within.",
        "catchphrases": [
            "The farm feeds the future.",
            "Development beats desperation.",
            "Every prospect tells a story - ours have happy endings.",
            "Rush the process, ruin the product."
        ],
        "trade_style": "Acquire raw talent and develop it. Rarely trades homegrown players.",
        "priorities": ["player_development", "raw_tools", "system_depth"],
        "risk_tolerance": 0.35,
        "preferred_categories": ["K", "SB", "WHIP"]
    },
    "Rocket City Trash Pandas": {
        "name": "Rocket Rodriguez",
        "title": "Assistant GM",
        "philosophy": "win_now",
        "personality": "Explosive and ambitious. Launches bold attacks on championship windows.",
        "catchphrases": [
            "We're going to the moon - championships or bust.",
            "Light the fuse and watch us fly.",
            "No mission is impossible with the right roster.",
            "Count down to glory starts now."
        ],
        "trade_style": "All-in mentality when window opens. Aggressive consolidation of talent.",
        "priorities": ["championship_runs", "star_acquisition", "roster_optimization"],
        "risk_tolerance": 0.85,
        "preferred_categories": ["HR", "RBI", "QS"]
    },
    "Sugar Land Space Cowboys": {
        "name": "Starman Stevens",
        "title": "Assistant GM",
        "philosophy": "balanced",
        "personality": "Calculated and analytical. Uses data to navigate the vast trade universe.",
        "catchphrases": [
            "The numbers don't lie - they just whisper.",
            "In space, nobody hears you overpay.",
            "Chart your course with data, not emotion.",
            "The trade frontier rewards the prepared mind."
        ],
        "trade_style": "Data-driven decisions. Analytical approach to value assessment.",
        "priorities": ["analytical_edge", "market_inefficiency", "projection_accuracy"],
        "risk_tolerance": 0.50,
        "preferred_categories": ["K/BB", "ERA", "R"]
    }
}

def get_assistant_gm(team_name):
    """Get the Assistant GM personality for a team"""
    return ASSISTANT_GMS.get(team_name, {
        "name": "Assistant GM",
        "title": "Assistant GM",
        "philosophy": "balanced",
        "personality": "Analytical and balanced approach to roster construction.",
        "catchphrases": ["Build smart, compete hard."],
        "trade_style": "Value-focused evaluation.",
        "priorities": ["value", "balance"],
        "risk_tolerance": 0.5,
        "preferred_categories": []
    })

def get_gm_advice(team_name, context_type, context_data=None):
    """Generate personalized advice from the team's Assistant GM"""
    import random
    gm = get_assistant_gm(team_name)
    catchphrase = random.choice(gm['catchphrases'])

    advice = {
        "gm_name": gm['name'],
        "gm_title": gm['title'],
        "catchphrase": catchphrase,
        "philosophy": gm['philosophy'],
        "risk_tolerance": gm['risk_tolerance']
    }

    return advice

DEFAULT_TEAM_PROFILE = {
    "gm_name": "",
    "philosophy": "balanced",
    "trade_aggressiveness": 0.5,
    "risk_tolerance": 0.5,
    "position_priorities": [],
    "category_priorities": [],
    "custom_notes": ""
}

TEAM_PROFILES_FILE = os.path.join(os.path.dirname(__file__), "team_profiles.json")

def load_team_profiles():
    if os.path.exists(TEAM_PROFILES_FILE):
        try:
            with open(TEAM_PROFILES_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_team_profiles(profiles):
    try:
        with open(TEAM_PROFILES_FILE, 'w') as f:
            json.dump(profiles, f, indent=2)
        return True
    except IOError:
        return False

def get_team_profile(team_name):
    profiles = load_team_profiles()
    if team_name in profiles:
        profile = DEFAULT_TEAM_PROFILE.copy()
        profile.update(profiles[team_name])
        return profile
    return DEFAULT_TEAM_PROFILE.copy()

def update_team_profile(team_name, updates):
    profiles = load_team_profiles()
    if team_name not in profiles:
        profiles[team_name] = DEFAULT_TEAM_PROFILE.copy()
    profiles[team_name].update(updates)
    return save_team_profiles(profiles)

app = Flask(__name__)

# Name aliases: Fantrax name -> Fangraphs/projection name
# Used to match players with different name formats
NAME_ALIASES = {
    "Andres Gimenez": "Andrés Giménez",
    "Ha-seong Kim": "Ha-Seong Kim",
    "Simeon Woods-Richardson": "Simeon Woods Richardson",
    "Luis Garcia Jr.": "Luis García Jr.",
    "Wander Franco": "Wander Franco",
    "Yainer Diaz": "Yainer Díaz",
    "Ozzie Albies": "Ozzie Albies",
    "Ronald Acuna Jr.": "Ronald Acuña Jr.",
    "Vladimir Guerrero Jr.": "Vladimir Guerrero Jr.",
    "Jose Ramirez": "José Ramírez",
    "Rafael Devers": "Rafael Devers",
    "Yordan Alvarez": "Yordan Alvarez",
    "Luis Robert Jr.": "Luis Robert Jr.",
    "Julio Rodriguez": "Julio Rodríguez",
}

# Prospect name aliases: Fantrax name -> Prospect ranking name
# Used to match prospects with different name formats between Fantrax and ranking sources
PROSPECT_NAME_ALIASES = {
    "Leodalis De Vries": "Leo De Vries",
    "J.R. Ritchie": "JR Ritchie",
    "Elmer Rodriguez": "Elmer Rodriguez-Cruz",
    "Sean Paul Linan": "Sean Linan",
    "Kalai Rosario": "Kala'i Rosario",  # FA CSV has no apostrophe
    "Hao-Yu Lee": "Hao-Yu  Lee",  # Prospect ranking has extra space
}

def add_name_aliases_to_projections():
    """Add alternate name lookups to projection dictionaries."""
    for fantrax_name, proj_name in NAME_ALIASES.items():
        # If projection exists under the accented name, add it under the Fantrax name too
        if proj_name in HITTER_PROJECTIONS and fantrax_name not in HITTER_PROJECTIONS:
            HITTER_PROJECTIONS[fantrax_name] = HITTER_PROJECTIONS[proj_name]
        if proj_name in PITCHER_PROJECTIONS and fantrax_name not in PITCHER_PROJECTIONS:
            PITCHER_PROJECTIONS[fantrax_name] = PITCHER_PROJECTIONS[proj_name]
        if proj_name in RELIEVER_PROJECTIONS and fantrax_name not in RELIEVER_PROJECTIONS:
            RELIEVER_PROJECTIONS[fantrax_name] = RELIEVER_PROJECTIONS[proj_name]


def add_prospect_name_aliases_to_rankings():
    """Add alternate name lookups to PROSPECT_RANKINGS dictionary.

    This allows the dynasty_trade_analyzer_v2 module to find prospects
    using Fantrax names (e.g., "J.R. Ritchie") even when the prospect
    ranking uses a different format (e.g., "JR Ritchie").
    """
    for fantrax_name, prospect_name in PROSPECT_NAME_ALIASES.items():
        # If prospect exists under the ranking name, add it under the Fantrax name too
        if prospect_name in PROSPECT_RANKINGS and fantrax_name not in PROSPECT_RANKINGS:
            PROSPECT_RANKINGS[fantrax_name] = PROSPECT_RANKINGS[prospect_name]
            print(f"Added prospect alias: {fantrax_name} -> {prospect_name} (rank {PROSPECT_RANKINGS[prospect_name]})")


# Normalized prospect name lookup table (built after prospect rankings are loaded)
NORMALIZED_PROSPECT_LOOKUP = {}  # normalized_name -> original_name

# Prospect metadata (position, age, mlb_team) for displaying prospects not in league
PROSPECT_METADATA = {}  # name -> {position, age, mlb_team}


def normalize_name(name):
    """Normalize a player name for matching purposes.

    - Strips whitespace
    - Converts to lowercase
    - Removes accents (José -> jose)
    - Normalizes Jr./Jr/Junior suffixes
    - Removes periods and hyphens
    """
    import unicodedata

    if not name:
        return ""

    # Strip whitespace
    name = name.strip()

    # Convert to lowercase
    name = name.lower()

    # Remove accents by decomposing unicode and keeping only ASCII
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')

    # Normalize Jr variations
    name = name.replace(' jr.', ' jr').replace(' jr', '').replace(' junior', '')

    # Remove periods and hyphens
    name = name.replace('.', '').replace('-', ' ')

    # Collapse multiple spaces
    name = ' '.join(name.split())

    return name


def build_normalized_prospect_lookup():
    """Build a normalized lookup table for prospect names.

    This allows matching 'Jose Garcia' to 'José García' in prospect rankings.
    """
    global NORMALIZED_PROSPECT_LOOKUP
    NORMALIZED_PROSPECT_LOOKUP.clear()

    for original_name in PROSPECT_RANKINGS.keys():
        normalized = normalize_name(original_name)
        NORMALIZED_PROSPECT_LOOKUP[normalized] = original_name

    print(f"Built normalized prospect lookup with {len(NORMALIZED_PROSPECT_LOOKUP)} entries")


def get_prospect_rank_for_name(name):
    """Get prospect rank for a player name, using normalized matching.

    Returns (rank, matched_name) tuple, or (None, None) if not found.
    The matched_name is always the canonical prospect ranking name.
    """
    if not name:
        return None, None

    # Check aliases FIRST - this ensures we return the canonical prospect name
    # even after aliases are added to PROSPECT_RANKINGS
    if name in PROSPECT_NAME_ALIASES:
        alias_name = PROSPECT_NAME_ALIASES[name]
        if alias_name in PROSPECT_RANKINGS:
            return PROSPECT_RANKINGS[alias_name], alias_name

    # Try exact match (for names that aren't aliases)
    if name in PROSPECT_RANKINGS:
        return PROSPECT_RANKINGS[name], name

    # Try normalized match
    normalized = normalize_name(name)
    if normalized in NORMALIZED_PROSPECT_LOOKUP:
        original_name = NORMALIZED_PROSPECT_LOOKUP[normalized]
        return PROSPECT_RANKINGS[original_name], original_name

    return None, None


def debug_prospect_lookup_sample():
    """Debug function to print sample prospect lookups on startup."""
    print(f"\n=== PROSPECT LOOKUP DEBUG ===")
    print(f"PROSPECT_RANKINGS has {len(PROSPECT_RANKINGS)} entries")
    print(f"NORMALIZED_PROSPECT_LOOKUP has {len(NORMALIZED_PROSPECT_LOOKUP)} entries")

    # Show first 5 prospects for verification
    sample_prospects = list(PROSPECT_RANKINGS.items())[:5]
    print(f"Sample prospects: {sample_prospects}")

    # Show first 5 normalized entries
    sample_normalized = list(NORMALIZED_PROSPECT_LOOKUP.items())[:5]
    print(f"Sample normalized: {sample_normalized}")
    print(f"=== END DEBUG ===\n")

# Global state
teams = {}
interactive = None
calculator = DynastyValueCalculator()

# League data
league_standings = []
league_matchups = []
league_transactions = []

# Player stats (actual in-season stats)
player_actual_stats = {}  # player_name -> {stats dict}
player_fantasy_points = {}  # player_name -> {fantasy_points, fppg}

# Draft order configuration (team_name -> pick_number for 2026)
# If empty, draft order is calculated based on team value (worst team = pick 1)
draft_order_config = {}
draft_order_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'draft_order.json')


def load_draft_order_config():
    """Load draft order configuration from file."""
    global draft_order_config
    if os.path.exists(draft_order_file):
        try:
            with open(draft_order_file, 'r') as f:
                draft_order_config.update(json.load(f))
            print(f"Loaded draft order configuration for {len(draft_order_config)} teams")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load draft order config: {e}")


def save_draft_order_config():
    """Save draft order configuration to file."""
    try:
        with open(draft_order_file, 'w') as f:
            json.dump(draft_order_config, f, indent=2)
    except IOError as e:
        print(f"Warning: Could not save draft order config: {e}")


def get_team_rankings():
    """Calculate team rankings based on total dynasty value (lower value = worse team = earlier pick)."""
    team_values = []
    for name, team in teams.items():
        total_value = sum(calculator.calculate_player_value(p) for p in team.players)
        team_values.append((name, total_value))

    # Sort by value ascending (worst team first for draft order)
    team_values.sort(key=lambda x: x[1])

    # Use configured draft order if available, otherwise calculate based on value
    if draft_order_config:
        draft_order = dict(draft_order_config)
        # Fill in any missing teams with calculated values
        for i, (name, _) in enumerate(team_values):
            if name not in draft_order:
                draft_order[name] = i + 1
    else:
        # Create ranking dict: team_name -> pick_number (1 = worst team)
        draft_order = {name: i + 1 for i, (name, _) in enumerate(team_values)}

    # Also return sorted by value descending for display (best team first)
    team_values.sort(key=lambda x: x[1], reverse=True)
    power_rankings = {name: i + 1 for i, (name, _) in enumerate(team_values)}

    return draft_order, power_rankings, {name: val for name, val in team_values}

# ============================================================================
# HTML CONTENT (Embedded UI)
# ============================================================================

HTML_CONTENT = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Diamond Dynasties Trade Analyzer</title>
    <style>
        :root {
            --color-primary: #00d4ff;
            --color-accent: #ffd700;
            --color-success: #00ff88;
            --color-danger: #ff4d6d;
            --color-text-muted: #888;
            --space-sm: 8px;
            --space-md: 16px;
            --space-lg: 24px;
            --radius-md: 10px;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
            min-height: 100vh;
            color: #f0f0f0;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { text-align: center; padding: 35px 0; border-bottom: 2px solid rgba(0, 212, 255, 0.3); margin-bottom: 30px; }
        header h1 { font-size: 2.8rem; background: linear-gradient(90deg, #00d4ff, #7b2cbf, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; text-shadow: 0 0 30px rgba(0, 212, 255, 0.3); }
        header p { color: #a0a0a0; margin-top: 10px; font-size: 1.1rem; }
        .tabs { display: flex; gap: 12px; margin-bottom: 25px; flex-wrap: wrap; }
        .tab { padding: 14px 28px; background: linear-gradient(145deg, #1e1e3f, #2a2a5a); border: 1px solid rgba(0, 212, 255, 0.2); border-radius: 12px; color: #c0c0c0; cursor: pointer; font-size: 1rem; transition: all 0.3s ease; }
        .tab:hover { background: linear-gradient(145deg, #2a2a5a, #3a3a7a); border-color: rgba(0, 212, 255, 0.5); color: #fff; transform: translateY(-2px); }
        .tab.active { background: linear-gradient(135deg, #00d4ff, #0099cc); color: #0f0c29; font-weight: 700; border-color: #00d4ff; box-shadow: 0 4px 20px rgba(0, 212, 255, 0.4); }
        .panel { display: none; background: linear-gradient(145deg, #1a1a3e, #252560); border-radius: 16px; padding: 30px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); border: 1px solid rgba(123, 44, 191, 0.2); }
        .panel.active { display: block; }
        .form-group { margin-bottom: 22px; }
        label { display: block; margin-bottom: 10px; color: #00d4ff; font-weight: 600; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.5px; }
        select, input[type="text"] { width: 100%; padding: 14px; border: 2px solid rgba(123, 44, 191, 0.3); border-radius: 10px; background: rgba(15, 12, 41, 0.8); color: #f0f0f0; font-size: 1rem; transition: all 0.3s; }
        select:focus, input[type="text"]:focus { outline: none; border-color: #00d4ff; box-shadow: 0 0 15px rgba(0, 212, 255, 0.3); }
        .trade-sides { display: grid; grid-template-columns: 1fr auto 1fr; gap: 25px; align-items: start; }
        .trade-side { background: linear-gradient(145deg, #151535, #1e1e50); border-radius: 14px; padding: 25px; border: 1px solid rgba(0, 212, 255, 0.15); }
        .trade-side h3 { color: #00d4ff; margin-bottom: 18px; font-size: 1.2rem; text-transform: uppercase; letter-spacing: 1px; }
        .arrow { display: flex; align-items: center; justify-content: center; font-size: 2.5rem; color: #7b2cbf; padding-top: 60px; text-shadow: 0 0 20px rgba(123, 44, 191, 0.5); }
        .player-input { display: flex; gap: 12px; margin-bottom: 12px; }
        .player-input input { flex: 1; background: rgba(30, 30, 80, 0.6); border: 2px solid rgba(123, 44, 191, 0.4); }
        .player-input input:focus { border-color: #00d4ff; background: rgba(30, 30, 80, 0.9); }
        .player-input input::placeholder { color: #7070a0; }
        .pick-label { font-size: 0.9rem; color: #00d4ff; margin-bottom: 6px; font-weight: 500; }
        .player-list { margin-top: 12px; min-height: 45px; }
        .player-tag { display: inline-flex; align-items: center; gap: 10px; background: linear-gradient(135deg, #3a3a7a, #4a4a9a); padding: 10px 16px; border-radius: 25px; margin: 5px; font-size: 0.95rem; border: 1px solid rgba(0, 212, 255, 0.3); }
        .player-tag.pick { background: linear-gradient(135deg, #5a3a2a, #7a4a3a); border-color: rgba(255, 170, 100, 0.4); }
        .player-tag .remove { cursor: pointer; color: #ff6b6b; font-weight: bold; font-size: 1.1rem; }
        .player-tag .remove:hover { color: #ff4040; }
        .btn { padding: 16px 32px; border: none; border-radius: 12px; font-size: 1.05rem; cursor: pointer; transition: all 0.3s ease; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }
        .btn-primary { background: linear-gradient(135deg, #00d4ff, #0099cc); color: #0f0c29; box-shadow: 0 4px 20px rgba(0, 212, 255, 0.3); }
        .btn-primary:hover { background: linear-gradient(135deg, #00e5ff, #00aadd); transform: translateY(-3px); box-shadow: 0 6px 30px rgba(0, 212, 255, 0.5); }
        .btn-secondary { background: linear-gradient(145deg, #3a3a6a, #4a4a8a); color: #f0f0f0; border: 1px solid rgba(123, 44, 191, 0.3); }
        .btn-secondary:hover { background: linear-gradient(145deg, #4a4a8a, #5a5a9a); }
        .btn-add { padding: 14px 20px; background: linear-gradient(135deg, #7b2cbf, #5a1a9f); color: #fff; }
        .btn-add:hover { background: linear-gradient(135deg, #9b3cdf, #7b2cbf); }
        .results { margin-top: 35px; }
        .result-card { background: linear-gradient(145deg, #151535, #1e1e50); border-radius: 16px; padding: 25px; margin-bottom: 18px; border: 1px solid rgba(0, 212, 255, 0.2); }
        .verdict { font-size: 1.6rem; font-weight: bold; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; }
        .verdict.fair { color: #00ff88; text-shadow: 0 0 20px rgba(0, 255, 136, 0.4); }
        .verdict.unfair { color: #ff4d6d; text-shadow: 0 0 20px rgba(255, 77, 109, 0.4); }
        .verdict.questionable { color: #ffbe0b; text-shadow: 0 0 20px rgba(255, 190, 11, 0.4); }
        .value-comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 25px; margin: 20px 0; }
        .value-box { background: linear-gradient(145deg, #1a1a4a, #252570); padding: 20px; border-radius: 12px; border: 1px solid rgba(123, 44, 191, 0.3); }
        .value-box h4 { color: #a0a0c0; font-size: 0.95rem; margin-bottom: 8px; text-transform: uppercase; }
        .value-box .value { font-size: 2rem; font-weight: bold; background: linear-gradient(90deg, #00d4ff, #7b2cbf); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .reasoning { color: #b0b0c0; line-height: 1.7; font-size: 1rem; }
        .team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 18px; }
        .team-card { background: linear-gradient(145deg, #151535, #1e1e50); border-radius: 14px; padding: 22px; cursor: pointer; transition: all 0.3s ease; border: 1px solid rgba(0, 212, 255, 0.15); }
        .team-card:hover { transform: translateY(-5px); box-shadow: 0 12px 35px rgba(0, 212, 255, 0.2); border-color: rgba(0, 212, 255, 0.4); }
        .team-card h3 { color: #00d4ff; margin-bottom: 12px; font-size: 1.15rem; }
        .team-card .stats { color: #a0a0c0; font-size: 0.95rem; }
        .player-card { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; background: linear-gradient(145deg, #151535, #1e1e50); border-radius: 10px; margin-bottom: 10px; border: 1px solid rgba(123, 44, 191, 0.2); transition: all 0.2s; }
        .player-card:hover { border-color: rgba(0, 212, 255, 0.4); background: linear-gradient(145deg, #1a1a45, #252565); }
        .player-card .name { font-weight: 600; color: #f0f0f0; }
        .player-card .value { color: #00d4ff; font-weight: bold; font-size: 1.1rem; }
        .search-container { position: relative; }
        .search-results { position: absolute; top: 100%; left: 0; right: 0; background: linear-gradient(145deg, #1e1e4e, #2a2a6a); border-radius: 0 0 12px 12px; max-height: 320px; overflow-y: auto; z-index: 100; display: none; border: 1px solid rgba(0, 212, 255, 0.3); border-top: none; }
        .search-results.active { display: block; }
        .search-result { padding: 14px 16px; cursor: pointer; border-bottom: 1px solid rgba(123, 44, 191, 0.2); transition: all 0.2s; }
        .search-result:hover { background: rgba(0, 212, 255, 0.1); }
        .search-result .player-name { font-weight: 600; color: #f0f0f0; }
        .search-result .player-info { font-size: 0.88rem; color: #a0a0c0; margin-top: 4px; }
        .modal { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(15, 12, 41, 0.95); z-index: 1000; overflow-y: auto; }
        .modal.active { display: flex; justify-content: center; align-items: flex-start; padding: 50px 20px; }
        .modal-content { background: linear-gradient(145deg, #1a1a4a, #252570); border-radius: 20px; max-width: 650px; width: 100%; padding: 35px; position: relative; border: 1px solid rgba(0, 212, 255, 0.3); box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5); }
        #player-modal { z-index: 1100; }
        #player-modal .modal-content { max-width: 520px; }
        .modal-close { position: absolute; top: 18px; right: 22px; font-size: 1.8rem; cursor: pointer; color: #7070a0; transition: all 0.2s; }
        .modal-close:hover { color: #00d4ff; }
        .player-header { text-align: center; margin-bottom: 30px; }
        .player-header h2 { color: #00d4ff; font-size: 2rem; text-shadow: 0 0 20px rgba(0, 212, 255, 0.3); }
        .player-header .dynasty-value { font-size: 3rem; font-weight: bold; background: linear-gradient(90deg, #00d4ff, #7b2cbf); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .player-stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 18px; }
        .stat-box { background: linear-gradient(145deg, #151535, #1e1e50); padding: 18px; border-radius: 12px; text-align: center; border: 1px solid rgba(123, 44, 191, 0.2); }
        .stat-box .label { color: #8080a0; font-size: 0.85rem; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
        .stat-box .value { font-size: 1.4rem; font-weight: bold; color: #f0f0f0; }
        .stat-box .value.ascending { color: #00ff88; }
        .stat-box .value.descending { color: #ff4d6d; }
        .trade-advice { margin-top: 25px; padding: 20px; background: linear-gradient(145deg, #151535, #1e1e50); border-radius: 12px; border-left: 4px solid #7b2cbf; }
        .trade-advice h4 { color: #7b2cbf; margin-bottom: 10px; font-size: 1.1rem; }
        .loading { text-align: center; padding: 50px; color: #7070a0; font-size: 1.1rem; }
        .suggestion-card { background: linear-gradient(145deg, #151535, #1e1e50); border-radius: 16px; padding: 22px; margin-bottom: 18px; cursor: pointer; transition: all 0.3s ease; border: 1px solid rgba(123, 44, 191, 0.2); }
        .suggestion-card:hover { transform: translateY(-4px); box-shadow: 0 10px 30px rgba(0, 212, 255, 0.15); border-color: rgba(0, 212, 255, 0.4); }
        .suggestion-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
        .suggestion-verdict { font-weight: bold; padding: 6px 16px; border-radius: 25px; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.5px; }
        .suggestion-verdict.great { background: linear-gradient(135deg, #00ff88, #00cc6a); color: #0f0c29; }
        .suggestion-verdict.good { background: linear-gradient(135deg, #ffbe0b, #cc9900); color: #0f0c29; }
        .suggestion-sides { display: grid; grid-template-columns: 1fr 1fr; gap: 25px; }
        .suggestion-side h4 { color: #8080a0; font-size: 0.9rem; margin-bottom: 10px; text-transform: uppercase; }
        .suggestion-players { font-size: 1rem; color: #d0d0e0; }
        .suggestion-value { color: #00d4ff; font-weight: 600; margin-top: 8px; font-size: 1.05rem; }
        .player-link { cursor: pointer; color: #00d4ff; transition: all 0.2s; }
        .player-link:hover { color: #7b2cbf; text-decoration: underline; }
        @media (max-width: 768px) {
            .trade-sides { grid-template-columns: 1fr; }
            .arrow { transform: rotate(90deg); padding: 20px 0; }
            .value-comparison { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Diamond Dynasties Trade Analyzer</h1>
            <p>Dynasty Fantasy Baseball Trade Analysis Tool</p>
        </header>

        <div class="tabs">
            <button class="tab active" onclick="showPanel('analyze')">Analyze Trade</button>
            <button class="tab" onclick="showPanel('teams')">Teams</button>
            <button class="tab" onclick="showPanel('prospects')">Top Prospects</button>
            <button class="tab" onclick="showPanel('suggest')">Trade Suggestions</button>
            <button class="tab" onclick="showPanel('freeagents')">Free Agents</button>
            <button class="tab" onclick="showPanel('search')">Player Search</button>
            <button class="tab" onclick="showPanel('league')">League</button>
        </div>

        <div id="analyze-panel" class="panel active">
            <div class="trade-sides">
                <div class="trade-side">
                    <h3>Team A Sends</h3>
                    <div class="form-group">
                        <label>Select Team</label>
                        <select id="teamASelect" onchange="updateTeamA()"></select>
                    </div>
                    <div class="form-group" id="teamARosterGroup" style="display:none;">
                        <label>Add from Roster</label>
                        <select id="teamARoster" onchange="addPlayerFromRoster('A')">
                            <option value="">-- Select Player --</option>
                        </select>
                    </div>
                    <div class="search-container">
                        <input type="text" id="teamASearch" placeholder="Or search all players..." oninput="searchPlayers('A')" onfocus="showSearchResults('A')">
                        <div id="teamAResults" class="search-results"></div>
                    </div>
                    <div style="margin-top:15px">
                        <div class="pick-label">Add Draft Pick:</div>
                        <div class="player-input">
                            <input type="text" id="teamAPick" placeholder="e.g., 2026 1st Round Pick 3 (#3)" list="draftPicksList">
                            <button class="btn btn-add" onclick="addPick('A')">+ Pick</button>
                        </div>
                    </div>
                    <div id="teamAPlayers" class="player-list"></div>
                </div>

                <div class="arrow"></div>

                <div class="trade-side">
                    <h3>Team B Sends</h3>
                    <div class="form-group">
                        <label>Select Team</label>
                        <select id="teamBSelect" onchange="updateTeamB()"></select>
                    </div>
                    <div class="form-group" id="teamBRosterGroup" style="display:none;">
                        <label>Add from Roster</label>
                        <select id="teamBRoster" onchange="addPlayerFromRoster('B')">
                            <option value="">-- Select Player --</option>
                        </select>
                    </div>
                    <div class="search-container">
                        <input type="text" id="teamBSearch" placeholder="Or search all players..." oninput="searchPlayers('B')" onfocus="showSearchResults('B')">
                        <div id="teamBResults" class="search-results"></div>
                    </div>
                    <div style="margin-top:15px">
                        <div class="pick-label">Add Draft Pick:</div>
                        <div class="player-input">
                            <input type="text" id="teamBPick" placeholder="e.g., 2026 2nd Round Pick 8 (#20)" list="draftPicksList">
                            <button class="btn btn-add" onclick="addPick('B')">+ Pick</button>
                        </div>
                    </div>
                    <div id="teamBPlayers" class="player-list"></div>
                </div>
            </div>

            <div style="text-align: center; margin-top: 25px;">
                <button class="btn btn-primary" onclick="analyzeTrade()">Analyze Trade</button>
                <button class="btn btn-secondary" onclick="clearTrade()" style="margin-left: 10px;">Clear</button>
            </div>

            <div id="results" class="results"></div>
        </div>

        <div id="teams-panel" class="panel">
            <h3 style="margin-bottom: 15px;">All Teams</h3>
            <div id="teams-loading" class="loading">Loading teams...</div>
            <div id="teams-grid" class="team-grid"></div>
        </div>

        <div id="prospects-panel" class="panel">
            <h3 style="margin-bottom: 15px;">Top Prospects League-Wide</h3>
            <p style="color: #888; font-size: 0.85rem; margin-bottom: 15px;">Showing all ranked prospects (top 300) on team rosters and available as free agents. <span style="color: #00ff88;">FA</span> = Available to pick up!</p>
            <div id="prospects-loading" class="loading">Loading prospects...</div>
            <div id="prospects-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px;"></div>
        </div>

        <div id="suggest-panel" class="panel">
            <!-- Trade Finder Section -->
            <div style="background: linear-gradient(135deg, rgba(0,212,255,0.1), rgba(255,215,0,0.05)); border: 1px solid rgba(0,212,255,0.3); border-radius: 12px; padding: 20px; margin-bottom: 25px;">
                <h3 style="color: #00d4ff; margin: 0 0 15px 0; font-size: 1.1rem;">Trade Finder</h3>
                <p style="color: #888; font-size: 0.85rem; margin-bottom: 15px;">Select a player to find trade packages involving them.</p>
                <div style="display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 15px;">
                    <div class="form-group" style="flex: 1; min-width: 180px;">
                        <label>Team</label>
                        <select id="tradeFinderTeamSelect" onchange="loadTradeFinderPlayers()">
                            <option value="">Select Team</option>
                        </select>
                    </div>
                    <div class="form-group" style="flex: 1; min-width: 200px;">
                        <label>Player</label>
                        <select id="tradeFinderPlayerSelect" disabled>
                            <option value="">Select team first</option>
                        </select>
                    </div>
                    <div class="form-group" style="flex: 1; min-width: 150px;">
                        <label>Direction</label>
                        <select id="tradeFinderDirection">
                            <option value="send">Trade Away</option>
                            <option value="receive">Acquire</option>
                        </select>
                    </div>
                    <div class="form-group" style="flex: 1; min-width: 180px;">
                        <label>Target Team (optional)</label>
                        <select id="tradeFinderTargetTeam">
                            <option value="">All Teams</option>
                        </select>
                    </div>
                </div>
                <button onclick="findTradesForPlayer()" style="background: linear-gradient(135deg, #00d4ff, #0099cc); color: #000; border: none; padding: 10px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; transition: all 0.2s;">
                    Find Trade Packages
                </button>
                <div id="trade-finder-results" style="margin-top: 20px;"></div>
            </div>

            <!-- Divider -->
            <div style="height: 1px; background: linear-gradient(90deg, transparent, rgba(0,212,255,0.3), transparent); margin: 25px 0;"></div>

            <!-- AI Trade Suggestions Section -->
            <h3 style="color: #ffd700; margin: 0 0 15px 0; font-size: 1.1rem;">AI Trade Suggestions</h3>
            <div style="display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px;">
                <div class="form-group" style="flex: 1; min-width: 180px;">
                    <label>Your Team</label>
                    <select id="suggestTeamSelect" onchange="loadSuggestions()"></select>
                </div>
                <div class="form-group" style="flex: 1; min-width: 180px;">
                    <label>Target Team (optional)</label>
                    <select id="suggestTargetSelect" onchange="loadSuggestions()">
                        <option value="">All Teams</option>
                    </select>
                </div>
                <div class="form-group" style="flex: 1; min-width: 150px;">
                    <label>Trade Type</label>
                    <select id="tradeTypeSelect" onchange="loadSuggestions()">
                        <option value="any">Any</option>
                        <option value="1-for-1">1-for-1</option>
                        <option value="2-for-1">2-for-1</option>
                        <option value="2-for-2">2-for-2</option>
                    </select>
                </div>
            </div>
            <div id="suggestions-results"></div>
        </div>

        <div id="freeagents-panel" class="panel">
            <h3 style="margin-bottom: 15px;">Free Agent Recommendations</h3>
            <div style="display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px;">
                <div class="form-group" style="flex: 1; min-width: 180px;">
                    <label>Your Team</label>
                    <select id="faTeamSelect" onchange="loadFASuggestions()">
                        <option value="">Select Team</option>
                    </select>
                </div>
                <div class="form-group" style="flex: 1; min-width: 150px;">
                    <label>Position Filter</label>
                    <select id="faPosFilter" onchange="loadFASuggestions()">
                        <option value="">All Positions</option>
                        <option value="C">C</option>
                        <option value="1B">1B</option>
                        <option value="2B">2B</option>
                        <option value="SS">SS</option>
                        <option value="3B">3B</option>
                        <option value="OF">OF</option>
                        <option value="SP">SP</option>
                        <option value="RP">RP</option>
                    </select>
                </div>
            </div>
            <p style="color: #888; font-size: 0.85rem; margin-bottom: 15px;">AI-powered recommendations. Select your team for personalized suggestions based on your needs.</p>
            <div id="fa-results">
                <div class="loading">Loading top free agents...</div>
            </div>
        </div>

        <div id="search-panel" class="panel">
            <div class="form-group">
                <label>Search for any player</label>
                <input type="text" id="playerSearchInput" placeholder="Type player name..." oninput="searchPlayers()" style="max-width: 400px;">
            </div>
            <div id="search-results" style="margin-top: 20px;"></div>
        </div>

        <div id="league-panel" class="panel">
            <div class="tabs" style="margin-bottom: 20px;">
                <button class="tab active" onclick="showLeagueTab('standings')">Standings</button>
                <button class="tab" onclick="showLeagueTab('matchups')">Matchups</button>
                <button class="tab" onclick="showLeagueTab('transactions')">Transactions</button>
            </div>
            <div id="league-standings" class="league-tab active"></div>
            <div id="league-matchups" class="league-tab" style="display:none;"></div>
            <div id="league-transactions" class="league-tab" style="display:none;"></div>
        </div>
    </div>

    <div id="player-modal" class="modal" onclick="closeModal(event)">
        <div class="modal-content" onclick="event.stopPropagation()">
            <span class="modal-close" onclick="closePlayerModal()">&times;</span>
            <div id="player-modal-content"></div>
        </div>
    </div>

    <div id="team-modal" class="modal" onclick="closeModal(event)">
        <div class="modal-content" onclick="event.stopPropagation()" style="max-width: 800px;">
            <span class="modal-close" onclick="closeTeamModal()">&times;</span>
            <div id="team-modal-content"></div>
        </div>
    </div>

    <script>
        const API_BASE = '';
        let teamsData = [];
        let tradePlayersA = [];
        let tradePlayersB = [];
        let tradePicksA = [];
        let tradePicksB = [];
        let currentSuggestOffset = 0;
        let currentTeamDepth = {};  // Store current team's positional depth for modal
        let currentSuggestLimit = 8;
        let allCurrentSuggestions = [];

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.search-container')) {
                document.querySelectorAll('.search-results').forEach(el => el.classList.remove('active'));
            }
        });

        async function loadTeams() {
            try {
                const res = await fetch(`${API_BASE}/teams`);
                const data = await res.json();
                teamsData = data.teams || [];
                populateTeamSelects();
                renderTeamsGrid();
            } catch (e) {
                console.error('Failed to load teams:', e);
            }
        }

        async function loadProspects() {
            const grid = document.getElementById('prospects-grid');
            const loading = document.getElementById('prospects-loading');

            try {
                const res = await fetch(`${API_BASE}/prospects`);
                const data = await res.json();
                loading.style.display = 'none';

                if (data.prospects && data.prospects.length > 0) {
                    grid.innerHTML = data.prospects.map(p => {
                        const tierColor = p.rank <= 10 ? '#ffd700' : p.rank <= 25 ? '#00d4ff' : p.rank <= 50 ? '#7b2cbf' : '#4a90d9';
                        const tierBg = p.rank <= 10 ? 'linear-gradient(145deg, #3d3d00, #4a4a00)' : p.rank <= 25 ? 'linear-gradient(145deg, #002a33, #003d4d)' : p.rank <= 50 ? 'linear-gradient(145deg, #2a1a3d, #3d2a50)' : 'linear-gradient(145deg, #151535, #1e1e50)';
                        const isFreeAgent = p.is_free_agent || p.fantasy_team === 'Free Agent';
                        const isNotInLeague = p.not_in_league || p.fantasy_team === 'Not in League';
                        let statusBadge = '';
                        let ownerText = '';
                        let ownerStyle = 'color: #c0c0e0;';
                        if (isNotInLeague) {
                            statusBadge = '<span style="background: #666; color: #fff; font-size: 0.65rem; padding: 2px 6px; border-radius: 8px; margin-left: 8px; font-weight: bold;">N/A</span>';
                            ownerText = '<span style="color: #888;">Not Available in League</span>';
                        } else if (isFreeAgent) {
                            statusBadge = '<span style="background: #00ff88; color: #000; font-size: 0.65rem; padding: 2px 6px; border-radius: 8px; margin-left: 8px; font-weight: bold;">FA</span>';
                            ownerStyle = 'color: #00ff88; font-weight: bold;';
                            ownerText = '<span style="' + ownerStyle + '">AVAILABLE - Free Agent</span>';
                        } else {
                            ownerText = 'Owner: <span style="' + ownerStyle + '">' + p.fantasy_team + '</span>';
                        }
                        const clickHandler = isNotInLeague ? '' : `onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')"`;
                        const cursorStyle = isNotInLeague ? 'cursor: default;' : 'cursor: pointer;';
                        const opacityStyle = isNotInLeague ? 'opacity: 0.7;' : '';
                        return `
                        <div ${clickHandler} style="background: ${tierBg}; border-radius: 12px; padding: 18px; border-left: 4px solid ${tierColor}; ${cursorStyle} transition: all 0.3s ease; border: 1px solid rgba(${p.rank <= 10 ? '255,215,0' : p.rank <= 25 ? '0,212,255' : p.rank <= 50 ? '123,44,191' : '74,144,217'}, 0.3); ${opacityStyle}" ${isNotInLeague ? '' : 'onmouseover="this.style.transform=\\'translateY(-3px)\\';this.style.boxShadow=\\'0 8px 25px rgba(0,0,0,0.3)\\';" onmouseout="this.style.transform=\\'translateY(0)\\';this.style.boxShadow=\\'none\\';"'}>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                                <span style="font-weight: bold; font-size: 1.05rem; color: ${tierColor};">#${p.rank} ${p.name}${statusBadge}</span>
                                <span style="color: #00d4ff; font-weight: bold; font-size: 1.1rem;">${p.value.toFixed(1)}</span>
                            </div>
                            <div style="font-size: 0.9rem; color: #a0a0c0;">
                                ${p.position} | ${p.age ? 'Age ' + p.age : 'Age N/A'} | ${p.mlb_team}
                            </div>
                            <div style="font-size: 0.85rem; color: #7070a0; margin-top: 8px;">
                                ${ownerText}
                            </div>
                        </div>
                    `}).join('');
                } else {
                    grid.innerHTML = '<div style="color: #7070a0; text-align: center; grid-column: 1/-1;">No prospects found.</div>';
                }
            } catch (e) {
                console.error('Failed to load prospects:', e);
                loading.style.display = 'none';
                grid.innerHTML = '<div style="color: #ff4d6d; text-align: center; grid-column: 1/-1;">Failed to load prospects.</div>';
            }
        }

        function populateTeamSelects() {
            const selects = ['teamASelect', 'teamBSelect', 'suggestTeamSelect', 'suggestTargetSelect', 'faTeamSelect', 'tradeFinderTeamSelect', 'tradeFinderTargetTeam'];
            selects.forEach(id => {
                const select = document.getElementById(id);
                if (!select) return;
                const currentValue = select.value;
                const isTarget = id === 'suggestTargetSelect' || id === 'tradeFinderTargetTeam';
                select.innerHTML = isTarget ? '<option value="">All Teams</option>' : '<option value="">Select team...</option>';
                teamsData.forEach(team => {
                    const opt = document.createElement('option');
                    opt.value = team.name;
                    opt.textContent = `${team.name} (#${team.power_rank} - ${team.total_value.toFixed(1)} pts)`;
                    select.appendChild(opt);
                });
                if (currentValue && [...select.options].some(o => o.value === currentValue)) {
                    select.value = currentValue;
                }
            });
        }

        function renderTeamsGrid() {
            const grid = document.getElementById('teams-grid');
            const loading = document.getElementById('teams-loading');
            loading.style.display = 'none';

            grid.innerHTML = teamsData.map(team => `
                <div class="team-card" onclick="showTeamDetails('${team.name.replace(/'/g, "\\'")}')">
                    <h3>#${team.power_rank} ${team.name}</h3>
                    <div class="stats">
                        <div style="color:#ffd700;font-size:1.2rem;font-weight:bold">${team.total_value.toFixed(1)} pts</div>
                        <div>${team.player_count} players</div>
                        <div style="color:#888;font-size:0.8rem">2026 Pick: #${team.draft_pick}</div>
                    </div>
                </div>
            `).join('');
        }

        function showPanel(panel) {
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tabs .tab').forEach(t => t.classList.remove('active'));
            document.getElementById(`${panel}-panel`).classList.add('active');
            event.target.classList.add('active');

            if (panel === 'league') loadLeagueData();
            if (panel === 'freeagents') loadFASuggestions();
        }

        async function loadLeagueData() {
            await Promise.all([loadStandings(), loadMatchups(), loadTransactions()]);
        }

        function showLeagueTab(tab) {
            document.querySelectorAll('.league-tab').forEach(t => t.style.display = 'none');
            document.querySelectorAll('#league-panel .tabs .tab').forEach(t => t.classList.remove('active'));
            document.getElementById(`league-${tab}`).style.display = 'block';
            event.target.classList.add('active');
        }

        async function loadStandings() {
            const container = document.getElementById('league-standings');
            try {
                const res = await fetch(`${API_BASE}/standings`);
                const data = await res.json();
                if (data.standings && data.standings.length > 0) {
                    container.innerHTML = `<table style="width:100%;border-collapse:collapse;">
                        <tr style="border-bottom:1px solid #444;"><th style="text-align:left;padding:10px;">Rank</th><th style="text-align:left;padding:10px;">Team</th><th style="padding:10px;">W</th><th style="padding:10px;">L</th><th style="padding:10px;">PF</th></tr>
                        ${data.standings.map(s => `<tr style="border-bottom:1px solid #333;"><td style="padding:10px;">${s.rank}</td><td style="padding:10px;">${s.team}</td><td style="text-align:center;padding:10px;">${s.wins}</td><td style="text-align:center;padding:10px;">${s.losses}</td><td style="text-align:center;padding:10px;">${s.points_for || '-'}</td></tr>`).join('')}
                    </table>`;
                } else {
                    container.innerHTML = '<div style="color:#888;text-align:center;">No standings data available.</div>';
                }
            } catch (e) {
                container.innerHTML = '<div style="color:#888;text-align:center;">Failed to load standings.</div>';
            }
        }

        async function loadMatchups() {
            const container = document.getElementById('league-matchups');
            try {
                const res = await fetch(`${API_BASE}/matchups`);
                const data = await res.json();
                if (data.matchups && data.matchups.length > 0) {
                    container.innerHTML = data.matchups.map(period => `
                        <div style="margin-bottom:20px;"><h4 style="color:#ffd700;margin-bottom:10px;">${period.period}</h4>
                        ${period.matchups.map(m => `<div style="padding:10px;background:#1a1a2e;border-radius:8px;margin-bottom:8px;">${m.away} (${m.away_score}) vs ${m.home} (${m.home_score})</div>`).join('')}
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div style="color:#888;text-align:center;">No matchup data available.</div>';
                }
            } catch (e) {
                container.innerHTML = '<div style="color:#888;text-align:center;">Failed to load matchups.</div>';
            }
        }

        async function loadTransactions() {
            const container = document.getElementById('league-transactions');
            try {
                const res = await fetch(`${API_BASE}/transactions`);
                const data = await res.json();
                if (data.transactions && data.transactions.length > 0) {
                    container.innerHTML = data.transactions.map(tx => `
                        <div style="padding:15px;background:#1a1a2e;border-radius:8px;margin-bottom:10px;">
                            <div style="color:#ffd700;font-weight:500;">${tx.team}</div>
                            <div style="color:#888;font-size:0.85rem;">${tx.date}</div>
                            <div style="margin-top:8px;">${tx.players.map(p => `<span style="margin-right:10px;">${p.type}: ${p.name}</span>`).join('')}</div>
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div style="color:#888;text-align:center;">No recent transactions.</div>';
                }
            } catch (e) {
                container.innerHTML = '<div style="color:#888;text-align:center;">Failed to load transactions.</div>';
            }
        }

        async function searchPlayers(side) {
            const input = document.getElementById(`team${side}Search`);
            const results = document.getElementById(`team${side}Results`);
            const query = input.value.trim();

            if (query.length < 2) {
                results.classList.remove('active');
                return;
            }

            try {
                const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}&limit=10`);
                const data = await res.json();

                if (data.results && data.results.length > 0) {
                    results.innerHTML = data.results.map(p => `
                        <div class="search-result" onclick="addPlayer('${side}', '${p.name.replace(/'/g, "\\'")}', '${p.fantasy_team.replace(/'/g, "\\'")}')">
                            <div class="player-name">${p.name}</div>
                            <div class="player-info">${p.position} | ${p.team} | ${p.fantasy_team} | Value: ${p.value.toFixed(1)}</div>
                        </div>
                    `).join('');
                    results.classList.add('active');
                } else {
                    results.innerHTML = '<div class="search-result">No players found</div>';
                    results.classList.add('active');
                }
            } catch (e) {
                console.error('Search failed:', e);
            }
        }

        function showSearchResults(side) {
            const results = document.getElementById(`team${side}Results`);
            if (results.innerHTML) results.classList.add('active');
        }

        function addPlayer(side, name, team) {
            const players = side === 'A' ? tradePlayersA : tradePlayersB;
            const select = document.getElementById(`team${side}Select`);

            if (!players.find(p => p.name === name)) {
                players.push({ name, team });
                if (!select.value) select.value = team;
            }

            document.getElementById(`team${side}Search`).value = '';
            document.getElementById(`team${side}Results`).classList.remove('active');
            renderTradePlayers(side);
        }

        function addPick(side) {
            const input = document.getElementById(`team${side}Pick`);
            const picks = side === 'A' ? tradePicksA : tradePicksB;
            const pick = input.value.trim();

            if (pick && !picks.includes(pick)) {
                picks.push(pick);
            }

            input.value = '';
            renderTradePlayers(side);
        }

        function removePlayer(side, name) {
            if (side === 'A') {
                tradePlayersA = tradePlayersA.filter(p => p.name !== name);
            } else {
                tradePlayersB = tradePlayersB.filter(p => p.name !== name);
            }
            renderTradePlayers(side);
        }

        function removePick(side, pick) {
            if (side === 'A') {
                tradePicksA = tradePicksA.filter(p => p !== pick);
            } else {
                tradePicksB = tradePicksB.filter(p => p !== pick);
            }
            renderTradePlayers(side);
        }

        function renderTradePlayers(side) {
            const container = document.getElementById(`team${side}Players`);
            const players = side === 'A' ? tradePlayersA : tradePlayersB;
            const picks = side === 'A' ? tradePicksA : tradePicksB;

            container.innerHTML =
                players.map(p => `<span class="player-tag">${p.name} <span class="remove" onclick="removePlayer('${side}', '${p.name.replace(/'/g, "\\'")}')">&times;</span></span>`).join('') +
                picks.map(p => `<span class="player-tag pick">${p} <span class="remove" onclick="removePick('${side}', '${p.replace(/'/g, "\\'")}')">&times;</span></span>`).join('');
        }

        function clearTrade() {
            tradePlayersA = [];
            tradePlayersB = [];
            tradePicksA = [];
            tradePicksB = [];
            renderTradePlayers('A');
            renderTradePlayers('B');
            document.getElementById('results').innerHTML = '';
        }

        async function analyzeTrade() {
            const teamA = document.getElementById('teamASelect').value;
            const teamB = document.getElementById('teamBSelect').value;

            if (!teamA || !teamB) {
                alert('Please select both teams');
                return;
            }

            if (tradePlayersA.length === 0 && tradePicksA.length === 0) {
                alert('Please add players or picks for Team A to send');
                return;
            }

            if (tradePlayersB.length === 0 && tradePicksB.length === 0) {
                alert('Please add players or picks for Team B to send');
                return;
            }

            const results = document.getElementById('results');
            results.innerHTML = '<div class="loading">Analyzing trade...</div>';

            try {
                const res = await fetch(`${API_BASE}/analyze`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        team_a: teamA,
                        team_b: teamB,
                        players_a: tradePlayersA.map(p => p.name),
                        players_b: tradePlayersB.map(p => p.name),
                        picks_a: tradePicksA,
                        picks_b: tradePicksB
                    })
                });

                const data = await res.json();

                if (data.error) {
                    results.innerHTML = `<div class="result-card"><p style="color: #f87171;">${data.error}</p></div>`;
                    return;
                }

                const verdictClass = data.verdict.toLowerCase().includes('fair') ? 'fair' : data.verdict.toLowerCase().includes('unfair') ? 'unfair' : 'questionable';

                // Build stat comparison table
                const stats = data.stat_comparison || {};
                const statRows = [
                    { label: 'HR', key: 'HR', type: 'hit' },
                    { label: 'RBI', key: 'RBI', type: 'hit' },
                    { label: 'R', key: 'R', type: 'hit' },
                    { label: 'SB', key: 'SB', type: 'hit' },
                    { label: 'AVG', key: 'AVG', type: 'hit', format: v => v ? v.toFixed(3) : '.000' },
                    { label: 'OPS', key: 'OPS', type: 'hit', format: v => v ? v.toFixed(3) : '.000' },
                    { label: 'K', key: 'K', type: 'pitch' },
                    { label: 'QS', key: 'QS', type: 'pitch' },
                    { label: 'SV+HLD', key: null, type: 'pitch', getValue: s => (s.SV || 0) + (s.HLD || 0) },
                    { label: 'ERA', key: 'ERA', type: 'pitch', format: v => v ? v.toFixed(2) : '0.00', inverse: true },
                    { label: 'WHIP', key: 'WHIP', type: 'pitch', format: v => v ? v.toFixed(2) : '0.00', inverse: true },
                ];

                let statTableHtml = '';
                if (stats.team_a_sends && stats.team_b_sends) {
                    statTableHtml = `
                        <div style="margin: 20px 0;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                                <h4 style="color: #00d4ff; margin: 0;">Stat Comparison</h4>
                                <button onclick="document.getElementById('stat-details').style.display = document.getElementById('stat-details').style.display === 'none' ? 'block' : 'none'" style="background: linear-gradient(135deg, #3a3a7a, #4a4a9a); border: none; color: #fff; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 0.85rem;">Toggle Details</button>
                            </div>
                            <div id="stat-details" style="display: none; background: linear-gradient(145deg, #151535, #1e1e50); border-radius: 12px; padding: 15px; border: 1px solid rgba(0, 212, 255, 0.2);">
                                <table style="width: 100%; border-collapse: collapse; font-size: 0.9rem;">
                                    <thead>
                                        <tr style="border-bottom: 2px solid rgba(0, 212, 255, 0.3);">
                                            <th style="text-align: left; padding: 10px; color: #7070a0;">Stat</th>
                                            <th style="text-align: center; padding: 10px; color: #7b2cbf;">${teamA} Sends</th>
                                            <th style="text-align: center; padding: 10px; color: #7b2cbf;">${teamB} Sends</th>
                                            <th style="text-align: center; padding: 10px; color: #00d4ff;">Net for ${teamA}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${statRows.map(row => {
                                            const aVal = row.getValue ? row.getValue(stats.team_a_sends) : stats.team_a_sends[row.key] || 0;
                                            const bVal = row.getValue ? row.getValue(stats.team_b_sends) : stats.team_b_sends[row.key] || 0;
                                            const net = row.getValue ? row.getValue(stats.net_for_team_a) : stats.net_for_team_a[row.key] || 0;
                                            const format = row.format || (v => Math.round(v));
                                            const isPositive = row.inverse ? net < 0 : net > 0;
                                            const isNegative = row.inverse ? net > 0 : net < 0;
                                            const netColor = isPositive ? '#00ff88' : isNegative ? '#ff4d6d' : '#a0a0c0';
                                            const netSign = net > 0 ? '+' : '';
                                            return `
                                                <tr style="border-bottom: 1px solid rgba(123, 44, 191, 0.15);">
                                                    <td style="padding: 8px 10px; color: #c0c0e0;">${row.label}</td>
                                                    <td style="text-align: center; padding: 8px; color: #a0a0c0;">${format(aVal)}</td>
                                                    <td style="text-align: center; padding: 8px; color: #a0a0c0;">${format(bVal)}</td>
                                                    <td style="text-align: center; padding: 8px; color: ${netColor}; font-weight: 600;">${netSign}${format(net)}</td>
                                                </tr>
                                            `;
                                        }).join('')}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    `;
                }

                results.innerHTML = `
                    <div class="result-card">
                        <div class="verdict ${verdictClass}">${data.verdict}</div>
                        <div class="value-comparison">
                            <div class="value-box">
                                <h4>${teamA} Receives</h4>
                                <div class="value">${data.value_a_receives.toFixed(1)}</div>
                                ${data.age_analysis?.team_b_sends_avg_age ? `<div style="color:#a0a0c0;font-size:0.85rem;margin-top:8px;">Avg Age: ${data.age_analysis.team_b_sends_avg_age}</div>` : ''}
                            </div>
                            <div class="value-box">
                                <h4>${teamB} Receives</h4>
                                <div class="value">${data.value_b_receives.toFixed(1)}</div>
                                ${data.age_analysis?.team_a_sends_avg_age ? `<div style="color:#a0a0c0;font-size:0.85rem;margin-top:8px;">Avg Age: ${data.age_analysis.team_a_sends_avg_age}</div>` : ''}
                            </div>
                        </div>
                        <div style="padding: 18px; background: linear-gradient(145deg, #151535, #1e1e50); border-radius: 12px; margin: 18px 0; border-left: 4px solid #7b2cbf;">
                            <div style="white-space: pre-line; line-height: 1.7; color: #d0d0e0;">${data.detailed_analysis || data.reasoning}</div>
                        </div>
                        ${data.category_impact && data.category_impact.length > 0 ? `
                            <div style="display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0;">
                                ${data.category_impact.map(c => `<span style="background: linear-gradient(135deg, #2a2a5a, #3a3a7a); padding: 8px 16px; border-radius: 20px; font-size: 0.9rem; border: 1px solid rgba(0, 212, 255, 0.2);">${c}</span>`).join('')}
                            </div>
                        ` : ''}
                        ${statTableHtml}
                        <div style="padding: 14px 24px; background: ${data.recommendation?.includes('[OK]') ? 'linear-gradient(135deg, #0a2a15, #153d20)' : data.recommendation?.includes('[!]') ? 'linear-gradient(135deg, #2a2510, #3d3515)' : 'linear-gradient(135deg, #2a1015, #3d1520)'}; border-radius: 12px; font-weight: 600; text-align: center; font-size: 1.05rem; border: 1px solid ${data.recommendation?.includes('[OK]') ? 'rgba(0, 255, 136, 0.3)' : data.recommendation?.includes('[!]') ? 'rgba(255, 190, 11, 0.3)' : 'rgba(255, 77, 109, 0.3)'};">
                            ${data.recommendation || ''}
                        </div>
                    </div>
                `;
            } catch (e) {
                results.innerHTML = `<div class="result-card"><p style="color: #f87171;">Failed to analyze trade: ${e.message}</p></div>`;
            }
        }

        function getRankColor(rank, total) {
            const pct = rank / total;
            if (pct <= 0.33) return '#4ade80';  // Top third - green
            if (pct <= 0.66) return '#ffd700';  // Middle third - gold
            return '#f87171';  // Bottom third - red
        }

        function renderCategoryBar(cat, value, rank, total, isReverse = false) {
            const rankPct = ((total - rank + 1) / total) * 100;
            const color = getRankColor(rank, total);
            const displayVal = typeof value === 'number' && value < 10 ? value.toFixed(3).replace('0.', '.') : Math.round(value);
            return `
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                        <span style="color: #e4e4e4; font-weight: 500;">${cat}</span>
                        <span style="color: ${color}; font-weight: bold;">${displayVal} <span style="color: #888; font-weight: normal;">(#${rank})</span></span>
                    </div>
                    <div style="background: #2a2a3e; height: 8px; border-radius: 4px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, ${color}, ${color}88); width: ${rankPct}%; height: 100%; border-radius: 4px;"></div>
                    </div>
                </div>
            `;
        }

        async function showTeamDetails(teamName) {
            const modal = document.getElementById('team-modal');
            const content = document.getElementById('team-modal-content');
            content.innerHTML = '<div class="loading">Loading team details...</div>';
            modal.classList.add('active');

            try {
                const res = await fetch(`${API_BASE}/team/${encodeURIComponent(teamName)}`);
                const data = await res.json();
                const numTeams = data.num_teams || 12;
                const cats = data.category_details || {};
                const comp = data.roster_composition || {};
                const posDepth = data.positional_depth || {};
                currentTeamDepth = posDepth;  // Store for position modal

                content.innerHTML = `
                    <h2 style="color: #ffd700; margin-bottom: 5px;">#${data.power_rank} ${data.name}</h2>
                    <div style="font-size: 0.9rem; color: #888; margin-bottom: 15px;">2026 Draft Pick: #${data.draft_pick}</div>

                    <!-- Quick Stats -->
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 12px; margin-bottom: 25px;">
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #3a3a5a;">
                            <div style="color: #888; font-size: 0.75rem;">Total Value</div>
                            <div style="color: #ffd700; font-size: 1.3rem; font-weight: bold;">${data.total_value.toFixed(1)}</div>
                        </div>
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #3a3a5a;">
                            <div style="color: #888; font-size: 0.75rem;">Avg Age</div>
                            <div style="color: #e4e4e4; font-size: 1.3rem; font-weight: bold;">${comp.avg_age || 'N/A'}</div>
                        </div>
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #3a3a5a;">
                            <div style="color: #888; font-size: 0.75rem;">Roster</div>
                            <div style="color: #e4e4e4; font-size: 1.3rem; font-weight: bold;">${data.player_count}</div>
                        </div>
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #3a3a5a;">
                            <div style="color: #888; font-size: 0.75rem;">Prospects</div>
                            <div style="color: #4ade80; font-size: 1.3rem; font-weight: bold;">${(data.prospects || []).length}</div>
                        </div>
                    </div>

                    <!-- Roster Composition -->
                    <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #3a3a5a;">
                        <h4 style="color: #00d4ff; margin: 0 0 12px 0; font-size: 0.9rem;">ROSTER COMPOSITION</h4>
                        <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                            <div><span style="color: #888;">Hitters:</span> <span style="color: #e4e4e4; font-weight: bold;">${comp.hitters || 0}</span></div>
                            <div><span style="color: #888;">SP:</span> <span style="color: #e4e4e4; font-weight: bold;">${comp.starters || 0}</span></div>
                            <div><span style="color: #888;">RP:</span> <span style="color: #e4e4e4; font-weight: bold;">${comp.relievers || 0}</span></div>
                            <div style="margin-left: auto;">
                                <span style="color: #4ade80;">${comp.young || 0} young</span> |
                                <span style="color: #ffd700;">${comp.prime || 0} prime</span> |
                                <span style="color: #f87171;">${comp.veteran || 0} vet</span>
                            </div>
                        </div>
                    </div>

                    <!-- Category Rankings -->
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 25px;">
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 10px; border: 1px solid #3a3a5a;">
                            <h4 style="color: #00d4ff; margin: 0 0 15px 0; font-size: 0.9rem;">HITTING CATEGORIES</h4>
                            ${cats.HR ? renderCategoryBar('HR', cats.HR.value, cats.HR.rank, numTeams) : ''}
                            ${cats.RBI ? renderCategoryBar('RBI', cats.RBI.value, cats.RBI.rank, numTeams) : ''}
                            ${cats.R ? renderCategoryBar('R', cats.R.value, cats.R.rank, numTeams) : ''}
                            ${cats.SB ? renderCategoryBar('SB', cats.SB.value, cats.SB.rank, numTeams) : ''}
                            ${cats.AVG ? renderCategoryBar('AVG', cats.AVG.value, cats.AVG.rank, numTeams) : ''}
                            ${cats.OPS ? renderCategoryBar('OPS', cats.OPS.value, cats.OPS.rank, numTeams) : ''}
                            ${cats.SO ? renderCategoryBar('SO', cats.SO.value, cats.SO.rank, numTeams, true) : ''}
                        </div>
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 10px; border: 1px solid #3a3a5a;">
                            <h4 style="color: #00d4ff; margin: 0 0 15px 0; font-size: 0.9rem;">PITCHING CATEGORIES</h4>
                            ${cats.K ? renderCategoryBar('K', cats.K.value, cats.K.rank, numTeams) : ''}
                            ${cats.QS ? renderCategoryBar('QS', cats.QS.value, cats.QS.rank, numTeams) : ''}
                            ${cats.ERA ? renderCategoryBar('ERA', cats.ERA.value, cats.ERA.rank, numTeams, true) : ''}
                            ${cats.WHIP ? renderCategoryBar('WHIP', cats.WHIP.value, cats.WHIP.rank, numTeams, true) : ''}
                            ${cats['K/BB'] ? renderCategoryBar('K/BB', cats['K/BB'].value, cats['K/BB'].rank, numTeams) : ''}
                            ${cats.L ? renderCategoryBar('L', cats.L.value, cats.L.rank, numTeams, true) : ''}
                            ${cats['SV+HLD'] ? renderCategoryBar('SV+HLD', cats['SV+HLD'].value, cats['SV+HLD'].rank, numTeams) : ''}
                        </div>
                    </div>

                    <!-- Strengths & Weaknesses Summary -->
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 25px;">
                        <div style="background: rgba(74, 222, 128, 0.1); padding: 12px; border-radius: 8px; border: 1px solid rgba(74, 222, 128, 0.3);">
                            <div style="color: #4ade80; font-size: 0.85rem; font-weight: bold; margin-bottom: 5px;">STRENGTHS</div>
                            <div style="color: #e4e4e4;">${[...(data.hitting_strengths || []), ...(data.pitching_strengths || [])].join(', ') || 'None'}</div>
                        </div>
                        <div style="background: rgba(248, 113, 113, 0.1); padding: 12px; border-radius: 8px; border: 1px solid rgba(248, 113, 113, 0.3);">
                            <div style="color: #f87171; font-size: 0.85rem; font-weight: bold; margin-bottom: 5px;">WEAKNESSES</div>
                            <div style="color: #e4e4e4;">${[...(data.hitting_weaknesses || []), ...(data.pitching_weaknesses || [])].join(', ') || 'None'}</div>
                        </div>
                    </div>

                    <!-- Analysis -->
                    ${data.analysis ? `<div style="margin-bottom: 25px; padding: 15px; background: linear-gradient(135deg, #1a1a2e, #16213e); border-radius: 10px; line-height: 1.7; border: 1px solid #3a3a5a;">${data.analysis}</div>` : ''}

                    <!-- Positional Depth -->
                    <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 10px; margin-bottom: 25px; border: 1px solid #3a3a5a;">
                        <h4 style="color: #00d4ff; margin: 0 0 15px 0; font-size: 0.9rem;">POSITIONAL DEPTH <span style="color: #888; font-size: 0.75rem;">(click to view all)</span></h4>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px;">
                            ${['C', '1B', '2B', 'SS', '3B', 'OF', 'SP', 'RP'].map(pos => {
                                const players = posDepth[pos] || [];
                                const depthColor = players.length >= 3 ? '#4ade80' : (players.length >= 2 ? '#ffd700' : '#f87171');
                                return `
                                    <div onclick="showPositionDepth('${pos}')" style="background: #2a2a3e; padding: 10px; border-radius: 6px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;" onmouseover="this.style.transform='scale(1.02)';this.style.boxShadow='0 4px 12px rgba(0,212,255,0.2)'" onmouseout="this.style.transform='scale(1)';this.style.boxShadow='none'">
                                        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                                            <span style="color: #00d4ff; font-weight: bold;">${pos}</span>
                                            <span style="color: ${depthColor}; font-size: 0.8rem;">${players.length} deep</span>
                                        </div>
                                        ${players.slice(0, 3).map((p, i) => `
                                            <div style="font-size: 0.75rem; color: ${i === 0 ? '#e4e4e4' : '#888'}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                                                ${p.name} (${p.value})
                                            </div>
                                        `).join('')}
                                        ${players.length === 0 ? '<div style="font-size: 0.75rem; color: #666;">No depth</div>' : ''}
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>

                    <!-- Full Roster by Position -->
                    <h4 style="color: #ffd700; margin-bottom: 15px;">Full Roster (${data.players.length} players)</h4>
                    <div id="roster-depth-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; margin-bottom: 25px;">
                    </div>

                    ${(data.prospects && data.prospects.length > 0) ? '<h4 style="color: #ffd700; margin: 25px 0 15px;">Ranked Prospects (' + data.prospects.length + ')</h4><div id="prospects-grid-modal" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px;"></div>' : ''}
                `;

                // Populate roster depth grid
                const depthGrid = document.getElementById('roster-depth-grid');
                if (depthGrid) {
                    ['C', '1B', '2B', 'SS', '3B', 'OF', 'SP', 'RP'].forEach(pos => {
                        const players = posDepth[pos] || [];
                        const posColor = ['SP', 'RP'].includes(pos) ? '#00d4ff' : '#ffd700';
                        const depthColor = players.length >= 3 ? '#4ade80' : (players.length >= 2 ? '#ffd700' : '#f87171');

                        const posDiv = document.createElement('div');
                        posDiv.style.cssText = 'background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 10px; border: 1px solid #3a3a5a;';

                        let html = '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid #3a3a5a; padding-bottom: 8px;">';
                        html += '<span style="color: ' + posColor + '; font-weight: bold; font-size: 1.1rem;">' + pos + '</span>';
                        html += '<span style="color: ' + depthColor + '; font-size: 0.85rem;">' + players.length + ' player' + (players.length !== 1 ? 's' : '') + '</span>';
                        html += '</div>';

                        if (players.length > 0) {
                            players.forEach((p, i) => {
                                const bgColor = i === 0 ? 'rgba(255,215,0,0.1)' : 'rgba(255,255,255,0.02)';
                                const textColor = i === 0 ? '#ffd700' : '#e4e4e4';
                                const fontWeight = i === 0 ? 'bold' : 'normal';
                                html += '<div class="depth-player" data-player="' + p.name.replace(/"/g, '&quot;') + '" style="display: flex; justify-content: space-between; align-items: center; padding: 8px; margin: 4px 0; background: ' + bgColor + '; border-radius: 6px; cursor: pointer;">';
                                html += '<div><span style="color: ' + textColor + '; font-weight: ' + fontWeight + ';">' + p.name + '</span>';
                                html += '<span style="color: #888; font-size: 0.8rem; margin-left: 8px;">Age ' + (p.age || '?') + '</span></div>';
                                html += '<span style="color: #00d4ff; font-weight: bold;">' + p.value + '</span></div>';
                            });
                        } else {
                            html += '<div style="color: #666; font-size: 0.85rem; padding: 8px;">No players</div>';
                        }

                        posDiv.innerHTML = html;
                        depthGrid.appendChild(posDiv);
                    });

                    // Add click handlers for depth players
                    depthGrid.querySelectorAll('.depth-player').forEach(el => {
                        el.addEventListener('click', () => showPlayerModal(el.dataset.player));
                    });
                }

                // Populate prospects grid
                const prospectsGrid = document.getElementById('prospects-grid-modal');
                if (prospectsGrid && data.prospects) {
                    data.prospects.forEach(p => {
                        const div = document.createElement('div');
                        div.className = 'player-card';
                        div.style.cursor = 'pointer';
                        div.innerHTML = '<div><div class="name player-link">' + p.name + '</div><div style="color: #888; font-size: 0.8rem;">' + (p.position || '') + ' | Age ' + (p.age || '?') + '</div></div><div class="value" style="color: #4ade80;">#' + p.rank + '</div>';
                        div.addEventListener('click', () => showPlayerModal(p.name));
                        prospectsGrid.appendChild(div);
                    });
                }
            } catch (e) {
                content.innerHTML = `<p style="color: #f87171;">Failed to load team details: ${e.message}</p>`;
            }
        }

        function showPositionDepth(position) {
            const players = currentTeamDepth[position] || [];
            const modal = document.getElementById('player-modal');
            const content = document.getElementById('player-modal-content');

            if (players.length === 0) {
                content.innerHTML = `
                    <h3 style="color: #00d4ff; margin-bottom: 15px;">${position} Depth</h3>
                    <p style="color: #888;">No players at this position.</p>
                `;
            } else {
                content.innerHTML = `
                    <h3 style="color: #00d4ff; margin-bottom: 15px;">${position} Depth (${players.length} players)</h3>
                    <div style="display: flex; flex-direction: column; gap: 8px;">
                        ${players.map((p, i) => `
                            <div class="player-card" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}'); event.stopPropagation();" style="cursor: pointer;">
                                <div style="display: flex; align-items: center; gap: 12px;">
                                    <span style="color: #888; font-size: 0.8rem; width: 24px;">#${i + 1}</span>
                                    <div>
                                        <div class="name player-link">${p.name}</div>
                                        <div style="color: #888; font-size: 0.8rem;">Age ${p.age || '?'}</div>
                                    </div>
                                </div>
                                <div class="value">${p.value}</div>
                            </div>
                        `).join('')}
                    </div>
                `;
            }
            modal.classList.add('active');
        }

        async function showPlayerModal(playerName) {
            const modal = document.getElementById('player-modal');
            const content = document.getElementById('player-modal-content');
            content.innerHTML = '<div class="loading">Loading player details...</div>';
            modal.classList.add('active');

            try {
                const res = await fetch(`${API_BASE}/player/${encodeURIComponent(playerName)}`);
                const data = await res.json();

                if (data.error) {
                    content.innerHTML = `<p style="color: #f87171;">${data.error}</p>`;
                    return;
                }

                const trajectoryClass = data.trajectory === 'Ascending' ? 'ascending' : (data.trajectory === 'Declining' ? 'descending' : '');

                // Build projections HTML
                let projectionsHtml = '';
                if (data.projections && Object.keys(data.projections).length > 0) {
                    const projItems = Object.entries(data.projections)
                        .filter(([key]) => !['estimated_pitcher', 'estimated_hitter'].includes(key))
                        .map(([key, val]) => {
                            let displayVal;
                            if (typeof val === 'number') {
                                if (key === 'AVG' || key === 'OBP' || key === 'SLG' || key === 'OPS' || key === 'WHIP') {
                                    displayVal = val.toFixed(3);
                                } else if (key === 'ERA' || key === 'K/BB') {
                                    displayVal = val.toFixed(2);
                                } else {
                                    displayVal = Math.round(val);
                                }
                            } else {
                                displayVal = val;
                            }
                            return '<div class="stat-box"><div class="label">' + key + '</div><div class="value">' + displayVal + '</div></div>';
                        }).join('');
                    projectionsHtml = '<div style="margin-top:15px;"><div style="color:#888;font-size:0.85rem;margin-bottom:10px;">' +
                        (data.projections_estimated ? 'Estimated Projections' : 'Projections') +
                        '</div><div class="player-stats">' + projItems + '</div></div>';
                } else {
                    projectionsHtml = '<div style="color:#888;margin-top:15px;">No projections available</div>';
                }

                // Build actual stats HTML
                let actualStatsHtml = '';
                if (data.actual_stats && Object.keys(data.actual_stats).length > 0) {
                    const statItems = Object.entries(data.actual_stats)
                        .filter(([key]) => key !== 'type')
                        .map(([key, val]) => '<div class="stat-box"><div class="label">' + key + '</div><div class="value">' + val + '</div></div>')
                        .join('');
                    actualStatsHtml = '<div style="margin-top:15px;"><div style="color:#4ade80;font-size:0.85rem;margin-bottom:10px;">2026 Actual Stats</div><div class="player-stats">' + statItems + '</div></div>';
                }

                // Build fantasy points HTML
                let fantasyPtsHtml = '';
                if (data.fantasy_points !== null || data.fppg !== null) {
                    let items = '';
                    if (data.fantasy_points !== null) items += '<div class="stat-box"><div class="label">Total FP</div><div class="value">' + data.fantasy_points.toFixed(1) + '</div></div>';
                    if (data.fppg !== null) items += '<div class="stat-box"><div class="label">FP/Game</div><div class="value">' + data.fppg.toFixed(2) + '</div></div>';
                    fantasyPtsHtml = '<div style="margin-top:15px;"><div style="color:#60a5fa;font-size:0.85rem;margin-bottom:10px;">Fantasy Points</div><div class="player-stats">' + items + '</div></div>';
                }

                // Build category contributions
                let categoryHtml = '';
                if (data.category_contributions && data.category_contributions.length > 0) {
                    categoryHtml = '<div style="margin-top:15px;"><div style="color:#888;font-size:0.85rem;margin-bottom:10px;">Category Contributions</div>' +
                        '<div style="display:flex;flex-wrap:wrap;gap:8px;">' +
                        data.category_contributions.map(c => '<span style="background:#3a3a5a;padding:6px 12px;border-radius:20px;font-size:0.8rem;color:#4ade80;">' + c + '</span>').join('') +
                        '</div></div>';
                }

                // Build prospect rank box
                let prospectRankHtml = '';
                if (data.is_prospect) {
                    prospectRankHtml = '<div class="stat-box"><div class="label">Prospect Rank</div><div class="value ascending">#' + (data.prospect_rank || 'N/A') + '</div></div>';
                }

                // Build prospect bonus box
                let prospectBonusHtml = '';
                if (data.prospect_bonus > 0) {
                    prospectBonusHtml = '<div class="stat-box"><div class="label">Prospect Bonus</div><div class="value ascending">+' + data.prospect_bonus + '</div></div>';
                }

                // Age adjustment class
                let ageAdjClass = data.age_adjustment > 0 ? 'ascending' : (data.age_adjustment < 0 ? 'descending' : '');
                let ageAdjPrefix = data.age_adjustment > 0 ? '+' : '';

                content.innerHTML = `
                    <div class="player-header">
                        <h2>${data.name}</h2>
                        <div style="color: #888; margin: 10px 0;">${data.position} | ${data.mlb_team || data.team} | ${data.fantasy_team}</div>
                        <div class="dynasty-value">${data.dynasty_value}</div>
                        <div style="color: #888;">Dynasty Value</div>
                    </div>

                    <div class="player-stats" style="margin-top:20px;">
                        <div class="stat-box">
                            <div class="label">Age</div>
                            <div class="value">${data.age}</div>
                        </div>
                        <div class="stat-box">
                            <div class="label">Trajectory</div>
                            <div class="value ${trajectoryClass}">${data.trajectory}</div>
                        </div>
                        ${prospectRankHtml}
                        <div class="stat-box">
                            <div class="label">Age Adj</div>
                            <div class="value ${ageAdjClass}">${ageAdjPrefix}${data.age_adjustment}</div>
                        </div>
                        ${prospectBonusHtml}
                    </div>

                    <div style="background:#1a1a2e;padding:12px 15px;border-radius:8px;margin-top:15px;">
                        <div style="color:#888;font-size:0.85rem;">${data.trajectory_desc}</div>
                    </div>

                    ${actualStatsHtml}

                    ${fantasyPtsHtml}

                    ${projectionsHtml}

                    ${categoryHtml}

                    <div class="trade-advice">
                        <h4>Trade Advice</h4>
                        <p>${data.trade_advice || 'No specific advice available.'}</p>
                    </div>
                `;
            } catch (e) {
                content.innerHTML = `<p style="color: #f87171;">Failed to load player details: ${e.message}</p>`;
            }
        }

        function closeModal(event) {
            if (event.target.classList.contains('modal')) {
                event.target.classList.remove('active');
            }
        }

        function closePlayerModal() {
            document.getElementById('player-modal').classList.remove('active');
        }

        function closeTeamModal() {
            document.getElementById('team-modal').classList.remove('active');
        }

        let searchTimeout = null;
        async function searchPlayers() {
            const query = document.getElementById('playerSearchInput').value.trim();
            const results = document.getElementById('search-results');

            if (query.length < 2) {
                results.innerHTML = '<div style="color:#888;">Type at least 2 characters to search...</div>';
                return;
            }

            // Debounce
            if (searchTimeout) clearTimeout(searchTimeout);
            searchTimeout = setTimeout(async () => {
                try {
                    const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}&limit=50`);
                    const data = await res.json();

                    if (!data.results || data.results.length === 0) {
                        results.innerHTML = '<div style="color:#888;">No players found</div>';
                        return;
                    }

                    results.innerHTML = data.results.map(p => `
                        <div class="player-card" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <div>
                                    <div style="font-weight:bold;">${p.name}</div>
                                    <div style="color:#888; font-size:0.85rem;">${p.position} | ${p.mlb_team} | ${p.fantasy_team}</div>
                                </div>
                                <div style="text-align:right;">
                                    <div style="color:#ffd700; font-size:1.1rem; font-weight:bold;">${p.value.toFixed(1)}</div>
                                    <div style="color:#888; font-size:0.8rem;">Age: ${p.age || '?'}</div>
                                </div>
                            </div>
                        </div>
                    `).join('');
                } catch (e) {
                    results.innerHTML = '<div style="color:#f87171;">Search failed: ' + e.message + '</div>';
                }
            }, 300);
        }

        // Close modals on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const playerModal = document.getElementById('player-modal');
                const teamModal = document.getElementById('team-modal');
                if (playerModal.classList.contains('active')) {
                    closePlayerModal();
                } else if (teamModal.classList.contains('active')) {
                    closeTeamModal();
                }
            }
        });

        async function loadSuggestions(append = false) {
            const myTeam = document.getElementById('suggestTeamSelect').value;
            const targetTeam = document.getElementById('suggestTargetSelect').value;
            const tradeType = document.getElementById('tradeTypeSelect').value;
            const results = document.getElementById('suggestions-results');

            if (!myTeam) {
                results.innerHTML = '<p style="color: #888; padding: 20px;">Select your team to see trade suggestions.</p>';
                return;
            }

            if (!append) {
                currentSuggestOffset = 0;
                allCurrentSuggestions = [];
                results.innerHTML = '<div class="loading">Finding trade suggestions...</div>';
            }

            try {
                let url = `${API_BASE}/suggest?my_team=${encodeURIComponent(myTeam)}&offset=${currentSuggestOffset}&limit=${currentSuggestLimit}`;
                if (targetTeam) url += `&target_team=${encodeURIComponent(targetTeam)}`;
                if (tradeType !== 'any') url += `&trade_type=${encodeURIComponent(tradeType)}`;
                const res = await fetch(url);
                const data = await res.json();

                if (data.error) {
                    results.innerHTML = `<p style="color: #f87171; padding: 20px;">${data.error}</p>`;
                    return;
                }

                if (!data.suggestions || data.suggestions.length === 0) {
                    if (!append) {
                        results.innerHTML = '<p style="color: #888; padding: 20px;">No suggestions found.</p>';
                    }
                    return;
                }

                allCurrentSuggestions = append ? [...allCurrentSuggestions, ...data.suggestions] : data.suggestions;

                // Show team needs if available
                let needsHtml = '';
                if (data.team_needs) {
                    const needs = data.team_needs;
                    needsHtml = `
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #3a3a5a;">
                            <div style="display: flex; gap: 20px; flex-wrap: wrap; align-items: center;">
                                <div>
                                    <span style="color: #888; font-size: 0.85rem;">Your Window:</span>
                                    <span style="color: #ffd700; font-weight: bold; margin-left: 8px; text-transform: capitalize;">${needs.window}</span>
                                </div>
                                ${needs.weaknesses && needs.weaknesses.length > 0 ? `
                                    <div>
                                        <span style="color: #888; font-size: 0.85rem;">Need:</span>
                                        <span style="color: #f87171; margin-left: 8px;">${needs.weaknesses.join(', ')}</span>
                                    </div>
                                ` : ''}
                                ${needs.strengths && needs.strengths.length > 0 ? `
                                    <div>
                                        <span style="color: #888; font-size: 0.85rem;">Strength:</span>
                                        <span style="color: #4ade80; margin-left: 8px;">${needs.strengths.join(', ')}</span>
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    `;
                }

                let html = needsHtml + allCurrentSuggestions.map((s, idx) => {
                    const fitLabel = s.fit_score >= 110 ? 'Excellent Fit' : (s.fit_score >= 95 ? 'Great Fit' : (s.fit_score >= 80 ? 'Good Fit' : 'Fair'));
                    const fitColor = s.fit_score >= 110 ? '#4ade80' : (s.fit_score >= 95 ? '#ffd700' : (s.fit_score >= 80 ? '#60a5fa' : '#888'));
                    const reasonsHtml = s.reasons && s.reasons.length > 0
                        ? `<div style="margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap;">
                            ${s.reasons.map(r => `<span style="background: rgba(74, 222, 128, 0.15); color: #4ade80; padding: 3px 10px; border-radius: 12px; font-size: 0.75rem;">${r}</span>`).join('')}
                           </div>`
                        : '';
                    return `
                    <div class="suggestion-card" onclick="applySuggestion(${idx})">
                        <div class="suggestion-header">
                            <span>Trade with ${s.other_team}</span>
                            <div style="display:flex;gap:8px;align-items:center;">
                                <span style="background:#3a3a5a;padding:4px 10px;border-radius:12px;font-size:0.75rem;">${s.trade_type || '1-for-1'}</span>
                                <span style="background: rgba(255,215,0,0.15); color: ${fitColor}; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: bold;">${fitLabel}</span>
                            </div>
                        </div>
                        <div class="suggestion-sides">
                            <div class="suggestion-side">
                                <h4>You Send (${s.you_send.length})</h4>
                                <div class="suggestion-players">${s.you_send.join(', ')}</div>
                                <div class="suggestion-value">Value: ${s.you_send_value.toFixed(1)}</div>
                            </div>
                            <div class="suggestion-side">
                                <h4>You Receive (${s.you_receive.length})</h4>
                                <div class="suggestion-players">${s.you_receive.join(', ')}</div>
                                <div class="suggestion-value">Value: ${s.you_receive_value.toFixed(1)}</div>
                            </div>
                        </div>
                        ${reasonsHtml}
                    </div>
                `}).join('');

                if (data.has_more) {
                    html += `<div style="text-align:center;margin-top:20px;"><button class="btn btn-secondary" onclick="loadMoreSuggestions()">More Suggestions</button></div>`;
                }

                results.innerHTML = html;
            } catch (e) {
                results.innerHTML = `<p style="color: #f87171; padding: 20px;">Failed to load suggestions: ${e.message}</p>`;
            }
        }

        function loadMoreSuggestions() {
            currentSuggestOffset += currentSuggestLimit;
            loadSuggestions(true);
        }

        async function loadFASuggestions() {
            const myTeam = document.getElementById('faTeamSelect').value;
            const posFilter = document.getElementById('faPosFilter').value;
            const results = document.getElementById('fa-results');

            results.innerHTML = '<div class="loading">Loading free agents...</div>';

            try {
                let url = `${API_BASE}/free-agents`;
                let params = [];
                if (myTeam) params.push(`team=${encodeURIComponent(myTeam)}`);
                if (posFilter) params.push(`position=${encodeURIComponent(posFilter)}`);
                if (params.length > 0) url += '?' + params.join('&');
                const res = await fetch(url);
                const data = await res.json();

                if (data.error) {
                    results.innerHTML = `<p style="color: #f87171; padding: 20px;">${data.error}</p>`;
                    return;
                }

                if (!data.suggestions || data.suggestions.length === 0) {
                    results.innerHTML = '<p style="color: #888; padding: 20px;">No free agent recommendations found.</p>';
                    return;
                }

                // Show team needs summary or general header
                let needsHtml = '';
                if (data.team_needs) {
                    const needs = data.team_needs;
                    needsHtml = `
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #3a3a5a;">
                            <div style="display: flex; gap: 20px; flex-wrap: wrap; align-items: center;">
                                <div>
                                    <span style="color: #888; font-size: 0.85rem;">Team Window:</span>
                                    <span style="color: #ffd700; font-weight: bold; margin-left: 8px; text-transform: capitalize;">${needs.window}</span>
                                </div>
                                ${needs.weaknesses && needs.weaknesses.length > 0 ? `
                                    <div>
                                        <span style="color: #888; font-size: 0.85rem;">Category Needs:</span>
                                        <span style="color: #f87171; margin-left: 8px;">${needs.weaknesses.join(', ')}</span>
                                    </div>
                                ` : ''}
                                ${needs.critical_needs && needs.critical_needs.length > 0 ? `
                                    <div>
                                        <span style="color: #888; font-size: 0.85rem;">Critical Positions:</span>
                                        <span style="color: #f87171; font-weight: bold; margin-left: 8px;">${needs.critical_needs.join(', ')}</span>
                                    </div>
                                ` : (needs.positional_needs && needs.positional_needs.length > 0 ? `
                                    <div>
                                        <span style="color: #888; font-size: 0.85rem;">Position Needs:</span>
                                        <span style="color: #60a5fa; margin-left: 8px;">${needs.positional_needs.join(', ')}</span>
                                    </div>
                                ` : '')}
                            </div>
                        </div>
                    `;
                } else {
                    needsHtml = `
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #3a3a5a;">
                            <div style="color: #ffd700; font-weight: bold;">Top ${data.suggestions.length} Available Free Agents</div>
                            <div style="color: #888; font-size: 0.85rem; margin-top: 5px;">Select your team above for personalized recommendations based on your needs.</div>
                        </div>
                    `;
                }

                let html = needsHtml + data.suggestions.map(fa => {
                    const fitLabel = fa.fit_score >= 90 ? 'Excellent Fit' : (fa.fit_score >= 75 ? 'Great Fit' : (fa.fit_score >= 60 ? 'Good Fit' : 'Fair'));
                    const fitColor = fa.fit_score >= 90 ? '#4ade80' : (fa.fit_score >= 75 ? '#ffd700' : (fa.fit_score >= 60 ? '#60a5fa' : '#888'));
                    const reasonsHtml = fa.reasons && fa.reasons.length > 0
                        ? `<div style="margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap;">
                            ${fa.reasons.map(r => `<span style="background: rgba(74, 222, 128, 0.15); color: #4ade80; padding: 2px 8px; border-radius: 10px; font-size: 0.7rem;">${r}</span>`).join('')}
                           </div>`
                        : '';
                    return `
                        <div class="player-card" onclick="showPlayerModal('${fa.name.replace(/'/g, "\\'")}')">
                            <div style="flex: 1;">
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <div class="name player-link">${fa.name}</div>
                                    <span style="background: rgba(255,215,0,0.15); color: ${fitColor}; padding: 2px 8px; border-radius: 10px; font-size: 0.7rem; font-weight: bold;">${fitLabel}</span>
                                </div>
                                <div style="color: #888; font-size: 0.8rem; margin-top: 2px;">${fa.position} | ${fa.mlb_team} | Age ${fa.age}</div>
                                ${reasonsHtml}
                            </div>
                            <div style="text-align: right;">
                                <div class="value">${fa.dynasty_value}</div>
                                <div style="color: #888; font-size: 0.7rem;">${fa.roster_pct}% rostered</div>
                            </div>
                        </div>
                    `;
                }).join('');

                results.innerHTML = html;
            } catch (e) {
                results.innerHTML = `<p style="color: #f87171; padding: 20px;">Failed to load free agents: ${e.message}</p>`;
            }
        }

        function applySuggestion(idx) {
            const s = allCurrentSuggestions[idx];
            if (!s) return;

            document.getElementById('teamASelect').value = s.my_team;
            document.getElementById('teamBSelect').value = s.other_team;

            tradePlayersA = s.you_send.map(name => ({ name, team: s.my_team }));
            tradePlayersB = s.you_receive.map(name => ({ name, team: s.other_team }));
            tradePicksA = [];
            tradePicksB = [];

            renderTradePlayers('A');
            renderTradePlayers('B');

            // Update roster dropdowns for both teams
            updateTeamA();
            updateTeamB();

            showPanel('analyze');
            document.querySelector('.tabs .tab').click();
        }

        async function updateTeamA() {
            const teamName = document.getElementById('teamASelect').value;
            const rosterGroup = document.getElementById('teamARosterGroup');
            const rosterSelect = document.getElementById('teamARoster');

            if (!teamName) {
                rosterGroup.style.display = 'none';
                return;
            }

            try {
                const res = await fetch(`${API_BASE}/team/${encodeURIComponent(teamName)}`);
                const data = await res.json();

                if (data.players && data.players.length > 0) {
                    rosterSelect.innerHTML = '<option value="">-- Select Player --</option>' +
                        data.players.map(p =>
                            `<option value="${p.name.replace(/"/g, '&quot;')}" data-team="${teamName.replace(/"/g, '&quot;')}">${p.name} (${p.position}, ${p.value})</option>`
                        ).join('');
                    rosterGroup.style.display = 'block';
                }
            } catch (e) {
                console.error('Failed to load team roster:', e);
            }
        }

        async function updateTeamB() {
            const teamName = document.getElementById('teamBSelect').value;
            const rosterGroup = document.getElementById('teamBRosterGroup');
            const rosterSelect = document.getElementById('teamBRoster');

            if (!teamName) {
                rosterGroup.style.display = 'none';
                return;
            }

            try {
                const res = await fetch(`${API_BASE}/team/${encodeURIComponent(teamName)}`);
                const data = await res.json();

                if (data.players && data.players.length > 0) {
                    rosterSelect.innerHTML = '<option value="">-- Select Player --</option>' +
                        data.players.map(p =>
                            `<option value="${p.name.replace(/"/g, '&quot;')}" data-team="${teamName.replace(/"/g, '&quot;')}">${p.name} (${p.position}, ${p.value})</option>`
                        ).join('');
                    rosterGroup.style.display = 'block';
                }
            } catch (e) {
                console.error('Failed to load team roster:', e);
            }
        }

        function addPlayerFromRoster(side) {
            const select = document.getElementById(`team${side}Roster`);
            const selectedOption = select.options[select.selectedIndex];

            if (!selectedOption || !selectedOption.value) return;

            const playerName = selectedOption.value;
            const teamName = selectedOption.dataset.team;

            addPlayer(side, playerName, teamName);

            // Reset dropdown to placeholder
            select.value = '';
        }

        function populateDraftPicksList() {
            const datalist = document.getElementById('draftPicksList');
            if (!datalist) return;

            const numTeams = 12;
            const rounds = ['1st', '2nd', '3rd', '4th'];
            let options = [];

            // 2026: All 4 rounds with specific pick numbers
            // Format: "2026 1st Round Pick 1 (#1)", "2026 2nd Round Pick 1 (#13)", etc.
            rounds.forEach((round, roundIdx) => {
                for (let pick = 1; pick <= numTeams; pick++) {
                    const overallPick = (roundIdx * numTeams) + pick;
                    options.push(`2026 ${round} Round Pick ${pick} (#${overallPick})`);
                }
            });

            // 2027 and 2028: Just rounds, no specific pick numbers
            // Format: "2027 1st Round Pick", "2027 2nd Round Pick", etc.
            [2027, 2028].forEach(year => {
                rounds.forEach(round => {
                    options.push(`${year} ${round} Round Pick`);
                });
            });

            datalist.innerHTML = options.map(opt => `<option value="${opt}">`).join('');
        }

        // Trade Finder Functions
        async function loadTradeFinderPlayers() {
            const teamSelect = document.getElementById('tradeFinderTeamSelect');
            const playerSelect = document.getElementById('tradeFinderPlayerSelect');
            const teamName = teamSelect.value;

            if (!teamName) {
                playerSelect.innerHTML = '<option value="">Select team first</option>';
                playerSelect.disabled = true;
                return;
            }

            playerSelect.innerHTML = '<option value="">Loading...</option>';
            playerSelect.disabled = true;

            try {
                const res = await fetch(API_BASE + '/team/' + encodeURIComponent(teamName));
                const data = await res.json();
                const players = (data.players || []).sort((a, b) => b.value - a.value);

                playerSelect.innerHTML = '<option value="">Select player...</option>';
                players.forEach(p => {
                    const opt = document.createElement('option');
                    opt.value = p.name;
                    opt.textContent = p.name + ' (' + p.position + ') - ' + p.value + ' pts';
                    playerSelect.appendChild(opt);
                });
                playerSelect.disabled = false;
            } catch (e) {
                playerSelect.innerHTML = '<option value="">Error loading</option>';
            }
        }

        async function findTradesForPlayer() {
            const teamName = document.getElementById('tradeFinderTeamSelect').value;
            const playerName = document.getElementById('tradeFinderPlayerSelect').value;
            const direction = document.getElementById('tradeFinderDirection').value;
            const targetTeam = document.getElementById('tradeFinderTargetTeam').value;
            const results = document.getElementById('trade-finder-results');

            if (!teamName || !playerName) {
                results.innerHTML = '<p style="color: #f87171;">Please select a team and player.</p>';
                return;
            }

            results.innerHTML = '<div class="loading">Finding trade packages...</div>';

            try {
                let url = API_BASE + '/find-trades-for-player?player_name=' + encodeURIComponent(playerName);
                url += '&team_name=' + encodeURIComponent(teamName);
                url += '&direction=' + direction + '&limit=20';
                if (targetTeam) url += '&target_team=' + encodeURIComponent(targetTeam);

                const res = await fetch(url);
                const data = await res.json();

                if (data.error) {
                    results.innerHTML = '<p style="color: #f87171;">' + data.error + '</p>';
                    return;
                }

                if (!data.packages || data.packages.length === 0) {
                    results.innerHTML = '<p style="color: #888;">No trade packages found.</p>';
                    return;
                }

                let html = '<div style="margin-bottom: 15px; color: #ffd700;">';
                html += data.packages.length + ' packages found for ' + playerName + ' (' + data.player_value + ' pts)</div>';
                html += '<div style="display: flex; flex-direction: column; gap: 12px;">';

                data.packages.forEach(pkg => {
                    const diffColor = Math.abs(pkg.value_diff) <= 5 ? '#4ade80' : (Math.abs(pkg.value_diff) <= 15 ? '#ffd700' : '#f87171');
                    const diffText = pkg.value_diff >= 0 ? '+' + pkg.value_diff : pkg.value_diff;

                    html += '<div style="background: linear-gradient(135deg, #1a1a2e, #16213e); border-radius: 10px; padding: 15px; border: 1px solid #3a3a5a;">';
                    html += '<div style="display: flex; justify-content: space-between; margin-bottom: 10px;">';
                    html += '<span style="color: #00d4ff;">' + pkg.other_team + '</span>';
                    html += '<span style="color: ' + diffColor + ';">' + diffText + ' pts</span>';
                    html += '</div>';
                    html += '<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">';
                    html += '<div style="background: rgba(248,113,113,0.1); padding: 10px; border-radius: 6px;">';
                    html += '<div style="color: #f87171; font-size: 0.8rem; margin-bottom: 5px;">Send (' + pkg.send_total + ')</div>';
                    pkg.send.forEach(p => {
                        html += '<div style="color: #e0e0e0; font-size: 0.85rem;">' + p.name + ' - ' + p.value + '</div>';
                    });
                    html += '</div>';
                    html += '<div style="background: rgba(74,222,128,0.1); padding: 10px; border-radius: 6px;">';
                    html += '<div style="color: #4ade80; font-size: 0.8rem; margin-bottom: 5px;">Receive (' + pkg.receive_total + ')</div>';
                    pkg.receive.forEach(p => {
                        html += '<div style="color: #e0e0e0; font-size: 0.85rem;">' + p.name + ' - ' + p.value + '</div>';
                    });
                    html += '</div></div></div>';
                });

                html += '</div>';
                results.innerHTML = html;
            } catch (e) {
                results.innerHTML = '<p style="color: #f87171;">Error: ' + e.message + '</p>';
            }
        }

        // Initialize
        loadTeams().then(() => populateDraftPicksList());
        loadProspects();
    </script>
    <datalist id="draftPicksList"></datalist>
</body>
</html>'''

# ============================================================================
# DATA LOADING
# ============================================================================

# Cache for player ages from Fantrax CSV
fantrax_ages = {}

# Free agents data
FREE_AGENTS = []


def load_free_agents():
    """Load available free agents from fantrax_available_players.csv."""
    import csv
    global FREE_AGENTS
    FREE_AGENTS = []

    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, 'fantrax_available_players.csv')

    if not os.path.exists(csv_path):
        print("Warning: fantrax_available_players.csv not found")
        return

    # Debug: Check PROSPECT_RANKINGS state before loading FAs
    print(f"load_free_agents: PROSPECT_RANKINGS has {len(PROSPECT_RANKINGS)} entries")
    sample_prospects = list(PROSPECT_RANKINGS.items())[:5]
    print(f"  Sample: {sample_prospects}")
    # Check if specific FA prospects are in rankings
    for test_name in ['Kade Anderson', 'Seth Hernandez', 'Julian Garcia']:
        rank = PROSPECT_RANKINGS.get(test_name)
        print(f"  '{test_name}' in PROSPECT_RANKINGS: {rank}")

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Parse the Score field (fantasy value)
                    score = float(row.get('Score', 0) or 0)
                    age = int(row.get('Age', 0) or 0)
                    rank = int(row.get('RkOv', 9999) or 9999)
                    ros_pct = row.get('Ros', '0%').replace('%', '')
                    ros = float(ros_pct) if ros_pct else 0

                    fa_name = row.get('Player', '')
                    # Handle ADP field that might be "-" or empty
                    adp_str = row.get('ADP', '999')
                    try:
                        adp = float(adp_str) if adp_str and adp_str != '-' else 999
                    except ValueError:
                        adp = 999

                    fa = {
                        'id': row.get('ID', ''),
                        'name': fa_name,
                        'mlb_team': row.get('Team', ''),
                        'position': row.get('Position', ''),
                        'rank': rank,
                        'age': age,
                        'score': score,
                        'roster_pct': ros,
                        'adp': adp,
                    }

                    # Check if FA is a ranked prospect (using normalized name matching)
                    prospect_rank, matched_name = get_prospect_rank_for_name(fa_name)
                    fa['is_prospect'] = prospect_rank is not None and prospect_rank <= 300
                    fa['prospect_rank'] = prospect_rank if fa['is_prospect'] else None
                    fa['prospect_name'] = matched_name if fa['is_prospect'] else None  # Store matched name for /prospects

                    # Debug: Log FA prospects found
                    if fa['is_prospect']:
                        match_info = f" (matched as '{matched_name}')" if matched_name != fa_name else ""
                        print(f"FA PROSPECT FOUND: {fa_name}{match_info} - Rank #{prospect_rank}")

                    # Calculate dynasty value for FA (with prospect bonus if applicable)
                    fa['dynasty_value'] = calculate_fa_dynasty_value(fa)

                    # Debug: Log value for ranked prospects
                    if fa['is_prospect']:
                        print(f"  -> Dynasty Value: {fa['dynasty_value']}")
                    FREE_AGENTS.append(fa)
                except (ValueError, TypeError) as e:
                    continue

        # Sort by dynasty value
        FREE_AGENTS.sort(key=lambda x: x['dynasty_value'], reverse=True)

        # Count FA prospects
        fa_prospect_count = sum(1 for fa in FREE_AGENTS if fa.get('is_prospect'))
        print(f"Loaded {len(FREE_AGENTS)} free agents ({fa_prospect_count} are ranked prospects)")
    except Exception as e:
        print(f"Error loading free agents: {e}")


def calculate_fa_dynasty_value(fa):
    """Calculate dynasty value for a free agent.

    The Fantrax 'Score' is projected fantasy points (0-100+ scale).
    We need to convert this to dynasty value (typically 5-90 for most players).
    FAs are generally worth less than rostered players, so we scale accordingly.
    """
    fantrax_score = fa['score']
    rank = fa['rank']
    age = fa['age']
    roster_pct = fa['roster_pct']

    # Convert Fantrax score to dynasty value scale
    # Elite FA (score 80+) -> dynasty ~40-50
    # Good FA (score 60-80) -> dynasty ~25-40
    # Average FA (score 40-60) -> dynasty ~15-25
    # Below average (score <40) -> dynasty ~5-15
    if fantrax_score >= 80:
        base_value = 35 + (fantrax_score - 80) * 0.5  # 35-45 range
    elif fantrax_score >= 60:
        base_value = 20 + (fantrax_score - 60) * 0.75  # 20-35 range
    elif fantrax_score >= 40:
        base_value = 10 + (fantrax_score - 40) * 0.5  # 10-20 range
    else:
        base_value = max(5, fantrax_score * 0.25)  # 5-10 range

    # DEBUG: Log calculation details for FA prospects
    if fa.get('is_prospect'):
        print(f"FA PROSPECT VALUE CALC: {fa.get('name')}")
        print(f"  fantrax_score={fantrax_score}, base_value={base_value}")
        print(f"  age={age}, rank={rank}, roster_pct={roster_pct}")

    # Age adjustment - younger FAs more valuable in dynasty
    if age <= 24:
        age_mult = 1.25
    elif age <= 26:
        age_mult = 1.15
    elif age <= 28:
        age_mult = 1.05
    elif age <= 30:
        age_mult = 0.95
    elif age <= 33:
        age_mult = 0.80
    else:
        age_mult = 0.60

    # Rank bonus - top ranked FAs get a boost
    if rank <= 50:
        rank_bonus = 8
    elif rank <= 100:
        rank_bonus = 5
    elif rank <= 200:
        rank_bonus = 3
    elif rank <= 400:
        rank_bonus = 1
    else:
        rank_bonus = 0

    # Roster % as quality indicator (if 80%+ of leagues roster them, they're good)
    if roster_pct >= 80:
        ros_bonus = 5
    elif roster_pct >= 60:
        ros_bonus = 3
    elif roster_pct >= 40:
        ros_bonus = 1
    else:
        ros_bonus = 0

    # Prospect handling - FA prospects should have values similar to rostered prospects
    # Use VALUE FLOORS to ensure ranked prospects have appropriate minimum values
    is_prospect = fa.get('is_prospect')
    prospect_rank = fa.get('prospect_rank')

    print(f"DEBUG calculate_fa_dynasty_value: {fa.get('name')} - is_prospect={is_prospect}, prospect_rank={prospect_rank}")

    if is_prospect and prospect_rank:
        # Calculate preliminary value
        preliminary_value = (base_value * age_mult) + rank_bonus + ros_bonus
        print(f"  -> preliminary_value={preliminary_value}, applying prospect floor for rank {prospect_rank}")

        # Apply prospect value floors using a graduated scale
        # IMPORTANT: Prospects should NOT exceed proven MLB players (who are typically 70-85)
        # Adjusted floors to match rostered prospect values:
        # Elite (1-10): floor 55-60, cap 68
        # Top 25 (11-25): floor 48-55, cap 62
        # Top 50 (26-50): floor 40-48, cap 55
        # Top 100 (51-100): floor 30-40, cap 48
        if prospect_rank <= 10:
            # Elite prospects (1-10): floor 55-60, cap 68
            floor = 60 - (prospect_rank - 1) * 0.5  # 60 down to 55.5
            cap = 68
            value = max(preliminary_value, floor)
            value = min(value, cap)
        elif prospect_rank <= 25:
            # Top 25 (11-25): floor 48-55, cap 62
            floor = 55 - (prospect_rank - 10) * 0.47  # 55 down to 48
            cap = 62
            value = max(preliminary_value, floor)
            value = min(value, cap)
        elif prospect_rank <= 50:
            # Top 50 (26-50): floor 40-48, cap 55
            floor = 48 - (prospect_rank - 25) * 0.32  # 48 down to 40
            cap = 55
            value = max(preliminary_value, floor)
            value = min(value, cap)
        elif prospect_rank <= 100:
            # Top 100 (51-100): floor 30-40, cap 48
            floor = 40 - (prospect_rank - 50) * 0.2  # 40 down to 30
            cap = 48
            value = max(preliminary_value, floor)
            value = min(value, cap)
        elif prospect_rank <= 150:
            # Rank 101-150: floor 20-30, cap 38
            floor = 30 - (prospect_rank - 100) * 0.2  # 30 down to 20
            cap = 38
            value = max(preliminary_value, floor)
            value = min(value, cap)
        elif prospect_rank <= 300:
            # Rank 151-200: floor 15-20, cap 28
            floor = 20 - (prospect_rank - 150) * 0.1  # 20 down to 15
            cap = 28
            value = max(preliminary_value, floor)
            value = min(value, cap)
        else:
            # Rank 201+: floor 10-15, cap 20
            floor = max(10, 15 - (prospect_rank - 200) * 0.05)
            cap = 20
            value = max(preliminary_value, floor)
            value = min(value, cap)

        final_value = round(value, 1)
        print(f"  -> PROSPECT FLOOR APPLIED: {fa.get('name')} rank {prospect_rank} -> value {final_value}")
        return final_value

    # Non-prospect FA value calculation
    value = (base_value * age_mult) + rank_bonus + ros_bonus
    final_value = round(value, 1)
    print(f"  -> NON-PROSPECT PATH: {fa.get('name')} -> value {final_value}")
    return final_value


def load_ages_from_fantrax_csv():
    """Load player ages from Fantrax CSV export and prospect ranking files."""
    import csv
    import glob

    global fantrax_ages
    script_dir = os.path.dirname(os.path.abspath(__file__))
    total_count = 0

    # Load from Fantrax player CSV (primary source)
    search_patterns = [
        os.path.join(script_dir, 'Fantrax*.csv'),
        os.path.join(script_dir, 'fantrax*.csv'),
    ]

    csv_file = None
    for pattern in search_patterns:
        matches = glob.glob(pattern)
        if matches:
            csv_file = matches[0]
            break

    if csv_file:
        try:
            count = 0
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Player', '').strip()
                    age_str = row.get('Age', '')
                    if name and age_str and age_str.isdigit():
                        fantrax_ages[name] = int(age_str)
                        count += 1
            print(f"Loaded {count} player ages from Fantrax CSV")
            total_count += count
        except Exception as e:
            print(f"Warning: Could not load ages from Fantrax CSV: {e}")

    # Also load from prospect ranking files (fill in missing or zero ages)
    prospect_patterns = [
        os.path.join(script_dir, 'Consensus*Ranks*Hitters*.csv'),
        os.path.join(script_dir, 'Consensus*Ranks*Pitchers*.csv'),
    ]

    for pattern in prospect_patterns:
        for csv_file in glob.glob(pattern):
            try:
                count = 0
                with open(csv_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = row.get('Name', '').strip()
                        age_str = row.get('Age', '')
                        # Add if missing OR if existing age is 0
                        if name and age_str and age_str.isdigit():
                            age = int(age_str)
                            if age > 0 and (name not in fantrax_ages or fantrax_ages[name] == 0):
                                fantrax_ages[name] = age
                                count += 1
                if count > 0:
                    print(f"Loaded {count} additional ages from {os.path.basename(csv_file)}")
                    total_count += count
            except Exception as e:
                print(f"Warning: Could not load ages from {csv_file}: {e}")

    print(f"Total player ages loaded: {total_count}")


def load_projection_csvs():
    """Load projection data from CSV files, averaging ZiPS and Steamer when available."""
    import csv
    import glob

    script_dir = os.path.dirname(os.path.abspath(__file__))

    def avg_val(v1, v2):
        """Average two values, handling None/0 cases."""
        if v1 and v2:
            return (v1 + v2) / 2
        return v1 or v2 or 0

    def load_fangraphs_hitters(csv_file):
        """Load hitter projections from a FanGraphs CSV."""
        projections = {}
        try:
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Name', '').strip().strip('"')
                    if not name:
                        continue
                    try:
                        projections[name] = {
                            "AB": int(float(row.get('AB', 0) or 0)),
                            "R": int(float(row.get('R', 0) or 0)),
                            "HR": int(float(row.get('HR', 0) or 0)),
                            "RBI": int(float(row.get('RBI', 0) or 0)),
                            "SB": int(float(row.get('SB', 0) or 0)),
                            "AVG": float(row.get('AVG', 0) or 0),
                            "OBP": float(row.get('OBP', 0) or 0),
                            "OPS": float(row.get('OPS', 0) or 0),
                            "H": int(float(row.get('H', 0) or 0)),
                            "2B": int(float(row.get('2B', 0) or 0)),
                            "3B": int(float(row.get('3B', 0) or 0)),
                            "BB": int(float(row.get('BB', 0) or 0)),
                            "SO": int(float(row.get('SO', 0) or 0)),
                            "SLG": float(row.get('SLG', 0) or 0),
                        }
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            print(f"Warning: Error loading {csv_file}: {e}")
        return projections

    def load_fangraphs_pitchers(csv_file):
        """Load pitcher projections from a FanGraphs CSV."""
        projections = {}
        try:
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Name', '').strip().strip('"')
                    if not name:
                        continue
                    try:
                        gs = int(float(row.get('GS', 0) or 0))
                        sv = int(float(row.get('SV', 0) or 0))
                        hld = int(float(row.get('HLD', 0) or 0))
                        projections[name] = {
                            "IP": float(row.get('IP', 0) or 0),
                            "K": int(float(row.get('SO', 0) or 0)),  # FanGraphs uses SO for pitcher K
                            "W": int(float(row.get('W', 0) or 0)),
                            "L": int(float(row.get('L', 0) or 0)),
                            "SV": sv,
                            "HD": hld,
                            "ERA": float(row.get('ERA', 0) or 0),
                            "WHIP": float(row.get('WHIP', 0) or 0),
                            "H": int(float(row.get('H', 0) or 0)),
                            "BB": int(float(row.get('BB', 0) or 0)),
                            "HR": int(float(row.get('HR', 0) or 0)),
                            "G": int(float(row.get('G', 0) or 0)),
                            "GS": gs,
                            "QS": int(float(row.get('QS', 0) or gs * 0.55)),
                        }
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            print(f"Warning: Error loading {csv_file}: {e}")
        return projections

    # Try to load FanGraphs ZiPS and Steamer projections
    zips_hitters = os.path.join(script_dir, 'fangraphs-leaderboard-projections-zips.csv')
    steamer_hitters = os.path.join(script_dir, 'fangraphs-leaderboard-projections-steamer.csv')
    zips_pitchers = os.path.join(script_dir, 'fangraphs-leaderboard-projections-pitcher-zips.csv')
    steamer_pitchers = os.path.join(script_dir, 'fangraphs-leaderboard-projections-pitcher-steamer.csv')

    hitter_count = 0
    pitcher_count = 0

    # Load and average hitter projections
    if os.path.exists(zips_hitters) or os.path.exists(steamer_hitters):
        zips_h = load_fangraphs_hitters(zips_hitters) if os.path.exists(zips_hitters) else {}
        steamer_h = load_fangraphs_hitters(steamer_hitters) if os.path.exists(steamer_hitters) else {}

        all_hitters = set(zips_h.keys()) | set(steamer_h.keys())
        for name in all_hitters:
            z = zips_h.get(name, {})
            s = steamer_h.get(name, {})
            if z or s:
                HITTER_PROJECTIONS[name] = {
                    "AB": int(avg_val(z.get('AB'), s.get('AB'))),
                    "R": int(avg_val(z.get('R'), s.get('R'))),
                    "HR": int(avg_val(z.get('HR'), s.get('HR'))),
                    "RBI": int(avg_val(z.get('RBI'), s.get('RBI'))),
                    "SB": int(avg_val(z.get('SB'), s.get('SB'))),
                    "AVG": round(avg_val(z.get('AVG'), s.get('AVG')), 3),
                    "OBP": round(avg_val(z.get('OBP'), s.get('OBP')), 3),
                    "OPS": round(avg_val(z.get('OPS'), s.get('OPS')), 3),
                    "H": int(avg_val(z.get('H'), s.get('H'))),
                    "2B": int(avg_val(z.get('2B'), s.get('2B'))),
                    "3B": int(avg_val(z.get('3B'), s.get('3B'))),
                    "BB": int(avg_val(z.get('BB'), s.get('BB'))),
                    "SO": int(avg_val(z.get('SO'), s.get('SO'))),
                    "SLG": round(avg_val(z.get('SLG'), s.get('SLG')), 3),
                }
                hitter_count += 1

        print(f"Loaded {hitter_count} hitter projections (ZiPS + Steamer averaged)")
    else:
        # Fallback to old projection files
        hitter_files = glob.glob(os.path.join(script_dir, '*hitter*projection*.csv'))
        if hitter_files:
            try:
                with open(hitter_files[0], 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        player_name = row.get('Player', '').strip()
                        if not player_name:
                            continue
                        try:
                            proj = {
                                "AB": int(float(row.get('AB', 0) or 0)),
                                "R": int(float(row.get('R', 0) or 0)),
                                "HR": int(float(row.get('HR', 0) or 0)),
                                "RBI": int(float(row.get('RBI', 0) or 0)),
                                "SB": int(float(row.get('SB', 0) or 0)),
                                "AVG": float(row.get('AVG', 0) or 0),
                                "OBP": float(row.get('OBP', 0) or 0),
                                "OPS": float(row.get('OPS', 0) or 0),
                                "H": int(float(row.get('H', 0) or 0)),
                                "2B": int(float(row.get('2B', 0) or 0)),
                                "3B": int(float(row.get('3B', 0) or 0)),
                                "BB": int(float(row.get('BB', 0) or 0)),
                                "SO": int(float(row.get('SO', 0) or 0)),
                                "SLG": float(row.get('SLG', 0) or 0),
                            }
                            if proj["AB"] > 0:
                                HITTER_PROJECTIONS[player_name] = proj
                                hitter_count += 1
                        except (ValueError, TypeError):
                            continue
                print(f"Loaded {hitter_count} hitter projections from CSV")
            except Exception as e:
                print(f"Warning: Failed to load hitter projections: {e}")

    # Load and average pitcher projections (ZiPS + Steamer)
    if os.path.exists(zips_pitchers) or os.path.exists(steamer_pitchers):
        zips_p = load_fangraphs_pitchers(zips_pitchers) if os.path.exists(zips_pitchers) else {}
        steamer_p = load_fangraphs_pitchers(steamer_pitchers) if os.path.exists(steamer_pitchers) else {}

        all_pitchers = set(zips_p.keys()) | set(steamer_p.keys())
        for name in all_pitchers:
            z = zips_p.get(name, {})
            s = steamer_p.get(name, {})
            if z or s:
                gs = int(avg_val(z.get('GS'), s.get('GS')))
                sv = int(avg_val(z.get('SV'), s.get('SV')))
                hld = int(avg_val(z.get('HD'), s.get('HD')))

                proj = {
                    "IP": round(avg_val(z.get('IP'), s.get('IP')), 1),
                    "K": int(avg_val(z.get('K'), s.get('K'))),
                    "W": int(avg_val(z.get('W'), s.get('W'))),
                    "L": int(avg_val(z.get('L'), s.get('L'))),
                    "SV": sv,
                    "HD": hld,
                    "ERA": round(avg_val(z.get('ERA'), s.get('ERA')), 2),
                    "WHIP": round(avg_val(z.get('WHIP'), s.get('WHIP')), 3),
                    "H": int(avg_val(z.get('H'), s.get('H'))),
                    "BB": int(avg_val(z.get('BB'), s.get('BB'))),
                    "HR": int(avg_val(z.get('HR'), s.get('HR'))),
                    "G": int(avg_val(z.get('G'), s.get('G'))),
                    "GS": gs,
                    "QS": int(avg_val(z.get('QS'), s.get('QS')) or gs * 0.55),
                }

                # Separate into SP and RP based on saves/holds
                if sv > 0 or hld > 0 or gs == 0:
                    RELIEVER_PROJECTIONS[name] = proj
                else:
                    PITCHER_PROJECTIONS[name] = proj
                pitcher_count += 1

        print(f"Loaded {pitcher_count} pitcher projections (ZiPS + Steamer averaged)")
    else:
        # Fallback to old projection files
        pitcher_files = [f for f in glob.glob(os.path.join(script_dir, '*pitcher*projection*.csv')) if 'relief' not in f.lower()]
        if pitcher_files:
            try:
                with open(pitcher_files[0], 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        player_name = row.get('Player', '').strip()
                        if not player_name:
                            continue
                        try:
                            gs = int(float(row.get('GS', 0) or 0))
                            proj = {
                                "IP": float(row.get('IP', 0) or 0),
                                "K": int(float(row.get('K', 0) or 0)),
                                "W": int(float(row.get('W', 0) or 0)),
                                "L": int(float(row.get('L', 0) or 0)),
                                "SV": int(float(row.get('SV', 0) or 0)),
                                "ERA": float(row.get('ERA', 0) or 0),
                                "WHIP": float(row.get('WHIP', 0) or 0),
                                "ER": int(float(row.get('ER', 0) or 0)),
                                "H": int(float(row.get('H', 0) or 0)),
                                "BB": int(float(row.get('BB', 0) or 0)),
                                "HR": int(float(row.get('HR', 0) or 0)),
                                "G": int(float(row.get('G', 0) or 0)),
                                "GS": gs,
                                "QS": int(gs * 0.55),
                            }
                            if proj["IP"] > 0:
                                PITCHER_PROJECTIONS[player_name] = proj
                                pitcher_count += 1
                        except (ValueError, TypeError):
                            continue
                print(f"Loaded {pitcher_count} pitcher projections from CSV")
            except Exception as e:
                print(f"Warning: Failed to load pitcher projections: {e}")

    # Load reliever projections (only if we didn't load from FanGraphs which includes RPs)
    if not (os.path.exists(zips_pitchers) or os.path.exists(steamer_pitchers)):
        relief_files = glob.glob(os.path.join(script_dir, '*relief*projection*.csv'))
        if relief_files:
            try:
                count = 0
                with open(relief_files[0], 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        player_name = row.get('Player', '').strip()
                        if not player_name:
                            continue
                        try:
                            proj = {
                                "IP": float(row.get('IP', 0) or 0),
                                "K": int(float(row.get('K', 0) or 0)),
                                "W": int(float(row.get('W', 0) or 0)),
                                "L": int(float(row.get('L', 0) or 0)),
                                "SV": int(float(row.get('SV', 0) or 0)),
                                "BS": int(float(row.get('BS', 0) or 0)),
                                "HD": int(float(row.get('HD', row.get('HLD', 0)) or 0)),
                                "ERA": float(row.get('ERA', 0) or 0),
                                "WHIP": float(row.get('WHIP', 0) or 0),
                                "ER": int(float(row.get('ER', 0) or 0)),
                                "H": int(float(row.get('H', 0) or 0)),
                                "BB": int(float(row.get('BB', 0) or 0)),
                                "HR": int(float(row.get('HR', 0) or 0)),
                                "G": int(float(row.get('G', 0) or 0)),
                            }
                            if proj["IP"] > 0:
                                RELIEVER_PROJECTIONS[player_name] = proj
                                count += 1
                        except (ValueError, TypeError):
                            continue
                print(f"Loaded {count} reliever projections from CSV")
            except Exception as e:
                print(f"Warning: Failed to load reliever projections: {e}")


def load_prospect_rankings():
    """Load prospect rankings from prospects.json and Consensus CSV files, average them,
    then re-rank sequentially 1-200+ to eliminate duplicates."""
    import csv
    import glob

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Store the original rankings from prospects.json (already loaded)
    json_rankings = dict(PROSPECT_RANKINGS)

    # Load rankings and metadata from CSV files (multiple formats supported)
    csv_rankings = {}
    csv_metadata = {}  # name -> {position, age, mlb_team}

    # Support multiple file patterns
    file_patterns = [
        'Consensus*Ranks*.csv',
        'Prospects Live*.csv',
        '*Prospect*Ranking*.csv'
    ]

    prospect_files = []
    for pattern in file_patterns:
        prospect_files.extend(glob.glob(os.path.join(script_dir, pattern)))
    prospect_files = list(set(prospect_files))  # Remove duplicates

    for csv_file in prospect_files:
        try:
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    # Support multiple column name formats
                    name = (row.get('Name') or row.get('Name_FG') or row.get('Player') or '').strip()
                    avg_rank_str = row.get('Avg Rank') or row.get('Rank') or row.get('Overall') or ''

                    if not name or not avg_rank_str:
                        continue

                    try:
                        avg_rank = float(avg_rank_str)
                        # Keep the better (lower) rank if player appears in multiple CSV files
                        if name not in csv_rankings or avg_rank < csv_rankings[name]:
                            csv_rankings[name] = avg_rank
                            # Store metadata for this prospect (support multiple column names)
                            age_str = row.get('Age', '')
                            csv_metadata[name] = {
                                'position': row.get('Pos') or row.get('Position') or 'UTIL',
                                'age': int(age_str) if age_str and age_str.isdigit() else 0,
                                'mlb_team': row.get('Team') or row.get('Org') or 'N/A',
                                'level': row.get('Level', 'N/A')
                            }
                            count += 1
                    except (ValueError, TypeError):
                        continue

            print(f"Loaded {count} prospect rankings from {os.path.basename(csv_file)}")
        except Exception as e:
            print(f"Warning: Could not load prospect rankings from {csv_file}: {e}")

    # Merge rankings - average when player is in both sources
    merged_rankings = {}  # name -> averaged float rank

    # Process all players from both sources
    all_names = set(json_rankings.keys()) | set(csv_rankings.keys())

    for name in all_names:
        json_rank = json_rankings.get(name)
        csv_rank = csv_rankings.get(name)

        if json_rank is not None and csv_rank is not None:
            # In both - average them
            merged_rankings[name] = (json_rank + csv_rank) / 2
        elif json_rank is not None:
            # Only in JSON
            merged_rankings[name] = float(json_rank)
        else:
            # Only in CSV
            merged_rankings[name] = csv_rank

    # Sort by averaged rank and re-assign sequential rankings (1, 2, 3, ...) to eliminate duplicates
    sorted_prospects = sorted(merged_rankings.items(), key=lambda x: x[1])

    # Exclude specific players who are established MLB players, not true prospects
    EXCLUDED_PLAYERS = {
        "Munetaka Murakami",  # Japanese MLB player
        "Kazuma Okamoto",     # Japanese MLB player
        "Tatsuya Imai",       # Japanese MLB player
        "Ben Joyce",          # MLB debut 2023, no longer a prospect
        "Mick Abel",          # No longer considered a top prospect
    }

    # Filter out players who are too old to be considered prospects (26+ years old)
    # Also filter out explicitly excluded players
    MAX_PROSPECT_AGE = 25
    filtered_prospects = []
    excluded_count = 0
    for name, avg_rank in sorted_prospects:
        # Skip excluded players
        if name in EXCLUDED_PLAYERS:
            excluded_count += 1
            continue
        age = csv_metadata.get(name, {}).get('age', 0)
        # Keep if age is unknown (0) or under the max age
        if age == 0 or age <= MAX_PROSPECT_AGE:
            filtered_prospects.append((name, avg_rank))

    print(f"Excluded {excluded_count} specific players: {EXCLUDED_PLAYERS}")
    print(f"Filtered {len(sorted_prospects) - len(filtered_prospects) - excluded_count} players over age {MAX_PROSPECT_AGE}")

    # Clear and rebuild PROSPECT_RANKINGS with sequential ranks
    # Include up to 500 prospects so value caps apply to fringe prospects too
    # (The UI shows top 300 prospects, value calculator uses ranks 301-500 for caps)
    PROSPECT_RANKINGS.clear()
    PROSPECT_METADATA.clear()
    for new_rank, (name, _) in enumerate(filtered_prospects[:500], start=1):
        PROSPECT_RANKINGS[name] = new_rank
        # Store metadata if available from CSV
        if name in csv_metadata:
            PROSPECT_METADATA[name] = csv_metadata[name]
        else:
            # Default metadata for prospects only in JSON
            PROSPECT_METADATA[name] = {
                'position': 'UTIL',
                'age': 0,
                'mlb_team': 'N/A',
                'level': 'N/A'
            }

    print(f"Prospect rankings merged and re-ranked: {len(PROSPECT_RANKINGS)} total (up to 500 for value caps)")
    print(f"Prospect metadata stored for {len(PROSPECT_METADATA)} prospects")

    # Debug: Print top 10 prospects to verify correct ordering
    top_prospects = sorted([(n, r) for n, r in PROSPECT_RANKINGS.items() if r <= 10], key=lambda x: x[1])
    print(f"Top 10 prospects: {[(n, r) for n, r in top_prospects]}")

    # Debug: Print prospects around rank 195-200 to verify we have full 200
    bottom_prospects = sorted([(n, r) for n, r in PROSPECT_RANKINGS.items() if r >= 195], key=lambda x: x[1])
    print(f"Bottom 6 prospects (195-200): {[(n, r) for n, r in bottom_prospects]}")

    # Debug: Check specific rostered prospects
    test_players = ["Marcelo Mayer", "Johnny King", "Quinn Mathews"]
    print(f"\n=== DEBUG: Checking specific rostered prospects ===")
    for name in test_players:
        rank = PROSPECT_RANKINGS.get(name)
        if rank:
            print(f"  {name}: Rank {rank} - IN PROSPECT_RANKINGS")
        else:
            # Check if it's a close match
            close_matches = [n for n in PROSPECT_RANKINGS.keys() if name.lower() in n.lower() or n.lower() in name.lower()]
            print(f"  {name}: NOT FOUND. Close matches: {close_matches[:3]}")
    print(f"=== END DEBUG ===\n")


def load_data_from_json():
    """Load all league data from league_data.json (exported by data_exporter.py)."""
    global teams, interactive, league_standings, league_matchups, league_transactions, player_actual_stats, player_fantasy_points

    # Look for league_data.json
    search_paths = [
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
        os.path.expanduser('~'),
    ]

    json_path = None
    for path in search_paths:
        candidate = os.path.join(path, 'league_data.json')
        if os.path.exists(candidate):
            json_path = candidate
            break

    if not json_path:
        print("No league_data.json found")
        return False

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        print(f"Loading from: {json_path}")
        print(f"Data exported at: {data.get('exported_at', 'unknown')}")

        # Load teams and projections
        teams.clear()
        total_players = 0
        projections_loaded = 0

        for team_name, team_data in data.get('teams', {}).items():
            team = Team(name=team_name)

            for p in team_data.get('players', []):
                # Get age: prefer Fantrax CSV (most current), fallback to JSON, then PLAYER_AGES
                player_name = p['name']
                player_age = fantrax_ages.get(player_name, 0)  # Fantrax CSV is most current
                if player_age == 0:
                    player_age = p.get('age', 0)  # JSON age
                if player_age == 0:
                    player_age = PLAYER_AGES.get(player_name, 0)  # Static dictionary

                # Get prospect rank from PROSPECT_RANKINGS (using normalized matching)
                prospect_rank, matched_prospect_name = get_prospect_rank_for_name(player_name)
                # Only mark as prospect for display if rank <= 200
                is_prospect = prospect_rank is not None and prospect_rank <= 300

                player = Player(
                    name=p['name'],
                    position=p.get('position', 'N/A'),
                    mlb_team=p.get('mlb_team', 'FA'),
                    fantasy_team=team_name,
                    roster_status=p.get('status', 'Active'),
                    age=player_age,
                    is_prospect=is_prospect,
                    prospect_rank=prospect_rank if is_prospect else 999,
                )
                # Store matched prospect name for /prospects endpoint
                if is_prospect and matched_prospect_name:
                    player.prospect_name = matched_prospect_name
                team.players.append(player)
                total_players += 1

                # Debug: log top prospects being loaded
                if is_prospect and prospect_rank and prospect_rank <= 15:
                    print(f"Top prospect loaded: {player_name} (rank {prospect_rank}) - team: {team_name}")

                # Load projections if available
                proj = p.get('projections')
                if proj:
                    player_name = p['name']
                    # Determine if hitter or pitcher based on projection keys
                    if 'AB' in proj or 'HR' in proj or 'RBI' in proj:
                        HITTER_PROJECTIONS[player_name] = proj
                        projections_loaded += 1
                    elif 'IP' in proj or 'ERA' in proj or 'WHIP' in proj:
                        if proj.get('SV', 0) > 0 or proj.get('HD', 0) > 0:
                            RELIEVER_PROJECTIONS[player_name] = proj
                        else:
                            PITCHER_PROJECTIONS[player_name] = proj
                        projections_loaded += 1

                # Load actual stats if available
                actual = p.get('actual_stats')
                if actual:
                    player_actual_stats[p['name']] = actual

                # Load fantasy points if available
                fp = p.get('fantasy_points')
                fppg = p.get('fppg')
                if fp is not None or fppg is not None:
                    player_fantasy_points[p['name']] = {
                        'fantasy_points': fp,
                        'fppg': fppg
                    }

            teams[team_name] = team

        interactive = InteractiveTradeAnalyzer(dict(teams))

        # Load standings
        league_standings.clear()
        league_standings.extend(data.get('standings', []))

        # Load matchups
        league_matchups.clear()
        league_matchups.extend(data.get('matchups', []))

        # Load transactions
        league_transactions.clear()
        league_transactions.extend(data.get('transactions', []))

        print(f"Loaded {len(teams)} teams with {total_players} players from JSON")
        print(f"Loaded {projections_loaded} player projections from JSON")
        print(f"Loaded {len(player_actual_stats)} players with actual stats")
        print(f"Loaded {len(player_fantasy_points)} players with fantasy points")
        print(f"Standings: {len(league_standings)}, Matchups: {len(league_matchups)}, Transactions: {len(league_transactions)}")
        return True

    except Exception as e:
        print(f"Failed to load from JSON: {e}")
        return False


def load_data_from_csv():
    """Load roster data from CSV file (fallback when API unavailable)."""
    global teams, interactive
    import csv
    import glob

    # Look for CSV file
    search_paths = [
        os.getcwd(),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.expanduser('~'),
        os.path.join(os.path.expanduser('~'), 'Downloads'),
    ]

    csv_path = None
    for path in search_paths:
        patterns = [
            os.path.join(path, 'Fantrax*.csv'),
            os.path.join(path, 'fantrax*.csv'),
        ]
        for pattern in patterns:
            matches = glob.glob(pattern)
            if matches:
                csv_path = matches[0]
                break
        if csv_path:
            break

    if not csv_path:
        print("No Fantrax CSV file found")
        return False

    try:
        # Use the load_fantrax_data function from dynasty_trade_analyzer_v2
        teams.clear()
        teams.update(load_fantrax_data(csv_path))
        interactive = InteractiveTradeAnalyzer(dict(teams))
        print(f"Loaded {len(teams)} teams from CSV: {csv_path}")
        return True
    except Exception as e:
        print(f"Failed to load from CSV: {e}")
        return False


def load_data_from_api():
    """Load roster data from Fantrax API."""
    global teams, interactive, league_standings, league_matchups, league_transactions

    if not FANTRAX_AVAILABLE:
        print("Fantrax API not available")
        return False

    try:
        from fantraxapi import FantraxAPI
        api = FantraxAPI(FANTRAX_LEAGUE_ID)

        # Load teams and rosters
        teams.clear()
        total_players = 0

        for fantrax_team in api.teams:
            team_name = fantrax_team.name
            roster = api.team_roster(fantrax_team.id)

            team = Team(name=team_name)

            for roster_player in roster.players:
                player_name = roster_player.name

                # Check if player is in prospect rankings (using normalized matching)
                prospect_rank, matched_prospect_name = get_prospect_rank_for_name(player_name)
                # Only mark as prospect for display if rank <= 200
                is_prospect = prospect_rank is not None and prospect_rank <= 300

                player = Player(
                    name=player_name,
                    position=roster_player.position or "N/A",
                    mlb_team=roster_player.mlb_team or "FA",
                    fantasy_team=team_name,
                    roster_status=roster_player.status or "Active",
                    age=roster_player.age or 0,
                    is_prospect=is_prospect,
                    prospect_rank=prospect_rank if is_prospect else 999,
                )
                # Store matched prospect name for /prospects endpoint
                if is_prospect and matched_prospect_name:
                    player.prospect_name = matched_prospect_name

                team.players.append(player)
                total_players += 1

            teams[team_name] = team

        interactive = InteractiveTradeAnalyzer(dict(teams))

        # Load standings
        try:
            standings = api.standings()
            league_standings = []
            for i, entry in enumerate(standings.teams, 1):
                league_standings.append({
                    "rank": i,
                    "team": entry.team.name if hasattr(entry, 'team') else str(entry),
                    "wins": getattr(entry, 'wins', 0),
                    "losses": getattr(entry, 'losses', 0),
                    "ties": getattr(entry, 'ties', 0),
                    "points_for": getattr(entry, 'points_for', 0),
                })
        except Exception as e:
            print(f"Could not load standings: {e}")

        # Load transactions
        try:
            txns = api.transactions(count=20)
            league_transactions = []
            for tx in txns:
                league_transactions.append({
                    "team": tx.team.name if hasattr(tx, 'team') else "Unknown",
                    "date": tx.date.strftime("%Y-%m-%d %H:%M") if hasattr(tx, 'date') else "",
                    "players": [{"name": p.name, "type": p.type} for p in tx.players] if hasattr(tx, 'players') else []
                })
        except Exception as e:
            print(f"Could not load transactions: {e}")

        print(f"Loaded {len(teams)} teams with {total_players} players from Fantrax API")
        return True

    except Exception as e:
        print(f"Failed to load from Fantrax API: {e}")
        return False


# ============================================================================
# ROUTE HANDLERS
# ============================================================================

@app.route('/')
def index():
    return Response(HTML_CONTENT, mimetype='text/html')


@app.route('/teams')
def get_teams():
    draft_order, power_rankings, team_totals = get_team_rankings()
    return jsonify({
        "teams": sorted([{
            "name": name,
            "player_count": len(team.players),
            "total_value": round(team_totals.get(name, 0), 1),
            "power_rank": power_rankings.get(name, 0),
            "draft_pick": draft_order.get(name, 0)
        } for name, team in teams.items()], key=lambda x: x["power_rank"])
    })


@app.route('/prospects')
def get_prospects():
    """Get all 200 prospects, including those not in the league."""
    # Track which prospects we've found (by name)
    found_prospects = {}  # name -> prospect_data

    # Get prospects from team rosters
    for team_name, team in teams.items():
        for player in team.players:
            if player.is_prospect and player.prospect_rank and player.prospect_rank <= 300:
                value = calculator.calculate_player_value(player)
                # Use matched prospect name as key (for consistency with PROSPECT_RANKINGS)
                prospect_key = getattr(player, 'prospect_name', None) or player.name
                found_prospects[prospect_key] = {
                    "name": player.name,
                    "rank": player.prospect_rank,
                    "position": player.position,
                    "age": player.age,
                    "mlb_team": player.mlb_team,
                    "fantasy_team": team_name,
                    "value": round(value, 1),
                    "is_free_agent": False,
                    "not_in_league": False
                }

    # Get prospects from free agents
    # Use the stored prospect_name which was matched during load_free_agents()
    for fa in FREE_AGENTS:
        if fa.get('is_prospect') and fa.get('prospect_rank') and fa['prospect_rank'] <= 300:
            # Use the stored prospect_name (matched during FA loading)
            prospect_name = fa.get('prospect_name') or fa['name']

            if prospect_name not in found_prospects:
                found_prospects[prospect_name] = {
                    "name": fa['name'],  # Use FA name for display
                    "rank": fa['prospect_rank'],
                    "position": fa['position'],
                    "age": fa['age'],
                    "mlb_team": fa['mlb_team'],
                    "fantasy_team": "Free Agent",
                    "value": fa['dynasty_value'],
                    "is_free_agent": True,
                    "not_in_league": False
                }

    # Add any prospects from PROSPECT_RANKINGS (1-300) that weren't found in rosters or FA list
    # These are all available as Free Agents in Fantrax (user confirmed all prospects are in the pool)
    # Skip alias names (keys in PROSPECT_NAME_ALIASES) to avoid duplicates
    for name, rank in PROSPECT_RANKINGS.items():
        # Skip if this is an alias name (the player will be found under their canonical name)
        if name in PROSPECT_NAME_ALIASES:
            continue
        # Only show top 300 prospects
        if rank > 300:
            continue
        if name not in found_prospects:
            metadata = PROSPECT_METADATA.get(name, {})
            # Calculate estimated value based on rank using graduated scale
            # Scale: Rank 1 = ~100, Rank 50 = ~75, Rank 100 = ~55, Rank 150 = ~32, Rank 200 = ~15, Rank 300 = ~8
            if rank <= 10:
                est_value = 100 - (rank - 1) * 0.5
            elif rank <= 25:
                est_value = 95 - (rank - 10) * 1.0
            elif rank <= 50:
                est_value = 80 - (rank - 25) * 0.5
            elif rank <= 100:
                est_value = 67 - (rank - 50) * 0.4
            elif rank <= 150:
                est_value = 46 - (rank - 100) * 0.4
            elif rank <= 200:
                est_value = 26 - (rank - 150) * 0.22  # ~15 at rank 200
            elif rank <= 250:
                est_value = 15 - (rank - 200) * 0.14  # ~8 at rank 250
            else:
                est_value = max(8 - (rank - 250) * 0.08, 5)  # Floor of 5 for ranks 251-300

            # All prospects are available in Fantrax pool - show as Free Agent
            found_prospects[name] = {
                "name": name,
                "rank": rank,
                "position": metadata.get('position', 'UTIL'),
                "age": metadata.get('age', 0),
                "mlb_team": metadata.get('mlb_team', 'N/A'),
                "fantasy_team": "Free Agent",
                "value": round(est_value, 1),
                "is_free_agent": True,
                "not_in_league": False
            }

    # Convert to list and sort by rank
    all_prospects = list(found_prospects.values())
    all_prospects.sort(key=lambda x: x["rank"])

    return jsonify({"prospects": all_prospects})


def calculate_league_category_rankings():
    """Calculate each team's category totals and rankings across the league."""
    team_cats = {}
    for t_name, t in teams.items():
        # Calculate team totals
        hr = sum(HITTER_PROJECTIONS.get(p.name, {}).get('HR', 0) for p in t.players)
        sb = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SB', 0) for p in t.players)
        rbi = sum(HITTER_PROJECTIONS.get(p.name, {}).get('RBI', 0) for p in t.players)
        runs = sum(HITTER_PROJECTIONS.get(p.name, {}).get('R', 0) for p in t.players)
        so = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SO', 0) for p in t.players)  # Hitter strikeouts (lower is better)
        k = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in t.players)
        sv_hld = sum((RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) + RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0)) for p in t.players)
        ip = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) for p in t.players)

        # Calculate QS (Quality Starts) - from starters only
        qs = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('QS', 0) for p in t.players)

        # Calculate L (Losses) - from both starters and relievers
        losses = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('L', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('L', 0)) for p in t.players)

        # Calculate BB (Walks) for K/BB ratio - from both starters and relievers
        bb = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('BB', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('BB', 0)) for p in t.players)
        k_bb = k / bb if bb > 0 else 0

        # Calculate weighted ERA and WHIP
        era_weighted = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('ERA', 0) * PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) for p in t.players)
        whip_weighted = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('WHIP', 0) * PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) for p in t.players)
        era = era_weighted / ip if ip > 0 else 5.00
        whip = whip_weighted / ip if ip > 0 else 1.50

        # Calculate weighted AVG and OPS (weighted by AB since PA not in projections)
        ab = sum(HITTER_PROJECTIONS.get(p.name, {}).get('AB', 0) for p in t.players)
        hits = sum(HITTER_PROJECTIONS.get(p.name, {}).get('AB', 0) * HITTER_PROJECTIONS.get(p.name, {}).get('AVG', 0) for p in t.players)
        ops_weighted = sum(HITTER_PROJECTIONS.get(p.name, {}).get('OPS', 0) * HITTER_PROJECTIONS.get(p.name, {}).get('AB', 0) for p in t.players)
        avg = hits / ab if ab > 0 else .250
        ops = ops_weighted / ab if ab > 0 else .700

        team_cats[t_name] = {
            'HR': hr, 'SB': sb, 'RBI': rbi, 'R': runs, 'SO': so, 'K': k, 'SV+HLD': sv_hld,
            'ERA': era, 'WHIP': whip, 'AVG': avg, 'OPS': ops, 'IP': ip,
            'QS': qs, 'L': losses, 'K/BB': k_bb
        }

    # Calculate rankings for each category
    rankings = {}
    for t_name in teams.keys():
        rankings[t_name] = {}

    # Higher is better categories
    for cat in ['HR', 'SB', 'RBI', 'R', 'K', 'SV+HLD', 'AVG', 'OPS', 'QS', 'K/BB']:
        sorted_teams = sorted(team_cats.keys(), key=lambda x: team_cats[x][cat], reverse=True)
        for rank, t_name in enumerate(sorted_teams, 1):
            rankings[t_name][cat] = rank

    # Lower is better categories (SO for hitters, ERA/WHIP/L for pitchers)
    for cat in ['SO', 'ERA', 'WHIP', 'L']:
        sorted_teams = sorted(team_cats.keys(), key=lambda x: team_cats[x][cat])
        for rank, t_name in enumerate(sorted_teams, 1):
            rankings[t_name][cat] = rank

    return team_cats, rankings


@app.route('/team/<team_name>')
def get_team(team_name):
    if team_name not in teams:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    team = teams[team_name]
    draft_order, power_rankings, team_totals = get_team_rankings()

    players_with_value = [(p, calculator.calculate_player_value(p)) for p in team.players]
    players_with_value.sort(key=lambda x: x[1], reverse=True)

    players = []
    for p, value in players_with_value:
        # Get projections for player info
        proj = HITTER_PROJECTIONS.get(p.name) or PITCHER_PROJECTIONS.get(p.name) or RELIEVER_PROJECTIONS.get(p.name, {})
        proj_str = ""
        if proj:
            if p.name in HITTER_PROJECTIONS:
                proj_str = f"{proj.get('HR', 0)} HR, {proj.get('RBI', 0)} RBI, .{int(proj.get('AVG', 0)*1000):03d} AVG"
            elif p.name in PITCHER_PROJECTIONS:
                proj_str = f"{proj.get('K', 0)} K, {proj.get('ERA', 0):.2f} ERA"
            elif p.name in RELIEVER_PROJECTIONS:
                proj_str = f"{proj.get('SV', 0)} SV, {proj.get('ERA', 0):.2f} ERA"

        players.append({
            "name": p.name,
            "position": p.position,
            "team": p.mlb_team,
            "age": p.age,
            "value": round(value, 1),
            "status": p.roster_status,
            "proj": proj_str
        })

    total_value = team_totals.get(team_name, 0)
    power_rank = power_rankings.get(team_name, 0)
    draft_pick = draft_order.get(team_name, 0)

    # Get top players and prospects
    top_players = players[:20]
    prospects = [{"name": p.name, "rank": p.prospect_rank, "age": p.age, "position": p.position}
                 for p in team.players if p.is_prospect and p.prospect_rank]
    prospects.sort(key=lambda x: x['rank'])

    # Calculate league-wide category rankings
    team_cats, league_rankings = calculate_league_category_rankings()
    my_cats = team_cats.get(team_name, {})
    my_rankings = league_rankings.get(team_name, {})
    num_teams = len(teams)

    # Build category details with values and rankings
    category_details = {
        'HR': {'value': my_cats.get('HR', 0), 'rank': my_rankings.get('HR', 0)},
        'SB': {'value': my_cats.get('SB', 0), 'rank': my_rankings.get('SB', 0)},
        'RBI': {'value': my_cats.get('RBI', 0), 'rank': my_rankings.get('RBI', 0)},
        'R': {'value': my_cats.get('R', 0), 'rank': my_rankings.get('R', 0)},
        'AVG': {'value': round(my_cats.get('AVG', .250), 3), 'rank': my_rankings.get('AVG', 0)},
        'OPS': {'value': round(my_cats.get('OPS', .700), 3), 'rank': my_rankings.get('OPS', 0)},
        'SO': {'value': my_cats.get('SO', 0), 'rank': my_rankings.get('SO', 0)},
        'K': {'value': my_cats.get('K', 0), 'rank': my_rankings.get('K', 0)},
        'ERA': {'value': round(my_cats.get('ERA', 4.50), 2), 'rank': my_rankings.get('ERA', 0)},
        'WHIP': {'value': round(my_cats.get('WHIP', 1.30), 2), 'rank': my_rankings.get('WHIP', 0)},
        'SV+HLD': {'value': my_cats.get('SV+HLD', 0), 'rank': my_rankings.get('SV+HLD', 0)},
        'QS': {'value': my_cats.get('QS', 0), 'rank': my_rankings.get('QS', 0)},
        'L': {'value': my_cats.get('L', 0), 'rank': my_rankings.get('L', 0)},
        'K/BB': {'value': round(my_cats.get('K/BB', 0), 2), 'rank': my_rankings.get('K/BB', 0)},
    }

    # Calculate category strengths/weaknesses based on rankings
    hitting_strengths, hitting_weaknesses = [], []
    pitching_strengths, pitching_weaknesses = [], []

    top_third = num_teams // 3
    bottom_third = num_teams - top_third

    for cat in ['HR', 'SB', 'RBI', 'R', 'AVG', 'OPS', 'SO']:
        rank = my_rankings.get(cat, num_teams)
        if rank <= top_third:
            hitting_strengths.append(cat)
        elif rank >= bottom_third:
            hitting_weaknesses.append(cat)

    for cat in ['K', 'ERA', 'WHIP', 'SV+HLD', 'QS', 'L', 'K/BB']:
        rank = my_rankings.get(cat, num_teams)
        if rank <= top_third:
            pitching_strengths.append(cat)
        elif rank >= bottom_third:
            pitching_weaknesses.append(cat)

    # Positional depth analysis
    pos_depth = {'C': [], '1B': [], '2B': [], 'SS': [], '3B': [], 'OF': [], 'SP': [], 'RP': []}
    for p, v in players_with_value:
        pos = p.position.upper() if p.position else ''
        player_info = {"name": p.name, "value": round(v, 1), "age": p.age}
        if 'C' in pos and '1B' not in pos and 'CF' not in pos:
            pos_depth['C'].append(player_info)
        if '1B' in pos:
            pos_depth['1B'].append(player_info)
        if '2B' in pos:
            pos_depth['2B'].append(player_info)
        if 'SS' in pos:
            pos_depth['SS'].append(player_info)
        if '3B' in pos:
            pos_depth['3B'].append(player_info)
        if 'OF' in pos or 'LF' in pos or 'CF' in pos or 'RF' in pos:
            pos_depth['OF'].append(player_info)
        if 'SP' in pos:
            pos_depth['SP'].append(player_info)
        if 'RP' in pos or 'CL' in pos:
            pos_depth['RP'].append(player_info)

    # Sort each position by value (keep all players for full depth chart)
    for pos in pos_depth:
        pos_depth[pos] = sorted(pos_depth[pos], key=lambda x: x['value'], reverse=True)

    # Calculate roster composition
    hitters = len([p for p in team.players if p.name in HITTER_PROJECTIONS])
    starters = len([p for p in team.players if p.name in PITCHER_PROJECTIONS])
    relievers = len([p for p in team.players if p.name in RELIEVER_PROJECTIONS])
    ages = [p.age for p in team.players if p.age > 0]
    avg_age = round(sum(ages) / len(ages), 1) if ages else 0
    young_count = len([a for a in ages if a <= 25])
    prime_count = len([a for a in ages if 26 <= a <= 30])
    vet_count = len([a for a in ages if a > 30])

    roster_composition = {
        'hitters': hitters,
        'starters': starters,
        'relievers': relievers,
        'avg_age': avg_age,
        'young': young_count,
        'prime': prime_count,
        'veteran': vet_count
    }

    # Generate analysis
    analysis = generate_team_analysis(team_name, team, players_with_value, power_rank, len(teams))

    return jsonify({
        "name": team_name,
        "players": players,
        "top_players": top_players,
        "prospects": prospects,
        "player_count": len(players),
        "total_value": round(total_value, 1),
        "power_rank": power_rank,
        "draft_pick": draft_pick,
        "hitting_strengths": hitting_strengths,
        "hitting_weaknesses": hitting_weaknesses,
        "pitching_strengths": pitching_strengths,
        "pitching_weaknesses": pitching_weaknesses,
        "category_details": category_details,
        "positional_depth": pos_depth,
        "roster_composition": roster_composition,
        "num_teams": num_teams,
        "analysis": analysis
    })


@app.route('/team-profile/<team_name>', methods=['GET'])
def get_team_profile_route(team_name):
    profile = get_team_profile(team_name)
    philosophy = GM_PHILOSOPHIES.get(profile.get('philosophy', 'balanced'), GM_PHILOSOPHIES['balanced'])
    assistant_gm = get_assistant_gm(team_name)
    return jsonify({
        "profile": profile,
        "philosophy_details": philosophy,
        "assistant_gm": assistant_gm
    })


@app.route('/assistant-gm/<team_name>')
def get_assistant_gm_route(team_name):
    """Get the AI Assistant GM personality for a team"""
    import random
    gm = get_assistant_gm(team_name)
    philosophy = GM_PHILOSOPHIES.get(gm.get('philosophy', 'balanced'), GM_PHILOSOPHIES['balanced'])

    return jsonify({
        "name": gm['name'],
        "title": gm['title'],
        "team": team_name,
        "philosophy": gm['philosophy'],
        "philosophy_details": philosophy,
        "personality": gm['personality'],
        "catchphrase": random.choice(gm['catchphrases']),
        "all_catchphrases": gm['catchphrases'],
        "trade_style": gm['trade_style'],
        "priorities": gm['priorities'],
        "risk_tolerance": gm['risk_tolerance'],
        "preferred_categories": gm.get('preferred_categories', [])
    })


@app.route('/team-profile/<team_name>', methods=['POST'])
def update_team_profile_route(team_name):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    success = update_team_profile(team_name, data)
    if success:
        return jsonify({"success": True, "message": "Profile updated"})
    return jsonify({"error": "Failed to save profile"}), 500


@app.route('/find-trades-for-player')
def find_trades_for_player():
    player_name = request.args.get('player_name', '')
    team_name = request.args.get('team_name', '')
    direction = request.args.get('direction', 'send')
    target_team = request.args.get('target_team', '')
    limit = int(request.args.get('limit', 20))

    if not player_name or not team_name:
        return jsonify({"error": "Missing player_name or team_name"}), 400

    if team_name not in teams:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    # Find the player
    team = teams[team_name]
    player = None
    for p in team.players:
        if p.name == player_name:
            player = p
            break

    if not player:
        return jsonify({"error": f"Player '{player_name}' not found on team"}), 404

    player_value = calculator.calculate_player_value(player)

    # Find trade packages
    packages = []

    other_teams = [t for t in teams.keys() if t != team_name]
    if target_team and target_team in other_teams:
        other_teams = [target_team]

    for other_team_name in other_teams:
        other_team = teams[other_team_name]

        if direction == 'send':
            # Find players from other team to receive
            other_players = [(p, calculator.calculate_player_value(p)) for p in other_team.players]
            other_players.sort(key=lambda x: x[1], reverse=True)

            # 1-for-1 trades
            for op, ov in other_players[:15]:
                value_diff = ov - player_value
                if -20 <= value_diff <= 20:
                    packages.append({
                        'other_team': other_team_name,
                        'trade_type': '1-for-1',
                        'send': [{'name': player.name, 'position': player.position, 'value': round(player_value, 1)}],
                        'receive': [{'name': op.name, 'position': op.position, 'value': round(ov, 1)}],
                        'send_total': round(player_value, 1),
                        'receive_total': round(ov, 1),
                        'value_diff': round(value_diff, 1),
                        'fit_score': 100 - abs(value_diff) * 2
                    })

        else:
            # direction == 'receive' - find packages to acquire the player
            my_players = [(p, calculator.calculate_player_value(p)) for p in team.players if p.name != player_name]
            my_players.sort(key=lambda x: x[1], reverse=True)

            for mp, mv in my_players[:15]:
                value_diff = player_value - mv
                if -20 <= value_diff <= 20:
                    packages.append({
                        'other_team': other_team_name,
                        'trade_type': '1-for-1',
                        'send': [{'name': mp.name, 'position': mp.position, 'value': round(mv, 1)}],
                        'receive': [{'name': player.name, 'position': player.position, 'value': round(player_value, 1)}],
                        'send_total': round(mv, 1),
                        'receive_total': round(player_value, 1),
                        'value_diff': round(value_diff, 1),
                        'fit_score': 100 - abs(value_diff) * 2
                    })

    # Sort by fit score
    packages.sort(key=lambda x: x['fit_score'], reverse=True)

    return jsonify({
        'player_name': player_name,
        'player_value': round(player_value, 1),
        'packages': packages[:limit]
    })


# ============================================================================
# AI ANALYSIS HELPER FUNCTIONS
# ============================================================================

def get_category_trade_targets(team_name, weak_categories, num_targets=3):
    """Find players from other teams who excel in categories the team needs."""
    targets = {}

    for cat in weak_categories[:2]:  # Focus on top 2 weaknesses
        cat_targets = []

        for other_team_name, other_team in teams.items():
            if other_team_name == team_name:
                continue

            for player in other_team.players:
                proj = HITTER_PROJECTIONS.get(player.name, {}) or PITCHER_PROJECTIONS.get(player.name, {}) or RELIEVER_PROJECTIONS.get(player.name, {})
                if not proj:
                    continue

                value = calculator.calculate_player_value(player)
                cat_value = 0

                # Map category to projection key
                if cat == 'HR':
                    cat_value = proj.get('HR', 0)
                elif cat == 'SB':
                    cat_value = proj.get('SB', 0)
                elif cat == 'RBI':
                    cat_value = proj.get('RBI', 0)
                elif cat == 'R':
                    cat_value = proj.get('R', 0)
                elif cat == 'K':
                    cat_value = proj.get('K', 0)
                elif cat == 'SV+HLD':
                    cat_value = proj.get('SV', 0) + proj.get('HD', 0)
                elif cat == 'QS':
                    cat_value = proj.get('QS', 0)

                if cat_value > 0:
                    cat_targets.append({
                        'name': player.name,
                        'team': other_team_name,
                        'value': value,
                        'cat_value': cat_value,
                        'age': player.age
                    })

        # Sort by category value and take top targets
        cat_targets.sort(key=lambda x: x['cat_value'], reverse=True)
        targets[cat] = cat_targets[:num_targets]

    return targets


def scan_league_for_opportunities(team_name):
    """
    League-wide scout report: identify the best opportunities across all teams.
    Returns structured analysis of what's available and who might be selling.
    """
    report = {
        'rebuilding_teams': [],
        'fire_sale_candidates': [],
        'prospect_rich_teams': [],
        'veteran_heavy_teams': [],
        'category_leaders': {},
        'trade_market_summary': ""
    }

    _, power_rankings, _ = get_team_rankings()
    team_cats, rankings = calculate_league_category_rankings()

    # Analyze each team
    for other_team_name, other_team in teams.items():
        if other_team_name == team_name:
            continue

        other_rank = power_rankings.get(other_team_name, 6)
        ages = [p.age for p in other_team.players if p.age > 0]
        avg_age = sum(ages) / len(ages) if ages else 28
        prospect_count = len([p for p in other_team.players if p.is_prospect])
        veteran_count = len([a for a in ages if a >= 30])

        # Rebuilding teams (likely sellers)
        if other_rank >= 9:
            sellable = []
            for p in other_team.players:
                v = calculator.calculate_player_value(p)
                if p.age >= 27 and v >= 35:
                    sellable.append((p.name, v, p.age))
            if sellable:
                sellable.sort(key=lambda x: x[1], reverse=True)
                report['rebuilding_teams'].append({
                    'team': other_team_name,
                    'rank': other_rank,
                    'sellable_assets': sellable[:3]
                })

        # Prospect-rich teams (trade targets for contenders)
        if prospect_count >= 8:
            top_prospects = sorted(
                [p for p in other_team.players if p.is_prospect and p.prospect_rank],
                key=lambda x: x.prospect_rank
            )[:3]
            report['prospect_rich_teams'].append({
                'team': other_team_name,
                'count': prospect_count,
                'top_prospects': [(p.name, p.prospect_rank) for p in top_prospects]
            })

        # Veteran-heavy teams (win-now mode, might overpay)
        if veteran_count >= 10 and other_rank <= 6:
            report['veteran_heavy_teams'].append({
                'team': other_team_name,
                'veteran_count': veteran_count,
                'avg_age': avg_age,
                'rank': other_rank
            })

    # Category leaders (who has the assets you might want)
    for cat in ['HR', 'SB', 'K', 'SV+HLD', 'QS']:
        cat_leaders = []
        for other_team_name in teams:
            if other_team_name == team_name:
                continue
            cat_rank = rankings.get(other_team_name, {}).get(cat, 12)
            if cat_rank <= 3:
                cat_leaders.append((other_team_name, cat_rank))
        if cat_leaders:
            report['category_leaders'][cat] = sorted(cat_leaders, key=lambda x: x[1])

    # Generate summary
    summary_parts = []
    if report['rebuilding_teams']:
        sellers = ", ".join([t['team'] for t in report['rebuilding_teams'][:3]])
        summary_parts.append(f"Sellers: {sellers}")
    if report['veteran_heavy_teams']:
        buyers = ", ".join([t['team'] for t in report['veteran_heavy_teams'][:2]])
        summary_parts.append(f"Buyers: {buyers}")
    if report['prospect_rich_teams']:
        farms = ", ".join([f"{t['team']} ({t['count']})" for t in report['prospect_rich_teams'][:2]])
        summary_parts.append(f"Deep farms: {farms}")

    report['trade_market_summary'] = " | ".join(summary_parts) if summary_parts else "Market is quiet"

    return report


def find_similar_value_players(team_name, player_value, tolerance=8):
    """Find players from other teams with similar dynasty value for trade ideas."""
    similar = []

    for other_team_name, other_team in teams.items():
        if other_team_name == team_name:
            continue

        for player in other_team.players:
            value = calculator.calculate_player_value(player)
            if abs(value - player_value) <= tolerance:
                similar.append({
                    'name': player.name,
                    'team': other_team_name,
                    'value': round(value, 1),
                    'age': player.age,
                    'position': player.position
                })

    return similar


def get_trade_package_suggestions(team_name, team, target_value, weak_cats):
    """Suggest players from the team that could be packaged to acquire targets."""
    players_with_value = [(p, calculator.calculate_player_value(p)) for p in team.players]
    players_with_value.sort(key=lambda x: x[1], reverse=True)

    # Find tradeable assets (not the top 3-5 core players unless rebuilding)
    tradeable = []
    for i, (p, v) in enumerate(players_with_value):
        # Skip top 5 core players
        if i < 5 and v > 50:
            continue
        # Include players with decent value that don't fill weak categories
        if v >= 15:
            tradeable.append({'name': p.name, 'value': round(v, 1), 'age': p.age})

    return tradeable[:8]


def get_draft_recommendations(team_name, draft_pick, weak_positions, weak_categories):
    """Generate detailed, personalized draft pick recommendations based on team context."""
    recommendations = []

    # Get team's competitive window for context
    _, power_rankings, _ = get_team_rankings()
    power_rank = power_rankings.get(team_name, 6)
    is_contender = power_rank <= 4
    is_rebuilding = power_rank >= 9

    # General tier guidance based on pick number
    if draft_pick <= 3:
        tier = "elite"
        pick_context = f"<b>Pick #{draft_pick} - Elite Tier:</b> You're selecting in the top 3. Best Player Available (BPA) is the only strategy here — elite talent trumps positional need every time."
        if is_contender:
            pick_context += " As a contender, target MLB-ready talent who can contribute immediately."
        elif is_rebuilding:
            pick_context += " As a rebuilder, prioritize ceiling and youth — the best 21-year-old prospect available."
    elif draft_pick <= 6:
        tier = "high"
        pick_context = f"<b>Pick #{draft_pick} - High Tier:</b> Strong draft position. Still prioritize BPA, but can factor in positional need if two players are close in value."
        if is_contender:
            pick_context += " Look for immediate impact at a position of need."
        elif is_rebuilding:
            pick_context += " Target high-ceiling prospects who project as future stars."
    elif draft_pick <= 9:
        tier = "mid"
        pick_context = f"<b>Pick #{draft_pick} - Mid Tier:</b> Balance BPA with team needs. The difference between players here is smaller, so fit matters more."
        if weak_positions:
            pick_context += f" Your thin spots ({', '.join(weak_positions[:2])}) should guide your pick."
    else:
        tier = "late"
        pick_context = f"<b>Pick #{draft_pick} - Value Hunting:</b> At this pick, target specific needs and high-upside gambles. Look for undervalued players who fit your roster holes."

    recommendations.append(pick_context)

    # Position-specific advice with more detail
    if weak_positions:
        pos_advice = f"<b>Positional Needs:</b> "
        pos_details = []
        if 'C' in weak_positions:
            pos_details.append("C (premium position — quality catchers are RARE in dynasty)")
        if 'SS' in weak_positions:
            pos_details.append("SS (elite SS combine power + speed — prioritize young options)")
        if '2B' in weak_positions:
            pos_details.append("2B (middle infield depth is valuable for flexibility)")
        if '3B' in weak_positions:
            pos_details.append("3B (corner power is replaceable — don't reach)")
        if 'OF' in weak_positions:
            pos_details.append("OF (deepest position — many options available)")
        if 'SP' in weak_positions:
            pos_details.append("SP (aces are difference-makers — elite SP is worth reaching for)")
        if 'RP' in weak_positions:
            pos_details.append("RP (volatile — don't draft closers early, find them on waivers)")

        if pos_details:
            pos_advice += ", ".join(pos_details[:3])
            recommendations.append(pos_advice)

    # Category-specific advice with detail
    if weak_categories:
        cat_names = [c if isinstance(c, str) else c[0] for c in weak_categories[:3]]
        cat_advice = f"<b>Category Targets:</b> "
        cat_details = []

        if 'SB' in cat_names:
            cat_details.append("SB (speed is scarce — elite base stealers are PREMIUM assets)")
        if 'HR' in cat_names:
            cat_details.append("HR (power is more available but young power bats are gold)")
        if 'K' in cat_names:
            cat_details.append("K (high-K arms anchor rotations — target 200+ K upside)")
        if 'QS' in cat_names:
            cat_details.append("QS (workload matters — target durable innings eaters)")
        if 'SV+HLD' in cat_names:
            cat_details.append("SV+HLD (don't overdraft relievers — role volatility is real)")
        if 'SO' in cat_names:
            cat_details.append("SO (contact hitters help — look for low-K bats)")
        if 'K/BB' in cat_names:
            cat_details.append("K/BB (elite command = elite pitchers — target sub-2.0 BB/9)")

        if cat_details:
            cat_advice += " | ".join(cat_details[:3])
            recommendations.append(cat_advice)

    # Window-specific final advice
    if is_contender:
        window_advice = "<b>Contender Strategy:</b> Balance win-now pieces with future value. An MLB-ready player who fills a need > a better prospect who won't contribute for 2 years."
    elif is_rebuilding:
        window_advice = "<b>Rebuilder Strategy:</b> Youth and ceiling over floor. Target the youngest, highest-upside player available. Avoid 28+ year olds even if they're 'better' now."
    else:
        window_advice = "<b>Middle-Tier Strategy:</b> Use this draft to push toward contention OR accelerate a rebuild. Pick a direction and draft accordingly."

    recommendations.append(window_advice)

    return recommendations


def get_buy_low_sell_high_alerts(team_name, team):
    """
    Personalized buy-low/sell-high analysis based on YOUR team's specific needs.
    Prioritizes: 1) Category fit 2) Skills you need 3) Value opportunities
    """
    alerts = {'buy_low': [], 'sell_high': [], 'category_targets': {}}

    # Get YOUR team's specific weaknesses - this drives personalization
    team_cats, rankings = calculate_league_category_rankings()
    my_ranks = rankings.get(team_name, {})

    # Sorted by rank (worst first) - these are YOUR priorities
    weak_cats = sorted([(cat, rank) for cat, rank in my_ranks.items() if rank >= 8],
                       key=lambda x: -x[1])[:4]
    weak_cat_names = [c[0] for c in weak_cats]

    strong_cats = [cat for cat, rank in my_ranks.items() if rank <= 4]

    # Get team's competitive window
    _, power_rankings, _ = get_team_rankings()
    my_power_rank = power_rankings.get(team_name, 6)
    is_contender = my_power_rank <= 4
    is_rebuilding = my_power_rank >= 9

    # ============ SELL-HIGH ANALYSIS (Your Team) ============
    players_with_value = [(p, calculator.calculate_player_value(p)) for p in team.players]
    players_with_value.sort(key=lambda x: x[1], reverse=True)

    for p, v in players_with_value:
        proj_h = HITTER_PROJECTIONS.get(p.name, {})
        proj_p = PITCHER_PROJECTIONS.get(p.name, {}) or RELIEVER_PROJECTIONS.get(p.name, {})

        # Aging veterans - more aggressive if rebuilding
        age_threshold = 31 if is_rebuilding else 33
        value_threshold = 30 if is_rebuilding else 40

        if p.age >= age_threshold and v >= value_threshold:
            urgency = 'critical' if p.age >= 34 else 'high' if p.age >= 32 else 'medium'
            alerts['sell_high'].append({
                'name': p.name,
                'reason': f"Age {p.age}, {v:.0f} value — maximize return now",
                'urgency': urgency,
                'value': v
            })
        # Pitchers age faster
        elif p.age >= 30 and v >= 45 and proj_p:
            alerts['sell_high'].append({
                'name': p.name,
                'reason': f"Age {p.age} pitcher — arm wear concern",
                'urgency': 'medium',
                'value': v
            })
        # Players contributing to categories you're STRONG in (surplus)
        elif strong_cats and v >= 35:
            surplus_cat = None
            if 'HR' in strong_cats and proj_h and proj_h.get('HR', 0) >= 25:
                surplus_cat = f"HR surplus ({proj_h.get('HR', 0)} HR)"
            elif 'SB' in strong_cats and proj_h and proj_h.get('SB', 0) >= 20:
                surplus_cat = f"SB surplus ({proj_h.get('SB', 0)} SB)"
            elif 'K' in strong_cats and proj_p and proj_p.get('K', 0) >= 150:
                surplus_cat = f"K surplus ({proj_p.get('K', 0)} K)"
            if surplus_cat:
                alerts['sell_high'].append({
                    'name': p.name,
                    'reason': f"{surplus_cat} — trade from strength",
                    'urgency': 'opportunity',
                    'value': v
                })

    # ============ BUY-LOW ANALYSIS - PERSONALIZED BY CATEGORY NEED ============
    # First, find best targets for EACH weak category
    category_best = {cat: [] for cat, _ in weak_cats}

    for other_team_name, other_team in teams.items():
        if other_team_name == team_name:
            continue

        other_power_rank = power_rankings.get(other_team_name, 6)
        is_seller = other_power_rank >= 9  # Rebuilding team = motivated seller

        for p in other_team.players:
            v = calculator.calculate_player_value(p)
            proj_h = HITTER_PROJECTIONS.get(p.name, {})
            proj_p = PITCHER_PROJECTIONS.get(p.name, {}) or RELIEVER_PROJECTIONS.get(p.name, {})

            # Skip if no projections (pure prospects handled separately)
            if not proj_h and not proj_p and not (p.is_prospect and p.prospect_rank):
                continue

            # Score player for each weak category YOUR team needs
            for cat, cat_rank in weak_cats:
                cat_contribution = 0
                reason = ""

                if cat == 'HR' and proj_h:
                    hr = proj_h.get('HR', 0)
                    if hr >= 15:
                        cat_contribution = hr
                        reason = f"{hr} HR projected"
                elif cat == 'SB' and proj_h:
                    sb = proj_h.get('SB', 0)
                    if sb >= 10:
                        cat_contribution = sb * 2  # SB is scarcer, weight higher
                        reason = f"{sb} SB projected"
                elif cat == 'RBI' and proj_h:
                    rbi = proj_h.get('RBI', 0)
                    if rbi >= 50:
                        cat_contribution = rbi / 3
                        reason = f"{rbi} RBI projected"
                elif cat == 'R' and proj_h:
                    r = proj_h.get('R', 0)
                    if r >= 50:
                        cat_contribution = r / 3
                        reason = f"{r} R projected"
                elif cat == 'K' and proj_p:
                    k = proj_p.get('K', 0)
                    if k >= 80:
                        cat_contribution = k / 5
                        reason = f"{k} K projected"
                elif cat == 'QS' and proj_p:
                    qs = proj_p.get('QS', 0)
                    if qs >= 8:
                        cat_contribution = qs * 3
                        reason = f"{qs} QS projected"
                elif cat == 'SV+HLD' and proj_p:
                    svh = proj_p.get('SV', 0) + proj_p.get('HD', 0)
                    if svh >= 15:
                        cat_contribution = svh
                        reason = f"{svh} SV+HLD projected"
                elif cat == 'ERA' and proj_p:
                    era = proj_p.get('ERA', 5)
                    ip = proj_p.get('IP', 0)
                    if era <= 3.50 and ip >= 100:
                        cat_contribution = (4.50 - era) * 20
                        reason = f"{era:.2f} ERA over {ip:.0f} IP"
                elif cat == 'WHIP' and proj_p:
                    whip = proj_p.get('WHIP', 1.5)
                    ip = proj_p.get('IP', 0)
                    if whip <= 1.15 and ip >= 100:
                        cat_contribution = (1.40 - whip) * 50
                        reason = f"{whip:.2f} WHIP"
                elif cat == 'SO' and proj_h:  # Lower is better - look for low SO hitters
                    so = proj_h.get('SO', 150)
                    ab = proj_h.get('AB', 400)
                    if ab >= 300 and so <= 100:
                        cat_contribution = (150 - so) / 3
                        reason = f"Only {so} SO in {ab} AB"
                elif cat == 'L' and proj_p:  # Lower is better - look for low loss pitchers
                    losses = proj_p.get('L', 10)
                    ip = proj_p.get('IP', 0)
                    if ip >= 100 and losses <= 8:
                        cat_contribution = (12 - losses) * 4
                        reason = f"Only {losses} L over {ip:.0f} IP"
                elif cat == 'K/BB' and proj_p:  # Higher is better - elite command
                    k = proj_p.get('K', 0)
                    bb = proj_p.get('BB', 50)
                    ip = proj_p.get('IP', 0)
                    if ip >= 80 and bb > 0:
                        k_bb = k / bb
                        if k_bb >= 3.5:
                            cat_contribution = k_bb * 8
                            reason = f"{k_bb:.2f} K/BB ({k} K, {bb} BB)"

                if cat_contribution > 0:
                    # Bonus for age (younger = more valuable in dynasty)
                    age_bonus = max(0, (28 - p.age) * 2) if p.age > 0 else 0
                    # Bonus for motivated seller
                    seller_bonus = 10 if is_seller else 0

                    score = cat_contribution + age_bonus + seller_bonus

                    category_best[cat].append({
                        'name': p.name,
                        'team': other_team_name,
                        'reason': reason,
                        'cat': cat,
                        'score': score,
                        'value': v,
                        'age': p.age,
                        'is_seller': is_seller
                    })

    # Sort each category's targets and take best
    for cat in category_best:
        category_best[cat].sort(key=lambda x: -x['score'])
        category_best[cat] = category_best[cat][:5]

    alerts['category_targets'] = category_best

    # Build final buy-low list - mix of category targets + value plays
    seen_players = set()

    # First: Add top target from each weak category (personalized!)
    for cat, _ in weak_cats[:3]:  # Top 3 weaknesses
        if category_best.get(cat):
            for target in category_best[cat][:2]:  # Top 2 per category
                if target['name'] not in seen_players:
                    seen_players.add(target['name'])
                    seller_note = " (motivated seller)" if target['is_seller'] else ""
                    alerts['buy_low'].append({
                        'name': target['name'],
                        'team': target['team'],
                        'reason': f"Fills {cat} need: {target['reason']}{seller_note}",
                        'priority': 1,  # Category fit = highest priority
                        'value': target['value'],
                        'age': target['age'],
                        'category': cat
                    })

    # Second: Add value opportunities (young, undervalued, on selling teams)
    for other_team_name, other_team in teams.items():
        if other_team_name == team_name:
            continue

        other_power_rank = power_rankings.get(other_team_name, 6)
        is_seller = other_power_rank >= 9

        for p in other_team.players:
            if p.name in seen_players:
                continue

            v = calculator.calculate_player_value(p)
            proj_h = HITTER_PROJECTIONS.get(p.name, {})
            proj_p = PITCHER_PROJECTIONS.get(p.name, {}) or RELIEVER_PROJECTIONS.get(p.name, {})

            # Young breakout candidates
            if p.age <= 25 and v >= 30 and v <= 55 and (proj_h or proj_p):
                seen_players.add(p.name)
                alerts['buy_low'].append({
                    'name': p.name,
                    'team': other_team_name,
                    'reason': f"Age {p.age} breakout candidate at {v:.0f} value",
                    'priority': 2,
                    'value': v,
                    'age': p.age,
                    'category': 'upside'
                })
            # Veterans on rebuilding teams (fire sale)
            elif is_seller and p.age >= 27 and p.age <= 32 and v >= 45:
                seen_players.add(p.name)
                alerts['buy_low'].append({
                    'name': p.name,
                    'team': other_team_name,
                    'reason': f"Prime veteran ({v:.0f} value) on selling team",
                    'priority': 3,
                    'value': v,
                    'age': p.age,
                    'category': 'value'
                })
            # Top prospects (still include but lower priority)
            elif p.is_prospect and p.prospect_rank and p.prospect_rank <= 50:
                seen_players.add(p.name)
                alerts['buy_low'].append({
                    'name': p.name,
                    'team': other_team_name,
                    'reason': f"Top {p.prospect_rank} dynasty prospect",
                    'priority': 4,
                    'value': v,
                    'age': p.age,
                    'category': 'prospect'
                })

    # Sort by priority (category fit first) then value
    alerts['buy_low'].sort(key=lambda x: (x['priority'], -x['value']))
    alerts['buy_low'] = alerts['buy_low'][:12]

    # Sort sell-high
    urgency_order = {'critical': 0, 'high': 1, 'medium': 2, 'opportunity': 3}
    alerts['sell_high'].sort(key=lambda x: (urgency_order.get(x['urgency'], 4), -x['value']))
    alerts['sell_high'] = alerts['sell_high'][:6]

    return alerts


def generate_gm_trade_scenarios(team_name, team):
    """
    Generate personalized, actionable trade scenarios based on YOUR team's specific situation.
    Scenarios differ based on competitive window, category needs, and roster composition.
    Now includes specific multi-player packages and counter-offer suggestions.
    """
    scenarios = []

    players_with_value = [(p, calculator.calculate_player_value(p)) for p in team.players]
    players_with_value.sort(key=lambda x: x[1], reverse=True)

    # Get team context
    team_cats, rankings = calculate_league_category_rankings()
    my_ranks = rankings.get(team_name, {})
    _, power_rankings, _ = get_team_rankings()
    my_power_rank = power_rankings.get(team_name, 6)

    # Determine competitive window
    is_contender = my_power_rank <= 4
    is_middle = 5 <= my_power_rank <= 8
    is_rebuilding = my_power_rank >= 9

    # Sorted category weaknesses and strengths
    weak_cats = sorted([(cat, rank) for cat, rank in my_ranks.items() if rank >= 8],
                       key=lambda x: -x[1])[:3]
    strong_cats = [(cat, rank) for cat, rank in my_ranks.items() if rank <= 4]

    # Team demographics
    ages = [p.age for p in team.players if p.age > 0]
    avg_age = sum(ages) / len(ages) if ages else 28
    prospects = [p for p in team.players if p.is_prospect and p.prospect_rank]
    veterans = [(p, v) for p, v in players_with_value if p.age >= 30 and v >= 35]
    young_stars = [(p, v) for p, v in players_with_value if p.age <= 26 and v >= 45]
    declining_vets = [(p, v) for p, v in players_with_value if p.age >= 32 and v >= 30]

    # Find tradeable assets
    tradeable = [(p, v) for i, (p, v) in enumerate(players_with_value) if i >= 4 and v >= 20]

    # Find positions of strength/weakness
    pos_counts = {}
    pos_values = {}  # Track value at each position
    for p, v in players_with_value:
        pos = p.position.split('/')[0].split(',')[0].upper() if p.position else 'UTIL'
        if pos in ['LF', 'CF', 'RF']:
            pos = 'OF'
        pos_counts[pos] = pos_counts.get(pos, 0) + 1
        if pos not in pos_values:
            pos_values[pos] = []
        pos_values[pos].append((p, v))
    surplus_positions = [pos for pos, count in pos_counts.items() if count >= 4]
    thin_positions = [pos for pos, count in pos_counts.items() if count <= 1 and pos not in ['UTIL', 'DH', '']]

    # Helper function to find trade partners for specific needs
    def find_trade_targets(target_cat, value_range=(30, 70), prefer_sellers=True):
        """Find specific players from other teams that address our category need."""
        targets = []
        for other_team_name, other_team in teams.items():
            if other_team_name == team_name:
                continue
            other_rank = power_rankings.get(other_team_name, 6)
            is_seller = other_rank >= 8

            for p in other_team.players:
                proj_h = HITTER_PROJECTIONS.get(p.name, {})
                proj_p = PITCHER_PROJECTIONS.get(p.name, {}) or RELIEVER_PROJECTIONS.get(p.name, {})
                cat_value = 0

                if target_cat in ['HR', 'RBI', 'R', 'SB', 'AVG', 'OPS'] and proj_h:
                    cat_value = proj_h.get(target_cat, 0)
                elif target_cat == 'K' and proj_p:
                    cat_value = proj_p.get('K', 0)
                elif target_cat == 'QS' and proj_p:
                    cat_value = proj_p.get('QS', 0)
                elif target_cat == 'SV+HLD' and proj_p:
                    cat_value = proj_p.get('SV', 0) + proj_p.get('HD', 0)
                elif target_cat == 'ERA' and proj_p:
                    cat_value = 5.0 - proj_p.get('ERA', 5.0)  # Invert so lower is better
                elif target_cat == 'WHIP' and proj_p:
                    cat_value = 2.0 - proj_p.get('WHIP', 1.5)  # Invert

                if cat_value > 0:
                    pv = calculator.calculate_player_value(p)
                    if value_range[0] <= pv <= value_range[1]:
                        targets.append({
                            'player': p,
                            'team': other_team_name,
                            'value': pv,
                            'cat_value': cat_value,
                            'is_seller': is_seller,
                            'age': p.age,
                        })

        # Sort by category value, prefer sellers if requested
        targets.sort(key=lambda x: (x['is_seller'] if prefer_sellers else 0, x['cat_value']), reverse=True)
        return targets[:5]

    # Helper function to build multi-player package
    def build_trade_package(target_value, prefer_prospects=False, max_players=3):
        """Build a package of players to match target value."""
        package = []
        remaining = target_value

        candidates = tradeable.copy()
        if prefer_prospects:
            candidates.sort(key=lambda x: (x[0].is_prospect, x[1]), reverse=True)
        else:
            candidates.sort(key=lambda x: x[1], reverse=True)

        for p, v in candidates:
            if len(package) >= max_players:
                break
            if v <= remaining * 1.2 and v >= remaining * 0.3:  # Reasonable fit
                package.append((p, v))
                remaining -= v
                if remaining <= target_value * 0.1:  # Close enough
                    break

        return package

    # ============ CONTENDER SCENARIOS ============
    if is_contender:
        # Scenario 1: Push for championship - address biggest weakness with specific target
        if weak_cats:
            target_cat, cat_rank = weak_cats[0]
            targets = find_trade_targets(target_cat, (35, 65), prefer_sellers=True)

            if targets:
                best = targets[0]
                target_value = best['value']

                # Build a specific package
                package = build_trade_package(target_value, prefer_prospects=True)

                if package:
                    offer_str = " + ".join([f"{p.name} ({v:.0f})" for p, v in package])
                    package_value = sum(v for p, v in package)
                    prospect_count = sum(1 for p, v in package if p.is_prospect)

                    seller_note = " MOTIVATED SELLER" if best['is_seller'] else ""
                    negotiation_tip = ""
                    if package_value < target_value * 0.9:
                        negotiation_tip = f"\nCounter-offer tip: May need to add a 2nd Rd pick or low prospect to close."
                    elif package_value > target_value * 1.1:
                        negotiation_tip = f"\nCounter-offer tip: You're overpaying - try removing one piece or ask for a pick back."

                    scenarios.append({
                        'title': f"Championship Push: Fix {target_cat}",
                        'target': f"{best['player'].name} ({best['team']}){seller_note}",
                        'target_value': target_value,
                        'target_stats': f"{best['cat_value']:.0f} {target_cat} projected",
                        'offer': offer_str,
                        'offer_value': package_value,
                        'package_details': [(p.name, round(v, 1), p.is_prospect) for p, v in package],
                        'reasoning': f"You're #{my_power_rank} but rank #{cat_rank} in {target_cat}. {best['player'].name} projects for {best['cat_value']:.0f} {target_cat}.{negotiation_tip}",
                        'trade_type': 'buy',
                        'urgency': 'high'
                    })

        # Scenario 2: Add second ace / closer for playoff push
        pitchers_needed = 'K' in [c for c, r in weak_cats] or 'QS' in [c for c, r in weak_cats]
        if pitchers_needed:
            targets = find_trade_targets('QS', (40, 75), prefer_sellers=True)
            if targets and len(scenarios) < 2:
                best = targets[0]
                package = build_trade_package(best['value'], prefer_prospects=True)
                if package:
                    offer_str = " + ".join([f"{p.name} ({v:.0f})" for p, v in package])
                    scenarios.append({
                        'title': "Playoff Rotation: Add an Ace",
                        'target': f"{best['player'].name} ({best['team']})",
                        'target_value': best['value'],
                        'target_stats': f"{best['cat_value']:.0f} QS projected",
                        'offer': offer_str,
                        'offer_value': sum(v for p, v in package),
                        'reasoning': f"Contenders need pitching depth for playoff rotation. {best['player'].name} can be your #2/#3 starter.",
                        'trade_type': 'buy',
                        'urgency': 'medium'
                    })

    # ============ REBUILDING SCENARIOS ============
    elif is_rebuilding:
        # Scenario 1: Sell declining veteran to contender
        if declining_vets:
            best_vet = declining_vets[0]
            # Find contending team with prospects to trade
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                other_rank = power_rankings.get(other_team_name, 6)
                if other_rank <= 5:  # Contending team
                    their_prospects = sorted(
                        [p for p in other_team.players if p.is_prospect and p.prospect_rank],
                        key=lambda x: x.prospect_rank
                    )
                    their_young = [(p, calculator.calculate_player_value(p)) for p in other_team.players
                                  if p.age <= 26 and not p.is_prospect]
                    their_young.sort(key=lambda x: x[1], reverse=True)

                    if their_prospects or their_young:
                        # Build what we want from them
                        ask_parts = []
                        ask_value = 0
                        if their_prospects:
                            ask_parts.append(f"{their_prospects[0].name} (#{their_prospects[0].prospect_rank})")
                            ask_value += calculator.calculate_player_value(their_prospects[0])
                        if their_young and ask_value < best_vet[1] * 0.8:
                            ask_parts.append(f"{their_young[0][0].name} ({their_young[0][1]:.0f})")
                            ask_value += their_young[0][1]

                        # Add pick suggestion if value gap
                        pick_suggestion = ""
                        if best_vet[1] > ask_value + 10:
                            pick_suggestion = " + 2nd Rd pick"
                        elif best_vet[1] > ask_value + 5:
                            pick_suggestion = " + 3rd Rd pick"

                        scenarios.append({
                            'title': "Rebuild Fuel: Sell Veteran to Contender",
                            'target': " + ".join(ask_parts) + pick_suggestion,
                            'target_value': ask_value,
                            'offer': f"{best_vet[0].name} ({best_vet[1]:.0f} value, age {best_vet[0].age})",
                            'offer_value': best_vet[1],
                            'reasoning': f"{other_team_name} is #{other_rank} and pushing for a title. {best_vet[0].name}'s value peaks NOW - sell before decline.\nNegotiation: Ask for their best prospect + a young player. They're desperate.",
                            'trade_type': 'sell',
                            'urgency': 'high'
                        })
                        break

        # Scenario 2: Consolidate prospects into elite prospect
        if len(prospects) >= 4:
            lower_prospects = sorted(prospects, key=lambda x: x.prospect_rank, reverse=True)[:2]
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                elite_prospects = [p for p in other_team.players
                                  if p.is_prospect and p.prospect_rank and p.prospect_rank <= 25]
                if elite_prospects:
                    target = elite_prospects[0]
                    target_value = calculator.calculate_player_value(target)
                    offer_value = sum(calculator.calculate_player_value(p) for p in lower_prospects)
                    offer_names = " + ".join([f"{p.name} (#{p.prospect_rank})" for p in lower_prospects])

                    # Value gap analysis
                    gap_note = ""
                    if offer_value < target_value * 0.85:
                        gap_note = f"\nMay need to add: 2nd Rd pick or another piece to close {target_value - offer_value:.0f} pt gap"
                    elif offer_value > target_value * 1.1:
                        gap_note = f"\nAsk for a pick back - you're overpaying"

                    scenarios.append({
                        'title': "Prospect Upgrade: Quality > Quantity",
                        'target': f"{target.name} (#{target.prospect_rank} from {other_team_name})",
                        'target_value': target_value,
                        'offer': offer_names,
                        'offer_value': offer_value,
                        'reasoning': f"You have {len(prospects)} prospects but none elite. {target.name} is a cornerstone to build around.{gap_note}",
                        'trade_type': 'consolidate',
                        'urgency': 'medium'
                    })
                    break

        # Scenario 3: Acquire draft picks
        if veterans and len(scenarios) < 2:
            sellable = [(p, v) for p, v in veterans if v >= 30]
            if sellable:
                vet = sellable[0]
                # Value to picks conversion
                picks_estimate = []
                remaining_value = vet[1]
                if remaining_value >= 30:
                    picks_estimate.append("1st Rd")
                    remaining_value -= 30
                if remaining_value >= 18:
                    picks_estimate.append("2nd Rd")
                    remaining_value -= 18
                if remaining_value >= 8:
                    picks_estimate.append("3rd Rd")

                scenarios.append({
                    'title': "Stockpile Picks: Future Draft Capital",
                    'target': " + ".join(picks_estimate) + " picks",
                    'target_value': vet[1] * 0.9,
                    'offer': f"{vet[0].name} ({vet[1]:.0f} value)",
                    'offer_value': vet[1],
                    'reasoning': f"Draft picks = lottery tickets. {vet[0].name} at age {vet[0].age} won't be part of your next contention window. Convert to picks.",
                    'trade_type': 'sell',
                    'urgency': 'medium'
                })

    # ============ MIDDLE TIER SCENARIOS ============
    elif is_middle:
        # Scenario 1: Pick a direction - analyze which way to lean
        if avg_age >= 28 and veterans:
            best_vet = veterans[0]

            # Find contender to sell to
            buyer_team = None
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                if power_rankings.get(other_team_name, 6) <= 4:
                    buyer_team = other_team_name
                    break

            if buyer_team:
                scenarios.append({
                    'title': "Crossroads: Commit to Rebuild",
                    'target': f"Prospects + picks from {buyer_team}",
                    'target_value': best_vet[1] * 0.9,
                    'offer': f"{best_vet[0].name} ({best_vet[1]:.0f} value, age {best_vet[0].age})",
                    'offer_value': best_vet[1],
                    'reasoning': f"Ranked #{my_power_rank} with avg age {avg_age:.1f}. Not good enough to win, too old to wait. Sell {best_vet[0].name} to {buyer_team} and restart.\nDecision time: Commit to rebuild NOW or risk being stuck in the middle forever.",
                    'trade_type': 'sell',
                    'urgency': 'high'
                })

        elif young_stars:
            star = young_stars[0]
            # Find what category they help and what we need
            if weak_cats:
                target_cat = weak_cats[0][0]
                targets = find_trade_targets(target_cat, (35, 55), prefer_sellers=False)
                if targets:
                    best = targets[0]
                    scenarios.append({
                        'title': "Accelerate: Build Around Your Star",
                        'target': f"{best['player'].name} ({best['team']})",
                        'target_value': best['value'],
                        'target_stats': f"Addresses your {target_cat} weakness",
                        'offer': "Prospects or depth pieces",
                        'offer_value': best['value'] * 0.9,
                        'reasoning': f"Ranked #{my_power_rank} with {star[0].name} as cornerstone (age {star[0].age}). Add {best['player'].name} to accelerate your window.\nYour star's prime is coming - don't waste it.",
                        'trade_type': 'buy',
                        'urgency': 'medium'
                    })

    # ============ UNIVERSAL SCENARIOS ============
    # Positional surplus trade (works for any team)
    if surplus_positions and weak_cats and len(scenarios) < 3:
        surplus_pos = surplus_positions[0]
        surplus_players = [(p, v) for p, v in players_with_value
                          if surplus_pos in (p.position or '').upper() and v >= 25]
        if len(surplus_players) >= 2:
            trade_piece = surplus_players[1]  # Not your best at position
            target_cat, target_rank = weak_cats[0]

            # Find specific target
            targets = find_trade_targets(target_cat, (trade_piece[1] * 0.7, trade_piece[1] * 1.3))
            if targets:
                best = targets[0]
                scenarios.append({
                    'title': f"Rebalance: {surplus_pos} Depth → {target_cat}",
                    'target': f"{best['player'].name} ({best['team']})",
                    'target_value': best['value'],
                    'target_stats': f"{best['cat_value']:.0f} {target_cat}",
                    'offer': f"{trade_piece[0].name} ({trade_piece[1]:.0f})",
                    'offer_value': trade_piece[1],
                    'reasoning': f"You have {pos_counts.get(surplus_pos, 0)} {surplus_pos} but rank #{target_rank} in {target_cat}. {best['player'].name} directly addresses your need.",
                    'trade_type': 'rebalance',
                    'urgency': 'low'
                })

    # Category strength trade (leverage what you're good at)
    if strong_cats and weak_cats and len(scenarios) < 4:
        strong_cat, strong_rank = strong_cats[0]
        weak_cat, weak_rank = weak_cats[0]

        # Find a player contributing to your strength that you could trade
        strength_players = []
        for p, v in tradeable:
            proj_h = HITTER_PROJECTIONS.get(p.name, {})
            proj_p = PITCHER_PROJECTIONS.get(p.name, {}) or RELIEVER_PROJECTIONS.get(p.name, {})

            contribution = 0
            if strong_cat in ['HR', 'RBI', 'R', 'SB'] and proj_h:
                contribution = proj_h.get(strong_cat, 0)
            elif strong_cat == 'K' and proj_p:
                contribution = proj_p.get('K', 0)
            elif strong_cat == 'SV+HLD' and proj_p:
                contribution = proj_p.get('SV', 0) + proj_p.get('HD', 0)

            if contribution > 0:
                strength_players.append((p, v, contribution))

        if strength_players:
            strength_players.sort(key=lambda x: x[2], reverse=True)
            trade_piece = strength_players[0]

            # Find target for weak category
            targets = find_trade_targets(weak_cat, (trade_piece[1] * 0.7, trade_piece[1] * 1.3))
            if targets:
                best = targets[0]
                scenarios.append({
                    'title': f"Trade Strength: {strong_cat} → {weak_cat}",
                    'target': f"{best['player'].name} ({best['team']})",
                    'target_value': best['value'],
                    'target_stats': f"Adds {best['cat_value']:.0f} {weak_cat}",
                    'offer': f"{trade_piece[0].name} ({trade_piece[1]:.0f}, {trade_piece[2]:.0f} {strong_cat})",
                    'offer_value': trade_piece[1],
                    'reasoning': f"You're #{strong_rank} in {strong_cat} (surplus) but #{weak_rank} in {weak_cat}. This is textbook roster optimization.",
                    'trade_type': 'rebalance',
                    'urgency': 'medium'
                })

    # ============ FALLBACK SCENARIOS - Ensure every team gets at least one ============
    if len(scenarios) == 0:
        # Fallback 1: General category improvement
        if weak_cats:
            target_cat, target_rank = weak_cats[0]
            targets = find_trade_targets(target_cat, (25, 60))
            if targets and tradeable:
                best = targets[0]
                trade_piece = tradeable[0]
                scenarios.append({
                    'title': f"Improve {target_cat}: Target Weakness",
                    'target': f"{best['player'].name} ({best['team']})",
                    'target_value': best['value'],
                    'target_stats': f"{best['cat_value']:.0f} {target_cat} projected",
                    'offer': f"{trade_piece[0].name} ({trade_piece[1]:.0f})",
                    'offer_value': trade_piece[1],
                    'reasoning': f"You rank #{target_rank} in {target_cat}. {best['player'].name} would directly address this gap.",
                    'trade_type': 'improve',
                    'urgency': 'medium'
                })

        # Fallback 2: Buy low on underperformer
        if len(scenarios) < 2:
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                other_rank = power_rankings.get(other_team_name, 6)
                if other_rank >= 8:  # Struggling team
                    their_players = [(p, calculator.calculate_player_value(p)) for p in other_team.players]
                    their_players.sort(key=lambda x: x[1], reverse=True)
                    # Find a quality player they might sell
                    for p, v in their_players[:10]:
                        if 35 <= v <= 55 and p.age <= 28:
                            scenarios.append({
                                'title': "Buy Low Opportunity",
                                'target': f"{p.name} ({other_team_name})",
                                'target_value': v,
                                'target_stats': f"Age {p.age}, {v:.0f} value",
                                'offer': "Prospect + pick package",
                                'offer_value': v * 0.85,
                                'reasoning': f"{other_team_name} is ranked #{other_rank} and may be selling. {p.name} could be available at a discount.",
                                'trade_type': 'buy',
                                'urgency': 'low'
                            })
                            break
                    if len(scenarios) >= 1:
                        break

        # Fallback 3: Depth consolidation
        if len(scenarios) < 2 and len(players_with_value) >= 10:
            # Find two mid-tier players to package
            mid_tier = [(p, v) for p, v in players_with_value[5:15] if 20 <= v <= 40]
            if len(mid_tier) >= 2:
                p1, v1 = mid_tier[0]
                p2, v2 = mid_tier[1]
                combined = v1 + v2
                scenarios.append({
                    'title': "Consolidate Depth: 2-for-1",
                    'target': f"Player valued ~{combined * 0.85:.0f}-{combined:.0f}",
                    'target_value': combined * 0.9,
                    'offer': f"{p1.name} ({v1:.0f}) + {p2.name} ({v2:.0f})",
                    'offer_value': combined,
                    'reasoning': f"Package two depth pieces ({combined:.0f} combined value) for one better player. Consolidating roster spots improves lineup flexibility.",
                    'trade_type': 'consolidate',
                    'urgency': 'low'
                })

    # ============ ABSOLUTE FALLBACK - ALWAYS generates something ============
    if len(scenarios) == 0:
        # Use the team's best tradeable asset to explore options
        if len(players_with_value) >= 6:
            trade_candidate = players_with_value[5]  # 6th best player
            p, v = trade_candidate

            # Find ANY team that might want this player
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                their_players = [(op, calculator.calculate_player_value(op)) for op in other_team.players]
                their_players.sort(key=lambda x: x[1], reverse=True)
                # Find a comparable player
                for op, ov in their_players:
                    if abs(ov - v) <= 10 and op.name != p.name:
                        scenarios.append({
                            'title': "Explore Value Swap",
                            'target': f"{op.name} ({other_team_name})",
                            'target_value': ov,
                            'target_stats': f"Age {op.age}, {op.position}",
                            'offer': f"{p.name} ({v:.0f})",
                            'offer_value': v,
                            'reasoning': f"Straight-up swap of similar value players. Sometimes a change of scenery benefits both teams. {op.name} might fit your roster better.",
                            'trade_type': 'swap',
                            'urgency': 'low'
                        })
                        break
                if scenarios:
                    break

        # If STILL nothing, give generic advice based on rank
        if len(scenarios) == 0:
            if my_power_rank <= 6:
                scenarios.append({
                    'title': "Stay the Course",
                    'target': "Minor upgrades only",
                    'target_value': 0,
                    'offer': "Depth pieces or late picks",
                    'offer_value': 0,
                    'reasoning': f"Ranked #{my_power_rank} with a solid roster. Don't force trades - wait for the right opportunity. Monitor the wire for FA upgrades and be ready if a contender panics.",
                    'trade_type': 'hold',
                    'urgency': 'low'
                })
            else:
                scenarios.append({
                    'title': "Assess Your Assets",
                    'target': "Build trade value",
                    'target_value': 0,
                    'offer': "Identify sellable pieces",
                    'offer_value': 0,
                    'reasoning': f"Ranked #{my_power_rank}. Take inventory of your roster - which players have value to contenders? Shop veterans to teams pushing for titles and accumulate young talent or picks.",
                    'trade_type': 'evaluate',
                    'urgency': 'medium'
                })

    return scenarios[:4]  # Max 4 scenarios


def generate_rivalry_analysis(team_name, rival_name):
    """Generate head-to-head analysis against rival team."""
    if rival_name not in teams:
        return None

    team = teams[team_name]
    rival = teams[rival_name]

    # Calculate total values
    my_value = sum(calculator.calculate_player_value(p) for p in team.players)
    rival_value = sum(calculator.calculate_player_value(p) for p in rival.players)

    # Get category comparisons
    team_cats, rankings = calculate_league_category_rankings()
    my_cats = team_cats.get(team_name, {})
    rival_cats = team_cats.get(rival_name, {})
    my_ranks = rankings.get(team_name, {})
    rival_ranks = rankings.get(rival_name, {})

    # Compare categories
    advantages = []
    disadvantages = []

    for cat in ['HR', 'SB', 'RBI', 'R', 'AVG', 'OPS', 'SO', 'K', 'ERA', 'WHIP', 'QS', 'SV+HLD']:
        my_rank = my_ranks.get(cat, 12)
        rival_rank = rival_ranks.get(cat, 12)

        if my_rank < rival_rank - 1:  # Significant advantage (2+ spots better)
            advantages.append(cat)
        elif rival_rank < my_rank - 1:  # Significant disadvantage
            disadvantages.append(cat)

    # Find top players on each side
    my_top = sorted([(p, calculator.calculate_player_value(p)) for p in team.players], key=lambda x: x[1], reverse=True)[:3]
    rival_top = sorted([(p, calculator.calculate_player_value(p)) for p in rival.players], key=lambda x: x[1], reverse=True)[:3]

    # Count prospects
    my_prospects = len([p for p in team.players if p.is_prospect])
    rival_prospects = len([p for p in rival.players if p.is_prospect])

    # Get historical H2H data
    history = RIVALRY_HISTORY.get(team_name, {})

    return {
        'rival_name': rival_name,
        'my_value': round(my_value, 0),
        'rival_value': round(rival_value, 0),
        'value_diff': round(my_value - rival_value, 0),
        'advantages': advantages,
        'disadvantages': disadvantages,
        'my_top_players': [(p.name, round(v, 1)) for p, v in my_top],
        'rival_top_players': [(p.name, round(v, 1)) for p, v in rival_top],
        'my_prospects': my_prospects,
        'rival_prospects': rival_prospects,
        'my_2025_record': history.get('record', 'N/A'),
        'my_h2h_record': history.get('h2h', 'N/A'),
        'rival_2025_record': history.get('rival_record', 'N/A'),
        'rival_h2h_record': history.get('rival_h2h', 'N/A'),
    }


def generate_team_analysis(team_name, team, players_with_value=None, power_rank=None, total_teams=12):
    """
    Generate comprehensive, personalized GM-level analysis for each team.
    Acts as a dedicated Assistant GM providing strategic insights.
    """
    if players_with_value is None:
        players_with_value = [(p, calculator.calculate_player_value(p)) for p in team.players]
        players_with_value.sort(key=lambda x: x[1], reverse=True)

    if power_rank is None:
        _, power_rankings, _ = get_team_rankings()
        power_rank = power_rankings.get(team_name, 0)

    analysis_parts = []
    total_value = sum(v for _, v in players_with_value)

    # ============ ASSISTANT GM HEADER ============
    import random
    gm = get_assistant_gm(team_name)
    catchphrase = random.choice(gm['catchphrases'])
    gm_header = f"<div style='background: linear-gradient(135deg, rgba(0,212,255,0.15), rgba(255,215,0,0.08)); padding: 16px; border-radius: 10px; margin-bottom: 16px; border-left: 4px solid #00d4ff;'>"
    gm_header += f"<div style='display: flex; align-items: center; gap: 12px;'>"
    gm_header += f"<div style='width: 48px; height: 48px; background: linear-gradient(135deg, #00d4ff, #0099cc); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: bold; color: #1a1a2e;'>{gm['name'][0]}</div>"
    gm_header += f"<div>"
    gm_header += f"<div style='font-size: 18px; font-weight: bold; color: #00d4ff;'>{gm['name']}</div>"
    gm_header += f"<div style='font-size: 12px; color: #888;'>{gm['title']} - {team_name}</div>"
    gm_header += f"</div></div>"
    gm_header += f"<div style='margin-top: 12px; font-style: italic; color: #ccc;'>\"{catchphrase}\"</div>"
    gm_header += f"<div style='margin-top: 8px; font-size: 12px; color: #888;'>Philosophy: <span style='color: #ffd700;'>{GM_PHILOSOPHIES.get(gm['philosophy'], {}).get('name', 'Balanced')}</span> | Risk Tolerance: <span style='color: #ffd700;'>{int(gm['risk_tolerance'] * 100)}%</span></div>"
    gm_header += f"</div>"
    analysis_parts.append(gm_header)

    # ============ DETAILED ROSTER DEMOGRAPHICS ============
    ages = [p.age for p in team.players if p.age > 0]
    avg_age = sum(ages) / len(ages) if ages else 0
    young_players = [(p, v) for p, v in players_with_value if p.age <= 25 and p.age > 0]
    prime_players = [(p, v) for p, v in players_with_value if 26 <= p.age <= 30]
    veteran_players = [(p, v) for p, v in players_with_value if p.age > 30]
    prospects = [p for p in team.players if p.is_prospect]

    # Hitters vs Pitchers breakdown
    hitters = [(p, v) for p, v in players_with_value if p.name in HITTER_PROJECTIONS]
    starters = [(p, v) for p, v in players_with_value if p.name in PITCHER_PROJECTIONS]
    relievers = [(p, v) for p, v in players_with_value if p.name in RELIEVER_PROJECTIONS]
    hitter_value = sum(v for _, v in hitters)
    pitcher_value = sum(v for _, v in starters) + sum(v for _, v in relievers)

    # Calculate comprehensive category totals
    total_hr = sum(HITTER_PROJECTIONS.get(p.name, {}).get('HR', 0) for p, _ in players_with_value)
    total_sb = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SB', 0) for p, _ in players_with_value)
    total_rbi = sum(HITTER_PROJECTIONS.get(p.name, {}).get('RBI', 0) for p, _ in players_with_value)
    total_r = sum(HITTER_PROJECTIONS.get(p.name, {}).get('R', 0) for p, _ in players_with_value)
    total_so = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SO', 0) for p, _ in players_with_value)
    total_k = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p, _ in players_with_value)
    total_qs = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('QS', 0) for p, _ in players_with_value)
    total_w = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('W', 0) for p, _ in players_with_value)
    total_l = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('L', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('L', 0)) for p, _ in players_with_value)
    total_sv_hld = sum((RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) + RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0)) for p, _ in players_with_value)
    total_bb = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('BB', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('BB', 0)) for p, _ in players_with_value)
    k_bb_ratio = total_k / total_bb if total_bb > 0 else 0

    # Get league-wide category rankings
    team_cats, rankings = calculate_league_category_rankings()
    my_ranks = rankings.get(team_name, {})

    # Identify category strengths and weaknesses by rank
    cat_strengths = [(cat, rank) for cat, rank in my_ranks.items() if rank <= 4]
    cat_weaknesses = [(cat, rank) for cat, rank in my_ranks.items() if rank >= 9]
    cat_strengths.sort(key=lambda x: x[1])
    cat_weaknesses.sort(key=lambda x: -x[1])

    # Determine competitive window with nuance
    top_third = total_teams // 3
    bottom_third = total_teams - top_third
    young_value = sum(v for _, v in young_players)
    prime_value = sum(v for _, v in prime_players)
    vet_value = sum(v for _, v in veteran_players)
    is_old_roster = avg_age >= 28 or vet_value > young_value + prime_value
    is_young_roster = avg_age <= 26.5 or len(prospects) >= 6 or young_value > vet_value * 1.5

    # ============ TEAM IDENTITY - DEEP ANALYSIS ============
    if power_rank <= top_third:
        if is_young_roster:
            window = "dynasty"
            window_desc = f"<span style='color:#ffd700'><b>DYNASTY POWERHOUSE</b></span> - {team_name} has it all: elite talent AND youth"
            window_detail = f"This is the rarest combination in dynasty fantasy. You have {len(young_players)} players 25 or younger contributing {young_value:.0f} points of value. Your window isn't just open - it's bolted open for years. Play from a position of strength: don't overpay to fill gaps, let others come to you."
        elif is_old_roster:
            window = "win-now"
            window_desc = f"<span style='color:#f59e0b'><b>WIN-NOW MODE</b></span> - {team_name} is built for immediate contention but time is the enemy"
            window_detail = f"Your roster averages {avg_age:.1f} years old with {len(veteran_players)} veterans contributing {vet_value:.0f} points. This is a championship-caliber roster TODAY, but every month you wait, asset values decline. Be aggressive in trades - overpay for the final pieces if needed. You can't take prospects to the championship."
        else:
            window = "contender"
            window_desc = f"<span style='color:#4ade80'><b>LEGITIMATE CONTENDER</b></span> - {team_name} has the roster to compete now"
            window_detail = f"Balanced across age groups with a strong core. Your {prime_value:.0f} points of prime-age value gives you a 2-3 year window of contention. Target surgical upgrades that address category weaknesses without mortgaging the future."
    elif power_rank >= bottom_third:
        if is_old_roster:
            window = "teardown"
            window_desc = f"<span style='color:#f87171'><b>TEARDOWN REQUIRED</b></span> - {team_name} has an aging roster with no path to contention"
            window_detail = f"Hard truth: averaging {avg_age:.1f} years old with {len(veteran_players)} veterans while ranked #{power_rank} means you're not close AND getting older. Every week you delay selling, your veteran assets lose value. Identify your 3-4 tradeable veterans and start shopping them to contenders NOW. Accept prospects and youth - quantity over quality is fine at this stage."
        elif is_young_roster:
            window = "rebuilding"
            window_desc = f"<span style='color:#60a5fa'><b>REBUILDING (On Track)</b></span> - {team_name} is stockpiling future assets"
            window_detail = f"The rebuild is progressing. With {len(prospects)} prospects and {len(young_players)} young players, you're accumulating the talent to compete in 2-3 years. Stay patient, resist the urge to buy win-now pieces. If a contender offers to overpay for a veteran, take the deal. Accumulate draft picks."
        else:
            window = "retooling"
            window_desc = f"<span style='color:#fbbf24'><b>STUCK IN THE MIDDLE</b></span> - {team_name} needs to pick a direction"
            window_detail = f"This is the danger zone. Not good enough to compete (#{power_rank}), not young enough to rebuild naturally. You have two options: 1) Go all-in by trading prospects for proven talent, or 2) Commit to rebuild by selling veterans. The worst choice is standing pat. Make a decision and commit."
    else:
        if is_young_roster:
            window = "rising"
            window_desc = f"<span style='color:#34d399'><b>RISING CONTENDER</b></span> - {team_name} is building toward a breakthrough"
            window_detail = f"Your young core is developing nicely. With {young_value:.0f} points of value from players 25 and under, you're positioned to rise. Look for undervalued veterans on rebuilding teams who can accelerate your timeline. In 1-2 years, you could be a true contender."
        elif is_old_roster:
            window = "declining"
            window_desc = f"<span style='color:#fb923c'><b>DECLINING ASSET BASE</b></span> - {team_name} is trending the wrong direction"
            window_detail = f"The warning signs are clear: ranked #{power_rank} with an average age of {avg_age:.1f}. Your veteran assets ({vet_value:.0f} points) are depreciating. You're not close enough to contend and your roster is aging out. Start selling veterans now while they still have value."
        else:
            window = "competitive"
            window_desc = f"<span style='color:#a78bfa'><b>COMPETITIVE BUT NOT ELITE</b></span> - {team_name} is in the pack but not leading it"
            window_detail = f"You're competitive but need a spark. Ranked #{power_rank} with a balanced roster, you're one or two moves away from breaking into the top tier. Identify your biggest category weakness and target an upgrade. A single elite addition could vault you into contention."

    identity_text = f"<b>TEAM IDENTITY:</b> {window_desc}<br>"
    identity_text += f"&nbsp;&nbsp;{window_detail}<br>"
    identity_text += f"&nbsp;&nbsp;<b>Power Ranking:</b> <span style='color:#ffd700'>#{power_rank}</span> of {total_teams} | <b>Total Value:</b> {total_value:.0f} points"
    analysis_parts.append(identity_text)

    # ============ ROSTER PROFILE - DETAILED BREAKDOWN ============
    roster_text = "<b>ROSTER PROFILE:</b><br>"

    # Age distribution with value context
    roster_text += f"&nbsp;&nbsp;<b>Demographics:</b> Average age {avg_age:.1f}<br>"
    roster_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Young (≤25): {len(young_players)} players, {young_value:.0f} value ({young_value/total_value*100:.0f}% of roster)<br>"
    roster_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Prime (26-30): {len(prime_players)} players, {prime_value:.0f} value ({prime_value/total_value*100:.0f}% of roster)<br>"
    roster_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Veteran (31+): {len(veteran_players)} players, {vet_value:.0f} value ({vet_value/total_value*100:.0f}% of roster)<br>"

    # Hitter/Pitcher split
    roster_text += f"&nbsp;&nbsp;<b>Roster Construction:</b><br>"
    roster_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Hitters: {len(hitters)} players, {hitter_value:.0f} value<br>"
    roster_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Starters: {len(starters)} players, {sum(v for _, v in starters):.0f} value<br>"
    roster_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Relievers: {len(relievers)} players, {sum(v for _, v in relievers):.0f} value"

    # Roster assessment
    if hitter_value > pitcher_value * 1.4:
        roster_text += "<br>&nbsp;&nbsp;<span style='color:#fbbf24'>Offense-heavy roster - consider adding pitching depth</span>"
    elif pitcher_value > hitter_value * 1.2:
        roster_text += "<br>&nbsp;&nbsp;<span style='color:#fbbf24'>Pitching-heavy roster - could use more offensive firepower</span>"
    else:
        roster_text += "<br>&nbsp;&nbsp;<span style='color:#4ade80'>Well-balanced between hitting and pitching</span>"

    analysis_parts.append(roster_text)

    # ============ CORE ASSETS - IN-DEPTH ANALYSIS ============
    core_text = "<b>CORE ASSETS:</b><br>"

    # Franchise player analysis
    if players_with_value:
        mvp = players_with_value[0]
        mvp_proj = HITTER_PROJECTIONS.get(mvp[0].name) or PITCHER_PROJECTIONS.get(mvp[0].name) or RELIEVER_PROJECTIONS.get(mvp[0].name) or {}

        # Detailed MVP analysis
        if mvp[0].age <= 25:
            mvp_outlook = "<span style='color:#4ade80'>ELITE LONG-TERM</span> — Franchise cornerstone with 8+ years of prime production ahead"
        elif mvp[0].age <= 28:
            mvp_outlook = "<span style='color:#34d399'>PRIME YEARS</span> — Peak performance window, maximize value now"
        elif mvp[0].age <= 31:
            mvp_outlook = "<span style='color:#fbbf24'>LATE PRIME</span> — Still elite but approaching the back end of his window"
        else:
            mvp_outlook = "<span style='color:#fb923c'>AGING STAR</span> — Producing now but decline is imminent, consider selling high"

        core_text += f"&nbsp;&nbsp;<b>Franchise Player:</b> {mvp[0].name}<br>"
        core_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Value: {mvp[1]:.0f} | Age: {mvp[0].age} | Position: {mvp[0].position}<br>"
        core_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Outlook: {mvp_outlook}<br>"

        # Key stats for franchise player
        if mvp_proj:
            if 'HR' in mvp_proj:
                core_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Projection: {mvp_proj.get('HR', 0)} HR, {mvp_proj.get('RBI', 0)} RBI, {mvp_proj.get('R', 0)} R, {mvp_proj.get('SB', 0)} SB<br>"
            elif 'K' in mvp_proj:
                core_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• Projection: {mvp_proj.get('K', 0)} K, {mvp_proj.get('ERA', 0):.2f} ERA, {mvp_proj.get('QS', 0)} QS<br>"

        # Supporting cast
        if len(players_with_value) >= 2:
            core_text += f"&nbsp;&nbsp;<b>Supporting Core:</b><br>"
            for p, v in players_with_value[1:5]:
                age_tag = f"<span style='color:#4ade80'>({p.age})</span>" if p.age <= 26 else f"<span style='color:#fbbf24'>({p.age})</span>" if p.age <= 30 else f"<span style='color:#fb923c'>({p.age})</span>"
                core_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• {p.name}: {v:.0f} value, age {age_tag}<br>"

        # Core quality analysis - count players by tier
        # Elite = 90+ (MVP candidates: Ohtani, Soto)
        # Star = 75+ (All-Stars, top-tier)
        # Starter = 60+ (quality everyday players)
        # Quality = 50+ (solid contributors)
        # Depth = 35+ (bench pieces)
        elite_count = len([v for _, v in players_with_value if v >= 90])
        star_count = len([v for _, v in players_with_value if v >= 75])
        starter_count = len([v for _, v in players_with_value if v >= 60])
        quality_count = len([v for _, v in players_with_value if v >= 50])
        depth_count = len([v for _, v in players_with_value if v >= 35])
        top_player_value = players_with_value[0][1] if players_with_value else 0

        # Use power_rank to validate roster assessment
        # Having stars but ranked poorly = top-heavy, not contender
        is_contender = power_rank <= 4
        is_competitive = power_rank <= 7
        is_bottom_half = power_rank >= 7

        # Determine roster profile based on talent + actual team ranking
        if elite_count >= 2 and is_contender:
            core_text += f"&nbsp;&nbsp;<span style='color:#4ade80'>Stacked: {elite_count} elite superstars (90+) - championship favorite</span>"
        elif elite_count >= 2 and is_competitive:
            core_text += f"&nbsp;&nbsp;<span style='color:#60a5fa'>Elite talent: {elite_count} superstars but ranked #{power_rank} - depth issues?</span>"
        elif elite_count >= 2:
            core_text += f"&nbsp;&nbsp;<span style='color:#fbbf24'>Top-heavy: {elite_count} elite stars but ranked #{power_rank} - need supporting cast</span>"
        elif elite_count == 1 and star_count >= 3 and is_contender:
            core_text += f"&nbsp;&nbsp;<span style='color:#4ade80'>Superstar-led: 1 elite + {star_count - 1} stars - title contender</span>"
        elif elite_count == 1 and star_count >= 3:
            core_text += f"&nbsp;&nbsp;<span style='color:#60a5fa'>Star power: 1 elite + {star_count - 1} stars but ranked #{power_rank}</span>"
        elif star_count >= 4 and is_competitive:
            core_text += f"&nbsp;&nbsp;<span style='color:#4ade80'>Star-powered: {star_count} stars (75+) - strong roster</span>"
        elif star_count >= 4:
            core_text += f"&nbsp;&nbsp;<span style='color:#fbbf24'>Stars without depth: {star_count} stars but ranked #{power_rank} - fill the gaps</span>"
        elif star_count >= 2 and starter_count >= 6:
            core_text += f"&nbsp;&nbsp;<span style='color:#60a5fa'>Balanced: {star_count} stars + {starter_count - star_count} starters</span>"
        elif starter_count >= 8:
            core_text += f"&nbsp;&nbsp;<span style='color:#60a5fa'>Deep lineup: {starter_count} starters (60+) but no true stars</span>"
        elif starter_count >= 5:
            core_text += f"&nbsp;&nbsp;<span style='color:#fbbf24'>Developing: {starter_count} starters, {quality_count - starter_count} quality - building</span>"
        elif quality_count >= 8:
            core_text += f"&nbsp;&nbsp;<span style='color:#fbbf24'>Quantity over quality: {quality_count} serviceable (50+) but no stars</span>"
        elif quality_count >= 4:
            core_text += f"&nbsp;&nbsp;<span style='color:#fb923c'>Thin roster: Only {quality_count} quality players (50+) - needs upgrades</span>"
        else:
            core_text += f"&nbsp;&nbsp;<span style='color:#f87171'>Full rebuild: {quality_count} quality, {depth_count} depth - start over</span>"

    analysis_parts.append(core_text.rstrip('<br>'))

    # ============ FARM SYSTEM - COMPREHENSIVE EVALUATION ============
    farm_text = "<b>FARM SYSTEM:</b><br>"

    top_100_prospects = sorted([p for p in prospects if p.prospect_rank and p.prospect_rank <= 100], key=lambda x: x.prospect_rank)
    top_300_prospects = sorted([p for p in prospects if p.prospect_rank and p.prospect_rank <= 300], key=lambda x: x.prospect_rank)
    all_ranked = sorted([p for p in prospects if p.prospect_rank], key=lambda x: x.prospect_rank)

    # Smarter farm grading using points system
    # Points weighted by prospect tier (higher tier = exponentially more valuable)
    farm_points = 0
    top_10_count = 0
    top_25_count = 0
    top_50_count = 0
    top_100_count = len(top_100_prospects)

    for p in prospects:
        if p.prospect_rank:
            if p.prospect_rank <= 10:
                farm_points += 25  # Elite of elite
                top_10_count += 1
                top_25_count += 1
                top_50_count += 1
            elif p.prospect_rank <= 25:
                farm_points += 15  # Blue chip
                top_25_count += 1
                top_50_count += 1
            elif p.prospect_rank <= 50:
                farm_points += 8   # High-end
                top_50_count += 1
            elif p.prospect_rank <= 100:
                farm_points += 4   # Solid
            elif p.prospect_rank <= 150:
                farm_points += 2   # Depth
            elif p.prospect_rank <= 250:
                farm_points += 1   # Lottery ticket
            else:
                farm_points += 0.5  # Filler

    # Calculate league-wide farm rankings for context
    all_farm_points = []
    for other_team_name, other_team in teams.items():
        other_points = 0
        for p in other_team.players:
            if p.is_prospect and p.prospect_rank:
                if p.prospect_rank <= 10:
                    other_points += 25
                elif p.prospect_rank <= 25:
                    other_points += 15
                elif p.prospect_rank <= 50:
                    other_points += 8
                elif p.prospect_rank <= 100:
                    other_points += 4
                elif p.prospect_rank <= 150:
                    other_points += 2
                elif p.prospect_rank <= 250:
                    other_points += 1
                else:
                    other_points += 0.5
        all_farm_points.append((other_team_name, other_points))

    all_farm_points.sort(key=lambda x: -x[1])
    farm_rank = next((i + 1 for i, (name, _) in enumerate(all_farm_points) if name == team_name), 12)
    avg_farm_points = sum(pts for _, pts in all_farm_points) / len(all_farm_points) if all_farm_points else 0

    # Grade based on league rank AND absolute quality
    # Only 1 team can be A+, 2 can be A, etc.
    if farm_rank == 1 and farm_points >= 40:
        farm_grade = "A+"
        farm_color = "#4ade80"
        farm_desc = "Best farm in the league — elite prospect capital"
    elif farm_rank <= 2 and farm_points >= 30:
        farm_grade = "A"
        farm_color = "#34d399"
        farm_desc = "Top-tier farm system — strong future foundation"
    elif farm_rank <= 4 and farm_points >= 20:
        farm_grade = "B+"
        farm_color = "#60a5fa"
        farm_desc = "Above average farm — quality over quantity"
    elif farm_rank <= 6 or farm_points >= 15:
        farm_grade = "B"
        farm_color = "#a78bfa"
        farm_desc = "Average farm — some upside but no stars"
    elif farm_rank <= 8 or farm_points >= 8:
        farm_grade = "C+"
        farm_color = "#fbbf24"
        farm_desc = "Below average — lacks impact talent"
    elif farm_rank <= 10 or farm_points >= 4:
        farm_grade = "C"
        farm_color = "#fb923c"
        farm_desc = "Weak farm — limited future value"
    else:
        farm_grade = "D"
        farm_color = "#f87171"
        farm_desc = "Depleted — needs major restocking"

    # Descriptive breakdown
    farm_text += f"&nbsp;&nbsp;<b>Farm Grade:</b> <span style='color:{farm_color}'><b>{farm_grade}</b></span> — {farm_desc}<br>"
    farm_text += f"&nbsp;&nbsp;<b>League Rank:</b> #{farm_rank} of {len(all_farm_points)} | <b>Farm Score:</b> {farm_points:.0f} pts (avg: {avg_farm_points:.0f})<br>"
    farm_text += f"&nbsp;&nbsp;<b>Breakdown:</b> {top_10_count} elite (1-10) | {top_25_count} blue-chip (1-25) | {top_50_count} top 50 | {top_100_count} top 100<br>"

    # Top prospects detail with more context
    if top_100_prospects:
        farm_text += f"&nbsp;&nbsp;<b>Top Prospects:</b><br>"
        for p in top_100_prospects[:4]:
            prospect_value = calculator.calculate_player_value(p)
            # More nuanced ETA based on rank and age
            if p.age <= 20:
                eta = "2028+" if p.prospect_rank > 50 else "2027"
            elif p.age <= 22:
                eta = "2027" if p.prospect_rank > 30 else "2026"
            else:
                eta = "2026" if prospect_value >= 35 else "2026-27"
            farm_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• <b>#{p.prospect_rank}</b> {p.name} ({p.position}, {p.age}y) - Value: {prospect_value:.0f}, ETA: {eta}<br>"
    elif all_ranked:
        farm_text += f"&nbsp;&nbsp;<b>Best Prospects:</b><br>"
        for p in all_ranked[:3]:
            prospect_value = calculator.calculate_player_value(p)
            farm_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• #{p.prospect_rank} {p.name} — Value: {prospect_value:.0f}<br>"
    else:
        farm_text += f"&nbsp;&nbsp;<span style='color:#f87171'>No ranked prospects on roster — farm is bare</span><br>"

    # Personalized farm recommendation based on team situation
    if window in ['dynasty', 'contender', 'win-now']:
        if farm_grade in ['A+', 'A']:
            farm_text += f"&nbsp;&nbsp;<span style='color:#4ade80'>Elite farm + contending = dynasty potential. You can trade prospects for missing pieces without mortgaging the future.</span>"
        elif farm_grade in ['B+', 'B']:
            farm_text += f"&nbsp;&nbsp;<span style='color:#fbbf24'>Contending with average farm - be selective about trading prospects. Each one matters more.</span>"
        else:
            farm_text += f"&nbsp;&nbsp;<span style='color:#fbbf24'>Contending with thin farm - be careful not to trade away future completely.</span>"
    elif window in ['rebuilding', 'teardown']:
        if farm_grade in ['A+', 'A', 'B+']:
            farm_text += f"&nbsp;&nbsp;<span style='color:#4ade80'>Rebuilding with strong farm - stay the course, let talent develop.</span>"
        else:
            farm_text += f"&nbsp;&nbsp;<span style='color:#fbbf24'>Need to acquire more prospects - sell any remaining veteran value.</span>"

    analysis_parts.append(farm_text.rstrip('<br>'))

    # ============ CATEGORY OUTLOOK - FULL BREAKDOWN ============
    cat_text = "<b>CATEGORY OUTLOOK:</b><br>"

    # Hitting categories with rankings
    cat_text += "&nbsp;&nbsp;<b>Hitting:</b><br>"
    hr_rank = my_ranks.get('HR', 12)
    sb_rank = my_ranks.get('SB', 12)
    rbi_rank = my_ranks.get('RBI', 12)
    r_rank = my_ranks.get('R', 12)
    so_rank = my_ranks.get('SO', 12)

    def rank_color(rank):
        if rank <= 4: return '#4ade80'  # Green - top third
        elif rank <= 8: return '#fbbf24'  # Yellow - middle
        else: return '#f87171'  # Red - bottom third

    cat_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• HR: {total_hr} <span style='color:{rank_color(hr_rank)}'>(#{hr_rank})</span> | "
    cat_text += f"SB: {total_sb} <span style='color:{rank_color(sb_rank)}'>(#{sb_rank})</span> | "
    cat_text += f"RBI: {total_rbi} <span style='color:{rank_color(rbi_rank)}'>(#{rbi_rank})</span> | "
    cat_text += f"R: {total_r} <span style='color:{rank_color(r_rank)}'>(#{r_rank})</span><br>"
    cat_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• SO: {total_so} <span style='color:{rank_color(so_rank)}'>(#{so_rank})</span> <i>(lower is better)</i><br>"

    # Pitching categories with rankings
    cat_text += "&nbsp;&nbsp;<b>Pitching:</b><br>"
    k_rank = my_ranks.get('K', 12)
    qs_rank = my_ranks.get('QS', 12)
    svh_rank = my_ranks.get('SV+HLD', 12)
    era_rank = my_ranks.get('ERA', 12)
    whip_rank = my_ranks.get('WHIP', 12)
    l_rank = my_ranks.get('L', 12)
    kbb_rank = my_ranks.get('K/BB', 12)

    cat_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• K: {total_k} <span style='color:{rank_color(k_rank)}'>(#{k_rank})</span> | "
    cat_text += f"QS: {total_qs} <span style='color:{rank_color(qs_rank)}'>(#{qs_rank})</span> | "
    cat_text += f"W: {total_w} | L: {total_l} <span style='color:{rank_color(l_rank)}'>(#{l_rank})</span><br>"
    cat_text += f"&nbsp;&nbsp;&nbsp;&nbsp;• SV+HLD: {total_sv_hld} <span style='color:{rank_color(svh_rank)}'>(#{svh_rank})</span> | "
    cat_text += f"K/BB: {k_bb_ratio:.2f} <span style='color:{rank_color(kbb_rank)}'>(#{kbb_rank})</span><br>"

    # Summary of strengths and weaknesses
    if cat_strengths:
        strength_list = ", ".join([f"{cat} (#{rank})" for cat, rank in cat_strengths[:3]])
        cat_text += f"&nbsp;&nbsp;<span style='color:#4ade80'><b>Strengths:</b> {strength_list}</span><br>"
    if cat_weaknesses:
        weakness_list = ", ".join([f"{cat} (#{rank})" for cat, rank in cat_weaknesses[:3]])
        cat_text += f"&nbsp;&nbsp;<span style='color:#f87171'><b>Weaknesses:</b> {weakness_list}</span>"

    analysis_parts.append(cat_text.rstrip('<br>'))

    # Risk factors with specific players
    risk_factors = []
    sell_candidates = []
    for p, v in players_with_value[:20]:
        if p.age >= 33 and v >= 30:
            sell_candidates.append(f"{p.name} (age {p.age}, value {v:.0f})")
        elif p.age >= 35 and v >= 20:
            sell_candidates.append(f"{p.name} (age {p.age})")

    if sell_candidates and window in ['rebuilding', 'teardown', 'declining', 'retooling']:
        risk_factors.append(f"<span style='color:#fbbf24'>Sell candidates:</span> {', '.join(sell_candidates[:3])}")
    elif sell_candidates:
        risk_factors.append(f"Aging assets to monitor: {', '.join(sell_candidates[:2])}")

    if players_with_value:
        top_2_value = sum(v for _, v in players_with_value[:2])
        total_value = sum(v for _, v in players_with_value)
        if total_value > 0 and top_2_value / total_value > 0.30:
            risk_factors.append(f"Top-heavy ({top_2_value/total_value*100:.0f}% value in top 2)")

    if risk_factors:
        analysis_parts.append(f"<b>RISK FACTORS:</b> {' | '.join(risk_factors)}.")
    else:
        analysis_parts.append("<b>RISK FACTORS:</b> Well-balanced roster with no major red flags.")

    # Personalized trade strategy with specific recommendations
    strategy = "<b>TRADE STRATEGY:</b><br>"

    # Find specific trade targets based on team needs
    biggest_weakness = cat_weaknesses[0] if cat_weaknesses else None
    biggest_strength = cat_strengths[0] if cat_strengths else None

    if window == "dynasty":
        strategy += f"&nbsp;&nbsp;<b>Approach:</b> <span style='color:#4ade80'>Play from strength</span> — you have the luxury of patience.<br>"
        if biggest_weakness:
            strategy += f"&nbsp;&nbsp;<b>Target:</b> Address {biggest_weakness[0]} (#{biggest_weakness[1]}) weakness, but don't overpay.<br>"
        strategy += f"&nbsp;&nbsp;<b>Avoid:</b> Trading core young assets for marginal upgrades. Let others come to you.<br>"
        if biggest_strength and farm_grade in ['A+', 'A', 'B+']:
            strategy += f"&nbsp;&nbsp;<b>Leverage:</b> Your {biggest_strength[0]} surplus and prospect depth are trade chips if needed."
    elif window == "contender":
        strategy += f"&nbsp;&nbsp;<b>Approach:</b> <span style='color:#34d399'>Surgical upgrades</span> — find the missing piece.<br>"
        if biggest_weakness:
            strategy += f"&nbsp;&nbsp;<b>Target:</b> Prioritize {biggest_weakness[0]} (#{biggest_weakness[1]}) — this is your biggest hole.<br>"
        strategy += f"&nbsp;&nbsp;<b>Willing to Pay:</b> Mid-tier prospects for proven contributors. Championships > potential.<br>"
        if sell_candidates:
            strategy += f"&nbsp;&nbsp;<b>Consider Moving:</b> {sell_candidates[0].split(' (')[0]} if you can upgrade at a position of need."
    elif window == "win-now":
        strategy += f"&nbsp;&nbsp;<b>Approach:</b> <span style='color:#f59e0b'>ALL IN</span> — your window is closing, act with urgency.<br>"
        strategy += f"&nbsp;&nbsp;<b>Target:</b> Any proven contributor who fills a need. Overpay if necessary.<br>"
        strategy += f"&nbsp;&nbsp;<b>Trade Away:</b> ALL prospects, future picks, anything not nailed down.<br>"
        if sell_candidates:
            strategy += f"&nbsp;&nbsp;<b>Clock is Ticking:</b> {sell_candidates[0].split(' (')[0]} won't be this valuable next year."
    elif window == "rising":
        strategy += f"&nbsp;&nbsp;<b>Approach:</b> <span style='color:#60a5fa'>Opportunistic buying</span> — accelerate carefully.<br>"
        strategy += f"&nbsp;&nbsp;<b>Target:</b> Undervalued vets from rebuilding teams who fit your timeline.<br>"
        strategy += f"&nbsp;&nbsp;<b>Protect:</b> Your top prospects — they're the foundation of future contention.<br>"
        if biggest_weakness:
            strategy += f"&nbsp;&nbsp;<b>Focus:</b> Address {biggest_weakness[0]} weakness without overpaying."
    elif window == "competitive":
        strategy += f"&nbsp;&nbsp;<b>Approach:</b> <span style='color:#a78bfa'>Decision time</span> — commit to a direction.<br>"
        strategy += f"&nbsp;&nbsp;<b>Option A:</b> Buy aggressively — trade prospects for win-now pieces and push for playoffs.<br>"
        strategy += f"&nbsp;&nbsp;<b>Option B:</b> Start selling — move veterans for youth and rebuild properly.<br>"
        strategy += f"&nbsp;&nbsp;<b>Avoid:</b> Standing pat. The middle ground leads to mediocrity."
    elif window == "declining":
        strategy += f"&nbsp;&nbsp;<b>Approach:</b> <span style='color:#fb923c'>Controlled sell-off</span> — maximize returns before values drop.<br>"
        if sell_candidates:
            strategy += f"&nbsp;&nbsp;<b>Sell Now:</b> {', '.join([s.split(' (')[0] for s in sell_candidates[:3]])}.<br>"
        strategy += f"&nbsp;&nbsp;<b>Target:</b> Young players, prospects, draft picks — anything with upside.<br>"
        strategy += f"&nbsp;&nbsp;<b>Urgency:</b> Every week you wait, your veteran assets lose value."
    elif window == "retooling":
        strategy += f"&nbsp;&nbsp;<b>Approach:</b> <span style='color:#fbbf24'>Pick a lane</span> — indecision is the enemy.<br>"
        strategy += f"&nbsp;&nbsp;<b>Reality Check:</b> You're #{power_rank} — not good enough to win, not bad enough for top picks.<br>"
        strategy += f"&nbsp;&nbsp;<b>Recommendation:</b> Commit to rebuild. Sell veterans, accumulate youth. Half-measures won't work."
    elif window == "rebuilding":
        strategy += f"&nbsp;&nbsp;<b>Approach:</b> <span style='color:#60a5fa'>Patient accumulation</span> — trust the process.<br>"
        strategy += f"&nbsp;&nbsp;<b>Target:</b> Prospects, young players, draft picks. Accept quantity over quality for now.<br>"
        strategy += f"&nbsp;&nbsp;<b>Sell:</b> Any player over 28 with trade value — you don't need veterans.<br>"
        if farm_grade in ['C+', 'C', 'D']:
            strategy += f"&nbsp;&nbsp;<b>Priority:</b> Your farm (grade {farm_grade}) needs restocking. Be aggressive acquiring prospects."
    elif window == "teardown":
        strategy += f"&nbsp;&nbsp;<b>Approach:</b> <span style='color:#f87171'>Full liquidation</span> — sell everything that moves.<br>"
        if sell_candidates:
            strategy += f"&nbsp;&nbsp;<b>Immediate Sales:</b> {', '.join([s.split(' (')[0] for s in sell_candidates[:3]])}.<br>"
        strategy += f"&nbsp;&nbsp;<b>Target:</b> Volume of prospects > quality. Cast a wide net.<br>"
        strategy += f"&nbsp;&nbsp;<b>Mindset:</b> You're building for 2-3 years from now. Accept short-term pain."

    analysis_parts.append(strategy.rstrip('<br>'))

    # Position depth analysis - normalize positions and count properly
    pos_counts = {'C': 0, '1B': 0, '2B': 0, 'SS': 0, '3B': 0, 'OF': 0, 'SP': 0, 'RP': 0}
    exclude_positions = ['DH', 'UTIL', 'UT', 'P', '']

    for p, _ in players_with_value:
        pos_str = (p.position or '').upper()
        # Count each position the player can play
        positions_found = set()
        for pos in pos_str.replace('/', ',').split(','):
            pos = pos.strip()
            # Normalize outfield positions
            if pos in ['LF', 'CF', 'RF', 'OF']:
                positions_found.add('OF')
            elif pos in pos_counts and pos not in exclude_positions:
                positions_found.add(pos)
        # Add to counts (each player counts once per position type)
        for pos in positions_found:
            pos_counts[pos] += 1

    # Determine thin (<=2) and deep (>=5) positions, excluding overlap
    thin_positions = [pos for pos, count in pos_counts.items() if count <= 2 and count > 0]
    deep_positions = [pos for pos, count in pos_counts.items() if count >= 5]

    # A position can't be both thin and deep - remove any overlap
    thin_positions = [p for p in thin_positions if p not in deep_positions]

    depth_text = "<b>POSITIONAL DEPTH:</b> "
    if thin_positions:
        depth_text += f"<span style='color:#f87171'>Thin at {', '.join(thin_positions[:3])}</span>. "
    if deep_positions:
        depth_text += f"<span style='color:#4ade80'>Deep at {', '.join(deep_positions[:3])}</span>. "
    if not thin_positions and not deep_positions:
        depth_text += "Balanced depth across positions. "

    # Identify specific position needs or trade chips
    if thin_positions:
        depth_text += f"Prioritize adding {thin_positions[0]} in trades/FA."
    elif deep_positions:
        depth_text += f"Consider trading from {deep_positions[0]} surplus for needs."
    analysis_parts.append(depth_text)

    # Bottom line summary
    bottom_line = "<b>BOTTOM LINE:</b> "
    total_value = sum(v for _, v in players_with_value)
    if window in ['dynasty', 'contender', 'win-now']:
        if cat_weaknesses:
            bottom_line += f"A {window} team that should be aggressive acquiring {cat_weaknesses[0]} help. "
        else:
            bottom_line += f"An elite roster built to win. Protect your core and target marginal upgrades. "
        bottom_line += f"Total roster value: <span style='color:#ffd700'>{total_value:.0f} points</span>."
    elif window in ['rebuilding', 'rising']:
        bottom_line += f"The future is bright with {len(prospects)} prospects and {len(young_players)} young players. "
        bottom_line += f"Be patient, accumulate assets, and let the talent develop. Value: {total_value:.0f} pts."
    elif window in ['teardown', 'declining']:
        if sell_candidates:
            bottom_line += f"Move {sell_candidates[0].split(' (')[0]} and other vets ASAP. "
        bottom_line += f"Every week you wait costs you draft capital. Time to accelerate the rebuild."
    else:
        bottom_line += f"Stuck in no-man's land with {total_value:.0f} points of value. "
        bottom_line += "Make a decisive move - buy in or sell out. The middle path leads nowhere."
    analysis_parts.append(bottom_line)

    # === ENHANCED AI ANALYSIS SECTIONS ===

    # Trade Targets by Category
    if cat_weaknesses:
        trade_targets = get_category_trade_targets(team_name, cat_weaknesses, num_targets=3)
        if trade_targets:
            targets_text = "<b>TRADE TARGETS BY NEED:</b><br>"
            for cat, players in trade_targets.items():
                if players:
                    player_list = ", ".join([f"{p['name']} ({p['team']}, {p['cat_value']} {cat})" for p in players[:2]])
                    targets_text += f"<span style='color:#00d4ff'>For {cat}:</span> {player_list}<br>"
            analysis_parts.append(targets_text.rstrip('<br>'))

    # Buy-Low / Sell-High Alerts - Enhanced GM-style
    alerts = get_buy_low_sell_high_alerts(team_name, team)
    if alerts['sell_high'] or alerts['buy_low']:
        alerts_text = "<b>MARKET OPPORTUNITIES:</b><br>"

        # Sell-high with reasoning
        if alerts['sell_high']:
            alerts_text += "<b>Sell Window Open:</b><br>"
            for a in alerts['sell_high'][:3]:
                urgency_color = '#f87171' if a['urgency'] == 'critical' else '#fbbf24' if a['urgency'] == 'high' else '#facc15'
                alerts_text += f"&nbsp;&nbsp;• <span style='color:{urgency_color}'>{a['name']}</span>: {a['reason']}<br>"

        # Buy-low with more detail
        if alerts['buy_low']:
            alerts_text += "<b>Acquisition Targets (other teams):</b><br>"
            for a in alerts['buy_low'][:6]:
                alerts_text += f"&nbsp;&nbsp;• <span style='color:#4ade80'>{a['name']}</span> ({a['team']}): {a['reason']}<br>"

        analysis_parts.append(alerts_text.rstrip('<br>'))

    # === GM TRADE SCENARIOS ===
    gm_scenarios = generate_gm_trade_scenarios(team_name, team)
    if gm_scenarios:
        scenario_text = f"<b>{gm['name'].upper()}'S TRADE SCENARIOS:</b><br>"
        scenario_text += f"<i>Here's what I'd explore given our {GM_PHILOSOPHIES.get(gm['philosophy'], {}).get('name', 'balanced')} approach:</i><br><br>"
        for i, s in enumerate(gm_scenarios, 1):
            scenario_text += f"<b>{s['title']}</b><br>"
            scenario_text += f"&nbsp;&nbsp;Target: {s['target']} (~{s['target_value']:.0f} value)<br>"
            scenario_text += f"&nbsp;&nbsp;Offer: {s['offer']} (~{s['offer_value']:.0f} value)<br>"
            scenario_text += f"&nbsp;&nbsp;Why: {s['reasoning']}<br>"
            if i < len(gm_scenarios):
                scenario_text += "<br>"
        analysis_parts.append(scenario_text)

    # === LEAGUE TRADE MARKET SCAN ===
    league_scan = scan_league_for_opportunities(team_name)
    if league_scan:
        scan_text = "<b>LEAGUE TRADE MARKET:</b><br>"
        scan_text += f"<i>{league_scan['trade_market_summary']}</i><br><br>"

        # Show rebuilding teams with sellable assets
        if league_scan['rebuilding_teams']:
            scan_text += "<b>Teams Selling:</b><br>"
            for t in league_scan['rebuilding_teams'][:3]:
                assets = ", ".join([f"{n} ({v:.0f}, age {a})" for n, v, a in t['sellable_assets'][:2]])
                scan_text += f"&nbsp;&nbsp;• <span style='color:#fbbf24'>{t['team']}</span> (#{t['rank']}): {assets}<br>"

        # Show veteran teams that might overpay
        if league_scan['veteran_heavy_teams']:
            scan_text += "<b>Win-Now Teams (potential buyers):</b><br>"
            for t in league_scan['veteran_heavy_teams'][:2]:
                scan_text += f"&nbsp;&nbsp;• <span style='color:#4ade80'>{t['team']}</span>: {t['veteran_count']} vets, avg age {t['avg_age']:.1f}<br>"

        analysis_parts.append(scan_text.rstrip('<br>'))

    # Draft Pick Recommendations
    if draft_order_config and team_name in draft_order_config:
        pick_num = draft_order_config[team_name]
        draft_recs = get_draft_recommendations(team_name, pick_num, thin_positions, cat_weaknesses)
        if draft_recs:
            draft_text = f"<b>2026 DRAFT (Pick #{pick_num}):</b><br>"
            draft_text += "<br>".join([f"• {rec}" for rec in draft_recs[:3]])
            analysis_parts.append(draft_text)

    # Rivalry Analysis
    rival_name = TEAM_RIVALRIES.get(team_name)
    if rival_name:
        rivalry = generate_rivalry_analysis(team_name, rival_name)
        if rivalry:
            diff = rivalry['value_diff']
            status = "leading" if diff > 0 else "trailing"
            diff_color = "#4ade80" if diff > 0 else "#f87171"

            rivalry_text = f"<b>RIVALRY vs {rival_name}:</b><br>"

            # Historical H2H record
            h2h = rivalry.get('my_h2h_record', 'N/A')
            if h2h != 'N/A':
                h2h_wins = int(h2h.split('-')[0]) if '-' in h2h else 0
                h2h_losses = int(h2h.split('-')[1].split('-')[0]) if '-' in h2h else 0
                h2h_color = "#4ade80" if h2h_wins > h2h_losses else "#f87171" if h2h_losses > h2h_wins else "#fbbf24"
                rivalry_text += f"<span style='color:{h2h_color}'>2025 H2H: {h2h}</span> (Your record: {rivalry.get('my_2025_record', 'N/A')} | Their record: {rivalry.get('rival_2025_record', 'N/A')})<br>"

            rivalry_text += f"Dynasty value: You're <span style='color:{diff_color}'>{status} by {abs(diff):.0f} points</span> ({rivalry['my_value']:.0f} vs {rivalry['rival_value']:.0f}). "

            if rivalry['advantages']:
                rivalry_text += f"<br><span style='color:#4ade80'>Category advantages: {', '.join(rivalry['advantages'][:4])}</span>. "
            if rivalry['disadvantages']:
                rivalry_text += f"<span style='color:#f87171'>Disadvantages: {', '.join(rivalry['disadvantages'][:4])}</span>. "

            rivalry_text += f"<br>Their stars: {', '.join([f'{n} ({v})' for n, v in rivalry['rival_top_players'][:2]])}."
            analysis_parts.append(rivalry_text)

    # ============ ASSISTANT GM SIGNATURE ============
    gm_signature = f"<div style='margin-top: 20px; padding-top: 16px; border-top: 1px solid rgba(255,215,0,0.3);'>"
    gm_signature += f"<div style='text-align: right; font-style: italic; color: #888;'>- {gm['name']}, {gm['title']}</div>"
    gm_signature += f"<div style='text-align: right; font-size: 12px; color: #666; margin-top: 4px;'>{gm['trade_style']}</div>"
    gm_signature += f"</div>"
    analysis_parts.append(gm_signature)

    return "<br><br>".join(analysis_parts)


@app.route('/search')
def search_players():
    query = request.args.get('q', '').strip().lower()
    limit = min(int(request.args.get('limit', 20)), 100)

    if len(query) < 2:
        return jsonify({"results": []})

    results = []
    for team_name, team in teams.items():
        for p in team.players:
            if query in p.name.lower():
                value = calculator.calculate_player_value(p)
                results.append({
                    "name": p.name,
                    "position": p.position,
                    "mlb_team": p.mlb_team,
                    "fantasy_team": team_name,
                    "age": p.age,
                    "value": value,
                    "is_prospect": p.is_prospect,
                    "prospect_rank": p.prospect_rank if p.is_prospect else None
                })

    results.sort(key=lambda x: x['value'], reverse=True)
    return jsonify({"results": results[:limit]})


@app.route('/player/<player_name>')
def get_player(player_name):
    # Find player on a team roster first
    player = None
    fantasy_team = None
    is_free_agent = False
    fa_data = None

    for team_name, team in teams.items():
        for p in team.players:
            if p.name.lower() == player_name.lower():
                player = p
                fantasy_team = team_name
                break
        if player:
            break

    # If not found on a team, check free agents
    if not player:
        for fa in FREE_AGENTS:
            if fa['name'].lower() == player_name.lower():
                is_free_agent = True
                fa_data = fa
                fantasy_team = "Free Agent"
                break

    if not player and not is_free_agent:
        return jsonify({"error": f"Player '{player_name}' not found"}), 404

    # Handle free agent display
    if is_free_agent:
        is_fa_prospect = fa_data.get('is_prospect', False)
        fa_prospect_rank = fa_data.get('prospect_rank')

        # Calculate prospect bonus for display
        prospect_bonus = 0
        if is_fa_prospect and fa_prospect_rank:
            if fa_prospect_rank <= 10:
                prospect_bonus = 25
            elif fa_prospect_rank <= 25:
                prospect_bonus = 20
            elif fa_prospect_rank <= 50:
                prospect_bonus = 15
            elif fa_prospect_rank <= 100:
                prospect_bonus = 10
            elif fa_prospect_rank <= 150:
                prospect_bonus = 6
            else:
                prospect_bonus = 3

        # Build trade advice
        if is_fa_prospect and fa_prospect_rank:
            trade_advice = f"TOP {fa_prospect_rank} PROSPECT available as free agent! High priority pickup for dynasty leagues."
        else:
            trade_advice = f"Free agent with {fa_data['roster_pct']:.0f}% roster rate. Fantrax rank #{fa_data['rank']}. Consider adding if he fills a need."

        return jsonify({
            "name": fa_data['name'],
            "position": fa_data['position'],
            "mlb_team": fa_data['mlb_team'],
            "fantasy_team": "Free Agent",
            "age": fa_data['age'],
            "dynasty_value": fa_data['dynasty_value'],
            "is_prospect": is_fa_prospect,
            "prospect_rank": fa_prospect_rank,
            "trajectory": "Ascending" if fa_data['age'] <= 26 else ("Prime" if fa_data['age'] <= 30 else "Declining"),
            "trajectory_desc": f"Age {fa_data['age']} free agent available for pickup." + (f" Ranked #{fa_prospect_rank} prospect!" if is_fa_prospect else ""),
            "age_adjustment": 5 if fa_data['age'] <= 26 else (0 if fa_data['age'] <= 30 else -5),
            "prospect_bonus": prospect_bonus,
            "projections": HITTER_PROJECTIONS.get(fa_data['name'], {}) or PITCHER_PROJECTIONS.get(fa_data['name'], {}) or RELIEVER_PROJECTIONS.get(fa_data['name'], {}),
            "projections_estimated": False,
            "actual_stats": None,
            "fantasy_points": None,
            "fppg": None,
            "category_contributions": [],
            "trade_advice": trade_advice,
            "fa_info": {
                "roster_pct": fa_data['roster_pct'],
                "fantrax_rank": fa_data['rank'],
                "fantrax_score": fa_data['score']
            }
        })

    value = calculator.calculate_player_value(player)

    # Get projections
    projections = {}
    projections_estimated = False
    if player.name in HITTER_PROJECTIONS:
        projections = dict(HITTER_PROJECTIONS[player.name])
    elif player.name in PITCHER_PROJECTIONS:
        projections = dict(PITCHER_PROJECTIONS[player.name])
    elif player.name in RELIEVER_PROJECTIONS:
        projections = dict(RELIEVER_PROJECTIONS[player.name])
    elif player.is_prospect and player.prospect_rank:
        # Estimate projections for prospects without data
        projections_estimated = True

    # Determine trajectory
    if player.age <= 25:
        trajectory = "Ascending"
        trajectory_desc = f"At {player.age}, this player is still developing and their value should increase."
    elif player.age <= 28:
        trajectory = "Prime"
        trajectory_desc = f"At {player.age}, this player is entering or in their prime years."
    elif player.age <= 31:
        trajectory = "Peak"
        trajectory_desc = f"At {player.age}, this player is at peak value but decline will start soon."
    else:
        trajectory = "Declining"
        trajectory_desc = f"At {player.age}, expect gradual decline in performance and value."

    # Age adjustment calculation (simplified)
    if player.age <= 24:
        age_adjustment = 10
    elif player.age <= 26:
        age_adjustment = 5
    elif player.age <= 28:
        age_adjustment = 0
    elif player.age <= 30:
        age_adjustment = -5
    elif player.age <= 32:
        age_adjustment = -10
    else:
        age_adjustment = -15

    # Prospect bonus
    prospect_bonus = 0
    if player.is_prospect and player.prospect_rank:
        if player.prospect_rank <= 10:
            prospect_bonus = 25
        elif player.prospect_rank <= 25:
            prospect_bonus = 20
        elif player.prospect_rank <= 50:
            prospect_bonus = 15
        elif player.prospect_rank <= 100:
            prospect_bonus = 10

    # Category contributions
    category_contributions = []
    if projections:
        if projections.get('HR', 0) >= 25:
            category_contributions.append("Power (HR)")
        if projections.get('SB', 0) >= 15:
            category_contributions.append("Speed (SB)")
        if projections.get('RBI', 0) >= 80:
            category_contributions.append("Run Production (RBI)")
        if projections.get('AVG', 0) >= 0.280:
            category_contributions.append("Average (AVG)")
        if projections.get('K', 0) >= 150:
            category_contributions.append("Strikeouts (K)")
        if projections.get('ERA', 99) <= 3.50:
            category_contributions.append("ERA")
        if (projections.get('SV', 0) + projections.get('HD', 0)) >= 20:
            category_contributions.append("Saves/Holds")

    # Trade advice
    if player.is_prospect and player.prospect_rank and player.prospect_rank <= 25:
        trade_advice = "Elite prospect - only trade for proven star or massive overpay. These players are franchise-changers."
    elif player.is_prospect and player.prospect_rank and player.prospect_rank <= 50:
        trade_advice = "Quality prospect - can be centerpiece of trade package. Don't sell low - wait for the right deal."
    elif player.is_prospect:
        trade_advice = "Lottery ticket prospect - use as sweetener in deals to upgrade your roster."
    elif value >= 80:
        trade_advice = "Cornerstone player - only trade for another cornerstone or elite package. Building blocks are rare."
    elif value >= 60:
        trade_advice = "Quality starter - good trade chip for upgrading or acquiring prospects. Solid contributor."
    elif value >= 40:
        trade_advice = "Solid contributor - useful in packages or to fill roster holes."
    else:
        trade_advice = "Depth piece - can be packaged in larger deals or used for roster flexibility."

    # Get actual stats and fantasy points
    actual_stats = player_actual_stats.get(player.name)
    fantasy_pts = player_fantasy_points.get(player.name, {})

    return jsonify({
        "name": player.name,
        "position": player.position,
        "team": player.mlb_team,
        "mlb_team": player.mlb_team,
        "fantasy_team": fantasy_team,
        "age": player.age,
        "dynasty_value": round(value, 1),
        "is_prospect": player.is_prospect,
        "prospect_rank": player.prospect_rank if player.is_prospect else None,
        "projections": projections,
        "projections_estimated": projections_estimated,
        "actual_stats": actual_stats,
        "fantasy_points": fantasy_pts.get('fantasy_points'),
        "fppg": fantasy_pts.get('fppg'),
        "trajectory": trajectory,
        "trajectory_desc": trajectory_desc,
        "age_adjustment": age_adjustment,
        "prospect_bonus": prospect_bonus,
        "category_contributions": category_contributions,
        "trade_advice": trade_advice
    })


@app.route('/analyze', methods=['POST'])
def analyze_trade():
    data = request.get_json()

    team_a = data.get('team_a')
    team_b = data.get('team_b')
    players_a = data.get('players_a', [])
    players_b = data.get('players_b', [])
    picks_a = data.get('picks_a', [])
    picks_b = data.get('picks_b', [])

    if not team_a or not team_b:
        return jsonify({"error": "Both teams must be specified"}), 400

    if team_a not in teams or team_b not in teams:
        return jsonify({"error": "One or both teams not found"}), 404

    # Find players
    found_players_a = []
    found_players_b = []

    for name in players_a:
        for p in teams[team_a].players:
            if p.name.lower() == name.lower():
                found_players_a.append(p)
                break

    for name in players_b:
        for p in teams[team_b].players:
            if p.name.lower() == name.lower():
                found_players_b.append(p)
                break

    # Calculate values
    value_a_sends = sum(calculator.calculate_player_value(p) for p in found_players_a)
    value_b_sends = sum(calculator.calculate_player_value(p) for p in found_players_b)

    # Add pick values
    for pick in picks_a:
        value_a_sends += DynastyValueCalculator.calculate_pick_value(pick)
    for pick in picks_b:
        value_b_sends += DynastyValueCalculator.calculate_pick_value(pick)

    value_diff = abs(value_a_sends - value_b_sends)

    # Determine verdict
    if value_diff < 5:
        verdict = "Fair Trade"
    elif value_diff < 15:
        verdict = "Slightly Uneven"
    elif value_diff < 25:
        verdict = "Questionable"
    else:
        verdict = "Unfair Trade"

    # Generate comprehensive analysis
    if value_a_sends > value_b_sends:
        winner = team_b
        loser = team_a
    else:
        winner = team_a
        loser = team_b

    # Basic reasoning
    if value_diff < 5:
        reasoning = "This trade is well-balanced. Both sides receive comparable value."
    elif value_diff < 15:
        reasoning = f"Slight edge to {winner}, but within acceptable range for a fair trade."
    else:
        reasoning = f"{winner} wins this trade by a significant margin ({value_diff:.1f} points). {loser} should reconsider."

    # Age analysis
    avg_age_a_sends = sum(p.age for p in found_players_a) / len(found_players_a) if found_players_a else 0
    avg_age_b_sends = sum(p.age for p in found_players_b) / len(found_players_b) if found_players_b else 0

    age_analysis = ""
    if avg_age_a_sends and avg_age_b_sends:
        age_diff = avg_age_a_sends - avg_age_b_sends
        # If team_a sends OLDER players (age_diff > 0), team_a RECEIVES younger players
        # If team_a sends YOUNGER players (age_diff < 0), team_b RECEIVES younger players
        if abs(age_diff) >= 3:
            team_getting_younger = team_a if age_diff > 0 else team_b
            team_getting_older = team_b if age_diff > 0 else team_a
            younger_age = min(avg_age_a_sends, avg_age_b_sends)
            older_age = max(avg_age_a_sends, avg_age_b_sends)
            age_analysis = f"{team_getting_younger} gets younger assets (receives avg {younger_age:.1f} yrs, sends {older_age:.1f} yrs). "
        elif abs(age_diff) >= 1:
            team_getting_younger = team_a if age_diff > 0 else team_b
            age_analysis = f"Slight age advantage to {team_getting_younger}. "

    # Position analysis
    positions_a_sends = [p.position.split('/')[0] if '/' in p.position else p.position for p in found_players_a]
    positions_b_sends = [p.position.split('/')[0] if '/' in p.position else p.position for p in found_players_b]

    position_analysis = ""
    pos_a_summary = ", ".join(set(positions_a_sends)) if positions_a_sends else "picks only"
    pos_b_summary = ", ".join(set(positions_b_sends)) if positions_b_sends else "picks only"
    position_analysis = f"{team_a} sends {pos_a_summary}; {team_b} sends {pos_b_summary}. "

    # Prospect analysis
    prospects_a = [p for p in found_players_a if p.is_prospect]
    prospects_b = [p for p in found_players_b if p.is_prospect]
    proven_a = [p for p in found_players_a if not p.is_prospect]
    proven_b = [p for p in found_players_b if not p.is_prospect]

    prospect_analysis = ""
    if prospects_a and not prospects_b:
        prospect_analysis = f"{team_a} trades away prospect potential for proven production. "
    elif prospects_b and not prospects_a:
        prospect_analysis = f"{team_b} trades away prospect potential for proven production. "
    elif prospects_a and prospects_b:
        prospect_analysis = "Both sides exchanging prospect value. "

    # Comprehensive stat breakdown for both sides
    def get_player_stats(players):
        stats = {
            # Hitting
            'HR': sum(HITTER_PROJECTIONS.get(p.name, {}).get('HR', 0) for p in players),
            'RBI': sum(HITTER_PROJECTIONS.get(p.name, {}).get('RBI', 0) for p in players),
            'R': sum(HITTER_PROJECTIONS.get(p.name, {}).get('R', 0) for p in players),
            'SB': sum(HITTER_PROJECTIONS.get(p.name, {}).get('SB', 0) for p in players),
            'SO': sum(HITTER_PROJECTIONS.get(p.name, {}).get('SO', 0) for p in players),  # Hitter strikeouts
            'AVG': 0,
            'OPS': 0,
            # Pitching
            'K': sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in players),
            'BB': sum((PITCHER_PROJECTIONS.get(p.name, {}).get('BB', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('BB', 0)) for p in players),
            'ERA': 0,
            'WHIP': 0,
            'SV': sum(RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) for p in players),
            'HLD': sum(RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0) for p in players),
            'QS': sum(PITCHER_PROJECTIONS.get(p.name, {}).get('QS', 0) for p in players),
            'W': sum((PITCHER_PROJECTIONS.get(p.name, {}).get('W', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('W', 0)) for p in players),
            'L': sum((PITCHER_PROJECTIONS.get(p.name, {}).get('L', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('L', 0)) for p in players),  # Losses
            'IP': sum((PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('IP', 0)) for p in players),
        }
        # Calculate K/BB ratio
        stats['K/BB'] = stats['K'] / stats['BB'] if stats['BB'] > 0 else 0

        # Calculate weighted AVG and OPS
        total_ab = sum(HITTER_PROJECTIONS.get(p.name, {}).get('AB', 0) for p in players)
        if total_ab > 0:
            stats['AVG'] = sum(HITTER_PROJECTIONS.get(p.name, {}).get('AVG', 0) * HITTER_PROJECTIONS.get(p.name, {}).get('AB', 0) for p in players) / total_ab
            stats['OPS'] = sum(HITTER_PROJECTIONS.get(p.name, {}).get('OPS', 0) * HITTER_PROJECTIONS.get(p.name, {}).get('AB', 0) for p in players) / total_ab
        # Calculate weighted ERA and WHIP
        if stats['IP'] > 0:
            total_er = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('ERA', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('ERA', 0)) * (PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('IP', 0)) / 9 for p in players)
            stats['ERA'] = (total_er * 9) / stats['IP'] if stats['IP'] > 0 else 0
            total_whip_ip = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('WHIP', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('WHIP', 0)) * (PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('IP', 0)) for p in players)
            stats['WHIP'] = total_whip_ip / stats['IP'] if stats['IP'] > 0 else 0
        return stats

    stats_a = get_player_stats(found_players_a)
    stats_b = get_player_stats(found_players_b)

    # Calculate stat differences (positive = team_a gains, negative = team_b gains)
    stat_diffs = {}
    for stat in stats_a:
        diff = stats_b[stat] - stats_a[stat]  # What team_a receives minus what they send
        stat_diffs[stat] = round(diff, 3) if stat in ['AVG', 'OPS', 'ERA', 'WHIP', 'K/BB'] else int(diff)

    # Category impact analysis with more detail
    cat_impacts = []
    # Hitting categories
    if abs(stat_diffs['HR']) >= 5:
        winner = team_a if stat_diffs['HR'] > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['HR'])} HR")
    if abs(stat_diffs['SB']) >= 5:
        winner = team_a if stat_diffs['SB'] > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['SB'])} SB")
    if abs(stat_diffs['RBI']) >= 20:
        winner = team_a if stat_diffs['RBI'] > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['RBI'])} RBI")
    if abs(stat_diffs['R']) >= 20:
        winner = team_a if stat_diffs['R'] > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['R'])} R")
    # SO - lower is better, so negative diff is good for team_a
    if abs(stat_diffs['SO']) >= 15:
        winner = team_a if stat_diffs['SO'] < 0 else team_b  # Lower SO is better
        cat_impacts.append(f"{winner} reduces SO by {abs(stat_diffs['SO'])}")

    # Pitching categories
    if abs(stat_diffs['K']) >= 30:
        winner = team_a if stat_diffs['K'] > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['K'])} K")
    if abs(stat_diffs['SV'] + stat_diffs['HLD']) >= 5:
        winner = team_a if (stat_diffs['SV'] + stat_diffs['HLD']) > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['SV'] + stat_diffs['HLD'])} SV+HLD")
    if abs(stat_diffs['QS']) >= 5:
        winner = team_a if stat_diffs['QS'] > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['QS'])} QS")
    # L - lower is better, so negative diff is good for team_a
    if abs(stat_diffs['L']) >= 3:
        winner = team_a if stat_diffs['L'] < 0 else team_b  # Fewer losses is better
        cat_impacts.append(f"{winner} reduces L by {abs(stat_diffs['L'])}")
    # K/BB - higher is better
    if abs(stat_diffs['K/BB']) >= 0.5:
        winner = team_a if stat_diffs['K/BB'] > 0 else team_b
        cat_impacts.append(f"{winner} improves K/BB by {abs(stat_diffs['K/BB']):.2f}")

    category_analysis = ""
    if cat_impacts:
        category_analysis = "Category impact: " + "; ".join(cat_impacts) + ". "

    # Team window analysis
    draft_order, power_rankings, team_totals = get_team_rankings()
    rank_a = power_rankings.get(team_a, 6)
    rank_b = power_rankings.get(team_b, 6)

    window_analysis = ""
    if rank_a <= 3 and rank_b >= 9:
        if avg_age_a_sends < avg_age_b_sends:
            window_analysis = f"Classic contender ({team_a}) / rebuilder ({team_b}) swap - makes sense for both windows. "
        else:
            window_analysis = f"Unusual: contender ({team_a}) getting older assets from rebuilder ({team_b}). "
    elif rank_b <= 3 and rank_a >= 9:
        if avg_age_b_sends < avg_age_a_sends:
            window_analysis = f"Classic contender ({team_b}) / rebuilder ({team_a}) swap - makes sense for both windows. "
        else:
            window_analysis = f"Unusual: contender ({team_b}) getting older assets from rebuilder ({team_a}). "

    # Combine detailed analysis
    detailed_analysis = f"{reasoning}\n\n"
    if age_analysis:
        detailed_analysis += age_analysis
    if position_analysis:
        detailed_analysis += position_analysis
    if prospect_analysis:
        detailed_analysis += prospect_analysis
    if category_analysis:
        detailed_analysis += "\n\n" + category_analysis
    if window_analysis:
        detailed_analysis += "\n\n" + window_analysis

    # Trade recommendation
    recommendation = ""
    if value_diff < 5:
        recommendation = "Recommended for both teams"
    elif value_diff < 10:
        recommendation = f"Acceptable for {winner}, decent for {loser}"
    elif value_diff < 20:
        recommendation = f"Good for {winner}, {loser} should seek more"
    else:
        recommendation = f"{loser} should decline unless addressing urgent need"

    # Generate counter-offer suggestions
    counter_offer_suggestions = []

    if value_diff >= 5:
        # Calculate what would make the trade fair
        gap = value_diff

        # Suggest picks to close the gap
        if gap >= 25:
            counter_offer_suggestions.append({
                'for_team': loser,
                'suggestion': f"Ask {winner} to add a 1st Round pick (~30 value) to balance",
                'value_add': 30
            })
        elif gap >= 15:
            counter_offer_suggestions.append({
                'for_team': loser,
                'suggestion': f"Ask {winner} to add a 2nd Round pick (~18 value) to balance",
                'value_add': 18
            })
        elif gap >= 8:
            counter_offer_suggestions.append({
                'for_team': loser,
                'suggestion': f"Ask {winner} to add a 3rd Round pick (~10 value) to balance",
                'value_add': 10
            })
        else:
            counter_offer_suggestions.append({
                'for_team': loser,
                'suggestion': f"Ask {winner} to add a 4th/5th Round pick to balance the {gap:.0f} pt gap",
                'value_add': 5
            })

        # Suggest removing a player to close the gap
        if loser == team_a and found_players_a:
            smallest = min(found_players_a, key=lambda p: calculator.calculate_player_value(p))
            smallest_val = calculator.calculate_player_value(smallest)
            if smallest_val <= gap * 1.5 and smallest_val >= gap * 0.5:
                counter_offer_suggestions.append({
                    'for_team': loser,
                    'suggestion': f"Remove {smallest.name} ({smallest_val:.0f}) from your side to reduce what you're giving up",
                    'value_add': smallest_val
                })
        elif loser == team_b and found_players_b:
            smallest = min(found_players_b, key=lambda p: calculator.calculate_player_value(p))
            smallest_val = calculator.calculate_player_value(smallest)
            if smallest_val <= gap * 1.5 and smallest_val >= gap * 0.5:
                counter_offer_suggestions.append({
                    'for_team': loser,
                    'suggestion': f"Remove {smallest.name} ({smallest_val:.0f}) from your side to reduce what you're giving up",
                    'value_add': smallest_val
                })

        # Find a player from winner's team that could be added
        winner_team = teams.get(winner)
        if winner_team:
            candidates = [(p, calculator.calculate_player_value(p)) for p in winner_team.players
                         if not any(fp.name == p.name for fp in (found_players_a if winner == team_a else found_players_b))]
            candidates.sort(key=lambda x: abs(x[1] - gap))

            if candidates:
                best_fit = candidates[0]
                if abs(best_fit[1] - gap) <= gap * 0.5:  # Within 50% of gap
                    counter_offer_suggestions.append({
                        'for_team': loser,
                        'suggestion': f"Ask {winner} to add {best_fit[0].name} ({best_fit[1]:.0f} value) to balance",
                        'value_add': best_fit[1]
                    })

    # Window-specific advice
    window_advice = []
    if rank_a <= 4 and rank_b >= 9:
        if prospects_a:
            window_advice.append(f"{team_a} is contending - trading prospects for proven talent makes sense for your window")
        if proven_b:
            window_advice.append(f"{team_b} is rebuilding - acquiring young assets/prospects for veterans aligns with your rebuild")
    elif rank_b <= 4 and rank_a >= 9:
        if prospects_b:
            window_advice.append(f"{team_b} is contending - trading prospects for proven talent makes sense for your window")
        if proven_a:
            window_advice.append(f"{team_a} is rebuilding - acquiring young assets/prospects for veterans aligns with your rebuild")

    # Category fit analysis for each team
    team_a_cats, team_a_pos, team_a_window = calculate_team_needs(team_a)
    team_b_cats, team_b_pos, team_b_window = calculate_team_needs(team_b)

    category_fit = {
        'team_a': {
            'window': team_a_window,
            'helps_weaknesses': [],
            'hurts_strengths': []
        },
        'team_b': {
            'window': team_b_window,
            'helps_weaknesses': [],
            'hurts_strengths': []
        }
    }

    # Check if trade helps team A's weaknesses
    for cat, score in team_a_cats.items():
        if score < 0:  # Team A weak in this category
            # Check if players from B help this
            if cat in ['HR', 'SB', 'RBI', 'R']:
                gain = sum(HITTER_PROJECTIONS.get(p.name, {}).get(cat, 0) for p in found_players_b)
                loss = sum(HITTER_PROJECTIONS.get(p.name, {}).get(cat, 0) for p in found_players_a)
                if gain > loss:
                    category_fit['team_a']['helps_weaknesses'].append(f"+{gain - loss:.0f} {cat}")
            elif cat == 'K':
                gain = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in found_players_b)
                loss = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in found_players_a)
                if gain > loss:
                    category_fit['team_a']['helps_weaknesses'].append(f"+{gain - loss:.0f} K")

    # Check if trade helps team B's weaknesses
    for cat, score in team_b_cats.items():
        if score < 0:  # Team B weak in this category
            if cat in ['HR', 'SB', 'RBI', 'R']:
                gain = sum(HITTER_PROJECTIONS.get(p.name, {}).get(cat, 0) for p in found_players_a)
                loss = sum(HITTER_PROJECTIONS.get(p.name, {}).get(cat, 0) for p in found_players_b)
                if gain > loss:
                    category_fit['team_b']['helps_weaknesses'].append(f"+{gain - loss:.0f} {cat}")
            elif cat == 'K':
                gain = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in found_players_a)
                loss = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in found_players_b)
                if gain > loss:
                    category_fit['team_b']['helps_weaknesses'].append(f"+{gain - loss:.0f} K")

    # Build player details for each side
    players_a_details = [{
        "name": p.name,
        "position": p.position,
        "age": p.age,
        "value": round(calculator.calculate_player_value(p), 1),
        "is_prospect": p.is_prospect,
        "prospect_rank": p.prospect_rank if p.is_prospect else None
    } for p in found_players_a]

    players_b_details = [{
        "name": p.name,
        "position": p.position,
        "age": p.age,
        "value": round(calculator.calculate_player_value(p), 1),
        "is_prospect": p.is_prospect,
        "prospect_rank": p.prospect_rank if p.is_prospect else None
    } for p in found_players_b]

    return jsonify({
        "verdict": verdict,
        "value_a_receives": round(value_b_sends, 1),
        "value_b_receives": round(value_a_sends, 1),
        "value_diff": round(value_diff, 1),
        "reasoning": reasoning,
        "detailed_analysis": detailed_analysis,
        "age_analysis": {
            "team_a_sends_avg_age": round(avg_age_a_sends, 1) if avg_age_a_sends else None,
            "team_b_sends_avg_age": round(avg_age_b_sends, 1) if avg_age_b_sends else None,
        },
        "category_impact": cat_impacts,
        "recommendation": recommendation,
        "counter_offer_suggestions": counter_offer_suggestions,
        "window_advice": window_advice,
        "category_fit": category_fit,
        "players_a": players_a_details,
        "players_b": players_b_details,
        "picks_a": picks_a,
        "picks_b": picks_b,
        "stat_comparison": {
            "team_a_sends": {k: round(v, 3) if isinstance(v, float) else v for k, v in stats_a.items()},
            "team_b_sends": {k: round(v, 3) if isinstance(v, float) else v for k, v in stats_b.items()},
            "net_for_team_a": stat_diffs
        }
    })


def calculate_team_needs(team_name):
    """Calculate a team's category needs and positional depth."""
    team = teams.get(team_name)
    if not team:
        return {}, {}, "unknown"

    # Calculate category totals
    total_hr = sum(HITTER_PROJECTIONS.get(p.name, {}).get('HR', 0) for p in team.players)
    total_sb = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SB', 0) for p in team.players)
    total_rbi = sum(HITTER_PROJECTIONS.get(p.name, {}).get('RBI', 0) for p in team.players)
    total_runs = sum(HITTER_PROJECTIONS.get(p.name, {}).get('R', 0) for p in team.players)
    total_k = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in team.players)
    total_sv_hld = sum((RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) + RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0)) for p in team.players)
    total_ip = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) for p in team.players)

    # Calculate weighted ERA and WHIP
    total_era_weighted = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('ERA', 0) * PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) for p in team.players)
    total_whip_weighted = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('WHIP', 0) * PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) for p in team.players)
    avg_era = total_era_weighted / total_ip if total_ip > 0 else 4.50
    avg_whip = total_whip_weighted / total_ip if total_ip > 0 else 1.30

    # Define thresholds for needs (lower = more need, higher = strength)
    # Scores from -2 (desperate need) to +2 (major strength)
    category_scores = {}
    category_scores['HR'] = 2 if total_hr >= 250 else (1 if total_hr >= 200 else (0 if total_hr >= 170 else (-1 if total_hr >= 140 else -2)))
    category_scores['SB'] = 2 if total_sb >= 130 else (1 if total_sb >= 100 else (0 if total_sb >= 75 else (-1 if total_sb >= 50 else -2)))
    category_scores['RBI'] = 2 if total_rbi >= 700 else (1 if total_rbi >= 600 else (0 if total_rbi >= 500 else (-1 if total_rbi >= 400 else -2)))
    category_scores['R'] = 2 if total_runs >= 700 else (1 if total_runs >= 600 else (0 if total_runs >= 500 else (-1 if total_runs >= 400 else -2)))
    category_scores['K'] = 2 if total_k >= 1400 else (1 if total_k >= 1200 else (0 if total_k >= 1000 else (-1 if total_k >= 800 else -2)))
    category_scores['SV+HLD'] = 2 if total_sv_hld >= 80 else (1 if total_sv_hld >= 60 else (0 if total_sv_hld >= 40 else (-1 if total_sv_hld >= 25 else -2)))
    category_scores['ERA'] = 2 if avg_era <= 3.50 else (1 if avg_era <= 3.80 else (0 if avg_era <= 4.10 else (-1 if avg_era <= 4.40 else -2)))
    category_scores['WHIP'] = 2 if avg_whip <= 1.15 else (1 if avg_whip <= 1.22 else (0 if avg_whip <= 1.30 else (-1 if avg_whip <= 1.38 else -2)))

    # Positional depth (count rostered players by position group)
    pos_depth = {'C': 0, '1B': 0, '2B': 0, 'SS': 0, '3B': 0, 'OF': 0, 'SP': 0, 'RP': 0}
    for p in team.players:
        pos = p.position.upper() if p.position else ''
        if 'C' in pos and '1B' not in pos and 'CF' not in pos:
            pos_depth['C'] += 1
        if '1B' in pos:
            pos_depth['1B'] += 1
        if '2B' in pos:
            pos_depth['2B'] += 1
        if 'SS' in pos:
            pos_depth['SS'] += 1
        if '3B' in pos:
            pos_depth['3B'] += 1
        if 'OF' in pos or 'LF' in pos or 'CF' in pos or 'RF' in pos:
            pos_depth['OF'] += 1
        if 'SP' in pos:
            pos_depth['SP'] += 1
        if 'RP' in pos or 'CL' in pos:
            pos_depth['RP'] += 1

    # Determine competitive window - USE SAME LOGIC AS TEAM ANALYSIS
    # to ensure consistency across the app
    ages = [p.age for p in team.players if p.age > 0]
    avg_age = sum(ages) / len(ages) if ages else 27
    prospects = len([p for p in team.players if p.is_prospect])

    players_with_value = [(p, calculator.calculate_player_value(p)) for p in team.players]
    total_value = sum(v for _, v in players_with_value)

    # Get power ranking for consistent window determination
    _, power_rankings, _ = get_team_rankings()
    power_rank = power_rankings.get(team_name, 6)
    total_teams = len(teams)
    top_third = total_teams // 3
    bottom_third = total_teams - top_third

    # Age profile flags (same as team analysis)
    is_young_roster = avg_age <= 26.5
    is_old_roster = avg_age >= 29.5

    # Window determination - MATCHES generate_team_analysis() logic
    if power_rank <= top_third:  # Top third of league
        if is_young_roster:
            window = "dynasty"
        elif is_old_roster:
            window = "win-now"
        else:
            window = "contender"
    elif power_rank >= bottom_third:  # Bottom third
        if is_old_roster:
            window = "teardown"
        elif is_young_roster:
            window = "rebuilding"
        else:
            window = "retooling"
    else:  # Middle third
        if is_young_roster:
            window = "rising"
        elif is_old_roster:
            window = "declining"
        else:
            window = "competitive"

    return category_scores, pos_depth, window


def get_player_categories(player):
    """Get the category contributions for a player."""
    proj = HITTER_PROJECTIONS.get(player.name, {})
    if proj:
        return {
            'type': 'hitter',
            'HR': proj.get('HR', 0),
            'SB': proj.get('SB', 0),
            'RBI': proj.get('RBI', 0),
            'R': proj.get('R', 0),
        }
    proj = PITCHER_PROJECTIONS.get(player.name, {})
    if proj:
        return {
            'type': 'pitcher',
            'K': proj.get('K', 0),
            'ERA': proj.get('ERA', 4.50),
            'WHIP': proj.get('WHIP', 1.30),
            'IP': proj.get('IP', 0),
        }
    proj = RELIEVER_PROJECTIONS.get(player.name, {})
    if proj:
        return {
            'type': 'reliever',
            'K': proj.get('K', 0),
            'SV': proj.get('SV', 0),
            'HLD': proj.get('HD', 0),
            'ERA': proj.get('ERA', 4.00),
            'WHIP': proj.get('WHIP', 1.25),
        }
    return {'type': 'unknown'}


def score_trade_fit(my_team_name, their_team_name, you_send, you_receive, value_diff):
    """Score how well a trade fits both teams' needs. Returns (score, reasons)."""
    my_cats, my_pos, my_window = calculate_team_needs(my_team_name)
    their_cats, their_pos, their_window = calculate_team_needs(their_team_name)

    score = 100  # Start with base score
    reasons = []

    # Penalize for value difference (0-15 range typical)
    fairness_penalty = value_diff * 2
    score -= fairness_penalty

    # Calculate category changes for my team
    my_cat_gains = {'HR': 0, 'SB': 0, 'RBI': 0, 'R': 0, 'K': 0, 'SV+HLD': 0}
    my_cat_losses = {'HR': 0, 'SB': 0, 'RBI': 0, 'R': 0, 'K': 0, 'SV+HLD': 0}

    for p in you_receive:
        cats = get_player_categories(p)
        if cats['type'] == 'hitter':
            my_cat_gains['HR'] += cats.get('HR', 0)
            my_cat_gains['SB'] += cats.get('SB', 0)
            my_cat_gains['RBI'] += cats.get('RBI', 0)
            my_cat_gains['R'] += cats.get('R', 0)
        elif cats['type'] in ['pitcher', 'reliever']:
            my_cat_gains['K'] += cats.get('K', 0)
            if cats['type'] == 'reliever':
                my_cat_gains['SV+HLD'] += cats.get('SV', 0) + cats.get('HLD', 0)

    for p in you_send:
        cats = get_player_categories(p)
        if cats['type'] == 'hitter':
            my_cat_losses['HR'] += cats.get('HR', 0)
            my_cat_losses['SB'] += cats.get('SB', 0)
            my_cat_losses['RBI'] += cats.get('RBI', 0)
            my_cat_losses['R'] += cats.get('R', 0)
        elif cats['type'] in ['pitcher', 'reliever']:
            my_cat_losses['K'] += cats.get('K', 0)
            if cats['type'] == 'reliever':
                my_cat_losses['SV+HLD'] += cats.get('SV', 0) + cats.get('HLD', 0)

    # Score based on filling needs vs losing strengths
    for cat in ['HR', 'SB', 'RBI', 'R', 'K', 'SV+HLD']:
        net_change = my_cat_gains[cat] - my_cat_losses[cat]
        need_score = my_cats.get(cat, 0)

        if net_change > 0 and need_score < 0:
            # Gaining in an area of need - big bonus!
            bonus = min(20, net_change * abs(need_score) * 2)
            score += bonus
            if need_score <= -1:
                reasons.append(f"+{net_change:.0f} {cat} (fills need)")
        elif net_change < 0 and need_score >= 1:
            # Losing in an area of strength - acceptable
            score += 5  # Small bonus for trading from strength
        elif net_change < 0 and need_score < 0:
            # Losing in an area of need - penalty
            penalty = min(15, abs(net_change) * abs(need_score))
            score -= penalty

    # Age-based adjustments based on window
    avg_age_receive = sum(p.age for p in you_receive if p.age > 0) / len(you_receive) if you_receive else 27
    avg_age_send = sum(p.age for p in you_send if p.age > 0) / len(you_send) if you_send else 27
    age_diff = avg_age_send - avg_age_receive  # Positive = getting younger

    if my_window in ['rebuilding', 'rising', 'dynasty']:
        if age_diff > 2:
            score += 10
            reasons.append("Gets younger")
        elif age_diff < -3:
            score -= 10
    elif my_window in ['win-now', 'contender']:
        if age_diff < -1 and avg_age_receive <= 32:
            score += 5  # Getting proven vets is fine for contenders

    # Prospect acquisition bonus for rebuilding teams
    prospects_gained = len([p for p in you_receive if p.is_prospect])
    prospects_lost = len([p for p in you_send if p.is_prospect])
    if my_window in ['rebuilding', 'rising']:
        if prospects_gained > prospects_lost:
            score += 8 * (prospects_gained - prospects_lost)
            reasons.append(f"+{prospects_gained - prospects_lost} prospects")
    elif my_window in ['win-now', 'contender']:
        if prospects_lost > prospects_gained:
            score += 5  # Trading prospects for talent is fine for contenders

    # Check if trade makes sense for the other team too (more likely to be accepted)
    their_benefits = []
    for p in you_send:
        cats = get_player_categories(p)
        if cats['type'] == 'hitter':
            for cat in ['HR', 'SB', 'RBI']:
                if their_cats.get(cat, 0) < 0 and cats.get(cat, 0) > 15:
                    their_benefits.append(cat)
        elif cats['type'] in ['pitcher', 'reliever']:
            if their_cats.get('K', 0) < 0 and cats.get('K', 0) > 80:
                their_benefits.append('K')

    if their_benefits:
        score += 5
        reasons.append(f"Fills their need: {', '.join(set(their_benefits))}")

    # Position swap bonus (like-for-like is easier to justify)
    send_positions = set()
    receive_positions = set()
    for p in you_send:
        pos = p.position.upper() if p.position else ''
        if 'SP' in pos:
            send_positions.add('SP')
        elif 'RP' in pos:
            send_positions.add('RP')
        else:
            send_positions.add('Hitter')
    for p in you_receive:
        pos = p.position.upper() if p.position else ''
        if 'SP' in pos:
            receive_positions.add('SP')
        elif 'RP' in pos:
            receive_positions.add('RP')
        else:
            receive_positions.add('Hitter')

    if send_positions == receive_positions:
        score += 3

    # Window compatibility bonus - complementary windows make better trade partners
    complementary_windows = {
        ('rebuilding', 'win-now'), ('rebuilding', 'contender'),
        ('win-now', 'rebuilding'), ('contender', 'rebuilding'),
        ('rising', 'declining'), ('declining', 'rising'),
        ('teardown', 'contender'), ('contender', 'teardown'),
        ('teardown', 'win-now'), ('win-now', 'teardown')
    }
    if (my_window, their_window) in complementary_windows:
        score += 8
        reasons.append(f"Good trade partners ({my_window} /{their_window})")

    # Elite young talent acquisition bonus
    for p in you_receive:
        if p.age <= 25:
            pval = calculator.calculate_player_value(p)
            if pval >= 60:
                score += 12
                reasons.append(f"Acquires elite young star ({p.name})")
            elif pval >= 45:
                score += 6
                reasons.append(f"Gets rising star ({p.name})")

    # Top prospect trade detection
    top_prospects_received = [p for p in you_receive if p.is_prospect and p.prospect_rank and p.prospect_rank <= 50]
    if top_prospects_received:
        for prospect in top_prospects_received:
            score += 15 if prospect.prospect_rank <= 20 else 8
            if prospect.prospect_rank <= 20:
                reasons.append(f"Acquires TOP-20 prospect #{prospect.prospect_rank}")

    # "Steal" detection - getting significantly younger player at similar value
    if you_receive and you_send:
        best_received = max(you_receive, key=lambda p: calculator.calculate_player_value(p))
        best_sent = max(you_send, key=lambda p: calculator.calculate_player_value(p))
        val_received = calculator.calculate_player_value(best_received)
        val_sent = calculator.calculate_player_value(best_sent)
        if best_received.age <= 26 and best_sent.age >= 30 and val_received >= val_sent * 0.9:
            score += 10
            reasons.append(f"Getting younger at similar value")

    # Positional upgrade detection
    for p_recv in you_receive:
        recv_pos = p_recv.position.upper() if p_recv.position else ''
        recv_val = calculator.calculate_player_value(p_recv)
        for p_send in you_send:
            send_pos = p_send.position.upper() if p_send.position else ''
            send_val = calculator.calculate_player_value(p_send)
            # Same position, getting upgrade
            if recv_pos == send_pos and recv_val > send_val * 1.15:
                score += 5
                reasons.append(f"Positional upgrade at {recv_pos}")
                break

    return score, reasons


@app.route('/suggest')
def get_suggestions():
    try:
        my_team = request.args.get('my_team')
        target_team = request.args.get('target_team')
        trade_type = request.args.get('trade_type', 'any')
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 8))

        if not my_team or my_team not in teams:
            return jsonify({"error": "Invalid team specified"}), 400

        suggestions = []
        my_players = [(p, calculator.calculate_player_value(p)) for p in teams[my_team].players]
        my_players.sort(key=lambda x: x[1], reverse=True)
        my_tradeable = [(p, v) for p, v in my_players if 15 <= v <= 85][:12]  # Reduced from 15

        # Get my team's needs for insights
        my_cats, my_pos, my_window = calculate_team_needs(my_team)

        # If targeting all teams, we need to be more selective to avoid timeout
        all_teams_mode = not target_team
        target_teams = [target_team] if target_team else [t for t in teams.keys() if t != my_team]

        for other_team in target_teams:
            if other_team == my_team:
                continue

            their_players = [(p, calculator.calculate_player_value(p)) for p in teams[other_team].players]
            their_players.sort(key=lambda x: x[1], reverse=True)
            # Use fewer players when searching all teams
            max_tradeable = 8 if all_teams_mode else 12
            their_tradeable = [(p, v) for p, v in their_players if 15 <= v <= 85][:max_tradeable]

            # 1-for-1 trades
            if trade_type in ['any', '1-for-1']:
                for my_p, my_val in my_tradeable:
                    for their_p, their_val in their_tradeable:
                        diff = abs(my_val - their_val)
                        if diff < 12:  # Tighter threshold
                            # Skip full scoring in all-teams mode for speed
                            if all_teams_mode:
                                fit_score = 100 - diff * 2
                                reasons = []
                            else:
                                fit_score, reasons = score_trade_fit(
                                    my_team, other_team, [my_p], [their_p], diff
                                )
                            suggestions.append({
                                "my_team": my_team,
                                "other_team": other_team,
                                "you_send": [my_p.name],
                                "you_receive": [their_p.name],
                                "you_send_value": round(my_val, 1),
                                "you_receive_value": round(their_val, 1),
                                "value_diff": round(diff, 1),
                                "trade_type": "1-for-1",
                                "fit_score": round(fit_score, 1),
                                "reasons": reasons[:3]
                            })

            # 2-for-1 trades (you send 2, receive 1 better player) - skip in all-teams mode
            if trade_type in ['any', '2-for-1'] and not all_teams_mode:
                for i, (my_p1, my_v1) in enumerate(my_tradeable[:8]):
                    for my_p2, my_v2 in my_tradeable[i+1:8]:
                        combined_val = my_v1 + my_v2
                        for their_p, their_val in their_tradeable:
                            diff = abs(combined_val - their_val)
                            # 2-for-1 should get a better player (their_val > max of yours)
                            if diff < 18 and their_val > max(my_v1, my_v2) * 1.1:
                                fit_score, reasons = score_trade_fit(
                                    my_team, other_team, [my_p1, my_p2], [their_p], diff
                                )
                                suggestions.append({
                                    "my_team": my_team,
                                    "other_team": other_team,
                                    "you_send": [my_p1.name, my_p2.name],
                                    "you_receive": [their_p.name],
                                    "you_send_value": round(combined_val, 1),
                                    "you_receive_value": round(their_val, 1),
                                    "value_diff": round(diff, 1),
                                    "trade_type": "2-for-1",
                                    "fit_score": round(fit_score, 1),
                                    "reasons": reasons[:3]
                                })

            # 2-for-2 trades - skip in all-teams mode
            if trade_type in ['any', '2-for-2'] and not all_teams_mode:
                for i, (my_p1, my_v1) in enumerate(my_tradeable[:6]):
                    for my_p2, my_v2 in my_tradeable[i+1:6]:
                        my_combined = my_v1 + my_v2
                        for j, (their_p1, their_v1) in enumerate(their_tradeable[:6]):
                            for their_p2, their_v2 in their_tradeable[j+1:6]:
                                their_combined = their_v1 + their_v2
                                diff = abs(my_combined - their_combined)
                                if diff < 18:
                                    fit_score, reasons = score_trade_fit(
                                        my_team, other_team, [my_p1, my_p2], [their_p1, their_p2], diff
                                    )
                                    suggestions.append({
                                        "my_team": my_team,
                                        "other_team": other_team,
                                        "you_send": [my_p1.name, my_p2.name],
                                        "you_receive": [their_p1.name, their_p2.name],
                                        "you_send_value": round(my_combined, 1),
                                        "you_receive_value": round(their_combined, 1),
                                        "value_diff": round(diff, 1),
                                        "trade_type": "2-for-2",
                                        "fit_score": round(fit_score, 1),
                                        "reasons": reasons[:3]
                                    })

        # Sort by fit score (best fits first), not just value difference
        suggestions.sort(key=lambda x: x['fit_score'], reverse=True)
        suggestions = suggestions[:200]  # Cap at 200 total suggestions

        # Paginate
        paginated = suggestions[offset:offset + limit]
        has_more = len(suggestions) > offset + limit

        # Add team needs summary to response
        needs_summary = {
            'weaknesses': [cat for cat, score in my_cats.items() if score < 0],
            'strengths': [cat for cat, score in my_cats.items() if score > 0],
            'window': my_window
        }

        return jsonify({
            "suggestions": paginated,
            "has_more": has_more,
            "total_found": len(suggestions),
            "offset": offset,
            "limit": limit,
            "team_needs": needs_summary
        })
    except Exception as e:
        print(f"Error in get_suggestions: {e}")
        return jsonify({"error": f"Failed to generate suggestions: {str(e)}", "suggestions": []}), 500


@app.route('/free-agents')
def get_free_agent_suggestions():
    """Get AI-powered free agent recommendations based on team needs."""
    try:
        team_name = request.args.get('team')
        position_filter = request.args.get('position', '')

        # Helper function to detect undervalued gems and breakout candidates
        def detect_special_value(fa, fa_proj):
            """Detect undervalued gems and breakout candidates."""
            special_tags = []
            name = fa['name']
            age = fa['age']
            roster_pct = fa['roster_pct']
            dynasty_value = fa['dynasty_value']

            # Breakout candidate: young player with good projections but low ownership
            if age <= 26 and roster_pct < 50:
                if fa_proj:
                    hr = fa_proj.get('HR', 0)
                    sb = fa_proj.get('SB', 0)
                    k = fa_proj.get('K', 0)
                    if hr >= 20 or sb >= 20 or k >= 150:
                        special_tags.append("Breakout Candidate")

            # Undervalued gem: good projections but low dynasty value
            if dynasty_value < 40 and fa_proj:
                hr = fa_proj.get('HR', 0)
                rbi = fa_proj.get('RBI', 0)
                k = fa_proj.get('K', 0)
                era = fa_proj.get('ERA', 5.0)
                if hr >= 25 or rbi >= 80 or k >= 180 or (k >= 100 and era <= 3.50):
                    special_tags.append("Undervalued Gem")

            # Streaming candidate: pitcher with good ratios, low ownership
            if 'SP' in fa['position'].upper() and roster_pct < 40 and fa_proj:
                era = fa_proj.get('ERA', 5.0)
                whip = fa_proj.get('WHIP', 1.5)
                if era <= 4.00 and whip <= 1.25:
                    special_tags.append("Streaming Option")

            # Closer watch: RP who could get saves
            if 'RP' in fa['position'].upper() and fa_proj:
                sv = fa_proj.get('SV', 0)
                if sv >= 10:
                    special_tags.append("Closer Potential")

            # Dynasty sleeper: young with upside
            if age <= 24 and dynasty_value >= 30 and roster_pct < 30:
                special_tags.append("Dynasty Sleeper")

            return special_tags

        # If no team selected, return top 30 FAs by dynasty value
        if not team_name or team_name not in teams:
            filtered_fas = FREE_AGENTS
            if position_filter:
                filtered_fas = [fa for fa in FREE_AGENTS if position_filter in fa['position']]

            # Add basic scoring for non-team view
            scored_fas = []
            for fa in filtered_fas[:50]:  # Consider top 50, return 30
                score = fa['dynasty_value']
                reasons = []

                # Get projections for special value detection
                fa_proj = HITTER_PROJECTIONS.get(fa['name'], {}) or PITCHER_PROJECTIONS.get(fa['name'], {}) or RELIEVER_PROJECTIONS.get(fa['name'], {})

                # Age-based value
                if fa['age'] <= 26:
                    score += 10
                    reasons.append("Young upside")
                elif fa['age'] <= 29:
                    score += 5
                    reasons.append("Prime years")

                # High roster % indicates quality
                if fa['roster_pct'] >= 60:
                    score += 8
                    reasons.append(f"{fa['roster_pct']:.0f}% rostered")
                elif fa['roster_pct'] >= 40:
                    score += 4
                    reasons.append("Solid ownership")

                # Position scarcity bonus
                fa_pos = fa['position'].upper()
                if 'C' in fa_pos and '1B' not in fa_pos:
                    score += 5
                    reasons.append("Catcher scarcity")
                elif 'SS' in fa_pos:
                    score += 3
                    reasons.append("Premium position")

                # Detect special value (breakout, undervalued, etc.)
                special_tags = detect_special_value(fa, fa_proj)
                if special_tags:
                    score += 5 * len(special_tags)  # Bonus for special value
                    reasons.extend(special_tags)

                scored_fas.append({
                    **fa,
                    'fit_score': round(score, 1),
                    'reasons': reasons[:4],
                    'special_tags': special_tags
                })

            scored_fas.sort(key=lambda x: x['fit_score'], reverse=True)
            return jsonify({
                "suggestions": scored_fas[:30],
                "team_needs": None,
                "total_available": len(FREE_AGENTS)
            })

        # Team-specific recommendations with enhanced AI logic
        team_cats, team_pos, team_window = calculate_team_needs(team_name)
        weaknesses = [cat for cat, score in team_cats.items() if score < 0]
        strengths = [cat for cat, score in team_cats.items() if score > 0]

        # Get league-wide category rankings for this team
        all_team_cats, league_rankings = calculate_league_category_rankings()
        my_ranks = league_rankings.get(team_name, {})

        # Rank weaknesses by severity (worst rank first)
        ranked_weaknesses = sorted([(cat, my_ranks.get(cat, 6)) for cat in weaknesses],
                                   key=lambda x: -x[1])
        worst_cats = [cat for cat, rank in ranked_weaknesses[:3] if rank >= 8]

        # Calculate detailed positional depth
        pos_depth = {}
        pos_quality = {}  # Track quality at each position
        pos_age = {}  # Track average age at position
        team = teams[team_name]
        for p in team.players:
            pos = p.position.upper() if p.position else ''
            pval = calculator.calculate_player_value(p)
            for check_pos in ['C', '1B', '2B', 'SS', '3B', 'OF', 'SP', 'RP']:
                if check_pos in pos or (check_pos == 'OF' and any(x in pos for x in ['LF', 'CF', 'RF'])):
                    pos_depth[check_pos] = pos_depth.get(check_pos, 0) + 1
                    pos_quality[check_pos] = max(pos_quality.get(check_pos, 0), pval)
                    # Track ages for position age analysis
                    if check_pos not in pos_age:
                        pos_age[check_pos] = []
                    if p.age > 0:
                        pos_age[check_pos].append(p.age)

        positional_needs = [pos for pos in ['C', '1B', '2B', 'SS', '3B', 'OF', 'SP', 'RP']
                          if pos_depth.get(pos, 0) < 3]
        critical_needs = [pos for pos in ['C', '1B', '2B', 'SS', '3B', 'OF', 'SP', 'RP']
                        if pos_depth.get(pos, 0) < 2]

        # Identify aging positions (avg age > 30)
        aging_positions = [pos for pos, ages in pos_age.items()
                         if ages and sum(ages)/len(ages) > 30]

        # Calculate multi-category fit scores
        def calculate_multi_category_fit(fa_proj, is_hitter):
            """Score how well a player addresses multiple category needs."""
            fit_score = 0
            cats_addressed = []

            if is_hitter:
                for cat in worst_cats:
                    if cat == 'HR' and fa_proj.get('HR', 0) >= 15:
                        fit_score += 15
                        cats_addressed.append(f"HR ({fa_proj.get('HR', 0)})")
                    elif cat == 'SB' and fa_proj.get('SB', 0) >= 10:
                        fit_score += 15
                        cats_addressed.append(f"SB ({fa_proj.get('SB', 0)})")
                    elif cat == 'RBI' and fa_proj.get('RBI', 0) >= 60:
                        fit_score += 12
                        cats_addressed.append(f"RBI ({fa_proj.get('RBI', 0)})")
                    elif cat == 'R' and fa_proj.get('R', 0) >= 60:
                        fit_score += 12
                        cats_addressed.append(f"R ({fa_proj.get('R', 0)})")
                    elif cat == 'AVG' and fa_proj.get('AVG', 0) >= .280:
                        fit_score += 10
                        cats_addressed.append(f"AVG ({fa_proj.get('AVG', 0):.3f})")
                    elif cat == 'OPS' and fa_proj.get('OPS', 0) >= .800:
                        fit_score += 10
                        cats_addressed.append(f"OPS ({fa_proj.get('OPS', 0):.3f})")
                    elif cat == 'SO' and fa_proj.get('SO', 0) <= 100:  # Lower is better
                        fit_score += 8
                        cats_addressed.append(f"Low K ({fa_proj.get('SO', 0)})")
            else:
                for cat in worst_cats:
                    if cat == 'K' and fa_proj.get('K', 0) >= 100:
                        fit_score += 15
                        cats_addressed.append(f"K ({fa_proj.get('K', 0)})")
                    elif cat == 'QS' and fa_proj.get('QS', 0) >= 10:
                        fit_score += 15
                        cats_addressed.append(f"QS ({fa_proj.get('QS', 0)})")
                    elif cat == 'ERA' and fa_proj.get('ERA', 5.0) <= 4.00:
                        fit_score += 12
                        cats_addressed.append(f"ERA ({fa_proj.get('ERA', 0):.2f})")
                    elif cat == 'WHIP' and fa_proj.get('WHIP', 1.5) <= 1.25:
                        fit_score += 12
                        cats_addressed.append(f"WHIP ({fa_proj.get('WHIP', 0):.2f})")
                    elif cat == 'SV+HLD':
                        sv_hld = fa_proj.get('SV', 0) + fa_proj.get('HD', 0)
                        if sv_hld >= 15:
                            fit_score += 15
                            cats_addressed.append(f"SV+HLD ({sv_hld})")
                    elif cat == 'W' and fa_proj.get('W', 0) >= 8:
                        fit_score += 10
                        cats_addressed.append(f"W ({fa_proj.get('W', 0)})")
                    elif cat == 'L':  # Lower is better
                        if fa_proj.get('L', 10) <= 8 and fa_proj.get('IP', 0) >= 100:
                            fit_score += 8
                            cats_addressed.append(f"Low L ({fa_proj.get('L', 0)})")

            # Bonus for addressing multiple categories
            if len(cats_addressed) >= 2:
                fit_score += 10  # Multi-category bonus
            if len(cats_addressed) >= 3:
                fit_score += 10  # Even bigger bonus for 3+

            return fit_score, cats_addressed

        # Enhanced scoring for team-specific recommendations
        scored_fas = []
        for fa in FREE_AGENTS:
            if position_filter and position_filter not in fa['position']:
                continue

            base_score = fa['dynasty_value']
            score = base_score
            reasons = []
            fit_explanation = []

            fa_pos = fa['position'].upper()
            is_hitter = any(pos in fa_pos for pos in ['C', '1B', '2B', 'SS', '3B', 'OF', 'LF', 'CF', 'RF', 'DH'])
            is_sp = 'SP' in fa_pos
            is_rp = 'RP' in fa_pos

            # Get FA's projected stats from our projections if available
            fa_proj = HITTER_PROJECTIONS.get(fa['name'], {}) or PITCHER_PROJECTIONS.get(fa['name'], {}) or RELIEVER_PROJECTIONS.get(fa['name'], {})

            # Multi-category fit analysis
            multi_fit_score, cats_addressed = calculate_multi_category_fit(fa_proj, is_hitter)
            if multi_fit_score > 0:
                score += multi_fit_score
                if len(cats_addressed) >= 2:
                    reasons.append(f"Addresses {len(cats_addressed)} needs")
                    fit_explanation.extend(cats_addressed)

            # Category need bonus with specific stat matching
            if is_hitter:
                hr_proj = fa_proj.get('HR', 0)
                sb_proj = fa_proj.get('SB', 0)
                rbi_proj = fa_proj.get('RBI', 0)
                avg_proj = fa_proj.get('AVG', 0)

                if 'HR' in weaknesses and hr_proj >= 20:
                    if 'HR' not in str(cats_addressed):
                        score += 20
                        reasons.append(f"+{hr_proj} HR projected")
                elif 'HR' in weaknesses and hr_proj >= 15:
                    if 'HR' not in str(cats_addressed):
                        score += 12

                if 'SB' in weaknesses and sb_proj >= 15:
                    if 'SB' not in str(cats_addressed):
                        score += 20
                        reasons.append(f"+{sb_proj} SB projected")
                elif 'SB' in weaknesses and sb_proj >= 10:
                    if 'SB' not in str(cats_addressed):
                        score += 12

                if 'RBI' in weaknesses and rbi_proj >= 70:
                    if 'RBI' not in str(cats_addressed):
                        score += 15
                        reasons.append(f"Run producer ({rbi_proj} RBI)")

                # Power + speed combo detection
                if hr_proj >= 15 and sb_proj >= 15:
                    score += 10
                    reasons.append(f"Power/Speed combo")

            if is_sp:
                k_proj = fa_proj.get('K', 0)
                era_proj = fa_proj.get('ERA', 5.0)
                qs_proj = fa_proj.get('QS', 0)
                ip_proj = fa_proj.get('IP', 0)

                if 'K' in weaknesses and k_proj >= 150:
                    if 'K' not in str(cats_addressed):
                        score += 20
                        reasons.append(f"Strikeout arm ({k_proj} K)")
                elif 'K' in weaknesses and k_proj >= 100:
                    if 'K' not in str(cats_addressed):
                        score += 12

                if 'ERA' in weaknesses and era_proj <= 3.50:
                    if 'ERA' not in str(cats_addressed):
                        score += 15
                        reasons.append(f"Elite ratios ({era_proj:.2f} ERA)")

                # Workhouse bonus for contenders
                if team_window in ['win-now', 'contender'] and ip_proj >= 170 and qs_proj >= 15:
                    score += 12
                    reasons.append(f"Workhouse ({ip_proj:.0f} IP)")

            if is_rp:
                sv_proj = fa_proj.get('SV', 0)
                hld_proj = fa_proj.get('HD', 0)
                era_proj = fa_proj.get('ERA', 5.0)

                if 'SV+HLD' in weaknesses:
                    if sv_proj >= 20:
                        score += 25
                        reasons.append(f"Closer ({sv_proj} SV proj)")
                    elif sv_proj >= 10 or hld_proj >= 15:
                        score += 15
                        reasons.append(f"Reliever help ({sv_proj+hld_proj} SV+HD)")

                # Elite ratio reliever
                if era_proj <= 3.00 and fa_proj.get('WHIP', 1.5) <= 1.10:
                    score += 8
                    reasons.append("Elite ratios RP")

            # Critical positional need - big bonus
            pos_reason_added = False
            for need_pos in critical_needs:
                if need_pos in fa_pos:
                    score += 20
                    reasons.append(f"CRITICAL {need_pos} need")
                    pos_reason_added = True
                    break

            if not pos_reason_added:
                # Regular positional need
                for need_pos in positional_needs:
                    if need_pos in fa_pos:
                        score += 10
                        reasons.append(f"Adds {need_pos} depth")
                        pos_reason_added = True
                        break

            # Aging position replacement (for dynasty/rebuilding teams)
            if not pos_reason_added and team_window in ['rebuilding', 'rising', 'dynasty']:
                for aging_pos in aging_positions:
                    if aging_pos in fa_pos and fa['age'] <= 27:
                        score += 12
                        reasons.append(f"Replaces aging {aging_pos}")
                        break

            # Window alignment with specific recommendations
            age = fa['age']
            if team_window in ['rebuilding', 'rising']:
                if age <= 25:
                    score += 15
                    reasons.append("Young asset for future")
                elif age <= 27:
                    score += 8
                    reasons.append("Fits rebuild timeline")
                elif age >= 32:
                    score -= 15  # Stronger penalty for old players on rebuilding teams
            elif team_window in ['win-now', 'contender']:
                if 26 <= age <= 31:
                    score += 12
                    reasons.append("Win-now fit")
                elif age <= 25 and base_score >= 55:
                    score += 8
                    reasons.append("Ready to contribute now")
                # Contenders should grab proven players
                if fa['roster_pct'] >= 60 and age >= 28 and age <= 32:
                    score += 5
                    reasons.append("Proven veteran")
            elif team_window == 'dynasty':
                if age <= 26:
                    score += 12
                    reasons.append("Dynasty building block")
                elif age <= 28 and base_score >= 50:
                    score += 6
                    reasons.append("Core piece")

            # Roster % as quality indicator
            if fa['roster_pct'] >= 70:
                score += 8
                if len(reasons) < 4:
                    reasons.append(f"High demand ({fa['roster_pct']:.0f}%)")
            elif fa['roster_pct'] >= 50:
                score += 4

            # Detect special value (breakout, undervalued, etc.)
            special_tags = detect_special_value(fa, fa_proj)
            if special_tags:
                score += 5 * len(special_tags)
                reasons.extend(special_tags)

            # Don't recommend players that don't fit at all
            if score < base_score - 5:  # Allow slightly negative if strong in other areas
                continue

            # Generate detailed fit explanation
            full_explanation = ""
            if fit_explanation:
                full_explanation = f"Addresses your needs in: {', '.join(fit_explanation[:3])}"
            elif reasons:
                full_explanation = reasons[0] if reasons else "Available depth"

            scored_fas.append({
                **fa,
                'fit_score': round(score, 1),
                'reasons': reasons[:4] if reasons else ["Available depth"],
                'fit_explanation': full_explanation,
                'categories_addressed': cats_addressed,
                'special_tags': special_tags
            })

        scored_fas.sort(key=lambda x: x['fit_score'], reverse=True)

        # Build AI summary for the team
        ai_summary = f"Based on your {team_window} window"
        if worst_cats:
            ai_summary += f", priority targets should address {', '.join(worst_cats[:2])}"
        if critical_needs:
            ai_summary += f". You need depth at {', '.join(critical_needs)}"
        if aging_positions and team_window in ['dynasty', 'rebuilding']:
            ai_summary += f". Consider replacing aging players at {', '.join(aging_positions)}"

        return jsonify({
            "suggestions": scored_fas[:30],
            "team_needs": {
                "weaknesses": weaknesses,
                "strengths": strengths,
                "worst_categories": worst_cats,
                "positional_needs": positional_needs,
                "critical_needs": critical_needs,
                "aging_positions": aging_positions,
                "window": team_window
            },
            "ai_summary": ai_summary,
            "total_available": len(FREE_AGENTS)
        })

    except Exception as e:
        print(f"Error in get_free_agent_suggestions: {e}")
        return jsonify({"error": f"Failed to get FA suggestions: {str(e)}"}), 500


@app.route('/standings')
def get_standings():
    return jsonify({"standings": league_standings})


@app.route('/matchups')
def get_matchups():
    return jsonify({"matchups": league_matchups})


@app.route('/transactions')
def get_transactions():
    return jsonify({"transactions": league_transactions})


@app.route('/draft-order', methods=['GET', 'POST'])
def handle_draft_order():
    global draft_order_config

    if request.method == 'POST':
        data = request.get_json()
        new_order = data.get('draft_order', {})

        if not new_order:
            # Clear the draft order
            draft_order_config.clear()
            save_draft_order_config()
            return jsonify({
                "success": True,
                "message": "Draft order cleared. Using calculated order based on team value."
            })

        # Validate the draft order
        pick_numbers = list(new_order.values())
        if len(pick_numbers) != len(set(pick_numbers)):
            return jsonify({"error": "Duplicate pick numbers detected"}), 400

        # Save the new draft order
        draft_order_config.clear()
        draft_order_config.update(new_order)
        save_draft_order_config()

        return jsonify({
            "success": True,
            "message": f"Draft order saved for {len(draft_order_config)} teams."
        })

    # GET request
    return jsonify({
        "draft_order": draft_order_config,
        "is_configured": bool(draft_order_config)
    })


# ============================================================================
# MAIN
# ============================================================================

# Load data on startup
print("Loading data...")
data_loaded = False

# Load ages from Fantrax CSV first
load_ages_from_fantrax_csv()

# Load projection CSVs (if available)
load_projection_csvs()

# Add name aliases for players with different name formats (accents, hyphens, etc.)
add_name_aliases_to_projections()

# Load prospect rankings from consensus CSV files
load_prospect_rankings()

# Add prospect name aliases so direct lookups work in dynasty_trade_analyzer_v2
add_prospect_name_aliases_to_rankings()

# Build normalized lookup for prospect name matching (handles accents, Jr., etc.)
build_normalized_prospect_lookup()

# Debug: Print sample lookups to verify prospect matching works
debug_prospect_lookup_sample()

# Try JSON first (exported by data_exporter.py - has all data including standings/matchups)
print("Looking for league_data.json...")
if load_data_from_json():
    data_loaded = True
    print("Successfully loaded data from league_data.json")
else:
    # Try API next
    print("No JSON found, attempting Fantrax API...")
    if load_data_from_api():
        data_loaded = True
        print("Successfully loaded data from Fantrax API")
    else:
        # Fall back to CSV
        print("API unavailable, trying CSV fallback...")
        if load_data_from_csv():
            data_loaded = True
            print("Successfully loaded data from CSV (standings/matchups unavailable)")
        else:
            print("Warning: Could not load data. App may have limited functionality.")

# Load draft order configuration
load_draft_order_config()

# Load free agents
load_free_agents()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)

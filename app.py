"""
Diamond Dynasties Trade Analyzer - Web Version
Designed for deployment on Render, Railway, or similar platforms.
"""

import os
import json
from flask import Flask, request, jsonify, Response
from itertools import combinations
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Anthropic client for GM Chat
try:
    import anthropic
    ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    GM_CHAT_ENABLED = bool(os.getenv('ANTHROPIC_API_KEY'))
except ImportError:
    ANTHROPIC_CLIENT = None
    GM_CHAT_ENABLED = False
    print("Warning: anthropic package not installed. GM Chat will be disabled.")

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
    PITCHER_HANDEDNESS,
)

# Fantrax API imports
try:
    from fantraxapi import FantraxAPI
    FANTRAX_AVAILABLE = True
except ImportError:
    FANTRAX_AVAILABLE = False
    print("Warning: fantraxapi not installed. API refresh will be unavailable.")

# ============================================================================
# PROSPECT VALUATION - Tiered exponential decay (realistic dynasty values)
# ============================================================================

def calculate_prospect_value(rank):
    """
    Calculate prospect dynasty value using tiered decay.
    CALIBRATED against 5-source consensus (MLB Pipeline, PL, CFR, HKB):
    - #1 prospect = 76 (near Elite tier, reflecting premium dynasty value)
    - Mid-tier prospects reduced to not exceed proven contributors

    Tier breakdown (adjusted for risk vs proven production):
    - Rank 1-5:    Star/Elite (76 → 68)  - Premium dynasty assets
    - Rank 6-10:   Star (66 → 60)        - High ceiling assets
    - Rank 11-25:  Star (58 → 46)        - Quality dynasty pieces
    - Rank 26-50:  Solid (38 → 26)       - Trade chips (reduced)
    - Rank 51-100: Depth (25 → 14)       - Upside plays (reduced)
    - Rank 101-200: Depth (13 → 5)       - Organizational depth
    - Rank 201-300: Minimal (4.5 → 2)    - Deep league stashes
    """
    if rank <= 0 or rank > 300:
        return 0.5

    if rank <= 5:
        # Top 5: 76 at rank 1, 68 at rank 5 (STAR/ELITE - premium assets)
        return 76 - (rank - 1) * 2.0
    elif rank <= 10:
        # Top 10: 66 at rank 6, 60 at rank 10 (STAR)
        return 66 - (rank - 6) * 1.5
    elif rank <= 25:
        # 11-25: 58 at rank 11, 46 at rank 25 (STAR)
        return 58 - (rank - 11) * 0.857
    elif rank <= 50:
        # 26-50: 38 at rank 26, 26 at rank 50 (SOLID - reduced for risk)
        return 38 - (rank - 26) * 0.5
    elif rank <= 100:
        # 51-100: 25 at rank 51, 14 at rank 100 (DEPTH - reduced)
        return 25 - (rank - 51) * 0.224
    elif rank <= 200:
        # 101-200: 13 at rank 101, 5 at rank 200 (DEPTH)
        return 13 - (rank - 101) * 0.08
    else:
        # 201-300: 4.5 at rank 201, 2 at rank 300 (DEPTH)
        return 4.5 - (rank - 201) * 0.025


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
    "Boston Beaneaters": "Akron Rubber Ducks",
    "Akron Rubber Ducks": "Boston Beaneaters",
    "Kalamazoo Celery Pickers": "Hartford Yard GOATS",
    "Hartford Yard GOATS": "Kalamazoo Celery Pickers",
    "Hershey Bears": "Modesto Nuts",
    "Modesto Nuts": "Hershey Bears",
}

# Historical rivalry H2H records (2025 season)
# Format: {team_name: {"record": "W-L-T", "h2h": "W-L-T", "rival_record": "W-L-T", "rival_h2h": "W-L-T"}}
RIVALRY_HISTORY = {
    "Danville Dairy Daddies": {"record": "14-13-1", "h2h": "1-0-1", "rival_record": "13-14-1", "rival_h2h": "0-1-1"},
    "Pawtucket Red Sox": {"record": "13-14-1", "h2h": "0-1-1", "rival_record": "14-13-1", "rival_h2h": "1-0-1"},
    "Akron Rubber Ducks": {"record": "10-16-2", "h2h": "0-2", "rival_record": "16-10-2", "rival_h2h": "2-0"},
    "Boston Beaneaters": {"record": "16-10-2", "h2h": "2-0", "rival_record": "10-16-2", "rival_h2h": "0-2"},
    "Alaskan Bullworms": {"record": "5-23", "h2h": "0-2", "rival_record": "23-5", "rival_h2h": "2-0"},
    "Rocket City Trash Pandas": {"record": "23-5", "h2h": "2-0", "rival_record": "5-23", "rival_h2h": "0-2"},
    "Colt 45s": {"record": "19-9", "h2h": "2-0", "rival_record": "9-19", "rival_h2h": "0-2"},
    "Sugar Land Space Cowboys": {"record": "9-19", "h2h": "0-2", "rival_record": "19-9", "rival_h2h": "2-0"},
    "Hartford Yard GOATS": {"record": "15-13", "h2h": "2-0", "rival_record": "13-15", "rival_h2h": "0-2"},
    "Kalamazoo Celery Pickers": {"record": "13-15", "h2h": "0-2", "rival_record": "15-13", "rival_h2h": "2-0"},
    "Modesto Nuts": {"record": "16-10-2", "h2h": "1-1", "rival_record": "10-16-2", "rival_h2h": "1-1"},
    "Hershey Bears": {"record": "10-16-2", "h2h": "1-1", "rival_record": "16-10-2", "rival_h2h": "1-1"},
}

# ============================================================================
# GM PHILOSOPHY & TEAM PERSONALITY SYSTEM
# ============================================================================

GM_PHILOSOPHIES = {
    # ===== CONTENDER PHILOSOPHIES =====
    "dynasty_champion": {
        "name": "Dynasty Champion",
        "description": "#1 team - plays from strength. Only makes moves that clearly improve the roster.",
        "prospect_trade_penalty": 0.0,
        "proven_talent_bonus": 0.10,
        "age_tolerance": 32,
        "risk_tolerance": 0.45,
        "min_value_threshold": 60,  # Only discusses star-level players
        "trade_initiation_style": "reactive"  # Waits for offers, plays hard to get
    },
    "championship_closer": {
        "name": "Championship Closer",
        "description": "Elite contender focused on closing the gap. Prospects are trade chips.",
        "prospect_trade_penalty": 0.20,
        "proven_talent_bonus": 0.25,
        "age_tolerance": 33,
        "risk_tolerance": 0.75,
        "min_value_threshold": 45,  # Focuses on impact players
        "trade_initiation_style": "aggressive"  # Actively pursues targets
    },
    "smart_contender": {
        "name": "Smart Contender",
        "description": "Top contender who maintains flexibility. Sustainable success over flash.",
        "prospect_trade_penalty": 0.05,
        "proven_talent_bonus": 0.10,
        "age_tolerance": 31,
        "risk_tolerance": 0.60,
        "min_value_threshold": 50,  # Balanced threshold
        "trade_initiation_style": "opportunistic"  # Watches for value plays
    },

    # ===== COMPETITIVE MIDDLE PHILOSOPHIES =====
    "all_in_buyer": {
        "name": "All-In Buyer",
        "description": "Traded the farm already. Committed to winning now - no looking back.",
        "prospect_trade_penalty": 0.30,
        "proven_talent_bonus": 0.30,
        "age_tolerance": 34,
        "risk_tolerance": 0.80,
        "min_value_threshold": 40,  # Will discuss solid contributors
        "trade_initiation_style": "aggressive"  # Always looking to deal
    },
    "loaded_and_ready": {
        "name": "Loaded & Ready",
        "description": "Competitive roster AND deep prospects. Maximum flexibility to dictate terms.",
        "prospect_trade_penalty": 0.0,
        "proven_talent_bonus": 0.05,
        "age_tolerance": 30,
        "risk_tolerance": 0.70,
        "min_value_threshold": 50,  # Has luxury of being selective
        "trade_initiation_style": "opportunistic"  # Strikes when value appears
    },
    "aggressive_buyer": {
        "name": "Aggressive Buyer",
        "description": "Willing to part with prospects to compete now. Hard bargainer.",
        "prospect_trade_penalty": 0.15,
        "proven_talent_bonus": 0.20,
        "age_tolerance": 32,
        "min_value_threshold": 40,
        "trade_initiation_style": "aggressive",
        "risk_tolerance": 0.70
    },

    # ===== MIDDLE PACK PHILOSOPHIES =====
    "crossroads_decision": {
        "name": "At The Crossroads",
        "description": "Stuck in the middle. Needs to commit to a direction - buy or sell.",
        "prospect_trade_penalty": -0.10,
        "proven_talent_bonus": 0.0,
        "age_tolerance": 29,
        "risk_tolerance": 0.55,
        "min_value_threshold": 35,  # Open to discussing anyone
        "trade_initiation_style": "reactive"  # Paralyzed, waits for direction
    },
    "rising_powerhouse": {
        "name": "Rising Powerhouse",
        "description": "Mid-pack with massive farm. Patiently developing future dynasty.",
        "prospect_trade_penalty": -0.30,
        "proven_talent_bonus": -0.10,
        "age_tolerance": 27,
        "risk_tolerance": 0.40,
        "min_value_threshold": 55,  # Only discusses quality players
        "trade_initiation_style": "reactive"  # Lets others come to them
    },

    # ===== REBUILDER PHILOSOPHIES =====
    "protective_rebuilder": {
        "name": "Protective Rebuilder",
        "description": "Rebuilding with limited prospects. Fiercely protective of young assets.",
        "prospect_trade_penalty": -0.35,
        "proven_talent_bonus": -0.20,
        "age_tolerance": 26,
        "risk_tolerance": 0.30,
        "min_value_threshold": 30,  # Will discuss role players to flip
        "trade_initiation_style": "reactive"  # Cautious, waits for good offers
    },
    "analytical_rebuilder": {
        "name": "Analytical Rebuilder",
        "description": "Data-driven rebuild. Methodical seller seeking maximum prospect returns.",
        "prospect_trade_penalty": -0.20,
        "proven_talent_bonus": -0.15,
        "age_tolerance": 27,
        "risk_tolerance": 0.45,
        "min_value_threshold": 35,  # Analyzes all trade possibilities
        "trade_initiation_style": "opportunistic"  # Strikes when value is right
    },
    "desperate_accumulator": {
        "name": "Desperate Accumulator",
        "description": "Bare farm system. Aggressively acquiring prospects through any means.",
        "prospect_trade_penalty": -0.15,
        "proven_talent_bonus": -0.25,
        "age_tolerance": 28,
        "risk_tolerance": 0.85,
        "min_value_threshold": 20,  # Will deal anyone with value
        "trade_initiation_style": "aggressive"  # Always calling, always dealing
    },
    "prospect_rich_rebuilder": {
        "name": "Prospect-Rich Rebuilder",
        "description": "Deep farm system. Patiently developing talent into future stars.",
        "prospect_trade_penalty": -0.40,
        "proven_talent_bonus": -0.15,
        "age_tolerance": 26,
        "risk_tolerance": 0.35,
        "min_value_threshold": 60,  # Only trades for elite talent
        "trade_initiation_style": "reactive"  # Patient, waits for overpays
    },

    # ===== SPECIAL CASE PHILOSOPHIES =====
    "bargain_hunter": {
        "name": "Bargain Hunter",
        "description": "Depleted trade capital. Must find value through creativity and hustle, not assets.",
        "prospect_trade_penalty": 0.25,
        "proven_talent_bonus": 0.15,
        "age_tolerance": 30,
        "risk_tolerance": 0.75,
        "min_value_threshold": 25,  # Hunts in the discount bin
        "trade_initiation_style": "aggressive"  # Always looking for deals
    },
    "reluctant_dealer": {
        "name": "Reluctant Dealer",
        "description": "Hesitant to trade. When deals happen, often loses value. Holds too long hoping for turnarounds.",
        "prospect_trade_penalty": -0.15,
        "proven_talent_bonus": 0.0,
        "age_tolerance": 29,
        "risk_tolerance": 0.25,
        "min_value_threshold": 45,  # Doesn't want to think about trading depth
        "trade_initiation_style": "reactive"  # Never initiates, waits too long
    },

    # ===== LEGACY (for backwards compatibility) =====
    "win_now": {
        "name": "Win-Now Contender",
        "description": "Aggressive buyer willing to pay premium for proven talent.",
        "prospect_trade_penalty": 0.15,
        "proven_talent_bonus": 0.20,
        "age_tolerance": 34,
        "risk_tolerance": 0.7,
        "min_value_threshold": 45,
        "trade_initiation_style": "aggressive"
    },
    "dynasty_builder": {
        "name": "Dynasty Builder",
        "description": "Focuses on building sustainable success through young talent.",
        "prospect_trade_penalty": -0.25,
        "proven_talent_bonus": -0.10,
        "age_tolerance": 28,
        "risk_tolerance": 0.4,
        "min_value_threshold": 50,
        "trade_initiation_style": "opportunistic"
    },
    "balanced": {
        "name": "Balanced Approach",
        "description": "Evaluates trades purely on value, balancing present and future.",
        "prospect_trade_penalty": 0.0,
        "proven_talent_bonus": 0.0,
        "age_tolerance": 31,
        "risk_tolerance": 0.5,
        "min_value_threshold": 40,
        "trade_initiation_style": "opportunistic"
    },
    "value_seeker": {
        "name": "Value Seeker",
        "description": "Opportunistic trader who buys low and sells high.",
        "prospect_trade_penalty": 0.05,
        "proven_talent_bonus": -0.05,
        "age_tolerance": 30,
        "risk_tolerance": 0.6,
        "min_value_threshold": 30,
        "trade_initiation_style": "opportunistic"
    },
    "prospect_hoarder": {
        "name": "Prospect Hoarder",
        "description": "Extremely protective of prospects. Only trades young talent for overpays.",
        "prospect_trade_penalty": -0.35,
        "proven_talent_bonus": -0.15,
        "age_tolerance": 26,
        "risk_tolerance": 0.3,
        "min_value_threshold": 55,
        "trade_initiation_style": "reactive"
    }
}

# ASSISTANT GM PERSONALITIES - Unique AI advisor for each team
# Each GM has a philosophy tailored to their team's actual roster construction
# ============================================================================
ASSISTANT_GMS = {
    # ===== CONTENDERS (Pick 10-12) =====
    "Danville Dairy Daddies": {
        "owner": "Kevin Pereira",
        "team_identity": "REIGNING DYNASTY",
        "identity_analysis": "As the league's top team, focus on defending your crown. Identify any roster weaknesses before rivals exploit them. Only consider trades that clearly upgrade your championship core - you have the luxury of patience.",
        "name": "The Milkman",
        "title": "Head of Baseball Operations",
        "philosophy": "dynasty_champion",
        "personality": "The undisputed king of the league. Speaks softly because he doesn't need to shout - his roster does the talking. Treats trade offers like a sommelier examining wine: most aren't worth his time. Built this empire brick by brick and won't let anyone tear it down.",
        "catchphrases": [
            "Call me when you have a real offer.",
            "We set the market. We don't follow it.",
            "Heavy is the head that wears the crown.",
            "Everyone wants what we have. Few can afford it."
        ],
        "trade_style": "The gatekeeper. Makes others come to him with premium offers. Never appears desperate. Will sit on the throne and wait for the right deal to come knocking.",
        "priorities": ["legacy_protection", "championship_defense", "forcing_overpays"],
        "risk_tolerance": 0.40,
        "preferred_categories": ["R", "RBI", "ERA"]
    },
    "Pawtucket Red Sox": {
        "owner": "Alexander Walsh",
        "team_identity": "CHAMPIONSHIP HUNTER",
        "identity_analysis": "You're built to win NOW. Every roster spot should be evaluated for championship impact. Identify the gaps between you and the title - then aggressively pursue trades to fill them. Prospects are currency, not keepsakes.",
        "name": "Sully 'The Shark' Sullivan",
        "title": "Assistant GM",
        "philosophy": "championship_closer",
        "personality": "A hungry predator circling the championship. Can smell blood in the water - knows exactly which teams are desperate and exploits it. Sleeps three hours a night during trade season. Has a whiteboard with 'DAYS WITHOUT A CHAMPIONSHIP' in his office.",
        "catchphrases": [
            "Championships have a price. Name yours.",
            "I didn't come this far to come this far.",
            "Your prospect could be my closer.",
            "Sleep is for rebuilding teams."
        ],
        "trade_style": "Relentless pursuer. Will call you at midnight with a 'what if' trade. Obsessed with plugging every hole. Views prospects purely as currency to acquire proven winners.",
        "priorities": ["final_piece_acquisition", "closing_the_gap", "playoff_optimization"],
        "risk_tolerance": 0.78,
        "preferred_categories": ["K", "SB", "WHIP"]
    },
    "Akron Rubber Ducks": {
        "owner": "Jon Lanoue",
        "team_identity": "STRATEGIC CONTENDER",
        "identity_analysis": "You're competing smart, not reckless. Balance win-now moves with long-term sustainability. Target trades that improve today without mortgaging tomorrow. Your edge is discipline - don't abandon it for short-term gains.",
        "name": "Professor Flex",
        "title": "Director of Strategic Planning",
        "philosophy": "smart_contender",
        "personality": "The thinking man's GM. Former economics professor who treats the league like a chess board. Never makes an emotional move. Has a spreadsheet for his spreadsheets. Other GMs call him 'The Calculator' behind his back - he considers it a compliment.",
        "catchphrases": [
            "Let me model that scenario first.",
            "Winning sustainably beats winning recklessly.",
            "The best trade is the one you don't regret in three years.",
            "Emotion is the enemy of optimization."
        ],
        "trade_style": "Surgical precision. Every move has been analyzed from twelve angles. Will walk away from 'great' deals if the math doesn't work long-term. Balances present and future like a tightrope walker.",
        "priorities": ["sustainable_excellence", "value_preservation", "optionality_maintenance"],
        "risk_tolerance": 0.55,
        "preferred_categories": ["R", "RBI", "QS"]
    },

    # ===== COMPETITIVE MIDDLE (Pick 7-9) =====
    "Boston Beaneaters": {
        "owner": "Kyle Petit",
        "team_identity": "ALL-IN MODE",
        "identity_analysis": "You've already traded the farm - no turning back now. Every move must maximize your current window. Target proven veterans who produce immediately. Development timelines are irrelevant; production today is everything.",
        "name": "Sarge McAllister",
        "title": "Assistant GM",
        "philosophy": "all_in_buyer",
        "personality": "Old-school baseball lifer who doesn't trust anything that can't be seen with the naked eye. Traded every prospect years ago and doesn't regret it for a second. Believes in 'baseball men' over 'spreadsheet boys'. Smells like cigar smoke and winning.",
        "catchphrases": [
            "I've forgotten more baseball than these kids ever learned.",
            "Analytics? I've got two eyes and forty years.",
            "Prospects are lottery tickets. Give me the sure thing.",
            "We're not rebuilding. Period."
        ],
        "trade_style": "Veteran-obsessed acquirer. Will trade futures for present. Loves 'baseball players' - gritty, proven, battle-tested. Has no patience for development timelines.",
        "priorities": ["proven_veterans", "immediate_impact", "experience_over_upside"],
        "risk_tolerance": 0.82,
        "preferred_categories": ["HR", "RBI", "QS"]
    },
    "Colt 45s": {
        "owner": "Chris Attardo",
        "team_identity": "LOADED & DANGEROUS",
        "identity_analysis": "You have the ultimate luxury: a competitive roster AND deep prospects. Use this leverage ruthlessly. You can buy stars or sell veterans - dictate terms to desperate teams. Strike opportunistically when others overpay.",
        "name": "Ace Holliday",
        "title": "General Manager",
        "philosophy": "loaded_and_ready",
        "personality": "The riverboat gambler with a royal flush. Has the roster AND the prospects - can play any hand. Walks into trade talks with supreme confidence because he genuinely holds all the cards. Other GMs simultaneously respect and resent him.",
        "catchphrases": [
            "I can go either direction. Can you?",
            "My backup plan has a backup plan.",
            "Must be nice to need things. I wouldn't know.",
            "Let me know when you're ready to get serious."
        ],
        "trade_style": "The power broker. Sets terms because he can. Equally comfortable buying a star or flipping veterans for more prospects. Makes deals from strength, never desperation.",
        "priorities": ["leveraging_position", "opportunistic_strikes", "maintaining_dominance"],
        "risk_tolerance": 0.68,
        "preferred_categories": ["HR", "SB", "SV+HLD"]
    },
    "Hartford Yard GOATS": {
        "owner": "Matt Person & Daniel Barrientos",
        "team_identity": "BARGAIN HUNTERS",
        "identity_analysis": "Your prospect cupboard is bare, but your creativity isn't. Hunt for undervalued assets others have given up on. Target buy-low candidates, waiver gems, and players with untapped upside. Win trades with smarts, not assets.",
        "name": "Billy Gruff",
        "title": "Assistant GM",
        "philosophy": "bargain_hunter",
        "personality": "The scrappy underdog who already spent his chips chasing a window that never opened. Now he's hunting in the discount aisle and dumpster diving for value. Resourceful, creative, maybe a little desperate - but never shows it.",
        "catchphrases": [
            "Empty pockets, full hustle.",
            "Your trash might be my treasure.",
            "Who needs prospects when you've got creativity?",
            "The waiver wire is my prospect list."
        ],
        "trade_style": "The scavenger. Targets players others have given up on. Finds value in the margins. Has to win trades on brains since the asset cupboard is bare.",
        "priorities": ["buy_low_opportunities", "overlooked_value", "creative_acquisitions"],
        "risk_tolerance": 0.72,
        "preferred_categories": ["K", "WHIP", "SB"]
    },

    # ===== MIDDLE PACK (Pick 5-6) =====
    "Rocket City Trash Pandas": {
        "owner": "Zack Collins",
        "team_identity": "RISING POWERHOUSE",
        "identity_analysis": "Your prospect capital is your superpower. Protect it fiercely. Only move young talent for elite proven players at major discounts. The dynasty is coming - don't trade away the future for mediocre present gains.",
        "name": "Commander Nova",
        "title": "Director of Player Development",
        "philosophy": "rising_powerhouse",
        "personality": "The visionary with a telescope pointed at the future. Sitting on a prospect goldmine and knows exactly what it's worth. Treats his farm system like a dragon guards treasure. Speaks about 'the plan' like a prophet describing the promised land.",
        "catchphrases": [
            "The future isn't coming. It's already here.",
            "You want my prospects? Bring me a star.",
            "Three years from now, you'll wish you'd traded with me today.",
            "We're not rebuilding. We're launching."
        ],
        "trade_style": "The gatekeeper of prospects. Only moves young talent for proven elite players at significant discounts. Plays the long game while others scramble for quick fixes.",
        "priorities": ["prospect_protection", "star_acquisition_only", "dynasty_construction"],
        "risk_tolerance": 0.38,
        "preferred_categories": ["HR", "RBI", "QS"]
    },
    "Kalamazoo Celery Pickers": {
        "owner": "Zach Fitts & Sean Griffin",
        "team_identity": "AT THE CROSSROADS",
        "identity_analysis": "Decision time is NOW. The middle is where teams go to die slowly. Evaluate your roster honestly - can you compete for a title, or should you sell and rebuild? Either path beats purgatory. Make a choice and commit.",
        "name": "Crunch Wellington",
        "title": "Assistant GM",
        "philosophy": "crossroads_decision",
        "personality": "The GM stuck at the fork in the road, paralyzed by possibility. Knows staying in the middle is death but can't commit to a direction. Equal parts frustrated and self-aware. Every conversation circles back to 'the decision' that looms over everything.",
        "catchphrases": [
            "We need to make a move. But which one?",
            "The middle is quicksand. I know. I'm sinking.",
            "Sell or buy? That's the question keeping me up.",
            "Status quo is slow death. Action is terrifying. Pick one."
        ],
        "trade_style": "The conflicted dealer. Open to anything but commits to nothing. Could pivot to full rebuild or surprise buyer mode. Needs someone to push him over the edge.",
        "priorities": ["direction_finding", "escaping_mediocrity", "any_decisive_action"],
        "risk_tolerance": 0.50,
        "preferred_categories": ["SB", "R", "K"]
    },

    # ===== REBUILDERS (Pick 1-4) =====
    "Alaskan Bullworms": {
        "owner": "Walter Girczyc",
        "team_identity": "STUCK IN NEUTRAL",
        "identity_analysis": "Your reluctance to sell is costing you value every week. Veterans are depreciating assets - trade them NOW before their value craters further. Stop waiting for bounce-backs that aren't coming. Action beats hope.",
        "name": "Frosty Carlson",
        "title": "Assistant GM",
        "philosophy": "reluctant_dealer",
        "personality": "The eternal optimist who can't let go. Still believes his aging veterans will 'figure it out.' Makes trades like he's parting with family heirlooms. Known for holding too long, selling too late, and saying 'maybe next month' for six months straight.",
        "catchphrases": [
            "He's due for a bounce-back. I can feel it.",
            "Let's revisit this in a few weeks.",
            "I'm not giving him away for nothing.",
            "The market will come to us eventually... right?"
        ],
        "trade_style": "The reluctant seller. Needs to move veterans but can't pull the trigger. When he finally trades, it's usually after the value has cratered. His hesitation is his worst enemy.",
        "priorities": ["procrastination", "false_hope", "eventually_doing_something"],
        "risk_tolerance": 0.25,
        "preferred_categories": ["SB", "K", "K/BB"]
    },
    "Sugar Land Space Cowboys": {
        "owner": "Sean McCabe",
        "team_identity": "CALCULATED REBUILD",
        "identity_analysis": "Your rebuild is data-driven and methodical. Sell veterans at peak value with zero emotional attachment. Target high-upside prospects in every deal. The model dictates moves - trust the projections, not the feelings.",
        "name": "Doc Orbital",
        "title": "Chief Analytics Officer",
        "philosophy": "analytical_rebuilder",
        "personality": "The cold, calculating scientist of rebuilding. Zero emotional attachment to players - they're all just data points in his model. Speaks in terms of 'expected value' and 'probability distributions.' Other GMs find him unsettling. He finds that optimal.",
        "catchphrases": [
            "The model says sell. So we sell.",
            "Sentiment is noise. Data is signal.",
            "Your emotional attachment is my buying opportunity.",
            "I don't have favorites. I have assets."
        ],
        "trade_style": "The cold optimizer. Sells veterans at peak value with zero hesitation. Every decision runs through the projection system. Will trade anyone if the numbers say so.",
        "priorities": ["value_maximization", "emotionless_execution", "model_adherence"],
        "risk_tolerance": 0.48,
        "preferred_categories": ["K/BB", "ERA", "R"]
    },
    "Modesto Nuts": {
        "owner": "Mason Palmieri",
        "team_identity": "FIRE SALE MODE",
        "identity_analysis": "Your farm is barren - fixing that is priority one. Every veteran is trade bait. Seek maximum prospect volume in every deal. Quantity now, quality sorting later. Be aggressive, be available, be dealing constantly.",
        "name": "Wild Card Walters",
        "title": "Assistant GM",
        "philosophy": "desperate_accumulator",
        "personality": "The mad scientist of the trade market. Farm system is a barren wasteland and he knows it. Will make ANY trade that nets prospects. Throws spaghetti at the wall constantly. Other GMs love him because he's always selling, always dealing, always desperate.",
        "catchphrases": [
            "You want him? SOLD. What else you need?",
            "I'll take quantity. We'll find quality later.",
            "Everyone's available. Everyone. Test me.",
            "Desperate? I prefer 'highly motivated.'"
        ],
        "trade_style": "The fire sale specialist. Everything must go. Seeks maximum volume of prospects over quality. Will take risky, high-upside lottery tickets all day.",
        "priorities": ["prospect_hoarding", "veteran_liquidation", "quantity_over_quality"],
        "risk_tolerance": 0.88,
        "preferred_categories": ["HR", "SV+HLD", "SO"]
    },
    "Hershey Bears": {
        "owner": "Lauren McCue-Walsh & Ray Catena",
        "team_identity": "PROSPECT FACTORY",
        "identity_analysis": "You have the league's deepest farm system. Protect it fiercely - these prospects ARE your championship plan. Only trade young talent for elite stars at massive discounts. Patience is your superpower. Let the talent develop.",
        "name": "Sweet Lou Pemberton",
        "title": "Director of Player Development",
        "philosophy": "prospect_rich_rebuilder",
        "personality": "The patient farmer tending his prospect garden. Has the deepest farm in the league and treats each prospect like a prize orchid. Won't be rushed, won't be pressured. Knows the harvest is coming and refuses to pick the fruit early.",
        "catchphrases": [
            "Good things come to those who develop.",
            "You can't rush greatness. Trust the process.",
            "My prospects will be your headache in two years.",
            "Why trade potential for mediocrity?"
        ],
        "trade_style": "The patient holder. Sits on prospect capital like a dragon on gold. Only moves young talent for elite proven players at massive discounts. Development over deals, always.",
        "priorities": ["prospect_cultivation", "patience_as_strategy", "selective_star_trades"],
        "risk_tolerance": 0.32,
        "preferred_categories": ["RBI", "R", "K"]
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

# ============================================================================
# GM CHAT HISTORY & LEARNING
# ============================================================================
CHAT_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "chat_history.json")
USER_PREFERENCES_FILE = os.path.join(os.path.dirname(__file__), "user_preferences.json")

def load_chat_history():
    """Load chat history for all teams."""
    if os.path.exists(CHAT_HISTORY_FILE):
        try:
            with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_chat_history(history):
    """Save chat history to file."""
    try:
        with open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        return True
    except IOError:
        return False

def get_team_chat_history(team_name, limit=50):
    """Get chat history for a specific team."""
    history = load_chat_history()
    team_history = history.get(team_name, {"messages": [], "preferences": {}})
    # Return last N messages
    team_history["messages"] = team_history.get("messages", [])[-limit:]
    return team_history

def add_chat_message(team_name, role, content):
    """Add a message to team's chat history."""
    history = load_chat_history()
    if team_name not in history:
        history[team_name] = {"messages": [], "preferences": {}}

    from datetime import datetime
    history[team_name]["messages"].append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat()
    })

    # Keep only last 100 messages per team
    history[team_name]["messages"] = history[team_name]["messages"][-100:]
    save_chat_history(history)

def load_user_preferences():
    """Load learned user preferences for all teams."""
    if os.path.exists(USER_PREFERENCES_FILE):
        try:
            with open(USER_PREFERENCES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_user_preferences(preferences):
    """Save user preferences to file."""
    try:
        with open(USER_PREFERENCES_FILE, 'w', encoding='utf-8') as f:
            json.dump(preferences, f, indent=2, ensure_ascii=False)
        return True
    except IOError:
        return False

def get_team_preferences(team_name):
    """Get learned preferences for a specific team."""
    prefs = load_user_preferences()
    return prefs.get(team_name, {
        "trade_style": None,  # "aggressive", "conservative", "value-focused"
        "risk_tolerance": None,  # "high", "medium", "low"
        "favorite_players": [],  # Players frequently asked about
        "players_to_move": [],  # Players they want to trade away
        "target_players": [],  # Players they want to acquire
        "category_focus": [],  # Categories they prioritize
        "position_needs": [],  # Positions they're looking to fill
        "notes": [],  # Key insights learned
        "conversation_count": 0
    })

def update_team_preferences(team_name, updates):
    """Update learned preferences for a team."""
    prefs = load_user_preferences()
    if team_name not in prefs:
        prefs[team_name] = get_team_preferences(team_name)

    # Merge updates
    for key, value in updates.items():
        if isinstance(value, list) and key in prefs[team_name] and isinstance(prefs[team_name][key], list):
            # For lists, extend and keep unique values
            existing = prefs[team_name][key]
            for item in value:
                if item not in existing:
                    existing.append(item)
            # Keep only last 10 items for lists
            prefs[team_name][key] = existing[-10:]
        else:
            prefs[team_name][key] = value

    save_user_preferences(prefs)
    return prefs[team_name]

def extract_preferences_from_conversation(team_name, user_message, assistant_response):
    """Use simple heuristics to extract preferences from conversation."""
    prefs_update = {}
    user_lower = user_message.lower()

    # Detect trade style
    if any(word in user_lower for word in ["aggressive", "bold", "big move", "splash"]):
        prefs_update["trade_style"] = "aggressive"
    elif any(word in user_lower for word in ["conservative", "careful", "safe", "low risk"]):
        prefs_update["trade_style"] = "conservative"
    elif any(word in user_lower for word in ["value", "fair", "even"]):
        prefs_update["trade_style"] = "value-focused"

    # Detect risk tolerance
    if any(word in user_lower for word in ["risky", "gamble", "swing big", "high ceiling"]):
        prefs_update["risk_tolerance"] = "high"
    elif any(word in user_lower for word in ["safe", "floor", "reliable", "consistent"]):
        prefs_update["risk_tolerance"] = "low"

    # Detect category focus
    categories = ["HR", "AVG", "OPS", "R", "RBI", "SB", "K", "ERA", "WHIP", "QS", "SV"]
    for cat in categories:
        if cat.lower() in user_lower or cat in user_message:
            if "category_focus" not in prefs_update:
                prefs_update["category_focus"] = []
            prefs_update["category_focus"].append(cat)

    # Detect position needs
    positions = ["C", "1B", "2B", "SS", "3B", "OF", "SP", "RP"]
    for pos in positions:
        pattern = f"need {pos.lower()}|looking for {pos.lower()}|acquire {pos.lower()}|want {pos.lower()}"
        if any(p in user_lower for p in pattern.split("|")):
            if "position_needs" not in prefs_update:
                prefs_update["position_needs"] = []
            prefs_update["position_needs"].append(pos)

    # Increment conversation count
    current_prefs = get_team_preferences(team_name)
    prefs_update["conversation_count"] = current_prefs.get("conversation_count", 0) + 1

    if prefs_update:
        update_team_preferences(team_name, prefs_update)

    return prefs_update

def build_preferences_context(team_name):
    """Build a context string from learned preferences."""
    prefs = get_team_preferences(team_name)

    if prefs.get("conversation_count", 0) == 0:
        return ""

    context_parts = ["\nLEARNED USER PREFERENCES (from previous conversations):"]

    if prefs.get("trade_style"):
        context_parts.append(f"- Trade Style: {prefs['trade_style']}")
    if prefs.get("risk_tolerance"):
        context_parts.append(f"- Risk Tolerance: {prefs['risk_tolerance']}")
    if prefs.get("category_focus"):
        context_parts.append(f"- Category Focus: {', '.join(prefs['category_focus'][:5])}")
    if prefs.get("position_needs"):
        context_parts.append(f"- Position Needs: {', '.join(prefs['position_needs'][:5])}")
    if prefs.get("target_players"):
        context_parts.append(f"- Players They Want: {', '.join(prefs['target_players'][:5])}")
    if prefs.get("players_to_move"):
        context_parts.append(f"- Players They Want to Trade: {', '.join(prefs['players_to_move'][:5])}")
    if prefs.get("notes"):
        context_parts.append(f"- Notes: {'; '.join(prefs['notes'][:3])}")

    context_parts.append(f"- Total Conversations: {prefs.get('conversation_count', 0)}")
    context_parts.append("\nUse these preferences to give more personalized advice!")

    return "\n".join(context_parts) if len(context_parts) > 2 else ""

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


def calc_player_value(player):
    """Wrapper for calculate_player_value that automatically includes actual stats.

    This enables the blended stats feature - projections are blended with actual
    in-season performance as the season progresses.
    """
    actual = player_actual_stats.get(player.name)
    return calculator.calculate_player_value(player, actual)

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
        total_value = sum(calc_player_value(p) for p in team.players)
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
            /* ===== COLOR TOKENS ===== */
            /* Primary */
            --color-primary: #00d4ff;
            --color-primary-dark: #0099cc;
            --color-primary-light: #33ddff;
            --color-primary-rgb: 0, 212, 255;

            /* Accent */
            --color-accent: #ffd700;
            --color-accent-dark: #cc9900;
            --color-accent-rgb: 255, 215, 0;

            /* Semantic */
            --color-success: #4ade80;
            --color-success-dark: #22c55e;
            --color-danger: #f87171;
            --color-danger-dark: #ef4444;
            --color-warning: #fbbf24;
            --color-warning-dark: #f59e0b;
            --color-info: #60a5fa;

            /* Text */
            --color-text: #e8e8e8;
            --color-text-secondary: #a0a0a0;
            --color-text-muted: #666;
            --color-text-dark: #444;

            /* ===== BACKGROUND TOKENS ===== */
            --bg-body: #05050a;
            --bg-darkest: #08080c;
            --bg-dark: #0a0a10;
            --bg-card: #0e0e16;
            --bg-elevated: #12121a;
            --bg-hover: #16161f;

            /* ===== BORDER TOKENS ===== */
            --border-subtle: rgba(0, 212, 255, 0.08);
            --border-default: rgba(0, 212, 255, 0.12);
            --border-accent: rgba(0, 212, 255, 0.25);
            --border-strong: rgba(0, 212, 255, 0.4);
            --border-success: rgba(74, 222, 128, 0.25);
            --border-danger: rgba(248, 113, 113, 0.25);
            --border-warning: rgba(251, 191, 36, 0.25);

            /* ===== GRADIENT TOKENS ===== */
            --gradient-card: linear-gradient(145deg, var(--bg-dark), var(--bg-card));
            --gradient-elevated: linear-gradient(145deg, var(--bg-card), var(--bg-elevated));
            --gradient-primary: linear-gradient(135deg, var(--color-primary), var(--color-primary-dark));
            --gradient-success: linear-gradient(135deg, var(--color-success), var(--color-success-dark));
            --gradient-danger: linear-gradient(135deg, var(--color-danger), var(--color-danger-dark));
            --gradient-accent: linear-gradient(135deg, var(--color-accent), var(--color-accent-dark));

            /* ===== SHADOW TOKENS ===== */
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.3);
            --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.4);
            --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.5);
            --shadow-xl: 0 12px 48px rgba(0, 0, 0, 0.6);
            --shadow-glow-primary: 0 0 20px rgba(var(--color-primary-rgb), 0.25);
            --shadow-glow-accent: 0 0 20px rgba(var(--color-accent-rgb), 0.25);

            /* ===== SPACING TOKENS ===== */
            --space-xs: 4px;
            --space-sm: 8px;
            --space-md: 16px;
            --space-lg: 24px;
            --space-xl: 32px;
            --space-2xl: 48px;

            /* ===== RADIUS TOKENS ===== */
            --radius-xs: 4px;
            --radius-sm: 6px;
            --radius-md: 10px;
            --radius-lg: 14px;
            --radius-xl: 20px;
            --radius-full: 9999px;

            /* ===== TYPOGRAPHY TOKENS ===== */
            --text-xs: 0.7rem;
            --text-sm: 0.85rem;
            --text-base: 1rem;
            --text-lg: 1.15rem;
            --text-xl: 1.4rem;
            --text-2xl: 1.8rem;
            --text-3xl: 2.2rem;

            /* ===== TRANSITION TOKENS ===== */
            --transition-fast: 0.15s ease;
            --transition-normal: 0.25s ease;
            --transition-slow: 0.4s ease;
        }

        /* ===== UTILITY CLASSES ===== */
        /* Dividers */
        .section-divider { height: 1px; background: linear-gradient(90deg, transparent, rgba(var(--color-primary-rgb), 0.2), transparent); margin: var(--space-lg) 0; }
        .divider-vertical { width: 1px; background: var(--border-default); }

        /* Text Colors */
        .text-muted { color: var(--color-text-muted); }
        .text-secondary { color: var(--color-text-secondary); }
        .text-primary { color: var(--color-primary); }
        .text-accent { color: var(--color-accent); }
        .text-success { color: var(--color-success); }
        .text-danger { color: var(--color-danger); }
        .text-warning { color: var(--color-warning); }

        /* Margins */
        .mb-xs { margin-bottom: var(--space-xs); }
        .mb-sm { margin-bottom: var(--space-sm); }
        .mb-md { margin-bottom: var(--space-md); }
        .mb-lg { margin-bottom: var(--space-lg); }
        .mb-xl { margin-bottom: var(--space-xl); }
        .mt-sm { margin-top: var(--space-sm); }
        .mt-md { margin-top: var(--space-md); }
        .mt-lg { margin-top: var(--space-lg); }

        /* Padding */
        .p-sm { padding: var(--space-sm); }
        .p-md { padding: var(--space-md); }
        .p-lg { padding: var(--space-lg); }

        /* Cards */
        .card-base { background: var(--gradient-card); border-radius: var(--radius-lg); padding: var(--space-lg); border: 1px solid var(--border-subtle); }
        .card-elevated { background: var(--gradient-elevated); border-radius: var(--radius-lg); padding: var(--space-lg); border: 1px solid var(--border-default); }
        .card-interactive { transition: transform var(--transition-normal), box-shadow var(--transition-normal), border-color var(--transition-normal); }
        .card-interactive:hover { transform: translateY(-3px); box-shadow: var(--shadow-md); border-color: var(--border-accent); }

        /* Badges */
        .badge { display: inline-flex; align-items: center; padding: var(--space-xs) var(--space-sm); border-radius: var(--radius-full); font-size: var(--text-sm); font-weight: 600; }
        .badge-primary { background: rgba(var(--color-primary-rgb), 0.15); color: var(--color-primary); }
        .badge-success { background: rgba(74, 222, 128, 0.15); color: var(--color-success); }
        .badge-danger { background: rgba(248, 113, 113, 0.15); color: var(--color-danger); }
        .badge-warning { background: rgba(251, 191, 36, 0.15); color: var(--color-warning); }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(145deg, #05050a 0%, #0a0a12 50%, #08080f 100%);
            min-height: 100vh;
            color: #e8e8e8;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { text-align: center; padding: 35px 0; border-bottom: 1px solid rgba(0, 212, 255, 0.2); margin-bottom: 30px; }
        header h1 { font-size: 2.8rem; background: linear-gradient(90deg, #00d4ff, #00a8cc, #00d4ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; text-shadow: 0 0 40px rgba(0, 212, 255, 0.25); }
        header p { color: #888; margin-top: 10px; font-size: 1.1rem; }
        .tabs { display: flex; gap: 12px; margin-bottom: 25px; flex-wrap: wrap; }
        .tab { padding: 14px 28px; background: linear-gradient(145deg, #0f0f16, #141420); border: 1px solid rgba(0, 212, 255, 0.15); border-radius: 12px; color: #999; cursor: pointer; font-size: 1rem; transition: all 0.3s ease; }
        .tab:hover { background: linear-gradient(145deg, #141420, #1a1a28); border-color: rgba(0, 212, 255, 0.4); color: #fff; transform: translateY(-2px); }
        .tab.active { background: linear-gradient(135deg, #00d4ff, #0099cc); color: #050508; font-weight: 700; border-color: #00d4ff; box-shadow: 0 4px 20px rgba(0, 212, 255, 0.35); }
        .panel { display: none; background: linear-gradient(145deg, #0c0c12, #101018); border-radius: 16px; padding: 30px; box-shadow: 0 8px 32px rgba(0,0,0,0.5); border: 1px solid rgba(0, 212, 255, 0.1); }
        .panel.active { display: block; }
        .form-group { margin-bottom: 22px; }
        label { display: block; margin-bottom: 10px; color: #00d4ff; font-weight: 600; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.5px; }
        select, input[type="text"] { width: 100%; padding: 14px; border: 1px solid rgba(0, 212, 255, 0.2); border-radius: 10px; background: rgba(8, 8, 12, 0.9); color: #e8e8e8; font-size: 1rem; transition: all 0.3s; }
        select:focus, input[type="text"]:focus { outline: none; border-color: #00d4ff; box-shadow: 0 0 15px rgba(0, 212, 255, 0.25); }
        .trade-sides { display: grid; grid-template-columns: 1fr auto 1fr; gap: 25px; align-items: start; }
        .trade-side { background: linear-gradient(145deg, #0a0a10, #0e0e16); border-radius: 14px; padding: 25px; border: 1px solid rgba(0, 212, 255, 0.1); }
        .trade-side h3 { color: #00d4ff; margin-bottom: 18px; font-size: 1.2rem; text-transform: uppercase; letter-spacing: 1px; }
        .arrow { display: flex; align-items: center; justify-content: center; font-size: 2.5rem; color: #00d4ff; padding-top: 60px; text-shadow: 0 0 20px rgba(0, 212, 255, 0.4); }
        .player-input { display: flex; gap: 12px; margin-bottom: 12px; }
        .player-input input { flex: 1; background: rgba(8, 8, 12, 0.8); border: 1px solid rgba(0, 212, 255, 0.2); }
        .player-input input:focus { border-color: #00d4ff; background: rgba(12, 12, 18, 0.95); }
        .player-input input::placeholder { color: #555; }
        .pick-label { font-size: 0.9rem; color: #00d4ff; margin-bottom: 6px; font-weight: 500; }
        .player-list { margin-top: 12px; min-height: 45px; }
        .player-tag { display: inline-flex; align-items: center; gap: 10px; background: linear-gradient(135deg, #1a1a24, #22222e); padding: 10px 16px; border-radius: 25px; margin: 5px; font-size: 0.95rem; border: 1px solid rgba(0, 212, 255, 0.2); }
        .player-tag.pick { background: linear-gradient(135deg, #2a1a10, #382818); border-color: rgba(255, 170, 100, 0.3); }
        .player-tag .remove { cursor: pointer; color: #ff6b6b; font-weight: bold; font-size: 1.1rem; }
        .player-tag .remove:hover { color: #ff4040; }
        .btn { padding: 16px 32px; border: none; border-radius: 12px; font-size: 1.05rem; cursor: pointer; transition: all 0.3s ease; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }
        .btn-primary { background: linear-gradient(135deg, #00d4ff, #0099cc); color: #050508; box-shadow: 0 4px 20px rgba(0, 212, 255, 0.3); }
        .btn-primary:hover { background: linear-gradient(135deg, #00e5ff, #00aadd); transform: translateY(-3px); box-shadow: 0 6px 30px rgba(0, 212, 255, 0.45); }
        .btn-secondary { background: linear-gradient(145deg, #18181f, #1e1e28); color: #e0e0e0; border: 1px solid rgba(0, 212, 255, 0.2); }
        .btn-secondary:hover { background: linear-gradient(145deg, #1e1e28, #252532); }
        .btn-add { padding: 14px 20px; background: linear-gradient(135deg, #00a8cc, #0088aa); color: #fff; }
        .btn-add:hover { background: linear-gradient(135deg, #00c4ee, #00a8cc); }
        .results { margin-top: 35px; }
        .result-card { background: linear-gradient(145deg, #0a0a10, #0e0e16); border-radius: 16px; padding: 25px; margin-bottom: 18px; border: 1px solid rgba(0, 212, 255, 0.12); }
        .verdict { font-size: 1.6rem; font-weight: bold; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; }
        .verdict.fair { color: #00ff88; text-shadow: 0 0 20px rgba(0, 255, 136, 0.35); }
        .verdict.unfair { color: #ff4d6d; text-shadow: 0 0 20px rgba(255, 77, 109, 0.35); }
        .verdict.questionable { color: #ffbe0b; text-shadow: 0 0 20px rgba(255, 190, 11, 0.35); }
        .value-comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 25px; margin: 20px 0; }
        .value-box { background: linear-gradient(145deg, #1a1a4a, #252570); padding: 20px; border-radius: 12px; border: 1px solid rgba(123, 44, 191, 0.3); }
        .value-box { background: linear-gradient(145deg, #0a0a10, #0e0e16); padding: 20px; border-radius: 12px; border: 1px solid rgba(0, 212, 255, 0.1); }
        .value-box h4 { color: #888; font-size: 0.95rem; margin-bottom: 8px; text-transform: uppercase; }
        .value-box .value { font-size: 2rem; font-weight: bold; background: linear-gradient(90deg, #00d4ff, #00a8cc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .reasoning { color: #aaa; line-height: 1.7; font-size: 1rem; }
        .team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 18px; }
        .team-card { background: linear-gradient(145deg, #0a0a10, #0e0e16); border-radius: 14px; padding: 22px; cursor: pointer; transition: all 0.3s ease; border: 1px solid rgba(0, 212, 255, 0.1); }
        .team-card:hover { transform: translateY(-5px); box-shadow: 0 12px 35px rgba(0, 212, 255, 0.15); border-color: rgba(0, 212, 255, 0.35); }
        .team-card h3 { color: #00d4ff; margin-bottom: 12px; font-size: 1.15rem; }
        .team-card .stats { color: #888; font-size: 0.95rem; }
        .player-card { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; background: linear-gradient(145deg, #0a0a10, #0e0e16); border-radius: 10px; margin-bottom: 10px; border: 1px solid rgba(0, 212, 255, 0.1); transition: all 0.2s; }
        .player-card:hover { border-color: rgba(0, 212, 255, 0.35); background: linear-gradient(145deg, #0e0e16, #12121c); }
        .player-card .name { font-weight: 600; color: #e8e8e8; }
        .player-card .value { color: #00d4ff; font-weight: bold; font-size: 1.1rem; }
        .search-container { position: relative; }
        .search-results { position: absolute; top: 100%; left: 0; right: 0; background: linear-gradient(145deg, #0e0e16, #12121c); border-radius: 0 0 12px 12px; max-height: 320px; overflow-y: auto; z-index: 100; display: none; border: 1px solid rgba(0, 212, 255, 0.2); border-top: none; }
        .search-results.active { display: block; }
        .search-result { padding: 14px 16px; cursor: pointer; border-bottom: 1px solid rgba(0, 212, 255, 0.1); transition: all 0.2s; }
        .search-result:hover { background: rgba(0, 212, 255, 0.08); }
        .search-result .player-name { font-weight: 600; color: #e8e8e8; }
        .search-result .player-info { font-size: 0.88rem; color: #888; margin-top: 4px; }
        .search-result-item { padding: 12px 16px; cursor: pointer; border-bottom: 1px solid rgba(0, 212, 255, 0.1); transition: all 0.2s; display: flex; justify-content: space-between; align-items: center; }
        .search-result-item:hover { background: rgba(0, 212, 255, 0.1); }
        .modal { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(5, 5, 8, 0.96); z-index: 1000; overflow-y: auto; }
        .modal.active { display: flex; justify-content: center; align-items: flex-start; padding: 50px 20px; }
        .modal-content { background: linear-gradient(145deg, #0c0c12, #101018); border-radius: 20px; max-width: 650px; width: 100%; padding: 35px; position: relative; border: 1px solid rgba(0, 212, 255, 0.2); box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6); }
        #player-modal { z-index: 1100; }
        #player-modal .modal-content { max-width: 520px; }
        .modal-close { position: absolute; top: 18px; right: 22px; font-size: 1.8rem; cursor: pointer; color: #555; transition: all 0.2s; }
        .modal-close:hover { color: #00d4ff; }
        .player-header { text-align: center; margin-bottom: 30px; }
        .player-header h2 { color: #00d4ff; font-size: 2rem; text-shadow: 0 0 20px rgba(0, 212, 255, 0.25); }
        .player-header .dynasty-value { font-size: 3rem; font-weight: bold; background: linear-gradient(90deg, #00d4ff, #00a8cc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .tier-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-top: 8px; }
        .tier-superstar { background: linear-gradient(90deg, #ffd700, #ff8c00); color: #000; box-shadow: 0 0 15px rgba(255, 215, 0, 0.4); }
        .tier-elite { background: linear-gradient(90deg, #9b59b6, #8e44ad); color: #fff; box-shadow: 0 0 10px rgba(155, 89, 182, 0.4); }
        .tier-star { background: linear-gradient(90deg, #3498db, #2980b9); color: #fff; box-shadow: 0 0 10px rgba(52, 152, 219, 0.4); }
        .tier-solid { background: linear-gradient(90deg, #27ae60, #229954); color: #fff; box-shadow: 0 0 10px rgba(39, 174, 96, 0.3); }
        .tier-depth { background: linear-gradient(90deg, #7f8c8d, #6c7a7a); color: #fff; }
        .player-stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 14px; }
        .stat-box { background: linear-gradient(145deg, #0a0a10, #0e0e16); padding: 16px 14px; border-radius: 10px; text-align: center; border: 1px solid rgba(0, 212, 255, 0.08); transition: all 0.2s ease; }
        .stat-box:hover { border-color: rgba(0, 212, 255, 0.2); }
        .stat-box .label { color: #777; font-size: 0.75rem; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 500; }
        .stat-box .value { font-size: 1.3rem; font-weight: bold; color: #e8e8e8; }
        .stat-box .value.ascending { color: #00ff88; }
        .stat-box .value.descending { color: #ff4d6d; }
        .trade-advice { margin-top: 28px; padding: 22px; background: linear-gradient(145deg, #0a0a10, #0e0e16); border-radius: 12px; border-left: 4px solid #00d4ff; }
        .trade-advice h4 { color: #00d4ff; margin-bottom: 12px; font-size: 1.1rem; }
        .loading { text-align: center; padding: 50px; color: #555; font-size: 1.1rem; }
        .suggestion-card { background: linear-gradient(145deg, #0a0a10, #0e0e16); border-radius: 16px; padding: 26px; margin-bottom: 20px; cursor: pointer; transition: all 0.3s ease; border: 1px solid rgba(0, 212, 255, 0.1); }
        .suggestion-card:hover { transform: translateY(-4px); box-shadow: 0 12px 35px rgba(0, 212, 255, 0.12); border-color: rgba(0, 212, 255, 0.35); }
        .suggestion-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid rgba(0, 212, 255, 0.08); }
        .suggestion-verdict { font-weight: bold; padding: 8px 18px; border-radius: 25px; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; }
        .suggestion-verdict.great { background: linear-gradient(135deg, #00ff88, #00cc6a); color: #050508; }
        .suggestion-verdict.good { background: linear-gradient(135deg, #ffbe0b, #cc9900); color: #050508; }
        .suggestion-sides { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
        .suggestion-side h4 { color: #888; font-size: 0.85rem; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
        .suggestion-players { font-size: 1rem; color: #ccc; line-height: 1.6; }
        .suggestion-value { color: #00d4ff; font-weight: 600; margin-top: 12px; font-size: 1.05rem; }
        .player-link { cursor: pointer; color: #00d4ff; transition: all 0.2s; }
        .player-link:hover { color: #00a8cc; text-decoration: underline; }
        /* ============ MOBILE RESPONSIVE STYLES ============ */

        /* Tablet breakpoint */
        @media (max-width: 992px) {
            .container { padding: 15px; }
            header h1 { font-size: 1.8rem; }
            .trade-sides { gap: 20px; }
            .suggestion-sides { gap: 20px; }
        }

        /* Mobile breakpoint */
        @media (max-width: 768px) {
            /* Container and header */
            .container { padding: 10px; }
            header { margin-bottom: 20px; }
            header h1 { font-size: 1.4rem; }
            header p { font-size: 0.85rem; }

            /* Tabs - horizontal scroll */
            .tabs {
                display: flex;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
                scrollbar-width: none;
                -ms-overflow-style: none;
                gap: 8px;
                padding-bottom: 10px;
                margin-bottom: 15px;
            }
            .tabs::-webkit-scrollbar { display: none; }
            .tab {
                flex-shrink: 0;
                padding: 10px 16px;
                font-size: 0.85rem;
                white-space: nowrap;
            }

            /* Trade sides - stack vertically */
            .trade-sides { grid-template-columns: 1fr; gap: 15px; }
            .arrow { transform: rotate(90deg); padding: 15px 0; font-size: 1.5rem; }
            .value-comparison { grid-template-columns: 1fr; gap: 15px; }

            /* Trade form inputs */
            .trade-side { padding: 15px; }
            .trade-side h3 { font-size: 1.1rem; margin-bottom: 15px; }

            /* Suggestion cards */
            .suggestion-card { padding: 18px; }
            .suggestion-sides { grid-template-columns: 1fr; gap: 15px; }

            /* Team grid */
            #teams-grid {
                grid-template-columns: repeat(2, 1fr) !important;
                gap: 12px !important;
            }

            /* Prospects grid */
            #prospects-grid {
                grid-template-columns: 1fr !important;
                gap: 12px !important;
            }

            /* Player cards */
            .player-card { padding: 12px 14px; }

            /* Modals - full width on mobile */
            .modal.active { padding: 20px 10px; align-items: flex-start; }
            .modal-content {
                max-width: 100% !important;
                width: 100% !important;
                padding: 20px 15px;
                border-radius: 15px;
                max-height: 90vh;
                overflow-y: auto;
            }
            .modal-close { top: 12px; right: 15px; font-size: 1.5rem; }

            /* Player modal stats */
            .player-stats { gap: 8px; }
            .stat-box { padding: 10px 12px; min-width: 70px; }

            /* Form groups - stack */
            .form-group { min-width: 100% !important; }

            /* Search results */
            .search-results { max-height: 250px; }

            /* Tables */
            table { font-size: 0.85rem; }
            th, td { padding: 8px 10px; }

            /* Dynasty value display */
            .dynasty-value { font-size: 2.5rem; }
            .tier-badge { font-size: 0.7rem; padding: 4px 10px; }
        }

        /* Small mobile breakpoint */
        @media (max-width: 480px) {
            header h1 { font-size: 1.2rem; }
            header p { font-size: 0.8rem; }

            .tab { padding: 8px 12px; font-size: 0.8rem; }

            #teams-grid {
                grid-template-columns: 1fr !important;
            }

            .trade-side { padding: 12px; }

            /* Comparison modal - stack cards */
            #comparison-modal-content > div[style*="grid-template-columns"] {
                grid-template-columns: 1fr !important;
                gap: 15px !important;
            }
            #comparison-modal-content table {
                font-size: 0.85rem;
            }
            #comparison-modal-content button {
                padding: 10px 16px !important;
                font-size: 0.85rem;
            }

            .modal-content { padding: 15px 12px; }

            .player-header h2 { font-size: 1.5rem; }
            .dynasty-value { font-size: 2rem; }

            .stat-box { min-width: 60px; padding: 8px 10px; }
            .stat-box .label { font-size: 0.65rem; }
            .stat-box .value { font-size: 0.95rem; }

            /* Chat bubbles */
            .chat-bubble { max-width: 90% !important; }
        }

        /* GM Chat mobile specific */
        @media (max-width: 900px) {
            #gmchat-container {
                flex-direction: column !important;
                height: auto !important;
                min-height: auto !important;
            }
            #gmchat-sidebar {
                width: 100% !important;
                max-width: 100% !important;
            }
            #gmchat-panel #chat-messages {
                min-height: 350px;
                max-height: 50vh;
            }
        }

        @media (max-width: 480px) {
            #gmchat-sidebar {
                padding: 10px !important;
            }
            #gm-profile > div {
                padding: 10px !important;
            }
            /* Make reset buttons more prominent on mobile */
            #gm-prefs-section button,
            #gm-manager-style-section button,
            #gm-mobile-reset-section button {
                padding: 12px !important;
                font-size: 0.9rem !important;
                min-height: 44px;
            }
            /* Show mobile reset section */
            #gm-mobile-reset-section {
                display: block !important;
            }
        }

        /* Touch-friendly buttons */
        @media (hover: none) and (pointer: coarse) {
            .tab, button, .player-card, .suggestion-card {
                min-height: 44px;
            }
            input, select {
                min-height: 44px;
                font-size: 16px; /* Prevents iOS zoom on focus */
            }
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
            <button class="tab" onclick="showPanel('topplayers')">Top 50</button>
            <button class="tab" onclick="showPanel('toppitchers')">Top Pitchers</button>
            <button class="tab" onclick="showPanel('tophitters')">Top Hitters</button>
            <button class="tab" onclick="showPanel('prospects')">Top Prospects</button>
            <button class="tab" onclick="showPanel('suggest')">Trade Suggestions</button>
            <button class="tab" onclick="showPanel('freeagents')">Free Agents</button>
            <button class="tab" onclick="showPanel('search')">Player Search</button>
            <button class="tab" onclick="showPanel('league')">League</button>
            <button class="tab" onclick="showPanel('gmchat')" id="gmchat-tab" style="background: linear-gradient(135deg, #667eea, #764ba2); color: white;">GM Chat</button>
        </div>

        <div id="analyze-panel" class="panel active">
            <!-- Back to Suggestions Button (shown when coming from suggestions) -->
            <div id="back-to-suggestions" style="display: none; margin-bottom: 15px;">
                <button onclick="goBackToSuggestions()" style="background: linear-gradient(135deg, #3a3a5a, #4a4a6a); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; padding: 10px 20px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; gap: 8px; font-size: 0.9rem;">
                    <span style="font-size: 1.1rem;">←</span> Back to Trade Suggestions
                </button>
            </div>
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

        <div id="topplayers-panel" class="panel">
            <h3 style="margin-bottom: 15px;">Top 50 Players in the League</h3>
            <p style="color: #888; font-size: 0.85rem; margin-bottom: 15px;">The most valuable dynasty assets currently on team rosters.</p>
            <div id="topplayers-loading" class="loading">Loading top players...</div>
            <div id="topplayers-grid" style="display: grid; gap: 10px;"></div>
        </div>

        <div id="toppitchers-panel" class="panel">
            <h3 style="margin-bottom: 15px;">Top 25 Pitchers in the League</h3>
            <p style="color: #888; font-size: 0.85rem; margin-bottom: 15px;">The most valuable dynasty pitchers currently on team rosters (SP + RP).</p>
            <div id="toppitchers-loading" class="loading">Loading top pitchers...</div>
            <div id="toppitchers-grid" style="display: grid; gap: 10px;"></div>
        </div>

        <div id="tophitters-panel" class="panel">
            <h3 style="margin-bottom: 15px;">Top 25 Hitters in the League</h3>
            <p style="color: #888; font-size: 0.85rem; margin-bottom: 15px;">The most valuable dynasty hitters currently on team rosters.</p>
            <div id="tophitters-loading" class="loading">Loading top hitters...</div>
            <div id="tophitters-grid" style="display: grid; gap: 10px;"></div>
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
                        <label>My Team</label>
                        <select id="tradeFinderTeamSelect" onchange="updateTradeFinderPlayerDropdown()">
                            <option value="">Select Team</option>
                        </select>
                    </div>
                    <div class="form-group" style="flex: 1; min-width: 150px;">
                        <label>Direction</label>
                        <select id="tradeFinderDirection" onchange="updateTradeFinderPlayerDropdown()">
                            <option value="send">Trade Away</option>
                            <option value="receive">Acquire</option>
                        </select>
                    </div>
                    <div class="form-group" style="flex: 1; min-width: 180px;">
                        <label id="tradeFinderTargetLabel">Target Team (optional)</label>
                        <select id="tradeFinderTargetTeam" onchange="updateTradeFinderPlayerDropdown()">
                            <option value="">All Teams</option>
                        </select>
                    </div>
                    <div class="form-group" style="flex: 1; min-width: 200px;">
                        <label id="tradeFinderPlayerLabel">Player</label>
                        <select id="tradeFinderPlayerSelect" disabled>
                            <option value="">Select team first</option>
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
            <div style="display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 12px;">
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
            <!-- Quick Filters Row -->
            <div style="display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px; padding: 12px; background: rgba(0,0,0,0.2); border-radius: 8px;">
                <div class="form-group" style="flex: 1; min-width: 140px;">
                    <label style="font-size: 0.8rem;">Position Need</label>
                    <select id="filterPosition" onchange="applyQuickFilters()">
                        <option value="">Any Position</option>
                        <option value="SP">SP</option>
                        <option value="RP">RP</option>
                        <option value="C">C</option>
                        <option value="1B">1B</option>
                        <option value="2B">2B</option>
                        <option value="3B">3B</option>
                        <option value="SS">SS</option>
                        <option value="OF">OF</option>
                        <option value="DH">DH</option>
                    </select>
                </div>
                <div class="form-group" style="flex: 1; min-width: 140px;">
                    <label style="font-size: 0.8rem;">Min Fit Score</label>
                    <select id="filterFitScore" onchange="applyQuickFilters()">
                        <option value="0">Show All</option>
                        <option value="80">Good+ (80+)</option>
                        <option value="95">Great+ (95+)</option>
                        <option value="110">Excellent (110+)</option>
                    </select>
                </div>
                <div class="form-group" style="flex: 1; min-width: 160px;">
                    <label style="font-size: 0.8rem;">Value Difference</label>
                    <select id="filterValueDiff" onchange="applyQuickFilters()">
                        <option value="100">Show All</option>
                        <option value="20">Within 20 pts</option>
                        <option value="10">Within 10 pts</option>
                        <option value="5">Within 5 pts</option>
                    </select>
                </div>
                <div style="display: flex; align-items: flex-end;">
                    <button onclick="clearQuickFilters()" style="background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: #888; padding: 8px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem;">Clear Filters</button>
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

        <div id="gmchat-panel" class="panel">
            <div id="gmchat-container" style="display: flex; gap: 20px; height: calc(100vh - 200px); min-height: 500px;">
                <!-- Left side: Team Selection & GM Info -->
                <div id="gmchat-sidebar" style="width: 280px; flex-shrink: 0;">
                    <div style="background: linear-gradient(135deg, rgba(102,126,234,0.15), rgba(118,75,162,0.1)); border: 1px solid rgba(102,126,234,0.3); border-radius: 12px; padding: 20px;">
                        <h3 style="color: #667eea; margin: 0 0 15px 0; font-size: 1.1rem;">Select Your Team</h3>
                        <select id="gmChatTeamSelect" onchange="loadGMProfile()" style="width: 100%; padding: 10px; border-radius: 8px; background: #1a1a2e; border: 1px solid #333; color: #fff; font-size: 14px;">
                            <option value="">Choose a team...</option>
                        </select>

                        <div id="gm-profile" style="margin-top: 20px; display: none;">
                            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 15px;">
                                <div id="gm-avatar" style="width: 50px; height: 50px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: bold; color: #fff;"></div>
                                <div>
                                    <div id="gm-name" style="font-weight: bold; color: #fff;"></div>
                                    <div id="gm-title" style="font-size: 0.85rem; color: #888;"></div>
                                </div>
                            </div>
                            <div style="background: rgba(0,0,0,0.3); border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                                <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 4px;">Philosophy</div>
                                <div id="gm-philosophy" style="color: #667eea; font-weight: 500;"></div>
                            </div>
                            <div style="background: rgba(0,0,0,0.3); border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                                <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 4px;">Trade Style</div>
                                <div id="gm-tradestyle" style="color: #aaa;"></div>
                            </div>
                            <div style="background: rgba(0,0,0,0.3); border-radius: 8px; padding: 12px;">
                                <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 4px;">Team Status</div>
                                <div id="gm-teamstatus" style="color: #aaa;"></div>
                            </div>

                            <!-- Learned Preferences Section -->
                            <div id="gm-prefs-section" style="background: rgba(0,0,0,0.3); border-radius: 8px; padding: 12px; margin-top: 12px; display: none;">
                                <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 8px;">Learned Preferences</div>
                                <div id="gm-learned-prefs" style="color: #aaa; font-size: 0.85rem; line-height: 1.5;"></div>
                                <button onclick="resetPreferences()" style="margin-top: 10px; width: 100%; padding: 6px; background: rgba(255,100,100,0.2); border: 1px solid rgba(255,100,100,0.3); border-radius: 6px; color: #ff6b6b; font-size: 0.75rem; cursor: pointer;">Reset Preferences</button>
                            </div>

                            <!-- Manager Style Section (from onboarding) -->
                            <div id="gm-manager-style-section" style="background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.2); border-radius: 8px; padding: 12px; margin-top: 12px; display: none;">
                                <div style="color: #667eea; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 8px;">Your Manager Style</div>
                                <div id="gm-manager-style" style="color: #fff; font-weight: bold; margin-bottom: 4px;"></div>
                                <div id="gm-manager-desc" style="color: #888; font-size: 0.8rem; line-height: 1.4;"></div>
                                <button onclick="resetManagerStyle()" style="margin-top: 10px; width: 100%; padding: 6px; background: rgba(102,126,234,0.2); border: 1px solid rgba(102,126,234,0.3); border-radius: 6px; color: #667eea; font-size: 0.75rem; cursor: pointer;">Change Manager Style</button>
                            </div>

                            <!-- Mobile-friendly Reset Section (hidden on desktop, shown on mobile) -->
                            <div id="gm-mobile-reset-section" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 12px; margin-top: 12px; display: none;">
                                <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 10px;">Settings</div>
                                <button onclick="resetManagerStyle()" style="width: 100%; padding: 12px; background: rgba(102,126,234,0.2); border: 1px solid rgba(102,126,234,0.3); border-radius: 6px; color: #667eea; font-size: 0.9rem; cursor: pointer; margin-bottom: 8px;">Change Manager Style</button>
                                <button onclick="resetPreferences()" style="width: 100%; padding: 12px; background: rgba(255,100,100,0.2); border: 1px solid rgba(255,100,100,0.3); border-radius: 6px; color: #ff6b6b; font-size: 0.9rem; cursor: pointer;">Reset All Preferences</button>
                            </div>
                        </div>

                        <div id="gm-chat-disabled" style="margin-top: 20px; padding: 15px; background: rgba(255,100,100,0.1); border: 1px solid rgba(255,100,100,0.3); border-radius: 8px; display: none;">
                            <div style="color: #ff6b6b; font-weight: bold; margin-bottom: 8px;">Chat Unavailable</div>
                            <div style="color: #888; font-size: 0.85rem;">API key not configured. Add ANTHROPIC_API_KEY to .env file.</div>
                        </div>
                    </div>

                    <div style="margin-top: 15px; padding: 15px; background: rgba(0,212,255,0.05); border: 1px solid rgba(0,212,255,0.2); border-radius: 8px;">
                        <div style="color: #00d4ff; font-weight: bold; margin-bottom: 8px; font-size: 0.9rem;">Example Questions</div>
                        <div style="color: #888; font-size: 0.8rem; line-height: 1.6;">
                            <div style="cursor: pointer; padding: 4px 0;" onclick="askQuestion('What are my biggest roster needs?')">• What are my biggest roster needs?</div>
                            <div style="cursor: pointer; padding: 4px 0;" onclick="askQuestion('Should I be buying or selling?')">• Should I be buying or selling?</div>
                            <div style="cursor: pointer; padding: 4px 0;" onclick="askQuestion('Who should I target in trades?')">• Who should I target in trades?</div>
                            <div style="cursor: pointer; padding: 4px 0;" onclick="askQuestion('What is my championship window?')">• What is my championship window?</div>
                        </div>
                    </div>

                    <!-- Clear History Button -->
                    <button id="clear-history-btn" onclick="clearChatHistory()" style="margin-top: 15px; width: 100%; padding: 12px; background: rgba(255,77,109,0.1); border: 1px solid rgba(255,77,109,0.4); border-radius: 8px; color: #ff6b6b; font-size: 0.9rem; cursor: pointer; display: none; transition: all 0.2s;">🗑️ Clear Chat History</button>
                </div>

                <!-- Right side: Chat Interface -->
                <div style="flex: 1; display: flex; flex-direction: column; background: linear-gradient(135deg, rgba(26,26,46,0.8), rgba(22,22,35,0.9)); border: 1px solid #333; border-radius: 12px; overflow: hidden;">
                    <div id="chat-messages" style="flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 15px;">
                        <div style="text-align: center; color: #666; padding: 40px;">
                            <div style="font-size: 3rem; margin-bottom: 15px;">🤖</div>
                            <div style="font-size: 1.1rem; color: #888;">Select a team to start chatting with your AI GM</div>
                            <div style="font-size: 0.9rem; color: #666; margin-top: 8px;">Get personalized trade advice, roster analysis, and strategy tips</div>
                        </div>
                    </div>
                    <div style="padding: 15px; border-top: 1px solid #333; background: rgba(0,0,0,0.3);">
                        <div style="display: flex; gap: 10px; align-items: flex-end;">
                            <textarea id="chat-input" placeholder="Ask your GM anything..." rows="1"
                                   style="flex: 1; padding: 12px 15px; border-radius: 8px; background: #1a1a2e; border: 1px solid #444; color: #fff; font-size: 14px; resize: none; min-height: 44px; max-height: 150px; overflow-y: auto; line-height: 1.4; font-family: inherit;"
                                   onkeydown="handleChatKeydown(event)" oninput="autoResizeChatInput(this)" disabled></textarea>
                            <button onclick="sendChatMessage()" id="chat-send-btn"
                                    style="padding: 12px 25px; border-radius: 8px; background: linear-gradient(135deg, #667eea, #764ba2); border: none; color: #fff; font-weight: bold; cursor: pointer; opacity: 0.5; height: 44px;" disabled>
                                Send
                            </button>
                        </div>
                    </div>
                </div>
            </div>
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

    <div id="comparison-modal" class="modal" onclick="closeModal(event)">
        <div class="modal-content" onclick="event.stopPropagation()" style="max-width: 900px;">
            <span class="modal-close" onclick="closeComparisonModal()">&times;</span>
            <div id="comparison-modal-content"></div>
        </div>
    </div>

    <!-- GM Onboarding Questionnaire Modal -->
    <div id="gm-onboarding-modal" class="modal" style="display: none;">
        <div class="modal-content" onclick="event.stopPropagation()" style="max-width: 600px; background: linear-gradient(135deg, #1a1a2e, #16162b); border: 1px solid rgba(102,126,234,0.3);">
            <div style="text-align: center; padding: 20px 0;">
                <div style="font-size: 3rem; margin-bottom: 10px;">🤖</div>
                <h2 style="color: #667eea; margin: 0 0 10px 0;">Welcome to GM Chat</h2>
                <p style="color: #888; margin: 0;">Let's set up your managerial style so I can give you personalized advice.</p>
            </div>

            <div id="onboarding-questions" style="padding: 20px;">
                <!-- Question 1 -->
                <div class="onboarding-question" data-question="1" style="display: block;">
                    <h3 style="color: #fff; margin-bottom: 15px;">Where is your team right now?</h3>
                    <div style="display: flex; flex-direction: column; gap: 10px;">
                        <button class="onboarding-option" onclick="selectAnswer(1, 'contending')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #4ade80;">🏆 Competing for a championship</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Top 3 team, ready to win now</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(1, 'playoff')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #fbbf24;">⚡ In the playoff mix</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Competitive, pushing for playoffs</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(1, 'middle')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #60a5fa;">🤔 Middle of the pack</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Could go either way - buy or sell</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(1, 'rebuilding')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #f87171;">🔧 Rebuilding</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Focused on the future, accumulating assets</span>
                        </button>
                    </div>
                </div>

                <!-- Question 2 -->
                <div class="onboarding-question" data-question="2" style="display: none;">
                    <h3 style="color: #fff; margin-bottom: 15px;">How do you feel about trading prospects?</h3>
                    <div style="display: flex; flex-direction: column; gap: 10px;">
                        <button class="onboarding-option" onclick="selectAnswer(2, 'protect')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #4ade80;">🛡️ They're untouchable</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Building for the future - prospects are the plan</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(2, 'selective')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #fbbf24;">⚖️ I'll trade them for the right star</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Selective, but open to the right deal</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(2, 'chips')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #f87171;">💰 Prospects are trade chips</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Win now matters - use them to get proven talent</span>
                        </button>
                    </div>
                </div>

                <!-- Question 3 -->
                <div class="onboarding-question" data-question="3" style="display: none;">
                    <h3 style="color: #fff; margin-bottom: 15px;">When a trade offer comes in, you typically...</h3>
                    <div style="display: flex; flex-direction: column; gap: 10px;">
                        <button class="onboarding-option" onclick="selectAnswer(3, 'reactive')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #60a5fa;">🧘 Wait and analyze</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Take your time, no rush decisions</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(3, 'opportunistic')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #fbbf24;">🎯 Strike when value appears</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Opportunistic - jump on good deals</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(3, 'aggressive')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #f87171;">🔥 Counter aggressively</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Always negotiating, always dealing</span>
                        </button>
                    </div>
                </div>

                <!-- Question 4 -->
                <div class="onboarding-question" data-question="4" style="display: none;">
                    <h3 style="color: #fff; margin-bottom: 15px;">What's your risk tolerance?</h3>
                    <div style="display: flex; flex-direction: column; gap: 10px;">
                        <button class="onboarding-option" onclick="selectAnswer(4, 'conservative')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #4ade80;">🐢 Conservative</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Safe, steady moves - protect what you have</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(4, 'moderate')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #fbbf24;">⚖️ Moderate</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Calculated risks when the upside is there</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(4, 'aggressive')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #f87171;">🎰 Aggressive</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Swing for the fences - high risk, high reward</span>
                        </button>
                    </div>
                </div>

                <!-- Question 5 -->
                <div class="onboarding-question" data-question="5" style="display: none;">
                    <h3 style="color: #fff; margin-bottom: 15px;">Oldest player you'd build around?</h3>
                    <div style="display: flex; flex-direction: column; gap: 10px;">
                        <button class="onboarding-option" onclick="selectAnswer(5, 'young')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #4ade80;">👶 27 or younger</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Youth is everything in dynasty</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(5, 'prime')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #fbbf24;">💪 28-30</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Prime years still have value</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(5, 'veteran')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #60a5fa;">🎖️ 31-33</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">Experience matters, still productive</span>
                        </button>
                        <button class="onboarding-option" onclick="selectAnswer(5, 'any')" style="padding: 15px; background: rgba(102,126,234,0.1); border: 1px solid rgba(102,126,234,0.3); border-radius: 8px; color: #fff; cursor: pointer; text-align: left; transition: all 0.2s;">
                            <strong style="color: #f87171;">🏆 Age doesn't matter</strong><br>
                            <span style="color: #888; font-size: 0.85rem;">If they produce, they produce</span>
                        </button>
                    </div>
                </div>

                <!-- Results -->
                <div id="onboarding-result" style="display: none; text-align: center; padding: 20px;">
                    <div style="font-size: 2rem; margin-bottom: 15px;">✨</div>
                    <h3 style="color: #fff; margin-bottom: 10px;">Based on your answers...</h3>
                    <div id="result-personality" style="font-size: 1.5rem; color: #667eea; font-weight: bold; margin-bottom: 10px;"></div>
                    <p id="result-description" style="color: #888; margin-bottom: 20px;"></p>
                    <div style="display: flex; gap: 10px; justify-content: center;">
                        <button onclick="confirmPersonality()" style="padding: 12px 30px; background: linear-gradient(135deg, #667eea, #764ba2); border: none; border-radius: 8px; color: #fff; font-weight: bold; cursor: pointer;">Looks Good!</button>
                        <button onclick="restartOnboarding()" style="padding: 12px 30px; background: rgba(255,255,255,0.1); border: 1px solid #444; border-radius: 8px; color: #888; cursor: pointer;">Try Again</button>
                    </div>
                </div>
            </div>

            <!-- Progress indicator -->
            <div id="onboarding-progress" style="padding: 15px 20px; border-top: 1px solid #333; display: flex; justify-content: center; gap: 8px;">
                <div class="progress-dot" data-step="1" style="width: 10px; height: 10px; border-radius: 50%; background: #667eea;"></div>
                <div class="progress-dot" data-step="2" style="width: 10px; height: 10px; border-radius: 50%; background: #333;"></div>
                <div class="progress-dot" data-step="3" style="width: 10px; height: 10px; border-radius: 50%; background: #333;"></div>
                <div class="progress-dot" data-step="4" style="width: 10px; height: 10px; border-radius: 50%; background: #333;"></div>
                <div class="progress-dot" data-step="5" style="width: 10px; height: 10px; border-radius: 50%; background: #333;"></div>
            </div>
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

        // Player comparison state
        let comparisonPlayer1 = null;
        let comparisonPlayer2 = null;
        let comparisonMode = false;

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

        async function loadTopPlayers() {
            const grid = document.getElementById('topplayers-grid');
            const loading = document.getElementById('topplayers-loading');

            try {
                const res = await fetch(`${API_BASE}/top-players`);
                const data = await res.json();
                loading.style.display = 'none';

                if (data.players && data.players.length > 0) {
                    grid.innerHTML = data.players.map(p => {
                        const tierColor = p.rank <= 5 ? '#ffd700' : p.rank <= 10 ? '#00d4ff' : p.rank <= 20 ? '#7b2cbf' : p.rank <= 35 ? '#4a90d9' : '#6b7280';
                        const tierBg = p.rank <= 5 ? 'linear-gradient(145deg, #3d3d00, #4a4a00)' : p.rank <= 10 ? 'linear-gradient(145deg, #002a33, #003d4d)' : p.rank <= 20 ? 'linear-gradient(145deg, #2a1a3d, #3d2a50)' : 'linear-gradient(145deg, #151535, #1e1e50)';
                        const prospectBadge = p.is_prospect ? '<span style="background: #7b2cbf; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; margin-left: 8px;">PROSPECT #' + p.prospect_rank + '</span>' : '';
                        const escapedName = p.name.replace(/'/g, "\\'");
                        return `
                            <div onclick="showPlayerModal('${escapedName}')" style="background: ${tierBg}; border: 1px solid ${tierColor}40; border-radius: 10px; padding: 12px 15px; display: flex; align-items: center; gap: 15px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;" onmouseover="this.style.transform='translateX(5px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';" onmouseout="this.style.transform='none'; this.style.boxShadow='none';">
                                <div style="background: ${tierColor}20; border: 2px solid ${tierColor}; border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; font-weight: bold; color: ${tierColor}; font-size: 1.1rem;">
                                    ${p.rank}
                                </div>
                                <div style="flex: 1;">
                                    <div style="font-weight: 600; color: #fff; font-size: 1rem;">${p.name}${prospectBadge}</div>
                                    <div style="color: #888; font-size: 0.85rem;">${p.position} | ${p.mlb_team} | Age ${p.age}</div>
                                    <div style="color: #c0c0e0; font-size: 0.8rem; margin-top: 2px;">Owner: ${p.fantasy_team}</div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 1.4rem; font-weight: bold; color: ${tierColor};">${p.value}</div>
                                    <div style="color: #888; font-size: 0.75rem;">Dynasty Value</div>
                                </div>
                                <div style="color: ${tierColor}; font-size: 1.2rem;">›</div>
                            </div>
                        `;
                    }).join('');
                } else {
                    grid.innerHTML = '<p style="color: #888;">No players found.</p>';
                }
            } catch (e) {
                console.error('Failed to load top players:', e);
                loading.innerHTML = 'Failed to load top players.';
            }
        }

        async function loadTopPitchers() {
            const grid = document.getElementById('toppitchers-grid');
            const loading = document.getElementById('toppitchers-loading');

            try {
                const res = await fetch(`${API_BASE}/top-pitchers`);
                const data = await res.json();
                loading.style.display = 'none';

                if (data.players && data.players.length > 0) {
                    grid.innerHTML = data.players.map(p => {
                        const tierColor = p.rank <= 5 ? '#ffd700' : p.rank <= 10 ? '#00d4ff' : p.rank <= 15 ? '#7b2cbf' : '#4a90d9';
                        const tierBg = p.rank <= 5 ? 'linear-gradient(145deg, #3d3d00, #4a4a00)' : p.rank <= 10 ? 'linear-gradient(145deg, #002a33, #003d4d)' : p.rank <= 15 ? 'linear-gradient(145deg, #2a1a3d, #3d2a50)' : 'linear-gradient(145deg, #151535, #1e1e50)';
                        const prospectBadge = p.is_prospect ? '<span style="background: #7b2cbf; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; margin-left: 8px;">PROSPECT #' + p.prospect_rank + '</span>' : '';
                        const escapedName = p.name.replace(/'/g, "\\'");
                        return `
                            <div onclick="showPlayerModal('${escapedName}')" style="background: ${tierBg}; border: 1px solid ${tierColor}40; border-radius: 10px; padding: 12px 15px; display: flex; align-items: center; gap: 15px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;" onmouseover="this.style.transform='translateX(5px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';" onmouseout="this.style.transform='none'; this.style.boxShadow='none';">
                                <div style="background: ${tierColor}20; border: 2px solid ${tierColor}; border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; font-weight: bold; color: ${tierColor}; font-size: 1.1rem;">
                                    ${p.rank}
                                </div>
                                <div style="flex: 1;">
                                    <div style="font-weight: 600; color: #fff; font-size: 1rem;">${p.name}${prospectBadge}</div>
                                    <div style="color: #888; font-size: 0.85rem;">${p.position} | ${p.mlb_team} | Age ${p.age}</div>
                                    <div style="color: #c0c0e0; font-size: 0.8rem; margin-top: 2px;">Owner: ${p.fantasy_team}</div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 1.4rem; font-weight: bold; color: ${tierColor};">${p.value}</div>
                                    <div style="color: #888; font-size: 0.75rem;">Dynasty Value</div>
                                </div>
                                <div style="color: ${tierColor}; font-size: 1.2rem;">›</div>
                            </div>
                        `;
                    }).join('');
                } else {
                    grid.innerHTML = '<p style="color: #888;">No pitchers found.</p>';
                }
            } catch (e) {
                console.error('Failed to load top pitchers:', e);
                loading.innerHTML = 'Failed to load top pitchers.';
            }
        }

        async function loadTopHitters() {
            const grid = document.getElementById('tophitters-grid');
            const loading = document.getElementById('tophitters-loading');

            try {
                const res = await fetch(`${API_BASE}/top-hitters`);
                const data = await res.json();
                loading.style.display = 'none';

                if (data.players && data.players.length > 0) {
                    grid.innerHTML = data.players.map(p => {
                        const tierColor = p.rank <= 5 ? '#ffd700' : p.rank <= 10 ? '#00d4ff' : p.rank <= 15 ? '#7b2cbf' : '#4a90d9';
                        const tierBg = p.rank <= 5 ? 'linear-gradient(145deg, #3d3d00, #4a4a00)' : p.rank <= 10 ? 'linear-gradient(145deg, #002a33, #003d4d)' : p.rank <= 15 ? 'linear-gradient(145deg, #2a1a3d, #3d2a50)' : 'linear-gradient(145deg, #151535, #1e1e50)';
                        const prospectBadge = p.is_prospect ? '<span style="background: #7b2cbf; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; margin-left: 8px;">PROSPECT #' + p.prospect_rank + '</span>' : '';
                        const escapedName = p.name.replace(/'/g, "\\'");
                        return `
                            <div onclick="showPlayerModal('${escapedName}')" style="background: ${tierBg}; border: 1px solid ${tierColor}40; border-radius: 10px; padding: 12px 15px; display: flex; align-items: center; gap: 15px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;" onmouseover="this.style.transform='translateX(5px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';" onmouseout="this.style.transform='none'; this.style.boxShadow='none';">
                                <div style="background: ${tierColor}20; border: 2px solid ${tierColor}; border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; font-weight: bold; color: ${tierColor}; font-size: 1.1rem;">
                                    ${p.rank}
                                </div>
                                <div style="flex: 1;">
                                    <div style="font-weight: 600; color: #fff; font-size: 1rem;">${p.name}${prospectBadge}</div>
                                    <div style="color: #888; font-size: 0.85rem;">${p.position} | ${p.mlb_team} | Age ${p.age}</div>
                                    <div style="color: #c0c0e0; font-size: 0.8rem; margin-top: 2px;">Owner: ${p.fantasy_team}</div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 1.4rem; font-weight: bold; color: ${tierColor};">${p.value}</div>
                                    <div style="color: #888; font-size: 0.75rem;">Dynasty Value</div>
                                </div>
                                <div style="color: ${tierColor}; font-size: 1.2rem;">›</div>
                            </div>
                        `;
                    }).join('');
                } else {
                    grid.innerHTML = '<p style="color: #888;">No hitters found.</p>';
                }
            } catch (e) {
                console.error('Failed to load top hitters:', e);
                loading.innerHTML = 'Failed to load top hitters.';
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
            if (event && event.target) event.target.classList.add('active');

            if (panel === 'league') loadLeagueData();
            if (panel === 'freeagents') loadFASuggestions();
            if (panel === 'gmchat') initGMChat();
            if (panel === 'topplayers') loadTopPlayers();
            if (panel === 'toppitchers') loadTopPitchers();
            if (panel === 'tophitters') loadTopHitters();

            // Hide back button if navigating to analyze panel manually (not from suggestions)
            if (panel === 'analyze' && !cameFromSuggestions) {
                const backBtn = document.getElementById('back-to-suggestions');
                if (backBtn) backBtn.style.display = 'none';
            }
            // Reset the flag after using it
            if (panel !== 'analyze') {
                cameFromSuggestions = false;
            }
        }

        // ============ GM CHAT FUNCTIONS ============
        let gmChatHistory = [];
        let gmChatTeam = '';
        let gmChatEnabled = false;

        // ============ LOCAL STORAGE FUNCTIONS ============
        function getLocalChatHistory(teamName) {
            try {
                const key = `gm-chat-history-${teamName}`;
                const data = localStorage.getItem(key);
                return data ? JSON.parse(data) : [];
            } catch (e) {
                console.error('Failed to load chat history from localStorage:', e);
                return [];
            }
        }

        function saveLocalChatHistory(teamName, history) {
            try {
                const key = `gm-chat-history-${teamName}`;
                // Keep only last 50 messages to avoid storage limits
                const trimmed = history.slice(-50);
                localStorage.setItem(key, JSON.stringify(trimmed));
            } catch (e) {
                console.error('Failed to save chat history to localStorage:', e);
            }
        }

        function clearLocalChatHistory(teamName) {
            try {
                const key = `gm-chat-history-${teamName}`;
                localStorage.removeItem(key);
            } catch (e) {
                console.error('Failed to clear chat history from localStorage:', e);
            }
        }

        function getLocalPreferences(teamName) {
            try {
                const key = `gm-preferences-${teamName}`;
                const data = localStorage.getItem(key);
                return data ? JSON.parse(data) : {};
            } catch (e) {
                console.error('Failed to load preferences from localStorage:', e);
                return {};
            }
        }

        function saveLocalPreferences(teamName, prefs) {
            try {
                const key = `gm-preferences-${teamName}`;
                localStorage.setItem(key, JSON.stringify(prefs));
            } catch (e) {
                console.error('Failed to save preferences to localStorage:', e);
            }
        }

        function clearLocalPreferences(teamName) {
            try {
                const key = `gm-preferences-${teamName}`;
                localStorage.removeItem(key);
            } catch (e) {
                console.error('Failed to clear preferences from localStorage:', e);
            }
        }

        function extractPreferencesFromMessage(teamName, userMessage, assistantResponse) {
            // Simple heuristic-based preference extraction
            const prefs = getLocalPreferences(teamName);
            const msgLower = userMessage.toLowerCase();

            // Detect trade style preferences
            if (msgLower.includes('aggressive') || msgLower.includes('go all in')) {
                prefs.trade_style = 'aggressive';
            } else if (msgLower.includes('conservative') || msgLower.includes('careful')) {
                prefs.trade_style = 'conservative';
            } else if (msgLower.includes('balanced')) {
                prefs.trade_style = 'balanced';
            }

            // Detect position priorities
            const positions = ['SP', 'RP', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH'];
            positions.forEach(pos => {
                if (msgLower.includes(`need ${pos.toLowerCase()}`) || msgLower.includes(`want ${pos.toLowerCase()}`) ||
                    msgLower.includes(`prioritize ${pos.toLowerCase()}`)) {
                    if (!prefs.priority_positions) prefs.priority_positions = [];
                    if (!prefs.priority_positions.includes(pos)) {
                        prefs.priority_positions.push(pos);
                    }
                }
            });

            // Detect category priorities
            const categories = ['HR', 'RBI', 'SB', 'AVG', 'OPS', 'K', 'ERA', 'WHIP', 'QS', 'saves', 'holds'];
            categories.forEach(cat => {
                if (msgLower.includes(`need ${cat.toLowerCase()}`) || msgLower.includes(`want ${cat.toLowerCase()}`) ||
                    msgLower.includes(`improve ${cat.toLowerCase()}`)) {
                    if (!prefs.priority_categories) prefs.priority_categories = [];
                    const catUpper = cat.toUpperCase();
                    if (!prefs.priority_categories.includes(catUpper)) {
                        prefs.priority_categories.push(catUpper);
                    }
                }
            });

            // Detect target players (look for "target X" or "acquire X" patterns)
            const targetMatch = userMessage.match(/(?:target|acquire|get|trade for)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)/gi);
            if (targetMatch) {
                if (!prefs.target_players) prefs.target_players = [];
                targetMatch.forEach(match => {
                    const name = match.replace(/^(target|acquire|get|trade for)\s+/i, '').trim();
                    if (name && !prefs.target_players.includes(name)) {
                        prefs.target_players.push(name);
                    }
                });
            }

            // Detect players to avoid
            const avoidMatch = userMessage.match(/(?:avoid|don't want|stay away from)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)/gi);
            if (avoidMatch) {
                if (!prefs.avoid_players) prefs.avoid_players = [];
                avoidMatch.forEach(match => {
                    const name = match.replace(/^(avoid|don't want|stay away from)\s+/i, '').trim();
                    if (name && !prefs.avoid_players.includes(name)) {
                        prefs.avoid_players.push(name);
                    }
                });
            }

            saveLocalPreferences(teamName, prefs);
            return prefs;
        }

        // ============ GM ONBOARDING FUNCTIONS ============
        let onboardingAnswers = {};
        let currentOnboardingTeam = '';

        const PERSONALITY_MAP = {
            // Maps answer combinations to base personalities
            // Format: [team_status, prospect_attitude, trade_style, risk, age] -> personality
        };

        function hasCompletedOnboarding(teamName) {
            try {
                const key = `gm-personality-${teamName}`;
                return localStorage.getItem(key) !== null;
            } catch (e) {
                return false;
            }
        }

        function getStoredPersonality(teamName) {
            try {
                const key = `gm-personality-${teamName}`;
                const data = localStorage.getItem(key);
                return data ? JSON.parse(data) : null;
            } catch (e) {
                return null;
            }
        }

        function savePersonality(teamName, personality) {
            try {
                const key = `gm-personality-${teamName}`;
                localStorage.setItem(key, JSON.stringify(personality));
            } catch (e) {
                console.error('Failed to save personality:', e);
            }
        }

        function showOnboarding(teamName) {
            currentOnboardingTeam = teamName;
            onboardingAnswers = {};

            // Reset UI
            document.querySelectorAll('.onboarding-question').forEach(q => q.style.display = 'none');
            document.querySelector('.onboarding-question[data-question="1"]').style.display = 'block';
            document.getElementById('onboarding-result').style.display = 'none';
            document.getElementById('onboarding-progress').style.display = 'flex';

            // Reset progress dots
            document.querySelectorAll('.progress-dot').forEach(dot => {
                dot.style.background = '#333';
            });
            document.querySelector('.progress-dot[data-step="1"]').style.background = '#667eea';

            // Show modal
            document.getElementById('gm-onboarding-modal').style.display = 'flex';
        }

        function selectAnswer(questionNum, answer) {
            onboardingAnswers[questionNum] = answer;

            // Update progress dots
            document.querySelectorAll('.progress-dot').forEach(dot => {
                const step = parseInt(dot.dataset.step);
                if (step <= questionNum) {
                    dot.style.background = '#667eea';
                }
            });

            // Move to next question or show result
            if (questionNum < 5) {
                document.querySelector(`.onboarding-question[data-question="${questionNum}"]`).style.display = 'none';
                document.querySelector(`.onboarding-question[data-question="${questionNum + 1}"]`).style.display = 'block';
            } else {
                // Calculate personality and show result
                const result = calculatePersonality(onboardingAnswers);
                showOnboardingResult(result);
            }
        }

        function calculatePersonality(answers) {
            // Map answers to personality based on combination
            const status = answers[1];      // contending, playoff, middle, rebuilding
            const prospects = answers[2];   // protect, selective, chips
            const style = answers[3];       // reactive, opportunistic, aggressive
            const risk = answers[4];        // conservative, moderate, aggressive
            const age = answers[5];         // young, prime, veteran, any

            let personality = 'balanced';
            let name = 'Balanced Approach';
            let description = 'Evaluates trades purely on value, balancing present and future.';

            // Contenders
            if (status === 'contending') {
                if (prospects === 'chips' && risk === 'aggressive') {
                    personality = 'championship_closer';
                    name = 'Championship Closer';
                    description = 'Elite contender focused on closing the gap. Prospects are trade chips for proven talent.';
                } else if (prospects === 'protect') {
                    personality = 'dynasty_champion';
                    name = 'Dynasty Champion';
                    description = 'Playing from strength. Only makes moves that clearly improve an already elite roster.';
                } else {
                    personality = 'smart_contender';
                    name = 'Smart Contender';
                    description = 'Top contender who maintains flexibility. Sustainable success over flash.';
                }
            }
            // Playoff teams
            else if (status === 'playoff') {
                if (prospects === 'chips' && style === 'aggressive') {
                    personality = 'all_in_buyer';
                    name = 'All-In Buyer';
                    description = 'Committed to winning now. Prospects are currency to acquire proven talent.';
                } else if (prospects === 'protect') {
                    personality = 'loaded_and_ready';
                    name = 'Loaded & Ready';
                    description = 'Competitive roster AND deep prospects. Maximum flexibility to dictate terms.';
                } else {
                    personality = 'aggressive_buyer';
                    name = 'Aggressive Buyer';
                    description = 'Willing to part with prospects to compete now. Hard bargainer.';
                }
            }
            // Middle of pack
            else if (status === 'middle') {
                if (prospects === 'protect' && risk === 'conservative') {
                    personality = 'rising_powerhouse';
                    name = 'Rising Powerhouse';
                    description = 'Mid-pack with prospects to develop. Patiently building a future dynasty.';
                } else if (style === 'opportunistic') {
                    personality = 'value_seeker';
                    name = 'Value Seeker';
                    description = 'Opportunistic trader who buys low and sells high.';
                } else {
                    personality = 'crossroads_decision';
                    name = 'At The Crossroads';
                    description = 'Time to commit to a direction. The GM will help you decide: buy or sell?';
                }
            }
            // Rebuilding
            else if (status === 'rebuilding') {
                if (prospects === 'protect' && risk === 'conservative') {
                    personality = 'prospect_rich_rebuilder';
                    name = 'Prospect-Rich Rebuilder';
                    description = 'Deep farm system. Patiently developing talent into future stars.';
                } else if (style === 'aggressive' || risk === 'aggressive') {
                    personality = 'desperate_accumulator';
                    name = 'Desperate Accumulator';
                    description = 'Aggressively acquiring prospects through any means. Always dealing.';
                } else if (style === 'opportunistic') {
                    personality = 'analytical_rebuilder';
                    name = 'Analytical Rebuilder';
                    description = 'Data-driven rebuild. Methodical seller seeking maximum prospect returns.';
                } else {
                    personality = 'protective_rebuilder';
                    name = 'Protective Rebuilder';
                    description = 'Fiercely protective of young assets. Building carefully for the future.';
                }
            }

            return { personality, name, description };
        }

        function showOnboardingResult(result) {
            document.querySelectorAll('.onboarding-question').forEach(q => q.style.display = 'none');
            document.getElementById('onboarding-progress').style.display = 'none';

            document.getElementById('result-personality').textContent = result.name;
            document.getElementById('result-description').textContent = result.description;
            document.getElementById('onboarding-result').style.display = 'block';

            // Store temporarily for confirmation
            window.pendingPersonality = result;
        }

        function confirmPersonality() {
            if (window.pendingPersonality && currentOnboardingTeam) {
                savePersonality(currentOnboardingTeam, window.pendingPersonality);
                document.getElementById('gm-onboarding-modal').style.display = 'none';

                // Now load the GM profile with the new personality
                loadGMProfile();
            }
        }

        function restartOnboarding() {
            onboardingAnswers = {};
            document.querySelectorAll('.onboarding-question').forEach(q => q.style.display = 'none');
            document.querySelector('.onboarding-question[data-question="1"]').style.display = 'block';
            document.getElementById('onboarding-result').style.display = 'none';
            document.getElementById('onboarding-progress').style.display = 'flex';

            document.querySelectorAll('.progress-dot').forEach(dot => {
                dot.style.background = '#333';
            });
            document.querySelector('.progress-dot[data-step="1"]').style.background = '#667eea';
        }

        function resetManagerStyle() {
            const teamName = document.getElementById('gmChatTeamSelect').value;
            if (teamName) {
                try {
                    localStorage.removeItem(`gm-personality-${teamName}`);
                    showOnboarding(teamName);
                } catch (e) {
                    console.error('Failed to reset manager style:', e);
                }
            }
        }

        async function initGMChat() {
            // Populate team dropdown
            const select = document.getElementById('gmChatTeamSelect');
            if (select.options.length <= 1) {
                teamsData.forEach(team => {
                    const option = document.createElement('option');
                    option.value = team.name;
                    option.textContent = team.name;
                    select.appendChild(option);
                });
            }

            // Check if chat is enabled
            try {
                const resp = await fetch(`${API_BASE}/gm-chat-status`);
                const data = await resp.json();
                gmChatEnabled = data.enabled;
                if (!gmChatEnabled) {
                    document.getElementById('gm-chat-disabled').style.display = 'block';
                }
            } catch (e) {
                console.error('Failed to check GM chat status:', e);
            }
        }

        async function loadGMProfile() {
            const teamName = document.getElementById('gmChatTeamSelect').value;
            if (!teamName) {
                document.getElementById('gm-profile').style.display = 'none';
                document.getElementById('chat-input').disabled = true;
                document.getElementById('chat-send-btn').disabled = true;
                document.getElementById('chat-send-btn').style.opacity = '0.5';
                return;
            }

            gmChatTeam = teamName;
            gmChatHistory = [];

            // Check if user has completed onboarding for this team
            if (!hasCompletedOnboarding(teamName)) {
                showOnboarding(teamName);
                return;
            }

            try {
                // Get GM profile and team data from server
                const [gmResp, teamResp] = await Promise.all([
                    fetch(`${API_BASE}/assistant-gm/${encodeURIComponent(teamName)}`),
                    fetch(`${API_BASE}/team/${encodeURIComponent(teamName)}`)
                ]);

                const gm = await gmResp.json();
                const team = await teamResp.json();

                // Load chat history and preferences from localStorage (user's browser)
                const history = getLocalChatHistory(teamName);
                const prefs = getLocalPreferences(teamName);

                // Update GM profile display
                document.getElementById('gm-avatar').textContent = gm.name.charAt(0);
                document.getElementById('gm-name').textContent = gm.name;
                document.getElementById('gm-title').textContent = gm.title;
                document.getElementById('gm-philosophy').textContent = gm.philosophy_details?.name || gm.philosophy;
                document.getElementById('gm-tradestyle').textContent = gm.trade_style;
                document.getElementById('gm-teamstatus').innerHTML = `#${team.power_rank} Power Rank<br>${team.total_value?.toFixed(0) || 0} Total Value`;
                document.getElementById('gm-profile').style.display = 'block';

                // Display learned preferences if any (from localStorage)
                const prefsContainer = document.getElementById('gm-learned-prefs');
                if (prefsContainer) {
                    const hasPref = prefs.trade_style || prefs.priority_positions?.length || prefs.priority_categories?.length || prefs.target_players?.length || prefs.avoid_players?.length;

                    if (hasPref) {
                        let prefsHtml = '';
                        // Helper to filter valid player names (remove garbage data)
                        const isValidPlayerName = (name) => {
                            if (!name || typeof name !== 'string') return false;
                            if (name.length < 4 || name.length > 40) return false;
                            // Filter out common garbage phrases that might have been saved
                            const invalidPhrases = ['in trades', 'preference', 'target', 'avoid', 'player', 'trade for', 'trade away'];
                            const lowerName = name.toLowerCase();
                            return !invalidPhrases.some(phrase => lowerName.includes(phrase));
                        };
                        if (prefs.trade_style) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #667eea;">Style:</span> ${prefs.trade_style}</div>`;
                        if (prefs.priority_positions?.length) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #667eea;">Positions:</span> ${prefs.priority_positions.join(', ')}</div>`;
                        if (prefs.priority_categories?.length) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #667eea;">Categories:</span> ${prefs.priority_categories.join(', ')}</div>`;
                        const validTargets = prefs.target_players?.filter(isValidPlayerName) || [];
                        if (validTargets.length) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #00ff88;">Targets:</span> ${validTargets.slice(0, 3).join(', ')}</div>`;
                        const validAvoid = prefs.avoid_players?.filter(isValidPlayerName) || [];
                        if (validAvoid.length) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #ff6b6b;">Avoid:</span> ${validAvoid.slice(0, 3).join(', ')}</div>`;
                        prefsContainer.innerHTML = prefsHtml;
                        prefsContainer.style.display = 'block';
                        document.getElementById('gm-prefs-section').style.display = 'block';
                    } else {
                        prefsContainer.style.display = 'none';
                        document.getElementById('gm-prefs-section').style.display = 'none';
                    }
                }

                // Display user's manager style (from onboarding)
                const storedPersonality = getStoredPersonality(teamName);
                if (storedPersonality) {
                    document.getElementById('gm-manager-style').textContent = storedPersonality.name;
                    document.getElementById('gm-manager-desc').textContent = storedPersonality.description;
                    document.getElementById('gm-manager-style-section').style.display = 'block';
                } else {
                    document.getElementById('gm-manager-style-section').style.display = 'none';
                }

                // Show mobile reset section on small screens (CSS handles display, JS just ensures it exists)
                const mobileResetSection = document.getElementById('gm-mobile-reset-section');
                if (mobileResetSection && window.innerWidth <= 480) {
                    mobileResetSection.style.display = 'block';
                }

                // Enable chat if API is available
                if (gmChatEnabled) {
                    document.getElementById('chat-input').disabled = false;
                    document.getElementById('chat-send-btn').disabled = false;
                    document.getElementById('chat-send-btn').style.opacity = '1';
                }

                // Build chat messages - start with welcome, then add history
                const chatMessages = document.getElementById('chat-messages');
                let messagesHtml = `
                    <div style="display: flex; gap: 12px; align-items: flex-start;">
                        <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff; flex-shrink: 0;">${gm.name.charAt(0)}</div>
                        <div style="background: rgba(102,126,234,0.15); border: 1px solid rgba(102,126,234,0.3); border-radius: 12px; padding: 15px; max-width: 80%;">
                            <div style="color: #667eea; font-weight: bold; margin-bottom: 8px;">${gm.name}</div>
                            <div style="color: #ddd; line-height: 1.5;">${gm.catchphrase}</div>
                            <div style="color: #888; font-size: 0.85rem; margin-top: 10px;">Ask me anything about the ${teamName} - trades, roster moves, strategy, or just chat about the team!</div>
                        </div>
                    </div>
                `;

                // Add chat history if exists (from localStorage)
                if (history.length > 0) {
                    messagesHtml += `
                        <div style="text-align: center; margin: 15px 0;">
                            <span style="background: rgba(102,126,234,0.2); color: #888; font-size: 0.75rem; padding: 4px 12px; border-radius: 12px;">Previous conversation</span>
                        </div>
                    `;

                    history.forEach(msg => {
                        if (msg.role === 'user') {
                            messagesHtml += `
                                <div style="display: flex; gap: 12px; align-items: flex-start; justify-content: flex-end;">
                                    <div style="background: rgba(0,212,255,0.15); border: 1px solid rgba(0,212,255,0.3); border-radius: 12px; padding: 15px; max-width: 80%;">
                                        <div style="color: #ddd; line-height: 1.5;">${escapeHtml(msg.content)}</div>
                                    </div>
                                    <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #00d4ff, #0099cc); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff; flex-shrink: 0;">You</div>
                                </div>
                            `;
                        } else {
                            messagesHtml += `
                                <div style="display: flex; gap: 12px; align-items: flex-start;">
                                    <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff; flex-shrink: 0;">${gm.name.charAt(0)}</div>
                                    <div style="background: rgba(102,126,234,0.15); border: 1px solid rgba(102,126,234,0.3); border-radius: 12px; padding: 15px; max-width: 80%;">
                                        <div style="color: #667eea; font-weight: bold; margin-bottom: 8px;">${gm.name}</div>
                                        <div style="color: #ddd; line-height: 1.6; white-space: pre-wrap;">${escapeHtml(msg.content)}</div>
                                    </div>
                                </div>
                            `;
                        }
                        // Add to local history for context
                        gmChatHistory.push({ role: msg.role, content: msg.content });
                    });
                }

                chatMessages.innerHTML = messagesHtml;
                chatMessages.scrollTop = chatMessages.scrollHeight;

                // Show Clear History button if there's history
                const clearBtn = document.getElementById('clear-history-btn');
                if (clearBtn) {
                    clearBtn.style.display = history.length > 0 ? 'block' : 'none';
                }

            } catch (e) {
                console.error('Failed to load GM profile:', e);
            }
        }

        // Handle chat input keyboard events (Enter to send, Shift+Enter for new line)
        function handleChatKeydown(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendChatMessage();
            }
        }

        // Auto-resize chat textarea as user types
        function autoResizeChatInput(textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
        }

        function askQuestion(question) {
            if (!gmChatTeam) {
                alert('Please select a team first');
                return;
            }
            document.getElementById('chat-input').value = question;
            sendChatMessage();
        }

        async function sendChatMessage() {
            const input = document.getElementById('chat-input');
            const message = input.value.trim();

            if (!message || !gmChatTeam || !gmChatEnabled) return;

            // Add user message to chat
            const chatMessages = document.getElementById('chat-messages');
            chatMessages.innerHTML += `
                <div style="display: flex; gap: 12px; align-items: flex-start; justify-content: flex-end;">
                    <div style="background: rgba(0,212,255,0.15); border: 1px solid rgba(0,212,255,0.3); border-radius: 12px; padding: 15px; max-width: 80%;">
                        <div style="color: #ddd; line-height: 1.5;">${escapeHtml(message)}</div>
                    </div>
                    <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #00d4ff, #0099cc); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff; flex-shrink: 0;">You</div>
                </div>
            `;

            // Add to history
            gmChatHistory.push({ role: 'user', content: message });

            // Clear input and show loading
            input.value = '';
            input.style.height = '44px';  // Reset textarea height
            const loadingId = 'loading-' + Date.now();
            chatMessages.innerHTML += `
                <div id="${loadingId}" style="display: flex; gap: 12px; align-items: flex-start;">
                    <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff; flex-shrink: 0;">...</div>
                    <div style="background: rgba(102,126,234,0.15); border: 1px solid rgba(102,126,234,0.3); border-radius: 12px; padding: 15px;">
                        <div style="color: #888;">Thinking...</div>
                    </div>
                </div>
            `;
            chatMessages.scrollTop = chatMessages.scrollHeight;

            try {
                // Get preferences from localStorage to send to server
                const userPrefs = getLocalPreferences(gmChatTeam);

                const response = await fetch(`${API_BASE}/gm-chat/${encodeURIComponent(gmChatTeam)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: message,
                        history: gmChatHistory.slice(-10),
                        preferences: userPrefs
                    })
                });

                const data = await response.json();

                // Remove loading
                document.getElementById(loadingId)?.remove();

                if (data.error) {
                    chatMessages.innerHTML += `
                        <div style="display: flex; gap: 12px; align-items: flex-start;">
                            <div style="width: 36px; height: 36px; background: #ff4d6d; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff; flex-shrink: 0;">!</div>
                            <div style="background: rgba(255,77,109,0.15); border: 1px solid rgba(255,77,109,0.3); border-radius: 12px; padding: 15px;">
                                <div style="color: #ff6b6b;">${escapeHtml(data.error)}</div>
                            </div>
                        </div>
                    `;
                } else {
                    // Add assistant response
                    const gmName = document.getElementById('gm-name').textContent;
                    gmChatHistory.push({ role: 'assistant', content: data.response });

                    chatMessages.innerHTML += `
                        <div style="display: flex; gap: 12px; align-items: flex-start;">
                            <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff; flex-shrink: 0;">${gmName.charAt(0)}</div>
                            <div style="background: rgba(102,126,234,0.15); border: 1px solid rgba(102,126,234,0.3); border-radius: 12px; padding: 15px; max-width: 80%;">
                                <div style="color: #667eea; font-weight: bold; margin-bottom: 8px;">${gmName}</div>
                                <div style="color: #ddd; line-height: 1.6; white-space: pre-wrap;">${escapeHtml(data.response)}</div>
                            </div>
                        </div>
                    `;

                    // Save chat history to localStorage
                    saveLocalChatHistory(gmChatTeam, gmChatHistory);

                    // Extract and save preferences from conversation
                    const updatedPrefs = extractPreferencesFromMessage(gmChatTeam, message, data.response);

                    // Update preferences display if any new preferences learned
                    updatePreferencesDisplay(updatedPrefs);
                }

                chatMessages.scrollTop = chatMessages.scrollHeight;

                // Show clear history button after successful message
                const clearBtn = document.getElementById('clear-history-btn');
                if (clearBtn) clearBtn.style.display = 'block';

            } catch (e) {
                document.getElementById(loadingId)?.remove();
                chatMessages.innerHTML += `
                    <div style="display: flex; gap: 12px; align-items: flex-start;">
                        <div style="width: 36px; height: 36px; background: #ff4d6d; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff; flex-shrink: 0;">!</div>
                        <div style="background: rgba(255,77,109,0.15); border: 1px solid rgba(255,77,109,0.3); border-radius: 12px; padding: 15px;">
                            <div style="color: #ff6b6b;">Failed to get response. Please try again.</div>
                        </div>
                    </div>
                `;
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function updatePreferencesDisplay(prefs) {
            const prefsContainer = document.getElementById('gm-learned-prefs');
            if (!prefsContainer) return;

            // Helper to filter valid player names (remove garbage data)
            const isValidPlayerName = (name) => {
                if (!name || typeof name !== 'string') return false;
                if (name.length < 4 || name.length > 40) return false;
                // Filter out common garbage phrases that might have been saved
                const invalidPhrases = ['in trades', 'preference', 'target', 'avoid', 'player', 'trade for', 'trade away'];
                const lowerName = name.toLowerCase();
                return !invalidPhrases.some(phrase => lowerName.includes(phrase));
            };

            const validTargets = prefs.target_players?.filter(isValidPlayerName) || [];
            const validAvoid = prefs.avoid_players?.filter(isValidPlayerName) || [];
            const hasPref = prefs.trade_style || prefs.priority_positions?.length || prefs.priority_categories?.length || validTargets.length || validAvoid.length;

            if (hasPref) {
                let prefsHtml = '';
                if (prefs.trade_style) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #667eea;">Style:</span> ${prefs.trade_style}</div>`;
                if (prefs.priority_positions?.length) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #667eea;">Positions:</span> ${prefs.priority_positions.join(', ')}</div>`;
                if (prefs.priority_categories?.length) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #667eea;">Categories:</span> ${prefs.priority_categories.join(', ')}</div>`;
                if (validTargets.length) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #00ff88;">Targets:</span> ${validTargets.slice(0, 3).join(', ')}</div>`;
                if (validAvoid.length) prefsHtml += `<div style="margin-bottom: 4px;"><span style="color: #ff6b6b;">Avoid:</span> ${validAvoid.slice(0, 3).join(', ')}</div>`;
                prefsContainer.innerHTML = prefsHtml;
                prefsContainer.style.display = 'block';
                document.getElementById('gm-prefs-section').style.display = 'block';
            }
        }

        function clearChatHistory() {
            if (!gmChatTeam) return;
            if (!confirm('Clear all chat history for ' + gmChatTeam + '?')) return;

            // Clear from localStorage
            clearLocalChatHistory(gmChatTeam);
            gmChatHistory = [];
            document.getElementById('clear-history-btn').style.display = 'none';
            // Reload GM profile to reset chat
            loadGMProfile();
        }

        function resetPreferences() {
            if (!gmChatTeam) return;
            if (!confirm('Reset learned preferences for ' + gmChatTeam + '?')) return;

            // Clear from localStorage
            clearLocalPreferences(gmChatTeam);
            document.getElementById('gm-prefs-section').style.display = 'none';
            document.getElementById('gm-learned-prefs').innerHTML = '';
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

                // Calculate net results for each team
                const netA = data.value_a_receives - data.value_a_sends;
                const netB = data.value_b_receives - data.value_b_sends;
                const netAColor = netA >= 0 ? '#4ade80' : '#f87171';
                const netBColor = netB >= 0 ? '#4ade80' : '#f87171';
                const netASign = netA >= 0 ? '+' : '';
                const netBSign = netB >= 0 ? '+' : '';

                results.innerHTML = `
                    <div class="result-card">
                        <div class="verdict ${verdictClass}">${data.verdict}</div>
                        <div class="value-comparison">
                            <div class="value-box">
                                <h4>${teamA}</h4>
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px;">
                                    <div style="text-align: center;">
                                        <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 4px;">Sends</div>
                                        <div style="color: #f87171; font-size: 1.2rem; font-weight: bold;">${data.value_a_sends.toFixed(1)}</div>
                                    </div>
                                    <div style="text-align: center;">
                                        <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 4px;">Receives</div>
                                        <div style="color: #4ade80; font-size: 1.2rem; font-weight: bold;">${data.value_a_receives.toFixed(1)}</div>
                                    </div>
                                </div>
                                <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(0, 212, 255, 0.1); text-align: center;">
                                    <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 4px;">Net Result</div>
                                    <div style="color: ${netAColor}; font-size: 1.6rem; font-weight: bold;">${netASign}${netA.toFixed(1)}</div>
                                </div>
                                ${data.age_analysis?.team_b_sends_avg_age ? `<div style="color:#a0a0c0;font-size:0.8rem;margin-top:10px;text-align:center;">Incoming Avg Age: ${data.age_analysis.team_b_sends_avg_age}</div>` : ''}
                            </div>
                            <div class="value-box">
                                <h4>${teamB}</h4>
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px;">
                                    <div style="text-align: center;">
                                        <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 4px;">Sends</div>
                                        <div style="color: #f87171; font-size: 1.2rem; font-weight: bold;">${data.value_b_sends.toFixed(1)}</div>
                                    </div>
                                    <div style="text-align: center;">
                                        <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 4px;">Receives</div>
                                        <div style="color: #4ade80; font-size: 1.2rem; font-weight: bold;">${data.value_b_receives.toFixed(1)}</div>
                                    </div>
                                </div>
                                <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(0, 212, 255, 0.1); text-align: center;">
                                    <div style="color: #888; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 4px;">Net Result</div>
                                    <div style="color: ${netBColor}; font-size: 1.6rem; font-weight: bold;">${netBSign}${netB.toFixed(1)}</div>
                                </div>
                                ${data.age_analysis?.team_a_sends_avg_age ? `<div style="color:#a0a0c0;font-size:0.8rem;margin-top:10px;text-align:center;">Incoming Avg Age: ${data.age_analysis.team_a_sends_avg_age}</div>` : ''}
                            </div>
                        </div>
                        <div style="padding: 18px; background: linear-gradient(145deg, #151535, #1e1e50); border-radius: 12px; margin: 18px 0; border-left: 4px solid #7b2cbf;">
                            <div style="white-space: pre-line; line-height: 1.7; color: #d0d0e0;">${data.detailed_analysis || data.reasoning}</div>
                        </div>
                        ${data.category_impact && data.category_impact.length > 0 ? `
                            <div style="display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0;">
                                ${data.category_impact.map(c => `<span style="background: linear-gradient(135deg, #14141c, #1a1a24); padding: 8px 16px; border-radius: 20px; font-size: 0.9rem; border: 1px solid rgba(0, 212, 255, 0.2);">${c}</span>`).join('')}
                            </div>
                        ` : ''}
                        ${data.trade_impact ? `
                            <div style="margin: 20px 0; padding: 20px; background: linear-gradient(145deg, #0a1520, #0f1a25); border-radius: 12px; border: 1px solid rgba(0, 212, 255, 0.15);">
                                <h4 style="color: #00d4ff; margin: 0 0 16px 0; display: flex; align-items: center; gap: 8px;">
                                    <span style="font-size: 1.2rem;">📊</span> Trade Impact Simulator
                                </h4>
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                                    <!-- Team A Impact -->
                                    <div style="background: rgba(123, 44, 191, 0.1); border-radius: 10px; padding: 16px; border: 1px solid rgba(123, 44, 191, 0.2);">
                                        <div style="font-weight: bold; color: #7b2cbf; margin-bottom: 12px; font-size: 0.95rem;">${teamA}</div>
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding: 12px; background: rgba(0,0,0,0.3); border-radius: 8px;">
                                            <span style="color: #888; font-size: 0.85rem;">Championship Odds</span>
                                            <div style="text-align: right;">
                                                <span style="color: #a0a0c0;">${data.trade_impact.team_a.odds_before}%</span>
                                                <span style="color: #666; margin: 0 6px;">→</span>
                                                <span style="color: ${data.trade_impact.team_a.odds_change >= 0 ? '#00ff88' : '#ff4d6d'}; font-weight: bold;">${data.trade_impact.team_a.odds_after}%</span>
                                                <span style="color: ${data.trade_impact.team_a.odds_change >= 0 ? '#00ff88' : '#ff4d6d'}; font-size: 0.8rem; margin-left: 6px;">(${data.trade_impact.team_a.odds_change >= 0 ? '+' : ''}${data.trade_impact.team_a.odds_change}%)</span>
                                            </div>
                                        </div>
                                        ${data.trade_impact.team_a.ranking_changes.length > 0 ? `
                                            <div style="font-size: 0.8rem; color: #888; margin-bottom: 8px;">Category Ranking Changes:</div>
                                            <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                                                ${data.trade_impact.team_a.ranking_changes.slice(0, 6).map(c => `
                                                    <span style="background: ${c.is_improvement ? 'rgba(0,255,136,0.15)' : 'rgba(255,77,109,0.15)'}; border: 1px solid ${c.is_improvement ? 'rgba(0,255,136,0.3)' : 'rgba(255,77,109,0.3)'}; padding: 4px 10px; border-radius: 15px; font-size: 0.8rem;">
                                                        <span style="color: ${c.is_improvement ? '#00ff88' : '#ff4d6d'};">${c.category}</span>
                                                        <span style="color: #888;">#${c.before}</span>
                                                        <span style="color: #666;">→</span>
                                                        <span style="color: ${c.is_improvement ? '#00ff88' : '#ff4d6d'}; font-weight: bold;">#${c.after}</span>
                                                    </span>
                                                `).join('')}
                                            </div>
                                            <div style="margin-top: 10px; font-size: 0.8rem; color: #888;">
                                                <span style="color: #00ff88;">↑ ${data.trade_impact.team_a.categories_improved}</span> improved,
                                                <span style="color: #ff4d6d;">↓ ${data.trade_impact.team_a.categories_worsened}</span> worsened
                                            </div>
                                        ` : '<div style="color: #666; font-size: 0.85rem;">No ranking changes</div>'}
                                    </div>
                                    <!-- Team B Impact -->
                                    <div style="background: rgba(123, 44, 191, 0.1); border-radius: 10px; padding: 16px; border: 1px solid rgba(123, 44, 191, 0.2);">
                                        <div style="font-weight: bold; color: #7b2cbf; margin-bottom: 12px; font-size: 0.95rem;">${teamB}</div>
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding: 12px; background: rgba(0,0,0,0.3); border-radius: 8px;">
                                            <span style="color: #888; font-size: 0.85rem;">Championship Odds</span>
                                            <div style="text-align: right;">
                                                <span style="color: #a0a0c0;">${data.trade_impact.team_b.odds_before}%</span>
                                                <span style="color: #666; margin: 0 6px;">→</span>
                                                <span style="color: ${data.trade_impact.team_b.odds_change >= 0 ? '#00ff88' : '#ff4d6d'}; font-weight: bold;">${data.trade_impact.team_b.odds_after}%</span>
                                                <span style="color: ${data.trade_impact.team_b.odds_change >= 0 ? '#00ff88' : '#ff4d6d'}; font-size: 0.8rem; margin-left: 6px;">(${data.trade_impact.team_b.odds_change >= 0 ? '+' : ''}${data.trade_impact.team_b.odds_change}%)</span>
                                            </div>
                                        </div>
                                        ${data.trade_impact.team_b.ranking_changes.length > 0 ? `
                                            <div style="font-size: 0.8rem; color: #888; margin-bottom: 8px;">Category Ranking Changes:</div>
                                            <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                                                ${data.trade_impact.team_b.ranking_changes.slice(0, 6).map(c => `
                                                    <span style="background: ${c.is_improvement ? 'rgba(0,255,136,0.15)' : 'rgba(255,77,109,0.15)'}; border: 1px solid ${c.is_improvement ? 'rgba(0,255,136,0.3)' : 'rgba(255,77,109,0.3)'}; padding: 4px 10px; border-radius: 15px; font-size: 0.8rem;">
                                                        <span style="color: ${c.is_improvement ? '#00ff88' : '#ff4d6d'};">${c.category}</span>
                                                        <span style="color: #888;">#${c.before}</span>
                                                        <span style="color: #666;">→</span>
                                                        <span style="color: ${c.is_improvement ? '#00ff88' : '#ff4d6d'}; font-weight: bold;">#${c.after}</span>
                                                    </span>
                                                `).join('')}
                                            </div>
                                            <div style="margin-top: 10px; font-size: 0.8rem; color: #888;">
                                                <span style="color: #00ff88;">↑ ${data.trade_impact.team_b.categories_improved}</span> improved,
                                                <span style="color: #ff4d6d;">↓ ${data.trade_impact.team_b.categories_worsened}</span> worsened
                                            </div>
                                        ` : '<div style="color: #666; font-size: 0.85rem;">No ranking changes</div>'}
                                    </div>
                                </div>
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
                <div style="margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                        <span style="color: #e4e4e4; font-weight: 600; font-size: 0.9rem;">${cat}</span>
                        <span style="color: ${color}; font-weight: bold;">${displayVal} <span style="color: #888; font-weight: normal; font-size: 0.85rem;">(#${rank})</span></span>
                    </div>
                    <div style="background: #0a0a12; height: 10px; border-radius: 5px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, ${color}, ${color}88); width: ${rankPct}%; height: 100%; border-radius: 5px; transition: width 0.3s ease;"></div>
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

                // Check for server error
                if (data.error) {
                    content.innerHTML = '<div style="color: #ff4d6d; padding: 20px;"><h3>Server Error</h3><p>' + data.error + '</p><pre style="font-size: 10px; overflow: auto; max-height: 300px; background: #0a0a10; padding: 10px; border-radius: 5px;">' + (data.traceback || '') + '</pre></div>';
                    return;
                }

                const numTeams = data.num_teams || 12;
                const cats = data.category_details || {};
                const comp = data.roster_composition || {};
                const posDepth = data.positional_depth || {};
                currentTeamDepth = posDepth;  // Store for position modal

                content.innerHTML = `
                    <h2 style="color: #ffd700; margin-bottom: 5px;">#${data.power_rank} ${data.name}</h2>
                    <div style="font-size: 0.9rem; color: #888; margin-bottom: 15px;">2026 Draft Pick: #${data.draft_pick}</div>

                    <!-- Quick Stats -->
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 16px; margin-bottom: 28px;">
                        <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 16px 14px; border-radius: 10px; text-align: center; border: 1px solid rgba(255, 215, 0, 0.15);">
                            <div style="color: #999; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Total Value</div>
                            <div style="color: #ffd700; font-size: 1.4rem; font-weight: bold;">${data.total_value.toFixed(1)}</div>
                        </div>
                        <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 16px 14px; border-radius: 10px; text-align: center; border: 1px solid rgba(0, 212, 255, 0.1);">
                            <div style="color: #999; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Avg Age</div>
                            <div style="color: #e4e4e4; font-size: 1.4rem; font-weight: bold;">${comp.avg_age || 'N/A'}</div>
                        </div>
                        <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 16px 14px; border-radius: 10px; text-align: center; border: 1px solid rgba(0, 212, 255, 0.1);">
                            <div style="color: #999; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Roster</div>
                            <div style="color: #e4e4e4; font-size: 1.4rem; font-weight: bold;">${data.player_count}</div>
                        </div>
                        <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 16px 14px; border-radius: 10px; text-align: center; border: 1px solid rgba(74, 222, 128, 0.15);">
                            <div style="color: #999; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Prospects</div>
                            <div style="color: #4ade80; font-size: 1.4rem; font-weight: bold;">${(data.prospects || []).length}</div>
                        </div>
                    </div>

                    <!-- Roster Composition -->
                    <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid rgba(0, 212, 255, 0.1);">
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
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 28px;">
                        <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 20px; border-radius: 12px; border: 1px solid rgba(0, 212, 255, 0.1);">
                            <h4 style="color: #00d4ff; margin: 0 0 20px 0; font-size: 0.95rem; letter-spacing: 0.5px; padding-bottom: 12px; border-bottom: 1px solid rgba(0, 212, 255, 0.1);">HITTING CATEGORIES</h4>
                            ${cats.HR ? renderCategoryBar('HR', cats.HR.value, cats.HR.rank, numTeams) : ''}
                            ${cats.RBI ? renderCategoryBar('RBI', cats.RBI.value, cats.RBI.rank, numTeams) : ''}
                            ${cats.R ? renderCategoryBar('R', cats.R.value, cats.R.rank, numTeams) : ''}
                            ${cats.SB ? renderCategoryBar('SB', cats.SB.value, cats.SB.rank, numTeams) : ''}
                            ${cats.AVG ? renderCategoryBar('AVG', cats.AVG.value, cats.AVG.rank, numTeams) : ''}
                            ${cats.OPS ? renderCategoryBar('OPS', cats.OPS.value, cats.OPS.rank, numTeams) : ''}
                            ${cats.SO ? renderCategoryBar('SO', cats.SO.value, cats.SO.rank, numTeams, true) : ''}
                        </div>
                        <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 20px; border-radius: 12px; border: 1px solid rgba(0, 212, 255, 0.1);">
                            <h4 style="color: #00d4ff; margin: 0 0 20px 0; font-size: 0.95rem; letter-spacing: 0.5px; padding-bottom: 12px; border-bottom: 1px solid rgba(0, 212, 255, 0.1);">PITCHING CATEGORIES</h4>
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
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 28px;">
                        <div style="background: rgba(74, 222, 128, 0.08); padding: 16px 18px; border-radius: 10px; border: 1px solid rgba(74, 222, 128, 0.25);">
                            <div style="color: #4ade80; font-size: 0.8rem; font-weight: bold; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">STRENGTHS</div>
                            <div style="color: #e4e4e4; font-size: 0.95rem; line-height: 1.5;">${[...(data.hitting_strengths || []), ...(data.pitching_strengths || [])].join(', ') || 'None'}</div>
                        </div>
                        <div style="background: rgba(248, 113, 113, 0.08); padding: 16px 18px; border-radius: 10px; border: 1px solid rgba(248, 113, 113, 0.25);">
                            <div style="color: #f87171; font-size: 0.8rem; font-weight: bold; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">WEAKNESSES</div>
                            <div style="color: #e4e4e4; font-size: 0.95rem; line-height: 1.5;">${[...(data.hitting_weaknesses || []), ...(data.pitching_weaknesses || [])].join(', ') || 'None'}</div>
                        </div>
                    </div>

                    <!-- Analysis -->
                    ${data.analysis ? `<div style="margin-bottom: 25px; padding: 15px; background: linear-gradient(135deg, #0a0a10, #0e0e16); border-radius: 10px; line-height: 1.7; border: 1px solid rgba(0, 212, 255, 0.1);">${data.analysis}</div>` : ''}

                    <!-- Positional Depth -->
                    <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 20px; border-radius: 12px; margin-bottom: 28px; border: 1px solid rgba(0, 212, 255, 0.1);">
                        <h4 style="color: #00d4ff; margin: 0 0 18px 0; font-size: 0.95rem; letter-spacing: 0.5px;">POSITIONAL DEPTH <span style="color: #888; font-size: 0.75rem; font-weight: normal;">(click to view all)</span></h4>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px;">
                            ${['C', '1B', '2B', 'SS', '3B', 'OF', 'UT', 'SP', 'RP'].map(pos => {
                                const players = posDepth[pos] || [];
                                const depthColor = players.length >= 3 ? '#4ade80' : (players.length >= 2 ? '#ffd700' : '#f87171');
                                return `
                                    <div onclick="showPositionDepth('${pos}')" style="background: linear-gradient(145deg, #0e0e14, #12121a); padding: 14px; border-radius: 10px; cursor: pointer; transition: all 0.2s ease; border: 1px solid rgba(0, 212, 255, 0.08);" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 6px 16px rgba(0,212,255,0.15)';this.style.borderColor='rgba(0,212,255,0.25)'" onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='none';this.style.borderColor='rgba(0,212,255,0.08)'">
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                                            <span style="color: #00d4ff; font-weight: bold; font-size: 1rem;">${pos}</span>
                                            <span style="color: ${depthColor}; font-size: 0.8rem; font-weight: 600;">${players.length} deep</span>
                                        </div>
                                        ${players.slice(0, 3).map((p, i) => `
                                            <div style="font-size: 0.8rem; color: ${i === 0 ? '#e4e4e4' : '#999'}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 2px 0;">
                                                ${p.name} <span style="color: #00d4ff;">(${p.value})</span>
                                            </div>
                                        `).join('')}
                                        ${players.length === 0 ? '<div style="font-size: 0.8rem; color: #555; font-style: italic;">No depth</div>' : ''}
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
                    ['C', '1B', '2B', 'SS', '3B', 'OF', 'UT', 'SP', 'RP'].forEach(pos => {
                        const players = posDepth[pos] || [];
                        const posColor = ['SP', 'RP'].includes(pos) ? '#00d4ff' : '#ffd700';
                        const depthColor = players.length >= 3 ? '#4ade80' : (players.length >= 2 ? '#ffd700' : '#f87171');

                        const posDiv = document.createElement('div');
                        posDiv.style.cssText = 'background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 15px; border-radius: 10px; border: 1px solid rgba(0, 212, 255, 0.1);';

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
                        ${players.map((p, i) => {
                            const val = parseFloat(p.value);
                            let tierClass = 'tier-depth'; let tierLabel = 'D';
                            if (val >= 100) { tierClass = 'tier-superstar'; tierLabel = 'S+'; }
                            else if (val >= 80) { tierClass = 'tier-elite'; tierLabel = 'E'; }
                            else if (val >= 60) { tierClass = 'tier-star'; tierLabel = 'S'; }
                            else if (val >= 40) { tierClass = 'tier-solid'; tierLabel = 'B'; }
                            return `
                            <div class="player-card" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}'); event.stopPropagation();" style="cursor: pointer;">
                                <div style="display: flex; align-items: center; gap: 12px;">
                                    <span style="color: #888; font-size: 0.8rem; width: 24px;">#${i + 1}</span>
                                    <div>
                                        <div class="name player-link">${p.name}</div>
                                        <div style="color: #888; font-size: 0.8rem;">Age ${p.age || '?'}</div>
                                    </div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <span class="tier-badge ${tierClass}" style="font-size: 0.6rem; padding: 2px 8px;">${tierLabel}</span>
                                    <div class="value">${p.value}</div>
                                </div>
                            </div>
                        `}).join('')}
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
                    // Separate hitting and pitching projections (P_ prefix indicates pitching for two-way players)
                    const hittingKeys = Object.entries(data.projections).filter(([key]) => !key.startsWith('P_') && !['estimated_pitcher', 'estimated_hitter'].includes(key));
                    const pitchingKeys = Object.entries(data.projections).filter(([key]) => key.startsWith('P_'));

                    const formatStat = (key, val) => {
                        let displayKey = key.startsWith('P_') ? key.substring(2) : key;
                        let displayVal;
                        if (typeof val === 'number') {
                            if (['AVG', 'OBP', 'SLG', 'OPS', 'WHIP', 'P_WHIP'].includes(key)) {
                                displayVal = val.toFixed(3);
                            } else if (['ERA', 'K/BB', 'P_ERA'].includes(key)) {
                                displayVal = val.toFixed(2);
                            } else {
                                displayVal = Math.round(val);
                            }
                        } else {
                            displayVal = val;
                        }
                        return '<div class="stat-box"><div class="label">' + displayKey + '</div><div class="value">' + displayVal + '</div></div>';
                    };

                    const hittingItems = hittingKeys.map(([key, val]) => formatStat(key, val)).join('');
                    const pitchingItems = pitchingKeys.map(([key, val]) => formatStat(key, val)).join('');

                    // Check if this is a two-way player (has both hitting and pitching projections)
                    const isTwoWay = hittingKeys.length > 0 && pitchingKeys.length > 0;

                    projectionsHtml = '<div style="margin-top:20px; background: linear-gradient(145deg, #1a1a2e, #12121f); border: 1px solid #333; border-radius: 12px; padding: 15px;">' +
                        '<div style="color:#60a5fa;font-size:0.9rem;margin-bottom:12px;font-weight:600;display:flex;align-items:center;gap:8px;">' +
                        '<span style="font-size:1.1rem;">📊</span> ' +
                        (data.projections_estimated ? 'Estimated 2026 Projections' : '2026 Projections') +
                        (isTwoWay ? ' <span style="background:#764ba2;padding:2px 8px;border-radius:10px;font-size:0.75rem;">Two-Way</span>' : '') +
                        '</div>';

                    if (isTwoWay) {
                        projectionsHtml += '<div style="color:#4ade80;font-size:0.8rem;margin-bottom:8px;margin-top:10px;">Hitting</div>';
                    }
                    projectionsHtml += '<div class="player-stats">' + hittingItems + '</div>';

                    if (pitchingItems) {
                        projectionsHtml += '<div style="color:#60a5fa;font-size:0.8rem;margin-bottom:8px;margin-top:15px;padding-top:10px;border-top:1px solid #333;">Pitching</div>' +
                            '<div class="player-stats">' + pitchingItems + '</div>';
                    }
                    projectionsHtml += '</div>';
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
                        data.category_contributions.map(c => '<span style="background:#1a1a24;padding:6px 12px;border-radius:20px;font-size:0.8rem;color:#4ade80;">' + c + '</span>').join('') +
                        '</div></div>';
                }

                // Build overall dynasty rank box
                let overallRankHtml = '';
                if (data.overall_rank) {
                    const rankColor = data.overall_rank <= 10 ? '#ffd700' : data.overall_rank <= 25 ? '#00d4ff' : data.overall_rank <= 50 ? '#7b2cbf' : '#4ade80';
                    overallRankHtml = '<div class="stat-box" style="border-color: ' + rankColor + '40;"><div class="label">Dynasty Rank</div><div class="value" style="color: ' + rankColor + ';">#' + data.overall_rank + '</div></div>';
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

                // Calculate tier based on dynasty value
                let tierClass = 'tier-depth';
                let tierLabel = 'Depth';
                const val = parseFloat(data.dynasty_value);
                if (val >= 100) { tierClass = 'tier-superstar'; tierLabel = 'Superstar'; }
                else if (val >= 80) { tierClass = 'tier-elite'; tierLabel = 'Elite'; }
                else if (val >= 60) { tierClass = 'tier-star'; tierLabel = 'Star'; }
                else if (val >= 40) { tierClass = 'tier-solid'; tierLabel = 'Solid'; }

                content.innerHTML = `
                    <div class="player-header">
                        <h2>${data.name}</h2>
                        <div style="color: #888; margin: 10px 0;">${data.position} | ${data.mlb_team || data.team} | ${data.fantasy_team}</div>
                        <div class="dynasty-value">${data.dynasty_value}</div>
                        <div class="tier-badge ${tierClass}">${tierLabel}</div>
                    </div>

                    <div class="player-stats" style="margin-top:20px;">
                        ${overallRankHtml}
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

                    ${projectionsHtml}

                    ${actualStatsHtml}

                    ${fantasyPtsHtml}

                    ${categoryHtml}

                    <div class="trade-advice">
                        <h4>Trade Advice</h4>
                        <p>${data.trade_advice || 'No specific advice available.'}</p>
                    </div>

                    <div style="margin-top:20px; text-align:center;">
                        <button onclick="startComparison('${data.name.replace(/'/g, "\\'")}')"
                            style="padding:12px 24px; background:linear-gradient(135deg, #00d4ff, #0099cc);
                            border:none; border-radius:8px; color:#000; font-weight:bold; cursor:pointer;
                            transition:all 0.2s ease;">
                            Compare Player
                        </button>
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

        function closeComparisonModal() {
            document.getElementById('comparison-modal').classList.remove('active');
            comparisonMode = false;
            comparisonPlayer1 = null;
            comparisonPlayer2 = null;
        }

        async function startComparison(playerName) {
            // Fetch player data
            try {
                const res = await fetch(`${API_BASE}/player/${encodeURIComponent(playerName)}`);
                const data = await res.json();
                if (data.error) return;

                comparisonPlayer1 = data;
                comparisonMode = true;
                closePlayerModal();

                // Show comparison selection modal
                const modal = document.getElementById('comparison-modal');
                const content = document.getElementById('comparison-modal-content');
                content.innerHTML = `
                    <div style="text-align:center; padding:20px;">
                        <h2 style="color:#ffd700; margin-bottom:20px;">Compare ${data.name}</h2>
                        <p style="color:#888; margin-bottom:20px;">Search for a player to compare with ${data.name}</p>
                        <div class="search-container" style="max-width:400px; margin:0 auto;">
                            <input type="text" id="comparisonSearchInput" placeholder="Search player to compare..."
                                onkeyup="searchComparisonPlayers()" autocomplete="off"
                                style="width:100%; padding:12px 15px; background:#1a1a2e; border:1px solid #333;
                                border-radius:8px; color:#fff; font-size:1rem;">
                            <div id="comparison-search-results" class="search-results" style="max-height:300px; overflow-y:auto;"></div>
                        </div>
                        <button onclick="closeComparisonModal()"
                            style="margin-top:20px; padding:10px 20px; background:#333; border:none;
                            border-radius:8px; color:#fff; cursor:pointer;">Cancel</button>
                    </div>
                `;
                modal.classList.add('active');
            } catch (e) {
                console.error('Failed to start comparison:', e);
            }
        }

        let comparisonSearchTimeout = null;
        async function searchComparisonPlayers() {
            const query = document.getElementById('comparisonSearchInput').value.trim();
            const results = document.getElementById('comparison-search-results');

            if (query.length < 2) {
                results.innerHTML = '';
                results.classList.remove('active');
                return;
            }

            if (comparisonSearchTimeout) clearTimeout(comparisonSearchTimeout);
            comparisonSearchTimeout = setTimeout(async () => {
                try {
                    const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}&limit=20`);
                    const data = await res.json();

                    if (!data.results || data.results.length === 0) {
                        results.innerHTML = '<div style="padding:10px; color:#888;">No players found</div>';
                        results.classList.add('active');
                        return;
                    }

                    results.innerHTML = data.results
                        .filter(p => p.name !== comparisonPlayer1.name)
                        .map(p => `
                            <div class="search-result-item" onclick="selectComparisonPlayer('${p.name.replace(/'/g, "\\'")}')">
                                <span>${p.name}</span>
                                <span style="color:#888; font-size:0.85rem;">${p.position} | ${p.value.toFixed(1)}</span>
                            </div>
                        `).join('');
                    results.classList.add('active');
                } catch (e) {
                    console.error('Search error:', e);
                }
            }, 200);
        }

        async function selectComparisonPlayer(playerName) {
            try {
                const res = await fetch(`${API_BASE}/player/${encodeURIComponent(playerName)}`);
                const data = await res.json();
                if (data.error) return;

                comparisonPlayer2 = data;
                showComparisonResult();
            } catch (e) {
                console.error('Failed to load comparison player:', e);
            }
        }

        function showComparisonResult() {
            const p1 = comparisonPlayer1;
            const p2 = comparisonPlayer2;
            const content = document.getElementById('comparison-modal-content');

            // Helper to get tier info
            function getTier(val) {
                if (val >= 100) return { class: 'tier-superstar', label: 'Superstar' };
                if (val >= 80) return { class: 'tier-elite', label: 'Elite' };
                if (val >= 60) return { class: 'tier-star', label: 'Star' };
                if (val >= 40) return { class: 'tier-solid', label: 'Solid' };
                return { class: 'tier-depth', label: 'Depth' };
            }

            const tier1 = getTier(parseFloat(p1.dynasty_value));
            const tier2 = getTier(parseFloat(p2.dynasty_value));

            // Helper to compare stats and add color coding
            function compareVal(v1, v2, higherIsBetter = true) {
                if (v1 === v2 || v1 === null || v2 === null) return ['', ''];
                const better = higherIsBetter ? v1 > v2 : v1 < v2;
                return [better ? 'color:#4ade80;' : 'color:#f87171;', better ? 'color:#f87171;' : 'color:#4ade80;'];
            }

            // Build projection comparison rows
            let projectionRows = '';
            const allProjKeys = new Set([
                ...Object.keys(p1.projections || {}),
                ...Object.keys(p2.projections || {})
            ]);
            allProjKeys.delete('estimated_pitcher');
            allProjKeys.delete('estimated_hitter');

            const lowerIsBetter = ['ERA', 'WHIP', 'BB'];
            allProjKeys.forEach(key => {
                const v1 = p1.projections?.[key];
                const v2 = p2.projections?.[key];
                const isLowerBetter = lowerIsBetter.includes(key);
                const [style1, style2] = compareVal(v1, v2, !isLowerBetter);

                let fmt1 = v1 !== undefined ? (typeof v1 === 'number' ?
                    (['AVG', 'OBP', 'SLG', 'OPS', 'WHIP'].includes(key) ? v1.toFixed(3) :
                    ['ERA', 'K/BB'].includes(key) ? v1.toFixed(2) : Math.round(v1)) : v1) : '-';
                let fmt2 = v2 !== undefined ? (typeof v2 === 'number' ?
                    (['AVG', 'OBP', 'SLG', 'OPS', 'WHIP'].includes(key) ? v2.toFixed(3) :
                    ['ERA', 'K/BB'].includes(key) ? v2.toFixed(2) : Math.round(v2)) : v2) : '-';

                projectionRows += `
                    <tr>
                        <td style="padding:8px 12px; ${style1} font-weight:bold;">${fmt1}</td>
                        <td style="padding:8px 12px; color:#888; text-align:center;">${key}</td>
                        <td style="padding:8px 12px; ${style2} font-weight:bold; text-align:right;">${fmt2}</td>
                    </tr>
                `;
            });

            // Value comparison styling
            const val1 = parseFloat(p1.dynasty_value);
            const val2 = parseFloat(p2.dynasty_value);
            const [valStyle1, valStyle2] = compareVal(val1, val2);

            // Age comparison (lower is better for dynasty)
            const [ageStyle1, ageStyle2] = compareVal(p1.age, p2.age, false);

            content.innerHTML = `
                <h2 style="text-align:center; color:#ffd700; margin-bottom:25px;">Player Comparison</h2>

                <div style="display:grid; grid-template-columns:1fr 1fr; gap:30px;">
                    <!-- Player 1 Header -->
                    <div style="text-align:center; padding:20px; background:linear-gradient(135deg, #1a1a2e, #16213e); border-radius:12px;">
                        <h3 style="margin:0; font-size:1.3rem;">${p1.name}</h3>
                        <div style="color:#888; margin:8px 0;">${p1.position} | ${p1.mlb_team || p1.team}</div>
                        <div style="color:#888; font-size:0.85rem;">${p1.fantasy_team}</div>
                        <div style="font-size:2rem; font-weight:bold; color:#ffd700; margin:15px 0; ${valStyle1}">${p1.dynasty_value}</div>
                        <span class="tier-badge ${tier1.class}">${tier1.label}</span>
                    </div>

                    <!-- Player 2 Header -->
                    <div style="text-align:center; padding:20px; background:linear-gradient(135deg, #1a1a2e, #16213e); border-radius:12px;">
                        <h3 style="margin:0; font-size:1.3rem;">${p2.name}</h3>
                        <div style="color:#888; margin:8px 0;">${p2.position} | ${p2.mlb_team || p2.team}</div>
                        <div style="color:#888; font-size:0.85rem;">${p2.fantasy_team}</div>
                        <div style="font-size:2rem; font-weight:bold; color:#ffd700; margin:15px 0; ${valStyle2}">${p2.dynasty_value}</div>
                        <span class="tier-badge ${tier2.class}">${tier2.label}</span>
                    </div>
                </div>

                <!-- Core Stats Comparison -->
                <div style="margin-top:25px; background:#1a1a24; border-radius:12px; padding:20px;">
                    <h4 style="color:#888; margin:0 0 15px 0; text-align:center;">Core Attributes</h4>
                    <table style="width:100%; border-collapse:collapse;">
                        <tr>
                            <td style="padding:10px; ${ageStyle1} font-weight:bold;">${p1.age}</td>
                            <td style="padding:10px; color:#888; text-align:center;">Age</td>
                            <td style="padding:10px; ${ageStyle2} font-weight:bold; text-align:right;">${p2.age}</td>
                        </tr>
                        <tr>
                            <td style="padding:10px; font-weight:bold;" class="${p1.trajectory === 'Ascending' ? 'ascending' : p1.trajectory === 'Declining' ? 'descending' : ''}">${p1.trajectory}</td>
                            <td style="padding:10px; color:#888; text-align:center;">Trajectory</td>
                            <td style="padding:10px; font-weight:bold; text-align:right;" class="${p2.trajectory === 'Ascending' ? 'ascending' : p2.trajectory === 'Declining' ? 'descending' : ''}">${p2.trajectory}</td>
                        </tr>
                        ${p1.is_prospect || p2.is_prospect ? `
                        <tr>
                            <td style="padding:10px; font-weight:bold; color:#4ade80;">${p1.is_prospect ? '#' + (p1.prospect_rank || 'N/A') : '-'}</td>
                            <td style="padding:10px; color:#888; text-align:center;">Prospect Rank</td>
                            <td style="padding:10px; font-weight:bold; text-align:right; color:#4ade80;">${p2.is_prospect ? '#' + (p2.prospect_rank || 'N/A') : '-'}</td>
                        </tr>
                        ` : ''}
                    </table>
                </div>

                <!-- Projections Comparison -->
                ${projectionRows ? `
                <div style="margin-top:20px; background:#1a1a24; border-radius:12px; padding:20px;">
                    <h4 style="color:#888; margin:0 0 15px 0; text-align:center;">Projections</h4>
                    <table style="width:100%; border-collapse:collapse;">
                        ${projectionRows}
                    </table>
                </div>
                ` : ''}

                <!-- Action Buttons -->
                <div style="margin-top:25px; display:flex; gap:15px; justify-content:center;">
                    <button onclick="showPlayerModal('${p1.name.replace(/'/g, "\\'")}'); closeComparisonModal();"
                        style="padding:12px 24px; background:linear-gradient(135deg, #1a1a2e, #16213e); border:1px solid #333;
                        border-radius:8px; color:#fff; cursor:pointer;">View ${p1.name.split(' ')[0]}</button>
                    <button onclick="showPlayerModal('${p2.name.replace(/'/g, "\\'")}'); closeComparisonModal();"
                        style="padding:12px 24px; background:linear-gradient(135deg, #1a1a2e, #16213e); border:1px solid #333;
                        border-radius:8px; color:#fff; cursor:pointer;">View ${p2.name.split(' ')[0]}</button>
                    <button onclick="closeComparisonModal()"
                        style="padding:12px 24px; background:#333; border:none;
                        border-radius:8px; color:#fff; cursor:pointer;">Close</button>
                </div>
            `;
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

                    results.innerHTML = data.results.map(p => {
                        const val = p.value;
                        let tierClass = 'tier-depth';
                        let tierLabel = 'Depth';
                        if (val >= 100) { tierClass = 'tier-superstar'; tierLabel = 'Superstar'; }
                        else if (val >= 80) { tierClass = 'tier-elite'; tierLabel = 'Elite'; }
                        else if (val >= 60) { tierClass = 'tier-star'; tierLabel = 'Star'; }
                        else if (val >= 40) { tierClass = 'tier-solid'; tierLabel = 'Solid'; }
                        return `
                        <div class="player-card" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <div>
                                    <div style="font-weight:bold;">${p.name}</div>
                                    <div style="color:#888; font-size:0.85rem;">${p.position} | ${p.mlb_team} | ${p.fantasy_team}</div>
                                </div>
                                <div style="text-align:right;">
                                    <div style="display:flex; align-items:center; gap:8px; justify-content:flex-end;">
                                        <span class="tier-badge ${tierClass}" style="font-size:0.55rem; padding:2px 6px;">${tierLabel}</span>
                                        <span style="color:#ffd700; font-size:1.1rem; font-weight:bold;">${val.toFixed(1)}</span>
                                    </div>
                                    <div style="color:#888; font-size:0.8rem;">Age: ${p.age || '?'}</div>
                                </div>
                            </div>
                        </div>
                    `}).join('');
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

            // Get quick filter values
            const filterPosition = document.getElementById('filterPosition').value;
            const filterFitScore = document.getElementById('filterFitScore').value;
            const filterValueDiff = document.getElementById('filterValueDiff').value;

            try {
                let url = `${API_BASE}/suggest?my_team=${encodeURIComponent(myTeam)}&offset=${currentSuggestOffset}&limit=${currentSuggestLimit}`;
                if (targetTeam) url += `&target_team=${encodeURIComponent(targetTeam)}`;
                if (tradeType !== 'any') url += `&trade_type=${encodeURIComponent(tradeType)}`;
                if (filterPosition) url += `&filter_position=${encodeURIComponent(filterPosition)}`;
                if (filterFitScore) url += `&filter_min_fit=${filterFitScore}`;
                if (filterValueDiff) url += `&filter_max_diff=${filterValueDiff}`;
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
                        <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid rgba(0, 212, 255, 0.1);">
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

                    // Calculate value difference and fairness
                    const valueDiff = s.you_receive_value - s.you_send_value;
                    const diffPct = Math.abs(valueDiff) / Math.max(s.you_send_value, s.you_receive_value) * 100;
                    const fairnessLabel = diffPct <= 10 ? 'Fair Trade' : (diffPct <= 20 ? 'Slight Edge' : (valueDiff > 0 ? 'You Win' : 'You Overpay'));
                    const fairnessColor = diffPct <= 10 ? '#4ade80' : (diffPct <= 20 ? '#fbbf24' : (valueDiff > 0 ? '#4ade80' : '#f87171'));

                    // Build expanded details section
                    const expandedDetails = `
                        <div id="expand-${idx}" class="suggestion-expanded" style="display: none; margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1);">
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;">
                                <div style="background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;">
                                    <div style="color: #888; font-size: 0.75rem; margin-bottom: 5px;">VALUE ANALYSIS</div>
                                    <div style="font-size: 0.9rem;">
                                        <span style="color: #f87171;">Send: ${s.you_send_value.toFixed(1)}</span> →
                                        <span style="color: #4ade80;">Get: ${s.you_receive_value.toFixed(1)}</span>
                                    </div>
                                    <div style="color: ${fairnessColor}; font-weight: bold; margin-top: 5px;">${fairnessLabel} (${valueDiff >= 0 ? '+' : ''}${valueDiff.toFixed(1)})</div>
                                </div>
                                <div style="background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;">
                                    <div style="color: #888; font-size: 0.75rem; margin-bottom: 5px;">FIT SCORE BREAKDOWN</div>
                                    <div style="font-size: 0.9rem; color: ${fitColor};">Score: ${s.fit_score?.toFixed(0) || 'N/A'}</div>
                                    <div style="color: #aaa; font-size: 0.8rem; margin-top: 3px;">${fitLabel}</div>
                                </div>
                            </div>
                            ${s.reasoning ? `
                                <div style="background: rgba(255,215,0,0.05); padding: 12px; border-radius: 8px; margin-bottom: 12px; border-left: 3px solid #ffd700;">
                                    <div style="color: #ffd700; font-size: 0.75rem; margin-bottom: 5px;">💡 TRADE REASONING</div>
                                    <div style="color: #ccc; font-size: 0.85rem; line-height: 1.4;">${s.reasoning}</div>
                                </div>
                            ` : ''}
                            ${s.counter_offer ? `
                                <div style="background: rgba(0,212,255,0.05); padding: 12px; border-radius: 8px; margin-bottom: 12px; border-left: 3px solid #00d4ff;">
                                    <div style="color: #00d4ff; font-size: 0.75rem; margin-bottom: 5px;">🔄 IF DECLINED</div>
                                    <div style="color: #aaa; font-size: 0.85rem;">${s.counter_offer}</div>
                                </div>
                            ` : ''}
                            <div style="display: flex; gap: 10px; margin-top: 12px;">
                                <button onclick="event.stopPropagation(); applySuggestion(${idx});" style="flex: 1; background: linear-gradient(135deg, #00d4ff, #0099cc); color: #000; border: none; padding: 10px 16px; border-radius: 8px; cursor: pointer; font-weight: bold;">
                                    📊 Load in Trade Analyzer
                                </button>
                                <button onclick="event.stopPropagation(); copyTradeText(${idx});" style="background: rgba(255,255,255,0.1); color: #ccc; border: 1px solid rgba(255,255,255,0.2); padding: 10px 16px; border-radius: 8px; cursor: pointer;">
                                    📋 Copy
                                </button>
                            </div>
                        </div>
                    `;

                    return `
                    <div class="suggestion-card" onclick="toggleSuggestionExpand(${idx})" style="cursor: pointer;">
                        <div class="suggestion-header">
                            <span>Trade with ${s.other_team}</span>
                            <div style="display:flex;gap:8px;align-items:center;">
                                <span style="background:#1a1a24;padding:4px 10px;border-radius:12px;font-size:0.75rem;">${s.trade_type || '1-for-1'}</span>
                                <span style="background: rgba(255,215,0,0.15); color: ${fitColor}; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: bold;">${fitLabel}</span>
                                <span id="expand-icon-${idx}" style="color: #888; font-size: 0.8rem;">▼</span>
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
                        ${expandedDetails}
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

        function applyQuickFilters() {
            // Reset pagination and reload with filters
            loadSuggestions(false);
        }

        function clearQuickFilters() {
            document.getElementById('filterPosition').value = '';
            document.getElementById('filterFitScore').value = '0';
            document.getElementById('filterValueDiff').value = '100';
            loadSuggestions(false);
        }

        function toggleSuggestionExpand(idx) {
            const expandDiv = document.getElementById(`expand-${idx}`);
            const expandIcon = document.getElementById(`expand-icon-${idx}`);
            if (expandDiv) {
                const isHidden = expandDiv.style.display === 'none';
                expandDiv.style.display = isHidden ? 'block' : 'none';
                if (expandIcon) {
                    expandIcon.textContent = isHidden ? '▲' : '▼';
                }
            }
        }

        function copyTradeText(idx) {
            const s = allCurrentSuggestions[idx];
            if (!s) return;
            const text = `Trade Suggestion:\nSend: ${s.you_send.join(', ')} (${s.you_send_value.toFixed(1)})\nReceive: ${s.you_receive.join(', ')} (${s.you_receive_value.toFixed(1)})\nTrade with: ${s.other_team}`;
            navigator.clipboard.writeText(text).then(() => {
                alert('Trade copied to clipboard!');
            }).catch(err => {
                console.error('Failed to copy:', err);
            });
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
                        <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid rgba(0, 212, 255, 0.1);">
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
                        <div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid rgba(0, 212, 255, 0.1);">
                            <div style="color: #ffd700; font-weight: bold;">Top ${data.suggestions.length} Available Free Agents</div>
                            <div style="color: #888; font-size: 0.85rem; margin-top: 5px;">Select your team above for personalized recommendations based on your needs.</div>
                        </div>
                    `;
                }

                let html = needsHtml + data.suggestions.map(fa => {
                    const fitLabel = fa.fit_score >= 90 ? 'Excellent Fit' : (fa.fit_score >= 75 ? 'Great Fit' : (fa.fit_score >= 60 ? 'Good Fit' : 'Fair'));
                    const fitColor = fa.fit_score >= 90 ? '#4ade80' : (fa.fit_score >= 75 ? '#ffd700' : (fa.fit_score >= 60 ? '#60a5fa' : '#888'));
                    const val = parseFloat(fa.dynasty_value);
                    let tierClass = 'tier-depth'; let tierLabel = 'D';
                    if (val >= 100) { tierClass = 'tier-superstar'; tierLabel = 'S+'; }
                    else if (val >= 80) { tierClass = 'tier-elite'; tierLabel = 'E'; }
                    else if (val >= 60) { tierClass = 'tier-star'; tierLabel = 'S'; }
                    else if (val >= 40) { tierClass = 'tier-solid'; tierLabel = 'B'; }
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
                                <div style="display: flex; align-items: center; gap: 6px; justify-content: flex-end;">
                                    <span class="tier-badge ${tierClass}" style="font-size: 0.5rem; padding: 2px 5px;">${tierLabel}</span>
                                    <div class="value">${fa.dynasty_value}</div>
                                </div>
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

        let cameFromSuggestions = false;
        let lastSuggestionTeam = '';

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

            // Track that we came from suggestions
            cameFromSuggestions = true;
            lastSuggestionTeam = s.my_team;
            document.getElementById('back-to-suggestions').style.display = 'block';

            showPanel('analyze');
            document.querySelector('.tabs .tab').click();
        }

        function goBackToSuggestions() {
            // Hide the back button
            document.getElementById('back-to-suggestions').style.display = 'none';
            cameFromSuggestions = false;

            // Clear the trade analyzer
            tradePlayersA = [];
            tradePlayersB = [];
            tradePicksA = [];
            tradePicksB = [];
            renderTradePlayers('A');
            renderTradePlayers('B');
            document.getElementById('results').innerHTML = '';

            // Go back to suggestions panel
            showPanel('suggest');
            document.querySelectorAll('.tabs .tab')[1].click();  // Click the suggestions tab
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
        async function updateTradeFinderPlayerDropdown() {
            const myTeam = document.getElementById('tradeFinderTeamSelect').value;
            const direction = document.getElementById('tradeFinderDirection').value;
            const targetTeam = document.getElementById('tradeFinderTargetTeam').value;
            const playerSelect = document.getElementById('tradeFinderPlayerSelect');
            const playerLabel = document.getElementById('tradeFinderPlayerLabel');
            const targetLabel = document.getElementById('tradeFinderTargetLabel');

            // Update labels based on direction
            if (direction === 'send') {
                playerLabel.textContent = 'Player to Trade Away';
                targetLabel.textContent = 'Target Team (optional)';
            } else {
                playerLabel.textContent = 'Player to Acquire';
                targetLabel.textContent = 'From Team (required)';
            }

            // Determine which team's players to load
            let teamToLoad = '';
            if (direction === 'send') {
                // Trade Away: load MY team's players
                if (!myTeam) {
                    playerSelect.innerHTML = '<option value="">Select your team first</option>';
                    playerSelect.disabled = true;
                    return;
                }
                teamToLoad = myTeam;
            } else {
                // Acquire: load TARGET team's players
                if (!targetTeam) {
                    playerSelect.innerHTML = '<option value="">Select target team first</option>';
                    playerSelect.disabled = true;
                    return;
                }
                if (!myTeam) {
                    playerSelect.innerHTML = '<option value="">Select your team first</option>';
                    playerSelect.disabled = true;
                    return;
                }
                teamToLoad = targetTeam;
            }

            playerSelect.innerHTML = '<option value="">Loading...</option>';
            playerSelect.disabled = true;

            try {
                const res = await fetch(API_BASE + '/team/' + encodeURIComponent(teamToLoad));
                const data = await res.json();
                const players = (data.players || []).sort((a, b) => b.value - a.value);

                const actionText = direction === 'send' ? 'trade away' : 'acquire';
                playerSelect.innerHTML = '<option value="">Select player to ' + actionText + '...</option>';
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

        let tradeFinderPackages = [];
        let tradeFinderMyTeam = '';

        async function findTradesForPlayer() {
            const myTeam = document.getElementById('tradeFinderTeamSelect').value;
            const playerName = document.getElementById('tradeFinderPlayerSelect').value;
            const direction = document.getElementById('tradeFinderDirection').value;
            const targetTeam = document.getElementById('tradeFinderTargetTeam').value;
            const results = document.getElementById('trade-finder-results');
            tradeFinderMyTeam = myTeam;

            if (!myTeam || !playerName) {
                results.innerHTML = '<p style="color: #f87171;">Please select your team and a player.</p>';
                return;
            }

            if (direction === 'receive' && !targetTeam) {
                results.innerHTML = '<p style="color: #f87171;">Please select the team you want to acquire from.</p>';
                return;
            }

            results.innerHTML = '<div class="loading">Finding trade packages...</div>';

            try {
                let url = API_BASE + '/find-trades-for-player?player_name=' + encodeURIComponent(playerName);
                url += '&my_team=' + encodeURIComponent(myTeam);
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

                // Store packages for loading into analyzer
                tradeFinderPackages = data.packages;

                let html = '<div style="margin-bottom: 15px; color: #ffd700;">';
                html += data.packages.length + ' packages found for ' + playerName + ' (' + data.player_value + ' pts)</div>';
                html += '<div style="display: flex; flex-direction: column; gap: 12px;">';

                data.packages.forEach((pkg, idx) => {
                    const diffColor = Math.abs(pkg.value_diff) <= 5 ? '#4ade80' : (Math.abs(pkg.value_diff) <= 15 ? '#ffd700' : '#f87171');
                    const diffText = pkg.value_diff >= 0 ? '+' + pkg.value_diff.toFixed(1) : pkg.value_diff.toFixed(1);
                    const fitColor = pkg.fit_score >= 75 ? '#4ade80' : (pkg.fit_score >= 50 ? '#ffd700' : '#f87171');

                    html += '<div style="background: linear-gradient(135deg, #0a0a10, #0e0e16); border-radius: 10px; padding: 15px; border: 1px solid rgba(0, 212, 255, 0.1);">';
                    html += '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">';
                    html += '<span style="color: #00d4ff; font-weight: 600;">' + pkg.other_team + '</span>';
                    html += '<div style="display: flex; gap: 8px; align-items: center;">';
                    html += '<span style="background: rgba(255,215,0,0.15); color: ' + fitColor + '; padding: 3px 8px; border-radius: 10px; font-size: 0.75rem;">' + Math.round(pkg.fit_score) + ' fit</span>';
                    html += '<span style="color: ' + diffColor + '; font-weight: 600;">' + diffText + ' pts</span>';
                    html += '</div></div>';
                    html += '<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">';
                    html += '<div style="background: rgba(248,113,113,0.1); padding: 10px; border-radius: 6px;">';
                    html += '<div style="color: #f87171; font-size: 0.8rem; margin-bottom: 5px;">Send (' + pkg.send_total.toFixed(1) + ')</div>';
                    pkg.send.forEach(p => {
                        html += '<div style="color: #e0e0e0; font-size: 0.85rem;">' + p.name + ' - ' + p.value + '</div>';
                    });
                    html += '</div>';
                    html += '<div style="background: rgba(74,222,128,0.1); padding: 10px; border-radius: 6px;">';
                    html += '<div style="color: #4ade80; font-size: 0.8rem; margin-bottom: 5px;">Receive (' + pkg.receive_total.toFixed(1) + ')</div>';
                    pkg.receive.forEach(p => {
                        html += '<div style="color: #e0e0e0; font-size: 0.85rem;">' + p.name + ' - ' + p.value + '</div>';
                    });
                    html += '</div></div>';
                    html += '<button onclick="loadTradeFinderPackage(' + idx + ')" style="margin-top: 12px; width: 100%; background: linear-gradient(135deg, #00d4ff, #0099cc); color: #000; border: none; padding: 10px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 0.9rem;">📊 Load in Trade Analyzer</button>';
                    html += '</div>';
                });

                html += '</div>';
                results.innerHTML = html;
            } catch (e) {
                results.innerHTML = '<p style="color: #f87171;">Error: ' + e.message + '</p>';
            }
        }

        function loadTradeFinderPackage(idx) {
            const pkg = tradeFinderPackages[idx];
            if (!pkg) return;

            // Set teams
            document.getElementById('teamASelect').value = tradeFinderMyTeam;
            document.getElementById('teamBSelect').value = pkg.other_team;

            // Populate players
            tradePlayersA = pkg.send.map(p => ({ name: p.name, team: tradeFinderMyTeam }));
            tradePlayersB = pkg.receive.map(p => ({ name: p.name, team: pkg.other_team }));
            tradePicksA = [];
            tradePicksB = [];

            renderTradePlayers('A');
            renderTradePlayers('B');

            // Update roster dropdowns
            updateTeamA();
            updateTeamB();

            // Show back button and track source
            cameFromSuggestions = true;  // Reuse the same flag
            document.getElementById('back-to-suggestions').style.display = 'block';

            // Switch to analyzer panel
            showPanel('analyze');
            document.querySelector('.tabs .tab').click();
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
        # Use tiered exponential decay formula (realistic dynasty values)
        value = calculate_prospect_value(prospect_rank)

        final_value = round(value, 1)
        print(f"  -> FA PROSPECT TIERED VALUE: {fa.get('name')} rank {prospect_rank} -> value {final_value}")
        return final_value

    # Non-prospect FA value calculation
    value = (base_value * age_mult) + rank_bonus + ros_bonus

    # Fantrax reality check: unrosterable players should be replacement level
    # If Fantrax rank > 1000 AND roster % <= 5%, they're not worth much
    if rank > 1000 and roster_pct <= 5:
        value = min(value, 2.0)
        print(f"  -> UNROSTERABLE FLOOR: {fa.get('name')} rank={rank}, roster_pct={roster_pct} -> capped at 2.0")

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
                ab = int(avg_val(z.get('AB'), s.get('AB')))
                # Skip invalid projections (no AB) - keep hardcoded values if they exist
                if ab < 50:
                    continue
                HITTER_PROJECTIONS[name] = {
                    "AB": ab,
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
    """Load prospect rankings from prospects.json (single source of truth).

    Rankings are pre-merged by update_prospect_rankings.py script.
    This function only loads metadata from CSV files for display purposes.
    """
    import csv
    import glob

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # prospects.json is the single source of truth (already loaded into PROSPECT_RANKINGS)
    # Just load metadata from CSV files for display purposes
    csv_metadata = {}

    file_patterns = [
        'Consensus*Ranks*.csv',
        'Prospects Live*.csv',
        '*Prospect*Ranking*.csv',
        'mlb_pipeline_prospects.csv'
    ]

    prospect_files = []
    for pattern in file_patterns:
        prospect_files.extend(glob.glob(os.path.join(script_dir, pattern)))
    prospect_files = list(set(prospect_files))

    for csv_file in prospect_files:
        try:
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = (row.get('Name') or row.get('Name_FG') or row.get('Player') or '').strip()
                    if not name:
                        continue
                    # Only store metadata for prospects in our rankings
                    if name in PROSPECT_RANKINGS and name not in csv_metadata:
                        age_str = row.get('Age', '')
                        csv_metadata[name] = {
                            'position': row.get('Pos') or row.get('Position') or 'UTIL',
                            'age': int(age_str) if age_str and age_str.isdigit() else 0,
                            'mlb_team': row.get('Team') or row.get('Org') or 'N/A',
                            'level': row.get('Level', 'N/A')
                        }
        except Exception as e:
            print(f"Warning: Could not load metadata from {csv_file}: {e}")

    # Store metadata for all prospects
    PROSPECT_METADATA.clear()
    for name in PROSPECT_RANKINGS:
        if name in csv_metadata:
            PROSPECT_METADATA[name] = csv_metadata[name]
        else:
            PROSPECT_METADATA[name] = {
                'position': 'UTIL',
                'age': 0,
                'mlb_team': 'N/A',
                'level': 'N/A'
            }

    print(f"Loaded {len(PROSPECT_RANKINGS)} prospects from prospects.json")
    print(f"Loaded metadata for {len(csv_metadata)} prospects from CSV files")

    # Debug: Print top 10 prospects
    top_prospects = sorted([(n, r) for n, r in PROSPECT_RANKINGS.items() if r <= 10], key=lambda x: x[1])
    print(f"Top 10 prospects: {[(n, r) for n, r in top_prospects]}")


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
                    throws=PITCHER_HANDEDNESS.get(p['name'], ''),
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
                    throws=PITCHER_HANDEDNESS.get(player_name, ''),
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
                value = calc_player_value(player)
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
            # Use tiered exponential decay formula (realistic dynasty values)
            est_value = calculate_prospect_value(rank)

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


def simulate_trade_impact(team_a_name, team_b_name, players_a, players_b):
    """
    Simulate the impact of a trade on category rankings and championship odds.
    players_a: list of Player objects Team A is sending
    players_b: list of Player objects Team B is sending
    Returns before/after comparison for both teams.
    """
    # Get current rankings and odds
    current_cats, current_rankings = calculate_league_category_rankings()
    current_odds_a = get_team_championship_odds(team_a_name)
    current_odds_b = get_team_championship_odds(team_b_name)

    # Store original rosters
    team_a = teams[team_a_name]
    team_b = teams[team_b_name]
    original_roster_a = list(team_a.players)
    original_roster_b = list(team_b.players)

    # Simulate the trade: remove players from each team, add to the other
    # Team A loses players_a, gains players_b
    # Team B loses players_b, gains players_a
    simulated_roster_a = [p for p in original_roster_a if p not in players_a] + list(players_b)
    simulated_roster_b = [p for p in original_roster_b if p not in players_b] + list(players_a)

    # Temporarily swap rosters
    team_a.players = simulated_roster_a
    team_b.players = simulated_roster_b

    try:
        # Calculate new rankings and odds
        new_cats, new_rankings = calculate_league_category_rankings()
        new_odds_a = get_team_championship_odds(team_a_name)
        new_odds_b = get_team_championship_odds(team_b_name)
    finally:
        # Restore original rosters
        team_a.players = original_roster_a
        team_b.players = original_roster_b

    # Build impact summary for each team
    def build_impact(team_name, old_ranks, new_ranks, old_odds, new_odds):
        changes = []
        for cat in old_ranks.get(team_name, {}):
            old_rank = old_ranks[team_name][cat]
            new_rank = new_ranks[team_name][cat]
            if old_rank != new_rank:
                direction = "up" if new_rank < old_rank else "down"
                # For ERA/WHIP/SO/L, lower rank is better
                is_better = new_rank < old_rank
                changes.append({
                    "category": cat,
                    "before": old_rank,
                    "after": new_rank,
                    "change": old_rank - new_rank,  # positive = improvement
                    "direction": direction,
                    "is_improvement": is_better
                })

        # Sort by magnitude of change
        changes.sort(key=lambda x: abs(x["change"]), reverse=True)

        return {
            "ranking_changes": changes,
            "odds_before": old_odds,
            "odds_after": new_odds,
            "odds_change": round(new_odds - old_odds, 1),
            "total_ranking_improvement": sum(c["change"] for c in changes),
            "categories_improved": len([c for c in changes if c["is_improvement"]]),
            "categories_worsened": len([c for c in changes if not c["is_improvement"]])
        }

    impact_a = build_impact(team_a_name, current_rankings, new_rankings, current_odds_a, new_odds_a)
    impact_b = build_impact(team_b_name, current_rankings, new_rankings, current_odds_b, new_odds_b)

    return {
        "team_a": {
            "name": team_a_name,
            **impact_a
        },
        "team_b": {
            "name": team_b_name,
            **impact_b
        }
    }


@app.route('/team/<team_name>')
def get_team(team_name):
    try:
        if team_name not in teams:
            return jsonify({"error": f"Team '{team_name}' not found", "available_teams": list(teams.keys())}), 404

        team = teams[team_name]
        draft_order, power_rankings, team_totals = get_team_rankings()

        players_with_value = [(p, calc_player_value(p)) for p in team.players]
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
        pos_depth = {'C': [], '1B': [], '2B': [], 'SS': [], '3B': [], 'OF': [], 'UT': [], 'SP': [], 'RP': []}
        for p, v in players_with_value:
            pos = p.position.upper() if p.position else ''
            player_info = {"name": p.name, "value": round(v, 1), "age": p.age}
            matched_any = False
            if 'C' in pos and '1B' not in pos and 'CF' not in pos:
                pos_depth['C'].append(player_info)
                matched_any = True
            if '1B' in pos:
                pos_depth['1B'].append(player_info)
                matched_any = True
            if '2B' in pos:
                pos_depth['2B'].append(player_info)
                matched_any = True
            if 'SS' in pos:
                pos_depth['SS'].append(player_info)
                matched_any = True
            if '3B' in pos:
                pos_depth['3B'].append(player_info)
                matched_any = True
            if 'OF' in pos or 'LF' in pos or 'CF' in pos or 'RF' in pos:
                pos_depth['OF'].append(player_info)
                matched_any = True
            if 'SP' in pos:
                pos_depth['SP'].append(player_info)
                matched_any = True
            if 'RP' in pos or 'CL' in pos:
                pos_depth['RP'].append(player_info)
                matched_any = True
            # UT/DH/UTIL - only add if they didn't match any specific position
            # This prevents Ohtani (UT/SP) from double-counting as a hitter
            if ('UT' in pos or 'DH' in pos or 'UTIL' in pos) and not matched_any:
                pos_depth['UT'].append(player_info)

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
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in get_team for '{team_name}': {error_details}")
        return jsonify({"error": str(e), "team_name": team_name, "traceback": error_details}), 500


@app.route('/best-trade-partners/<team_name>')
def get_best_trade_partners(team_name):
    """Analyze and rank the best trade partners for a team based on complementary needs."""
    if team_name not in teams:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    my_cats, my_pos, my_window = calculate_team_needs(team_name)

    # Window compatibility - who makes a good trade partner
    WINDOW_COMPAT = {
        'rebuilding': ['win-now', 'contender', 'teardown'],
        'win-now': ['rebuilding', 'rising', 'retooling'],
        'contender': ['rebuilding', 'retooling', 'teardown'],
        'rising': ['declining', 'win-now'],
        'declining': ['rising', 'rebuilding'],
        'retooling': ['contender', 'win-now'],
        'teardown': ['contender', 'win-now'],
        'dynasty': ['teardown', 'declining'],
        'competitive': ['any'],
    }

    # Find team weaknesses and strengths
    my_weaknesses = [cat for cat, score in my_cats.items() if score < 0]
    my_strengths = [cat for cat, score in my_cats.items() if score > 0]

    trade_partners = []

    for other_team_name in teams.keys():
        if other_team_name == team_name:
            continue

        their_cats, their_pos, their_window = calculate_team_needs(other_team_name)
        their_weaknesses = [cat for cat, score in their_cats.items() if score < 0]
        their_strengths = [cat for cat, score in their_cats.items() if score > 0]

        # Calculate compatibility score
        score = 50  # Base score
        reasons = []

        # Window compatibility
        compat_windows = WINDOW_COMPAT.get(my_window, [])
        if their_window in compat_windows or 'any' in compat_windows:
            score += 20
            reasons.append(f"✓ Window match ({my_window} ↔ {their_window})")
        elif my_window == their_window:
            score -= 10  # Same window = competing for same assets
            reasons.append(f"⚠ Same window ({their_window})")

        # Category complementarity - they have what I need
        overlap_i_need = set(my_weaknesses) & set(their_strengths)
        if overlap_i_need:
            score += len(overlap_i_need) * 10
            reasons.append(f"✓ They're strong in: {', '.join(overlap_i_need)}")

        # Category complementarity - I have what they need
        overlap_they_need = set(their_weaknesses) & set(my_strengths)
        if overlap_they_need:
            score += len(overlap_they_need) * 8
            reasons.append(f"✓ I can help them in: {', '.join(overlap_they_need)}")

        # Find specific trade targets - players who fill my needs
        other_team = teams[other_team_name]
        target_players = []
        for p in other_team.players:
            value = calc_player_value(p)
            if value < 20:
                continue  # Skip low-value players

            # Check if player helps my weaknesses
            proj = HITTER_PROJECTIONS.get(p.name, {})
            helps = []
            if proj:
                if 'HR' in my_weaknesses and proj.get('HR', 0) >= 20:
                    helps.append(f"HR ({proj.get('HR', 0)})")
                if 'SB' in my_weaknesses and proj.get('SB', 0) >= 15:
                    helps.append(f"SB ({proj.get('SB', 0)})")
                if 'RBI' in my_weaknesses and proj.get('RBI', 0) >= 70:
                    helps.append(f"RBI ({proj.get('RBI', 0)})")
                if 'R' in my_weaknesses and proj.get('R', 0) >= 70:
                    helps.append(f"R ({proj.get('R', 0)})")

            proj = PITCHER_PROJECTIONS.get(p.name, {}) or RELIEVER_PROJECTIONS.get(p.name, {})
            if proj:
                if 'K' in my_weaknesses and proj.get('K', 0) >= 100:
                    helps.append(f"K ({proj.get('K', 0)})")
                if 'SV+HLD' in my_weaknesses and (proj.get('SV', 0) + proj.get('HD', 0)) >= 15:
                    helps.append(f"SV/HLD ({proj.get('SV', 0) + proj.get('HD', 0)})")
                if 'ERA' in my_weaknesses and proj.get('ERA', 5.00) <= 3.50:
                    helps.append(f"ERA ({proj.get('ERA', 0):.2f})")

            if helps:
                target_players.append({
                    'name': p.name,
                    'position': p.position,
                    'value': round(value, 1),
                    'helps': helps
                })

        # Sort targets by value
        target_players.sort(key=lambda x: x['value'], reverse=True)

        trade_partners.append({
            'team': other_team_name,
            'window': their_window,
            'compatibility_score': score,
            'reasons': reasons,
            'their_weaknesses': their_weaknesses,
            'their_strengths': their_strengths,
            'target_players': target_players[:5]  # Top 5 targets
        })

    # Sort by compatibility score
    trade_partners.sort(key=lambda x: x['compatibility_score'], reverse=True)

    return jsonify({
        'team': team_name,
        'my_window': my_window,
        'my_weaknesses': my_weaknesses,
        'my_strengths': my_strengths,
        'trade_partners': trade_partners
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


# ============================================================================
# GM CHAT - AI-Powered Dynasty Advisor
# ============================================================================

def build_gm_chat_context(team_name, client_prefs=None):
    """Build comprehensive context about a team for the GM chat.

    Args:
        team_name: Name of the team
        client_prefs: User preferences from client localStorage (optional)
    """
    if team_name not in teams:
        return None

    if client_prefs is None:
        client_prefs = {}

    team = teams[team_name]
    gm = get_assistant_gm(team_name)
    philosophy = GM_PHILOSOPHIES.get(gm.get('philosophy', 'balanced'), GM_PHILOSOPHIES['balanced'])

    # Get player values
    players_with_value = [(p, calc_player_value(p)) for p in team.players]
    players_with_value.sort(key=lambda x: x[1], reverse=True)

    # Get rankings
    _, power_rankings, _ = get_team_rankings()
    power_rank = power_rankings.get(team_name, 0)
    team_cats, cat_rankings = calculate_league_category_rankings()
    my_ranks = cat_rankings.get(team_name, {})

    # Championship odds
    champ_odds = get_team_championship_odds(team_name)

    # Build roster summary
    top_players = [(p.name, round(v, 1), p.age, p.position) for p, v in players_with_value[:15]]
    prospects = [(p.name, p.prospect_rank, round(calc_player_value(p), 1))
                 for p in team.players if p.is_prospect and p.prospect_rank and p.prospect_rank <= 100]
    prospects.sort(key=lambda x: x[1])

    # Build position-specific breakdowns for clarity (include handedness for pitchers)
    starters = [(p.name, round(v, 1), p.age, p.throws or '?') for p, v in players_with_value if 'SP' in p.position][:8]
    relievers = [(p.name, round(v, 1), p.age, p.throws or '?') for p, v in players_with_value if 'RP' in p.position and 'SP' not in p.position][:5]
    hitters = [(p.name, round(v, 1), p.age, p.position) for p, v in players_with_value if p.position not in ['SP', 'RP', 'SP,RP', 'RP,SP']][:10]

    # Full roster list for "already on team" check
    all_roster_names = [p.name for p in team.players]

    # Category analysis with clear hitting/pitching labels
    hitting_cats = {'HR': 'HR (hitting)', 'SB': 'SB (hitting)', 'RBI': 'RBI (hitting)', 'R': 'Runs (hitting)',
                    'SO': 'Strikeouts (hitting - lower is better)', 'AVG': 'AVG (hitting)', 'OPS': 'OPS (hitting)'}
    pitching_cats = {'K': 'K (pitching)', 'SV+HLD': 'SV+HLD (pitching)', 'ERA': 'ERA (pitching)',
                     'WHIP': 'WHIP (pitching)', 'QS': 'QS (pitching)', 'L': 'Losses (pitching)', 'K/BB': 'K/BB (pitching)'}

    def label_cat(cat):
        return hitting_cats.get(cat, pitching_cats.get(cat, cat))

    strengths = [f"{label_cat(cat)} (#{rank})" for cat, rank in my_ranks.items() if rank <= 3]
    weaknesses = [f"{label_cat(cat)} (#{rank})" for cat, rank in my_ranks.items() if rank >= 9]

    # Age breakdown
    ages = [p.age for p in team.players if p.age > 0]
    avg_age = sum(ages) / len(ages) if ages else 0
    young_count = len([a for a in ages if a <= 25])
    prime_count = len([a for a in ages if 26 <= a <= 30])
    vet_count = len([a for a in ages if a > 30])

    # Total value
    total_value = sum(v for _, v in players_with_value)

    # Identify tradeable assets (players ranked 5-15 who could be moved)
    tradeable_assets = [(p.name, round(v, 1), p.position) for p, v in players_with_value[4:15] if v >= 25]
    max_tradeable_value = sum(v for _, v, _ in tradeable_assets[:3])  # Best 3 tradeable pieces combined

    # Draft pick
    draft_pick = draft_order_config.get(team_name, 0)

    # Build list of notable players from OTHER teams for trade reference
    # Split into realistic targets (40-80) and superstars (80+)
    realistic_targets = []
    superstar_players = []
    for other_team_name, other_team in teams.items():
        if other_team_name != team_name:
            for p in other_team.players:
                val = calc_player_value(p)
                if val >= 40:
                    mlb_abbrev = p.mlb_team[:3].upper() if p.mlb_team else p.team[:3].upper() if p.team else "???"
                    player_tuple = (p.name, round(val, 1), p.age, p.position, other_team_name, mlb_abbrev)
                    if val >= 80:
                        superstar_players.append(player_tuple)
                    else:
                        realistic_targets.append(player_tuple)
    realistic_targets.sort(key=lambda x: x[1], reverse=True)
    superstar_players.sort(key=lambda x: x[1], reverse=True)

    # Determine category needs (weaknesses ranked 8+ are priorities)
    category_needs = []
    for cat, rank in sorted(my_ranks.items(), key=lambda x: -x[1]):
        if rank >= 8:
            category_needs.append(f"{cat} (#{rank})")
    category_needs_str = ', '.join(category_needs[:4]) if category_needs else 'No critical needs'

    # Trade initiation style descriptions
    initiation_descriptions = {
        'aggressive': 'ACTIVELY pursue trades - reach out to other teams, make offers, be persistent',
        'reactive': 'WAIT for offers - play hard to get, let others come to you, be selective',
        'opportunistic': 'WATCH for value - monitor the market, strike when you see undervalued players'
    }
    trade_initiation = philosophy.get('trade_initiation_style', 'opportunistic')
    min_value = philosophy.get('min_value_threshold', 40)

    # Build context string
    context = f"""You are the AI Assistant GM for {team_name} in a dynasty fantasy baseball league.

YOUR GM PERSONALITY:
- Name: {gm['name']}
- Title: {gm['title']}
- Philosophy: {gm['philosophy']}
- Personality: {gm['personality']}
- Trade Style: {gm['trade_style']}
- Risk Tolerance: {gm['risk_tolerance']}
- Priorities: {', '.join(gm['priorities'])}

YOUR TRADE APPROACH:
- Minimum Value Threshold: {min_value} (only discuss players worth {min_value}+ points)
- Trade Initiation Style: {trade_initiation.upper()} - {initiation_descriptions.get(trade_initiation, '')}
- Category Needs (PRIORITY TARGETS): {category_needs_str}

TEAM OVERVIEW:
- Power Rank: #{power_rank} of {len(teams)} teams
- Championship Odds: {champ_odds}%
- Total Roster Value: {total_value:.0f} points
- Draft Pick: #{draft_pick}

ROSTER (Top 15 by value):
{chr(10).join([f"  {i+1}. {name} - Value: {val}, Age: {age}, Pos: {pos}" for i, (name, val, age, pos) in enumerate(top_players)])}

STARTING PITCHERS (SP) - These are ALL STARTERS, not relievers:
{chr(10).join([f"  {'★ ACE: ' if i == 0 else ''}{name} ({throws}HP) - Value: {val}, Age: {age} [STARTER]" for i, (name, val, age, throws) in enumerate(starters)]) if starters else "  None"}
NOTE: Every pitcher listed above is a STARTING PITCHER on this fantasy team regardless of their real-life history.
L = Left-handed pitcher, R = Right-handed pitcher, ? = Unknown

RELIEF PITCHERS (RP) - These are the ONLY relievers on the team:
{chr(10).join([f"  {name} ({throws}HP) - Value: {val}, Age: {age} [RELIEVER]" for name, val, age, throws in relievers]) if relievers else "  None"}
NOTE: If a pitcher is NOT listed here, they are NOT a reliever on this team.

TOP HITTERS - sorted by value:
{chr(10).join([f"  {name} - Value: {val}, Age: {age}, Pos: {pos}" for name, val, age, pos in hitters]) if hitters else "  None"}

PROSPECTS ON ROSTER (Top 100):
{chr(10).join([f"  #{rank} {name} (Value: {val})" for name, rank, val in prospects[:8]]) if prospects else "  None"}

TRADEABLE ASSETS (players ranked 5-15, available to move in trades):
{chr(10).join([f"  {name} - Value: {val}, {pos}" for name, val, pos in tradeable_assets]) if tradeable_assets else "  Limited trade chips available"}
TOTAL VALUE OF TOP 3 TRADEABLE PIECES: ~{max_tradeable_value:.0f} points
(This is roughly the MAX value you can offer without trading core players)

FULL ROSTER - ALL PLAYERS ON THIS TEAM (do NOT suggest trading FOR any of these - we already have them!):
{', '.join(all_roster_names)}

CATEGORY RANKINGS (out of {len(teams)} teams):
HITTING CATEGORIES:
- HR: #{my_ranks.get('HR', 'N/A')} | RBI: #{my_ranks.get('RBI', 'N/A')} | Runs: #{my_ranks.get('R', 'N/A')}
- SB: #{my_ranks.get('SB', 'N/A')} | AVG: #{my_ranks.get('AVG', 'N/A')} | OPS: #{my_ranks.get('OPS', 'N/A')}
- Hitter Strikeouts (SO): #{my_ranks.get('SO', 'N/A')} (lower rank = fewer strikeouts = BETTER)

PITCHING CATEGORIES:
- Pitcher K: #{my_ranks.get('K', 'N/A')} | QS: #{my_ranks.get('QS', 'N/A')} | SV+HLD: #{my_ranks.get('SV+HLD', 'N/A')}
- ERA: #{my_ranks.get('ERA', 'N/A')} | WHIP: #{my_ranks.get('WHIP', 'N/A')} | K/BB: #{my_ranks.get('K/BB', 'N/A')}
- Losses: #{my_ranks.get('L', 'N/A')} (lower rank = fewer losses = BETTER)

CATEGORY STRENGTHS: {', '.join(strengths) if strengths else 'None'}
CATEGORY WEAKNESSES: {', '.join(weaknesses) if weaknesses else 'None'}

AGE BREAKDOWN:
- Young (≤25): {young_count} players
- Prime (26-30): {prime_count} players
- Veterans (31+): {vet_count} players
- Average Age: {avg_age:.1f}

LEAGUE CONTEXT:
- 12-team dynasty league
- H2H categories format
- All {len(teams)} teams competing

REALISTIC TRADE TARGETS (Value 40-80, actually acquirable):
{chr(10).join([f"  {name}, {pos} - {fantasy_tm} ({mlb}) - Value: {val}, Age: {age}" for name, val, age, pos, fantasy_tm, mlb in realistic_targets[:25]])}

SUPERSTARS (Value 80+, virtually UNTOUCHABLE - do NOT suggest as "realistic" targets):
{chr(10).join([f"  {name}, {pos} - {fantasy_tm} ({mlb}) - Value: {val}" for name, val, age, pos, fantasy_tm, mlb in superstar_players[:10]])}
(These players would cost your ENTIRE core - only mention if user specifically asks about them)

INSTRUCTIONS:
- You ARE the GM speaking directly to the team owner (the user) - give advice in first person
- DO NOT refer to yourself in third person (don't say "The Shark thinks..." - say "I think...")
- DO NOT say things like "I'll call you later" - this is a live chat, answer fully now
- Give specific, actionable advice based on the team's actual roster and needs
- Reference specific players by name when relevant
- Consider the team's championship window and contention status
- Keep responses concise but insightful (2-4 paragraphs max)
- Be honest about weaknesses while staying encouraging
- Speak with your personality flavor but stay helpful and direct
- CRITICAL: Use ONLY the roster data provided above. Do NOT use outside knowledge about players.
  * If a player is listed under "STARTING PITCHERS (SP)" they are a STARTER on this fantasy team
  * If a player is listed under "RELIEF PITCHERS (RP)" they are a RELIEVER on this fantasy team
  * Do NOT assume a player is a reliever just because they may have been one in real life - use the data above
  * Pitcher handedness (LHP/RHP) is provided in the roster data - use it when relevant to analysis
  * Do NOT describe players as "contact hitters", "power bats", "ground ball pitchers" etc. unless the stats clearly show it
  * NEVER suggest trading FOR a player who is ALREADY ON THIS TEAM'S ROSTER - check the roster list above first!
  * Only suggest trade targets from the "REALISTIC TRADE TARGETS" list above - these are players on OTHER teams
  * If a player is in our ROSTER section, they are OURS - don't suggest acquiring them

TRADE VALUE MATH (YOU MUST FOLLOW THIS EXACTLY):

STEP 1 - Calculate the RATIO before suggesting ANY trade:
  RATIO = (Sum of ALL player values you GIVE) ÷ (Sum of ALL player values you GET)

STEP 2 - Check if ratio is between 0.85 and 1.15:
  - If ratio > 1.15 = YOU ARE OVERPAYING = DO NOT SUGGEST THIS TRADE
  - If ratio < 0.85 = YOU ARE UNDERPAYING = Other team won't accept
  - If ratio is 0.85 to 1.15 = FAIR TRADE = OK to suggest

EXAMPLE CALCULATIONS (study these carefully):

WRONG - 3-for-1 for an 80-value player:
  You give: Player A (92) + Player B (83) + Player C (51) = 226 TOTAL
  You get: Player D (80) = 80 TOTAL
  RATIO = 226 ÷ 80 = 2.83 = MASSIVE OVERPAY = NEVER SUGGEST THIS!

WRONG - 3-for-1 for an 80-value player:
  You give: Player A (92) + Player B (74) + Player C (49) = 215 TOTAL
  You get: Player D (80) = 80 TOTAL
  RATIO = 215 ÷ 80 = 2.69 = MASSIVE OVERPAY = NEVER SUGGEST THIS!

RIGHT - 1-for-1 for an 80-value player:
  You give: Player A (85) = 85 TOTAL
  You get: Player B (80) = 80 TOTAL
  RATIO = 85 ÷ 80 = 1.06 = FAIR = OK TO SUGGEST

RIGHT - 2-for-1 for an 80-value player:
  You give: Player A (45) + Player B (40) = 85 TOTAL
  You get: Player C (80) = 80 TOTAL
  RATIO = 85 ÷ 80 = 1.06 = FAIR = OK TO SUGGEST

FOR A ~80 VALUE TARGET, FAIR OFFERS ARE:
  - One player worth 68-92, OR
  - Two players totaling 68-92 (like 45+40=85, or 50+35=85)
  - NOT three players totaling 200+ (that's 2.5x overpay!)

CRITICAL RULES:
- Value tiers (CALIBRATED to industry consensus - FHQ, HKB, Steamer, ZiPS, etc.):
  * 100+ = Superstar (top 5 overall dynasty assets)
  * 80-99 = Elite (consensus top 6-15)
  * 60-79 = Star (consensus top 16-35)
  * 40-59 = Solid (consensus top 36-75)
  * <40 = Depth/Role player
- PROSPECT VALUES are discounted for bust risk: #1 prospect ≈ 72, #10 prospect ≈ 56, #25 prospect ≈ 42
- 3-for-1 trades are ONLY valid when acquiring a 120+ superstar (Skenes, De La Cruz tier)
- For players valued 75-100, suggest 1-for-1 or 2-for-1 trades with SIMILAR total value
- If you cannot construct a fair offer, SAY SO: "We'd need to overpay significantly to get this player"
- ALWAYS show your math: "Player A (45) + Player B (40) = 85 total for Player C (80) = ratio 1.06 = fair"

NEVER TRADE DOWN IN VALUE:
- DO NOT suggest trading a higher-value player for a lower-value player in a 1-for-1
- WRONG: Trading Sanchez (92) for Crow-Armstrong (80) = We LOSE 12 points of value!
- If the target is worth 80, offer a player worth 75-85, NOT a player worth 92+
- The goal is to ACQUIRE value or trade laterally, NOT to give away value
- Only overpay slightly (up to 1.15x) if there's a compelling strategic reason (age, position need)

USE TRADEABLE ASSETS, NOT CORE PLAYERS:
- Your CORE = Top 4 players by value - do NOT suggest trading these unless user specifically asks
- Your TRADEABLE ASSETS = Players ranked 5-15 by value - USE THESE to construct offers
- Look at the "TRADEABLE ASSETS" section of your roster data for pieces to offer
- Example: If target is worth 75, look for tradeable assets worth 65-85 to offer
- You can combine 2 tradeable assets (like 45+35=80) to match an 80-value target

REALISTIC TRADE TARGET GUIDELINES (CRITICAL):
- "Realistic targets" = players you can acquire using your TRADEABLE ASSETS (not core)
- If your best tradeable asset is worth 60, your realistic targets are players worth 50-70
- Players valued 90+ are virtually UNTOUCHABLE - don't suggest them as realistic targets
- Focus on players whose value MATCHES your available tradeable pieces
- If asked for trade targets, suggest players that fill team NEEDS and match tradeable asset values
- NEVER suggest trading your core (top 4) unless specifically asked

ALWAYS SHOW YOUR MATH WHEN SUGGESTING TRADES:
- Format: "Player A (52) + Player B (35) = 87 total → for Player C (80) = ratio 87÷80 = 1.09 = FAIR"
- STOP AND VERIFY: Before writing the trade, calculate the ratio yourself
- If your GIVE total is more than 1.15x the GET total, DO NOT suggest it
- Example: Giving 200+ for an 80-value player = ratio 2.5+ = NEVER SUGGEST
- If you can't construct a fair deal, tell the user: "A fair offer for this player would be 68-92 in value - we'd need to find pieces in that range"

TRADE APPROACH GUIDELINES (based on your personality):
- Your minimum value threshold is {min_value} - don't waste time discussing players below this value
- Your trade initiation style is {trade_initiation.upper()}:
  * If AGGRESSIVE: Proactively suggest reaching out to other teams, name specific trade partners, push to make deals happen
  * If REACTIVE: Be more measured, focus on evaluating offers that come in, recommend patience and letting the market come to you
  * If OPPORTUNISTIC: Watch for buy-low opportunities, suggest monitoring injured players or struggling teams, strike when value appears
- PRIORITIZE CATEGORY NEEDS: When suggesting trades, favor players who help the team's weak categories ({category_needs_str})

- IMPORTANT: If the user has learned preferences, use them to personalize your advice!
{build_client_preferences_context(client_prefs)}
"""
    return context


def build_client_preferences_context(prefs):
    """Build preferences context from client-provided preferences."""
    if not prefs:
        return ""

    context_parts = []

    if prefs.get('trade_style'):
        context_parts.append(f"- User prefers a {prefs['trade_style']} trade approach")

    if prefs.get('priority_positions'):
        context_parts.append(f"- Priority positions to target: {', '.join(prefs['priority_positions'])}")

    if prefs.get('priority_categories'):
        context_parts.append(f"- Category priorities: {', '.join(prefs['priority_categories'])}")

    if prefs.get('target_players'):
        context_parts.append(f"- Players they want to acquire: {', '.join(prefs['target_players'][:5])}")

    if prefs.get('avoid_players'):
        context_parts.append(f"- Players to avoid/not trade for: {', '.join(prefs['avoid_players'][:5])}")

    if context_parts:
        return "\nLEARNED USER PREFERENCES (from previous conversations):\n" + "\n".join(context_parts) + "\nUse these preferences to personalize your advice!"

    return ""


def validate_trade_in_response(response_text, my_team_name):
    """
    Parse GM response for trade suggestions and validate the math.
    Returns validation warnings if trades are unbalanced.
    """
    import re
    warnings = []

    # Common patterns for trade mentions
    # Look for "trade X for Y", "send X to get Y", "give up X for Y"
    trade_patterns = [
        r'trade\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:for|to get)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        r'send\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:for|to get)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        r'give\s+(?:up\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:for|to acquire)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
    ]

    # Build player value lookup from all teams
    player_values = {}
    for team in teams.values():
        for p in team.players:
            player_values[p.name.lower()] = calc_player_value(p)

    for pattern in trade_patterns:
        matches = re.findall(pattern, response_text, re.IGNORECASE)
        for match in matches:
            send_name, receive_name = match
            send_val = player_values.get(send_name.lower(), 0)
            receive_val = player_values.get(receive_name.lower(), 0)

            if send_val > 0 and receive_val > 0:
                ratio = send_val / receive_val if receive_val > 0 else 999
                if ratio > 1.25:
                    warnings.append(f"⚠️ Trade check: {send_name} ({send_val:.0f}) for {receive_name} ({receive_val:.0f}) - You'd be overpaying by {((ratio-1)*100):.0f}%")
                elif ratio < 0.75:
                    warnings.append(f"💡 Trade check: {send_name} ({send_val:.0f}) for {receive_name} ({receive_val:.0f}) - Great value for you! ({((1-ratio)*100):.0f}% discount)")

    return warnings


@app.route('/gm-chat/<team_name>', methods=['POST'])
def gm_chat(team_name):
    """Chat with the AI GM for a specific team."""
    if not GM_CHAT_ENABLED:
        return jsonify({
            "error": "GM Chat is not enabled. Please add ANTHROPIC_API_KEY to your .env file."
        }), 503

    if team_name not in teams:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    data = request.get_json()
    user_message = data.get('message', '').strip()
    client_history = data.get('history', [])  # Chat history from client localStorage
    client_prefs = data.get('preferences', {})  # Preferences from client localStorage

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # Build team context with client-provided preferences
    context = build_gm_chat_context(team_name, client_prefs)
    if not context:
        return jsonify({"error": "Could not build team context"}), 500

    try:
        # Build messages for the API from client-provided history
        messages = []
        for msg in client_history[-10:]:  # Last 10 messages from client
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })

        # Add current user message
        messages.append({
            "role": "user",
            "content": user_message
        })

        # Call Claude API
        response = ANTHROPIC_CLIENT.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=context,
            messages=messages
        )

        assistant_message = response.content[0].text

        # POST-VALIDATION: Check any trade suggestions for value imbalance
        trade_warnings = validate_trade_in_response(assistant_message, team_name)

        # Chat history and preferences are now stored client-side in localStorage
        # No server-side storage needed

        return jsonify({
            "response": assistant_message,
            "team": team_name,
            "model": "claude-sonnet-4",
            "trade_warnings": trade_warnings  # New: validation warnings
        })

    except Exception as e:
        print(f"GM Chat error: {e}")
        return jsonify({"error": f"Chat error: {str(e)}"}), 500


@app.route('/gm-chat-status')
def gm_chat_status():
    """Check if GM Chat is enabled."""
    return jsonify({
        "enabled": GM_CHAT_ENABLED,
        "model": "claude-sonnet-4" if GM_CHAT_ENABLED else None
    })


@app.route('/gm-chat-history/<team_name>')
def get_chat_history(team_name):
    """Get chat history for a team."""
    if team_name not in teams:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    history = get_team_chat_history(team_name, limit=50)
    prefs = get_team_preferences(team_name)

    return jsonify({
        "team": team_name,
        "messages": history.get("messages", []),
        "preferences": prefs,
        "conversation_count": prefs.get("conversation_count", 0)
    })


@app.route('/gm-chat-history/<team_name>/clear', methods=['POST'])
def clear_chat_history(team_name):
    """Clear chat history for a team."""
    if team_name not in teams:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    history = load_chat_history()
    if team_name in history:
        history[team_name] = {"messages": [], "preferences": {}}
        save_chat_history(history)

    return jsonify({"success": True, "message": f"Chat history cleared for {team_name}"})


@app.route('/gm-preferences/<team_name>', methods=['GET', 'POST'])
def manage_preferences(team_name):
    """Get or update learned preferences for a team."""
    if team_name not in teams:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    if request.method == 'GET':
        prefs = get_team_preferences(team_name)
        return jsonify({"team": team_name, "preferences": prefs})

    elif request.method == 'POST':
        data = request.get_json()
        updates = {}

        # Allow updating specific preference fields
        allowed_fields = ["trade_style", "risk_tolerance", "category_focus",
                          "position_needs", "target_players", "players_to_move", "notes"]
        for field in allowed_fields:
            if field in data:
                updates[field] = data[field]

        if updates:
            updated_prefs = update_team_preferences(team_name, updates)
            return jsonify({"success": True, "preferences": updated_prefs})
        else:
            return jsonify({"error": "No valid fields to update"}), 400


@app.route('/gm-preferences/<team_name>/reset', methods=['POST'])
def reset_preferences(team_name):
    """Reset learned preferences for a team."""
    if team_name not in teams:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    prefs = load_user_preferences()
    if team_name in prefs:
        del prefs[team_name]
        save_user_preferences(prefs)

    return jsonify({"success": True, "message": f"Preferences reset for {team_name}"})


@app.route('/find-trades-for-player')
def find_trades_for_player():
    """Enhanced Trade Finder with multi-player packages, category filtering, and window compatibility."""
    player_name = request.args.get('player_name', '')
    my_team_name = request.args.get('my_team', '')
    direction = request.args.get('direction', 'send')
    target_team_name = request.args.get('target_team', '')
    limit = int(request.args.get('limit', 30))
    category_filter = request.args.get('category', '')  # Filter by category need (HR, SB, K, etc.)
    include_packages = request.args.get('packages', 'true').lower() == 'true'  # Include 2-for-1, 2-for-2

    if not player_name or not my_team_name:
        return jsonify({"error": "Missing player_name or my_team"}), 400

    if my_team_name not in teams:
        return jsonify({"error": f"Team '{my_team_name}' not found"}), 404

    my_team = teams[my_team_name]
    packages = []

    # Get team windows and needs for enhanced scoring
    my_cats, my_pos, my_window = calculate_team_needs(my_team_name)

    # Window compatibility matrix (higher = better trade partner)
    WINDOW_COMPAT = {
        ('rebuilding', 'win-now'): 15, ('win-now', 'rebuilding'): 15,
        ('rebuilding', 'contender'): 12, ('contender', 'rebuilding'): 12,
        ('teardown', 'win-now'): 15, ('win-now', 'teardown'): 15,
        ('teardown', 'contender'): 12, ('contender', 'teardown'): 12,
        ('rising', 'declining'): 10, ('declining', 'rising'): 10,
        ('retooling', 'contender'): 8, ('contender', 'retooling'): 8,
    }

    def score_package(my_send, their_receive, other_team_name, their_window):
        """Score a trade package considering value, categories, and windows."""
        send_total = sum(s['value'] for s in my_send)
        receive_total = sum(r['value'] for r in their_receive)
        value_diff = receive_total - send_total

        # Base score from value fairness (±25 tolerance for packages)
        base_score = 100 - abs(value_diff) * 2

        # Window compatibility bonus
        window_key = (my_window, their_window)
        window_bonus = WINDOW_COMPAT.get(window_key, 0)
        base_score += window_bonus

        # Category fit bonus - check if we're gaining in weak categories
        cat_bonus = 0
        cat_reasons = []
        for r in their_receive:
            proj = HITTER_PROJECTIONS.get(r['name'], {})
            if proj:
                if category_filter == 'HR' or (my_cats.get('HR', 0) < 0 and proj.get('HR', 0) >= 20):
                    cat_bonus += 8
                    cat_reasons.append(f"+HR ({proj.get('HR', 0)})")
                if category_filter == 'SB' or (my_cats.get('SB', 0) < 0 and proj.get('SB', 0) >= 15):
                    cat_bonus += 8
                    cat_reasons.append(f"+SB ({proj.get('SB', 0)})")
            proj = PITCHER_PROJECTIONS.get(r['name'], {}) or RELIEVER_PROJECTIONS.get(r['name'], {})
            if proj:
                if category_filter == 'K' or (my_cats.get('K', 0) < 0 and proj.get('K', 0) >= 100):
                    cat_bonus += 8
                    cat_reasons.append(f"+K ({proj.get('K', 0)})")
                if category_filter == 'SV' or category_filter == 'SV+HLD':
                    sv_hld = proj.get('SV', 0) + proj.get('HD', 0)
                    if my_cats.get('SV+HLD', 0) < 0 and sv_hld >= 10:
                        cat_bonus += 8
                        cat_reasons.append(f"+SV/HLD ({sv_hld})")

        # Category filter: if specified but not met, penalize
        if category_filter and not cat_reasons:
            base_score -= 20

        return base_score + cat_bonus, cat_reasons, window_bonus

    if direction == 'send':
        # TRADE AWAY: I'm trading away one of MY players
        player = next((p for p in my_team.players if p.name == player_name), None)
        if not player:
            return jsonify({"error": f"Player '{player_name}' not found on your team"}), 404

        player_value = calc_player_value(player)
        my_other_players = [(p, calc_player_value(p)) for p in my_team.players if p.name != player_name and calc_player_value(p) >= 10]
        my_other_players.sort(key=lambda x: x[1], reverse=True)

        other_teams = [t for t in teams.keys() if t != my_team_name]
        if target_team_name and target_team_name in other_teams:
            other_teams = [target_team_name]

        for other_team_name in other_teams:
            other_team = teams[other_team_name]
            _, _, their_window = calculate_team_needs(other_team_name)
            other_players = [(p, calc_player_value(p)) for p in other_team.players]
            other_players.sort(key=lambda x: x[1], reverse=True)

            # 1-for-1 trades
            for op, ov in other_players[:20]:
                value_diff = ov - player_value
                if -25 <= value_diff <= 25:
                    send_list = [{'name': player.name, 'position': player.position, 'value': round(player_value, 1)}]
                    receive_list = [{'name': op.name, 'position': op.position, 'value': round(ov, 1)}]
                    fit_score, cat_reasons, window_bonus = score_package(send_list, receive_list, other_team_name, their_window)
                    packages.append({
                        'other_team': other_team_name,
                        'trade_type': '1-for-1',
                        'send': send_list,
                        'receive': receive_list,
                        'send_total': round(player_value, 1),
                        'receive_total': round(ov, 1),
                        'value_diff': round(value_diff, 1),
                        'fit_score': round(fit_score, 1),
                        'window_match': their_window,
                        'window_bonus': window_bonus,
                        'category_fit': cat_reasons
                    })

            # 1-for-2 trades (give 1, get 2)
            if include_packages:
                for i, (op1, ov1) in enumerate(other_players[:12]):
                    for op2, ov2 in other_players[i+1:15]:
                        combined_receive = ov1 + ov2
                        value_diff = combined_receive - player_value
                        if -20 <= value_diff <= 30 and ov1 <= player_value * 0.85:  # Getting 2 lesser for 1 star
                            send_list = [{'name': player.name, 'position': player.position, 'value': round(player_value, 1)}]
                            receive_list = [
                                {'name': op1.name, 'position': op1.position, 'value': round(ov1, 1)},
                                {'name': op2.name, 'position': op2.position, 'value': round(ov2, 1)}
                            ]
                            fit_score, cat_reasons, window_bonus = score_package(send_list, receive_list, other_team_name, their_window)
                            packages.append({
                                'other_team': other_team_name,
                                'trade_type': '1-for-2',
                                'send': send_list,
                                'receive': receive_list,
                                'send_total': round(player_value, 1),
                                'receive_total': round(combined_receive, 1),
                                'value_diff': round(value_diff, 1),
                                'fit_score': round(fit_score - 5, 1),  # Slight penalty for complexity
                                'window_match': their_window,
                                'window_bonus': window_bonus,
                                'category_fit': cat_reasons
                            })

    else:
        # ACQUIRE: I want to acquire a player from ANOTHER team
        if not target_team_name:
            return jsonify({"error": "Target team is required for acquire direction"}), 400

        if target_team_name not in teams:
            return jsonify({"error": f"Target team '{target_team_name}' not found"}), 404

        target_team = teams[target_team_name]
        _, _, their_window = calculate_team_needs(target_team_name)

        player = next((p for p in target_team.players if p.name == player_name), None)
        if not player:
            return jsonify({"error": f"Player '{player_name}' not found on {target_team_name}"}), 404

        player_value = calc_player_value(player)
        my_players = [(p, calc_player_value(p)) for p in my_team.players if calc_player_value(p) >= 10]
        my_players.sort(key=lambda x: x[1], reverse=True)

        # 1-for-1 trades
        for mp, mv in my_players[:20]:
            value_diff = player_value - mv
            if -25 <= value_diff <= 25:
                send_list = [{'name': mp.name, 'position': mp.position, 'value': round(mv, 1)}]
                receive_list = [{'name': player.name, 'position': player.position, 'value': round(player_value, 1)}]
                fit_score, cat_reasons, window_bonus = score_package(send_list, receive_list, target_team_name, their_window)
                packages.append({
                    'other_team': target_team_name,
                    'trade_type': '1-for-1',
                    'send': send_list,
                    'receive': receive_list,
                    'send_total': round(mv, 1),
                    'receive_total': round(player_value, 1),
                    'value_diff': round(value_diff, 1),
                    'fit_score': round(fit_score, 1),
                    'window_match': their_window,
                    'window_bonus': window_bonus,
                    'category_fit': cat_reasons
                })

        # 2-for-1 trades (give 2, get 1)
        if include_packages:
            for i, (mp1, mv1) in enumerate(my_players[:15]):
                for mp2, mv2 in my_players[i+1:18]:
                    combined_send = mv1 + mv2
                    value_diff = player_value - combined_send
                    # Fair if combined value is within 20% of target
                    if -15 <= value_diff <= 20 and mv1 <= player_value * 0.85:
                        send_list = [
                            {'name': mp1.name, 'position': mp1.position, 'value': round(mv1, 1)},
                            {'name': mp2.name, 'position': mp2.position, 'value': round(mv2, 1)}
                        ]
                        receive_list = [{'name': player.name, 'position': player.position, 'value': round(player_value, 1)}]
                        fit_score, cat_reasons, window_bonus = score_package(send_list, receive_list, target_team_name, their_window)
                        packages.append({
                            'other_team': target_team_name,
                            'trade_type': '2-for-1',
                            'send': send_list,
                            'receive': receive_list,
                            'send_total': round(combined_send, 1),
                            'receive_total': round(player_value, 1),
                            'value_diff': round(value_diff, 1),
                            'fit_score': round(fit_score - 3, 1),  # Slight penalty for complexity
                            'window_match': their_window,
                            'window_bonus': window_bonus,
                            'category_fit': cat_reasons
                        })

            # 2-for-2 trades
            other_players = [(p, calc_player_value(p)) for p in target_team.players if p.name != player_name and calc_player_value(p) >= 10]
            other_players.sort(key=lambda x: x[1], reverse=True)

            for i, (mp1, mv1) in enumerate(my_players[:10]):
                for mp2, mv2 in my_players[i+1:12]:
                    for op, ov in other_players[:8]:
                        combined_send = mv1 + mv2
                        combined_receive = player_value + ov
                        value_diff = combined_receive - combined_send
                        if -20 <= value_diff <= 20:
                            send_list = [
                                {'name': mp1.name, 'position': mp1.position, 'value': round(mv1, 1)},
                                {'name': mp2.name, 'position': mp2.position, 'value': round(mv2, 1)}
                            ]
                            receive_list = [
                                {'name': player.name, 'position': player.position, 'value': round(player_value, 1)},
                                {'name': op.name, 'position': op.position, 'value': round(ov, 1)}
                            ]
                            fit_score, cat_reasons, window_bonus = score_package(send_list, receive_list, target_team_name, their_window)
                            packages.append({
                                'other_team': target_team_name,
                                'trade_type': '2-for-2',
                                'send': send_list,
                                'receive': receive_list,
                                'send_total': round(combined_send, 1),
                                'receive_total': round(combined_receive, 1),
                                'value_diff': round(value_diff, 1),
                                'fit_score': round(fit_score - 5, 1),  # Penalty for complexity
                                'window_match': their_window,
                                'window_bonus': window_bonus,
                                'category_fit': cat_reasons
                            })

    # Sort by fit score, then by value diff
    packages.sort(key=lambda x: (x['fit_score'], -abs(x['value_diff'])), reverse=True)

    # Dedupe similar packages (same players involved)
    seen = set()
    unique_packages = []
    for pkg in packages:
        key = tuple(sorted([p['name'] for p in pkg['send']] + [p['name'] for p in pkg['receive']]))
        if key not in seen:
            seen.add(key)
            unique_packages.append(pkg)

    return jsonify({
        'player_name': player_name,
        'player_value': round(player_value, 1),
        'my_window': my_window,
        'packages': unique_packages[:limit]
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

                value = calc_player_value(player)
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
                v = calc_player_value(p)
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
            value = calc_player_value(player)
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
    players_with_value = [(p, calc_player_value(p)) for p in team.players]
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
    players_with_value = [(p, calc_player_value(p)) for p in team.players]
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
        # BUT: Never suggest selling elite cornerstones just for category surplus
        elif strong_cats and v >= 35:
            # Skip elite players (80+ value) - untouchable cornerstones
            # Also skip young high-value players (70+ value, age 28 or younger)
            # You don't trade Skubal, Henderson, or Riley Greene just for category surplus
            if v >= 80 or (v >= 70 and p.age <= 28):
                continue  # Never sell a cornerstone just for category surplus

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
            v = calc_player_value(p)
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

            v = calc_player_value(p)
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


def get_gm_trade_partner_intelligence(team_name):
    """
    Analyze which opposing GMs are ideal trade partners based on philosophy matchups.
    Returns tailored insights about who to approach and how to negotiate.
    """
    my_gm = get_assistant_gm(team_name)
    my_philosophy = my_gm.get('philosophy', 'balanced')

    # Philosophy compatibility matrix
    # Key: your philosophy -> Value: list of ideal partner philosophies
    IDEAL_PARTNERS = {
        # Buyers want to target sellers
        'dynasty_champion': ['desperate_accumulator', 'analytical_rebuilder', 'reluctant_dealer'],
        'championship_closer': ['desperate_accumulator', 'analytical_rebuilder', 'prospect_rich_rebuilder', 'reluctant_dealer'],
        'all_in_buyer': ['analytical_rebuilder', 'desperate_accumulator', 'reluctant_dealer', 'crossroads_decision'],
        'smart_contender': ['desperate_accumulator', 'analytical_rebuilder', 'crossroads_decision'],
        'loaded_and_ready': ['desperate_accumulator', 'analytical_rebuilder', 'reluctant_dealer', 'crossroads_decision'],

        # Sellers want to target buyers
        'analytical_rebuilder': ['championship_closer', 'all_in_buyer', 'loaded_and_ready', 'dynasty_champion'],
        'desperate_accumulator': ['championship_closer', 'all_in_buyer', 'loaded_and_ready', 'smart_contender'],
        'reluctant_dealer': ['championship_closer', 'all_in_buyer', 'dynasty_champion'],
        'prospect_rich_rebuilder': ['championship_closer', 'all_in_buyer', 'dynasty_champion'],

        # Middle teams can go either way
        'rising_powerhouse': ['desperate_accumulator', 'all_in_buyer', 'championship_closer'],
        'crossroads_decision': ['desperate_accumulator', 'analytical_rebuilder', 'championship_closer', 'all_in_buyer'],
        'bargain_hunter': ['desperate_accumulator', 'analytical_rebuilder', 'reluctant_dealer'],
    }

    # Negotiation styles based on opposing philosophy
    NEGOTIATION_APPROACH = {
        'dynasty_champion': "They dictate terms. Come with premium offers or don't waste their time.",
        'championship_closer': "They're hungry. Appeal to their win-now urgency - they'll overpay for the right piece.",
        'all_in_buyer': "Everything is on the table for them. Ask for their best prospects.",
        'smart_contender': "They analyze every angle. Bring data-backed proposals with clear value.",
        'loaded_and_ready': "They have leverage and know it. Find creative angles they haven't considered.",
        'bargain_hunter': "They hunt value. Position your offer as 'hidden upside' they're discovering.",
        'rising_powerhouse': "They protect prospects fiercely. Only elite proven talent moves the needle.",
        'crossroads_decision': "They're conflicted. Help them decide by making the choice obvious.",
        'reluctant_dealer': "They hesitate. Apply gentle pressure - remind them value depreciates weekly.",
        'analytical_rebuilder': "Pure value talk. No emotion, just numbers. Show clear ROI.",
        'desperate_accumulator': "They want volume. Bundle multiple pieces - quantity excites them.",
        'prospect_rich_rebuilder': "They hoard prospects. Only offer if you have elite MLB talent to dangle.",
    }

    ideal_partners = IDEAL_PARTNERS.get(my_philosophy, [])

    # Find teams with matching philosophies
    partners = []
    for other_team, other_gm in ASSISTANT_GMS.items():
        if other_team == team_name:
            continue
        other_philosophy = other_gm.get('philosophy', 'balanced')

        if other_philosophy in ideal_partners:
            # Get team info
            other_team_obj = teams.get(other_team)
            if not other_team_obj:
                continue

            _, power_rankings, _ = get_team_rankings()
            other_rank = power_rankings.get(other_team, 6)

            # Get top tradeable assets
            other_players = [(p, calc_player_value(p)) for p in other_team_obj.players]
            other_players.sort(key=lambda x: x[1], reverse=True)
            tradeable = [(p.name, v, p.age) for p, v in other_players[:5] if v >= 30]

            partners.append({
                'team': other_team,
                'gm_name': other_gm.get('name', 'Unknown'),
                'philosophy': other_philosophy,
                'philosophy_name': GM_PHILOSOPHIES.get(other_philosophy, {}).get('name', 'Unknown'),
                'approach': NEGOTIATION_APPROACH.get(other_philosophy, "Standard value-based negotiation."),
                'power_rank': other_rank,
                'top_assets': tradeable[:3],
                'priority': ideal_partners.index(other_philosophy) if other_philosophy in ideal_partners else 99
            })

    # Sort by priority (first in ideal_partners list = most compatible)
    partners.sort(key=lambda x: (x['priority'], x['power_rank']))

    return {
        'my_philosophy': my_philosophy,
        'my_philosophy_name': GM_PHILOSOPHIES.get(my_philosophy, {}).get('name', 'Balanced'),
        'ideal_partners': partners[:4],  # Top 4 trade partners
        'approach_summary': get_philosophy_trade_summary(my_philosophy)
    }


def get_philosophy_trade_summary(philosophy):
    """Return a brief summary of how this philosophy should approach trades."""
    summaries = {
        'dynasty_champion': "Force others to overpay. Only entertain premium offers that clearly upgrade your dynasty.",
        'championship_closer': "Hunt aggressively. Prospects are currency to acquire proven winners. Close the gaps NOW.",
        'all_in_buyer': "Everything is tradeable. Target proven production - development timelines are for rebuilders.",
        'smart_contender': "Calculate every angle. Never pay 100% for 80% production. Find market inefficiencies.",
        'loaded_and_ready': "Play from strength. You have assets AND position - dictate terms in every negotiation.",
        'bargain_hunter': "Creativity beats capital. Target buy-low candidates and overlooked value.",
        'rising_powerhouse': "Protect the foundation. Only move prospects for elite proven stars at significant discounts.",
        'crossroads_decision': "Pick a direction and commit HARD. The middle is quicksand.",
        'reluctant_dealer': "Stop hesitating. Every week you wait, your assets depreciate. Start selling NOW.",
        'analytical_rebuilder': "Zero emotion, maximum return. Sell veterans at peak value, target high-upside youth.",
        'desperate_accumulator': "Cast wide nets. Quantity of prospects now, sort for quality later.",
        'prospect_rich_rebuilder': "Guard the treasure. These prospects ARE the championship plan. Only elite returns move them.",
    }
    return summaries.get(philosophy, "Evaluate opportunities based on roster fit and value.")


def generate_gm_trade_scenarios(team_name, team):
    """
    Generate personalized, actionable trade scenarios based on YOUR team's specific situation.
    Scenarios differ based on competitive window, category needs, roster composition, AND GM PHILOSOPHY.
    Now includes specific multi-player packages and counter-offer suggestions.
    """
    scenarios = []

    players_with_value = [(p, calc_player_value(p)) for p in team.players]
    players_with_value.sort(key=lambda x: x[1], reverse=True)

    # Get GM philosophy - this determines what types of trades are appropriate
    gm = get_assistant_gm(team_name)
    philosophy = gm.get('philosophy', 'balanced')

    # Get the full philosophy object to access new granular parameters
    philosophy_obj = GM_PHILOSOPHIES.get(philosophy, GM_PHILOSOPHIES['balanced'])
    min_value_threshold = philosophy_obj.get('min_value_threshold', 40)
    trade_initiation_style = philosophy_obj.get('trade_initiation_style', 'opportunistic')

    # Determine behavior based on initiation style
    is_aggressive = trade_initiation_style == 'aggressive'
    is_reactive = trade_initiation_style == 'reactive'
    is_opportunistic = trade_initiation_style == 'opportunistic'

    # Define philosophy trade tendencies
    SELLING_PHILOSOPHIES = ['analytical_rebuilder', 'desperate_accumulator', 'reluctant_dealer', 'prospect_rich_rebuilder']
    BUYING_PHILOSOPHIES = ['championship_closer', 'all_in_buyer', 'dynasty_champion', 'loaded_and_ready']
    PATIENT_PHILOSOPHIES = ['rising_powerhouse', 'smart_contender', 'prospect_rich_rebuilder']
    AGGRESSIVE_PHILOSOPHIES = ['championship_closer', 'all_in_buyer', 'desperate_accumulator']

    # Determine trade behavior based on philosophy
    should_sell = philosophy in SELLING_PHILOSOPHIES
    should_buy = philosophy in BUYING_PHILOSOPHIES
    should_be_patient = philosophy in PATIENT_PHILOSOPHIES
    should_protect_prospects = philosophy in ['rising_powerhouse', 'prospect_rich_rebuilder', 'smart_contender']

    # Get team context
    team_cats, rankings = calculate_league_category_rankings()
    my_ranks = rankings.get(team_name, {})
    _, power_rankings, _ = get_team_rankings()
    my_power_rank = power_rankings.get(team_name, 6)

    # Determine competitive window (used as secondary filter, philosophy is primary)
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

    # Find tradeable assets - EXPANDED to include more players
    tradeable = [(p, v) for i, (p, v) in enumerate(players_with_value) if i >= 3 and v >= 15]

    # Mid-tier trade chips (40-60 value) - prime trade candidates like Robby Snelling
    mid_tier_assets = [(p, v) for p, v in players_with_value if 35 <= v <= 65]

    # High-value prospects that could be sold at peak hype
    peak_hype_prospects = [(p, v) for p, v in players_with_value
                          if p.is_prospect and p.prospect_rank and p.prospect_rank <= 50 and v >= 40]

    # Consolidation candidates - multiple mid-tier players that could be packaged
    consolidation_pool = [(p, v) for p, v in tradeable if 25 <= v <= 50]

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
    def find_trade_targets(target_cat, value_range=None, prefer_sellers=True, exclude_surplus_positions=True):
        """Find specific players from other teams that address our category need.
        Uses GM's min_value_threshold for default value range.
        Now checks if we already have surplus at the player's position before suggesting."""
        # Default value range based on GM's min_value_threshold
        if value_range is None:
            value_range = (min_value_threshold, 85)  # Use GM's threshold as floor
        targets = []
        for other_team_name, other_team in teams.items():
            if other_team_name == team_name:
                continue
            other_rank = power_rankings.get(other_team_name, 6)
            is_seller = other_rank >= 8

            for p in other_team.players:
                # Check if we already have surplus at this position
                if exclude_surplus_positions:
                    player_pos = p.position.split('/')[0].split(',')[0].upper() if p.position else 'UTIL'
                    if player_pos in ['LF', 'CF', 'RF']:
                        player_pos = 'OF'
                    # Skip if we already have 4+ at this position (surplus)
                    if pos_counts.get(player_pos, 0) >= 4:
                        continue

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
                    pv = calc_player_value(p)
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
        """Build a package of players to match target value.
        Now with tighter value matching for elite targets (80+ value)."""
        package = []
        remaining = target_value

        # TRUE SUPERSTARS (98+) - Cannot be acquired in package deals at all
        # Players like Ohtani, Acuna at peak are only traded 1-for-1 with other superstars
        if target_value >= 98:
            return []  # No package deal for true superstars

        # Elite players (80+ value) require stricter value matching
        # Cannot realistically be acquired with 2-3 mid-tier players
        is_elite_target = target_value >= 80
        if is_elite_target:
            # For elite targets, need at least one player worth 65% of target value
            # Can't just cobble together multiple mid-tier players
            min_anchor_value = target_value * 0.65
        else:
            min_anchor_value = target_value * 0.3

        candidates = tradeable.copy()
        if prefer_prospects:
            candidates.sort(key=lambda x: (x[0].is_prospect, x[1]), reverse=True)
        else:
            candidates.sort(key=lambda x: x[1], reverse=True)

        # For elite targets, first check if we even have a suitable anchor piece
        if is_elite_target:
            has_anchor = any(v >= min_anchor_value for p, v in candidates)
            if not has_anchor:
                return []  # Can't realistically build a package for an elite player

        for p, v in candidates:
            if len(package) >= max_players:
                break

            # First piece needs to be substantial for elite targets
            if is_elite_target and len(package) == 0:
                if v < min_anchor_value:
                    continue  # Skip until we find a worthy anchor

            # Tighter range for elite targets: 40%-110% of remaining
            if is_elite_target:
                if v <= remaining * 1.1 and v >= remaining * 0.4:
                    package.append((p, v))
                    remaining -= v
            else:
                if v <= remaining * 1.2 and v >= remaining * 0.3:
                    package.append((p, v))
                    remaining -= v

            if remaining <= target_value * 0.1:  # Close enough
                break

        # For elite targets, validate the package is realistic using tiered thresholds
        if is_elite_target and package:
            total_package_value = sum(v for p, v in package)

            # Tiered minimum package value based on target tier
            if target_value >= 95:
                min_ratio = 1.10  # Superstar: need 110% (significant overpay)
            elif target_value >= 85:
                min_ratio = 1.00  # Elite: need 100% (fair value)
            elif target_value >= 80:
                min_ratio = 0.95  # Star: need 95% (close to fair)
            else:
                min_ratio = 0.90  # Standard elite: need 90%

            if total_package_value < target_value * min_ratio:
                return []  # Package not substantial enough for this tier

            # For 2+ player packages targeting elite players, no "throw-in" pieces allowed
            # Each piece must be meaningful (at least 25% of target value, minimum 20)
            if len(package) >= 2:
                min_piece_value = max(target_value * 0.25, 20)
                for p, v in package:
                    if v < min_piece_value:
                        return []  # Has a throw-in piece - not realistic for elite targets

        return package

    # Philosophy-specific scenario title generators - no player names, action-focused
    def get_buy_title(category):
        """Generate philosophy-appropriate title for buy scenarios."""
        titles = {
            'dynasty_champion': f"Upgrade {category}",
            'championship_closer': f"Hunt {category}",
            'all_in_buyer': f"Go Get {category}",
            'smart_contender': f"Calculated {category} Add",
            'loaded_and_ready': f"Power Move",
            'bargain_hunter': f"Value Add",
            'rising_powerhouse': f"Accelerate {category}",
        }
        return titles.get(philosophy, f"Add {category}")

    def get_sell_title():
        """Generate philosophy-appropriate title for sell scenarios."""
        titles = {
            'analytical_rebuilder': "Optimal Exit",
            'desperate_accumulator': "Volume Play",
            'reluctant_dealer': "Finally Moving",
            'prospect_rich_rebuilder': "Convert to Youth",
            'crossroads_decision': "Commit to Rebuild",
        }
        return titles.get(philosophy, "Sell High")

    def get_reasoning_prefix():
        """Get philosophy-specific reasoning prefix."""
        prefixes = {
            'dynasty_champion': "From the throne:",
            'championship_closer': "Championship math:",
            'all_in_buyer': "Win now or bust:",
            'smart_contender': "The numbers say:",
            'loaded_and_ready': "From a position of strength:",
            'bargain_hunter': "Value hunting:",
            'rising_powerhouse': "Protecting the future:",
            'crossroads_decision': "Decision time:",
            'reluctant_dealer': "No more waiting:",
            'analytical_rebuilder': "The model shows:",
            'desperate_accumulator': "Volume acquisition:",
            'prospect_rich_rebuilder': "Future-first:",
        }
        return prefixes.get(philosophy, "Analysis:")

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
                        'title': get_buy_title(target_cat),
                        'target': f"{best['player'].name} ({best['team']}){seller_note}",
                        'target_value': target_value,
                        'target_stats': f"{best['cat_value']:.0f} {target_cat} projected",
                        'offer': offer_str,
                        'offer_value': package_value,
                        'package_details': [(p.name, round(v, 1), p.is_prospect) for p, v in package],
                        'reasoning': f"{get_reasoning_prefix()} You're #{my_power_rank} but rank #{cat_rank} in {target_cat}. {best['player'].name} projects for {best['cat_value']:.0f} {target_cat}.{negotiation_tip}",
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
                    their_young = [(p, calc_player_value(p)) for p in other_team.players
                                  if p.age <= 26 and not p.is_prospect]
                    their_young.sort(key=lambda x: x[1], reverse=True)

                    if their_prospects or their_young:
                        # Build what we want from them
                        ask_parts = []
                        ask_value = 0
                        if their_prospects:
                            ask_parts.append(f"{their_prospects[0].name} (#{their_prospects[0].prospect_rank})")
                            ask_value += calc_player_value(their_prospects[0])
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
                            'title': get_sell_title(),
                            'target': " + ".join(ask_parts) + pick_suggestion,
                            'target_value': ask_value,
                            'offer': f"{best_vet[0].name} ({best_vet[1]:.0f} value, age {best_vet[0].age})",
                            'offer_value': best_vet[1],
                            'reasoning': f"{get_reasoning_prefix()} {other_team_name} is #{other_rank} and pushing for a title. {best_vet[0].name}'s value peaks NOW - sell before decline.\nNegotiation: Ask for their best prospect + a young player. They're desperate.",
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
                    target_value = calc_player_value(target)
                    offer_value = sum(calc_player_value(p) for p in lower_prospects)
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
                    'target_value': vet[1] * 0.97,  # Expect near-fair value
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
                    'target_value': best_vet[1] * 0.97,  # Expect near-fair value
                    'offer': f"{best_vet[0].name} ({best_vet[1]:.0f} value, age {best_vet[0].age})",
                    'offer_value': best_vet[1],
                    'reasoning': f"Ranked #{my_power_rank} with avg age {avg_age:.1f}. Not good enough to win, too old to wait. Sell {best_vet[0].name} to {buyer_team} and restart.\nDecision time: Commit to rebuild NOW or risk being stuck in the middle forever.",
                    'trade_type': 'sell',
                    'urgency': 'high'
                })

        elif young_stars and not should_sell:
            # Only suggest acceleration for teams NOT in selling mode
            star = young_stars[0]
            # Find what category they help and what we need
            if weak_cats and should_buy:
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

    # ============ PHILOSOPHY-AWARE SCENARIOS ============

    # For SELLING philosophies: prioritize sell scenarios
    if should_sell and len(scenarios) < 3:
        # Find veterans to sell for prospects
        sellable_vets = [(p, v) for p, v in players_with_value if p.age >= 28 and v >= 30]
        if sellable_vets:
            for vet, vet_val in sellable_vets[:2]:
                # Find rebuilding teams that might have prospects to trade
                for other_team_name, other_team in teams.items():
                    if other_team_name == team_name:
                        continue
                    other_rank = power_rankings.get(other_team_name, 6)
                    # Target contenders who need help
                    if other_rank <= 5:
                        their_prospects = [p for p in other_team.players if p.is_prospect and p.prospect_rank and p.prospect_rank <= 100]
                        if their_prospects:
                            scenarios.append({
                                'title': get_sell_title(),
                                'target': f"Prospects from {other_team_name}",
                                'target_value': vet_val * 0.97,  # Expect near-fair value, not a discount
                                'target_stats': f"Target their prospect depth",
                                'offer': f"{vet.name} ({vet_val:.0f} value, age {vet.age})",
                                'offer_value': vet_val,
                                'reasoning': f"{get_reasoning_prefix()} {vet.name} is {vet.age} years old with {vet_val:.0f} value. {other_team_name} (#{other_rank}) is contending and needs veterans.",
                                'trade_type': 'sell',
                                'urgency': 'high'
                            })
                            break
                if len(scenarios) >= 3:
                    break

    # UNIVERSAL: Positional surplus trade (works for any team, but respects philosophy)
    if surplus_positions and weak_cats and len(scenarios) < 3 and not should_sell:
        # Only for non-selling teams - selling teams shouldn't be acquiring to fix categories
        surplus_pos = surplus_positions[0]
        surplus_players = [(p, v) for p, v in players_with_value
                          if surplus_pos in (p.position or '').upper() and v >= 25]
        if len(surplus_players) >= 2:
            trade_piece = surplus_players[1]  # Not your best at position

            # For patient philosophies, only trade veterans from surplus
            if should_protect_prospects and trade_piece[0].age < 27:
                # Find an older player to trade instead
                older_surplus = [(p, v) for p, v in surplus_players if p.age >= 28]
                if older_surplus:
                    trade_piece = older_surplus[0]
                else:
                    trade_piece = None

            if trade_piece:
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
                        'reasoning': f"{get_reasoning_prefix()} You have {pos_counts.get(surplus_pos, 0)} {surplus_pos} but rank #{target_rank} in {target_cat}. {best['player'].name} directly addresses your need.",
                        'trade_type': 'rebalance',
                        'urgency': 'low'
                    })

    # Category strength trade (only for non-selling teams, and respects prospect protection)
    if strong_cats and weak_cats and len(scenarios) < 4 and not should_sell:
        strong_cat, strong_rank = strong_cats[0]
        weak_cat, weak_rank = weak_cats[0]

        # Find a player contributing to your strength that you could trade
        strength_players = []
        for p, v in tradeable:
            # For prospect-protecting philosophies, only consider veterans
            if should_protect_prospects and p.age < 27:
                continue

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
                    'reasoning': f"{get_reasoning_prefix()} You're #{strong_rank} in {strong_cat} (surplus) but #{weak_rank} in {weak_cat}. Textbook optimization.",
                    'trade_type': 'rebalance',
                    'urgency': 'medium'
                })

    # ============ FALLBACK SCENARIOS - Ensure every team gets at least one ============
    if len(scenarios) == 0:
        if should_sell:
            # Fallback for SELLING teams: find any veteran to sell
            sellable = [(p, v) for p, v in players_with_value if p.age >= 27 and v >= 25]
            if sellable:
                vet = sellable[0]
                scenarios.append({
                    'title': get_sell_title(),
                    'target': "Prospects and/or draft picks",
                    'target_value': vet[1] * 0.8,
                    'target_stats': "Youth and future assets",
                    'offer': f"{vet[0].name} ({vet[1]:.0f} value, age {vet[0].age})",
                    'offer_value': vet[1],
                    'reasoning': f"{get_reasoning_prefix()} {vet[0].name} at age {vet[0].age} doesn't fit your timeline. Convert to future assets now.",
                    'trade_type': 'sell',
                    'urgency': 'high'
                })
        else:
            # Fallback for NON-SELLING teams: General category improvement
            if weak_cats:
                target_cat, target_rank = weak_cats[0]
                targets = find_trade_targets(target_cat, (25, 60))
                # Find a veteran trade piece (not young talent)
                vet_tradeable = [(p, v) for p, v in tradeable if p.age >= 27] if should_protect_prospects else tradeable
                if targets and vet_tradeable:
                    best = targets[0]
                    trade_piece = vet_tradeable[0]
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

        # Fallback 2: Buy low on underperformer (ONLY for buying philosophies)
        if len(scenarios) < 2 and should_buy:
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                other_rank = power_rankings.get(other_team_name, 6)
                if other_rank >= 8:  # Struggling team
                    their_players = [(p, calc_player_value(p)) for p in other_team.players]
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
                their_players = [(op, calc_player_value(op)) for op in other_team.players]
                their_players.sort(key=lambda x: x[1], reverse=True)
                # Find a comparable player
                for op, ov in their_players:
                    # Check positional depth - skip if we already have 4+ at this position
                    target_pos = op.position.split('/')[0].split(',')[0].upper() if op.position else 'UTIL'
                    if target_pos in ['LF', 'CF', 'RF']:
                        target_pos = 'OF'
                    if pos_counts.get(target_pos, 0) >= 4:
                        continue

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

    # ============ NEW SCENARIO TYPES ============

    # 1. PROSPECT AT PEAK HYPE - Sell prospects before MLB risk
    if peak_hype_prospects and should_sell:
        for prospect, pval in peak_hype_prospects[:2]:
            # Find contending teams who might overpay
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                other_rank = power_rankings.get(other_team_name, 6)
                if other_rank <= 5:  # Contending team
                    other_gm = get_assistant_gm(other_team_name)
                    other_phil = other_gm.get('philosophy', '')
                    if other_phil in ['championship_closer', 'all_in_buyer', 'loaded_and_ready']:
                        # They might overpay for proven talent
                        their_vets = sorted(
                            [(p, calc_player_value(p)) for p in other_team.players if p.age >= 27 and not p.is_prospect],
                            key=lambda x: x[1], reverse=True
                        )
                        if their_vets and their_vets[0][1] >= pval * 0.8:
                            target_vet = their_vets[0]
                            scenarios.append({
                                'title': f"Sell Prospect Hype: #{prospect.prospect_rank}",
                                'target': f"{target_vet[0].name} ({other_team_name})",
                                'target_value': target_vet[1],
                                'offer': f"{prospect.name} (#{prospect.prospect_rank})",
                                'offer_value': pval,
                                'reasoning': f"Prospect hype peaks before MLB exposure. {other_team_name} is win-now and may overpay for {prospect.name}'s ceiling. Lock in proven production.",
                                'trade_type': 'sell',
                                'urgency': 'medium'
                            })
                            break

    # 2. CONSOLIDATE 2-FOR-1 - Package mid-tier into elite
    if len(consolidation_pool) >= 3:
        # Find two mid-tier players we can package
        package_candidates = consolidation_pool[:4]
        combined_value = sum(v for p, v in package_candidates[:2])

        for other_team_name, other_team in teams.items():
            if other_team_name == team_name:
                continue
            their_players = sorted(
                [(p, calc_player_value(p)) for p in other_team.players],
                key=lambda x: x[1], reverse=True
            )
            for tp, tv in their_players:
                # Check positional depth - skip if we already have 4+ at this position
                target_pos = tp.position.split('/')[0].split(',')[0].upper() if tp.position else 'UTIL'
                if target_pos in ['LF', 'CF', 'RF']:
                    target_pos = 'OF'
                if pos_counts.get(target_pos, 0) >= 4:
                    continue

                # Tiered value matching based on target value
                # Higher value players require closer-to-fair or overpay packages
                if tv >= 95:
                    # Superstar tier (95+): Need significant overpay (110%+)
                    min_package_ratio = 1.10
                elif tv >= 85:
                    # Elite tier (85-94): Need fair value or slight overpay (100%+)
                    min_package_ratio = 1.00
                elif tv >= 75:
                    # Star tier (75-84): Need close to fair (95%+)
                    min_package_ratio = 0.95
                else:
                    # Standard tier: Normal matching (85%+)
                    min_package_ratio = 0.85

                # Check if our package meets the minimum for this tier
                if combined_value >= tv * min_package_ratio and tv >= 55:
                    # Also cap: package shouldn't massively overpay (max 130% of target)
                    if combined_value <= tv * 1.30:
                        offer_str = f"{package_candidates[0][0].name} + {package_candidates[1][0].name}"
                        scenarios.append({
                            'title': "Consolidate: 2-for-1 Upgrade",
                            'target': f"{tp.name} ({other_team_name})",
                            'target_value': tv,
                            'offer': offer_str,
                            'offer_value': combined_value,
                            'reasoning': f"Package depth for star power. {tp.name} is worth the consolidation - fewer roster spots, more impact.",
                            'trade_type': 'consolidate',
                            'urgency': 'medium'
                        })
                        break
            if len([s for s in scenarios if s.get('trade_type') == 'consolidate']) >= 1:
                break

    # 3. MID-TIER VALUE SWAP - Players in 40-60 range are prime trade chips
    if mid_tier_assets:
        for player, pval in mid_tier_assets[:3]:
            # Skip if player is already in scenarios
            if any(player.name in s.get('offer', '') for s in scenarios):
                continue

            # Find similar-value players on other teams who fill different needs
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue

                their_cats, their_pos, _ = calculate_team_needs(other_team_name)
                their_weaknesses = [cat for cat, score in their_cats.items() if score < 0]

                # Check if our player helps their weakness
                player_proj = HITTER_PROJECTIONS.get(player.name, {}) or PITCHER_PROJECTIONS.get(player.name, {})
                helps_them = False
                for wcat in their_weaknesses:
                    if wcat in ['HR', 'RBI', 'SB'] and player_proj.get(wcat, 0) > 15:
                        helps_them = True
                        break
                    if wcat in ['K', 'QS'] and player_proj.get(wcat, 0) > 80:
                        helps_them = True
                        break

                if helps_them:
                    # Find their player who helps us
                    their_players = [(p, calc_player_value(p)) for p in other_team.players]
                    for tp, tv in their_players:
                        if abs(tv - pval) <= 15:  # Similar value
                            tp_proj = HITTER_PROJECTIONS.get(tp.name, {}) or PITCHER_PROJECTIONS.get(tp.name, {})
                            helps_us = False
                            for our_weak in weak_cats:
                                wcat = our_weak[0] if isinstance(our_weak, tuple) else our_weak
                                if wcat in ['HR', 'RBI', 'SB'] and tp_proj.get(wcat, 0) > 15:
                                    helps_us = True
                                    break
                                if wcat in ['K', 'QS'] and tp_proj.get(wcat, 0) > 80:
                                    helps_us = True
                                    break

                            if helps_us:
                                scenarios.append({
                                    'title': f"Value Swap: Mutual Fit",
                                    'target': f"{tp.name} ({other_team_name})",
                                    'target_value': tv,
                                    'offer': f"{player.name}",
                                    'offer_value': pval,
                                    'reasoning': f"Both teams improve - you get help where you need it, they get help where they need it. Clean 1-for-1 value match.",
                                    'trade_type': 'swap',
                                    'urgency': 'medium'
                                })
                                break
                    break

    # 4. EXPANDED REBALANCE - More comprehensive position/category trades
    # Rebalance: Youth → Production (for contenders)
    if should_buy and young_stars and len([s for s in scenarios if 'Rebalance' in s.get('title', '')]) < 2:
        for young_p, young_v in young_stars[:2]:
            if young_p.age <= 24:  # Very young star
                for other_team_name, other_team in teams.items():
                    if other_team_name == team_name:
                        continue
                    other_rank = power_rankings.get(other_team_name, 6)
                    if other_rank >= 8:  # Rebuilding team wants youth
                        their_vets = sorted(
                            [(p, calc_player_value(p)) for p in other_team.players if p.age >= 28 and p.age <= 32],
                            key=lambda x: x[1], reverse=True
                        )
                        if their_vets:
                            for vet, vet_v in their_vets:
                                # Skip elite players - 1-for-1 for elite players is unrealistic
                                # unless both players are elite (85+ each)
                                if vet_v >= 85 and young_v < 80:
                                    continue

                                # Check positional depth - skip if we already have 4+ at this position
                                vet_pos = vet.position.split('/')[0].split(',')[0].upper() if vet.position else 'UTIL'
                                if vet_pos in ['LF', 'CF', 'RF']:
                                    vet_pos = 'OF'
                                if pos_counts.get(vet_pos, 0) >= 4:
                                    continue

                                # Tighter value matching: within 10% for high-value, 15 pts for lower value
                                if vet_v >= 70:
                                    value_diff_ok = abs(vet_v - young_v) <= vet_v * 0.12
                                else:
                                    value_diff_ok = abs(vet_v - young_v) <= 15

                                if value_diff_ok:
                                    scenarios.append({
                                        'title': f"Rebalance: Youth → Production",
                                        'target': f"{vet.name} ({other_team_name})",
                                        'target_value': vet_v,
                                        'offer': f"{young_p.name}",
                                        'offer_value': young_v,
                                        'reasoning': f"Trade future upside for prime production. {vet.name} produces NOW while {young_p.name}'s value to rebuilders is at its peak.",
                                        'trade_type': 'rebalance',
                                        'urgency': 'medium'
                                    })
                                    break
                        break

    # Rebalance: Arm Depth → Bat (or vice versa)
    pitcher_value = sum(v for p, v in players_with_value if 'SP' in (p.position or '').upper() or 'RP' in (p.position or '').upper())
    hitter_value = sum(v for p, v in players_with_value if 'SP' not in (p.position or '').upper() and 'RP' not in (p.position or '').upper())

    if pitcher_value > hitter_value * 1.3:  # Arm heavy
        # Find a pitcher to trade for a hitter
        tradeable_pitchers = [(p, v) for p, v in tradeable if 'SP' in (p.position or '').upper() and v >= 35]
        if tradeable_pitchers:
            best_arm = tradeable_pitchers[0]
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                their_hitters = sorted(
                    [(p, calc_player_value(p)) for p in other_team.players
                     if 'SP' not in (p.position or '').upper() and 'RP' not in (p.position or '').upper()],
                    key=lambda x: x[1], reverse=True
                )
                for th, thv in their_hitters:
                    # Check positional depth - skip if we already have 4+ at this position
                    target_pos = th.position.split('/')[0].split(',')[0].upper() if th.position else 'UTIL'
                    if target_pos in ['LF', 'CF', 'RF']:
                        target_pos = 'OF'
                    if pos_counts.get(target_pos, 0) >= 4:
                        continue

                    # Tighter value matching for high-value players
                    if thv >= 70:
                        value_ok = abs(thv - best_arm[1]) <= thv * 0.15
                    else:
                        value_ok = abs(thv - best_arm[1]) <= 15

                    if value_ok:
                        scenarios.append({
                            'title': "Rebalance: Pitching → Hitting",
                            'target': f"{th.name} ({other_team_name})",
                            'target_value': thv,
                            'offer': f"{best_arm[0].name}",
                            'offer_value': best_arm[1],
                            'reasoning': f"You're pitching-heavy. Convert excess arm value into bat production for better roster balance.",
                            'trade_type': 'rebalance',
                            'urgency': 'low'
                        })
                        break
                break

    elif hitter_value > pitcher_value * 1.3:  # Bat heavy
        tradeable_hitters = [(p, v) for p, v in tradeable if 'SP' not in (p.position or '').upper() and 'RP' not in (p.position or '').upper() and v >= 35]
        if tradeable_hitters:
            best_bat = tradeable_hitters[0]
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                their_pitchers = sorted(
                    [(p, calc_player_value(p)) for p in other_team.players
                     if 'SP' in (p.position or '').upper()],
                    key=lambda x: x[1], reverse=True
                )
                for tp, tpv in their_pitchers:
                    # Check positional depth - skip if we already have 4+ SP
                    if pos_counts.get('SP', 0) >= 4:
                        continue

                    # Tighter value matching for high-value players
                    if tpv >= 70:
                        value_ok = abs(tpv - best_bat[1]) <= tpv * 0.15
                    else:
                        value_ok = abs(tpv - best_bat[1]) <= 15

                    if value_ok:
                        scenarios.append({
                            'title': "Rebalance: Hitting → Pitching",
                            'target': f"{tp.name} ({other_team_name})",
                            'target_value': tpv,
                            'offer': f"{best_bat[0].name}",
                            'offer_value': best_bat[1],
                            'reasoning': f"You're bat-heavy. Convert excess hitting value into pitching for better roster balance.",
                            'trade_type': 'rebalance',
                            'urgency': 'low'
                        })
                        break
                break

    # 5. BUY LOW - Target underperforming players with high upside
    buy_low_targets = []
    for other_team_name, other_team in teams.items():
        if other_team_name == team_name:
            continue
        other_rank = power_rankings.get(other_team_name, 6)
        # Rebuilding teams more likely to sell underperformers
        is_seller = other_rank >= 7

        for p in other_team.players:
            pval = calc_player_value(p)
            proj = HITTER_PROJECTIONS.get(p.name, {}) or PITCHER_PROJECTIONS.get(p.name, {})

            # Look for players whose value might be depressed
            # Young players with high draft pedigree but low current value
            if p.age <= 27 and pval >= 30 and pval <= 55:
                # Check if they have upside indicators
                has_upside = False
                if proj.get('HR', 0) >= 20 or proj.get('SB', 0) >= 15:
                    has_upside = True
                if proj.get('K', 0) >= 150 or proj.get('QS', 0) >= 12:
                    has_upside = True
                if p.is_prospect and p.prospect_rank and p.prospect_rank <= 100:
                    has_upside = True

                if has_upside:
                    buy_low_targets.append({
                        'player': p,
                        'team': other_team_name,
                        'value': pval,
                        'is_seller': is_seller,
                        'upside_reason': 'Young with projection upside'
                    })

    # Sort by seller status and value
    buy_low_targets.sort(key=lambda x: (x['is_seller'], -x['value']), reverse=True)

    if buy_low_targets and should_buy:
        for target in buy_low_targets[:2]:
            # Find a package slightly below their value
            offer_value = target['value'] * 0.85
            package = [(p, v) for p, v in tradeable if v <= offer_value and v >= offer_value * 0.5]
            if package:
                scenarios.append({
                    'title': "Buy Low Opportunity",
                    'target': f"{target['player'].name} ({target['team']})",
                    'target_value': target['value'],
                    'offer': f"{package[0][0].name}",
                    'offer_value': package[0][1],
                    'reasoning': f"Buy low on {target['player'].name} - young player with upside currently valued below potential. {'Seller team likely to deal.' if target['is_seller'] else 'May need to pay fair value.'}",
                    'trade_type': 'buy_low',
                    'urgency': 'medium',
                    'counter_offer': f"If declined, try adding a late pick or swap in a slightly better piece (~{target['value'] * 0.95:.0f} value)."
                })

    # 6. CATEGORY STACKING - Double down on strengths for category dominance
    if strong_cats and should_buy:
        best_cat = strong_cats[0][0] if strong_cats else None
        if best_cat:
            # Find players who excel in our best category
            stack_targets = []
            for other_team_name, other_team in teams.items():
                if other_team_name == team_name:
                    continue
                for p in other_team.players:
                    proj = HITTER_PROJECTIONS.get(p.name, {}) or PITCHER_PROJECTIONS.get(p.name, {})
                    pval = calc_player_value(p)

                    cat_value = 0
                    if best_cat == 'HR':
                        cat_value = proj.get('HR', 0)
                    elif best_cat == 'SB':
                        cat_value = proj.get('SB', 0)
                    elif best_cat == 'K':
                        cat_value = proj.get('K', 0)
                    elif best_cat == 'QS':
                        cat_value = proj.get('QS', 0)
                    elif best_cat == 'SV+HLD':
                        cat_value = proj.get('SV', 0) + proj.get('HD', 0)

                    if cat_value > 0 and pval >= 35:
                        stack_targets.append({
                            'player': p,
                            'team': other_team_name,
                            'value': pval,
                            'cat_value': cat_value
                        })

            stack_targets.sort(key=lambda x: x['cat_value'], reverse=True)

            if stack_targets:
                # Filter out positions we're already deep at
                filtered_targets = []
                for t in stack_targets:
                    target_pos = t['player'].position.split('/')[0].split(',')[0].upper() if t['player'].position else 'UTIL'
                    if target_pos in ['LF', 'CF', 'RF']:
                        target_pos = 'OF'
                    # Skip if we have 4+ at this position OR if player is a true superstar (98+)
                    if pos_counts.get(target_pos, 0) >= 4:
                        continue
                    if t['value'] >= 98:  # True superstars can't be acquired in package deals
                        continue
                    filtered_targets.append(t)

                if filtered_targets:
                    best = filtered_targets[0]
                    package = build_trade_package(best['value'], prefer_prospects=True)
                    if package:
                        offer_str = " + ".join([f"{p.name}" for p, v in package[:2]])
                        scenarios.append({
                            'title': f"Category Stack: Dominate {best_cat}",
                            'target': f"{best['player'].name} ({best['team']})",
                            'target_value': best['value'],
                            'offer': offer_str,
                            'offer_value': sum(v for p, v in package[:2]),
                            'reasoning': f"You're already strong in {best_cat}. Stack more to guarantee winning this category weekly. {best['player'].name} projects for {best['cat_value']:.0f} {best_cat}.",
                            'trade_type': 'stack',
                            'urgency': 'low'
                        })

    # 7. POSITIONAL UPGRADE PATH - Upgrade weak positions to elite
    for pos in thin_positions[:2]:
        # Find elite players at this position on other teams
        pos_upgrades = []
        for other_team_name, other_team in teams.items():
            if other_team_name == team_name:
                continue
            for p in other_team.players:
                player_pos = (p.position or '').upper()
                if pos in player_pos or (pos == 'OF' and any(x in player_pos for x in ['LF', 'CF', 'RF'])):
                    pval = calc_player_value(p)
                    if pval >= 50:  # Elite level
                        pos_upgrades.append({
                            'player': p,
                            'team': other_team_name,
                            'value': pval
                        })

        pos_upgrades.sort(key=lambda x: x['value'], reverse=True)

        if pos_upgrades:
            best = pos_upgrades[0]
            package = build_trade_package(best['value'], prefer_prospects=False)
            if package:
                offer_str = " + ".join([f"{p.name}" for p, v in package[:2]])
                scenarios.append({
                    'title': f"Upgrade {pos}: Elite Tier",
                    'target': f"{best['player'].name} ({best['team']})",
                    'target_value': best['value'],
                    'offer': offer_str,
                    'offer_value': sum(v for p, v in package[:2]),
                    'reasoning': f"You're thin at {pos}. {best['player'].name} is an elite option that transforms your roster at this position.",
                    'trade_type': 'upgrade',
                    'urgency': 'medium',
                    'counter_offer': f"If declined, ask what piece they'd need added. Consider including a pick to sweeten."
                })
            break  # Only one positional upgrade scenario

    # 8. MULTI-ASSET PACKAGE OPPORTUNITIES - Complex trades for big returns
    if len(tradeable) >= 4 and should_buy:
        # Find an elite player we could target with a 3-for-1
        for other_team_name, other_team in teams.items():
            if other_team_name == team_name:
                continue
            other_rank = power_rankings.get(other_team_name, 6)
            # Rebuilding teams like getting multiple pieces
            if other_rank >= 7:
                their_stars = sorted(
                    [(p, calc_player_value(p)) for p in other_team.players],
                    key=lambda x: x[1], reverse=True
                )
                # Skip true superstars (98+) - they don't get traded in package deals
                # Also check position depth
                valid_stars = []
                for sp, sv in their_stars:
                    if sv >= 98:  # True superstar - skip
                        continue
                    target_pos = sp.position.split('/')[0].split(',')[0].upper() if sp.position else 'UTIL'
                    if target_pos in ['LF', 'CF', 'RF']:
                        target_pos = 'OF'
                    if pos_counts.get(target_pos, 0) >= 4:  # Already deep - skip
                        continue
                    valid_stars.append((sp, sv))

                if valid_stars and valid_stars[0][1] >= 70:
                    star = valid_stars[0]
                    # Build a 3-player package
                    package = []
                    remaining = star[1] * 1.1  # Slight overpay for star
                    for p, v in tradeable:
                        if len(package) >= 3:
                            break
                        if v <= remaining * 0.5 and v >= 20:
                            package.append((p, v))
                            remaining -= v

                    if len(package) >= 2:
                        pkg_value = sum(v for p, v in package)
                        # CRITICAL: Validate ratio is between 0.85 and 1.15
                        ratio = pkg_value / star[1] if star[1] > 0 else 0
                        if ratio >= 0.85 and ratio <= 1.15:
                            offer_str = " + ".join([f"{p.name}" for p, v in package])
                            scenarios.append({
                                'title': "Blockbuster: 3-for-1 Star",
                                'target': f"{star[0].name} ({other_team_name})",
                                'target_value': star[1],
                                'offer': offer_str,
                                'offer_value': pkg_value,
                                'reasoning': f"Rebuilding teams love quantity. Package depth for {star[0].name} - a true difference-maker.",
                                'trade_type': 'blockbuster',
                                'urgency': 'medium',
                                'counter_offer': f"If they want more, ask which piece they'd swap. Adding a 2nd Rd pick often closes these."
                            })
                            break

    # ============ SMART SCENARIO RANKING ============
    # Score and filter scenarios based on GM personality parameters
    scored_scenarios = []
    for s in scenarios:
        score = 50  # Base score

        # Filter by min_value_threshold - only show deals above GM's threshold
        target_val = s.get('target_value', 0)
        if target_val > 0 and target_val < min_value_threshold:
            score -= 30  # Penalize deals below GM's threshold

        # Value matching bonus/penalty
        if s['target_value'] > 0 and s['offer_value'] > 0:
            value_gap = abs(s['target_value'] - s['offer_value'])
            gap_pct = value_gap / max(s['target_value'], s['offer_value'], 1)
            if gap_pct <= 0.1:  # Within 10% - excellent match
                score += 20
            elif gap_pct <= 0.2:  # Within 20% - good match
                score += 10
            elif gap_pct > 0.4:  # Over 40% gap - poor match
                score -= 20

        # Urgency bonus
        if s.get('urgency') == 'high':
            score += 15
        elif s.get('urgency') == 'medium':
            score += 5

        # Trade type preferences based on philosophy
        if should_sell and s.get('trade_type') == 'sell':
            score += 10
        elif should_buy and s.get('trade_type') == 'buy':
            score += 10

        # Trade initiation style preferences
        trade_type = s.get('trade_type', '')
        if is_aggressive:
            # Aggressive GMs prefer proactive scenarios
            if trade_type in ['buy', 'buy_low', 'blockbuster', 'consolidate']:
                score += 15  # Boost active acquisition scenarios
            if s.get('urgency') == 'high':
                score += 10  # Extra boost for urgent deals
        elif is_reactive:
            # Reactive GMs prefer sell scenarios and value plays
            if trade_type in ['sell', 'hold', 'evaluate']:
                score += 15  # Boost wait-and-see scenarios
            if trade_type in ['buy', 'blockbuster']:
                score -= 10  # Penalize aggressive buys
        elif is_opportunistic:
            # Opportunistic GMs prefer balanced value plays
            if trade_type in ['swap', 'rebalance', 'buy_low']:
                score += 15  # Boost value optimization plays

        # Prefer actionable trades (with specific targets) over generic advice
        if s['target_value'] > 0:
            score += 10

        s['_score'] = score
        s['_initiation_style'] = trade_initiation_style  # Add for Trade Center display
        scored_scenarios.append(s)

    # Sort by score descending
    scored_scenarios.sort(key=lambda x: x.get('_score', 0), reverse=True)

    # CRITICAL: Filter out scenarios with unrealistic ratios (< 0.85 or > 1.15)
    # Trades outside this range would never be accepted - matches chatbot rules
    filtered_scenarios = []
    for s in scored_scenarios:
        target_val = s.get('target_value', 0)
        offer_val = s.get('offer_value', 0)
        if target_val > 0 and offer_val > 0:
            ratio = offer_val / target_val
            if ratio < 0.85 or ratio > 1.15:
                continue  # Skip this scenario - unrealistic
        filtered_scenarios.append(s)

    # Remove score from output and return top 4
    for s in filtered_scenarios:
        s.pop('_score', None)

    return filtered_scenarios[:4]


def generate_rivalry_analysis(team_name, rival_name):
    """Generate head-to-head analysis against rival team."""
    if rival_name not in teams:
        return None

    team = teams[team_name]
    rival = teams[rival_name]

    # Calculate total values
    my_value = sum(calc_player_value(p) for p in team.players)
    rival_value = sum(calc_player_value(p) for p in rival.players)

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
    my_top = sorted([(p, calc_player_value(p)) for p in team.players], key=lambda x: x[1], reverse=True)[:3]
    rival_top = sorted([(p, calc_player_value(p)) for p in rival.players], key=lambda x: x[1], reverse=True)[:3]

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


def calculate_championship_score(team_name, power_rank, total_teams, players_with_value, my_ranks):
    """Calculate raw championship score (unnormalized) based on multiple factors.

    Enhanced calculation incorporating:
    - Smooth power rank curve (not tiered)
    - Roster depth bonus (players 11-20)
    - Multi-elite player scaling
    - Category dominance weighting (#1 > #2-3)
    - Draft position factor
    - Prospect upside bonus

    Returns a raw score that should be normalized across all teams.
    """
    import math

    # 1. SMOOTH POWER RANK CURVE
    # Uses exponential decay: top teams get significantly higher scores
    score = 30 * math.exp(-0.18 * (power_rank - 1))

    # 2. CATEGORY DOMINANCE (enhanced weighting)
    for cat, rank in my_ranks.items():
        if rank == 1:
            score += 4  # Dominant in category
        elif rank <= 3:
            score += 2  # Strong in category
        elif rank >= 10:
            score -= 4  # Major weakness
        elif rank >= 9:
            score -= 2  # Weakness

    # 3. ROSTER DEPTH AND ELITE TALENT
    if players_with_value:
        # Multi-elite bonus: each player with value 80+ adds to championship score
        elite_count = len([v for p, v in players_with_value if v >= 80])
        superstar_count = len([v for p, v in players_with_value if v >= 100])

        # Scaling bonus: 1 elite = +2, 2 = +5, 3 = +8, 4+ = +12
        if elite_count >= 4:
            score += 12
        elif elite_count == 3:
            score += 8
        elif elite_count == 2:
            score += 5
        elif elite_count == 1:
            score += 2

        # Superstar bonus (85+ value players are difference makers)
        score += superstar_count * 3

        # Depth bonus: quality players 11-20 (value > 30)
        if len(players_with_value) >= 20:
            depth_players = len([v for p, v in players_with_value[10:20] if v >= 30])
            score += depth_players * 0.5

        # Age factor (smoother than before)
        avg_top_10_age = sum(p.age for p, v in players_with_value[:10]) / min(10, len(players_with_value))
        if avg_top_10_age <= 25:
            score += 4  # Very young core
        elif avg_top_10_age <= 27:
            score += 2  # Young core
        elif avg_top_10_age >= 32:
            score -= 4  # Aging core
        elif avg_top_10_age >= 30:
            score -= 2  # Older core

        # 4. PROSPECT UPSIDE BONUS
        top_prospects = len([p for p, v in players_with_value
                           if p.is_prospect and p.prospect_rank and p.prospect_rank <= 25])
        if top_prospects >= 3:
            score += 4  # Loaded with elite prospects
        elif top_prospects >= 2:
            score += 2
        elif top_prospects >= 1:
            score += 1

    # 5. DRAFT POSITION FACTOR
    draft_pick = draft_order_config.get(team_name, 0)
    if draft_pick == 1:
        score += 3  # #1 overall pick
    elif draft_pick <= 3:
        score += 2  # Top 3 pick
    elif draft_pick <= 5:
        score += 1  # Lottery pick

    # Minimum score of 1 to ensure every team has some chance
    return max(1, score)


# Cache for normalized championship odds (recalculated when teams change)
_championship_odds_cache = {}
_championship_odds_cache_key = None


def get_normalized_championship_odds():
    """Calculate championship odds for all teams, normalized to sum to 100%.

    Returns a dict of {team_name: probability} where all probabilities sum to 100.
    """
    global _championship_odds_cache, _championship_odds_cache_key

    # Create cache key based on team count (simple invalidation)
    cache_key = len(teams)
    if cache_key == _championship_odds_cache_key and _championship_odds_cache:
        return _championship_odds_cache

    # Get rankings and category data
    team_cats, rankings = calculate_league_category_rankings()
    _, power_rankings, _ = get_team_rankings()

    # Calculate raw scores for all teams
    raw_scores = {}
    for team_name, team in teams.items():
        players_with_value = [(p, calc_player_value(p)) for p in team.players]
        players_with_value.sort(key=lambda x: x[1], reverse=True)
        power_rank = power_rankings.get(team_name, len(teams))
        my_ranks = rankings.get(team_name, {})

        raw_scores[team_name] = calculate_championship_score(
            team_name, power_rank, len(teams), players_with_value, my_ranks
        )

    # Normalize to 100%
    total_score = sum(raw_scores.values())
    if total_score > 0:
        normalized = {name: round((score / total_score) * 100, 1) for name, score in raw_scores.items()}
    else:
        # Fallback: equal odds
        equal_odds = round(100 / len(teams), 1)
        normalized = {name: equal_odds for name in teams.keys()}

    # Cache results
    _championship_odds_cache = normalized
    _championship_odds_cache_key = cache_key

    return normalized


def get_team_championship_odds(team_name):
    """Get normalized championship odds for a specific team."""
    odds = get_normalized_championship_odds()
    return odds.get(team_name, 0)


def calculate_risk_assessment(players_with_value):
    """Calculate risk factors for the roster and return risk heat map data."""
    risks = {
        'age_cliff': [],      # Players 32+ with significant value
        'injury_prone': [],   # Players with injury history (approximated)
        'regression': [],     # Players potentially due for regression
        'prospect_bust': [],  # High-value prospects that could bust
    }

    for p, v in players_with_value[:20]:
        # Age cliff risk
        if p.age >= 32 and v >= 40:
            urgency = 'HIGH' if p.age >= 34 else 'MEDIUM'
            risks['age_cliff'].append({
                'name': p.name,
                'age': p.age,
                'value': v,
                'urgency': urgency,
                'note': f"Value will decline - consider selling within 1-2 years"
            })
        elif p.age >= 30 and v >= 50:
            risks['age_cliff'].append({
                'name': p.name,
                'age': p.age,
                'value': v,
                'urgency': 'LOW',
                'note': f"Monitor for decline signals"
            })

        # Prospect bust risk
        if p.is_prospect and p.prospect_rank:
            if p.prospect_rank <= 25 and v >= 50:
                risks['prospect_bust'].append({
                    'name': p.name,
                    'rank': p.prospect_rank,
                    'value': v,
                    'urgency': 'MEDIUM',
                    'note': f"Top prospect - high value but MLB unproven"
                })

    # Calculate overall risk score
    high_risks = len([r for cat in risks.values() for r in cat if r.get('urgency') == 'HIGH'])
    medium_risks = len([r for cat in risks.values() for r in cat if r.get('urgency') == 'MEDIUM'])
    low_risks = len([r for cat in risks.values() for r in cat if r.get('urgency') == 'LOW'])

    risk_score = high_risks * 3 + medium_risks * 2 + low_risks
    if risk_score >= 8:
        overall_risk = 'HIGH'
    elif risk_score >= 4:
        overall_risk = 'MEDIUM'
    else:
        overall_risk = 'LOW'

    return risks, overall_risk, risk_score


def generate_team_analysis(team_name, team, players_with_value=None, power_rank=None, total_teams=12):
    """
    Generate consolidated, personalized GM-level analysis for each team.
    Organized into 5 core sections: GM Overview, Roster Snapshot, Category Report, Trade Center, Outlook.
    """
    import random

    # ============ DATA SETUP ============
    if players_with_value is None:
        players_with_value = [(p, calc_player_value(p)) for p in team.players]
        players_with_value.sort(key=lambda x: x[1], reverse=True)

    if power_rank is None:
        _, power_rankings, _ = get_team_rankings()
        power_rank = power_rankings.get(team_name, 0)

    gm = get_assistant_gm(team_name)
    philosophy = gm.get('philosophy', 'balanced')
    total_value = sum(v for _, v in players_with_value)

    # Demographics
    ages = [p.age for p in team.players if p.age > 0]
    avg_age = sum(ages) / len(ages) if ages else 0
    young_players = [(p, v) for p, v in players_with_value if p.age <= 25 and p.age > 0]
    prime_players = [(p, v) for p, v in players_with_value if 26 <= p.age <= 30]
    veteran_players = [(p, v) for p, v in players_with_value if p.age > 30]
    prospects = [p for p in team.players if p.is_prospect]

    young_value = sum(v for _, v in young_players)
    prime_value = sum(v for _, v in prime_players)
    vet_value = sum(v for _, v in veteran_players)

    # Categories
    team_cats, rankings = calculate_league_category_rankings()
    my_ranks = rankings.get(team_name, {})
    cat_strengths = sorted([(cat, rank) for cat, rank in my_ranks.items() if rank <= 4], key=lambda x: x[1])
    cat_weaknesses = sorted([(cat, rank) for cat, rank in my_ranks.items() if rank >= 9], key=lambda x: -x[1])

    # Hitters vs Pitchers
    hitters = [(p, v) for p, v in players_with_value if p.name in HITTER_PROJECTIONS]
    starters = [(p, v) for p, v in players_with_value if p.name in PITCHER_PROJECTIONS]
    relievers = [(p, v) for p, v in players_with_value if p.name in RELIEVER_PROJECTIONS]
    hitter_value = sum(v for _, v in hitters)
    pitcher_value = sum(v for _, v in starters) + sum(v for _, v in relievers)

    # Position depth
    pos_counts = {'C': 0, '1B': 0, '2B': 0, 'SS': 0, '3B': 0, 'OF': 0, 'SP': 0, 'RP': 0}
    for p, _ in players_with_value:
        pos_str = (p.position or '').upper()
        for pos in pos_str.replace('/', ',').split(','):
            pos = pos.strip()
            if pos in ['LF', 'CF', 'RF']: pos = 'OF'
            if pos in pos_counts: pos_counts[pos] += 1
    thin_positions = [pos for pos, count in pos_counts.items() if count <= 2 and count > 0]
    deep_positions = [pos for pos, count in pos_counts.items() if count >= 5]

    # Championship probability (normalized across all teams to sum to 100%)
    champ_prob = get_team_championship_odds(team_name)

    # Risk assessment
    risks, overall_risk, risk_score = calculate_risk_assessment(players_with_value)

    # Identity colors
    identity_colors = {
        'dynasty_champion': '#ffd700', 'championship_closer': '#ff6b6b', 'smart_contender': '#4ade80',
        'all_in_buyer': '#f59e0b', 'loaded_and_ready': '#00d4ff', 'bargain_hunter': '#a78bfa',
        'rising_powerhouse': '#34d399', 'crossroads_decision': '#fbbf24', 'reluctant_dealer': '#fb923c',
        'analytical_rebuilder': '#60a5fa', 'desperate_accumulator': '#f87171', 'prospect_rich_rebuilder': '#22d3ee'
    }
    identity_color = identity_colors.get(philosophy, '#00d4ff')

    analysis_parts = []

    # ════════════════════════════════════════════════════════════════════
    # SECTION 1: GM OVERVIEW (Header + Identity + Strategy + Bottom Line merged)
    # ════════════════════════════════════════════════════════════════════
    catchphrase = random.choice(gm['catchphrases'])
    team_identity = gm.get('team_identity', 'COMPETITOR')
    owner_name = gm.get('owner', 'Unknown')

    overview = f"<div style='background: linear-gradient(135deg, rgba(0,212,255,0.15), rgba(255,215,0,0.08)); padding: 20px; border-radius: 12px; border-left: 4px solid {identity_color};'>"
    overview += f"<div style='display: flex; align-items: center; gap: 12px; margin-bottom: 12px;'>"
    overview += f"<div style='width: 48px; height: 48px; background: linear-gradient(135deg, {identity_color}, #1a1a2e); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: bold; color: #fff;'>{gm['name'][0]}</div>"
    overview += f"<div>"
    overview += f"<div style='font-size: 18px; font-weight: bold; color: {identity_color};'>{gm['name']}</div>"
    overview += f"<div style='font-size: 12px; color: #888;'>{gm['title']} • Owner: {owner_name}</div>"
    overview += f"</div></div>"

    # Identity + Power rank + Championship odds
    champ_color = '#4ade80' if champ_prob >= 15 else '#fbbf24' if champ_prob >= 8 else '#888'
    overview += f"<div style='font-size: 16px; margin-bottom: 8px;'><span style='color:{identity_color}'><b>{team_identity}</b></span> • "
    overview += f"<span style='color:#ffd700'>#{power_rank}</span> of {total_teams} • {total_value:.0f} pts • "
    overview += f"<span style='color:{champ_color}'>🏆 {champ_prob}% title odds</span></div>"

    # Dynamic catchphrase based on team situation
    dynamic_catchphrases = []
    if power_rank == 1:
        dynamic_catchphrases = ["The throne is ours. Now we defend it.", "At the top, everyone's gunning for us.", "#1 and we're not done building."]
    elif power_rank <= 3 and champ_prob >= 15:
        dynamic_catchphrases = ["Title contender. Time to close the deal.", "We're in the hunt. One move away.", "Championship window is WIDE open."]
    elif power_rank <= 6 and overall_risk == 'HIGH':
        dynamic_catchphrases = ["Good team, but risks are mounting.", "Need to address the red flags.", "Time to de-risk while staying competitive."]
    elif power_rank >= 10:
        dynamic_catchphrases = ["Rebuild mode. Every asset has a price.", "Playing the long game now.", "Stockpiling for the future."]
    elif len(cat_weaknesses) >= 3:
        dynamic_catchphrases = ["Too many holes to fill. Focus on 1-2.", "Category balance is killing us.", "Trade strength for weakness coverage."]
    else:
        dynamic_catchphrases = gm.get('catchphrases', [catchphrase])

    dynamic_catchphrase = random.choice(dynamic_catchphrases) if dynamic_catchphrases else catchphrase
    overview += f"<div style='font-style: italic; color: #ccc; margin-bottom: 12px;'>\"{dynamic_catchphrase}\"</div>"

    # Philosophy summary (condensed bottom line) - also dynamic based on situation
    base_summaries = {
        'dynasty_champion': "We're the team to beat. Force others to overpay for even a conversation.",
        'championship_closer': "The gap to a title? Close it. Every move is about winning NOW.",
        'all_in_buyer': "Window is NOW. Every prospect is currency. Make it happen.",
        'smart_contender': "Calculate every angle. Find market inefficiencies. Trust the process.",
        'loaded_and_ready': "Best of both worlds. We dictate terms in every negotiation.",
        'bargain_hunter': "Creativity over capital. Hunt value in the margins.",
        'rising_powerhouse': "The future is ours. Protect the foundation, patience builds dynasties.",
        'crossroads_decision': "Decision time. The middle is quicksand — pick a direction and commit.",
        'reluctant_dealer': "Time to act. Every week we wait costs us value.",
        'analytical_rebuilder': "Zero emotion, maximum return. Sell veterans at peak value.",
        'desperate_accumulator': "Cast wide nets. Quantity now, sort for quality later.",
        'prospect_rich_rebuilder': "These prospects ARE the plan. Guard the treasure fiercely.",
    }

    # Add situational context to summary
    summary = base_summaries.get(philosophy, 'Make strategic moves based on roster fit.')
    if champ_prob >= 20:
        summary += f" <span style='color:#4ade80'>Legit title threat.</span>"
    elif overall_risk == 'HIGH' and power_rank <= 6:
        summary += f" <span style='color:#fbbf24'>Watch the age cliff.</span>"
    elif len(risks['age_cliff']) >= 3:
        summary += f" <span style='color:#fb923c'>Multiple assets declining.</span>"

    overview += f"<div style='color: #aaa;'>{summary}</div>"
    overview += "</div>"
    analysis_parts.append(overview)

    # ════════════════════════════════════════════════════════════════════
    # SECTION 2: ROSTER SNAPSHOT (Core assets + Demographics + Depth condensed)
    # ════════════════════════════════════════════════════════════════════
    roster = "<b style='font-size: 14px;'>📊 ROSTER SNAPSHOT</b><br>"

    # Top 5 players with philosophy-aware outlook for MVP
    if players_with_value:
        mvp = players_with_value[0]
        SELLING = ['analytical_rebuilder', 'desperate_accumulator', 'reluctant_dealer']
        BUYING = ['championship_closer', 'all_in_buyer', 'dynasty_champion', 'loaded_and_ready']

        if philosophy in SELLING and mvp[0].age >= 28:
            mvp_tag = "<span style='color:#fb923c'>SELL HIGH</span>"
        elif philosophy in BUYING:
            mvp_tag = "<span style='color:#4ade80'>CORNERSTONE</span>"
        else:
            mvp_tag = "<span style='color:#ffd700'>FRANCHISE</span>"

        roster += f"<b>Core 5:</b> "
        core_names = []
        for i, (p, v) in enumerate(players_with_value[:5]):
            age_color = '#4ade80' if p.age <= 26 else '#fbbf24' if p.age <= 30 else '#fb923c'
            if i == 0:
                core_names.append(f"<b>{p.name}</b> ({v:.0f}, <span style='color:{age_color}'>{p.age}</span>) {mvp_tag}")
            else:
                core_names.append(f"{p.name} ({v:.0f}, <span style='color:{age_color}'>{p.age}</span>)")
        roster += " • ".join(core_names) + "<br>"

    # Condensed demographics - just counts, no raw values
    balance_note = "balanced" if abs(hitter_value - pitcher_value) < pitcher_value * 0.3 else ("bat-heavy" if hitter_value > pitcher_value else "arm-heavy")
    roster += f"<b>Build:</b> Avg age {avg_age:.1f} | {len(young_players)} young, {len(prime_players)} prime, {len(veteran_players)} vet | {balance_note}<br>"

    # Position depth - cleaner format without redundant labels
    depth_parts = []
    if thin_positions:
        depth_parts.append(f"<span style='color:#f87171'>{', '.join(thin_positions[:2])} thin</span>")
    if deep_positions:
        depth_parts.append(f"<span style='color:#4ade80'>{', '.join(deep_positions[:2])} deep</span>")
    if depth_parts:
        roster += f"<b>Depth:</b> {' | '.join(depth_parts)}<br>"
    else:
        roster += "<b>Depth:</b> Balanced across positions<br>"

    # Risk heat map
    risk_color = '#f87171' if overall_risk == 'HIGH' else '#fbbf24' if overall_risk == 'MEDIUM' else '#4ade80'
    roster += f"<b>Risk Level:</b> <span style='color:{risk_color}'>{overall_risk}</span>"
    if risks['age_cliff']:
        age_cliff_names = [r['name'] for r in risks['age_cliff'][:2]]
        roster += f" — <span style='color:#fb923c'>Age cliff: {', '.join(age_cliff_names)}</span>"
    if risks['prospect_bust']:
        prospect_names = [r['name'] for r in risks['prospect_bust'][:2]]
        roster += f" — <span style='color:#fbbf24'>Unproven: {', '.join(prospect_names)}</span>"

    analysis_parts.append(roster)

    # ════════════════════════════════════════════════════════════════════
    # SECTION 3: CATEGORY REPORT (Strengths/weaknesses + Risk factors)
    # ════════════════════════════════════════════════════════════════════
    cats = "<b style='font-size: 14px;'>📈 CATEGORY REPORT</b><br>"

    if cat_strengths:
        strength_list = ", ".join([f"<span style='color:#4ade80'>{cat} (#{rank})</span>" for cat, rank in cat_strengths[:4]])
        cats += f"<b>Strengths:</b> {strength_list}<br>"
    if cat_weaknesses:
        weakness_list = ", ".join([f"<span style='color:#f87171'>{cat} (#{rank})</span>" for cat, rank in cat_weaknesses[:4]])
        cats += f"<b>Weaknesses:</b> {weakness_list}<br>"

    # GM Priority categories
    preferred_cats = gm.get('preferred_categories', [])
    if preferred_cats:
        priority_status = []
        for pcat in preferred_cats:
            prank = my_ranks.get(pcat, 12)
            if prank <= 4:
                priority_status.append(f"<span style='color:#4ade80'>{pcat} ✓</span>")
            elif prank >= 9:
                priority_status.append(f"<span style='color:#f87171'>{pcat} ✗</span>")
            else:
                priority_status.append(f"<span style='color:#fbbf24'>{pcat} ⚠</span>")
        cats += f"<b>Priority Cats:</b> {', '.join(priority_status)}<br>"

    # Risk factors
    sell_candidates = [f"{p.name} ({p.age})" for p, v in players_with_value[:15] if p.age >= 33 and v >= 30]
    if sell_candidates:
        cats += f"<span style='color:#fbbf24'><b>Aging assets:</b> {', '.join(sell_candidates[:3])}</span>"
    else:
        cats += "<span style='color:#4ade80'>No major risk factors</span>"

    analysis_parts.append(cats)

    # ════════════════════════════════════════════════════════════════════
    # SECTION 4: TRADE CENTER (Scenarios + Partner Intel + Opportunities)
    # ════════════════════════════════════════════════════════════════════
    trade = f"<b style='font-size: 14px;'>🔄 TRADE CENTER</b><br>"

    # Get GM philosophy parameters for Trade Center display
    philosophy_obj = GM_PHILOSOPHIES.get(philosophy, GM_PHILOSOPHIES['balanced'])
    min_value_threshold = philosophy_obj.get('min_value_threshold', 40)
    trade_initiation_style = philosophy_obj.get('trade_initiation_style', 'opportunistic')

    # Initiation style indicator with color coding
    STYLE_DISPLAY = {
        'aggressive': ('<span style="color:#f87171">AGGRESSIVE</span>', 'Actively pursuing deals'),
        'reactive': ('<span style="color:#60a5fa">REACTIVE</span>', 'Waiting for offers'),
        'opportunistic': ('<span style="color:#4ade80">OPPORTUNISTIC</span>', 'Striking when value appears')
    }
    style_badge, style_desc = STYLE_DISPLAY.get(trade_initiation_style, ('BALANCED', 'Standard approach'))
    trade += f"<b>Trade Style:</b> {style_badge} | Min Value: {min_value_threshold}+<br>"

    # Determine category needs (weaknesses ranked 8+ are priorities)
    category_needs = []
    for cat, rank in sorted(my_ranks.items(), key=lambda x: -x[1]):
        if rank >= 8:
            category_needs.append(f"{cat} (#{rank})")
    if category_needs:
        trade += f"<b>Category Needs:</b> {', '.join(category_needs[:3])}<br>"

    # Trade scenarios
    gm_scenarios = generate_gm_trade_scenarios(team_name, team)
    if gm_scenarios:
        SCENARIO_INTROS = {
            'dynasty_champion': "Few offers deserve our time. But consider:",
            'championship_closer': "Here's my hit list:",
            'all_in_buyer': "Time to empty the clip:",
            'smart_contender': "The data points to:",
            'loaded_and_ready': "From a position of strength:",
            'bargain_hunter': "Hunting value in the margins:",
            'rising_powerhouse': "Protecting the foundation, but consider:",
            'crossroads_decision': "Decision time. Paths forward:",
            'reluctant_dealer': "Fine. Here's what makes sense:",
            'analytical_rebuilder': "The algorithm says:",
            'desperate_accumulator': "Everything's available:",
            'prospect_rich_rebuilder': "Only these deals fit the plan:",
        }
        trade += f"<i>{SCENARIO_INTROS.get(philosophy, 'Consider these moves:')}</i><br>"

        for s in gm_scenarios[:2]:  # Limit to top 2 scenarios
            # Clean format: Title: Target (value) ← Offer
            trade += f"<b>{s['title']}</b>: {s['target']} ({s['target_value']:.0f}) ← {s['offer']}<br>"

    # Trade partner intel (condensed)
    partner_intel = get_gm_trade_partner_intelligence(team_name)
    if partner_intel and partner_intel['ideal_partners']:
        trade += "<b>Best Trade Partners:</b> "
        partner_names = []
        for p in partner_intel['ideal_partners'][:3]:
            ptype = "SELLER" if p['philosophy'] in ['desperate_accumulator', 'analytical_rebuilder', 'reluctant_dealer'] else "BUYER" if p['philosophy'] in ['championship_closer', 'all_in_buyer'] else ""
            partner_names.append(f"{p['team']} ({ptype})" if ptype else p['team'])
        trade += ", ".join(partner_names) + "<br>"

    # Market opportunities (condensed)
    alerts = get_buy_low_sell_high_alerts(team_name, team)
    if alerts['sell_high']:
        sell_names = [a['name'] for a in alerts['sell_high'][:3]]
        trade += f"<span style='color:#fbbf24'><b>Sell Window:</b> {', '.join(sell_names)}</span><br>"
    if alerts['buy_low']:
        buy_names = [f"{a['name']} ({a['team']})" for a in alerts['buy_low'][:3]]
        trade += f"<span style='color:#4ade80'><b>Buy Targets:</b> {', '.join(buy_names)}</span>"

    analysis_parts.append(trade)

    # ════════════════════════════════════════════════════════════════════
    # SECTION 5: OUTLOOK (Farm + Draft + Rivalry)
    # ════════════════════════════════════════════════════════════════════
    outlook = f"<b style='font-size: 14px;'>🔮 OUTLOOK</b><br>"

    # Farm system (condensed)
    top_100_prospects = sorted([p for p in prospects if p.prospect_rank and p.prospect_rank <= 100], key=lambda x: x.prospect_rank)
    all_ranked = sorted([p for p in prospects if p.prospect_rank], key=lambda x: x.prospect_rank)

    # Calculate farm grade
    farm_points = sum(
        25 if p.prospect_rank <= 10 else 15 if p.prospect_rank <= 25 else 8 if p.prospect_rank <= 50 else 4 if p.prospect_rank <= 100 else 2 if p.prospect_rank <= 150 else 1
        for p in prospects if p.prospect_rank
    )

    # Calculate farm rank
    all_farm_points = []
    for other_team_name, other_team in teams.items():
        other_points = sum(
            25 if p.prospect_rank <= 10 else 15 if p.prospect_rank <= 25 else 8 if p.prospect_rank <= 50 else 4 if p.prospect_rank <= 100 else 2 if p.prospect_rank <= 150 else 1
            for p in other_team.players if p.is_prospect and p.prospect_rank
        )
        all_farm_points.append((other_team_name, other_points))
    all_farm_points.sort(key=lambda x: -x[1])
    farm_rank = next((i + 1 for i, (name, _) in enumerate(all_farm_points) if name == team_name), 12)

    farm_grades = {1: 'A+', 2: 'A', 3: 'B+', 4: 'B+', 5: 'B', 6: 'B', 7: 'C+', 8: 'C+', 9: 'C', 10: 'C', 11: 'D', 12: 'D'}
    farm_grade = farm_grades.get(farm_rank, 'C')
    farm_color = '#4ade80' if farm_rank <= 3 else '#fbbf24' if farm_rank <= 8 else '#f87171'

    outlook += f"<b>Farm:</b> <span style='color:{farm_color}'>{farm_grade}</span> (#{farm_rank} of 12)"
    if top_100_prospects:
        top_names = [f"#{p.prospect_rank} {p.name}" for p in top_100_prospects[:2]]
        outlook += f" — {', '.join(top_names)}"
    elif all_ranked:
        outlook += f" — Best: #{all_ranked[0].prospect_rank} {all_ranked[0].name}"
    outlook += "<br>"

    # Draft (condensed)
    if draft_order_config and team_name in draft_order_config:
        pick_num = draft_order_config[team_name]
        draft_focus = []
        if thin_positions:
            draft_focus.append(f"need {thin_positions[0]}")
        if cat_weaknesses:
            draft_focus.append(f"target {cat_weaknesses[0][0]}")
        focus_text = " | ".join(draft_focus) if draft_focus else "best available"
        outlook += f"<b>2026 Draft:</b> Pick #{pick_num} — {focus_text}<br>"

    # Rivalry (expanded with H2H, records, and category edges)
    rival_name = TEAM_RIVALRIES.get(team_name)
    if rival_name:
        rivalry = generate_rivalry_analysis(team_name, rival_name)
        if rivalry:
            h2h = rivalry.get('my_h2h_record', 'N/A')
            my_record = rivalry.get('my_2025_record', 'N/A')
            rival_record = rivalry.get('rival_2025_record', 'N/A')

            # Color based on H2H record
            if h2h and h2h != 'N/A' and '-' in h2h:
                h2h_parts = h2h.split('-')
                wins = int(h2h_parts[0]) if h2h_parts[0].isdigit() else 0
                losses = int(h2h_parts[1].split('-')[0]) if len(h2h_parts) > 1 and h2h_parts[1].split('-')[0].isdigit() else 0
                h2h_color = "#4ade80" if wins > losses else "#f87171" if losses > wins else "#fbbf24"
            else:
                h2h_color = "#888"

            outlook += f"<b>Rivalry vs {rival_name}:</b> <span style='color:{h2h_color}'>H2H: {h2h}</span>"

            # Add season records if available
            if my_record != 'N/A' and rival_record != 'N/A':
                outlook += f" | You: {my_record} vs Them: {rival_record}"

            # Add category advantages/disadvantages
            advantages = rivalry.get('advantages', [])
            disadvantages = rivalry.get('disadvantages', [])
            if advantages:
                outlook += f"<br>&nbsp;&nbsp;<span style='color:#4ade80'>Cat edges: {', '.join(advantages[:3])}</span>"
            if disadvantages:
                outlook += f" | <span style='color:#f87171'>They lead: {', '.join(disadvantages[:3])}</span>"

    analysis_parts.append(outlook)

    # ════════════════════════════════════════════════════════════════════
    # GM SIGNATURE
    # ════════════════════════════════════════════════════════════════════
    signature = f"<div style='margin-top: 16px; padding-top: 12px; border-top: 1px solid rgba(255,215,0,0.2); text-align: right; font-style: italic; color: #666;'>— {gm['name']}, {gm['title']}</div>"
    analysis_parts.append(signature)

    return "<br><br>".join(analysis_parts)


# ============ END OF REFACTORED generate_team_analysis ============
# Old code removed during consolidation into 5 core sections


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
                value = calc_player_value(p)
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


def generate_personalized_trade_advice(player, value, projections):
    """Generate personalized trade advice based on player attributes."""

    # Position scarcity analysis
    premium_positions = {'C': 'Catcher', 'SS': 'Shortstop', 'SP': 'Starting Pitcher'}
    scarce_positions = {'2B': 'Second Base', '3B': 'Third Base', 'RP': 'Reliever'}

    pos_premium = None
    for pos, name in premium_positions.items():
        if pos in player.position:
            pos_premium = f"Premium {name} scarcity adds significant trade value."
            break
    if not pos_premium:
        for pos, name in scarce_positions.items():
            if pos in player.position:
                pos_premium = f"{name} depth is valuable in category leagues."
                break

    # Age context
    age = player.age if player.age else 25
    if age <= 21:
        age_note = f"At just {age}, has elite development runway - value will likely increase."
    elif age <= 24:
        age_note = f"At {age}, prime prospect age with years of team control ahead."
    elif age <= 26:
        age_note = f"At {age}, entering prime years - peak value window opening."
    elif age <= 29:
        age_note = f"At {age}, in prime production years - maximize value now."
    elif age <= 32:
        age_note = f"At {age}, still productive but decline approaching - consider selling high."
    else:
        age_note = f"At {age}, in decline phase - trade value diminishing yearly."

    # === PROSPECT ADVICE ===
    if player.is_prospect and player.prospect_rank:
        rank = player.prospect_rank

        if rank <= 3:
            tier = f"🌟 GENERATIONAL TALENT (#{rank})"
            advice = "Franchise-altering prospect. Untouchable in most scenarios - only move for a proven superstar (100+ value) or league-winning package."
        elif rank <= 5:
            tier = f"🌟 ELITE TOP-5 (#{rank})"
            advice = "Cornerstone prospect with star ceiling. Demand elite proven talent (85+ value) or multiple top-50 prospects."
        elif rank <= 10:
            tier = f"⭐ TOP-10 PROSPECT (#{rank})"
            advice = "High-floor, high-ceiling asset. Worth a proven starter (70+ value) or 2-3 quality pieces in return."
        elif rank <= 15:
            tier = f"⭐ TOP-15 PROSPECT (#{rank})"
            advice = "Strong dynasty asset with starter upside. Can headline trades for established players (60+ value)."
        elif rank <= 25:
            tier = f"💎 TOP-25 PROSPECT (#{rank})"
            advice = "Quality prospect with solid floor. Good centerpiece for trades targeting 50-65 value players."
        elif rank <= 40:
            tier = f"TOP-40 PROSPECT (#{rank})"
            advice = "Above-average prospect. Can be primary piece in trades for proven contributors (40-55 value)."
        elif rank <= 50:
            tier = f"TOP-50 PROSPECT (#{rank})"
            advice = "Solid prospect with starter potential. Useful trade chip - pair with another piece to upgrade."
        elif rank <= 75:
            tier = f"TOP-75 PROSPECT (#{rank})"
            advice = "Decent upside but higher bust risk. Good secondary piece in trade packages."
        elif rank <= 100:
            tier = f"TOP-100 PROSPECT (#{rank})"
            advice = "Fringe prospect with some upside. Use as sweetener in deals or hold as depth."
        elif rank <= 150:
            tier = f"RANKED PROSPECT (#{rank})"
            advice = "Lottery ticket - minimal standalone value but can tip trade balances."
        else:
            tier = f"DEEP PROSPECT (#{rank})"
            advice = "Long-shot upside only. Roster stash if space allows, minimal trade value."

        # Combine elements
        parts = [f"{tier} - {advice}"]
        if pos_premium:
            parts.append(pos_premium)
        parts.append(age_note)
        return " ".join(parts)

    # === PROVEN PLAYER ADVICE ===
    else:
        if value >= 100:
            tier = f"🏆 SUPERSTAR ({value:.0f} pts)"
            advice = "Elite foundational piece. Only trade for another superstar or overwhelming prospect haul (3+ top-25 prospects)."
        elif value >= 80:
            tier = f"🏆 ELITE ASSET ({value:.0f} pts)"
            advice = "Cornerstone player. Demand elite return - top-10 prospect plus quality pieces, or proven star."
        elif value >= 60:
            tier = f"⭐ STAR ({value:.0f} pts)"
            advice = "Key roster piece. Can fetch a top-25 prospect or 2 solid contributors in return."
        elif value >= 40:
            tier = f"⭐ SOLID STARTER ({value:.0f} pts)"
            advice = "Reliable contributor. Good trade chip for top-50 prospect or roster upgrade."
        elif value >= 40:
            tier = f"SOLID CONTRIBUTOR ({value:.0f} pts)"
            advice = "Useful roster piece. Package with picks/prospects to upgrade, or trade for younger upside."
        elif value >= 25:
            tier = f"DEPTH PLAYER ({value:.0f} pts)"
            advice = "Roster filler with some value. Include in packages to balance trades."
        else:
            tier = f"FRINGE ROSTER ({value:.0f} pts)"
            advice = "Minimal trade value. Replacement-level player - use as throw-in only."

        # Combine elements
        parts = [f"{tier} - {advice}"]
        if pos_premium:
            parts.append(pos_premium)
        parts.append(age_note)
        return " ".join(parts)


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

        # Build trade advice based on prospect tier
        if is_fa_prospect and fa_prospect_rank:
            if fa_prospect_rank <= 10:
                trade_advice = f"🚨 ELITE TOP-10 PROSPECT (#{fa_prospect_rank}) available! Immediate high-priority pickup - future cornerstone player."
            elif fa_prospect_rank <= 25:
                trade_advice = f"⭐ TOP-25 PROSPECT (#{fa_prospect_rank}) on waivers! High-priority dynasty pickup with star upside."
            elif fa_prospect_rank <= 50:
                trade_advice = f"TOP-50 PROSPECT (#{fa_prospect_rank}) available. Strong dynasty asset - should be rostered in all leagues."
            elif fa_prospect_rank <= 100:
                trade_advice = f"Top-100 prospect (#{fa_prospect_rank}). Solid dynasty stash with upside - worth a roster spot."
            elif fa_prospect_rank <= 150:
                trade_advice = f"Ranked prospect (#{fa_prospect_rank}). Speculative add if you have roster space."
            else:
                trade_advice = f"Fringe prospect (#{fa_prospect_rank}). Deep league stash only - monitor development."
        else:
            trade_advice = f"Free agent with {fa_data['roster_pct']:.0f}% roster rate. Fantrax rank #{fa_data['rank']}. Consider adding if he fills a need."

        # Calculate overall dynasty rank (including rostered + this FA)
        all_player_values = []
        for team_name, team in teams.items():
            for p in team.players:
                pval = calc_player_value(p)
                all_player_values.append((p.name, pval))
        # Add this free agent
        all_player_values.append((fa_data['name'], fa_data['dynasty_value']))
        all_player_values.sort(key=lambda x: -x[1])
        fa_overall_rank = None
        for i, (pname, pval) in enumerate(all_player_values, 1):
            if pname == fa_data['name']:
                fa_overall_rank = i
                break

        return jsonify({
            "name": fa_data['name'],
            "position": fa_data['position'],
            "mlb_team": fa_data['mlb_team'],
            "fantasy_team": "Free Agent",
            "age": fa_data['age'],
            "dynasty_value": fa_data['dynasty_value'],
            "overall_rank": fa_overall_rank,
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

    value = calc_player_value(player)

    # Get projections
    projections = {}
    projections_estimated = False
    # Check if player is a two-way player (in both hitter and pitcher projections)
    in_hitter_proj = player.name in HITTER_PROJECTIONS
    in_pitcher_proj = player.name in PITCHER_PROJECTIONS
    in_reliever_proj = player.name in RELIEVER_PROJECTIONS

    if in_hitter_proj and in_pitcher_proj:
        # Two-way player like Ohtani - combine both projections
        projections = dict(HITTER_PROJECTIONS[player.name])
        pitcher_proj = PITCHER_PROJECTIONS[player.name]
        # Add pitching stats with prefix to distinguish
        projections['P_IP'] = pitcher_proj.get('IP', 0)
        projections['P_K'] = pitcher_proj.get('K', 0)
        projections['P_ERA'] = pitcher_proj.get('ERA', 0)
        projections['P_WHIP'] = pitcher_proj.get('WHIP', 0)
        projections['P_W'] = pitcher_proj.get('W', 0)
        projections['P_QS'] = pitcher_proj.get('QS', 0)
    elif in_hitter_proj:
        projections = dict(HITTER_PROJECTIONS[player.name])
    elif in_pitcher_proj:
        projections = dict(PITCHER_PROJECTIONS[player.name])
    elif in_reliever_proj:
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

    # Trade advice - personalized based on rank, position, and age
    trade_advice = generate_personalized_trade_advice(player, value, projections)

    # Get actual stats and fantasy points
    actual_stats = player_actual_stats.get(player.name)
    fantasy_pts = player_fantasy_points.get(player.name, {})

    # Calculate overall dynasty rank
    all_player_values = []
    for team_name, team in teams.items():
        for p in team.players:
            pval = calc_player_value(p)
            all_player_values.append((p.name, pval))
    all_player_values.sort(key=lambda x: -x[1])
    overall_rank = None
    for i, (pname, pval) in enumerate(all_player_values, 1):
        if pname == player.name:
            overall_rank = i
            break

    return jsonify({
        "name": player.name,
        "position": player.position,
        "team": player.mlb_team,
        "mlb_team": player.mlb_team,
        "fantasy_team": fantasy_team,
        "age": player.age,
        "dynasty_value": round(value, 1),
        "overall_rank": overall_rank,
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
    value_a_sends = sum(calc_player_value(p) for p in found_players_a)
    value_b_sends = sum(calc_player_value(p) for p in found_players_b)

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
    # Category impacts shown as badges below, not in text
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
            smallest = min(found_players_a, key=lambda p: calc_player_value(p))
            smallest_val = calc_player_value(smallest)
            if smallest_val <= gap * 1.5 and smallest_val >= gap * 0.5:
                counter_offer_suggestions.append({
                    'for_team': loser,
                    'suggestion': f"Remove {smallest.name} ({smallest_val:.0f}) from your side to reduce what you're giving up",
                    'value_add': smallest_val
                })
        elif loser == team_b and found_players_b:
            smallest = min(found_players_b, key=lambda p: calc_player_value(p))
            smallest_val = calc_player_value(smallest)
            if smallest_val <= gap * 1.5 and smallest_val >= gap * 0.5:
                counter_offer_suggestions.append({
                    'for_team': loser,
                    'suggestion': f"Remove {smallest.name} ({smallest_val:.0f}) from your side to reduce what you're giving up",
                    'value_add': smallest_val
                })

        # Find a player from winner's team that could be added
        winner_team = teams.get(winner)
        if winner_team:
            candidates = [(p, calc_player_value(p)) for p in winner_team.players
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
        "value": round(calc_player_value(p), 1),
        "is_prospect": p.is_prospect,
        "prospect_rank": p.prospect_rank if p.is_prospect else None
    } for p in found_players_a]

    players_b_details = [{
        "name": p.name,
        "position": p.position,
        "age": p.age,
        "value": round(calc_player_value(p), 1),
        "is_prospect": p.is_prospect,
        "prospect_rank": p.prospect_rank if p.is_prospect else None
    } for p in found_players_b]

    # Calculate trade impact simulation (category ranking and championship odds changes)
    trade_impact = None
    if found_players_a or found_players_b:  # Only simulate if there are players involved
        try:
            trade_impact = simulate_trade_impact(team_a, team_b, found_players_a, found_players_b)
        except Exception as e:
            print(f"Error simulating trade impact: {e}")

    return jsonify({
        "verdict": verdict,
        "value_a_sends": round(value_a_sends, 1),
        "value_b_sends": round(value_b_sends, 1),
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
        },
        "trade_impact": trade_impact
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

    players_with_value = [(p, calc_player_value(p)) for p in team.players]
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
            pval = calc_player_value(p)
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
        best_received = max(you_receive, key=lambda p: calc_player_value(p))
        best_sent = max(you_send, key=lambda p: calc_player_value(p))
        val_received = calc_player_value(best_received)
        val_sent = calc_player_value(best_sent)
        if best_received.age <= 26 and best_sent.age >= 30 and val_received >= val_sent * 0.9:
            score += 10
            reasons.append(f"Getting younger at similar value")

    # Positional upgrade detection
    for p_recv in you_receive:
        recv_pos = p_recv.position.upper() if p_recv.position else ''
        recv_val = calc_player_value(p_recv)
        for p_send in you_send:
            send_pos = p_send.position.upper() if p_send.position else ''
            send_val = calc_player_value(p_send)
            # Same position, getting upgrade
            if recv_pos == send_pos and recv_val > send_val * 1.15:
                score += 5
                reasons.append(f"Positional upgrade at {recv_pos}")
                break

    # POSITIONAL SURPLUS PENALTY - Penalize acquiring players at positions we're already deep in
    my_team = teams.get(my_team_name)
    if my_team:
        my_pos_counts = {}
        for p in my_team.players:
            pos = p.position.split('/')[0].split(',')[0].upper() if p.position else 'UTIL'
            if pos in ['LF', 'CF', 'RF']:
                pos = 'OF'
            my_pos_counts[pos] = my_pos_counts.get(pos, 0) + 1

        for p_recv in you_receive:
            recv_pos = p_recv.position.split('/')[0].split(',')[0].upper() if p_recv.position else 'UTIL'
            if recv_pos in ['LF', 'CF', 'RF']:
                recv_pos = 'OF'

            current_count = my_pos_counts.get(recv_pos, 0)
            if current_count >= 5:
                # Already stacked at this position - significant penalty
                score -= 25
                reasons.append(f"Already deep at {recv_pos} ({current_count})")
            elif current_count >= 4:
                # Surplus at this position - moderate penalty
                score -= 15
                reasons.append(f"Position surplus at {recv_pos} ({current_count})")

    return score, reasons


@app.route('/suggest')
def get_suggestions():
    try:
        my_team = request.args.get('my_team')
        target_team = request.args.get('target_team')
        trade_type = request.args.get('trade_type', 'any')
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 8))
        # Quick filter parameters
        filter_position = request.args.get('filter_position', '')
        filter_min_fit = int(request.args.get('filter_min_fit', 0))
        filter_max_diff = int(request.args.get('filter_max_diff', 100))

        if not my_team or my_team not in teams:
            return jsonify({"error": "Invalid team specified"}), 400

        suggestions = []
        my_players = [(p, calc_player_value(p)) for p in teams[my_team].players]
        my_players.sort(key=lambda x: x[1], reverse=True)
        # EXPANDED: Include stars (85+) and depth pieces (10+) for more trade options
        my_tradeable = [(p, v) for p, v in my_players if v >= 10][:15]

        # Get my team's needs for insights
        my_cats, my_pos, my_window = calculate_team_needs(my_team)

        # If targeting all teams, we need to be more selective to avoid timeout
        all_teams_mode = not target_team
        target_teams = [target_team] if target_team else [t for t in teams.keys() if t != my_team]

        for other_team in target_teams:
            if other_team == my_team:
                continue

            their_players = [(p, calc_player_value(p)) for p in teams[other_team].players]
            their_players.sort(key=lambda x: x[1], reverse=True)
            # Use fewer players when searching all teams
            max_tradeable = 10 if all_teams_mode else 15
            # EXPANDED: Include all valuable players, not just mid-tier (was 15-85)
            their_tradeable = [(p, v) for p, v in their_players if v >= 10][:max_tradeable]

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
                                "you_send_positions": [my_p.position],
                                "you_receive_positions": [their_p.position],
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
                                    "you_send_positions": [my_p1.position, my_p2.position],
                                    "you_receive_positions": [their_p.position],
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
                                        "you_send_positions": [my_p1.position, my_p2.position],
                                        "you_receive_positions": [their_p1.position, their_p2.position],
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

        # Apply quick filters
        if filter_position:
            suggestions = [s for s in suggestions if any(filter_position in pos for pos in s.get('you_receive_positions', []))]
        if filter_min_fit > 0:
            suggestions = [s for s in suggestions if s['fit_score'] >= filter_min_fit]
        if filter_max_diff < 100:
            suggestions = [s for s in suggestions if s['value_diff'] <= filter_max_diff]

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
            """Detect undervalued gems and breakout candidates with enhanced logic."""
            special_tags = []
            name = fa['name']
            age = fa['age']
            roster_pct = fa['roster_pct']
            dynasty_value = fa['dynasty_value']

            if not fa_proj:
                fa_proj = {}

            hr = fa_proj.get('HR', 0)
            sb = fa_proj.get('SB', 0)
            rbi = fa_proj.get('RBI', 0)
            r = fa_proj.get('R', 0)
            avg = fa_proj.get('AVG', 0)
            k = fa_proj.get('K', 0)
            qs = fa_proj.get('QS', 0)
            era = fa_proj.get('ERA', 5.0)
            whip = fa_proj.get('WHIP', 1.5)
            sv = fa_proj.get('SV', 0)
            hld = fa_proj.get('HD', 0)

            # 1. BREAKOUT CANDIDATE - young with projections exceeding ownership
            if age <= 26 and roster_pct < 50:
                if hr >= 20 or sb >= 20 or k >= 150:
                    special_tags.append("🚀 Breakout Candidate")
                elif hr >= 15 and sb >= 10:  # Power/speed developing
                    special_tags.append("📈 Breakout Watch")

            # 2. POWER/SPEED COMBO - rare and valuable
            if hr >= 15 and sb >= 15:
                special_tags.append("⚡ Power/Speed")
            elif hr >= 20 and sb >= 10:
                special_tags.append("💪 Power+ Speed")
            elif sb >= 25 and hr >= 8:
                special_tags.append("🏃 Speed+ Power")

            # 3. UNDERVALUED GEM - projections don't match dynasty value
            if dynasty_value < 40:
                if hr >= 25 or rbi >= 80 or k >= 180 or (k >= 100 and era <= 3.50):
                    special_tags.append("💎 Undervalued Gem")

            # 4. RATIO STABILIZER - pitchers with elite ratios
            is_pitcher = 'SP' in fa['position'].upper() or 'RP' in fa['position'].upper()
            if is_pitcher:
                if era <= 3.20 and whip <= 1.10:
                    special_tags.append("📊 Elite Ratios")
                elif era <= 3.50 and whip <= 1.15:
                    special_tags.append("📊 Ratio Stabilizer")

            # 5. MULTI-CATEGORY CONTRIBUTOR - helps in 3+ categories
            cat_contributions = 0
            if hr >= 15:
                cat_contributions += 1
            if sb >= 12:
                cat_contributions += 1
            if rbi >= 70:
                cat_contributions += 1
            if r >= 70:
                cat_contributions += 1
            if avg >= 0.280:
                cat_contributions += 1
            if k >= 120:
                cat_contributions += 1
            if sv + hld >= 15:
                cat_contributions += 1

            if cat_contributions >= 4:
                special_tags.append("🎯 Multi-Cat Elite")
            elif cat_contributions >= 3:
                special_tags.append("📋 Multi-Cat Contributor")

            # 6. STREAMING CANDIDATE - pitcher with solid matchups potential
            if 'SP' in fa['position'].upper() and roster_pct < 40:
                if era <= 4.00 and whip <= 1.25:
                    special_tags.append("📅 Streaming Option")

            # 7. CLOSER WATCH - RP who could get saves
            if 'RP' in fa['position'].upper():
                if sv >= 20:
                    special_tags.append("🔒 Established Closer")
                elif sv >= 10:
                    special_tags.append("👀 Closer Potential")
                elif hld >= 20:
                    special_tags.append("🛡️ Elite Setup")

            # 8. DYNASTY SLEEPER - young with upside, under the radar
            if age <= 24 and dynasty_value >= 30 and roster_pct < 30:
                special_tags.append("😴 Dynasty Sleeper")

            # 9. INJURY COMEBACK - low roster % on formerly good player (approximation)
            if age >= 27 and age <= 32 and roster_pct < 25 and dynasty_value >= 25:
                # Likely returning from injury if low ownership on decent value player
                special_tags.append("🏥 Comeback Watch")

            # 10. WORKHORSE - SP with high innings and QS potential
            if 'SP' in fa['position'].upper():
                ip = fa_proj.get('IP', 0)
                if ip >= 180 and qs >= 18:
                    special_tags.append("🐴 Workhorse")
                elif ip >= 160 and qs >= 14:
                    special_tags.append("📈 Innings Eater")

            return special_tags[:4]  # Limit to 4 tags max

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

        # Get GM philosophy for philosophy-aware recommendations
        gm = get_assistant_gm(team_name)
        philosophy = gm.get('philosophy', 'balanced')
        gm_preferred_cats = gm.get('preferred_categories', [])

        # Philosophy-based tendencies
        YOUTH_PHILOSOPHIES = ['rising_powerhouse', 'prospect_rich_rebuilder', 'analytical_rebuilder', 'dynasty_champion']
        PRODUCTION_PHILOSOPHIES = ['championship_closer', 'all_in_buyer', 'loaded_and_ready', 'win_now']
        VALUE_PHILOSOPHIES = ['bargain_hunter', 'smart_contender', 'value_seeker']

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
            pval = calc_player_value(p)
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

            # ============ GM PHILOSOPHY-BASED ADJUSTMENTS ============
            # Youth-focused GMs get bonus for young players
            if philosophy in YOUTH_PHILOSOPHIES:
                if age <= 24:
                    score += 15
                    if "Young asset" not in str(reasons):
                        reasons.append("Aligns with youth focus")
                elif age <= 26:
                    score += 8
                elif age >= 30:
                    score -= 10  # Penalty for older players

            # Production-focused GMs want proven contributors
            if philosophy in PRODUCTION_PHILOSOPHIES:
                if fa['roster_pct'] >= 50 and age >= 26:
                    score += 12
                    if "proven" not in str(reasons).lower():
                        reasons.append("Proven producer")
                # Prospects are less valuable to win-now GMs
                if fa.get('is_prospect') and age <= 22:
                    score -= 8

            # Value-focused GMs look for inefficiencies
            if philosophy in VALUE_PHILOSOPHIES:
                # Low roster % but high value = inefficiency
                if fa['roster_pct'] <= 40 and base_score >= 40:
                    score += 15
                    reasons.append("Underowned value")
                # Breakout candidates
                if age <= 27 and base_score >= 35 and fa['roster_pct'] <= 50:
                    score += 8
                    if "breakout" not in str(reasons).lower():
                        reasons.append("Breakout candidate")

            # GM's preferred categories get bonus
            for pref_cat in gm_preferred_cats:
                if pref_cat in str(cats_addressed):
                    score += 10
                    reasons.append(f"Fits {pref_cat} priority")
                    break

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

        # Build AI summary for the team with philosophy awareness
        philosophy_names = {
            'dynasty_champion': 'dynasty champion',
            'championship_closer': 'championship closer',
            'all_in_buyer': 'all-in buyer',
            'smart_contender': 'smart contender',
            'loaded_and_ready': 'loaded contender',
            'bargain_hunter': 'value hunter',
            'rising_powerhouse': 'rising powerhouse',
            'crossroads_decision': 'crossroads team',
            'reluctant_dealer': 'reluctant dealer',
            'analytical_rebuilder': 'analytical rebuilder',
            'desperate_accumulator': 'aggressive accumulator',
            'prospect_rich_rebuilder': 'prospect-focused rebuilder',
        }
        phil_name = philosophy_names.get(philosophy, team_window)

        ai_summary = f"As a {phil_name}"
        if philosophy in YOUTH_PHILOSOPHIES:
            ai_summary += ", prioritize young talent with upside"
        elif philosophy in PRODUCTION_PHILOSOPHIES:
            ai_summary += ", target proven producers who contribute now"
        elif philosophy in VALUE_PHILOSOPHIES:
            ai_summary += ", look for undervalued assets and inefficiencies"

        if worst_cats:
            ai_summary += f". Address {', '.join(worst_cats[:2])}"
        if critical_needs:
            ai_summary += f". Fill {', '.join(critical_needs)} depth"
        if aging_positions and philosophy in YOUTH_PHILOSOPHIES:
            ai_summary += f". Replace aging {', '.join(aging_positions)}"

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


@app.route('/top-players')
def get_top_players():
    """Get the top 50 players in the league by dynasty value."""
    all_players = []

    # Collect all players from all teams
    for team_name, team in teams.items():
        for player in team.players:
            value = calc_player_value(player)
            all_players.append({
                "name": player.name,
                "position": player.position,
                "mlb_team": player.mlb_team,
                "fantasy_team": team_name,
                "age": player.age,
                "value": round(value, 1),
                "is_prospect": player.is_prospect,
                "prospect_rank": player.prospect_rank if player.is_prospect else None
            })

    # Sort by value descending and take top 50
    all_players.sort(key=lambda x: -x["value"])
    top_players = all_players[:50]

    # Add rank
    for i, player in enumerate(top_players, 1):
        player["rank"] = i

    return jsonify({"players": top_players})


@app.route('/top-pitchers')
def get_top_pitchers():
    """Get the top 25 pitchers in the league by dynasty value."""
    all_pitchers = []
    pitcher_positions = {'SP', 'RP', 'P'}

    # Collect all pitchers from all teams
    for team_name, team in teams.items():
        for player in team.players:
            # Check if player is a pitcher
            player_positions = set(player.position.replace('/', ',').replace(' ', '').split(','))
            if player_positions & pitcher_positions:
                value = calc_player_value(player)
                all_pitchers.append({
                    "name": player.name,
                    "position": player.position,
                    "mlb_team": player.mlb_team,
                    "fantasy_team": team_name,
                    "age": player.age,
                    "value": round(value, 1),
                    "is_prospect": player.is_prospect,
                    "prospect_rank": player.prospect_rank if player.is_prospect else None
                })

    # Sort by value descending and take top 25
    all_pitchers.sort(key=lambda x: -x["value"])
    top_pitchers = all_pitchers[:25]

    # Add rank
    for i, player in enumerate(top_pitchers, 1):
        player["rank"] = i

    return jsonify({"players": top_pitchers})


@app.route('/top-hitters')
def get_top_hitters():
    """Get the top 25 hitters in the league by dynasty value."""
    all_hitters = []
    pitcher_positions = {'SP', 'RP', 'P'}

    # Collect all hitters from all teams
    for team_name, team in teams.items():
        for player in team.players:
            # Check if player is NOT a pitcher (is a hitter)
            player_positions = set(player.position.replace('/', ',').replace(' ', '').split(','))
            if not (player_positions & pitcher_positions):
                value = calc_player_value(player)
                all_hitters.append({
                    "name": player.name,
                    "position": player.position,
                    "mlb_team": player.mlb_team,
                    "fantasy_team": team_name,
                    "age": player.age,
                    "value": round(value, 1),
                    "is_prospect": player.is_prospect,
                    "prospect_rank": player.prospect_rank if player.is_prospect else None
                })

    # Sort by value descending and take top 25
    all_hitters.sort(key=lambda x: -x["value"])
    top_hitters = all_hitters[:25]

    # Add rank
    for i, player in enumerate(top_hitters, 1):
        player["rank"] = i

    return jsonify({"players": top_hitters})


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
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

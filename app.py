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

                <div class="arrow">⇄</div>

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
            <p style="color: #888; font-size: 0.85rem; margin-bottom: 15px;">Showing all ranked prospects (top 200) on team rosters and available as free agents. <span style="color: #00ff88;">FA</span> = Available to pick up!</p>
            <div id="prospects-loading" class="loading">Loading prospects...</div>
            <div id="prospects-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px;"></div>
        </div>

        <div id="suggest-panel" class="panel">
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
                        const faBadge = isFreeAgent ? '<span style="background: #00ff88; color: #000; font-size: 0.65rem; padding: 2px 6px; border-radius: 8px; margin-left: 8px; font-weight: bold;">FA</span>' : '';
                        const ownerStyle = isFreeAgent ? 'color: #00ff88; font-weight: bold;' : 'color: #c0c0e0;';
                        return `
                        <div onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')" style="background: ${tierBg}; border-radius: 12px; padding: 18px; border-left: 4px solid ${tierColor}; cursor: pointer; transition: all 0.3s ease; border: 1px solid rgba(${p.rank <= 10 ? '255,215,0' : p.rank <= 25 ? '0,212,255' : p.rank <= 50 ? '123,44,191' : '74,144,217'}, 0.3);" onmouseover="this.style.transform='translateY(-3px)';this.style.boxShadow='0 8px 25px rgba(0,0,0,0.3)';" onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='none';">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                                <span style="font-weight: bold; font-size: 1.05rem; color: ${tierColor};">#${p.rank} ${p.name}${faBadge}</span>
                                <span style="color: #00d4ff; font-weight: bold; font-size: 1.1rem;">${p.value.toFixed(1)}</span>
                            </div>
                            <div style="font-size: 0.9rem; color: #a0a0c0;">
                                ${p.position} | Age ${p.age} | ${p.mlb_team}
                            </div>
                            <div style="font-size: 0.85rem; color: #7070a0; margin-top: 8px;">
                                ${isFreeAgent ? '<span style="' + ownerStyle + '">AVAILABLE - Free Agent</span>' : 'Owner: <span style="' + ownerStyle + '">' + p.fantasy_team + '</span>'}
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
            const selects = ['teamASelect', 'teamBSelect', 'suggestTeamSelect', 'suggestTargetSelect', 'faTeamSelect'];
            selects.forEach(id => {
                const select = document.getElementById(id);
                if (!select) return;
                const currentValue = select.value;
                const isTarget = id === 'suggestTargetSelect';
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
                        <div style="padding: 14px 24px; background: ${data.recommendation?.includes('✓') ? 'linear-gradient(135deg, #0a2a15, #153d20)' : data.recommendation?.includes('⚠') ? 'linear-gradient(135deg, #2a2510, #3d3515)' : 'linear-gradient(135deg, #2a1015, #3d1520)'}; border-radius: 12px; font-weight: 600; text-align: center; font-size: 1.05rem; border: 1px solid ${data.recommendation?.includes('✓') ? 'rgba(0, 255, 136, 0.3)' : data.recommendation?.includes('⚠') ? 'rgba(255, 190, 11, 0.3)' : 'rgba(255, 77, 109, 0.3)'};">
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
                        </div>
                        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 10px; border: 1px solid #3a3a5a;">
                            <h4 style="color: #00d4ff; margin: 0 0 15px 0; font-size: 0.9rem;">PITCHING CATEGORIES</h4>
                            ${cats.K ? renderCategoryBar('K', cats.K.value, cats.K.rank, numTeams) : ''}
                            ${cats.ERA ? renderCategoryBar('ERA', cats.ERA.value, cats.ERA.rank, numTeams, true) : ''}
                            ${cats.WHIP ? renderCategoryBar('WHIP', cats.WHIP.value, cats.WHIP.rank, numTeams, true) : ''}
                            ${cats['SV+HLD'] ? renderCategoryBar('SV+HLD', cats['SV+HLD'].value, cats['SV+HLD'].rank, numTeams) : ''}
                        </div>
                    </div>

                    <!-- Strengths & Weaknesses Summary -->
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 25px;">
                        <div style="background: rgba(74, 222, 128, 0.1); padding: 12px; border-radius: 8px; border: 1px solid rgba(74, 222, 128, 0.3);">
                            <div style="color: #4ade80; font-size: 0.85rem; font-weight: bold; margin-bottom: 5px;">💪 STRENGTHS</div>
                            <div style="color: #e4e4e4;">${[...(data.hitting_strengths || []), ...(data.pitching_strengths || [])].join(', ') || 'None'}</div>
                        </div>
                        <div style="background: rgba(248, 113, 113, 0.1); padding: 12px; border-radius: 8px; border: 1px solid rgba(248, 113, 113, 0.3);">
                            <div style="color: #f87171; font-size: 0.85rem; font-weight: bold; margin-bottom: 5px;">📉 WEAKNESSES</div>
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

                    <h4 style="color: #ffd700; margin-bottom: 15px;">Top Players</h4>
                    ${(data.top_players || data.players.slice(0, 20)).map(p => `
                        <div class="player-card" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">
                            <div>
                                <div class="name player-link">${p.name}</div>
                                <div style="color: #888; font-size: 0.85rem;">${p.position} | Age ${p.age}${p.proj ? ` | ${p.proj}` : ''}</div>
                            </div>
                            <div class="value">${p.value.toFixed(1)}</div>
                        </div>
                    `).join('')}

                    ${(data.prospects && data.prospects.length > 0) ? `
                        <h4 style="color: #ffd700; margin: 25px 0 15px;">Prospects (${data.prospects.length})</h4>
                        ${data.prospects.map(p => `
                            <div class="player-card" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">
                                <div>
                                    <div class="name player-link">${p.name}</div>
                                    <div style="color: #888; font-size: 0.8rem;">${p.position || ''} | Age ${p.age || '?'}</div>
                                </div>
                                <div class="value" style="color: #4ade80;">#${p.rank}</div>
                            </div>
                        `).join('')}
                    ` : ''}
                `;
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
                    fa = {
                        'id': row.get('ID', ''),
                        'name': fa_name,
                        'mlb_team': row.get('Team', ''),
                        'position': row.get('Position', ''),
                        'rank': rank,
                        'age': age,
                        'score': score,
                        'roster_pct': ros,
                        'adp': float(row.get('ADP', 999) or 999),
                    }

                    # Check if FA is a ranked prospect
                    prospect_rank = PROSPECT_RANKINGS.get(fa_name)
                    fa['is_prospect'] = prospect_rank is not None and prospect_rank <= 200
                    fa['prospect_rank'] = prospect_rank if fa['is_prospect'] else None

                    # Debug: Log FA prospects found
                    if fa['is_prospect']:
                        print(f"FA PROSPECT FOUND: {fa_name} - Rank #{prospect_rank}")

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
        print(f"Loaded {len(FREE_AGENTS)} free agents")
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

        # Apply prospect floors (matching the main dynasty calculator)
        # These ensure a Top 20 FA prospect isn't valued at 25 just because they have no Fantrax score
        if prospect_rank <= 10:
            # Elite prospects: floor 85, multiplier 1.20
            value = max(preliminary_value, 85) * 1.20
        elif prospect_rank <= 25:
            # Top 25: floor 75, multiplier 1.15
            value = max(preliminary_value, 75) * 1.15
        elif prospect_rank <= 50:
            # Top 50: floor 68, multiplier 1.10
            value = max(preliminary_value, 68) * 1.10
        elif prospect_rank <= 100:
            # Top 100: floor 50, multiplier 1.05
            value = max(preliminary_value, 50) * 1.05
        elif prospect_rank <= 150:
            # Rank 101-150: floor 40
            value = max(preliminary_value, 40)
        elif prospect_rank <= 200:
            # Rank 151-200: floor 32
            value = max(preliminary_value, 32)
        else:
            # Rank 201+: floor 25
            value = max(preliminary_value, 25)

        return round(value, 1)

    # Non-prospect FA value calculation
    value = (base_value * age_mult) + rank_bonus + ros_bonus
    return round(value, 1)


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

    # Load rankings from consensus CSV files
    csv_rankings = {}
    prospect_files = glob.glob(os.path.join(script_dir, 'Consensus*Ranks*.csv'))

    for csv_file in prospect_files:
        try:
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Name', '').strip()
                    avg_rank_str = row.get('Avg Rank', '')

                    if not name or not avg_rank_str:
                        continue

                    try:
                        avg_rank = float(avg_rank_str)
                        # Keep the better (lower) rank if player appears in multiple CSV files
                        if name not in csv_rankings or avg_rank < csv_rankings[name]:
                            csv_rankings[name] = avg_rank
                    except (ValueError, TypeError):
                        continue

            print(f"Loaded prospect rankings from {os.path.basename(csv_file)}")
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

    # Clear and rebuild PROSPECT_RANKINGS with sequential ranks
    PROSPECT_RANKINGS.clear()
    for new_rank, (name, _) in enumerate(sorted_prospects, start=1):
        PROSPECT_RANKINGS[name] = new_rank

    top_200_count = len([r for r in PROSPECT_RANKINGS.values() if r <= 200])
    print(f"Prospect rankings merged and re-ranked: {len(PROSPECT_RANKINGS)} total ({top_200_count} in top 200)")

    # Debug: Print top 10 prospects to verify correct ordering
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

                # Get prospect rank from PROSPECT_RANKINGS (averaged from JSON + CSV)
                prospect_rank = PROSPECT_RANKINGS.get(player_name)
                # Only mark as prospect for display if rank <= 200
                # (But they're still in PROSPECT_RANKINGS for value capping purposes)
                is_prospect = prospect_rank is not None and prospect_rank <= 200

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

                # Check if player is in prospect rankings
                prospect_rank = PROSPECT_RANKINGS.get(player_name)
                # Only mark as prospect for display if rank <= 200
                is_prospect = prospect_rank is not None and prospect_rank <= 200

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
    """Get all prospects across all teams AND free agents, sorted by rank."""
    all_prospects = []

    # Get prospects from team rosters
    for team_name, team in teams.items():
        for player in team.players:
            if player.is_prospect and player.prospect_rank and player.prospect_rank <= 200:
                value = calculator.calculate_player_value(player)
                all_prospects.append({
                    "name": player.name,
                    "rank": player.prospect_rank,
                    "position": player.position,
                    "age": player.age,
                    "mlb_team": player.mlb_team,
                    "fantasy_team": team_name,
                    "value": round(value, 1),
                    "is_free_agent": False
                })

    # Get prospects from free agents
    for fa in FREE_AGENTS:
        if fa.get('is_prospect') and fa.get('prospect_rank') and fa['prospect_rank'] <= 200:
            all_prospects.append({
                "name": fa['name'],
                "rank": fa['prospect_rank'],
                "position": fa['position'],
                "age": fa['age'],
                "mlb_team": fa['mlb_team'],
                "fantasy_team": "Free Agent",
                "value": fa['dynasty_value'],
                "is_free_agent": True
            })

    # Sort by rank
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
        k = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in t.players)
        sv_hld = sum((RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) + RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0)) for p in t.players)
        ip = sum(PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) for p in t.players)

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
            'HR': hr, 'SB': sb, 'RBI': rbi, 'R': runs, 'K': k, 'SV+HLD': sv_hld,
            'ERA': era, 'WHIP': whip, 'AVG': avg, 'OPS': ops, 'IP': ip
        }

    # Calculate rankings for each category
    rankings = {}
    for t_name in teams.keys():
        rankings[t_name] = {}

    for cat in ['HR', 'SB', 'RBI', 'R', 'K', 'SV+HLD', 'AVG', 'OPS']:
        sorted_teams = sorted(team_cats.keys(), key=lambda x: team_cats[x][cat], reverse=True)
        for rank, t_name in enumerate(sorted_teams, 1):
            rankings[t_name][cat] = rank

    # ERA and WHIP - lower is better
    for cat in ['ERA', 'WHIP']:
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
        'K': {'value': my_cats.get('K', 0), 'rank': my_rankings.get('K', 0)},
        'ERA': {'value': round(my_cats.get('ERA', 4.50), 2), 'rank': my_rankings.get('ERA', 0)},
        'WHIP': {'value': round(my_cats.get('WHIP', 1.30), 2), 'rank': my_rankings.get('WHIP', 0)},
        'SV+HLD': {'value': my_cats.get('SV+HLD', 0), 'rank': my_rankings.get('SV+HLD', 0)},
    }

    # Calculate category strengths/weaknesses based on rankings
    hitting_strengths, hitting_weaknesses = [], []
    pitching_strengths, pitching_weaknesses = [], []

    top_third = num_teams // 3
    bottom_third = num_teams - top_third

    for cat in ['HR', 'SB', 'RBI', 'R', 'AVG', 'OPS']:
        rank = my_rankings.get(cat, num_teams)
        if rank <= top_third:
            hitting_strengths.append(cat)
        elif rank >= bottom_third:
            hitting_weaknesses.append(cat)

    for cat in ['K', 'ERA', 'WHIP', 'SV+HLD']:
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

    # Sort each position by value and keep top 5
    for pos in pos_depth:
        pos_depth[pos] = sorted(pos_depth[pos], key=lambda x: x['value'], reverse=True)[:5]

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


def generate_team_analysis(team_name, team, players_with_value=None, power_rank=None, total_teams=12):
    """Generate a comprehensive, personalized text analysis/description of a team."""
    if players_with_value is None:
        players_with_value = [(p, calculator.calculate_player_value(p)) for p in team.players]
        players_with_value.sort(key=lambda x: x[1], reverse=True)

    if power_rank is None:
        _, power_rankings, _ = get_team_rankings()
        power_rank = power_rankings.get(team_name, 0)

    analysis_parts = []

    # Calculate roster demographics
    ages = [p.age for p in team.players if p.age > 0]
    avg_age = sum(ages) / len(ages) if ages else 0
    young_players = len([a for a in ages if a <= 25])
    prime_players = len([a for a in ages if 26 <= a <= 30])
    veteran_players = len([a for a in ages if a > 30])
    prospects = [p for p in team.players if p.is_prospect]

    # Calculate team totals and category analysis
    total_hr = sum(HITTER_PROJECTIONS.get(p.name, {}).get('HR', 0) for p, _ in players_with_value)
    total_sb = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SB', 0) for p, _ in players_with_value)
    total_rbi = sum(HITTER_PROJECTIONS.get(p.name, {}).get('RBI', 0) for p, _ in players_with_value)
    total_k = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p, _ in players_with_value)
    total_sv_hld = sum((RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) + RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0)) for p, _ in players_with_value)

    # Identify strengths and weaknesses
    cat_strengths, cat_weaknesses = [], []
    if total_hr >= 220: cat_strengths.append("HR")
    elif total_hr < 160: cat_weaknesses.append("HR")
    if total_sb >= 120: cat_strengths.append("SB")
    elif total_sb < 70: cat_weaknesses.append("SB")
    if total_k >= 1300: cat_strengths.append("K")
    elif total_k < 900: cat_weaknesses.append("K")
    if total_sv_hld >= 70: cat_strengths.append("SV+HLD")
    elif total_sv_hld < 35: cat_weaknesses.append("SV+HLD")

    # Determine competitive window
    top_third = total_teams // 3
    bottom_third = total_teams - top_third
    is_old_roster = avg_age >= 28 or veteran_players > prime_players
    is_young_roster = avg_age <= 26 or len(prospects) >= 6

    if power_rank <= top_third:
        if is_young_roster:
            window = "dynasty"
            window_desc = f"{team_name} is a dynasty powerhouse with elite young talent and a championship window that extends for years"
        elif is_old_roster:
            window = "win-now"
            window_desc = f"{team_name} is in win-now mode - a veteran-laden contender that needs to push all chips to the middle"
        else:
            window = "contender"
            window_desc = f"{team_name} is a legitimate title contender with a balanced, competitive roster"
    elif power_rank >= bottom_third:
        if is_old_roster:
            window = "teardown"
            window_desc = f"{team_name} needs a full teardown - an aging roster with limited path to contention"
        elif is_young_roster:
            window = "rebuilding"
            window_desc = f"{team_name} is rebuilding the right way - stockpiling young talent for future success"
        else:
            window = "retooling"
            window_desc = f"{team_name} is stuck in the middle and needs to commit to a clear direction"
    else:
        if is_young_roster:
            window = "rising"
            window_desc = f"{team_name} is on the rise - young talent developing that could push into contention soon"
        elif is_old_roster:
            window = "declining"
            window_desc = f"{team_name} is trending downward - aging assets should be sold before values crater"
        else:
            window = "competitive"
            window_desc = f"{team_name} is competitive but not a frontrunner - needs a move or two to break through"

    analysis_parts.append(f"<b>🏆 TEAM IDENTITY:</b> {window_desc}. Currently ranked <span style='color:#ffd700'>#{power_rank}</span> of {total_teams}.")

    # Roster composition with character
    if young_players > veteran_players + 3:
        roster_vibe = "This is a youth movement in full swing"
    elif veteran_players > young_players + 3:
        roster_vibe = "Experience runs deep on this roster"
    elif prime_players >= young_players and prime_players >= veteran_players:
        roster_vibe = "The core is locked into their prime years"
    else:
        roster_vibe = "A balanced mix across all age groups"
    analysis_parts.append(f"<b>👥 ROSTER PROFILE:</b> {roster_vibe}. Average age {avg_age:.1f} with {young_players} young (≤25), {prime_players} prime (26-30), {veteran_players} veteran (31+).")

    # Cornerstone players with commentary
    top_3 = players_with_value[:3]
    if top_3:
        mvp = top_3[0]
        if mvp[0].age <= 25:
            mvp_note = "is the franchise cornerstone with elite upside"
        elif mvp[0].age <= 28:
            mvp_note = "is in his prime and driving this team"
        elif mvp[0].age <= 31:
            mvp_note = "remains the alpha but the clock is ticking"
        else:
            mvp_note = "is still producing but won't be forever"
        others = ", ".join([f"{p.name} ({v:.0f})" for p, v in top_3[1:3]])
        analysis_parts.append(f"<b>⭐ CORE ASSETS:</b> {mvp[0].name} ({mvp[1]:.0f}) {mvp_note}. Supported by {others}.")

    # Prospect pipeline
    if prospects:
        top_prospects = sorted([p for p in prospects if p.prospect_rank and p.prospect_rank <= 100], key=lambda x: x.prospect_rank)[:3]
        if top_prospects:
            top_p = top_prospects[0]
            if top_p.prospect_rank <= 20:
                farm_note = "An elite prospect anchors this farm system"
            elif top_p.prospect_rank <= 50:
                farm_note = "Quality prospect capital in the pipeline"
            else:
                farm_note = "Some upside brewing in the minors"
            prospect_list = ", ".join([f"{p.name} (#{p.prospect_rank})" for p in top_prospects])
            analysis_parts.append(f"<b>🌟 FARM SYSTEM:</b> {farm_note}. Top prospects: {prospect_list}.")
        elif len(prospects) > 3:
            analysis_parts.append(f"<b>🌟 FARM SYSTEM:</b> Quantity over quality - {len(prospects)} prospects but none cracking the top 100.")
    else:
        analysis_parts.append("<b>🌟 FARM SYSTEM:</b> Bare cupboard - no ranked prospects on the roster.")

    # Category outlook with specific analysis
    cat_text = f"<b>📊 CATEGORY OUTLOOK:</b> Projected {total_hr} HR, {total_sb} SB, {total_rbi} RBI, {total_k} K, {total_sv_hld} SV+HLD."
    if cat_strengths:
        cat_text += f" <span style='color:#4ade80'>Strong in {', '.join(cat_strengths)}</span>."
    if cat_weaknesses:
        cat_text += f" <span style='color:#f87171'>Needs help in {', '.join(cat_weaknesses)}</span>."
    analysis_parts.append(cat_text)

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
        analysis_parts.append(f"<b>⚠️ RISK FACTORS:</b> {' | '.join(risk_factors)}.")
    else:
        analysis_parts.append("<b>⚠️ RISK FACTORS:</b> Well-balanced roster with no major red flags.")

    # Personalized trade strategy
    strategy = "<b>💼 TRADE STRATEGY:</b> "
    if window == "dynasty":
        if cat_weaknesses:
            strategy += f"From a position of strength, target {cat_weaknesses[0]} help without sacrificing your young core. "
        strategy += "You can be patient - don't overpay to fill small gaps."
    elif window == "contender":
        if cat_weaknesses:
            strategy += f"Time for surgical strikes - overpay if needed to fix your {cat_weaknesses[0]} weakness. "
        strategy += "A key addition could be the difference between good and great."
    elif window == "win-now":
        strategy += "Go all-in NOW. Trade prospects and future picks for proven talent. "
        if sell_candidates:
            strategy += f"Your window is closing - maximize value from {sell_candidates[0].split(' (')[0]} while you can."
    elif window == "rising":
        strategy += "Protect your prospect capital but look for undervalued veterans to complement your young core. Be opportunistic but don't mortgage the future."
    elif window == "competitive":
        strategy += "At a crossroads - either make a splash to push into contention, or start selling veterans to reload. The worst move is standing pat."
    elif window == "declining":
        if sell_candidates:
            strategy += f"Time to sell. {sell_candidates[0].split(' (')[0]} and other vets still have value - move them for youth and picks. "
        strategy += "Every month you wait, asset values decline."
    elif window == "retooling":
        strategy += "Pick a lane. You're not good enough to compete and not bad enough to get top picks. Commit to rebuild or buy aggressively - the middle is death."
    elif window == "rebuilding":
        strategy += "Stay the course. Accumulate prospects, draft picks, and young upside. Any veteran over 28 with value should be on the block. Patience pays."
    elif window == "teardown":
        strategy += "Full liquidation mode. Every player over 28 must go. "
        if sell_candidates:
            strategy += f"Start with {sell_candidates[0].split(' (')[0]} - maximize return on your best tradeable assets."

    analysis_parts.append(strategy)

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

    depth_text = "<b>🔍 POSITIONAL DEPTH:</b> "
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
    bottom_line = "<b>📋 BOTTOM LINE:</b> "
    total_value = sum(v for _, v in players_with_value)
    if window in ['dynasty', 'contender', 'win-now']:
        if cat_weaknesses:
            bottom_line += f"A {window} team that should be aggressive acquiring {cat_weaknesses[0]} help. "
        else:
            bottom_line += f"An elite roster built to win. Protect your core and target marginal upgrades. "
        bottom_line += f"Total roster value: <span style='color:#ffd700'>{total_value:.0f} points</span>."
    elif window in ['rebuilding', 'rising']:
        bottom_line += f"The future is bright with {len(prospects)} prospects and {young_players} young players. "
        bottom_line += f"Be patient, accumulate assets, and let the talent develop. Value: {total_value:.0f} pts."
    elif window in ['teardown', 'declining']:
        if sell_candidates:
            bottom_line += f"Move {sell_candidates[0].split(' (')[0]} and other vets ASAP. "
        bottom_line += f"Every week you wait costs you draft capital. Time to accelerate the rebuild."
    else:
        bottom_line += f"Stuck in no-man's land with {total_value:.0f} points of value. "
        bottom_line += "Make a decisive move - buy in or sell out. The middle path leads nowhere."
    analysis_parts.append(bottom_line)

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
            trade_advice = f"🌟 TOP {fa_prospect_rank} PROSPECT available as free agent! High priority pickup for dynasty leagues."
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
        if abs(age_diff) >= 3:
            younger_team = team_b if age_diff > 0 else team_a
            older_team = team_a if age_diff > 0 else team_b
            age_analysis = f"{younger_team} gets younger assets (avg age: {min(avg_age_a_sends, avg_age_b_sends):.1f} vs {max(avg_age_a_sends, avg_age_b_sends):.1f}). "
        elif abs(age_diff) >= 1:
            age_analysis = f"Slight age advantage to {team_b if age_diff > 0 else team_a}. "

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
            'AVG': 0,
            'OPS': 0,
            # Pitching
            'K': sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in players),
            'ERA': 0,
            'WHIP': 0,
            'SV': sum(RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) for p in players),
            'HLD': sum(RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0) for p in players),
            'QS': sum(PITCHER_PROJECTIONS.get(p.name, {}).get('QS', 0) for p in players),
            'W': sum((PITCHER_PROJECTIONS.get(p.name, {}).get('W', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('W', 0)) for p in players),
            'IP': sum((PITCHER_PROJECTIONS.get(p.name, {}).get('IP', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('IP', 0)) for p in players),
        }
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
        stat_diffs[stat] = round(diff, 3) if stat in ['AVG', 'OPS', 'ERA', 'WHIP'] else int(diff)

    # Category impact analysis with more detail
    cat_impacts = []
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
    if abs(stat_diffs['K']) >= 30:
        winner = team_a if stat_diffs['K'] > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['K'])} K")
    if abs(stat_diffs['SV'] + stat_diffs['HLD']) >= 5:
        winner = team_a if (stat_diffs['SV'] + stat_diffs['HLD']) > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['SV'] + stat_diffs['HLD'])} SV+HLD")
    if abs(stat_diffs['QS']) >= 5:
        winner = team_a if stat_diffs['QS'] > 0 else team_b
        cat_impacts.append(f"{winner} gains {abs(stat_diffs['QS'])} QS")

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
        recommendation = "✓ Recommended for both teams"
    elif value_diff < 10:
        recommendation = f"✓ Acceptable for {winner}, decent for {loser}"
    elif value_diff < 20:
        recommendation = f"⚠ Good for {winner}, {loser} should seek more"
    else:
        recommendation = f"✗ {loser} should decline unless addressing urgent need"

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

    # Determine competitive window
    ages = [p.age for p in team.players if p.age > 0]
    avg_age = sum(ages) / len(ages) if ages else 27
    prospects = len([p for p in team.players if p.is_prospect])

    players_with_value = [(p, calculator.calculate_player_value(p)) for p in team.players]
    total_value = sum(v for _, v in players_with_value)

    # Determine window based on value and age profile
    if total_value >= 900 and avg_age <= 27:
        window = "dynasty"
    elif total_value >= 800:
        window = "contender" if avg_age <= 28 else "win-now"
    elif total_value >= 650:
        window = "rising" if avg_age <= 27 else "competitive"
    elif prospects >= 6 or avg_age <= 26:
        window = "rebuilding"
    else:
        window = "retooling"

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
        reasons.append(f"Good trade partners ({my_window} ↔ {their_window})")

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

                scored_fas.append({
                    **fa,
                    'fit_score': round(score, 1),
                    'reasons': reasons[:3]
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

        # Calculate detailed positional depth
        pos_depth = {}
        pos_quality = {}  # Track quality at each position
        team = teams[team_name]
        for p in team.players:
            pos = p.position.upper() if p.position else ''
            pval = calculator.calculate_player_value(p)
            for check_pos in ['C', '1B', '2B', 'SS', '3B', 'OF', 'SP', 'RP']:
                if check_pos in pos or (check_pos == 'OF' and any(x in pos for x in ['LF', 'CF', 'RF'])):
                    pos_depth[check_pos] = pos_depth.get(check_pos, 0) + 1
                    pos_quality[check_pos] = max(pos_quality.get(check_pos, 0), pval)

        positional_needs = [pos for pos in ['C', '1B', '2B', 'SS', '3B', 'OF', 'SP', 'RP']
                          if pos_depth.get(pos, 0) < 3]
        critical_needs = [pos for pos in ['C', '1B', '2B', 'SS', '3B', 'OF', 'SP', 'RP']
                        if pos_depth.get(pos, 0) < 2]

        # Enhanced scoring for team-specific recommendations
        scored_fas = []
        for fa in FREE_AGENTS:
            if position_filter and position_filter not in fa['position']:
                continue

            base_score = fa['dynasty_value']
            score = base_score
            reasons = []

            fa_pos = fa['position'].upper()
            is_hitter = any(pos in fa_pos for pos in ['C', '1B', '2B', 'SS', '3B', 'OF', 'LF', 'CF', 'RF', 'DH'])
            is_sp = 'SP' in fa_pos
            is_rp = 'RP' in fa_pos

            # Get FA's projected stats from our projections if available
            fa_proj = HITTER_PROJECTIONS.get(fa['name'], {}) or PITCHER_PROJECTIONS.get(fa['name'], {}) or RELIEVER_PROJECTIONS.get(fa['name'], {})

            # Category need bonus with specific stat matching
            if is_hitter:
                hr_proj = fa_proj.get('HR', 0)
                sb_proj = fa_proj.get('SB', 0)
                rbi_proj = fa_proj.get('RBI', 0)

                if 'HR' in weaknesses and hr_proj >= 20:
                    score += 20
                    reasons.append(f"+{hr_proj} HR projected")
                elif 'HR' in weaknesses and hr_proj >= 15:
                    score += 12
                    reasons.append(f"HR help ({hr_proj} proj)")

                if 'SB' in weaknesses and sb_proj >= 15:
                    score += 20
                    reasons.append(f"+{sb_proj} SB projected")
                elif 'SB' in weaknesses and sb_proj >= 10:
                    score += 12
                    reasons.append(f"Speed boost ({sb_proj} SB)")

                if 'RBI' in weaknesses and rbi_proj >= 70:
                    score += 15
                    reasons.append(f"Run producer ({rbi_proj} RBI)")

            if is_sp:
                k_proj = fa_proj.get('K', 0)
                era_proj = fa_proj.get('ERA', 5.0)

                if 'K' in weaknesses and k_proj >= 150:
                    score += 20
                    reasons.append(f"Strikeout arm ({k_proj} K)")
                elif 'K' in weaknesses and k_proj >= 100:
                    score += 12
                    reasons.append(f"K upside ({k_proj} proj)")

                if 'ERA' in weaknesses and era_proj <= 3.50:
                    score += 15
                    reasons.append(f"Elite ratios ({era_proj} ERA)")

            if is_rp:
                sv_proj = fa_proj.get('SV', 0)
                hld_proj = fa_proj.get('HD', 0)

                if 'SV+HLD' in weaknesses:
                    if sv_proj >= 20:
                        score += 25
                        reasons.append(f"Closer ({sv_proj} SV proj)")
                    elif sv_proj >= 10 or hld_proj >= 15:
                        score += 15
                        reasons.append(f"Reliever help")

            # Critical positional need - big bonus
            for need_pos in critical_needs:
                if need_pos in fa_pos:
                    score += 20
                    reasons.append(f"CRITICAL {need_pos} need")
                    break
            else:
                # Regular positional need
                for need_pos in positional_needs:
                    if need_pos in fa_pos:
                        score += 10
                        reasons.append(f"Adds {need_pos} depth")
                        break

            # Window alignment with specific recommendations
            age = fa['age']
            if team_window in ['rebuilding', 'rising']:
                if age <= 25:
                    score += 15
                    reasons.append("Young asset for future")
                elif age <= 27:
                    score += 8
                    reasons.append("Fits timeline")
                elif age >= 32:
                    score -= 10  # Penalty for old players on rebuilding teams
            elif team_window in ['win-now', 'contender']:
                if 26 <= age <= 31:
                    score += 10
                    reasons.append("Win-now fit")
                elif age <= 25 and base_score >= 60:
                    score += 5
                    reasons.append("Ready to contribute")
            elif team_window == 'dynasty':
                if age <= 26:
                    score += 12
                    reasons.append("Dynasty building block")

            # Roster % as quality indicator
            if fa['roster_pct'] >= 70:
                score += 8
                if len(reasons) < 3:
                    reasons.append(f"High demand ({fa['roster_pct']:.0f}%)")
            elif fa['roster_pct'] >= 50:
                score += 4

            # Don't recommend players that don't fit at all
            if score < base_score:
                continue

            scored_fas.append({
                **fa,
                'fit_score': round(score, 1),
                'reasons': reasons[:3] if reasons else ["Available depth"]
            })

        scored_fas.sort(key=lambda x: x['fit_score'], reverse=True)

        return jsonify({
            "suggestions": scored_fas[:30],
            "team_needs": {
                "weaknesses": weaknesses,
                "strengths": strengths,
                "positional_needs": positional_needs,
                "critical_needs": critical_needs,
                "window": team_window
            },
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

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
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #e4e4e4;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { text-align: center; padding: 30px 0; border-bottom: 1px solid #333; margin-bottom: 30px; }
        header h1 { font-size: 2.5rem; color: #ffd700; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
        header p { color: #888; margin-top: 8px; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        .tab { padding: 12px 24px; background: #2a2a4a; border: none; border-radius: 8px; color: #e4e4e4; cursor: pointer; font-size: 1rem; transition: all 0.2s; }
        .tab:hover { background: #3a3a5a; }
        .tab.active { background: #ffd700; color: #1a1a2e; font-weight: 600; }
        .panel { display: none; background: #252540; border-radius: 12px; padding: 25px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
        .panel.active { display: block; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; color: #aaa; font-weight: 500; }
        select, input[type="text"] { width: 100%; padding: 12px; border: 1px solid #444; border-radius: 8px; background: #1a1a2e; color: #e4e4e4; font-size: 1rem; }
        select:focus, input[type="text"]:focus { outline: none; border-color: #ffd700; }
        .trade-sides { display: grid; grid-template-columns: 1fr auto 1fr; gap: 20px; align-items: start; }
        .trade-side { background: #1a1a2e; border-radius: 10px; padding: 20px; }
        .trade-side h3 { color: #ffd700; margin-bottom: 15px; font-size: 1.1rem; }
        .arrow { display: flex; align-items: center; justify-content: center; font-size: 2rem; color: #ffd700; padding-top: 60px; }
        .player-input { display: flex; gap: 10px; margin-bottom: 10px; }
        .player-input input { flex: 1; background: #252545; border: 2px solid #5a5a8a; }
        .player-input input:focus { border-color: #ffd700; background: #2a2a4a; }
        .player-input input::placeholder { color: #8888aa; }
        .pick-label { font-size: 0.85rem; color: #aaa; margin-bottom: 5px; }
        .player-list { margin-top: 10px; min-height: 40px; }
        .player-tag { display: inline-flex; align-items: center; gap: 8px; background: #3a3a5a; padding: 8px 12px; border-radius: 20px; margin: 4px; font-size: 0.9rem; }
        .player-tag.pick { background: #4a3a2a; }
        .player-tag .remove { cursor: pointer; color: #ff6b6b; font-weight: bold; }
        .btn { padding: 14px 28px; border: none; border-radius: 8px; font-size: 1rem; cursor: pointer; transition: all 0.2s; font-weight: 600; }
        .btn-primary { background: #ffd700; color: #1a1a2e; }
        .btn-primary:hover { background: #ffed4a; transform: translateY(-2px); }
        .btn-secondary { background: #3a3a5a; color: #e4e4e4; }
        .btn-add { padding: 12px 16px; background: #4a4a6a; }
        .results { margin-top: 30px; }
        .result-card { background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 15px; }
        .verdict { font-size: 1.5rem; font-weight: bold; margin-bottom: 10px; }
        .verdict.fair { color: #4ade80; }
        .verdict.unfair { color: #f87171; }
        .verdict.questionable { color: #fbbf24; }
        .value-comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 15px 0; }
        .value-box { background: #252540; padding: 15px; border-radius: 8px; }
        .value-box h4 { color: #888; font-size: 0.9rem; margin-bottom: 5px; }
        .value-box .value { font-size: 1.8rem; font-weight: bold; color: #ffd700; }
        .reasoning { color: #aaa; line-height: 1.6; }
        .team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 15px; }
        .team-card { background: #1a1a2e; border-radius: 10px; padding: 20px; cursor: pointer; transition: all 0.2s; }
        .team-card:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }
        .team-card h3 { color: #ffd700; margin-bottom: 10px; }
        .team-card .stats { color: #888; font-size: 0.9rem; }
        .player-card { display: flex; justify-content: space-between; align-items: center; padding: 12px; background: #1a1a2e; border-radius: 8px; margin-bottom: 8px; }
        .player-card .name { font-weight: 500; }
        .player-card .value { color: #ffd700; font-weight: bold; }
        .search-container { position: relative; }
        .search-results { position: absolute; top: 100%; left: 0; right: 0; background: #2a2a4a; border-radius: 0 0 8px 8px; max-height: 300px; overflow-y: auto; z-index: 100; display: none; }
        .search-results.active { display: block; }
        .search-result { padding: 12px; cursor: pointer; border-bottom: 1px solid #3a3a5a; }
        .search-result:hover { background: #3a3a5a; }
        .search-result .player-name { font-weight: 500; }
        .search-result .player-info { font-size: 0.85rem; color: #888; }
        .modal { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.8); z-index: 1000; overflow-y: auto; }
        .modal.active { display: flex; justify-content: center; align-items: flex-start; padding: 40px 20px; }
        .modal-content { background: #252540; border-radius: 16px; max-width: 600px; width: 100%; padding: 30px; position: relative; }
        #player-modal { z-index: 1100; }
        #player-modal .modal-content { max-width: 500px; }
        .modal-close { position: absolute; top: 15px; right: 20px; font-size: 1.5rem; cursor: pointer; color: #888; }
        .player-header { text-align: center; margin-bottom: 25px; }
        .player-header h2 { color: #ffd700; font-size: 1.8rem; }
        .player-header .dynasty-value { font-size: 2.5rem; font-weight: bold; color: #ffd700; }
        .player-stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 15px; }
        .stat-box { background: #1a1a2e; padding: 15px; border-radius: 8px; text-align: center; }
        .stat-box .label { color: #888; font-size: 0.8rem; margin-bottom: 5px; }
        .stat-box .value { font-size: 1.3rem; font-weight: bold; }
        .stat-box .value.ascending { color: #4ade80; }
        .stat-box .value.descending { color: #f87171; }
        .trade-advice { margin-top: 20px; padding: 15px; background: #1a1a2e; border-radius: 8px; }
        .trade-advice h4 { color: #ffd700; margin-bottom: 8px; }
        .loading { text-align: center; padding: 40px; color: #888; }
        .suggestion-card { background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 15px; cursor: pointer; transition: all 0.2s; }
        .suggestion-card:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        .suggestion-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .suggestion-verdict { font-weight: bold; padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; }
        .suggestion-verdict.great { background: #166534; color: #4ade80; }
        .suggestion-verdict.good { background: #854d0e; color: #fbbf24; }
        .suggestion-sides { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .suggestion-side h4 { color: #888; font-size: 0.85rem; margin-bottom: 8px; }
        .suggestion-players { font-size: 0.95rem; }
        .suggestion-value { color: #ffd700; font-weight: 500; margin-top: 5px; }
        .player-link { cursor: pointer; color: #60a5fa; }
        .player-link:hover { text-decoration: underline; }
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
            <button class="tab" onclick="showPanel('suggest')">Trade Suggestions</button>
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
                    <div class="search-container">
                        <input type="text" id="teamASearch" placeholder="Search players..." oninput="searchPlayers('A')" onfocus="showSearchResults('A')">
                        <div id="teamAResults" class="search-results"></div>
                    </div>
                    <div style="margin-top:15px">
                        <div class="pick-label">Add Draft Pick:</div>
                        <div class="player-input">
                            <input type="text" id="teamAPick" placeholder="e.g., 2026 1st Rd #3" list="draftPicksList">
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
                    <div class="search-container">
                        <input type="text" id="teamBSearch" placeholder="Search players..." oninput="searchPlayers('B')" onfocus="showSearchResults('B')">
                        <div id="teamBResults" class="search-results"></div>
                    </div>
                    <div style="margin-top:15px">
                        <div class="pick-label">Add Draft Pick:</div>
                        <div class="player-input">
                            <input type="text" id="teamBPick" placeholder="e.g., 2026 2nd Rd #8" list="draftPicksList">
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
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h3 style="margin:0;">All Teams</h3>
                <button class="btn" onclick="showDraftOrderConfig()" style="font-size: 0.85rem; padding: 8px 16px;">Configure Draft Order</button>
            </div>
            <div id="draftOrderConfig" style="display:none; background:#1a1a2e; border-radius:10px; padding:20px; margin-bottom:20px;">
                <h4 style="color:#ffd700; margin-bottom:15px;">2026 Draft Order</h4>
                <p style="color:#888; font-size:0.85rem; margin-bottom:15px;">Set each team's draft pick position (1 = first pick). Leave empty to use calculated order based on team value.</p>
                <div id="draftOrderInputs" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:10px;"></div>
                <div style="margin-top:15px; display:flex; gap:10px;">
                    <button class="btn" onclick="saveDraftOrder()">Save Draft Order</button>
                    <button class="btn" onclick="clearDraftOrder()" style="background:#444;">Use Calculated Order</button>
                    <button class="btn" onclick="hideDraftOrderConfig()" style="background:#444;">Cancel</button>
                </div>
            </div>
            <div id="teams-loading" class="loading">Loading teams...</div>
            <div id="teams-grid" class="team-grid"></div>
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

        function populateTeamSelects() {
            const selects = ['teamASelect', 'teamBSelect', 'suggestTeamSelect', 'suggestTargetSelect'];
            selects.forEach(id => {
                const select = document.getElementById(id);
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

        async function showDraftOrderConfig() {
            document.getElementById('draftOrderConfig').style.display = 'block';
            const inputs = document.getElementById('draftOrderInputs');
            try {
                const res = await fetch(`${API_BASE}/draft-order`);
                const data = await res.json();
                inputs.innerHTML = teamsData.map(t => `
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="flex:1; font-size:0.9rem;">${t.name}</span>
                        <input type="number" id="pick_${t.name.replace(/[^a-zA-Z0-9]/g,'_')}" min="1" max="${teamsData.length}"
                            value="${data.draft_order[t.name] || ''}" placeholder="${t.draft_pick}"
                            style="width:60px; padding:6px; border-radius:4px; border:1px solid #444; background:#252540; color:#e4e4e4;">
                    </div>
                `).join('');
            } catch (err) { inputs.innerHTML = `<div style="color:#f87171">Error loading draft order</div>`; }
        }

        function hideDraftOrderConfig() {
            document.getElementById('draftOrderConfig').style.display = 'none';
        }

        async function saveDraftOrder() {
            const draftOrder = {};
            teamsData.forEach(t => {
                const input = document.getElementById(`pick_${t.name.replace(/[^a-zA-Z0-9]/g,'_')}`);
                if (input && input.value) {
                    draftOrder[t.name] = parseInt(input.value);
                }
            });
            try {
                const res = await fetch(`${API_BASE}/draft-order`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({draft_order: draftOrder})
                });
                const data = await res.json();
                if (data.success) {
                    alert(data.message);
                    hideDraftOrderConfig();
                    loadTeams();
                } else {
                    alert(data.error || 'Failed to save');
                }
            } catch (err) { alert('Error saving draft order: ' + err.message); }
        }

        async function clearDraftOrder() {
            try {
                const res = await fetch(`${API_BASE}/draft-order`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({draft_order: {}})
                });
                const data = await res.json();
                alert(data.message);
                hideDraftOrderConfig();
                loadTeams();
            } catch (err) { alert('Error: ' + err.message); }
        }

        function showPanel(panel) {
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tabs .tab').forEach(t => t.classList.remove('active'));
            document.getElementById(`${panel}-panel`).classList.add('active');
            event.target.classList.add('active');

            if (panel === 'league') loadLeagueData();
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

                results.innerHTML = `
                    <div class="result-card">
                        <div class="verdict ${verdictClass}">${data.verdict}</div>
                        <div class="value-comparison">
                            <div class="value-box">
                                <h4>${teamA} Receives</h4>
                                <div class="value">${data.value_a_receives.toFixed(1)}</div>
                                ${data.age_analysis?.team_b_sends_avg_age ? `<div style="color:#888;font-size:0.8rem;margin-top:5px;">Avg Age: ${data.age_analysis.team_b_sends_avg_age}</div>` : ''}
                            </div>
                            <div class="value-box">
                                <h4>${teamB} Receives</h4>
                                <div class="value">${data.value_b_receives.toFixed(1)}</div>
                                ${data.age_analysis?.team_a_sends_avg_age ? `<div style="color:#888;font-size:0.8rem;margin-top:5px;">Avg Age: ${data.age_analysis.team_a_sends_avg_age}</div>` : ''}
                            </div>
                        </div>
                        <div style="padding: 15px; background: #1a1a2e; border-radius: 8px; margin: 15px 0;">
                            <div style="white-space: pre-line; line-height: 1.6; color: #ccc;">${data.detailed_analysis || data.reasoning}</div>
                        </div>
                        ${data.category_impact && data.category_impact.length > 0 ? `
                            <div style="display: flex; flex-wrap: wrap; gap: 8px; margin: 15px 0;">
                                ${data.category_impact.map(c => `<span style="background:#3a3a5a;padding:6px 12px;border-radius:15px;font-size:0.85rem;">${c}</span>`).join('')}
                            </div>
                        ` : ''}
                        <div style="padding: 12px 20px; background: ${data.recommendation?.includes('✓') ? '#16331a' : data.recommendation?.includes('⚠') ? '#332d16' : '#331616'}; border-radius: 8px; font-weight: 500; text-align: center;">
                            ${data.recommendation || ''}
                        </div>
                    </div>
                `;
            } catch (e) {
                results.innerHTML = `<div class="result-card"><p style="color: #f87171;">Failed to analyze trade: ${e.message}</p></div>`;
            }
        }

        async function showTeamDetails(teamName) {
            const modal = document.getElementById('team-modal');
            const content = document.getElementById('team-modal-content');
            content.innerHTML = '<div class="loading">Loading team details...</div>';
            modal.classList.add('active');

            try {
                const res = await fetch(`${API_BASE}/team/${encodeURIComponent(teamName)}`);
                const data = await res.json();

                content.innerHTML = `
                    <h2 style="color: #ffd700; margin-bottom: 5px;">#${data.power_rank} ${data.name}</h2>
                    <div style="font-size: 0.9rem; color: #888; margin-bottom: 15px;">2026 Draft Pick: #${data.draft_pick}</div>

                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 15px; margin-bottom: 25px;">
                        <div style="background: #1a1a2e; padding: 15px; border-radius: 8px; text-align: center;">
                            <div style="color: #888; font-size: 0.85rem;">Total Value</div>
                            <div style="color: #ffd700; font-size: 1.5rem; font-weight: bold;">${data.total_value.toFixed(1)}</div>
                        </div>
                        <div style="background: #1a1a2e; padding: 15px; border-radius: 8px; text-align: center;">
                            <div style="color: #888; font-size: 0.85rem;">Power Rank</div>
                            <div style="color: #ffd700; font-size: 1.5rem; font-weight: bold;">#${data.power_rank}</div>
                        </div>
                        <div style="background: #1a1a2e; padding: 15px; border-radius: 8px; text-align: center;">
                            <div style="color: #888; font-size: 0.85rem;">2026 Pick</div>
                            <div style="color: #ffd700; font-size: 1.5rem; font-weight: bold;">#${data.draft_pick}</div>
                        </div>
                        <div style="background: #1a1a2e; padding: 15px; border-radius: 8px; text-align: center;">
                            <div style="color: #888; font-size: 0.85rem;">Players</div>
                            <div style="color: #e4e4e4; font-size: 1.5rem; font-weight: bold;">${data.player_count}</div>
                        </div>
                    </div>

                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 25px;">
                        <div style="background: #1a1a2e; padding: 15px; border-radius: 8px;">
                            <div style="color: #888; font-size: 0.85rem; margin-bottom: 5px;">Hitting Strengths</div>
                            <div style="color: #4ade80;">${(data.hitting_strengths || []).join(', ') || 'None'}</div>
                        </div>
                        <div style="background: #1a1a2e; padding: 15px; border-radius: 8px;">
                            <div style="color: #888; font-size: 0.85rem; margin-bottom: 5px;">Hitting Weaknesses</div>
                            <div style="color: #f87171;">${(data.hitting_weaknesses || []).join(', ') || 'None'}</div>
                        </div>
                        <div style="background: #1a1a2e; padding: 15px; border-radius: 8px;">
                            <div style="color: #888; font-size: 0.85rem; margin-bottom: 5px;">Pitching Strengths</div>
                            <div style="color: #4ade80;">${(data.pitching_strengths || []).join(', ') || 'None'}</div>
                        </div>
                        <div style="background: #1a1a2e; padding: 15px; border-radius: 8px;">
                            <div style="color: #888; font-size: 0.85rem; margin-bottom: 5px;">Pitching Weaknesses</div>
                            <div style="color: #f87171;">${(data.pitching_weaknesses || []).join(', ') || 'None'}</div>
                        </div>
                    </div>

                    ${data.analysis ? `<div style="margin-bottom: 25px; padding: 15px; background: #1a1a2e; border-radius: 8px; line-height: 1.7;">${data.analysis}</div>` : ''}

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
                        <h4 style="color: #ffd700; margin: 25px 0 15px;">Prospects</h4>
                        ${data.prospects.map(p => `
                            <div class="player-card" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">
                                <div class="name player-link">${p.name}</div>
                                <div class="value" style="color: #4ade80;">#${p.rank}</div>
                            </div>
                        `).join('')}
                    ` : ''}
                `;
            } catch (e) {
                content.innerHTML = `<p style="color: #f87171;">Failed to load team details: ${e.message}</p>`;
            }
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

                let html = allCurrentSuggestions.map((s, idx) => `
                    <div class="suggestion-card" onclick="applySuggestion(${idx})">
                        <div class="suggestion-header">
                            <span>Trade with ${s.other_team}</span>
                            <div style="display:flex;gap:8px;align-items:center;">
                                <span style="background:#3a3a5a;padding:4px 10px;border-radius:12px;font-size:0.75rem;">${s.trade_type || '1-for-1'}</span>
                                <span class="suggestion-verdict ${s.value_diff < 5 ? 'great' : 'good'}">${s.value_diff < 5 ? 'Great Deal' : 'Good Deal'}</span>
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
                    </div>
                `).join('');

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

            showPanel('analyze');
            document.querySelector('.tabs .tab').click();
        }

        function updateTeamA() {}
        function updateTeamB() {}

        function populateDraftPicksList() {
            const datalist = document.getElementById('draftPicksList');
            if (!datalist) return;

            const years = [2025, 2026, 2027, 2028, 2029];
            const rounds = ['1st', '2nd', '3rd', '4th', '5th'];
            const numTeams = teamsData.length || 12;

            let options = [];
            years.forEach(year => {
                rounds.forEach(round => {
                    for (let pick = 1; pick <= numTeams; pick++) {
                        options.push(`${year} ${round} Rd #${pick}`);
                    }
                });
            });

            datalist.innerHTML = options.map(opt => `<option value="${opt}">`).join('');
        }

        // Initialize
        loadTeams().then(() => populateDraftPicksList());
    </script>
    <datalist id="draftPicksList"></datalist>
</body>
</html>'''

# ============================================================================
# DATA LOADING
# ============================================================================

# Cache for player ages from Fantrax CSV
fantrax_ages = {}


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

    # Also load from prospect ranking files (for prospects not in Fantrax)
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
                        # Only add if not already in fantrax_ages (Fantrax is primary)
                        if name and age_str and age_str.isdigit() and name not in fantrax_ages:
                            fantrax_ages[name] = int(age_str)
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
    """Load prospect rankings from consensus ranking CSV files."""
    import csv
    import glob

    script_dir = os.path.dirname(os.path.abspath(__file__))
    total_count = 0

    # Look for consensus ranking files
    prospect_files = glob.glob(os.path.join(script_dir, 'Consensus*Ranks*.csv'))

    for csv_file in prospect_files:
        try:
            count = 0
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Name', '').strip()
                    avg_rank_str = row.get('Avg Rank', '')

                    if not name or not avg_rank_str:
                        continue

                    try:
                        avg_rank = float(avg_rank_str)
                        # Convert avg rank to an integer rank (round to nearest)
                        rank = int(round(avg_rank))

                        # Only add if not already in PROSPECT_RANKINGS or if this rank is better
                        if name not in PROSPECT_RANKINGS or rank < PROSPECT_RANKINGS[name]:
                            PROSPECT_RANKINGS[name] = rank
                            count += 1
                    except (ValueError, TypeError):
                        continue

            if count > 0:
                print(f"Loaded {count} prospect rankings from {os.path.basename(csv_file)}")
                total_count += count
        except Exception as e:
            print(f"Warning: Could not load prospect rankings from {csv_file}: {e}")

    if total_count > 0:
        print(f"Total prospect rankings loaded: {total_count}")


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

                player = Player(
                    name=p['name'],
                    position=p.get('position', 'N/A'),
                    mlb_team=p.get('mlb_team', 'FA'),
                    fantasy_team=team_name,
                    roster_status=p.get('status', 'Active'),
                    age=player_age,
                    is_prospect=p.get('is_prospect', False),
                    prospect_rank=p.get('prospect_rank') or 999,
                )
                team.players.append(player)
                total_players += 1

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
                is_prospect = prospect_rank is not None

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
    prospects = [{"name": p.name, "rank": p.prospect_rank, "age": p.age}
                 for p in team.players if p.is_prospect and p.prospect_rank]
    prospects.sort(key=lambda x: x['rank'])

    # Calculate category strengths/weaknesses
    hitting_strengths, hitting_weaknesses = [], []
    pitching_strengths, pitching_weaknesses = [], []

    # Calculate team totals
    total_hr = sum(HITTER_PROJECTIONS.get(p.name, {}).get('HR', 0) for p in team.players)
    total_sb = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SB', 0) for p in team.players)
    total_rbi = sum(HITTER_PROJECTIONS.get(p.name, {}).get('RBI', 0) for p in team.players)
    total_k = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in team.players)
    total_sv_hld = sum((RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) + RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0)) for p in team.players)

    # Compare to league averages (simple threshold-based)
    if total_hr >= 200: hitting_strengths.append("HR")
    elif total_hr < 150: hitting_weaknesses.append("HR")
    if total_sb >= 100: hitting_strengths.append("SB")
    elif total_sb < 60: hitting_weaknesses.append("SB")
    if total_rbi >= 600: hitting_strengths.append("RBI")
    elif total_rbi < 450: hitting_weaknesses.append("RBI")
    if total_k >= 1200: pitching_strengths.append("K")
    elif total_k < 800: pitching_weaknesses.append("K")
    if total_sv_hld >= 60: pitching_strengths.append("SV+HLD")
    elif total_sv_hld < 30: pitching_weaknesses.append("SV+HLD")

    # Generate analysis
    analysis = generate_team_analysis(team_name, team, players_with_value, power_rank, len(teams))

    return jsonify({
        "name": team_name,
        "players": players,
        "top_players": top_players,
        "prospects": prospects,  # Show all prospects
        "player_count": len(players),
        "total_value": round(total_value, 1),
        "power_rank": power_rank,
        "draft_pick": draft_pick,
        "hitting_strengths": hitting_strengths,
        "hitting_weaknesses": hitting_weaknesses,
        "pitching_strengths": pitching_strengths,
        "pitching_weaknesses": pitching_weaknesses,
        "analysis": analysis
    })


def generate_team_analysis(team_name, team, players_with_value=None, power_rank=None, total_teams=12):
    """Generate a comprehensive text analysis/description of a team."""
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

    # Calculate team totals
    total_hr = sum(HITTER_PROJECTIONS.get(p.name, {}).get('HR', 0) for p, _ in players_with_value)
    total_sb = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SB', 0) for p, _ in players_with_value)
    total_k = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p, _ in players_with_value)
    total_sv_hld = sum((RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) + RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0)) for p, _ in players_with_value)

    # Determine competitive window
    top_third = total_teams // 3
    bottom_third = total_teams - top_third
    is_old_roster = avg_age >= 28 or veteran_players > prime_players
    is_young_roster = avg_age <= 26 or len(prospects) >= 6

    if power_rank <= top_third:
        if is_young_roster:
            window = "dynasty"
            window_desc = "a dynasty powerhouse with elite young talent and a long competitive window"
        elif is_old_roster:
            window = "win-now"
            window_desc = "a win-now contender that should push for a championship while their window is open"
        else:
            window = "contender"
            window_desc = "a legitimate contender with a strong, balanced roster"
    elif power_rank >= bottom_third:
        if is_old_roster:
            window = "teardown"
            window_desc = "an aging roster in need of a full rebuild"
        elif is_young_roster:
            window = "rebuilding"
            window_desc = "a rebuilding team on the right track with young talent to develop"
        else:
            window = "retooling"
            window_desc = "a team that needs to retool - stuck in the middle with no clear direction"
    else:
        if is_young_roster:
            window = "rising"
            window_desc = "a rising team with young talent that could emerge as a contender soon"
        elif is_old_roster:
            window = "declining"
            window_desc = "a declining roster that may need to sell aging assets before they lose value"
        else:
            window = "competitive"
            window_desc = "a competitive team in the mix but not a true frontrunner"

    analysis_parts.append(f"<b>TEAM IDENTITY:</b> Ranked #{power_rank} in the league. {window_desc.capitalize()}.")

    # Roster composition
    roster_desc = f"<b>ROSTER PROFILE:</b> Averages {avg_age:.1f} years old"
    if young_players > veteran_players:
        roster_desc += f" (skews young with {young_players} players 25 or under)"
    elif veteran_players > young_players:
        roster_desc += f" (skews veteran with {veteran_players} players 31+)"
    else:
        roster_desc += f" ({young_players} young, {prime_players} prime, {veteran_players} veteran)"
    analysis_parts.append(roster_desc + ".")

    # Top assets with trajectory
    top_3 = players_with_value[:3]
    if top_3:
        asset_strs = []
        for p, v in top_3:
            if p.age <= 25:
                trajectory = "ascending"
            elif p.age <= 28:
                trajectory = "prime"
            elif p.age <= 31:
                trajectory = "peak"
            else:
                trajectory = "declining"
            asset_strs.append(f"{p.name} ({v:.0f}, {trajectory})")
        analysis_parts.append(f"<b>CORNERSTONE PLAYERS:</b> {', '.join(asset_strs)}.")

    # Prospects
    if prospects:
        top_prospects = sorted([p for p in prospects if p.prospect_rank and p.prospect_rank <= 100], key=lambda x: x.prospect_rank)[:3]
        if top_prospects:
            prospect_strs = []
            for p in top_prospects:
                eta = "MLB-ready" if p.age >= 22 else f"ETA {2026 + (22 - p.age) if p.age else '?'}"
                prospect_strs.append(f"{p.name} (#{p.prospect_rank}, {eta})")
            analysis_parts.append(f"<b>PROSPECT PIPELINE:</b> {', '.join(prospect_strs)}.")

    # Category outlook
    analysis_parts.append(f"<b>CATEGORY OUTLOOK:</b> Projected totals: {total_hr} HR, {total_sb} SB, {total_k} K, {total_sv_hld} SV+HLD.")

    # Risk factors
    risk_factors = []
    regression_candidates = []
    for p, v in players_with_value[:15]:
        if p.age >= 33 and v >= 25:
            regression_candidates.append(f"{p.name} (age {p.age})")
        elif p.age >= 35:
            regression_candidates.append(f"{p.name} (age {p.age})")
    if regression_candidates:
        risk_factors.append(f"Regression watch: {', '.join(regression_candidates[:3])}")

    # Concentration risk
    if players_with_value:
        top_2_value = sum(v for _, v in players_with_value[:2])
        total_value = sum(v for _, v in players_with_value)
        if total_value > 0 and top_2_value / total_value > 0.30:
            risk_factors.append(f"Top-heavy ({top_2_value/total_value*100:.0f}% value in top 2)")

    if not risk_factors:
        risk_factors.append("No major concerns identified")

    analysis_parts.append(f"<b>RISK FACTORS:</b> {' | '.join(risk_factors)}.")

    # Trade strategy based on window
    if window == "dynasty":
        analysis_parts.append("<b>TRADE STRATEGY:</b> Dynasty dominance mode - protect your core, but don't overpay to fill small gaps. You can afford to be patient.")
    elif window == "contender":
        analysis_parts.append("<b>TRADE STRATEGY:</b> Contender's edge - make surgical moves to address weaknesses. Worth paying a premium for the right piece.")
    elif window == "win-now":
        analysis_parts.append("<b>TRADE STRATEGY:</b> Championship window closing - be aggressive. Trade future assets for proven talent now.")
    elif window == "rising":
        analysis_parts.append("<b>TRADE STRATEGY:</b> Build around your young core. Target complementary pieces to accelerate your timeline.")
    elif window == "competitive":
        analysis_parts.append("<b>TRADE STRATEGY:</b> In the mix but need more. Look for undervalued assets to push into contention.")
    elif window == "declining":
        analysis_parts.append("<b>TRADE STRATEGY:</b> Begin transitioning before values crater. Sell aging assets while they still have value.")
    elif window == "retooling":
        analysis_parts.append("<b>TRADE STRATEGY:</b> Stuck in the middle - commit to a direction. Either sell vets to rebuild or buy to compete.")
    elif window == "rebuilding":
        analysis_parts.append("<b>TRADE STRATEGY:</b> Stay the course - accumulate young assets and draft picks. Patience will pay off.")
    elif window == "teardown":
        analysis_parts.append("<b>TRADE STRATEGY:</b> Full rebuild required. Sell veterans for picks and prospects - every aging asset must go.")

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
    # Find player
    player = None
    fantasy_team = None

    for team_name, team in teams.items():
        for p in team.players:
            if p.name.lower() == player_name.lower():
                player = p
                fantasy_team = team_name
                break
        if player:
            break

    if not player:
        return jsonify({"error": f"Player '{player_name}' not found"}), 404

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

    # Category impact analysis
    category_analysis = ""
    hr_a = sum(HITTER_PROJECTIONS.get(p.name, {}).get('HR', 0) for p in found_players_a)
    hr_b = sum(HITTER_PROJECTIONS.get(p.name, {}).get('HR', 0) for p in found_players_b)
    sb_a = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SB', 0) for p in found_players_a)
    sb_b = sum(HITTER_PROJECTIONS.get(p.name, {}).get('SB', 0) for p in found_players_b)
    k_a = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in found_players_a)
    k_b = sum((PITCHER_PROJECTIONS.get(p.name, {}).get('K', 0) or RELIEVER_PROJECTIONS.get(p.name, {}).get('K', 0)) for p in found_players_b)
    sv_hld_a = sum((RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) + RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0)) for p in found_players_a)
    sv_hld_b = sum((RELIEVER_PROJECTIONS.get(p.name, {}).get('SV', 0) + RELIEVER_PROJECTIONS.get(p.name, {}).get('HD', 0)) for p in found_players_b)

    cat_impacts = []
    if hr_a - hr_b >= 15:
        cat_impacts.append(f"{team_b} gains power ({hr_a - hr_b} HR)")
    elif hr_b - hr_a >= 15:
        cat_impacts.append(f"{team_a} gains power ({hr_b - hr_a} HR)")
    if sb_a - sb_b >= 10:
        cat_impacts.append(f"{team_b} gains speed ({sb_a - sb_b} SB)")
    elif sb_b - sb_a >= 10:
        cat_impacts.append(f"{team_a} gains speed ({sb_b - sb_a} SB)")
    if k_a - k_b >= 50:
        cat_impacts.append(f"{team_b} gains strikeouts ({k_a - k_b} K)")
    elif k_b - k_a >= 50:
        cat_impacts.append(f"{team_a} gains strikeouts ({k_b - k_a} K)")
    if sv_hld_a - sv_hld_b >= 10:
        cat_impacts.append(f"{team_b} gains saves/holds ({sv_hld_a - sv_hld_b} SV+HLD)")
    elif sv_hld_b - sv_hld_a >= 10:
        cat_impacts.append(f"{team_a} gains saves/holds ({sv_hld_b - sv_hld_a} SV+HLD)")

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

    return jsonify({
        "verdict": verdict,
        "value_a_receives": value_b_sends,
        "value_b_receives": value_a_sends,
        "value_diff": value_diff,
        "reasoning": reasoning,
        "detailed_analysis": detailed_analysis,
        "age_analysis": {
            "team_a_sends_avg_age": round(avg_age_a_sends, 1) if avg_age_a_sends else None,
            "team_b_sends_avg_age": round(avg_age_b_sends, 1) if avg_age_b_sends else None,
        },
        "category_impact": cat_impacts,
        "recommendation": recommendation
    })


@app.route('/suggest')
def get_suggestions():
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
    my_tradeable = [(p, v) for p, v in my_players if 15 <= v <= 85][:15]

    target_teams = [target_team] if target_team else [t for t in teams.keys() if t != my_team]

    for other_team in target_teams:
        if other_team == my_team:
            continue

        their_players = [(p, calculator.calculate_player_value(p)) for p in teams[other_team].players]
        their_players.sort(key=lambda x: x[1], reverse=True)
        their_tradeable = [(p, v) for p, v in their_players if 15 <= v <= 85][:15]

        # 1-for-1 trades
        if trade_type in ['any', '1-for-1']:
            for my_p, my_val in my_tradeable:
                for their_p, their_val in their_tradeable:
                    diff = abs(my_val - their_val)
                    if diff < 15:
                        suggestions.append({
                            "my_team": my_team,
                            "other_team": other_team,
                            "you_send": [my_p.name],
                            "you_receive": [their_p.name],
                            "you_send_value": round(my_val, 1),
                            "you_receive_value": round(their_val, 1),
                            "value_diff": round(diff, 1),
                            "trade_type": "1-for-1"
                        })

        # 2-for-1 trades (you send 2, receive 1 better player)
        if trade_type in ['any', '2-for-1']:
            for i, (my_p1, my_v1) in enumerate(my_tradeable):
                for my_p2, my_v2 in my_tradeable[i+1:]:
                    combined_val = my_v1 + my_v2
                    for their_p, their_val in their_tradeable:
                        diff = abs(combined_val - their_val)
                        # 2-for-1 should get a better player (their_val > max of yours)
                        if diff < 20 and their_val > max(my_v1, my_v2) * 1.1:
                            suggestions.append({
                                "my_team": my_team,
                                "other_team": other_team,
                                "you_send": [my_p1.name, my_p2.name],
                                "you_receive": [their_p.name],
                                "you_send_value": round(combined_val, 1),
                                "you_receive_value": round(their_val, 1),
                                "value_diff": round(diff, 1),
                                "trade_type": "2-for-1"
                            })

        # 2-for-2 trades
        if trade_type in ['any', '2-for-2']:
            for i, (my_p1, my_v1) in enumerate(my_tradeable[:8]):
                for my_p2, my_v2 in my_tradeable[i+1:8]:
                    my_combined = my_v1 + my_v2
                    for j, (their_p1, their_v1) in enumerate(their_tradeable[:8]):
                        for their_p2, their_v2 in their_tradeable[j+1:8]:
                            their_combined = their_v1 + their_v2
                            diff = abs(my_combined - their_combined)
                            if diff < 20:
                                suggestions.append({
                                    "my_team": my_team,
                                    "other_team": other_team,
                                    "you_send": [my_p1.name, my_p2.name],
                                    "you_receive": [their_p1.name, their_p2.name],
                                    "you_send_value": round(my_combined, 1),
                                    "you_receive_value": round(their_combined, 1),
                                    "value_diff": round(diff, 1),
                                    "trade_type": "2-for-2"
                                })

    # Sort by value difference (fairest first), limit to prevent too many
    suggestions.sort(key=lambda x: x['value_diff'])
    suggestions = suggestions[:200]  # Cap at 200 total suggestions

    # Paginate
    paginated = suggestions[offset:offset + limit]
    has_more = len(suggestions) > offset + limit

    return jsonify({
        "suggestions": paginated,
        "has_more": has_more,
        "total_found": len(suggestions),
        "offset": offset,
        "limit": limit
    })


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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)

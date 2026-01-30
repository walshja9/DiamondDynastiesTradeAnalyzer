"""
Diamond Dynasties Data Exporter
Run this locally to export all league data from Fantrax to league_data.json
Then push that file to GitHub for the hosted app to use.

Usage:
    python data_exporter.py

This will:
1. Open a browser for Fantrax login
2. Wait for you to log in
3. Fetch all league data (rosters, standings, matchups, transactions)
4. Save to league_data.json
"""

import json
import os
import pickle
import time
from datetime import datetime

# Configuration
FANTRAX_LEAGUE_ID = "3iibc548mhhszwor"
COOKIE_FILE = os.path.join(os.path.expanduser('~'), '.fantrax_cookies.pkl')
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'league_data.json')

# Import prospect rankings and player ages
from dynasty_trade_analyzer_v2 import (
    PROSPECT_RANKINGS,
    HITTER_PROJECTIONS,
    PITCHER_PROJECTIONS,
    RELIEVER_PROJECTIONS,
    PLAYER_AGES,
    DynastyValueCalculator,
)

# Load ages from CSV if available (more complete than PLAYER_AGES dict)
def load_ages_from_csv():
    """Load player ages from Fantrax CSV export if available."""
    import csv
    import glob

    ages = {}
    search_paths = [
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
        os.path.expanduser('~'),
        os.path.join(os.path.expanduser('~'), 'Downloads'),
    ]

    csv_path = None
    for path in search_paths:
        for pattern in ['Fantrax*.csv', 'fantrax*.csv']:
            matches = glob.glob(os.path.join(path, pattern))
            if matches:
                csv_path = matches[0]
                break
        if csv_path:
            break

    if csv_path:
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Player', '')
                    age_str = row.get('Age', '')
                    if name and age_str.isdigit():
                        ages[name] = int(age_str)
            print(f"Loaded {len(ages)} player ages from CSV: {csv_path}")
        except Exception as e:
            print(f"Warning: Could not load ages from CSV: {e}")

    return ages

# Load CSV ages at module level
CSV_AGES = load_ages_from_csv()


def load_stats_from_csv():
    """Load actual player stats from Fantrax stats CSV export if available."""
    import csv
    import glob

    stats = {}
    search_paths = [
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
        os.path.expanduser('~'),
        os.path.join(os.path.expanduser('~'), 'Downloads'),
    ]

    # Look for hitter stats CSV
    hitter_csv = None
    pitcher_csv = None
    for path in search_paths:
        for pattern in ['*hitter*stats*.csv', '*batting*stats*.csv', '*hitting*.csv']:
            matches = glob.glob(os.path.join(path, pattern))
            if matches:
                hitter_csv = matches[0]
                break
        for pattern in ['*pitcher*stats*.csv', '*pitching*stats*.csv', '*pitching*.csv']:
            matches = glob.glob(os.path.join(path, pattern))
            if matches:
                pitcher_csv = matches[0]
                break
        if hitter_csv and pitcher_csv:
            break

    # Load hitter stats
    if hitter_csv:
        try:
            with open(hitter_csv, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Player', row.get('Name', '')).strip()
                    if not name:
                        continue
                    stats[name] = {
                        "type": "hitter",
                        "G": int(float(row.get('G', 0) or 0)),
                        "AB": int(float(row.get('AB', 0) or 0)),
                        "R": int(float(row.get('R', 0) or 0)),
                        "H": int(float(row.get('H', 0) or 0)),
                        "HR": int(float(row.get('HR', 0) or 0)),
                        "RBI": int(float(row.get('RBI', 0) or 0)),
                        "SB": int(float(row.get('SB', 0) or 0)),
                        "AVG": row.get('AVG', '.000'),
                        "OBP": row.get('OBP', '.000'),
                        "OPS": row.get('OPS', '.000'),
                    }
            print(f"Loaded {len([s for s in stats.values() if s['type'] == 'hitter'])} hitter stats from: {hitter_csv}")
        except Exception as e:
            print(f"Warning: Could not load hitter stats from CSV: {e}")

    # Load pitcher stats
    if pitcher_csv:
        try:
            with open(pitcher_csv, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Player', row.get('Name', '')).strip()
                    if not name:
                        continue
                    stats[name] = {
                        "type": "pitcher",
                        "G": int(float(row.get('G', 0) or 0)),
                        "GS": int(float(row.get('GS', 0) or 0)),
                        "IP": row.get('IP', '0.0'),
                        "W": int(float(row.get('W', 0) or 0)),
                        "L": int(float(row.get('L', 0) or 0)),
                        "SV": int(float(row.get('SV', 0) or 0)),
                        "K": int(float(row.get('K', row.get('SO', 0)) or 0)),
                        "ERA": row.get('ERA', '0.00'),
                        "WHIP": row.get('WHIP', '0.00'),
                    }
            print(f"Loaded {len([s for s in stats.values() if s['type'] == 'pitcher'])} pitcher stats from: {pitcher_csv}")
        except Exception as e:
            print(f"Warning: Could not load pitcher stats from CSV: {e}")

    return stats

# Load stats CSV at module level
CSV_STATS = load_stats_from_csv()


def save_cookies(cookies):
    """Save cookies to file for reuse."""
    with open(COOKIE_FILE, 'wb') as f:
        pickle.dump(cookies, f)
    print(f"Saved cookies to {COOKIE_FILE}")


def load_cookies():
    """Load saved cookies if available."""
    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE, 'rb') as f:
                return pickle.load(f)
        except Exception:
            pass
    return None


def get_authenticated_session():
    """Get an authenticated session, using saved cookies or browser login."""
    from requests import Session

    session = Session()

    # Try saved cookies first
    saved_cookies = load_cookies()
    if saved_cookies:
        print("Found saved cookies, testing...")
        for name, value in saved_cookies.items():
            session.cookies.set(name, value, domain='.fantrax.com')

        # Test if cookies still work
        try:
            from fantraxapi import FantraxAPI
            api = FantraxAPI(FANTRAX_LEAGUE_ID, session=session)
            # Try to access something that requires auth
            api.trade_block()
            print("Saved cookies are valid!")
            return session, api
        except Exception as e:
            print(f"Saved cookies expired or invalid: {e}")
            session = Session()  # Reset session

    # Need fresh login via browser
    print("\nOpening browser for Fantrax login...")
    print("Please log in to your Fantrax account.")
    print("After logging in, return here and press Enter.\n")

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as e:
        print(f"Error: Missing dependency - {e}")
        print("Install with: pip install selenium webdriver-manager")
        return None, None

    # Set up Chrome
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # Navigate to Fantrax login
        driver.get("https://www.fantrax.com/login")

        print("Browser opened. Please log in to Fantrax...")
        print("After logging in and seeing your dashboard, press Enter here.")
        input("\nPress Enter when logged in... ")

        # Capture cookies
        selenium_cookies = driver.get_cookies()
        current_url = driver.current_url

        print(f"Current URL: {current_url}")

        # Transfer cookies to requests session
        cookie_dict = {}
        for cookie in selenium_cookies:
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', '.fantrax.com'))
            cookie_dict[cookie['name']] = cookie['value']

        # Save for next time
        save_cookies(cookie_dict)

        # Create API instance
        from fantraxapi import FantraxAPI
        api = FantraxAPI(FANTRAX_LEAGUE_ID, session=session)

        return session, api

    finally:
        driver.quit()
        print("Browser closed.")


def export_league_data():
    """Export all league data to JSON file."""
    print("=" * 50)
    print("  Diamond Dynasties Data Exporter")
    print("=" * 50)
    print()

    # Get authenticated session
    session, api = get_authenticated_session()

    if not api:
        print("Failed to authenticate. Exiting.")
        return False

    print("\nFetching league data...")

    calculator = DynastyValueCalculator()
    export_data = {
        "exported_at": datetime.now().isoformat(),
        "league_id": FANTRAX_LEAGUE_ID,
        "league_name": "",
        "teams": {},
        "standings": [],
        "matchups": [],
        "transactions": [],
    }

    # Get league info
    try:
        export_data["league_name"] = api.name
        print(f"League: {api.name}")
    except Exception as e:
        print(f"Warning: Could not get league name: {e}")

    # Export teams and rosters
    print("\nExporting teams and rosters...")
    total_players = 0

    try:
        for fantrax_team in api.teams:
            team_name = fantrax_team.name
            print(f"  - {team_name}...", end=" ")

            roster = api.team_roster(fantrax_team.id)

            players = []
            # Roster has 'rows' attribute, each row has a 'player' attribute
            for row in roster.rows:
                if row.player is None:
                    continue

                p = row.player

                # Check prospect status
                prospect_rank = PROSPECT_RANKINGS.get(p.name)
                is_prospect = prospect_rank is not None

                # Get projections
                projections = {}
                if p.name in HITTER_PROJECTIONS:
                    projections = HITTER_PROJECTIONS[p.name]
                elif p.name in PITCHER_PROJECTIONS:
                    projections = PITCHER_PROJECTIONS[p.name]
                elif p.name in RELIEVER_PROJECTIONS:
                    projections = RELIEVER_PROJECTIONS[p.name]

                # Get position and status from player object
                pos = p.pos_short_name if hasattr(p, 'pos_short_name') else (p.position if hasattr(p, 'position') else "N/A")
                mlb_team = p.team_short_name if hasattr(p, 'team_short_name') else "FA"
                # Get age: API first, then CSV ages, then PLAYER_AGES dictionary
                age = p.age if hasattr(p, 'age') and p.age else 0
                if age == 0:
                    age = CSV_AGES.get(p.name, 0)
                if age == 0:
                    age = PLAYER_AGES.get(p.name, 0)

                # Get fantasy points from roster row
                fantasy_points = row.total_fantasy_points if hasattr(row, 'total_fantasy_points') else None
                fppg = row.fantasy_points_per_game if hasattr(row, 'fantasy_points_per_game') else None

                # Get actual stats from CSV if available
                actual_stats = CSV_STATS.get(p.name)

                player_data = {
                    "name": p.name,
                    "position": pos,
                    "mlb_team": mlb_team,
                    "age": age,
                    "status": row.position.short_name if hasattr(row.position, 'short_name') else "Active",
                    "is_prospect": is_prospect,
                    "prospect_rank": prospect_rank if is_prospect else None,
                    "has_projections": bool(projections),
                    "projections": projections if projections else None,
                    "fantasy_points": fantasy_points,
                    "fppg": fppg,
                    "actual_stats": actual_stats,
                }
                players.append(player_data)
                total_players += 1

            export_data["teams"][team_name] = {
                "id": fantrax_team.id,
                "name": team_name,
                "players": players,
            }
            print(f"{len(players)} players")
    except Exception as e:
        import traceback
        print(f"\nError exporting teams: {e}")
        traceback.print_exc()

    print(f"\nTotal: {len(export_data['teams'])} teams, {total_players} players")

    # Export standings
    print("\nExporting standings...")
    try:
        standings = api.standings()
        # Standings has 'ranks' dict: rank (int) -> Record object
        for rank, record in standings.ranks.items():
            standing_data = {
                "rank": rank,
                "team": record.team.name if hasattr(record, 'team') else str(record),
                "wins": record.win if hasattr(record, 'win') else 0,
                "losses": record.loss if hasattr(record, 'loss') else 0,
                "ties": record.tie if hasattr(record, 'tie') else 0,
                "points_for": record.points_for if hasattr(record, 'points_for') else 0,
                "points_against": record.points_against if hasattr(record, 'points_against') else 0,
                "streak": record.streak if hasattr(record, 'streak') else "",
            }
            export_data["standings"].append(standing_data)
        # Sort by rank
        export_data["standings"].sort(key=lambda x: x["rank"])
        print(f"  {len(export_data['standings'])} teams in standings")
    except Exception as e:
        import traceback
        print(f"  Warning: Could not export standings: {e}")
        traceback.print_exc()

    # Export matchups/schedule
    print("\nExporting matchups...")
    try:
        scoring_periods = api.scoring_period_results(season=True, playoffs=False)
        for period_num, period in scoring_periods.items():
            period_data = {
                "period": f"Period {period_num}",
                "start": period.start.isoformat() if hasattr(period, 'start') else "",
                "end": period.end.isoformat() if hasattr(period, 'end') else "",
                "status": "complete" if getattr(period, 'complete', False) else "current" if getattr(period, 'current', False) else "future",
                "matchups": [],
            }

            for matchup in period.matchups:
                away_name = matchup.away.name if hasattr(matchup.away, 'name') else str(matchup.away)
                home_name = matchup.home.name if hasattr(matchup.home, 'name') else str(matchup.home)

                period_data["matchups"].append({
                    "away": away_name,
                    "home": home_name,
                    "away_score": matchup.away_score,
                    "home_score": matchup.home_score,
                })

            export_data["matchups"].append(period_data)

        print(f"  {len(export_data['matchups'])} scoring periods")
    except Exception as e:
        print(f"  Warning: Could not export matchups: {e}")
        print(f"  (This may mean the season hasn't started yet)")

    # Export transactions
    print("\nExporting transactions...")
    try:
        txns = api.transactions(count=50)
        for tx in txns:
            tx_data = {
                "team": tx.team.name if hasattr(tx, 'team') else "Unknown",
                "date": tx.date.strftime("%Y-%m-%d %H:%M") if hasattr(tx, 'date') else "",
                "players": [],
            }

            if hasattr(tx, 'players'):
                for p in tx.players:
                    tx_data["players"].append({
                        "name": p.name,
                        "type": p.type,
                    })

            export_data["transactions"].append(tx_data)

        print(f"  {len(export_data['transactions'])} transactions")
    except Exception as e:
        print(f"  Warning: Could not export transactions: {e}")

    # Save to file
    print(f"\nSaving to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, default=str)

    print("\n" + "=" * 50)
    print("  Export Complete!")
    print("=" * 50)
    print(f"\nData saved to: {OUTPUT_FILE}")
    print(f"Exported at: {export_data['exported_at']}")
    print(f"\nNext steps:")
    print(f"1. Commit and push league_data.json to your GitHub repo")
    print(f"2. Render will auto-deploy with the new data")
    print(f"3. Your leaguemates will see the updated data")

    return True


if __name__ == "__main__":
    export_league_data()

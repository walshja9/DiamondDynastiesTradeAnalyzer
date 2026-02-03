import os
os.chdir(r"C:\Users\Alex\DiamondDynastiesTradeAnalyzer")

from app import app
import json

with app.test_client() as client:
    resp = client.get('/team/Pawtucket%20Red%20Sox')
    data = json.loads(resp.data)

    print("Window Analysis:")
    wa = data.get('window_analysis', {})
    print(f"  MLB Ready: {wa.get('mlb_ready_prospects')}")
    print(f"  Prospect ETA: {wa.get('prospect_eta')}")
    print(f"  Window: {wa.get('window')}")
    print(f"  Score: {wa.get('window_score')}")

    print("\nFirst 5 prospects with level/eta:")
    for p in data['prospects'][:5]:
        print(f"  {p['name']}: level={p.get('level', 'N/A')}, eta={p.get('eta', 'N/A')}")

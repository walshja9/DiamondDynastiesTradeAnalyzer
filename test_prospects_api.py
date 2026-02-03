import os
os.chdir(r"C:\Users\Alex\DiamondDynastiesTradeAnalyzer")

from app import app, CFR_PROSPECT_LEVELS, teams, calc_player_value
import json

print(f"CFR_PROSPECT_LEVELS has {len(CFR_PROSPECT_LEVELS)} entries")
print(f"Sample: Sal Stewart = {CFR_PROSPECT_LEVELS.get('Sal Stewart', 'NOT FOUND')}")

# Test the endpoint
with app.test_client() as client:
    resp = client.get('/team/Pawtucket%20Red%20Sox')
    data = json.loads(resp.data)

    print("\nProspects from API:")
    for p in data['prospects'][:5]:
        print(f"  {p}")

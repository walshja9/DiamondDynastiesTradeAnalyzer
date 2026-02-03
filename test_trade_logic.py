import os
os.chdir(r"C:\Users\Alex\DiamondDynastiesTradeAnalyzer")

from app import app
import json

with app.test_client() as client:
    # Test sending Riley Greene
    resp = client.get('/find-trades-for-player?player_name=Riley%20Greene&my_team=Pawtucket%20Red%20Sox&direction=send&limit=10')
    data = json.loads(resp.data)

    print(f"Riley Greene value: {data['player_value']}")
    print(f"\nTop 5 trade suggestions:")
    print("-" * 60)

    for pkg in data['packages'][:5]:
        receive_names = [r['name'] for r in pkg['receive']]
        print(f"Receive: {', '.join(receive_names)}")
        print(f"  Value diff: {pkg['value_diff']:+.1f} | Fit: {pkg['fit_score']} | Likely: {pkg.get('likelihood', 'N/A')}%")
        print()

import sys
sys.path.append(r'c:\Users\Alex\DiamondDynastiesTradeAnalyzer')
import app

def main():
    ok = app.load_trade_history()
    print('loaded', ok, 'trades:', len(app.completed_trades))
    for t in app.completed_trades:
        if 'Matthew Liberatore' in (str(t.get('team_a_sends')) + str(t.get('team_a_receives')) + str(t.get('team_b_sends')) + str(t.get('team_b_receives'))):
            import json
            print(json.dumps(t, indent=2))
            return
    print('No trade with Matthew Liberatore found')

if __name__ == '__main__':
    main()

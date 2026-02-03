with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    # Find CFR loading sections
    for i in range(len(lines)):
        if 'CFR' in lines[i] and 'path' in lines[i]:
            print(f"{i+1}: {lines[i].rstrip()}")

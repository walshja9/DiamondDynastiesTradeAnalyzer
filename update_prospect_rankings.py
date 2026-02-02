"""
Script to merge prospect rankings from multiple sources and update prospects.json.
This ensures the display rank matches the calculated value.
"""
import json
import csv
import glob
import os

def merge_prospect_rankings():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load current prospects.json
    json_path = os.path.join(script_dir, 'prospects.json')
    with open(json_path, 'r', encoding='utf-8') as f:
        json_rankings = json.load(f)
    print(f"Loaded {len(json_rankings)} prospects from prospects.json")

    # Load rankings from CSV files
    csv_rankings = {}
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
                count = 0
                for row in reader:
                    name = (row.get('Name') or row.get('Name_FG') or row.get('Player') or '').strip()
                    avg_rank_str = row.get('Avg Rank') or row.get('Rank') or row.get('Overall') or ''

                    if not name or not avg_rank_str:
                        continue

                    try:
                        avg_rank = float(avg_rank_str)
                        if name not in csv_rankings or avg_rank < csv_rankings[name]:
                            csv_rankings[name] = avg_rank
                            age_str = row.get('Age', '')
                            csv_metadata[name] = {
                                'position': row.get('Pos') or row.get('Position') or 'UTIL',
                                'age': int(age_str) if age_str and age_str.isdigit() else 0,
                                'mlb_team': row.get('Team') or row.get('Org') or 'N/A',
                            }
                            count += 1
                    except (ValueError, TypeError):
                        continue

            print(f"Loaded {count} prospects from {os.path.basename(csv_file)}")
        except Exception as e:
            print(f"Warning: Could not load {csv_file}: {e}")

    # Merge rankings - average when player is in both sources
    merged_rankings = {}
    all_names = set(json_rankings.keys()) | set(csv_rankings.keys())

    for name in all_names:
        json_rank = json_rankings.get(name)
        csv_rank = csv_rankings.get(name)

        if json_rank is not None and csv_rank is not None:
            merged_rankings[name] = (json_rank + csv_rank) / 2
        elif json_rank is not None:
            merged_rankings[name] = float(json_rank)
        else:
            merged_rankings[name] = csv_rank

    # Exclude graduated/MLB players
    EXCLUDED_PLAYERS = {
        "Munetaka Murakami", "Kazuma Okamoto", "Tatsuya Imai",
        "Ben Joyce", "Mick Abel", "Marcelo Mayer", "Roman Anthony",
        "Junior Caminero", "Nick Kurtz", "Jackson Chourio", "Jackson Holliday",
        "Wyatt Langford", "James Wood",
    }

    MAX_PROSPECT_AGE = 25

    # Sort and filter
    sorted_prospects = sorted(merged_rankings.items(), key=lambda x: x[1])

    filtered_prospects = []
    for name, avg_rank in sorted_prospects:
        if name in EXCLUDED_PLAYERS:
            print(f"  Excluding {name} (graduated/MLB player)")
            continue
        age = csv_metadata.get(name, {}).get('age', 0)
        if age > 0 and age > MAX_PROSPECT_AGE:
            print(f"  Excluding {name} (age {age} > {MAX_PROSPECT_AGE})")
            continue
        filtered_prospects.append((name, avg_rank))

    # Create new sequential rankings
    new_rankings = {}
    for new_rank, (name, old_avg_rank) in enumerate(filtered_prospects[:300], start=1):
        new_rankings[name] = new_rank

    print(f"\nMerged rankings: {len(new_rankings)} prospects")

    # Show top 20
    print("\nTop 20 prospects after merge:")
    for name, rank in list(new_rankings.items())[:20]:
        old_json = json_rankings.get(name, 'N/A')
        old_csv = csv_rankings.get(name, 'N/A')
        print(f"  #{rank}: {name} (was JSON #{old_json}, CSV #{old_csv})")

    # Save new prospects.json
    output_path = os.path.join(script_dir, 'prospects.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(new_rankings, f, indent=4)

    print(f"\nSaved updated prospects.json with {len(new_rankings)} prospects")
    return new_rankings

if __name__ == '__main__':
    merge_prospect_rankings()

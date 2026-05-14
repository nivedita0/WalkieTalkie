#!/usr/bin/env python3
"""
Analyze evaluation results to compare small vs large model performance.
Extracts latency, quality, and per-tier metrics from JSONL result files.
"""

import json
from pathlib import Path
from collections import defaultdict
import statistics

def load_results(filepath):
    """Load JSONL results from file."""
    results = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results

def analyze_results(results):
    """Analyze results by tier and city."""
    by_tier = defaultdict(list)
    by_tier_city = defaultdict(lambda: defaultdict(list))

    for result in results:
        tier = result.get('tier', 'unknown')
        query_id = result.get('query_id', '')
        elapsed = result.get('elapsed_sec', -1)

        # Extract city from query_id (san01 -> San Francisco, kol01 -> Kolkata)
        if query_id.startswith('san'):
            city = 'San Francisco'
        elif query_id.startswith('kol'):
            city = 'Kolkata'
        elif query_id.startswith('inj'):
            city = 'Injection Test'
        else:
            city = 'Unknown'

        if elapsed > 0:
            by_tier[tier].append(elapsed)
            by_tier_city[tier][city].append(elapsed)

    return by_tier, by_tier_city

def print_report(by_tier, by_tier_city):
    """Print comparison report."""
    print("\n" + "="*80)
    print("WALKIE-TALKIE MODEL COMPARISON REPORT")
    print("="*80)

    print("\n### OVERALL METRICS BY TIER ###\n")

    tiers = sorted(by_tier.keys())
    for tier in tiers:
        latencies = by_tier[tier]
        if latencies:
            count = len(latencies)
            mean = statistics.mean(latencies)
            median = statistics.median(latencies)
            p90 = sorted(latencies)[int(len(latencies)*0.9)]
            min_lat = min(latencies)
            max_lat = max(latencies)

            print(f"\n**{tier.upper()} TIER:**")
            print(f"  Query Count:     {count}")
            print(f"  Mean Latency:    {mean:.2f}s")
            print(f"  Median (p50):    {median:.2f}s")
            print(f"  p90:             {p90:.2f}s")
            print(f"  Min:             {min_lat:.2f}s")
            print(f"  Max:             {max_lat:.2f}s")

    print("\n### BREAKDOWN BY CITY & TIER ###\n")

    for tier in tiers:
        print(f"\n**{tier.upper()} TIER - By City:**")
        for city in sorted(by_tier_city[tier].keys()):
            latencies = by_tier_city[tier][city]
            if latencies:
                mean = statistics.mean(latencies)
                count = len(latencies)
                print(f"  {city:20s}: {count:3d} queries, {mean:7.2f}s avg")

def main():
    eval_dir = Path(__file__).parent / "results"

    # Find all JSONL result files
    result_files = sorted(eval_dir.glob("eval_*.jsonl"), reverse=True)

    print(f"Found {len(result_files)} result files")

    if not result_files:
        print("No result files found!")
        return

    # Load and analyze all results
    all_results = []
    for result_file in result_files:
        print(f"  Loading: {result_file.name}")
        results = load_results(result_file)
        all_results.extend(results)

    print(f"\nTotal records loaded: {len(all_results)}")

    # Analyze
    by_tier, by_tier_city = analyze_results(all_results)

    # Print report
    print_report(by_tier, by_tier_city)

    # Comparison summary
    print("\n" + "="*80)
    print("COMPARISON SUMMARY")
    print("="*80)

    if 'small' in by_tier and 'large' in by_tier:
        small_mean = statistics.mean(by_tier['small'])
        large_mean = statistics.mean(by_tier['large'])
        diff = large_mean - small_mean
        pct_diff = (diff / small_mean * 100) if small_mean > 0 else 0

        print(f"\nSmall Model: {small_mean:.2f}s mean latency ({len(by_tier['small'])} queries)")
        print(f"Large Model: {large_mean:.2f}s mean latency ({len(by_tier['large'])} queries)")
        print(f"Difference:  {diff:+.2f}s ({pct_diff:+.1f}%)")
        print(f"\nNote: Large model is {'SLOWER' if diff > 0 else 'FASTER'} by {abs(diff):.2f}s on average")
    else:
        print("\nInsufficient data: Need both small and large tier results for comparison")

if __name__ == "__main__":
    main()

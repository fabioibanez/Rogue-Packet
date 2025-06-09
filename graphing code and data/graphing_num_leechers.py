import json
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
import argparse
try:
    from scipy import stats as scipy_stats
except ImportError:
    print("Warning: scipy not available. Confidence intervals will not be calculated.")
    scipy_stats = None

def load_experiment_data(json_file):
    """Load experiment data from JSON file."""
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Error: File '{json_file}' not found")
        return None
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in file '{json_file}'")
        return None

def group_experiments_by_leechers(experiments):
    """Group experiments by number of leechers, treating each node as a separate data point."""
    grouped = defaultdict(list)
    
    for experiment in experiments:
        # Extract number of leechers from args
        num_leechers = experiment['args']['leechers']
        
        # Treat each node as a separate data point - calculate throughput
        for node_result in experiment['results']:
            bytes_transferred = node_result['bytes']
            time_seconds = node_result['seconds']
            # Convert to KB/s
            throughput_kbps = (bytes_transferred / 1024) / time_seconds
            grouped[num_leechers].append(throughput_kbps)
    
    # Calculate mean, std, and confidence intervals for each number of leechers
    stats = {}
    for leechers, throughputs in grouped.items():
        n = len(throughputs)
        mean_throughput = np.mean(throughputs)
        std_throughput = np.std(throughputs, ddof=1) if n > 1 else 0  # Sample standard deviation
        
        # Calculate 95% confidence interval
        if n > 1 and scipy_stats:
            confidence_level = 0.95
            degrees_freedom = n - 1
            confidence_interval = scipy_stats.t.interval(
                confidence_level, degrees_freedom, 
                loc=mean_throughput, scale=std_throughput/np.sqrt(n)
            )
        else:
            confidence_interval = (mean_throughput, mean_throughput)
        
        stats[leechers] = {
            'mean': mean_throughput,
            'std': std_throughput,
            'count': n,
            'throughputs': throughputs,
            'confidence_interval': confidence_interval,
            'min': min(throughputs),
            'max': max(throughputs)
        }
    
    return stats

def plot_leechers_vs_throughput(stats, output_file=None, show_individual_points=True):
    """Plot number of leechers vs average throughput with confidence intervals."""
    # Sort by number of leechers
    sorted_leechers = sorted(stats.keys())
    means = [stats[leechers]['mean'] for leechers in sorted_leechers]
    stds = [stats[leechers]['std'] for leechers in sorted_leechers]
    counts = [stats[leechers]['count'] for leechers in sorted_leechers]
    confidence_intervals = [stats[leechers]['confidence_interval'] for leechers in sorted_leechers]
    
    # Extract confidence interval bounds
    ci_lower = [ci[0] for ci in confidence_intervals]
    ci_upper = [ci[1] for ci in confidence_intervals]
    ci_errors = [[mean - lower for mean, lower in zip(means, ci_lower)],
                 [upper - mean for mean, upper in zip(means, ci_upper)]]
    
    plt.figure(figsize=(12, 8))
    
    # Plot individual data points if requested
    if show_individual_points:
        for leechers in sorted_leechers:
            throughputs = stats[leechers]['throughputs']
            # Add small random jitter to x-axis for visibility
            x_jitter = np.random.normal(leechers, 0.3, len(throughputs))
            plt.scatter(x_jitter, throughputs, alpha=0.6, color='lightblue', s=40, 
                       label='Individual nodes' if leechers == sorted_leechers[0] else "")
    
    # Plot mean with confidence interval error bars
    plt.errorbar(sorted_leechers, means, yerr=ci_errors, 
                marker='o', linewidth=2, markersize=10, capsize=8, capthick=3,
                color='darkblue', ecolor='blue', label='Mean ± 95% CI')
    
    # Connect points with a line
    plt.plot(sorted_leechers, means, '--', alpha=0.7, color='red', linewidth=2)
    
    # Annotations for sample sizes
    for i, (leechers, count) in enumerate(zip(sorted_leechers, counts)):
        plt.annotate(f'n={count}', (leechers, means[i]), 
                    textcoords="offset points", xytext=(0,15), ha='center', 
                    fontsize=10, fontweight='bold')
    
    plt.xlabel('Number of Leechers', fontsize=14)
    plt.ylabel('Average Throughput (KB/s)', fontsize=14)
    plt.title('BitTorrent Throughput vs Number of Leechers\n(Each Node Treated as Independent Sample)', 
              fontsize=16, pad=20)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=12)
    
    # Add summary statistics as text
    total_nodes = sum(counts)
    total_experiments = len(sorted_leechers)
    plt.text(0.02, 0.98, f'Total Nodes: {total_nodes}\nTotal Experiments: {total_experiments}', 
             transform=plt.gca().transAxes, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8), fontsize=11)
    
    # Set reasonable axis limits
    plt.ylim(0, max(means) * 1.3)  # Dynamic upper limit based on data
    plt.xlim(min(sorted_leechers) - 1, max(sorted_leechers) + 1)
    
    plt.tight_layout()
    
    if output_file:
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Plot saved to: {output_file}")
    
    plt.show()

def print_summary_statistics(stats):
    """Print summary statistics for the experiments."""
    print("="*95)
    print("EXPERIMENT SUMMARY STATISTICS (Throughput in KB/s vs Number of Leechers)")
    print("="*95)
    
    sorted_leechers = sorted(stats.keys())
    
    print(f"{'Leechers':<10} {'Mean (KB/s)':<14} {'Std Dev':<12} {'Count':<8} {'Min':<10} {'Max':<10} {'95% CI':<25}")
    print("-" * 95)
    
    for leechers in sorted_leechers:
        mean_throughput = stats[leechers]['mean']
        std_throughput = stats[leechers]['std']
        count = stats[leechers]['count']
        min_throughput = stats[leechers]['min']
        max_throughput = stats[leechers]['max']
        ci_lower, ci_upper = stats[leechers]['confidence_interval']
        ci_str = f"[{ci_lower:.3f}, {ci_upper:.3f}]"
        
        print(f"{leechers:<10} {mean_throughput:<14.3f} {std_throughput:<12.3f} {count:<8} "
              f"{min_throughput:<10.3f} {max_throughput:<10.3f} {ci_str:<25}")
    
    # Overall statistics
    all_throughputs = []
    total_experiments = len(sorted_leechers)
    for leecher_stats in stats.values():
        all_throughputs.extend(leecher_stats['throughputs'])
    
    print("\n" + "-" * 95)
    print(f"Overall Statistics:")
    print(f"  Total Leecher Count Levels: {total_experiments}")
    print(f"  Total Individual Nodes: {len(all_throughputs)}")
    print(f"  Overall Mean: {np.mean(all_throughputs):.3f} KB/s")
    print(f"  Overall Std Dev: {np.std(all_throughputs, ddof=1):.3f} KB/s")
    print(f"  Min Node Throughput: {min(all_throughputs):.3f} KB/s")
    print(f"  Max Node Throughput: {max(all_throughputs):.3f} KB/s")

def analyze_throughput_trends(stats):
    """Analyze and print throughput trends."""
    sorted_leechers = sorted(stats.keys())
    means = [stats[leechers]['mean'] for leechers in sorted_leechers]
    
    print("\n" + "="*60)
    print("THROUGHPUT TREND ANALYSIS")
    print("="*60)
    
    print(f"{'Leechers':<10} {'Mean Throughput':<18} {'Change from Previous':<20}")
    print("-" * 60)
    
    for i, leechers in enumerate(sorted_leechers):
        mean_throughput = means[i]
        if i == 0:
            change_str = "baseline"
        else:
            prev_mean = means[i-1]
            change = mean_throughput - prev_mean
            change_pct = (change / prev_mean) * 100
            change_str = f"{change:+.3f} KB/s ({change_pct:+.1f}%)"
        
        print(f"{leechers:<10} {mean_throughput:<18.3f} {change_str:<20}")
    
    # Overall trend
    if len(means) >= 2:
        overall_change = means[-1] - means[0]
        overall_pct = (overall_change / means[0]) * 100
        print(f"\nOverall trend from {sorted_leechers[0]} to {sorted_leechers[-1]} leechers:")
        print(f"  Change: {overall_change:+.3f} KB/s ({overall_pct:+.1f}%)")
        
        # Linear correlation
        correlation = np.corrcoef(sorted_leechers, means)[0, 1]
        print(f"  Correlation coefficient: {correlation:.3f}")
        
        if correlation < -0.5:
            trend = "Strong negative correlation (more leechers → lower throughput)"
        elif correlation < -0.2:
            trend = "Weak negative correlation"
        elif correlation > 0.5:
            trend = "Strong positive correlation (more leechers → higher throughput)"
        elif correlation > 0.2:
            trend = "Weak positive correlation"
        else:
            trend = "No clear correlation"
        
        print(f"  Interpretation: {trend}")

def create_sample_data():
    """Create sample data for demonstration based on the actual data structure."""
    import random
    
    sample_experiments = []
    leecher_counts = [1, 5, 10, 15, 20, 25, 30]
    
    for leechers in leecher_counts:
        results = []
        
        # Generate results for each leecher node
        for node_num in range(2, leechers + 2):  # h2 to h(leechers+1)
            # More leechers generally means more competition and potentially lower individual throughput
            base_throughput_kbps = 120.0 - (leechers * 2.0)  # Decreasing with more leechers
            base_throughput_kbps = max(10.0, base_throughput_kbps)  # Minimum 10 KB/s
            
            throughput_variation = random.uniform(0.5, 1.5)
            node_throughput = base_throughput_kbps * throughput_variation
            node_throughput = max(5.0, node_throughput)  # Minimum 5 KB/s
            
            # Convert back to time for the JSON structure (assuming 2MB file)
            file_size_kb = 2048  # 2MB in KB
            download_time = file_size_kb / node_throughput
            
            results.append({
                "node": f"h{node_num}",
                "bytes": 2097152,  # 2MB in bytes
                "seconds": download_time
            })
        
        experiment = {
            "args": {
                "torrent_file": "torrents/torrent_1.dat.torrent",
                "verbose": False,
                "deletetorrent": False,
                "seed": False,
                "seeders": 1,
                "leechers": leechers,
                "topology": "single",
                "delay": "0ms",
                "seeder_file": "seeder_sources/torrent_1.dat",
                "no_auto_install": False,
                "experiments_file": "experiments.json",
                "markov_prob": None,
                "overall_loss": 0,
                "timeout": 240.0
            },
            "results": results
        }
        sample_experiments.append(experiment)
    
    return sample_experiments

def main():
    parser = argparse.ArgumentParser(description='Plot number of leechers vs throughput')
    parser.add_argument('json_file', nargs='?', help='JSON file containing experiment results')
    parser.add_argument('-o', '--output', help='Output file for the plot (e.g., plot.png)')
    parser.add_argument('--no-points', action='store_true', help='Hide individual data points')
    parser.add_argument('--sample', action='store_true', help='Generate and use sample data')
    parser.add_argument('--no-trend', action='store_true', help='Skip trend analysis')
    
    args = parser.parse_args()
    
    if args.sample:
        print("Generating sample data...")
        experiments = create_sample_data()
        print(f"Generated {len(experiments)} sample experiments")
    elif args.json_file:
        experiments = load_experiment_data(args.json_file)
        if experiments is None:
            return
    else:
        print("Error: Please provide a JSON file or use --sample to generate sample data")
        parser.print_help()
        return
    
    # Group experiments by number of leechers
    stats = group_experiments_by_leechers(experiments)
    
    if not stats:
        print("No valid experiment data found")
        return
    
    # Print summary statistics
    print_summary_statistics(stats)
    
    # Analyze trends
    if not args.no_trend:
        analyze_throughput_trends(stats)
    
    # Create plot
    plot_leechers_vs_throughput(stats, args.output, not args.no_points)

if __name__ == "__main__":
    main()
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

def calculate_average_download_time(results):
    """Calculate average download time from results."""
    if not results:
        return 0
    
    total_time = sum(node['seconds'] for node in results)
    return total_time / len(results)

def group_experiments_by_markov_prob(experiments):
    """Group experiments by markov_prob, treating each node as a separate data point."""
    grouped = defaultdict(list)
    
    for experiment in experiments:
        markov_prob = experiment['args']['markov_prob']
        
        # Treat each node as a separate data point - calculate throughput
        for node_result in experiment['results']:
            bytes_transferred = node_result['bytes']
            time_seconds = node_result['seconds']
            # Convert to MB/s (bytes -> MB by dividing by 1024*1024)
            # Change from MB/s to KB/s
            throughput_kbps = (bytes_transferred / 1024) / time_seconds
            grouped[markov_prob].append(throughput_kbps)

    
    # Calculate mean, std, and confidence intervals for each markov_prob
    stats = {}
    for prob, throughputs in grouped.items():
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
        
        stats[prob] = {
            'mean': mean_throughput,
            'std': std_throughput,
            'count': n,
            'throughputs': throughputs,  # Changed from 'times' to 'throughputs'
            'confidence_interval': confidence_interval,
            'min': min(throughputs),
            'max': max(throughputs)
        }
    
    return stats

def plot_markov_vs_download_time(stats, output_file=None, show_individual_points=True):
    """Plot Markov probability vs average throughput with confidence intervals."""
    # Sort by markov probability
    sorted_probs = sorted(stats.keys())
    means = [stats[prob]['mean'] for prob in sorted_probs]
    stds = [stats[prob]['std'] for prob in sorted_probs]
    counts = [stats[prob]['count'] for prob in sorted_probs]
    confidence_intervals = [stats[prob]['confidence_interval'] for prob in sorted_probs]
    
    # Extract confidence interval bounds
    ci_lower = [ci[0] for ci in confidence_intervals]
    ci_upper = [ci[1] for ci in confidence_intervals]
    ci_errors = [[mean - lower for mean, lower in zip(means, ci_lower)],
                 [upper - mean for mean, upper in zip(means, ci_upper)]]
    
    plt.figure(figsize=(12, 8))
    
    # Plot individual data points if requested
    if show_individual_points:
        for prob in sorted_probs:
            throughputs = stats[prob]['throughputs']
            # Add small random jitter to x-axis for visibility
            x_jitter = np.random.normal(prob, 0.01, len(throughputs))
            plt.scatter(x_jitter, throughputs, alpha=0.6, color='lightblue', s=40, 
                       label='Individual nodes' if prob == sorted_probs[0] else "")
    
    # Plot mean with confidence interval error bars
    plt.errorbar(sorted_probs, means, yerr=ci_errors, 
                marker='o', linewidth=2, markersize=10, capsize=8, capthick=3,
                color='darkblue', ecolor='blue', label='Mean ± 95% CI')
    
    # Connect points with a line
    plt.plot(sorted_probs, means, '--', alpha=0.7, color='red', linewidth=2)
    
    # Annotations for sample sizes
    for i, (prob, count) in enumerate(zip(sorted_probs, counts)):
        plt.annotate(f'n={count}', (prob, means[i]), 
                    textcoords="offset points", xytext=(0,15), ha='center', 
                    fontsize=10, fontweight='bold')
    
    plt.xlabel('Transition Probability p', fontsize=14)
    plt.ylabel('Average Throughput (KB/s)', fontsize=14)
    plt.title('BitTorrent Throughput vs Network Interference\n(Each Node Treated as Independent Sample)', 
              fontsize=16, pad=20)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=12)
    
    # Add summary statistics as text
    total_nodes = sum(counts)
    total_experiments = len(set(prob for prob in sorted_probs))
    plt.text(0.02, 0.98, f'Total Nodes: {total_nodes}\nTotal Experiments: {total_experiments}', 
             transform=plt.gca().transAxes, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8), fontsize=11)
    
    plt.tight_layout()
    
    if output_file:
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Plot saved to: {output_file}")

    
    plt.ylim(0,70)
    plt.show()

def print_summary_statistics(stats):
    """Print summary statistics for the experiments."""
    print("="*90)
    print("EXPERIMENT SUMMARY STATISTICS (Throughput in KB/s - Each Node as Independent Sample)")
    print("="*90)
    
    sorted_probs = sorted(stats.keys())
    
    print(f"{'Markov Prob':<12} {'Mean (KB/s)':<14} {'Std Dev':<12} {'Count':<8} {'Min':<10} {'Max':<10} {'95% CI':<25}")
    print("-" * 85)
    
    for prob in sorted_probs:
        mean_throughput = stats[prob]['mean']
        std_throughput = stats[prob]['std']
        count = stats[prob]['count']
        min_throughput = stats[prob]['min']
        max_throughput = stats[prob]['max']
        ci_lower, ci_upper = stats[prob]['confidence_interval']
        ci_str = f"[{ci_lower:.3f}, {ci_upper:.3f}]"
        
        print(f"{prob:<12.2f} {mean_throughput:<14.3f} {std_throughput:<12.3f} {count:<8} "f"{min_throughput:<10.3f} {max_throughput:<10.3f} {ci_str:<25}")
    
    # Overall statistics
    all_throughputs = []
    total_experiments = len(sorted_probs)
    for prob_stats in stats.values():
        all_throughputs.extend(prob_stats['throughputs'])
    
    print("\n" + "-" * 85)
    print(f"Overall Statistics:")
    print(f"  Total Markov Probability Levels: {total_experiments}")
    print(f"  Total Individual Nodes: {len(all_throughputs)}")
    print(f"  Overall Mean: {np.mean(all_throughputs):.3f} KB/s")
    print(f"  Overall Std Dev: {np.std(all_throughputs, ddof=1):.3f} KB/s")
    print(f"  Min Node Throughput: {min(all_throughputs):.3f} KB/s")
    print(f"  Max Node Throughput: {max(all_throughputs):.3f} KB/s")

def create_sample_data():
    """Create sample data for demonstration."""
    import random
    
    # Sample data with different markov probabilities
    sample_experiments = []
    
    markov_probs = [0.1, 0.3, 0.5, 0.7, 0.9]
    
    for prob in markov_probs:
        # Simulate 3-5 experiments per probability
        for _ in range(random.randint(3, 5)):
            # Base time increases with higher interference probability
            base_time = 15 + (prob * 20)  # 15-35 seconds base
            
            results = []
            for node_num in range(2, 6):  # h2 to h5
                # Add some randomness - higher probability = lower throughput
                base_throughput = 3.0 - (prob * 2.0)  # 3.0 MB/s at p=0, 1.0 MB/s at p=1
                throughput_variation = random.uniform(0.8, 1.2)
                node_throughput = base_throughput * throughput_variation + random.uniform(-0.2, 0.2)
                node_throughput = max(0.1, node_throughput)  # Minimum 0.1 MB/s
                
                # Convert back to time for the JSON structure (assuming 2MB file)
                file_size_mb = 2.0  # 2MB file
                download_time = file_size_mb / node_throughput
                
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
                    "leechers": 4,
                    "topology": "single",
                    "delay": "0ms",
                    "seeder_file": "seeder_sources/torrent_1.dat",
                    "no_auto_install": False,
                    "experiments_file": "experiments.json",
                    "markov_prob": prob
                },
                "results": results
            }
            sample_experiments.append(experiment)
    
    return sample_experiments

def main():
    parser = argparse.ArgumentParser(description='Plot Markov probability vs download time')
    parser.add_argument('json_file', nargs='?', help='JSON file containing experiment results')
    parser.add_argument('-o', '--output', help='Output file for the plot (e.g., plot.png)')
    parser.add_argument('--no-points', action='store_true', help='Hide individual data points')
    parser.add_argument('--sample', action='store_true', help='Generate and use sample data')
    
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
    
    # Group experiments by markov probability
    stats = group_experiments_by_markov_prob(experiments)
    
    if not stats:
        print("No valid experiment data found")
        return
    
    # Print summary statistics
    print_summary_statistics(stats)
    
    # Create plot
    plot_markov_vs_download_time(stats, args.output, not args.no_points)

if __name__ == "__main__":
    main()
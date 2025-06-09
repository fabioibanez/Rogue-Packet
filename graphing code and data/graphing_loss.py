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

def group_experiments_by_packet_loss(experiments):
    """Group experiments by overall_loss, treating each node as a separate data point."""
    grouped = defaultdict(list)
    
    for experiment in experiments:
        # Extract packet loss rate from args
        packet_loss_rate = experiment['args']['overall_loss']
        
        # Treat each node as a separate data point - calculate throughput
        for node_result in experiment['results']:
            bytes_transferred = node_result['bytes']
            time_seconds = node_result['seconds']
            # Convert to KB/s
            throughput_kbps = (bytes_transferred / 1024) / time_seconds
            grouped[packet_loss_rate].append(throughput_kbps)
    
    # Calculate mean, std, and confidence intervals for each packet loss rate
    stats = {}
    for loss_rate, throughputs in grouped.items():
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
        
        stats[loss_rate] = {
            'mean': mean_throughput,
            'std': std_throughput,
            'count': n,
            'throughputs': throughputs,
            'confidence_interval': confidence_interval,
            'min': min(throughputs),
            'max': max(throughputs)
        }
    
    return stats

def plot_packet_loss_vs_throughput(stats, output_file=None, show_individual_points=True):
    """Plot packet loss rate vs average throughput with confidence intervals."""
    # Sort by packet loss rate
    sorted_loss_rates = sorted(stats.keys())
    means = [stats[rate]['mean'] for rate in sorted_loss_rates]
    stds = [stats[rate]['std'] for rate in sorted_loss_rates]
    counts = [stats[rate]['count'] for rate in sorted_loss_rates]
    confidence_intervals = [stats[rate]['confidence_interval'] for rate in sorted_loss_rates]
    
    # Extract confidence interval bounds
    ci_lower = [ci[0] for ci in confidence_intervals]
    ci_upper = [ci[1] for ci in confidence_intervals]
    ci_errors = [[mean - lower for mean, lower in zip(means, ci_lower)],
                 [upper - mean for mean, upper in zip(means, ci_upper)]]
    
    plt.figure(figsize=(12, 8))
    
    # Plot individual data points if requested
    if show_individual_points:
        for loss_rate in sorted_loss_rates:
            throughputs = stats[loss_rate]['throughputs']
            # Add small random jitter to x-axis for visibility
            x_jitter = np.random.normal(loss_rate, 0.001, len(throughputs))  # Smaller jitter for loss rates
            plt.scatter(x_jitter, throughputs, alpha=0.6, color='lightblue', s=40, 
                       label='Individual nodes' if loss_rate == sorted_loss_rates[0] else "")
    
    # Plot mean with confidence interval error bars
    plt.errorbar(sorted_loss_rates, means, yerr=ci_errors, 
                marker='o', linewidth=2, markersize=10, capsize=8, capthick=3,
                color='darkblue', ecolor='blue', label='Mean ± 95% CI')
    
    # Connect points with a line
    plt.plot(sorted_loss_rates, means, '--', alpha=0.7, color='red', linewidth=2)
    
    # Annotations for sample sizes
    for i, (loss_rate, count) in enumerate(zip(sorted_loss_rates, counts)):
        plt.annotate(f'n={count}', (loss_rate, means[i]), 
                    textcoords="offset points", xytext=(0,15), ha='center', 
                    fontsize=10, fontweight='bold')
    
    plt.xlabel('Packet Loss Rate (%)', fontsize=14)
    plt.ylabel('Average Throughput (KB/s)', fontsize=14)
    plt.title('BitTorrent Throughput vs Packet Loss Rate\n(Each Node Treated as Independent Sample)', 
              fontsize=16, pad=20)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=12)
    
    # Add summary statistics as text
    total_nodes = sum(counts)
    total_experiments = len(set(rate for rate in sorted_loss_rates))
    plt.text(0.02, 0.98, f'Total Nodes: {total_nodes}\nTotal Experiments: {total_experiments}', 
             transform=plt.gca().transAxes, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8), fontsize=11)
    
    # Set y-axis limit
    plt.ylim(0, max(means) * 1.2)  # Dynamic upper limit based on data
    
    plt.tight_layout()
    
    if output_file:
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Plot saved to: {output_file}")
    
    plt.show()

def print_summary_statistics(stats):
    """Print summary statistics for the experiments."""
    print("="*95)
    print("EXPERIMENT SUMMARY STATISTICS (Throughput in KB/s vs Packet Loss Rate)")
    print("="*95)
    
    sorted_loss_rates = sorted(stats.keys())
    
    print(f"{'Loss Rate (%)':<12} {'Mean (KB/s)':<14} {'Std Dev':<12} {'Count':<8} {'Min':<10} {'Max':<10} {'95% CI':<25}")
    print("-" * 95)
    
    for loss_rate in sorted_loss_rates:
        mean_throughput = stats[loss_rate]['mean']
        std_throughput = stats[loss_rate]['std']
        count = stats[loss_rate]['count']
        min_throughput = stats[loss_rate]['min']
        max_throughput = stats[loss_rate]['max']
        ci_lower, ci_upper = stats[loss_rate]['confidence_interval']
        ci_str = f"[{ci_lower:.3f}, {ci_upper:.3f}]"
        
        print(f"{loss_rate:<12.2f} {mean_throughput:<14.3f} {std_throughput:<12.3f} {count:<8} "
              f"{min_throughput:<10.3f} {max_throughput:<10.3f} {ci_str:<25}")
    
    # Overall statistics
    all_throughputs = []
    total_experiments = len(sorted_loss_rates)
    for rate_stats in stats.values():
        all_throughputs.extend(rate_stats['throughputs'])
    
    print("\n" + "-" * 95)
    print(f"Overall Statistics:")
    print(f"  Total Packet Loss Rate Levels: {total_experiments}")
    print(f"  Total Individual Nodes: {len(all_throughputs)}")
    print(f"  Overall Mean: {np.mean(all_throughputs):.3f} KB/s")
    print(f"  Overall Std Dev: {np.std(all_throughputs, ddof=1):.3f} KB/s")
    print(f"  Min Node Throughput: {min(all_throughputs):.3f} KB/s")
    print(f"  Max Node Throughput: {max(all_throughputs):.3f} KB/s")

def create_sample_data():
    """Create sample data for demonstration."""
    import random
    
    # Sample data with different packet loss rates
    sample_experiments = []
    
    loss_rates = [0.5, 2.0, 5.0, 10.0, 15.0]  # Packet loss rates in %
    
    for loss_rate in loss_rates:
        # Simulate 3-5 experiments per loss rate
        for _ in range(random.randint(3, 5)):
            results = []
            for node_num in range(2, 6):  # h2 to h5
                # Higher packet loss = lower throughput
                base_throughput_kbps = 60.0 - (loss_rate * 3.0)  # 60 KB/s at 0% loss, decreasing
                throughput_variation = random.uniform(0.8, 1.2)
                node_throughput = base_throughput_kbps * throughput_variation + random.uniform(-5, 5)
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
                    "leechers": 4,
                    "topology": "single",
                    "delay": "0ms",
                    "seeder_file": "seeder_sources/torrent_1.dat",
                    "no_auto_install": False,
                    "experiments_file": "experiments.json",
                    "overall_loss": loss_rate  # Changed from markov_prob to overall_loss
                },
                "results": results
            }
            sample_experiments.append(experiment)
    
    return sample_experiments

def main():
    parser = argparse.ArgumentParser(description='Plot packet loss rate vs throughput')
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
    
    # Group experiments by packet loss rate
    stats = group_experiments_by_packet_loss(experiments)
    
    if not stats:
        print("No valid experiment data found")
        return
    
    # Print summary statistics
    print_summary_statistics(stats)
    
    # Create plot
    plot_packet_loss_vs_throughput(stats, args.output, not args.no_points)

if __name__ == "__main__":
    main()
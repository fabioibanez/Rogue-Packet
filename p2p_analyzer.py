#!/usr/bin/env python3
"""
P2P Performance Analysis Tool
Compares PropShare vs BitTorrent download performance across different client compositions.

File Structure:
experiment_data/
├── config.json                 # Configuration file
├── logs/                      # Experiment directories
│   ├── exp_000_prop0.0/       # All faithful clients
│   │   ├── client_001.csv
│   │   ├── client_002.csv
│   │   └── ...
│   ├── exp_001_prop0.2/       # 20% PropShare clients
│   │   ├── client_001.csv
│   │   ├── client_002.csv
│   │   └── ...
│   └── exp_005_prop1.0/       # All PropShare clients
│       ├── client_001.csv
│       └── ...
└── results/                   # Output directory
    ├── performance_analysis.png
    ├── comparison_charts.png
    └── summary_stats.json
"""

import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import argparse
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

class P2PPerformanceAnalyzer:
    """Analyzes P2P protocol performance from experimental data."""
    
    def __init__(self, config_path: str, logs_dir: str, output_dir: str = "results"):
        """
        Initialize the analyzer.
        
        Args:
            config_path: Path to configuration JSON file
            logs_dir: Directory containing CSV log files
            output_dir: Directory for output files
        """
        self.config_path = Path(config_path)
        self.logs_dir = Path(logs_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Load configuration
        with open(self.config_path, 'r') as f:
            self.config = json.load(f)
        
        print(f"Loaded {len(self.config)} experimental configurations")
        print(f"Experiment logs base directory: {self.logs_dir}")
    
    def parse_client_log(self, csv_path: Path) -> Optional[Dict]:
        """
        Parse a single client CSV log file.
        
        Expected CSV format:
        file_path,size,time
        /path/to/file1,1024,0.5
        /path/to/file2,2048,1.2
        
        Returns:
            Dict with download_time, final_size, start_time, end_time
        """
        try:
            # Read CSV with flexible column detection
            df = pd.read_csv(csv_path)
            
            # Handle different possible column names
            col_mapping = {}
            for col in df.columns:
                col_lower = col.lower().strip()
                if 'path' in col_lower or 'file' in col_lower:
                    col_mapping['file_path'] = col
                elif 'size' in col_lower:
                    col_mapping['size'] = col
                elif 'time' in col_lower:
                    col_mapping['time'] = col
            
            # Use original column names if mapping not found
            if 'size' not in col_mapping:
                col_mapping['size'] = df.columns[1] if len(df.columns) > 1 else df.columns[0]
            if 'time' not in col_mapping:
                col_mapping['time'] = df.columns[2] if len(df.columns) > 2 else df.columns[-1]
            
            # Extract data
            sizes = pd.to_numeric(df[col_mapping['size']], errors='coerce').dropna()
            times = pd.to_numeric(df[col_mapping['time']], errors='coerce').dropna()
            
            if len(times) == 0 or len(sizes) == 0:
                print(f"Warning: No valid data in {csv_path}")
                return None
            
            # Calculate metrics
            start_time = times.min()
            end_time = times.max()
            download_time = end_time - start_time
            final_size = sizes.max()
            
            return {
                'download_time': download_time,
                'final_size': final_size,
                'start_time': start_time,
                'end_time': end_time,
                'data_points': len(times)
            }
            
        except Exception as e:
            print(f"Error parsing {csv_path}: {e}")
            return None
    
    def analyze_configuration(self, config: Dict, exp_index: int) -> Dict:
        """
        Analyze a single experimental configuration.
        
        Args:
            config: Configuration dict with propshare_ids and faithful_ids
            exp_index: Index of the experiment for directory lookup
            
        Returns:
            Dict with analysis results
        """
        propshare_times = []
        faithful_times = []
        processed_files = {'propshare': [], 'faithful': []}
        
        # Process PropShare clients (paths like "exp_000_prop0.0/client_001.csv")
        for client_path in config.get('propshare_ids', []):
            full_path = self.logs_dir / client_path
            if full_path.exists():
                result = self.parse_client_log(full_path)
                if result:
                    propshare_times.append(result['download_time'])
                    processed_files['propshare'].append(client_path)
            else:
                print(f"Warning: PropShare client file not found: {full_path}")
        
        # Process Faithful (BitTorrent) clients
        for client_path in config.get('faithful_ids', []):
            full_path = self.logs_dir / client_path
            if full_path.exists():
                result = self.parse_client_log(full_path)
                if result:
                    faithful_times.append(result['download_time'])
                    processed_files['faithful'].append(client_path)
            else:
                print(f"Warning: Faithful client file not found: {full_path}")
        
        # Calculate statistics
        def calc_stats(times_list):
            if not times_list:
                return {'mean': np.nan, 'std': np.nan, 'count': 0}
            return {
                'mean': np.mean(times_list),
                'std': np.std(times_list, ddof=1) if len(times_list) > 1 else 0,
                'count': len(times_list)
            }
        
        propshare_stats = calc_stats(propshare_times)
        faithful_stats = calc_stats(faithful_times)
        
        # Calculate propshare fraction
        total_clients = len(config.get('propshare_ids', [])) + len(config.get('faithful_ids', []))
        propshare_fraction = len(config.get('propshare_ids', [])) / total_clients if total_clients > 0 else 0
        
        # Extract experiment info from first file path
        exp_directory = None
        if config.get('propshare_ids') or config.get('faithful_ids'):
            first_path = (config.get('propshare_ids') + config.get('faithful_ids'))[0]
            exp_directory = first_path.split('/')[0] if '/' in first_path else 'unknown'
        
        print(f"Processing experiment {exp_index}: {exp_directory} "
              f"(PropShare: {len(propshare_times)}, Faithful: {len(faithful_times)})")
        
        return {
            'propshare_fraction': propshare_fraction,
            'propshare': propshare_stats,
            'faithful': faithful_stats,
            'total_clients': total_clients,
            'exp_directory': exp_directory,
            'processed_files': processed_files
        }
    
    def run_analysis(self) -> List[Dict]:
        """Run analysis on all configurations."""
        results = []
        
        print("Analyzing configurations...")
        for i, config in enumerate(self.config):
            print(f"Processing configuration {i+1}/{len(self.config)}")
            result = self.analyze_configuration(config, i)
            results.append(result)
        
        return results
    
    def create_performance_comparison_plot(self, results: List[Dict]):
        """Create the main performance comparison plot matching the original figure."""
        # Set up the plot style
        plt.style.use('default')
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # Extract data for plotting
        fractions = [r['propshare_fraction'] for r in results]
        
        # PropShare data (circles with dashed lines)
        prop_means = [r['propshare']['mean'] for r in results if not np.isnan(r['propshare']['mean'])]
        prop_stds = [r['propshare']['std'] for r in results if not np.isnan(r['propshare']['mean'])]
        prop_fractions = [r['propshare_fraction'] for r in results if not np.isnan(r['propshare']['mean'])]
        
        # Faithful/BitTorrent data (X marks with solid lines)
        faith_means = [r['faithful']['mean'] for r in results if not np.isnan(r['faithful']['mean'])]
        faith_stds = [r['faithful']['std'] for r in results if not np.isnan(r['faithful']['mean'])]
        faith_fractions = [r['propshare_fraction'] for r in results if not np.isnan(r['faithful']['mean'])]
        
        # Plot PropShare (circles with error bars)
        if prop_means:
            ax.errorbar(prop_fractions, prop_means, yerr=prop_stds, 
                       fmt='o', markersize=8, linewidth=2, capsize=5,
                       color='black', markerfacecolor='white', markeredgewidth=2,
                       linestyle=':', label='PropShare')
        
        # Plot BitTorrent/Faithful (X marks with error bars)
        if faith_means:
            ax.errorbar(faith_fractions, faith_means, yerr=faith_stds,
                       fmt='x', markersize=12, linewidth=3, capsize=5,
                       color='black', markeredgewidth=3,
                       linestyle='-', label='BitTorrent')
        
        # Formatting to match original
        ax.set_xlabel('Frac. PropShare Clients', fontsize=14, fontweight='bold')
        ax.set_ylabel('Avg. Download Times (sec)', fontsize=14, fontweight='bold')
        ax.set_title('Figure 8: PropShare vs. BitTorrent', fontsize=16, fontweight='bold', pad=20)
        
        # Set axis limits and grid
        ax.set_xlim(-0.05, 1.05)
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.legend(loc='upper right', fontsize=12)
        
        # Make it look more like the original
        ax.tick_params(axis='both', which='major', labelsize=12)
        
        plt.tight_layout()
        
        # Save the plot
        output_path = self.output_dir / 'performance_comparison.png'
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"Saved performance comparison plot to {output_path}")
        
        return fig
    
    def create_additional_charts(self, results: List[Dict]):
        """Create additional analysis charts."""
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        
        # Data preparation
        df_results = pd.DataFrame([
            {
                'Fraction': r['propshare_fraction'],
                'PropShare_Mean': r['propshare']['mean'],
                'PropShare_Std': r['propshare']['std'],
                'BitTorrent_Mean': r['faithful']['mean'],
                'BitTorrent_Std': r['faithful']['std'],
                'PropShare_Count': r['propshare']['count'],
                'BitTorrent_Count': r['faithful']['count']
            }
            for r in results
        ])
        
        # 1. Line plot showing trends
        axes[0, 0].plot(df_results['Fraction'], df_results['PropShare_Mean'], 
                       'o-', label='PropShare', linewidth=2, markersize=6)
        axes[0, 0].plot(df_results['Fraction'], df_results['BitTorrent_Mean'], 
                       's-', label='BitTorrent', linewidth=2, markersize=6)
        axes[0, 0].set_xlabel('PropShare Fraction')
        axes[0, 0].set_ylabel('Avg Download Time (sec)')
        axes[0, 0].set_title('Performance Trends')
        axes[0, 0].legend()
        axes[0, 0].grid(True, alpha=0.3)
        
        # 2. Bar chart comparing averages
        fractions = df_results['Fraction']
        width = 0.35
        x = np.arange(len(fractions))
        
        prop_mask = ~np.isnan(df_results['PropShare_Mean'])
        bit_mask = ~np.isnan(df_results['BitTorrent_Mean'])
        
        axes[0, 1].bar(x[prop_mask] - width/2, df_results['PropShare_Mean'][prop_mask], 
                      width, label='PropShare', alpha=0.8)
        axes[0, 1].bar(x[bit_mask] + width/2, df_results['BitTorrent_Mean'][bit_mask], 
                      width, label='BitTorrent', alpha=0.8)
        axes[0, 1].set_xlabel('Configuration')
        axes[0, 1].set_ylabel('Avg Download Time (sec)')
        axes[0, 1].set_title('Performance by Configuration')
        axes[0, 1].set_xticks(x)
        axes[0, 1].set_xticklabels([f'{f:.1f}' for f in fractions])
        axes[0, 1].legend()
        
        # 3. Standard deviation comparison
        axes[1, 0].plot(df_results['Fraction'], df_results['PropShare_Std'], 
                       'o-', label='PropShare Std Dev', linewidth=2)
        axes[1, 0].plot(df_results['Fraction'], df_results['BitTorrent_Std'], 
                       's-', label='BitTorrent Std Dev', linewidth=2)
        axes[1, 0].set_xlabel('PropShare Fraction')
        axes[1, 0].set_ylabel('Standard Deviation (sec)')
        axes[1, 0].set_title('Performance Variability')
        axes[1, 0].legend()
        axes[1, 0].grid(True, alpha=0.3)
        
        # 4. Sample size information
        axes[1, 1].bar(x - width/2, df_results['PropShare_Count'], width, 
                      label='PropShare Clients', alpha=0.8)
        axes[1, 1].bar(x + width/2, df_results['BitTorrent_Count'], width, 
                      label='BitTorrent Clients', alpha=0.8)
        axes[1, 1].set_xlabel('Configuration')
        axes[1, 1].set_ylabel('Number of Clients')
        axes[1, 1].set_title('Client Distribution')
        axes[1, 1].set_xticks(x)
        axes[1, 1].set_xticklabels([f'{f:.1f}' for f in fractions])
        axes[1, 1].legend()
        
        plt.tight_layout()
        
        # Save additional charts
        output_path = self.output_dir / 'additional_analysis.png'
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"Saved additional analysis charts to {output_path}")
        
        return fig
    
    def generate_summary_report(self, results: List[Dict]):
        """Generate a summary statistics report."""
        summary = {
            'experiment_summary': {
                'total_configurations': len(results),
                'configurations_analyzed': len([r for r in results if r['total_clients'] > 0])
            },
            'performance_summary': {},
            'detailed_results': results
        }
        
        # Calculate overall performance statistics
        prop_times = [r['propshare']['mean'] for r in results if not np.isnan(r['propshare']['mean'])]
        faith_times = [r['faithful']['mean'] for r in results if not np.isnan(r['faithful']['mean'])]
        
        if prop_times:
            summary['performance_summary']['propshare'] = {
                'mean_download_time': np.mean(prop_times),
                'min_download_time': np.min(prop_times),
                'max_download_time': np.max(prop_times),
                'std_download_time': np.std(prop_times)
            }
        
        if faith_times:
            summary['performance_summary']['bittorrent'] = {
                'mean_download_time': np.mean(faith_times),
                'min_download_time': np.min(faith_times),
                'max_download_time': np.max(faith_times),
                'std_download_time': np.std(faith_times)
            }
        
        # Save summary
        output_path = self.output_dir / 'summary_report.json'
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        print(f"Saved summary report to {output_path}")
        
        # Print key findings
        print("\n" + "="*60)
        print("PERFORMANCE ANALYSIS SUMMARY")
        print("="*60)
        
        if prop_times and faith_times:
            prop_avg = np.mean(prop_times)
            faith_avg = np.mean(faith_times)
            improvement = ((faith_avg - prop_avg) / faith_avg) * 100
            
            print(f"PropShare Average: {prop_avg:.1f} seconds")
            print(f"BitTorrent Average: {faith_avg:.1f} seconds")
            print(f"PropShare Performance: {improvement:+.1f}% vs BitTorrent")
        
        print(f"Total Configurations: {len(results)}")
        print(f"Output Directory: {self.output_dir}")


def create_sample_data():
    """Create sample configuration and CSV files for testing."""
    # Create sample directory structure
    sample_dir = Path("sample_experiment")
    logs_dir = sample_dir / "logs"
    
    # Create sample configuration with explicit paths
    config = [
        {
            "propshare_ids": [],
            "faithful_ids": [
                "exp_000_prop0.0/client_001.csv",
                "exp_000_prop0.0/client_002.csv", 
                "exp_000_prop0.0/client_003.csv",
                "exp_000_prop0.0/client_004.csv",
                "exp_000_prop0.0/client_005.csv"
            ]
        },
        {
            "propshare_ids": [
                "exp_001_prop0.2/client_001.csv"
            ],
            "faithful_ids": [
                "exp_001_prop0.2/client_002.csv",
                "exp_001_prop0.2/client_003.csv",
                "exp_001_prop0.2/client_004.csv",
                "exp_001_prop0.2/client_005.csv"
            ]
        },
        {
            "propshare_ids": [
                "exp_002_prop0.4/client_001.csv",
                "exp_002_prop0.4/client_002.csv"
            ],
            "faithful_ids": [
                "exp_002_prop0.4/client_003.csv",
                "exp_002_prop0.4/client_004.csv",
                "exp_002_prop0.4/client_005.csv"
            ]
        },
        {
            "propshare_ids": [
                "exp_003_prop0.6/client_001.csv",
                "exp_003_prop0.6/client_002.csv",
                "exp_003_prop0.6/client_003.csv"
            ],
            "faithful_ids": [
                "exp_003_prop0.6/client_004.csv",
                "exp_003_prop0.6/client_005.csv"
            ]
        },
        {
            "propshare_ids": [
                "exp_004_prop0.8/client_001.csv",
                "exp_004_prop0.8/client_002.csv",
                "exp_004_prop0.8/client_003.csv",
                "exp_004_prop0.8/client_004.csv"
            ],
            "faithful_ids": [
                "exp_004_prop0.8/client_005.csv"
            ]
        },
        {
            "propshare_ids": [
                "exp_005_prop1.0/client_001.csv",
                "exp_005_prop1.0/client_002.csv",
                "exp_005_prop1.0/client_003.csv",
                "exp_005_prop1.0/client_004.csv",
                "exp_005_prop1.0/client_005.csv"
            ],
            "faithful_ids": []
        }
    ]
    
    # Save configuration
    with open(sample_dir / "config.json", 'w') as f:
        json.dump(config, f, indent=2)
    
    # Create experiment directories and CSV files
    np.random.seed(42)
    for exp_idx, exp_config in enumerate(config):
        total_clients = len(exp_config['propshare_ids']) + len(exp_config['faithful_ids'])
        propshare_fraction = len(exp_config['propshare_ids']) / total_clients if total_clients > 0 else 0
        
        # Create experiment directory
        exp_dir = logs_dir / f"exp_{exp_idx:03d}_prop{propshare_fraction:.1f}"
        exp_dir.mkdir(parents=True, exist_ok=True)
        
        # Get all client file paths for this experiment
        all_client_paths = exp_config['propshare_ids'] + exp_config['faithful_ids']
        
        for client_path in all_client_paths:
            # Extract just the filename from the path (e.g., "client_001.csv" from "exp_000_prop0.0/client_001.csv")
            client_filename = client_path.split('/')[-1]
            # Generate realistic download progression data
            # PropShare clients tend to be slightly faster in this simulation
            is_propshare = client_path in exp_config['propshare_ids']
            base_time = 150 if is_propshare else 170
            times = np.sort(np.random.uniform(0, base_time, 50))  # 50 data points
            sizes = np.cumsum(np.random.exponential(1000, 50))  # Cumulative file sizes
            
            # Add some noise to make it realistic
            times += np.random.normal(0, 5, 50)
            
            df = pd.DataFrame({
                'file_path': [f'/download/chunk_{j:03d}.dat' for j in range(50)],
                'size': sizes.astype(int),
                'time': times
            })
            
            # Save to the experiment directory using just the filename
            df.to_csv(exp_dir / client_filename, index=False)
    
    print(f"Sample data created in {sample_dir}/")
    print("Directory structure:")
    for exp_dir in sorted(logs_dir.iterdir()):
        if exp_dir.is_dir():
            files = list(exp_dir.glob("*.csv"))
            print(f"  {exp_dir.name}/ ({len(files)} files)")
    
    return sample_dir


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description='P2P Performance Analysis Tool')
    parser.add_argument('--config', type=str, help='Path to configuration JSON file')
    parser.add_argument('--logs', type=str, help='Directory containing CSV log files')
    parser.add_argument('--output', type=str, default='results', help='Output directory')
    parser.add_argument('--create-sample', action='store_true', help='Create sample data for testing')
    
    args = parser.parse_args()
    
    if args.create_sample:
        sample_dir = create_sample_data()
        print("Sample data created! Run with:")
        print(f"python {__file__} --config {sample_dir}/config.json --logs {sample_dir}/logs")
        return
    
    if not args.config or not args.logs:
        print("Error: --config and --logs arguments are required")
        print("Use --create-sample to generate sample data first")
        return
    
    # Run analysis
    analyzer = P2PPerformanceAnalyzer(args.config, args.logs, args.output)
    results = analyzer.run_analysis()
    
    # Generate visualizations
    analyzer.create_performance_comparison_plot(results)
    analyzer.create_additional_charts(results)
    analyzer.generate_summary_report(results)
    
    print("\nAnalysis complete! Check the results directory for outputs.")


if __name__ == "__main__":
    main()
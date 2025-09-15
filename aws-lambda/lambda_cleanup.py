#!/usr/bin/env python3
"""
AWS Lambda Functions Cleanup Tool
Lists all Lambda functions and allows safe deletion with cost analysis.
"""

import boto3
import argparse
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
import time
import json

class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    BOLD = '\033[1m'
    END = '\033[0m'

class LambdaCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS Lambda cleaner"""
        self.profile_name = profile_name
        self.session = None
        self.accessible_regions = []
        self.setup_aws_session()
        
    def setup_aws_session(self):
        """Setup AWS session with the specified profile"""
        try:
            if self.profile_name:
                self.session = boto3.Session(profile_name=self.profile_name)
                print(f"{Colors.BLUE}Using AWS profile: {self.profile_name}{Colors.END}")
            else:
                self.session = boto3.Session()
                print(f"{Colors.BLUE}Using default AWS profile{Colors.END}")
            
            # Test credentials
            sts = self.session.client('sts')
            identity = sts.get_caller_identity()
            
            print(f"{Colors.GREEN}✓ Connected to AWS Account: {identity['Account']}{Colors.END}")
            print(f"{Colors.GREEN}✓ User/Role: {identity['Arn']}{Colors.END}")
            
        except NoCredentialsError:
            print(f"{Colors.RED}Error: AWS credentials not found!{Colors.END}")
            print("Please run: aws configure")
            sys.exit(1)
        except ClientError as e:
            print(f"{Colors.RED}Error: {e}{Colors.END}")
            sys.exit(1)
    
    def test_region_connectivity(self) -> List[str]:
        """Test connectivity to different AWS regions"""
        test_regions = [
            'us-east-1', 'us-west-2', 'ap-south-1', 
            'ap-southeast-1', 'eu-west-1', 'eu-central-1'
        ]
        
        accessible_regions = []
        print(f"\n{Colors.BLUE}Testing region connectivity...{Colors.END}")
        
        for region in test_regions:
            try:
                lambda_client = self.session.client('lambda', region_name=region)
                # Quick test
                lambda_client.list_functions(MaxItems=1)
                print(f"{Colors.GREEN}✓ {region} - accessible{Colors.END}")
                accessible_regions.append(region)
            except (EndpointConnectionError, ClientError) as e:
                print(f"{Colors.RED}✗ {region} - not accessible{Colors.END}")
            except Exception as e:
                print(f"{Colors.RED}✗ {region} - error: {str(e)[:50]}...{Colors.END}")
        
        if not accessible_regions:
            print(f"{Colors.RED}Error: No accessible regions found!{Colors.END}")
            sys.exit(1)
            
        self.accessible_regions = accessible_regions
        return accessible_regions
    
    def get_function_stats(self, function_name: str, region: str) -> Dict[str, Any]:
        """Get detailed statistics for a Lambda function"""
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            cloudwatch = self.session.client('cloudwatch', region_name=region)
            
            # Get function configuration
            config = lambda_client.get_function_configuration(FunctionName=function_name)
            
            # Get invocation stats from CloudWatch (last 30 days)
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=30)
            
            invocation_stats = cloudwatch.get_metric_statistics(
                Namespace='AWS/Lambda',
                MetricName='Invocations',
                Dimensions=[{'Name': 'FunctionName', 'Value': function_name}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,  # Daily
                Statistics=['Sum']
            )
            
            error_stats = cloudwatch.get_metric_statistics(
                Namespace='AWS/Lambda',
                MetricName='Errors',
                Dimensions=[{'Name': 'FunctionName', 'Value': function_name}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,
                Statistics=['Sum']
            )
            
            # Calculate totals
            total_invocations = sum(point['Sum'] for point in invocation_stats['Datapoints'])
            total_errors = sum(point['Sum'] for point in error_stats['Datapoints'])
            
            # Estimate monthly cost
            memory_mb = config['MemorySize']
            timeout_seconds = config['Timeout']
            
            # Lambda pricing (rough estimate)
            # $0.0000166667 per GB-second + $0.20 per 1M requests
            gb_seconds_per_invocation = (memory_mb / 1024) * (timeout_seconds)
            monthly_gb_seconds = gb_seconds_per_invocation * total_invocations * (30/30)  # Scale to monthly
            
            estimated_compute_cost = monthly_gb_seconds * 0.0000166667
            estimated_request_cost = (total_invocations * (30/30) / 1000000) * 0.20
            estimated_monthly_cost = estimated_compute_cost + estimated_request_cost
            
            return {
                'total_invocations': int(total_invocations),
                'total_errors': int(total_errors),
                'estimated_monthly_cost': estimated_monthly_cost,
                'memory_mb': memory_mb,
                'timeout_seconds': timeout_seconds,
                'runtime': config['Runtime'],
                'last_modified': config['LastModified'],
                'code_size': config['CodeSize']
            }
            
        except ClientError as e:
            return {
                'error': str(e),
                'total_invocations': 0,
                'total_errors': 0,
                'estimated_monthly_cost': 0
            }
    
    def check_function_safety(self, function_config: Dict[str, Any], region: str) -> Dict[str, Any]:
        """Check if function appears to be important or in use"""
        function_name = function_config['FunctionName']
        safety_warnings = []
        
        # Check for important patterns in name
        important_patterns = [
            'prod', 'production', 'api', 'webhook', 'auth', 'payment',
            'critical', 'main', 'core', 'live', 'backup'
        ]
        
        name_lower = function_name.lower()
        for pattern in important_patterns:
            if pattern in name_lower:
                safety_warnings.append(f"Name contains '{pattern}' - might be important")
        
        # Check if function has triggers/event sources
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            
            # Check event source mappings
            event_sources = lambda_client.list_event_source_mappings(FunctionName=function_name)
            if event_sources['EventSourceMappings']:
                safety_warnings.append(f"Has {len(event_sources['EventSourceMappings'])} event source mappings")
            
        except ClientError:
            pass
        
        # Check environment variables for important configs
        env_vars = function_config.get('Environment', {}).get('Variables', {})
        important_env_patterns = ['API_KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'DATABASE']
        for env_var in env_vars.keys():
            for pattern in important_env_patterns:
                if pattern in env_var.upper():
                    safety_warnings.append("Has sensitive environment variables")
                    break
        
        # Check if function was recently modified (within 7 days)
        last_modified = function_config['LastModified']
        if isinstance(last_modified, str):
            last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
        
        days_since_modified = (datetime.now(timezone.utc) - last_modified).days
        if days_since_modified <= 7:
            safety_warnings.append(f"Recently modified ({days_since_modified} days ago)")
        
        return {
            'is_risky': len(safety_warnings) > 0,
            'warnings': safety_warnings,
            'days_since_modified': days_since_modified
        }
    
    def format_size(self, size_bytes: int) -> str:
        """Format bytes into human readable format"""
        if size_bytes == 0:
            return "0 B"
        
        units = ['B', 'KB', 'MB', 'GB']
        unit_index = 0
        size = float(size_bytes)
        
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        
        return f"{size:.1f} {units[unit_index]}"
    
    def list_functions_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all Lambda functions in a specific region"""
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            
            functions = []
            paginator = lambda_client.get_paginator('list_functions')
            
            for page in paginator.paginate():
                for function in page['Functions']:
                    # Get detailed stats
                    stats = self.get_function_stats(function['FunctionName'], region)
                    safety = self.check_function_safety(function, region)
                    
                    function_info = {
                        'name': function['FunctionName'],
                        'region': region,
                        'runtime': function['Runtime'],
                        'memory_size': function['MemorySize'],
                        'timeout': function['Timeout'],
                        'last_modified': function['LastModified'],
                        'code_size': function['CodeSize'],
                        'description': function.get('Description', ''),
                        'stats': stats,
                        'safety': safety
                    }
                    
                    functions.append(function_info)
            
            return functions
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing functions in {region}: {e}{Colors.END}")
            return []
    
    def format_function_info(self, function: Dict[str, Any]) -> str:
        """Format function information for display"""
        name = function['name'][:25] if len(function['name']) > 25 else function['name']
        region = function['region']
        runtime = function['runtime'][:12]
        memory = f"{function['memory_size']}MB"
        timeout = f"{function['timeout']}s"
        code_size = self.format_size(function['code_size'])
        
        stats = function['stats']
        invocations = stats['total_invocations']
        monthly_cost = stats['estimated_monthly_cost']
        
        last_modified = function['last_modified']
        if isinstance(last_modified, str):
            last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
        days_ago = (datetime.now(timezone.utc) - last_modified).days
        
        # Safety indicator
        if function['safety']['is_risky']:
            safety_indicator = f"{Colors.RED}⚠{Colors.END}"
        else:
            safety_indicator = f"{Colors.GREEN}✓{Colors.END}"
        
        return f"  {name:<25} | {region:<12} | {runtime:<12} | {memory:<6} | {timeout:<4} | {code_size:<8} | {invocations:>8} | ${monthly_cost:>5.2f} | {days_ago:>3}d | {safety_indicator}"
    
    def list_all_functions(self) -> List[Dict[str, Any]]:
        """List all Lambda functions across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*120}{Colors.END}")
        print(f"{Colors.BLUE}Scanning Lambda Functions across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*120}{Colors.END}")
        
        all_functions = []
        total_cost = 0
        total_invocations = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            functions = self.list_functions_in_region(region)
            
            if functions:
                region_cost = sum(f['stats']['estimated_monthly_cost'] for f in functions)
                region_invocations = sum(f['stats']['total_invocations'] for f in functions)
                
                print(f"{Colors.GREEN}Found {len(functions)} functions{Colors.END}")
                print(f"{Colors.BLUE}Total invocations (30 days): {region_invocations:,}{Colors.END}")
                print(f"{Colors.BLUE}Estimated monthly cost: ${region_cost:.2f}{Colors.END}")
                
                total_cost += region_cost
                total_invocations += region_invocations
                all_functions.extend(functions)
            else:
                print(f"{Colors.GREEN}No functions found{Colors.END}")
        
        # Display summary
        risky_count = sum(1 for f in all_functions if f['safety']['is_risky'])
        unused_count = sum(1 for f in all_functions if f['stats']['total_invocations'] == 0)
        
        print(f"\n{Colors.BOLD}LAMBDA FUNCTIONS SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*120}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total functions found: {Colors.YELLOW}{len(all_functions)}{Colors.END}")
        print(f"Functions with safety warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Unused functions (0 invocations): {Colors.YELLOW}{unused_count}{Colors.END}")
        print(f"Total invocations (30 days): {Colors.YELLOW}{total_invocations:,}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        
        if all_functions:
            print(f"\n{Colors.BOLD}FUNCTION DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*120}{Colors.END}")
            print(f"  {'Function Name':<25} | {'Region':<12} | {'Runtime':<12} | {'Memory':<6} | {'Timeout':<4} | {'Size':<8} | {'Invokes':<8} | {'Cost':<6} | {'Age':<4} | Safe")
            print(f"  {'-'*25} | {'-'*12} | {'-'*12} | {'-'*6} | {'-'*4} | {'-'*8} | {'-'*8} | {'-'*6} | {'-'*4} | {'-'*4}")
            
            # Sort by cost (highest first), then by invocations
            sorted_functions = sorted(all_functions, key=lambda x: (-x['stats']['estimated_monthly_cost'], -x['stats']['total_invocations']))
            
            for function in sorted_functions:
                print(self.format_function_info(function))
                
                # Show safety warnings
                if function['safety']['warnings']:
                    for warning in function['safety']['warnings'][:2]:
                        print(f"    {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # Show breakdown by runtime
            print(f"\n{Colors.BOLD}BREAKDOWN BY RUNTIME{Colors.END}")
            runtimes = {}
            for func in all_functions:
                runtime = func['runtime']
                if runtime not in runtimes:
                    runtimes[runtime] = {'count': 0, 'cost': 0, 'unused': 0}
                runtimes[runtime]['count'] += 1
                runtimes[runtime]['cost'] += func['stats']['estimated_monthly_cost']
                if func['stats']['total_invocations'] == 0:
                    runtimes[runtime]['unused'] += 1
            
            for runtime, stats in sorted(runtimes.items()):
                print(f"  {runtime:<15}: {stats['count']} functions, ${stats['cost']:.2f}/month ({stats['unused']} unused)")
        
        return all_functions
    
    def get_user_confirmation(self, message: str) -> bool:
        """Get user confirmation"""
        while True:
            response = input(f"\n{Colors.YELLOW}{message} (y/n): {Colors.END}").lower().strip()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
            else:
                print(f"{Colors.RED}Please enter 'y' for yes or 'n' for no{Colors.END}")
    
    def show_function_selection_menu(self, functions: List[Dict[str, Any]]) -> List[str]:
        """Show menu for function selection"""
        if not functions:
            return []
        
        print(f"\n{Colors.BOLD}SELECT FUNCTIONS TO DELETE{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}")
        print("Enter function numbers separated by commas (e.g., 1,3,5)")
        print("Or enter 'all' to select all functions")
        print("Or enter 'unused' to select only unused functions (0 invocations)")
        print("Or enter 'safe' to select only functions without warnings")
        print("")
        
        # Show numbered list
        unused_functions = []
        safe_functions = []
        
        for i, function in enumerate(functions, 1):
            safety_indicator = f"{Colors.RED}⚠{Colors.END}" if function['safety']['is_risky'] else f"{Colors.GREEN}✓{Colors.END}"
            invocations = function['stats']['total_invocations']
            cost = function['stats']['estimated_monthly_cost']
            
            unused_indicator = f"{Colors.YELLOW}(UNUSED){Colors.END}" if invocations == 0 else ""
            
            print(f"{i:2d}. {function['name']:<30} | {function['region']:<12} | {invocations:>8} calls | ${cost:>5.2f}/mo | {safety_indicator} {unused_indicator}")
            
            if invocations == 0:
                unused_functions.append(function['name'])
            if not function['safety']['is_risky']:
                safe_functions.append(function['name'])
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Your selection: {Colors.END}").strip().lower()
            
            if choice == 'all':
                return [f['name'] for f in functions]
            elif choice == 'unused':
                if unused_functions:
                    return unused_functions
                else:
                    print(f"{Colors.RED}No unused functions found{Colors.END}")
                    continue
            elif choice == 'safe':
                if safe_functions:
                    return safe_functions
                else:
                    print(f"{Colors.RED}No 'safe' functions found (all have warnings){Colors.END}")
                    continue
            elif choice == '':
                return []
            else:
                try:
                    indices = [int(x.strip()) for x in choice.split(',')]
                    selected = []
                    
                    for idx in indices:
                        if 1 <= idx <= len(functions):
                            selected.append(functions[idx-1]['name'])
                        else:
                            print(f"{Colors.RED}Invalid function number: {idx}{Colors.END}")
                            raise ValueError()
                    
                    return selected
                    
                except ValueError:
                    print(f"{Colors.RED}Invalid input. Please enter numbers separated by commas, 'all', 'unused', or 'safe'{Colors.END}")
    
    def delete_function(self, function_name: str, region: str, dry_run: bool = False) -> bool:
        """Delete a single Lambda function"""
        if dry_run:
            print(f"  {Colors.BLUE}[DRY RUN] Would delete function {function_name}{Colors.END}")
            return True
        
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            lambda_client.delete_function(FunctionName=function_name)
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                print(f"  {Colors.YELLOW}Function {function_name} already deleted{Colors.END}")
                return True
            else:
                print(f"  {Colors.RED}Error deleting {function_name}: {e}{Colors.END}")
                return False
    
    def delete_functions(self, functions: List[Dict[str, Any]], selected_function_names: List[str], dry_run: bool = False):
        """Delete selected functions"""
        functions_to_delete = [f for f in functions if f['name'] in selected_function_names]
        
        if not functions_to_delete:
            print(f"{Colors.YELLOW}No functions selected for deletion.{Colors.END}")
            return
        
        mode_text = "DRY RUN - " if dry_run else ""
        print(f"\n{Colors.RED}{'='*70}{Colors.END}")
        print(f"{Colors.RED}{mode_text}DELETING LAMBDA FUNCTIONS{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}THIS CANNOT BE UNDONE!{Colors.END}")
        print(f"{Colors.RED}{'='*70}{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, function in enumerate(functions_to_delete, 1):
            function_name = function['name']
            region = function['region']
            monthly_cost = function['stats']['estimated_monthly_cost']
            invocations = function['stats']['total_invocations']
            
            print(f"\n[{i}/{len(functions_to_delete)}] Processing function: {function_name}")
            print(f"  Region: {region}, Invocations: {invocations:,}, Cost: ${monthly_cost:.2f}/month")
            
            # Show warnings
            if function['safety']['warnings']:
                for warning in function['safety']['warnings'][:3]:
                    print(f"  {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            if self.delete_function(function_name, region, dry_run):
                success_text = "Would delete" if dry_run else "Successfully deleted"
                print(f"  {Colors.GREEN}✓ {success_text} {function_name}{Colors.END}")
                deleted_count += 1
                total_savings += monthly_cost
            else:
                print(f"  {Colors.RED}✗ Failed to delete {function_name}{Colors.END}")
                failed_count += 1
            
            # Small delay to avoid rate limiting
            if not dry_run:
                time.sleep(0.5)
        
        # Final summary
        print(f"\n{Colors.BOLD}{'DRY RUN ' if dry_run else ''}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        success_text = "would be deleted" if dry_run else "deleted"
        print(f"Successfully {success_text}: {Colors.GREEN}{deleted_count} functions{Colors.END}")
        print(f"Failed: {Colors.RED}{failed_count} functions{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
    
    def run(self, dry_run: bool = False):
        """Main execution flow"""
        mode_text = " (DRY RUN MODE)" if dry_run else ""
        print(f"{Colors.BOLD}AWS Lambda Functions Cleanup Tool{mode_text}{Colors.END}")
        print(f"{Colors.BLUE}{'='*70}{Colors.END}")
        
        if dry_run:
            print(f"{Colors.BLUE}Running in DRY RUN mode - no actual deletions will be performed{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all functions
        functions = self.list_all_functions()
        
        if not functions:
            print(f"\n{Colors.GREEN}No Lambda functions found! Nothing to delete.{Colors.END}")
            return
        
        # Show deletion options
        total_cost = sum(f['stats']['estimated_monthly_cost'] for f in functions)
        risky_count = sum(1 for f in functions if f['safety']['is_risky'])
        unused_count = sum(1 for f in functions if f['stats']['total_invocations'] == 0)
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION OPTIONS{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Total functions: {Colors.BLUE}{len(functions)}{Colors.END}")
        print(f"Functions with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Unused functions: {Colors.YELLOW}{unused_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}⚠️  Deletion will permanently remove selected functions!{Colors.END}")
            print(f"{Colors.RED}⚠️  This action CANNOT be undone!{Colors.END}")
        
        # Ask what user wants to do
        proceed_msg = "Do you want to proceed with function selection?" if not dry_run else "Do you want to see what would be deleted?"
        if not self.get_user_confirmation(proceed_msg):
            return
        
        # Let user select functions
        selected_function_names = self.show_function_selection_menu(functions)
        
        if not selected_function_names:
            print(f"{Colors.BLUE}No functions selected. Exiting.{Colors.END}")
            return
        
        selected_functions = [f for f in functions if f['name'] in selected_function_names]
        selected_cost = sum(f['stats']['estimated_monthly_cost'] for f in selected_functions)
        
        # Final confirmation
        confirmation_text = "DRY RUN CONFIRMATION" if dry_run else "FINAL CONFIRMATION"
        print(f"\n{Colors.RED}{confirmation_text}{Colors.END}")
        print(f"Selected functions: {Colors.YELLOW}{len(selected_functions)}{Colors.END}")
        print(f"Monthly savings: {Colors.GREEN}${selected_cost:.2f}{Colors.END}")
        
        final_question = "Proceed with analysis?" if dry_run else "Are you absolutely sure you want to delete these functions?"
        if self.get_user_confirmation(final_question):
            self.delete_functions(functions, selected_function_names, dry_run)
        else:
            print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS Lambda Functions Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 lambda_cleanup.py                       # Use default AWS profile
  python3 lambda_cleanup.py --profile dev         # Use specific profile
  python3 lambda_cleanup.py --dry-run             # Test mode - no actual deletions
  
Features:
  - Lists all Lambda functions with usage statistics
  - Shows cost estimates and invocation counts
  - Identifies unused functions (0 invocations)
  - Safety warnings for potentially important functions
  - Selective deletion with multiple confirmation prompts
        """
    )
    
    parser.add_argument(
        '--profile', '-p',
        type=str,
        help='AWS profile to use (default: uses default profile)'
    )
    
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Dry run mode - show what would be deleted without actually deleting'
    )
    
    args = parser.parse_args()
    
    try:
        cleaner = LambdaCleaner(profile_name=args.profile)
        cleaner.run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()
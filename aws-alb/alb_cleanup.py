#!/usr/bin/env python3
"""
AWS Load Balancer Cleanup Tool
Lists all Load Balancers (ALB, NLB, CLB) and allows safe deletion with cost analysis.
Load balancers can cost $18-20+ per month each, making them expensive if unused.
"""

import boto3
import argparse
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
import time

class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    BOLD = '\033[1m'
    END = '\033[0m'

class LoadBalancerCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS Load Balancer cleaner"""
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
                elbv2 = self.session.client('elbv2', region_name=region)
                elbv2.describe_load_balancers(PageSize=1)
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
    
    def get_lb_metrics(self, lb_name: str, lb_type: str, region: str) -> Dict[str, Any]:
        """Get CloudWatch metrics for load balancer"""
        try:
            cloudwatch = self.session.client('cloudwatch', region_name=region)
            
            # Get metrics for the last 30 days
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=30)
            
            metrics = {}
            
            if lb_type in ['application', 'network']:
                # ALB/NLB metrics
                namespace = 'AWS/ApplicationELB' if lb_type == 'application' else 'AWS/NetworkELB'
                
                # Request count
                request_response = cloudwatch.get_metric_statistics(
                    Namespace=namespace,
                    MetricName='RequestCount' if lb_type == 'application' else 'ActiveFlowCount_TCP',
                    Dimensions=[{'Name': 'LoadBalancer', 'Value': lb_name}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,
                    Statistics=['Sum'] if lb_type == 'application' else ['Average']
                )
                
                if request_response['Datapoints']:
                    if lb_type == 'application':
                        metrics['total_requests'] = sum(point['Sum'] for point in request_response['Datapoints'])
                    else:
                        metrics['avg_active_flows'] = max(point['Average'] for point in request_response['Datapoints'])
                else:
                    metrics['total_requests'] = 0 if lb_type == 'application' else 0
                    metrics['avg_active_flows'] = 0 if lb_type == 'network' else 0
                
            else:
                # Classic Load Balancer metrics
                request_response = cloudwatch.get_metric_statistics(
                    Namespace='AWS/ELB',
                    MetricName='RequestCount',
                    Dimensions=[{'Name': 'LoadBalancerName', 'Value': lb_name}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,
                    Statistics=['Sum']
                )
                
                metrics['total_requests'] = sum(point['Sum'] for point in request_response['Datapoints']) if request_response['Datapoints'] else 0
            
            return metrics
            
        except ClientError as e:
            return {'error': str(e), 'total_requests': 0}
    
    def get_monthly_cost_estimate(self, lb_type: str, region: str) -> float:
        """Estimate monthly cost for load balancer type"""
        # Rough cost estimates (varies by region)
        cost_estimates = {
            'application': 22.50,  # ALB: ~$22.50/month base
            'network': 22.50,      # NLB: ~$22.50/month base  
            'classic': 18.00       # CLB: ~$18.00/month base
        }
        
        # Some regions are more expensive
        expensive_regions = ['ap-south-1', 'ap-southeast-1', 'sa-east-1']
        multiplier = 1.2 if region in expensive_regions else 1.0
        
        return cost_estimates.get(lb_type, 20.00) * multiplier
    
    def check_lb_safety(self, lb_info: Dict[str, Any]) -> Dict[str, Any]:
        """Check if load balancer appears to be important or in use"""
        lb_name = lb_info['name']
        safety_warnings = []
        
        # Check for important patterns in name
        important_patterns = [
            'prod', 'production', 'api', 'public', 'main', 'primary',
            'critical', 'live', 'web', 'app', 'frontend'
        ]
        
        name_lower = lb_name.lower()
        for pattern in important_patterns:
            if pattern in name_lower:
                safety_warnings.append(f"Name contains '{pattern}' - might be important")
        
        # Check if LB has targets
        target_count = lb_info.get('target_count', 0)
        healthy_target_count = lb_info.get('healthy_target_count', 0)
        
        if target_count > 0:
            safety_warnings.append(f"Has {target_count} registered targets ({healthy_target_count} healthy)")
        
        # Check scheme (internet-facing vs internal)
        if lb_info.get('scheme') == 'internet-facing':
            safety_warnings.append("Internet-facing load balancer")
        
        # Check recent activity
        total_requests = lb_info.get('metrics', {}).get('total_requests', 0)
        if total_requests > 1000:  # More than 1000 requests in 30 days
            safety_warnings.append(f"Recent activity: {total_requests:,} requests in 30 days")
        
        # Check if recently created (within 7 days)
        created_time = lb_info['created_time']
        days_since_created = (datetime.now(timezone.utc) - created_time).days
        if days_since_created <= 7:
            safety_warnings.append(f"Recently created ({days_since_created} days ago)")
        
        return {
            'is_risky': len(safety_warnings) > 0,
            'warnings': safety_warnings,
            'days_since_created': days_since_created
        }
    
    def get_target_group_info(self, lb_arn: str, region: str) -> Dict[str, int]:
        """Get target group information for ALB/NLB"""
        try:
            elbv2 = self.session.client('elbv2', region_name=region)
            
            # Get target groups for this load balancer
            tg_response = elbv2.describe_target_groups(LoadBalancerArn=lb_arn)
            
            total_targets = 0
            healthy_targets = 0
            
            for tg in tg_response['TargetGroups']:
                tg_arn = tg['TargetGroupArn']
                
                # Get target health
                health_response = elbv2.describe_target_health(TargetGroupArn=tg_arn)
                
                for target in health_response['TargetHealthDescriptions']:
                    total_targets += 1
                    if target['TargetHealth']['State'] == 'healthy':
                        healthy_targets += 1
            
            return {
                'target_count': total_targets,
                'healthy_target_count': healthy_targets,
                'target_group_count': len(tg_response['TargetGroups'])
            }
            
        except ClientError:
            return {'target_count': 0, 'healthy_target_count': 0, 'target_group_count': 0}
    
    def get_clb_instances(self, lb_name: str, region: str) -> Dict[str, int]:
        """Get instance information for Classic Load Balancer"""
        try:
            elb = self.session.client('elb', region_name=region)
            
            # Get instance health
            health_response = elb.describe_instance_health(LoadBalancerName=lb_name)
            
            total_instances = len(health_response['InstanceStates'])
            healthy_instances = sum(1 for instance in health_response['InstanceStates'] 
                                  if instance['State'] == 'InService')
            
            return {
                'target_count': total_instances,
                'healthy_target_count': healthy_instances
            }
            
        except ClientError:
            return {'target_count': 0, 'healthy_target_count': 0}
    
    def list_alb_nlb_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List Application and Network Load Balancers in a region"""
        try:
            elbv2 = self.session.client('elbv2', region_name=region)
            
            load_balancers = []
            paginator = elbv2.get_paginator('describe_load_balancers')
            
            for page in paginator.paginate():
                for lb in page['LoadBalancers']:
                    lb_name = lb['LoadBalancerName']
                    lb_arn = lb['LoadBalancerArn']
                    lb_type = lb['Type']  # 'application' or 'network'
                    
                    # Get metrics
                    # For ALB/NLB, the LoadBalancer dimension uses the full ARN suffix
                    lb_dimension_name = '/'.join(lb_arn.split('/')[-3:])
                    metrics = self.get_lb_metrics(lb_dimension_name, lb_type, region)
                    
                    # Get target information
                    target_info = self.get_target_group_info(lb_arn, region)
                    
                    # Estimate cost
                    monthly_cost = self.get_monthly_cost_estimate(lb_type, region)
                    
                    lb_info = {
                        'name': lb_name,
                        'arn': lb_arn,
                        'type': lb_type,
                        'region': region,
                        'scheme': lb['Scheme'],
                        'state': lb['State']['Code'],
                        'created_time': lb['CreatedTime'],
                        'dns_name': lb['DNSName'],
                        'vpc_id': lb['VpcId'],
                        'availability_zones': [az['ZoneName'] for az in lb['AvailabilityZones']],
                        'metrics': metrics,
                        'monthly_cost': monthly_cost,
                        **target_info
                    }
                    
                    # Add safety check
                    lb_info['safety'] = self.check_lb_safety(lb_info)
                    
                    load_balancers.append(lb_info)
            
            return load_balancers
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing ALB/NLB in {region}: {e}{Colors.END}")
            return []
    
    def list_clb_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List Classic Load Balancers in a region"""
        try:
            elb = self.session.client('elb', region_name=region)
            
            load_balancers = []
            paginator = elb.get_paginator('describe_load_balancers')
            
            for page in paginator.paginate():
                for lb in page['LoadBalancers']:
                    lb_name = lb['LoadBalancerName']
                    
                    # Get metrics
                    metrics = self.get_lb_metrics(lb_name, 'classic', region)
                    
                    # Get instance information
                    instance_info = self.get_clb_instances(lb_name, region)
                    
                    # Estimate cost
                    monthly_cost = self.get_monthly_cost_estimate('classic', region)
                    
                    lb_info = {
                        'name': lb_name,
                        'type': 'classic',
                        'region': region,
                        'scheme': lb['Scheme'],
                        'state': 'active',  # CLBs don't have explicit state
                        'created_time': lb['CreatedTime'],
                        'dns_name': lb['DNSName'],
                        'vpc_id': lb.get('VPCId', 'EC2-Classic'),
                        'availability_zones': lb['AvailabilityZones'],
                        'metrics': metrics,
                        'monthly_cost': monthly_cost,
                        **instance_info
                    }
                    
                    # Add safety check
                    lb_info['safety'] = self.check_lb_safety(lb_info)
                    
                    load_balancers.append(lb_info)
            
            return load_balancers
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing CLB in {region}: {e}{Colors.END}")
            return []
    
    def format_lb_info(self, lb: Dict[str, Any]) -> str:
        """Format load balancer information for display"""
        name = lb['name'][:20] if len(lb['name']) > 20 else lb['name']
        region = lb['region']
        lb_type = lb['type'].upper()
        scheme = lb['scheme'][:8]
        state = lb['state']
        
        target_count = lb['target_count']
        healthy_count = lb['healthy_target_count']
        monthly_cost = lb['monthly_cost']
        
        # Activity indicator
        total_requests = lb['metrics'].get('total_requests', 0)
        if lb['type'] == 'network':
            activity = f"{lb['metrics'].get('avg_active_flows', 0):.0f} flows"
        else:
            activity = f"{total_requests:,} reqs" if total_requests > 0 else "No activity"
        
        created_time = lb['created_time']
        days_ago = (datetime.now(timezone.utc) - created_time).days
        
        # Safety indicator
        if lb['safety']['is_risky']:
            safety_indicator = f"{Colors.RED}⚠{Colors.END}"
        else:
            safety_indicator = f"{Colors.GREEN}✓{Colors.END}"
        
        return f"  {name:<20} | {region:<12} | {lb_type:<7} | {scheme:<8} | {state:<10} | {target_count:>2}/{healthy_count:<2} | {activity:<12} | ${monthly_cost:>5.1f} | {days_ago:>3}d | {safety_indicator}"
    
    def list_all_load_balancers(self) -> List[Dict[str, Any]]:
        """List all load balancers across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*140}{Colors.END}")
        print(f"{Colors.BLUE}Scanning Load Balancers across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*140}{Colors.END}")
        
        all_load_balancers = []
        total_cost = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            
            # Get ALBs and NLBs
            alb_nlb = self.list_alb_nlb_in_region(region)
            
            # Get Classic Load Balancers
            clb = self.list_clb_in_region(region)
            
            region_lbs = alb_nlb + clb
            
            if region_lbs:
                region_cost = sum(lb['monthly_cost'] for lb in region_lbs)
                region_targets = sum(lb['target_count'] for lb in region_lbs)
                
                print(f"{Colors.GREEN}Found {len(region_lbs)} load balancers{Colors.END}")
                print(f"  ALB/NLB: {len(alb_nlb)}, CLB: {len(clb)}")
                print(f"  Total targets: {region_targets}")
                print(f"  Estimated monthly cost: ${region_cost:.2f}")
                
                total_cost += region_cost
                all_load_balancers.extend(region_lbs)
            else:
                print(f"{Colors.GREEN}No load balancers found{Colors.END}")
        
        # Display summary
        risky_count = sum(1 for lb in all_load_balancers if lb['safety']['is_risky'])
        unused_count = sum(1 for lb in all_load_balancers if lb['metrics'].get('total_requests', 0) == 0 and lb['target_count'] == 0)
        
        # Count by type
        alb_count = sum(1 for lb in all_load_balancers if lb['type'] == 'application')
        nlb_count = sum(1 for lb in all_load_balancers if lb['type'] == 'network')
        clb_count = sum(1 for lb in all_load_balancers if lb['type'] == 'classic')
        
        print(f"\n{Colors.BOLD}LOAD BALANCER SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*140}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total load balancers: {Colors.YELLOW}{len(all_load_balancers)}{Colors.END}")
        print(f"  Application (ALB): {Colors.BLUE}{alb_count}{Colors.END}")
        print(f"  Network (NLB): {Colors.BLUE}{nlb_count}{Colors.END}")
        print(f"  Classic (CLB): {Colors.BLUE}{clb_count}{Colors.END}")
        print(f"Load balancers with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Potentially unused load balancers: {Colors.YELLOW}{unused_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Total estimated annual cost: {Colors.YELLOW}${total_cost * 12:.2f}{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        
        if all_load_balancers:
            print(f"\n{Colors.BOLD}LOAD BALANCER DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*140}{Colors.END}")
            print(f"  {'Name':<20} | {'Region':<12} | {'Type':<7} | {'Scheme':<8} | {'State':<10} | {'Tgts':<5} | {'Activity':<12} | {'Cost':<6} | {'Age':<4} | Safe")
            print(f"  {'-'*20} | {'-'*12} | {'-'*7} | {'-'*8} | {'-'*10} | {'-'*5} | {'-'*12} | {'-'*6} | {'-'*4} | {'-'*4}")
            
            # Sort by cost (highest first), then by type
            sorted_lbs = sorted(all_load_balancers, key=lambda x: (-x['monthly_cost'], x['type']))
            
            for lb in sorted_lbs:
                print(self.format_lb_info(lb))
                
                # Show safety warnings
                if lb['safety']['warnings']:
                    for warning in lb['safety']['warnings'][:2]:
                        print(f"    {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # Show breakdown by type and region
            print(f"\n{Colors.BOLD}BREAKDOWN BY TYPE{Colors.END}")
            types = {}
            for lb in all_load_balancers:
                lb_type = lb['type']
                if lb_type not in types:
                    types[lb_type] = {'count': 0, 'cost': 0, 'unused': 0}
                types[lb_type]['count'] += 1
                types[lb_type]['cost'] += lb['monthly_cost']
                if lb['metrics'].get('total_requests', 0) == 0 and lb['target_count'] == 0:
                    types[lb_type]['unused'] += 1
            
            for lb_type, stats in sorted(types.items()):
                print(f"  {lb_type.upper():<12}: {stats['count']} load balancers, ${stats['cost']:.2f}/month ({stats['unused']} potentially unused)")
        
        return all_load_balancers
    
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
    
    def show_lb_selection_menu(self, load_balancers: List[Dict[str, Any]]) -> List[str]:
        """Show menu for load balancer selection"""
        if not load_balancers:
            return []
        
        print(f"\n{Colors.BOLD}SELECT LOAD BALANCERS TO DELETE{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}")
        print("Enter load balancer numbers separated by commas (e.g., 1,3,5)")
        print("Or enter 'all' to select all load balancers")
        print("Or enter 'unused' to select potentially unused load balancers")
        print("Or enter 'clb' to select only Classic Load Balancers")
        print("Or enter 'safe' to select only load balancers without warnings")
        print("")
        
        # Show numbered list
        unused_lbs = []
        safe_lbs = []
        clb_lbs = []
        
        for i, lb in enumerate(load_balancers, 1):
            safety_indicator = f"{Colors.RED}⚠{Colors.END}" if lb['safety']['is_risky'] else f"{Colors.GREEN}✓{Colors.END}"
            target_count = lb['target_count']
            monthly_cost = lb['monthly_cost']
            lb_type = lb['type'].upper()
            
            total_requests = lb['metrics'].get('total_requests', 0)
            unused_indicator = f"{Colors.YELLOW}(UNUSED?){Colors.END}" if total_requests == 0 and target_count == 0 else ""
            
            print(f"{i:2d}. {lb['name']:<25} | {lb['region']:<12} | {lb_type:<7} | {target_count:>2} targets | ${monthly_cost:>5.1f}/mo | {safety_indicator} {unused_indicator}")
            
            if total_requests == 0 and target_count == 0:
                unused_lbs.append(lb['name'])
            if not lb['safety']['is_risky']:
                safe_lbs.append(lb['name'])
            if lb['type'] == 'classic':
                clb_lbs.append(lb['name'])
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Your selection: {Colors.END}").strip().lower()
            
            if choice == 'all':
                return [lb['name'] for lb in load_balancers]
            elif choice == 'unused':
                if unused_lbs:
                    return unused_lbs
                else:
                    print(f"{Colors.RED}No potentially unused load balancers found{Colors.END}")
                    continue
            elif choice == 'clb':
                if clb_lbs:
                    return clb_lbs
                else:
                    print(f"{Colors.RED}No Classic Load Balancers found{Colors.END}")
                    continue
            elif choice == 'safe':
                if safe_lbs:
                    return safe_lbs
                else:
                    print(f"{Colors.RED}No 'safe' load balancers found (all have warnings){Colors.END}")
                    continue
            elif choice == '':
                return []
            else:
                try:
                    indices = [int(x.strip()) for x in choice.split(',')]
                    selected = []
                    
                    for idx in indices:
                        if 1 <= idx <= len(load_balancers):
                            selected.append(load_balancers[idx-1]['name'])
                        else:
                            print(f"{Colors.RED}Invalid load balancer number: {idx}{Colors.END}")
                            raise ValueError()
                    
                    return selected
                    
                except ValueError:
                    print(f"{Colors.RED}Invalid input. Please enter numbers separated by commas, 'all', 'unused', 'clb', or 'safe'{Colors.END}")
    
    def delete_load_balancer(self, lb: Dict[str, Any], dry_run: bool = False) -> bool:
        """Delete a single load balancer"""
        lb_name = lb['name']
        lb_type = lb['type']
        region = lb['region']
        
        if dry_run:
            print(f"  {Colors.BLUE}[DRY RUN] Would delete {lb_type.upper()} load balancer {lb_name}{Colors.END}")
            return True
        
        try:
            if lb_type in ['application', 'network']:
                # Delete ALB/NLB
                elbv2 = self.session.client('elbv2', region_name=region)
                elbv2.delete_load_balancer(LoadBalancerArn=lb['arn'])
            else:
                # Delete CLB
                elb = self.session.client('elb', region_name=region)
                elb.delete_load_balancer(LoadBalancerName=lb_name)
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'LoadBalancerNotFound':
                print(f"  {Colors.YELLOW}Load balancer {lb_name} already deleted{Colors.END}")
                return True
            else:
                print(f"  {Colors.RED}Error deleting {lb_name}: {e}{Colors.END}")
                return False
    
    def delete_load_balancers(self, load_balancers: List[Dict[str, Any]], selected_lb_names: List[str], dry_run: bool = False):
        """Delete selected load balancers"""
        lbs_to_delete = [lb for lb in load_balancers if lb['name'] in selected_lb_names]
        
        if not lbs_to_delete:
            print(f"{Colors.YELLOW}No load balancers selected for deletion.{Colors.END}")
            return
        
        mode_text = "DRY RUN - " if dry_run else ""
        print(f"\n{Colors.RED}{'='*70}{Colors.END}")
        print(f"{Colors.RED}{mode_text}DELETING LOAD BALANCERS{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}THIS CANNOT BE UNDONE!{Colors.END}")
        print(f"{Colors.RED}{'='*70}{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, lb in enumerate(lbs_to_delete, 1):
            lb_name = lb['name']
            region = lb['region']
            lb_type = lb['type'].upper()
            monthly_cost = lb['monthly_cost']
            target_count = lb['target_count']
            
            print(f"\n[{i}/{len(lbs_to_delete)}] Processing {lb_type}: {lb_name}")
            print(f"  Region: {region}, Targets: {target_count}, Cost: ${monthly_cost:.2f}/month")
            
            # Show warnings
            if lb['safety']['warnings']:
                for warning in lb['safety']['warnings'][:3]:
                    print(f"  {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            if self.delete_load_balancer(lb, dry_run):
                success_text = "Would delete" if dry_run else "Successfully deleted"
                print(f"  {Colors.GREEN}✓ {success_text} {lb_name}{Colors.END}")
                deleted_count += 1
                total_savings += monthly_cost
            else:
                print(f"  {Colors.RED}✗ Failed to delete {lb_name}{Colors.END}")
                failed_count += 1
            
            # Small delay to avoid rate limiting
            if not dry_run:
                time.sleep(2)  # LB deletion can be slow
        
        # Final summary
        print(f"\n{Colors.BOLD}{'DRY RUN ' if dry_run else ''}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        success_text = "would be deleted" if dry_run else "deleted"
        print(f"Successfully {success_text}: {Colors.GREEN}{deleted_count} load balancers{Colors.END}")
        print(f"Failed: {Colors.RED}{failed_count} load balancers{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        
        if not dry_run and deleted_count > 0:
            print(f"\n{Colors.YELLOW}Note: Load balancer deletion may take several minutes to complete.{Colors.END}")
    
    def run(self, dry_run: bool = False):
        """Main execution flow"""
        mode_text = " (DRY RUN MODE)" if dry_run else ""
        print(f"{Colors.BOLD}AWS Load Balancer Cleanup Tool{mode_text}{Colors.END}")
        print(f"{Colors.BLUE}{'='*70}{Colors.END}")
        
        if dry_run:
            print(f"{Colors.BLUE}Running in DRY RUN mode - no actual deletions will be performed{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all load balancers
        load_balancers = self.list_all_load_balancers()
        
        if not load_balancers:
            print(f"\n{Colors.GREEN}No load balancers found! Nothing to delete.{Colors.END}")
            return
        
        # Show deletion options
        total_cost = sum(lb['monthly_cost'] for lb in load_balancers)
        risky_count = sum(1 for lb in load_balancers if lb['safety']['is_risky'])
        unused_count = sum(1 for lb in load_balancers if lb['metrics'].get('total_requests', 0) == 0 and lb['target_count'] == 0)
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION OPTIONS{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Total load balancers: {Colors.BLUE}{len(load_balancers)}{Colors.END}")
        print(f"Load balancers with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Potentially unused load balancers: {Colors.YELLOW}{unused_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Potential annual savings: {Colors.GREEN}${total_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}⚠️  Deletion will permanently remove selected load balancers!{Colors.END}")
            print(f"{Colors.RED}⚠️  This action CANNOT be undone!{Colors.END}")
        
        # Ask what user wants to do
        proceed_msg = "Do you want to proceed with load balancer selection?" if not dry_run else "Do you want to see what would be deleted?"
        if not self.get_user_confirmation(proceed_msg):
            return
        
        # Let user select load balancers
        selected_lb_names = self.show_lb_selection_menu(load_balancers)
        
        if not selected_lb_names:
            print(f"{Colors.BLUE}No load balancers selected. Exiting.{Colors.END}")
            return
        
        selected_lbs = [lb for lb in load_balancers if lb['name'] in selected_lb_names]
        selected_cost = sum(lb['monthly_cost'] for lb in selected_lbs)
        
        # Final confirmation
        confirmation_text = "DRY RUN CONFIRMATION" if dry_run else "FINAL CONFIRMATION"
        print(f"\n{Colors.RED}{confirmation_text}{Colors.END}")
        print(f"Selected load balancers: {Colors.YELLOW}{len(selected_lbs)}{Colors.END}")
        print(f"Monthly savings: {Colors.GREEN}${selected_cost:.2f}{Colors.END}")
        print(f"Annual savings: {Colors.GREEN}${selected_cost * 12:.2f}{Colors.END}")
        
        final_question = "Proceed with analysis?" if dry_run else "Are you absolutely sure you want to delete these load balancers?"
        if self.get_user_confirmation(final_question):
            self.delete_load_balancers(load_balancers, selected_lb_names, dry_run)
        else:
            print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS Load Balancer Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 loadbalancer_cleanup.py                 # Use default AWS profile
  python3 loadbalancer_cleanup.py --profile dev   # Use specific profile
  python3 loadbalancer_cleanup.py --dry-run       # Test mode - no actual deletions
  
Features:
  - Lists all Load Balancers (ALB, NLB, CLB) with cost estimates
  - Shows target health and activity metrics
  - Identifies potentially unused load balancers
  - Safety warnings for important load balancers
  - High cost impact - LBs cost $18-22+ per month each
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
        cleaner = LoadBalancerCleaner(profile_name=args.profile)
        cleaner.run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()
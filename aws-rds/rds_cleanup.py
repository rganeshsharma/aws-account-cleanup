#!/usr/bin/env python3
"""
AWS RDS Database Cleanup Tool
Lists all RDS databases and allows safe deletion with cost analysis.
RDS instances can be very expensive ($50-500+ per month), making cleanup critical.
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

class RDSCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS RDS cleaner"""
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
                rds = self.session.client('rds', region_name=region)
                rds.describe_db_instances(MaxRecords=1)
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
    
    def get_rds_pricing(self, instance_class: str, engine: str, region: str) -> float:
        """Get rough monthly pricing for RDS instance"""
        # Simplified pricing estimates (actual pricing varies by region and reserved instances)
        # These are on-demand prices for common configurations
        
        base_pricing = {
            # General Purpose (gp2/gp3)
            'db.t3.micro': 0.017,    # $0.017/hour = ~$12.24/month
            'db.t3.small': 0.034,    # $0.034/hour = ~$24.48/month
            'db.t3.medium': 0.068,   # $0.068/hour = ~$48.96/month
            'db.t3.large': 0.136,    # $0.136/hour = ~$97.92/month
            'db.t3.xlarge': 0.272,   # $0.272/hour = ~$195.84/month
            'db.t3.2xlarge': 0.544,  # $0.544/hour = ~$391.68/month
            
            # Memory Optimized
            'db.r5.large': 0.240,    # $0.240/hour = ~$172.8/month
            'db.r5.xlarge': 0.480,   # $0.480/hour = ~$345.6/month
            'db.r5.2xlarge': 0.960,  # $0.960/hour = ~$691.2/month
            'db.r5.4xlarge': 1.920,  # $1.920/hour = ~$1382.4/month
            
            # Compute Optimized
            'db.c5.large': 0.192,    # $0.192/hour = ~$138.24/month
            'db.c5.xlarge': 0.384,   # $0.384/hour = ~$276.48/month
            'db.c5.2xlarge': 0.768,  # $0.768/hour = ~$552.96/month
            
            # Previous generation (cheaper)
            'db.t2.micro': 0.017,
            'db.t2.small': 0.034,
            'db.t2.medium': 0.068,
            'db.m5.large': 0.192,
            'db.m5.xlarge': 0.384,
        }
        
        # Engine multipliers (some engines cost more)
        engine_multipliers = {
            'mysql': 1.0,
            'postgres': 1.0,
            'mariadb': 1.0,
            'oracle-ee': 2.5,      # Oracle Enterprise is much more expensive
            'oracle-se2': 1.8,     # Oracle Standard Edition
            'sqlserver-ex': 1.0,   # SQL Server Express (free license)
            'sqlserver-web': 1.3,  # SQL Server Web
            'sqlserver-se': 2.0,   # SQL Server Standard
            'sqlserver-ee': 3.0,   # SQL Server Enterprise
            'aurora-mysql': 1.2,   # Aurora costs more than regular RDS
            'aurora-postgresql': 1.2,
        }
        
        # Region multipliers (some regions are more expensive)
        expensive_regions = ['ap-south-1', 'ap-southeast-1', 'sa-east-1', 'eu-central-1']
        region_multiplier = 1.2 if region in expensive_regions else 1.0
        
        # Get base hourly cost
        hourly_cost = base_pricing.get(instance_class, 0.1)  # Default to $0.1/hour if unknown
        
        # Apply engine multiplier
        engine_key = engine.lower().replace('-', '-').split('-')[0] if '-' in engine else engine.lower()
        engine_multiplier = engine_multipliers.get(engine_key, 1.0)
        
        # Calculate monthly cost (24 hours * 30 days)
        monthly_cost = hourly_cost * 24 * 30 * engine_multiplier * region_multiplier
        
        return monthly_cost
    
    def get_db_metrics(self, db_identifier: str, region: str) -> Dict[str, Any]:
        """Get CloudWatch metrics for RDS instance"""
        try:
            cloudwatch = self.session.client('cloudwatch', region_name=region)
            
            # Get metrics for the last 30 days
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=30)
            
            # Database connections
            connections_response = cloudwatch.get_metric_statistics(
                Namespace='AWS/RDS',
                MetricName='DatabaseConnections',
                Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_identifier}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,  # Daily
                Statistics=['Average', 'Maximum']
            )
            
            # CPU Utilization
            cpu_response = cloudwatch.get_metric_statistics(
                Namespace='AWS/RDS',
                MetricName='CPUUtilization',
                Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_identifier}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,
                Statistics=['Average', 'Maximum']
            )
            
            # Database connections
            avg_connections = 0
            max_connections = 0
            if connections_response['Datapoints']:
                avg_connections = sum(point['Average'] for point in connections_response['Datapoints']) / len(connections_response['Datapoints'])
                max_connections = max(point['Maximum'] for point in connections_response['Datapoints'])
            
            # CPU utilization
            avg_cpu = 0
            max_cpu = 0
            if cpu_response['Datapoints']:
                avg_cpu = sum(point['Average'] for point in cpu_response['Datapoints']) / len(cpu_response['Datapoints'])
                max_cpu = max(point['Maximum'] for point in cpu_response['Datapoints'])
            
            return {
                'avg_connections': avg_connections,
                'max_connections': max_connections,
                'avg_cpu_utilization': avg_cpu,
                'max_cpu_utilization': max_cpu,
                'has_activity': avg_connections > 0 or avg_cpu > 1
            }
            
        except ClientError as e:
            return {
                'error': str(e),
                'avg_connections': 0,
                'max_connections': 0,
                'avg_cpu_utilization': 0,
                'max_cpu_utilization': 0,
                'has_activity': False
            }
    
    def check_db_safety(self, db_info: Dict[str, Any]) -> Dict[str, Any]:
        """Check if database appears to be important or in use"""
        db_identifier = db_info['identifier']
        safety_warnings = []
        
        # Check for important patterns in name
        important_patterns = [
            'prod', 'production', 'live', 'main', 'primary', 'master',
            'critical', 'backup', 'replica', 'standby'
        ]
        
        identifier_lower = db_identifier.lower()
        for pattern in important_patterns:
            if pattern in identifier_lower:
                safety_warnings.append(f"Name contains '{pattern}' - might be important")
        
        # Check if database has recent activity
        metrics = db_info['metrics']
        if metrics['has_activity']:
            if metrics['avg_connections'] > 1:
                safety_warnings.append(f"Active database: {metrics['avg_connections']:.1f} avg connections")
            if metrics['avg_cpu_utilization'] > 5:
                safety_warnings.append(f"CPU usage: {metrics['avg_cpu_utilization']:.1f}% average")
        
        # Check if database has snapshots (indicates it's being backed up)
        if db_info.get('automated_backup_enabled'):
            safety_warnings.append("Automated backups enabled")
        
        # Check if database is in a VPC (more likely to be important)
        if db_info.get('vpc_id'):
            safety_warnings.append("Database in VPC")
        
        # Check if database is encrypted (more likely to be important)
        if db_info.get('encrypted'):
            safety_warnings.append("Database is encrypted")
        
        # Check if database is Multi-AZ (high availability setup)
        if db_info.get('multi_az'):
            safety_warnings.append("Multi-AZ deployment (high availability)")
        
        # Check if database has read replicas
        if db_info.get('read_replica_count', 0) > 0:
            safety_warnings.append(f"Has {db_info['read_replica_count']} read replicas")
        
        # Check if recently created (within 7 days)
        created_time = db_info['created_time']
        days_since_created = (datetime.now(timezone.utc) - created_time).days
        if days_since_created <= 7:
            safety_warnings.append(f"Recently created ({days_since_created} days ago)")
        
        return {
            'is_risky': len(safety_warnings) > 0,
            'warnings': safety_warnings,
            'days_since_created': days_since_created
        }
    
    def list_rds_instances_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all RDS instances in a specific region"""
        try:
            rds = self.session.client('rds', region_name=region)
            
            instances = []
            paginator = rds.get_paginator('describe_db_instances')
            
            for page in paginator.paginate():
                for db_instance in page['DBInstances']:
                    db_identifier = db_instance['DBInstanceIdentifier']
                    
                    # Skip Aurora cluster members (we'll handle clusters separately)
                    if db_instance.get('DBClusterIdentifier'):
                        continue
                    
                    # Get metrics
                    metrics = self.get_db_metrics(db_identifier, region)
                    
                    # Get pricing
                    monthly_cost = self.get_rds_pricing(
                        db_instance['DBInstanceClass'],
                        db_instance['Engine'],
                        region
                    )
                    
                    # Count read replicas
                    read_replica_count = len(db_instance.get('ReadReplicaDBInstanceIdentifiers', []))
                    
                    db_info = {
                        'identifier': db_identifier,
                        'region': region,
                        'engine': db_instance['Engine'],
                        'engine_version': db_instance['EngineVersion'],
                        'instance_class': db_instance['DBInstanceClass'],
                        'status': db_instance['DBInstanceStatus'],
                        'allocated_storage': db_instance['AllocatedStorage'],
                        'storage_type': db_instance.get('StorageType', 'gp2'),
                        'multi_az': db_instance['MultiAZ'],
                        'vpc_id': db_instance.get('DbInstancePort', {}).get('VpcId'),
                        'encrypted': db_instance.get('StorageEncrypted', False),
                        'created_time': db_instance['InstanceCreateTime'],
                        'backup_retention': db_instance['BackupRetentionPeriod'],
                        'automated_backup_enabled': db_instance['BackupRetentionPeriod'] > 0,
                        'read_replica_count': read_replica_count,
                        'master_username': db_instance.get('MasterUsername', ''),
                        'endpoint': db_instance.get('Endpoint', {}).get('Address', 'N/A'),
                        'port': db_instance.get('Endpoint', {}).get('Port', 'N/A'),
                        'metrics': metrics,
                        'monthly_cost': monthly_cost
                    }
                    
                    # Add safety check
                    db_info['safety'] = self.check_db_safety(db_info)
                    
                    instances.append(db_info)
            
            return instances
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing RDS instances in {region}: {e}{Colors.END}")
            return []
    
    def list_aurora_clusters_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all Aurora clusters in a specific region"""
        try:
            rds = self.session.client('rds', region_name=region)
            
            clusters = []
            
            try:
                paginator = rds.get_paginator('describe_db_clusters')
                
                for page in paginator.paginate():
                    for cluster in page['DBClusters']:
                        cluster_identifier = cluster['DBClusterIdentifier']
                        
                        # Get total cost (sum of all cluster instances)
                        total_monthly_cost = 0
                        instance_count = 0
                        
                        for member in cluster.get('DBClusterMembers', []):
                            if member.get('DBInstanceIdentifier'):
                                instance_count += 1
                                # Get instance details for pricing
                                try:
                                    instance_response = rds.describe_db_instances(
                                        DBInstanceIdentifier=member['DBInstanceIdentifier']
                                    )
                                    instance = instance_response['DBInstances'][0]
                                    instance_cost = self.get_rds_pricing(
                                        instance['DBInstanceClass'],
                                        cluster['Engine'],
                                        region
                                    )
                                    total_monthly_cost += instance_cost
                                except ClientError:
                                    # Estimate if we can't get instance details
                                    total_monthly_cost += 50  # Rough estimate
                        
                        # Get cluster metrics (use first writer instance)
                        writer_instance = None
                        for member in cluster.get('DBClusterMembers', []):
                            if member.get('IsClusterWriter'):
                                writer_instance = member.get('DBInstanceIdentifier')
                                break
                        
                        metrics = {'has_activity': False, 'avg_connections': 0}
                        if writer_instance:
                            metrics = self.get_db_metrics(writer_instance, region)
                        
                        cluster_info = {
                            'identifier': cluster_identifier,
                            'region': region,
                            'engine': cluster['Engine'],
                            'engine_version': cluster['EngineVersion'],
                            'instance_class': 'Aurora Cluster',
                            'status': cluster['Status'],
                            'allocated_storage': cluster.get('AllocatedStorage', 0),
                            'storage_type': 'Aurora',
                            'multi_az': True,  # Aurora is inherently multi-AZ
                            'vpc_id': cluster.get('VpcId'),
                            'encrypted': cluster.get('StorageEncrypted', False),
                            'created_time': cluster['ClusterCreateTime'],
                            'backup_retention': cluster['BackupRetentionPeriod'],
                            'automated_backup_enabled': cluster['BackupRetentionPeriod'] > 0,
                            'read_replica_count': instance_count - 1 if instance_count > 1 else 0,
                            'master_username': cluster.get('MasterUsername', ''),
                            'endpoint': cluster.get('Endpoint', 'N/A'),
                            'port': cluster.get('Port', 'N/A'),
                            'metrics': metrics,
                            'monthly_cost': total_monthly_cost,
                            'instance_count': instance_count,
                            'is_aurora_cluster': True
                        }
                        
                        # Add safety check
                        cluster_info['safety'] = self.check_db_safety(cluster_info)
                        
                        clusters.append(cluster_info)
                        
            except ClientError as e:
                # Aurora might not be available in all regions
                if 'InvalidParameterValue' not in str(e):
                    print(f"{Colors.YELLOW}Note: Aurora not available in {region}{Colors.END}")
            
            return clusters
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing Aurora clusters in {region}: {e}{Colors.END}")
            return []
    
    def format_db_info(self, db: Dict[str, Any]) -> str:
        """Format database information for display"""
        identifier = db['identifier'][:20] if len(db['identifier']) > 20 else db['identifier']
        region = db['region']
        engine = db['engine'][:10]
        instance_class = db['instance_class'][:15] if 'Cluster' not in db['instance_class'] else 'Aurora'
        status = db['status'][:10]
        
        storage = f"{db['allocated_storage']}GB" if db['allocated_storage'] > 0 else 'Aurora'
        monthly_cost = db['monthly_cost']
        
        # Activity indicator
        metrics = db['metrics']
        if metrics.get('has_activity'):
            activity = f"{metrics['avg_connections']:.0f} conn"
        else:
            activity = "No activity"
        
        created_time = db['created_time']
        days_ago = (datetime.now(timezone.utc) - created_time).days
        
        # Multi-AZ indicator
        multi_az = "✓" if db['multi_az'] else "✗"
        
        # Safety indicator
        if db['safety']['is_risky']:
            safety_indicator = f"{Colors.RED}⚠{Colors.END}"
        else:
            safety_indicator = f"{Colors.GREEN}✓{Colors.END}"
        
        return f"  {identifier:<20} | {region:<12} | {engine:<10} | {instance_class:<15} | {status:<10} | {storage:<8} | {multi_az:<3} | {activity:<12} | ${monthly_cost:>6.0f} | {days_ago:>3}d | {safety_indicator}"
    
    def list_all_databases(self) -> List[Dict[str, Any]]:
        """List all RDS databases and Aurora clusters across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*140}{Colors.END}")
        print(f"{Colors.BLUE}Scanning RDS Databases and Aurora Clusters across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*140}{Colors.END}")
        
        all_databases = []
        total_cost = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            
            # Get RDS instances
            rds_instances = self.list_rds_instances_in_region(region)
            
            # Get Aurora clusters
            aurora_clusters = self.list_aurora_clusters_in_region(region)
            
            region_databases = rds_instances + aurora_clusters
            
            if region_databases:
                region_cost = sum(db['monthly_cost'] for db in region_databases)
                
                print(f"{Colors.GREEN}Found {len(region_databases)} databases{Colors.END}")
                print(f"  RDS Instances: {len(rds_instances)}")
                print(f"  Aurora Clusters: {len(aurora_clusters)}")
                print(f"  Estimated monthly cost: ${region_cost:.2f}")
                
                total_cost += region_cost
                all_databases.extend(region_databases)
            else:
                print(f"{Colors.GREEN}No databases found{Colors.END}")
        
        # Display summary
        risky_count = sum(1 for db in all_databases if db['safety']['is_risky'])
        inactive_count = sum(1 for db in all_databases if not db['metrics'].get('has_activity', False))
        
        # Count by engine
        engines = {}
        for db in all_databases:
            engine = db['engine']
            if engine not in engines:
                engines[engine] = {'count': 0, 'cost': 0}
            engines[engine]['count'] += 1
            engines[engine]['cost'] += db['monthly_cost']
        
        print(f"\n{Colors.BOLD}RDS DATABASE SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*140}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total databases found: {Colors.YELLOW}{len(all_databases)}{Colors.END}")
        print(f"Databases with safety warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Inactive databases (no recent activity): {Colors.YELLOW}{inactive_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Total estimated annual cost: {Colors.YELLOW}${total_cost * 12:.2f}{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        
        if all_databases:
            print(f"\n{Colors.BOLD}DATABASE DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*140}{Colors.END}")
            print(f"  {'Database ID':<20} | {'Region':<12} | {'Engine':<10} | {'Instance Class':<15} | {'Status':<10} | {'Storage':<8} | {'MAZ':<3} | {'Activity':<12} | {'Cost':<7} | {'Age':<4} | Safe")
            print(f"  {'-'*20} | {'-'*12} | {'-'*10} | {'-'*15} | {'-'*10} | {'-'*8} | {'-'*3} | {'-'*12} | {'-'*7} | {'-'*4} | {'-'*4}")
            
            # Sort by cost (highest first)
            sorted_databases = sorted(all_databases, key=lambda x: -x['monthly_cost'])
            
            for db in sorted_databases:
                print(self.format_db_info(db))
                
                # Show safety warnings
                if db['safety']['warnings']:
                    for warning in db['safety']['warnings'][:2]:
                        print(f"    {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # Show breakdown by engine
            print(f"\n{Colors.BOLD}BREAKDOWN BY ENGINE{Colors.END}")
            for engine, stats in sorted(engines.items(), key=lambda x: -x[1]['cost']):
                print(f"  {engine:<20}: {stats['count']} databases, ${stats['cost']:.2f}/month")
        
        return all_databases
    
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
    
    def show_db_selection_menu(self, databases: List[Dict[str, Any]]) -> List[str]:
        """Show menu for database selection"""
        if not databases:
            return []
        
        print(f"\n{Colors.BOLD}SELECT DATABASES TO DELETE{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}")
        print("Enter database numbers separated by commas (e.g., 1,3,5)")
        print("Or enter 'all' to select all databases")
        print("Or enter 'inactive' to select databases with no recent activity")
        print("Or enter 'safe' to select only databases without warnings")
        print("")
        
        # Show numbered list
        inactive_dbs = []
        safe_dbs = []
        
        for i, db in enumerate(databases, 1):
            safety_indicator = f"{Colors.RED}⚠{Colors.END}" if db['safety']['is_risky'] else f"{Colors.GREEN}✓{Colors.END}"
            monthly_cost = db['monthly_cost']
            engine = db['engine']
            
            activity_indicator = ""
            if not db['metrics'].get('has_activity', False):
                activity_indicator = f"{Colors.YELLOW}(INACTIVE){Colors.END}"
                inactive_dbs.append(db['identifier'])
            
            if not db['safety']['is_risky']:
                safe_dbs.append(db['identifier'])
            
            print(f"{i:2d}. {db['identifier']:<25} | {db['region']:<12} | {engine:<12} | ${monthly_cost:>6.0f}/mo | {safety_indicator} {activity_indicator}")
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Your selection: {Colors.END}").strip().lower()
            
            if choice == 'all':
                return [db['identifier'] for db in databases]
            elif choice == 'inactive':
                if inactive_dbs:
                    return inactive_dbs
                else:
                    print(f"{Colors.RED}No inactive databases found{Colors.END}")
                    continue
            elif choice == 'safe':
                if safe_dbs:
                    return safe_dbs
                else:
                    print(f"{Colors.RED}No 'safe' databases found (all have warnings){Colors.END}")
                    continue
            elif choice == '':
                return []
            else:
                try:
                    indices = [int(x.strip()) for x in choice.split(',')]
                    selected = []
                    
                    for idx in indices:
                        if 1 <= idx <= len(databases):
                            selected.append(databases[idx-1]['identifier'])
                        else:
                            print(f"{Colors.RED}Invalid database number: {idx}{Colors.END}")
                            raise ValueError()
                    
                    return selected
                    
                except ValueError:
                    print(f"{Colors.RED}Invalid input. Please enter numbers separated by commas, 'all', 'inactive', or 'safe'{Colors.END}")
    
    def delete_database(self, db: Dict[str, Any], skip_final_snapshot: bool = False, dry_run: bool = False) -> bool:
        """Delete a single RDS database or Aurora cluster"""
        db_identifier = db['identifier']
        region = db['region']
        
        if dry_run:
            print(f"  {Colors.BLUE}[DRY RUN] Would delete database {db_identifier}{Colors.END}")
            return True
        
        try:
            rds = self.session.client('rds', region_name=region)
            
            if db.get('is_aurora_cluster'):
                # Delete Aurora cluster
                rds.delete_db_cluster(
                    DBClusterIdentifier=db_identifier,
                    SkipFinalSnapshot=skip_final_snapshot,
                    FinalDBSnapshotIdentifier=f"{db_identifier}-final-snapshot-{int(time.time())}" if not skip_final_snapshot else None
                )
            else:
                # Delete RDS instance
                rds.delete_db_instance(
                    DBInstanceIdentifier=db_identifier,
                    SkipFinalSnapshot=skip_final_snapshot,
                    FinalDBSnapshotIdentifier=f"{db_identifier}-final-snapshot-{int(time.time())}" if not skip_final_snapshot else None
                )
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ['DBInstanceNotFoundFault', 'DBClusterNotFoundFault']:
                print(f"  {Colors.YELLOW}Database {db_identifier} already deleted{Colors.END}")
                return True
            else:
                print(f"  {Colors.RED}Error deleting {db_identifier}: {e}{Colors.END}")
                return False
    
    def delete_databases(self, databases: List[Dict[str, Any]], selected_db_names: List[str], skip_final_snapshot: bool = False, dry_run: bool = False):
        """Delete selected databases"""
        dbs_to_delete = [db for db in databases if db['identifier'] in selected_db_names]
        
        if not dbs_to_delete:
            print(f"{Colors.YELLOW}No databases selected for deletion.{Colors.END}")
            return
        
        mode_text = "DRY RUN - " if dry_run else ""
        print(f"\n{Colors.RED}{'='*80}{Colors.END}")
        print(f"{Colors.RED}{mode_text}DELETING RDS DATABASES AND AURORA CLUSTERS{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}THIS CANNOT BE UNDONE!{Colors.END}")
        print(f"{Colors.RED}{'='*80}{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, db in enumerate(dbs_to_delete, 1):
            db_identifier = db['identifier']
            region = db['region']
            engine = db['engine']
            monthly_cost = db['monthly_cost']
            
            print(f"\n[{i}/{len(dbs_to_delete)}] Processing database: {db_identifier}")
            print(f"  Engine: {engine}, Region: {region}, Cost: ${monthly_cost:.2f}/month")
            
            # Show warnings
            if db['safety']['warnings']:
                for warning in db['safety']['warnings'][:3]:
                    print(f"  {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            if self.delete_database(db, skip_final_snapshot, dry_run):
                success_text = "Would delete" if dry_run else "Successfully deleted"
                print(f"  {Colors.GREEN}✓ {success_text} {db_identifier}{Colors.END}")
                if not dry_run and not skip_final_snapshot:
                    print(f"  {Colors.BLUE}Final snapshot will be created{Colors.END}")
                deleted_count += 1
                total_savings += monthly_cost
            else:
                print(f"  {Colors.RED}✗ Failed to delete {db_identifier}{Colors.END}")
                failed_count += 1
            
            # Longer delay for RDS operations
            if not dry_run:
                time.sleep(3)
        
        # Final summary
        print(f"\n{Colors.BOLD}{'DRY RUN ' if dry_run else ''}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        success_text = "would be deleted" if dry_run else "deleted"
        print(f"Successfully {success_text}: {Colors.GREEN}{deleted_count} databases{Colors.END}")
        print(f"Failed: {Colors.RED}{failed_count} databases{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        
        if not dry_run and deleted_count > 0:
            print(f"\n{Colors.YELLOW}Note: Database deletion may take 5-15 minutes to complete.{Colors.END}")
            if not skip_final_snapshot:
                print(f"{Colors.BLUE}Final snapshots are being created for backup purposes.{Colors.END}")
    
    def run(self, dry_run: bool = False):
        """Main execution flow"""
        mode_text = " (DRY RUN MODE)" if dry_run else ""
        print(f"{Colors.BOLD}AWS RDS Database Cleanup Tool{mode_text}{Colors.END}")
        print(f"{Colors.BLUE}{'='*70}{Colors.END}")
        
        if dry_run:
            print(f"{Colors.BLUE}Running in DRY RUN mode - no actual deletions will be performed{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all databases
        databases = self.list_all_databases()
        
        if not databases:
            print(f"\n{Colors.GREEN}No RDS databases found! Nothing to delete.{Colors.END}")
            return
        
        # Show deletion options
        total_cost = sum(db['monthly_cost'] for db in databases)
        risky_count = sum(1 for db in databases if db['safety']['is_risky'])
        inactive_count = sum(1 for db in databases if not db['metrics'].get('has_activity', False))
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION OPTIONS{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Total databases: {Colors.BLUE}{len(databases)}{Colors.END}")
        print(f"Databases with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Inactive databases: {Colors.YELLOW}{inactive_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Potential annual savings: {Colors.GREEN}${total_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}⚠️  RDS databases are expensive! Double-check before deletion!{Colors.END}")
            print(f"{Colors.RED}⚠️  This action CANNOT be undone (except from snapshots)!{Colors.END}")
        
        # Ask what user wants to do
        proceed_msg = "Do you want to proceed with database selection?" if not dry_run else "Do you want to see what would be deleted?"
        if not self.get_user_confirmation(proceed_msg):
            return
        
        # Let user select databases
        selected_db_names = self.show_db_selection_menu(databases)
        
        if not selected_db_names:
            print(f"{Colors.BLUE}No databases selected. Exiting.{Colors.END}")
            return
        
        selected_dbs = [db for db in databases if db['identifier'] in selected_db_names]
        selected_cost = sum(db['monthly_cost'] for db in selected_dbs)
        
        # Ask about final snapshots
        skip_final_snapshot = False
        if not dry_run:
            print(f"\n{Colors.YELLOW}FINAL SNAPSHOT OPTION{Colors.END}")
            print("AWS can create a final snapshot before deletion for backup purposes.")
            print("This costs extra storage but allows recovery if needed.")
            skip_final_snapshot = self.get_user_confirmation("Skip final snapshot? (not recommended for production)")
        
        # Final confirmation
        confirmation_text = "DRY RUN CONFIRMATION" if dry_run else "FINAL CONFIRMATION"
        print(f"\n{Colors.RED}{confirmation_text}{Colors.END}")
        print(f"Selected databases: {Colors.YELLOW}{len(selected_dbs)}{Colors.END}")
        print(f"Monthly savings: {Colors.GREEN}${selected_cost:.2f}{Colors.END}")
        print(f"Annual savings: {Colors.GREEN}${selected_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            snapshot_text = "WITHOUT final snapshots" if skip_final_snapshot else "WITH final snapshots"
            print(f"Final snapshots: {Colors.YELLOW}{snapshot_text}{Colors.END}")
        
        final_question = "Proceed with analysis?" if dry_run else "Are you absolutely sure you want to delete these databases?"
        if self.get_user_confirmation(final_question):
            self.delete_databases(databases, selected_db_names, skip_final_snapshot, dry_run)
        else:
            print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS RDS Database Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 rds_cleanup.py                          # Use default AWS profile
  python3 rds_cleanup.py --profile dev            # Use specific profile
  python3 rds_cleanup.py --dry-run                # Test mode - no actual deletions
  
Features:
  - Lists all RDS instances and Aurora clusters with cost estimates
  - Shows activity metrics and connection statistics
  - Identifies inactive databases with no recent usage
  - Safety warnings for production and active databases
  - Very high cost impact - databases can cost $50-500+ per month
  - Option to create final snapshots before deletion
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
        cleaner = RDSCleaner(profile_name=args.profile)
        cleaner.run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()
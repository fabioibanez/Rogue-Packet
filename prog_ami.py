#!/usr/bin/env python3
"""
Test script for programmatic AMI lookup across AWS regions
Tests both describe_images and SSM Parameter Store approaches
"""

import boto3
import time
from datetime import datetime

# Test regions
TEST_REGIONS = [
    'us-east-1',
    'us-west-2', 
    'eu-west-1',
    'ap-southeast-1',
    'sa-east-1'
]

# Colors for output
COLOR_GREEN = '\033[92m'
COLOR_RED = '\033[91m'
COLOR_YELLOW = '\033[93m'
COLOR_BLUE = '\033[94m'
COLOR_RESET = '\033[0m'

def get_latest_ubuntu_ami_describe(region):
    """Get latest Ubuntu 22.04 AMI using describe_images"""
    try:
        ec2_client = boto3.client('ec2', region_name=region)
        
        response = ec2_client.describe_images(
            Owners=['099720109477'],  # Canonical (Ubuntu)
            Filters=[
                {
                    'Name': 'name', 
                    'Values': ['ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*']
                },
                {
                    'Name': 'state', 
                    'Values': ['available']
                },
                {
                    'Name': 'architecture',
                    'Values': ['x86_64']
                }
            ]
        )
        
        if not response['Images']:
            return None, "No Ubuntu 22.04 AMIs found"
        
        # Sort by creation date and get the latest
        latest_ami = sorted(
            response['Images'], 
            key=lambda x: x['CreationDate'], 
            reverse=True
        )[0]
        
        return {
            'ami_id': latest_ami['ImageId'],
            'name': latest_ami['Name'],
            'creation_date': latest_ami['CreationDate'],
            'description': latest_ami.get('Description', 'N/A')
        }, None
        
    except Exception as e:
        return None, str(e)

def get_latest_ubuntu_ami_ssm(region):
    """Get latest Ubuntu 22.04 AMI using SSM Parameter Store"""
    try:
        ssm_client = boto3.client('ssm', region_name=region)
        
        # AWS maintains this parameter with the latest Ubuntu 22.04 AMI ID
        parameter_name = '/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id'
        
        response = ssm_client.get_parameter(Name=parameter_name)
        ami_id = response['Parameter']['Value']
        
        # Get additional info about this AMI
        ec2_client = boto3.client('ec2', region_name=region)
        ami_response = ec2_client.describe_images(ImageIds=[ami_id])
        
        if ami_response['Images']:
            ami_info = ami_response['Images'][0]
            return {
                'ami_id': ami_id,
                'name': ami_info['Name'],
                'creation_date': ami_info['CreationDate'],
                'description': ami_info.get('Description', 'N/A')
            }, None
        else:
            return {'ami_id': ami_id}, None
            
    except Exception as e:
        return None, str(e)

def test_ami_lookup():
    """Test AMI lookup in multiple regions using both methods"""
    print(f"{COLOR_BLUE}🔍 Testing AMI Lookup Across Regions{COLOR_RESET}")
    print("=" * 60)
    
    results = {}
    
    for region in TEST_REGIONS:
        print(f"\n{COLOR_YELLOW}📍 Testing region: {region}{COLOR_RESET}")
        results[region] = {}
        
        # Test Method 1: describe_images
        print("  Method 1: describe_images")
        start_time = time.time()
        ami_info, error = get_latest_ubuntu_ami_describe(region)
        duration = time.time() - start_time
        
        if ami_info:
            print(f"    {COLOR_GREEN}✓ Success ({duration:.2f}s){COLOR_RESET}")
            print(f"    AMI ID: {ami_info['ami_id']}")
            print(f"    Name: {ami_info['name']}")
            print(f"    Created: {ami_info['creation_date']}")
            results[region]['describe_images'] = ami_info
        else:
            print(f"    {COLOR_RED}✗ Failed: {error}{COLOR_RESET}")
            results[region]['describe_images'] = None
        
        # Test Method 2: SSM Parameter Store
        print("  Method 2: SSM Parameter Store")
        start_time = time.time()
        ami_info, error = get_latest_ubuntu_ami_ssm(region)
        duration = time.time() - start_time
        
        if ami_info:
            print(f"    {COLOR_GREEN}✓ Success ({duration:.2f}s){COLOR_RESET}")
            print(f"    AMI ID: {ami_info['ami_id']}")
            if 'name' in ami_info:
                print(f"    Name: {ami_info['name']}")
                print(f"    Created: {ami_info['creation_date']}")
            results[region]['ssm'] = ami_info
        else:
            print(f"    {COLOR_RED}✗ Failed: {error}{COLOR_RESET}")
            results[region]['ssm'] = None
    
    # Summary
    print(f"\n{COLOR_BLUE}📊 Summary{COLOR_RESET}")
    print("=" * 60)
    
    for region in TEST_REGIONS:
        print(f"\n{COLOR_YELLOW}{region}:{COLOR_RESET}")
        
        describe_ami = results[region].get('describe_images')
        ssm_ami = results[region].get('ssm')
        
        if describe_ami and ssm_ami:
            if describe_ami['ami_id'] == ssm_ami['ami_id']:
                print(f"  {COLOR_GREEN}✓ Both methods returned same AMI: {describe_ami['ami_id']}{COLOR_RESET}")
            else:
                print(f"  {COLOR_YELLOW}⚠ Different AMIs:{COLOR_RESET}")
                print(f"    describe_images: {describe_ami['ami_id']}")
                print(f"    ssm: {ssm_ami['ami_id']}")
        elif describe_ami:
            print(f"  {COLOR_GREEN}✓ describe_images: {describe_ami['ami_id']}{COLOR_RESET}")
            print(f"  {COLOR_RED}✗ ssm: failed{COLOR_RESET}")
        elif ssm_ami:
            print(f"  {COLOR_RED}✗ describe_images: failed{COLOR_RESET}")
            print(f"  {COLOR_GREEN}✓ ssm: {ssm_ami['ami_id']}{COLOR_RESET}")
        else:
            print(f"  {COLOR_RED}✗ Both methods failed{COLOR_RESET}")
    
    return results

def test_specific_region(region='us-east-1'):
    """Test a specific region in detail"""
    print(f"\n{COLOR_BLUE}🔬 Detailed Test for {region}{COLOR_RESET}")
    print("=" * 40)
    
    ami_info, error = get_latest_ubuntu_ami_describe(region)
    if ami_info:
        print(f"{COLOR_GREEN}Success!{COLOR_RESET}")
        print(f"AMI ID: {ami_info['ami_id']}")
        print(f"Name: {ami_info['name']}")
        print(f"Creation Date: {ami_info['creation_date']}")
        print(f"Description: {ami_info['description']}")
        
        # Test that we can actually use this AMI
        try:
            ec2_client = boto3.client('ec2', region_name=region)
            # Just describe the AMI to make sure it's accessible
            response = ec2_client.describe_images(ImageIds=[ami_info['ami_id']])
            if response['Images']:
                print(f"{COLOR_GREEN}✓ AMI is accessible and valid{COLOR_RESET}")
            else:
                print(f"{COLOR_RED}✗ AMI not accessible{COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_RED}✗ Error accessing AMI: {e}{COLOR_RESET}")
    else:
        print(f"{COLOR_RED}Failed: {error}{COLOR_RESET}")

if __name__ == "__main__":
    print(f"{COLOR_BLUE}🚀 AMI Lookup Test Script{COLOR_RESET}")
    print(f"Testing programmatic AMI lookup for Ubuntu 22.04")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Test all regions
        results = test_ami_lookup()
        
        # Detailed test for us-east-1
        test_specific_region('us-east-1')
        
        print(f"\n{COLOR_GREEN}🎉 Test completed successfully!{COLOR_RESET}")
        print(f"{COLOR_BLUE}💡 Recommendation: Use describe_images method for more control{COLOR_RESET}")
        
    except Exception as e:
        print(f"\n{COLOR_RED}💥 Test failed with error: {e}{COLOR_RESET}")
        import traceback
        traceback.print_exc()
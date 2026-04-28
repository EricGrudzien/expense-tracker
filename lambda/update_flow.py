"""
Update and prepare a Bedrock Flow from a local JSON export.

Usage:
    # Update and prepare the flow
    python update_flow.py

    # Update only (skip prepare)
    python update_flow.py --no-prepare

    # Use a different export file
    python update_flow.py --file my-flow.json

    # Target a different flow
    python update_flow.py --flow-id ABCDEFGHIJ

    # Dry run — show what would be sent without calling the API
    python update_flow.py --dry-run
"""

import argparse
import boto3
import json
import os
import sys
import time


DEFAULT_EXPORT_FILE = os.path.join(os.path.dirname(__file__), "flow-export.json")
DEFAULT_FLOW_ID = "FNO4NHO5DT"
DEFAULT_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")


def load_export(filepath):
    """Load and validate the flow export JSON."""
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    with open(filepath) as f:
        export = json.load(f)

    # Validate required fields
    if "definition" not in export:
        print("Error: Export file missing 'definition' key")
        sys.exit(1)
    if "name" not in export:
        print("Error: Export file missing 'name' key")
        sys.exit(1)
    if "executionRoleArn" not in export:
        print("Error: Export file missing 'executionRoleArn' key")
        sys.exit(1)

    nodes = export["definition"].get("nodes", [])
    connections = export["definition"].get("connections", [])
    print(f"Loaded: {filepath}")
    print(f"  Flow name:   {export['name']}")
    print(f"  Nodes:       {len(nodes)}")
    print(f"  Connections: {len(connections)}")
    print(f"  Role:        {export['executionRoleArn']}")
    print()

    return export


def update_flow(client, flow_id, export, dry_run=False):
    """Push the flow definition to Bedrock."""
    if dry_run:
        print("[DRY RUN] Would call update_flow with:")
        print(f"  flowIdentifier:   {flow_id}")
        print(f"  name:             {export['name']}")
        print(f"  executionRoleArn: {export['executionRoleArn']}")
        print(f"  definition:       ({len(json.dumps(export['definition']))} bytes)")
        return None

    print(f"Updating flow {flow_id}...")
    response = client.update_flow(
        flowIdentifier=flow_id,
        name=export["name"],
        executionRoleArn=export["executionRoleArn"],
        definition=export["definition"],
    )
    status = response.get("status", "UNKNOWN")
    print(f"  Status: {status}")
    return response


def prepare_flow(client, flow_id, dry_run=False):
    """Prepare the flow so it can be invoked."""
    if dry_run:
        print("[DRY RUN] Would call prepare_flow")
        return None

    print(f"Preparing flow {flow_id}...")
    client.prepare_flow(flowIdentifier=flow_id)

    # Poll until prepared (or timeout after 60s)
    for i in range(30):
        time.sleep(2)
        flow = client.get_flow(flowIdentifier=flow_id)
        status = flow.get("status", "UNKNOWN")
        if status == "Prepared":
            print(f"  Status: {status} ✓")
            return flow
        elif status == "Failed":
            print(f"  Status: {status} ✗")
            print(f"  Error:  {flow.get('statusReasons', 'Unknown error')}")
            sys.exit(1)
        else:
            print(f"  Status: {status} (waiting...)")

    print("  Timed out waiting for flow to prepare")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Update a Bedrock Flow from a local JSON export")
    parser.add_argument("--file", default=DEFAULT_EXPORT_FILE, help="Path to flow export JSON")
    parser.add_argument("--flow-id", default=DEFAULT_FLOW_ID, help="Bedrock Flow identifier")
    parser.add_argument("--region", default=DEFAULT_REGION, help="AWS region")
    parser.add_argument("--no-prepare", action="store_true", help="Skip the prepare step")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without calling APIs")
    args = parser.parse_args()

    export = load_export(args.file)

    client = boto3.client("bedrock-agent", region_name=args.region)

    update_flow(client, args.flow_id, export, dry_run=args.dry_run)

    if not args.no_prepare:
        print()
        prepare_flow(client, args.flow_id, dry_run=args.dry_run)

    print()
    print("Done.")


if __name__ == "__main__":
    main()

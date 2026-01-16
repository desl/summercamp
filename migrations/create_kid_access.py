"""
Migration script to create KidAccess records for existing kids.

This migration ensures backwards compatibility by creating 'owner' KidAccess
records for all existing kids based on their user_email field.

Run with: python -m migrations.create_kid_access --project=PROJECT_ID

Why this migration exists:
Before multi-parent support, kid ownership was determined by the user_email
field on the Kid entity. Now it's determined by KidAccess records. This
migration creates the necessary KidAccess records so existing users continue
to see their kids.
"""

import argparse
import sys
from google.cloud import datastore
from datetime import datetime, timezone
import uuid


def get_kid_access(client, kid_id, user_email):
    """Check if a KidAccess record already exists."""
    query = client.query(kind='KidAccess')
    query.add_filter('kid_id', '=', kid_id)
    query.add_filter('user_email', '=', user_email)
    results = list(query.fetch(limit=1))
    return results[0] if results else None


def create_kid_access(client, kid_id, user_email, role, granted_by):
    """Create a KidAccess record."""
    entity_id = str(uuid.uuid4())
    key = client.key('KidAccess', entity_id)
    entity = datastore.Entity(key=key)

    now = datetime.now(timezone.utc)
    entity['kid_id'] = kid_id
    entity['user_email'] = user_email
    entity['role'] = role
    entity['granted_by'] = granted_by
    entity['created_at'] = now
    entity['updated_at'] = now

    client.put(entity)
    return entity


def migrate_kid_access(project_id, dry_run=False):
    """Create KidAccess records for all existing kids."""
    client = datastore.Client(project=project_id)

    # Get all existing kids
    query = client.query(kind='Kid')
    kids = list(query.fetch())

    print(f"Found {len(kids)} kids to process")

    created = 0
    skipped = 0

    for kid in kids:
        kid_id = kid.key.name
        owner_email = kid.get('user_email')

        if not owner_email:
            print(f"  WARNING: Kid {kid_id} has no user_email, skipping")
            skipped += 1
            continue

        # Check if KidAccess already exists
        existing = get_kid_access(client, kid_id, owner_email)
        if existing:
            print(f"  SKIP: Kid {kid_id} already has access record for {owner_email}")
            skipped += 1
            continue

        if dry_run:
            print(f"  DRY RUN: Would create owner access for {kid_id} -> {owner_email}")
            created += 1
        else:
            # Create owner KidAccess record
            create_kid_access(
                client,
                kid_id=kid_id,
                user_email=owner_email,
                role='owner',
                granted_by=owner_email  # Self-granted for migration
            )
            print(f"  CREATED: Owner access for {kid_id} -> {owner_email}")
            created += 1

    print(f"\nMigration complete: {created} created, {skipped} skipped")
    return created, skipped


def verify_migration(project_id):
    """Verify all kids have corresponding KidAccess records."""
    client = datastore.Client(project=project_id)

    kids = list(client.query(kind='Kid').fetch())
    access_records = list(client.query(kind='KidAccess').fetch())

    print(f"Found {len(kids)} kids and {len(access_records)} access records")

    # Build lookup of kid_id -> access records
    access_by_kid = {}
    for record in access_records:
        kid_id = record['kid_id']
        if kid_id not in access_by_kid:
            access_by_kid[kid_id] = []
        access_by_kid[kid_id].append(record)

    # Check each kid has at least one owner access record
    missing = []
    for kid in kids:
        kid_id = kid.key.name
        records = access_by_kid.get(kid_id, [])
        owners = [r for r in records if r.get('role') == 'owner']
        if not owners:
            missing.append((kid_id, kid.get('user_email', 'unknown')))

    if missing:
        print(f"\nERROR: {len(missing)} kids missing owner access:")
        for kid_id, email in missing:
            print(f"  - {kid_id} (owner: {email})")
        return False
    else:
        print(f"\nSUCCESS: All {len(kids)} kids have owner access records")
        return True


def main():
    parser = argparse.ArgumentParser(description='Migrate Kid entities to KidAccess')
    parser.add_argument('--project', required=True, help='GCP project ID')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--verify', action='store_true', help='Verify migration instead of running it')

    args = parser.parse_args()

    if args.verify:
        success = verify_migration(args.project)
        sys.exit(0 if success else 1)
    else:
        migrate_kid_access(args.project, dry_run=args.dry_run)


if __name__ == '__main__':
    main()

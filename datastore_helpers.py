"""
Helper functions for Cloud Datastore operations.

This module provides common patterns for working with Datastore entities:
- Creating entities with timestamps and user ownership
- Querying entities by user_email
- Converting entities to dictionaries
- Validating entity ownership

Why these helpers exist:
Every entity in our system needs user_email filtering (for security),
UTC timestamps (for audit trails), and ownership validation (to prevent
unauthorized access). Centralizing these patterns makes the code more
maintainable and helps beginning engineers learn the correct approach.
"""

from google.cloud import datastore
from datetime import datetime, timezone
import uuid


def get_datastore_client(project_id):
    """
    Create and return a Cloud Datastore client.

    Args:
        project_id: GCP project ID

    Returns:
        datastore.Client instance

    Why: Centralized client creation ensures consistent configuration.
    """
    return datastore.Client(project=project_id)


def create_entity(client, kind, user_email, properties):
    """
    Create a new Datastore entity with automatic timestamps and UUID key.

    Args:
        client: datastore.Client instance
        kind: Entity kind (e.g., 'Kid', 'Camp', 'Session')
        user_email: Email of the authenticated user (for ownership)
        properties: Dictionary of entity properties

    Returns:
        The created entity with key, timestamps, and user_email

    Why: Every entity needs:
    - UUID key (simple, secure, no collisions)
    - user_email (isolate data by user)
    - created_at and updated_at (audit trail)
    This function ensures we never forget these critical properties.
    """
    # Generate a unique ID for this entity
    entity_id = str(uuid.uuid4())

    # Create the Datastore key
    key = client.key(kind, entity_id)

    # Create the entity
    entity = datastore.Entity(key=key)

    # Add user ownership (critical for security)
    entity['user_email'] = user_email

    # Add timestamps (UTC timezone-aware for Datastore compatibility)
    now = datetime.now(timezone.utc)
    entity['created_at'] = now
    entity['updated_at'] = now

    # Add all the custom properties
    entity.update(properties)

    # Save to Datastore
    client.put(entity)

    return entity


def get_entity_for_user(client, kind, entity_id, user_email):
    """
    Get an entity by ID and verify it belongs to the authenticated user.

    Args:
        client: datastore.Client instance
        kind: Entity kind (e.g., 'Kid', 'Camp')
        entity_id: The entity's UUID
        user_email: Email of the authenticated user

    Returns:
        The entity if found and owned by user, otherwise None

    Why: This prevents users from accessing other users' data. Every
    GET/PUT/DELETE operation must verify ownership to maintain security.
    """
    key = client.key(kind, entity_id)
    entity = client.get(key)

    # Check if entity exists and belongs to this user
    if entity and entity.get('user_email') == user_email:
        return entity

    return None


def update_entity(client, entity, properties):
    """
    Update an existing entity with new properties and refresh updated_at.

    Args:
        client: datastore.Client instance
        entity: The entity to update
        properties: Dictionary of properties to update

    Returns:
        The updated entity

    Why: Always update the updated_at timestamp when modifying entities.
    This helps track when data changed and makes debugging easier.
    """
    # Update the timestamp
    entity['updated_at'] = datetime.now(timezone.utc)

    # Update the properties
    entity.update(properties)

    # Save to Datastore
    client.put(entity)

    return entity


def delete_entity(client, entity):
    """
    Delete an entity from Datastore.

    Args:
        client: datastore.Client instance
        entity: The entity to delete

    Why: Centralized delete function for consistency and potential
    future enhancements (e.g., soft deletes, audit logging).
    """
    client.delete(entity.key)


def query_by_user(client, kind, user_email, order_by=None, filters=None):
    """
    Query entities of a specific kind for a specific user.

    Args:
        client: datastore.Client instance
        kind: Entity kind to query
        user_email: Email of the authenticated user
        order_by: Optional field name to sort by (e.g., 'created_at')
        filters: Optional list of (property, operator, value) tuples

    Returns:
        List of entities owned by the user

    Why: All queries must filter by user_email for security. This helper
    ensures we never accidentally return another user's data.

    Example:
        kids = query_by_user(client, 'Kid', user_email, order_by='name')

        # With additional filters
        booked = query_by_user(
            client,
            'Booking',
            user_email,
            filters=[('state', '=', 'booked')]
        )
    """
    query = client.query(kind=kind)

    # Always filter by user_email (critical for security)
    query.add_filter('user_email', '=', user_email)

    # Add any additional filters
    if filters:
        for prop, operator, value in filters:
            query.add_filter(prop, operator, value)

    # Add ordering if specified
    if order_by:
        query.order = [order_by]

    # Execute query and return results
    return list(query.fetch())


def entity_to_dict(entity):
    """
    Convert a Datastore entity to a dictionary.

    Args:
        entity: Datastore entity

    Returns:
        Dictionary with entity data plus 'id' field

    Why: Templates and JSON responses need dictionaries, not Entity objects.
    This helper converts entities to a format that's easy to work with.
    The 'id' field is added from entity.key.name for convenience.
    """
    if not entity:
        return None

    # Start with all entity properties
    result = dict(entity)

    # Add the entity ID (from the key)
    result['id'] = entity.key.name

    # Convert datetime objects to strings for template/form compatibility
    for key, value in result.items():
        if isinstance(value, datetime):
            # For date fields (no time component), format as YYYY-MM-DD for HTML date inputs
            # For datetime fields with time, use ISO format
            if value.hour == 0 and value.minute == 0 and value.second == 0:
                result[key] = value.strftime('%Y-%m-%d')
            else:
                result[key] = value.isoformat()

    return result


def entities_to_dict_list(entities):
    """
    Convert a list of Datastore entities to a list of dictionaries.

    Args:
        entities: List of Datastore entities

    Returns:
        List of dictionaries

    Why: Convenience function for converting query results to JSON-friendly
    format in one step.
    """
    return [entity_to_dict(entity) for entity in entities]


# ============================================================================
# SHARE TOKEN FUNCTIONS
# ============================================================================

def create_share_token(client, user_email):
    """
    Create a share token for sharing a user's schedule publicly.

    Args:
        client: datastore.Client instance
        user_email: Email of the user creating the share

    Returns:
        The generated token string (UUID)

    Why: Uses the token as the entity key for efficient direct lookup
    without needing a query. This is important for public access where
    we don't know the user_email upfront.
    """
    token = str(uuid.uuid4())
    key = client.key('ShareToken', token)
    entity = datastore.Entity(key=key)
    entity['user_email'] = user_email
    entity['created_at'] = datetime.now(timezone.utc)
    entity['updated_at'] = datetime.now(timezone.utc)
    client.put(entity)
    return token


def get_share_token(client, token):
    """
    Get a share token entity by its token value.

    Args:
        client: datastore.Client instance
        token: The token string (UUID)

    Returns:
        The ShareToken entity if found, None otherwise

    Why: This is used for public access - we look up by token without
    knowing the user_email. No ownership check needed since the token
    itself is the authorization.
    """
    key = client.key('ShareToken', token)
    return client.get(key)


def get_share_token_for_user(client, user_email):
    """
    Get the share token for a specific user (if one exists).

    Args:
        client: datastore.Client instance
        user_email: Email of the user

    Returns:
        The token string if found, None otherwise

    Why: Used to check if a user already has a share link before creating
    a new one, and to display the existing share URL.
    """
    query = client.query(kind='ShareToken')
    query.add_filter('user_email', '=', user_email)
    tokens = list(query.fetch(limit=1))
    if tokens:
        return tokens[0].key.name  # The token is stored as the key name
    return None


def delete_share_token_for_user(client, user_email):
    """
    Delete all share tokens for a user.

    Args:
        client: datastore.Client instance
        user_email: Email of the user

    Returns:
        Number of tokens deleted

    Why: When a user wants to revoke their share link, we delete all
    their tokens. This invalidates any shared URLs immediately.
    """
    query = client.query(kind='ShareToken')
    query.add_filter('user_email', '=', user_email)
    tokens = list(query.fetch())
    for token in tokens:
        client.delete(token.key)
    return len(tokens)

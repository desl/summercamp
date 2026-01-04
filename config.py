"""
Configuration settings for the Summer Camp Organization Tool.

This module contains all configuration settings for the application,
including OAuth credentials, session configuration, and allowed users.

Environment variables are used for sensitive data like OAuth secrets.
"""

import os


class Config:
    """
    Application configuration class.

    Settings are loaded from environment variables with sensible defaults
    for development. Production should always use environment variables.
    """

    # Flask secret key for session encryption
    # This is used to sign session cookies and should be a random string
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # Google OAuth 2.0 credentials
    # These are obtained from the GCP Console (APIs & Services > Credentials)
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

    # OAuth scopes define what information we request from Google
    # - openid: Basic OpenID Connect authentication
    # - userinfo.email: User's email address
    # - userinfo.profile: User's basic profile info (name, picture)
    GOOGLE_OAUTH_SCOPES = [
        'openid',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/userinfo.profile'
    ]

    # Email allowlist - only these users can access the application
    # In production, this should be set via ALLOWED_EMAILS environment variable
    # Format: comma-separated list (e.g., "user1@gmail.com,user2@gmail.com")
    ALLOWED_EMAILS = os.environ.get('ALLOWED_EMAILS', '').split(',') if os.environ.get('ALLOWED_EMAILS') else [
        'safarileader@gmail.com',  # Default allowed user for development
    ]

    # Session configuration
    # Sessions are stored server-side in Cloud Datastore for security and scalability
    SESSION_TYPE = 'datastore'  # Use custom Datastore backend
    SESSION_PERMANENT = True  # Sessions persist beyond browser close
    PERMANENT_SESSION_LIFETIME = 86400  # Session lifetime: 24 hours in seconds

    # GCP Project ID (used for Datastore client)
    GCP_PROJECT_ID = os.environ.get('GOOGLE_CLOUD_PROJECT') or 'summercamp-dev-202601'

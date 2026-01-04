"""
Authentication module using Google OAuth 2.0.

This module handles the OAuth flow for user authentication:
- Login: Redirect to Google for authentication
- Callback: Handle Google's response and create session
- Logout: Clear session
- Authorization: Check if user's email is in allowlist

Only users whose email addresses are in the ALLOWED_EMAILS configuration
can access the application.
"""

from functools import wraps
from flask import Blueprint, redirect, request, session, url_for, render_template, current_app
from google_auth_oauthlib.flow import Flow
from google.auth.transport import requests as google_requests
import os


# Create Blueprint for auth routes
# Blueprints organize related routes into modules
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


def create_flow():
    """
    Create and configure a Google OAuth 2.0 flow.

    The flow manages the OAuth authentication process with Google.
    It's created fresh for each auth request to ensure proper state management.

    Returns:
        Flow: Configured OAuth flow object
    """
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": current_app.config['GOOGLE_CLIENT_ID'],
                "client_secret": current_app.config['GOOGLE_CLIENT_SECRET'],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [url_for('auth.callback', _external=True)]
            }
        },
        scopes=current_app.config['GOOGLE_OAUTH_SCOPES']
    )

    # Set the redirect URI to the callback route
    flow.redirect_uri = url_for('auth.callback', _external=True)

    return flow


def login_required(f):
    """
    Decorator to protect routes that require authentication.

    Apply this decorator to any route that should only be accessible
    to logged-in users. If the user is not logged in, they will be
    redirected to the login page.

    Usage:
        @app.route('/dashboard')
        @login_required
        def dashboard():
            return render_template('dashboard.html')

    Args:
        f: The route function to protect

    Returns:
        Decorated function that checks for authentication
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            # User not logged in - redirect to login page
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """
    Get the currently logged-in user's information from the session.

    Returns:
        dict: User information (email, name, picture) or None if not logged in
    """
    return session.get('user')


@auth_bp.route('/login-page')
def login_page():
    """
    Display the login page with "Sign in with Google" button.

    This is the landing page for unauthenticated users.
    """
    return render_template('login.html')


@auth_bp.route('/login')
def login():
    """
    Initiate the Google OAuth authentication flow.

    This route redirects the user to Google's consent screen where they
    will authenticate and grant permissions. After authentication, Google
    redirects back to the callback route.
    """
    flow = create_flow()

    # Generate authorization URL and redirect user to Google
    authorization_url, state = flow.authorization_url(
        access_type='offline',  # Request refresh token
        include_granted_scopes='true'  # Incremental authorization
    )

    # Store state in session to verify callback authenticity (CSRF protection)
    session['oauth_state'] = state

    return redirect(authorization_url)


@auth_bp.route('/callback')
def callback():
    """
    Handle the OAuth callback from Google.

    Google redirects here after the user authenticates. This route:
    1. Exchanges the authorization code for tokens
    2. Fetches user information from Google
    3. Checks if user's email is in the allowlist
    4. Creates a session for authorized users
    5. Shows error page for unauthorized users

    Returns:
        Redirect to dashboard (authorized) or unauthorized page (not authorized)
    """
    # Verify state to prevent CSRF attacks
    state = session.get('oauth_state')
    if not state:
        return "Invalid state parameter", 400

    # Create flow with the same state
    flow = create_flow()
    flow.fetch_token(authorization_response=request.url)

    # Get credentials from the flow
    credentials = flow.credentials

    # Fetch user info from Google
    # We use the credentials to call Google's userinfo API
    id_info_request = google_requests.Request()
    from google.oauth2 import id_token

    try:
        # Verify and decode the ID token to get user information
        id_info = id_token.verify_oauth2_token(
            credentials.id_token,
            id_info_request,
            current_app.config['GOOGLE_CLIENT_ID']
        )

        # Extract user information
        user_email = id_info.get('email')
        user_name = id_info.get('name')
        user_picture = id_info.get('picture')

        # Check if user's email is in the allowlist
        allowed_emails = current_app.config['ALLOWED_EMAILS']
        if user_email not in allowed_emails:
            # User not authorized - show error page
            return render_template('unauthorized.html', email=user_email)

        # User is authorized - create session
        session['user'] = {
            'email': user_email,
            'name': user_name,
            'picture': user_picture
        }

        # Clear the oauth_state from session (no longer needed)
        session.pop('oauth_state', None)

        # Redirect to home page / dashboard
        return redirect(url_for('index'))

    except ValueError as e:
        # Invalid token
        return f"Invalid token: {str(e)}", 400


@auth_bp.route('/logout')
def logout():
    """
    Log out the current user by clearing their session.

    This removes all user data from the session and redirects to the login page.
    """
    session.clear()
    return redirect(url_for('auth.login_page'))

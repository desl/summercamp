"""
Summer Camp Organization Tool - Main Flask Application

This is the entry point for the Flask web application with Google OAuth authentication.
Users must authenticate with their Google account and be in the email allowlist to access.
"""

from flask import Flask, render_template
from config import Config
from session_datastore import DatastoreSessionInterface
from auth import auth_bp, login_required, get_current_user
from family import family_bp
from camps import camps_bp
from schedule import schedule_bp
from datetime import datetime
import os

# Disable HTTPS requirement for OAuth flow in development
# This is needed because google-auth-oauthlib requires HTTPS by default
# App Engine provides HTTPS in production, but for local testing we need this
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Create the Flask application instance
app = Flask(__name__)

# Load configuration from config.py
# This includes OAuth settings, session config, and email allowlist
app.config.from_object(Config)

# Initialize custom Datastore session backend
# This replaces Flask's default cookie-based sessions with server-side sessions
# stored in Cloud Datastore for better security and scalability
app.session_interface = DatastoreSessionInterface(app.config['GCP_PROJECT_ID'])

# Register authentication blueprint
# This adds all the auth routes (/auth/login, /auth/callback, /auth/logout)
app.register_blueprint(auth_bp)

# Register family management blueprint
# This adds routes for managing parents, kids, and trips (/family/*)
app.register_blueprint(family_bp)

# Register camps management blueprint
# This adds routes for managing camps and sessions (/camps/*)
app.register_blueprint(camps_bp)

# Register schedule blueprint
# This adds routes for managing weeks and bookings (/schedule/*)
app.register_blueprint(schedule_bp)


# Add custom Jinja2 template filter for formatting dates
@app.template_filter('format_date_short')
def format_date_short(date_value):
    """
    Format a date as MM/DD instead of YYYY-MM-DD.

    Used in schedule and week views for a cleaner, more compact display.
    """
    if isinstance(date_value, datetime):
        return date_value.strftime('%m/%d')
    elif isinstance(date_value, str):
        # Handle string dates (YYYY-MM-DD format)
        try:
            dt = datetime.strptime(date_value, '%Y-%m-%d')
            return dt.strftime('%m/%d')
        except ValueError:
            return date_value
    return str(date_value)


@app.route('/')
@login_required
def index():
    """
    Home page / dashboard route.

    Protected by @login_required - only authenticated users can access.
    Shows the summer camp planning dashboard with user information.
    """
    user = get_current_user()
    return render_template('index.html', user=user)


@app.route('/health')
def health():
    """
    Health check endpoint.

    Unprotected route used by App Engine and monitoring tools to verify
    the app is running. Does not require authentication.
    """
    return {'status': 'healthy', 'environment': 'dev'}, 200


# This block only runs when testing locally (not needed for App Engine)
# App Engine uses gunicorn to run the app, not this dev server
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)

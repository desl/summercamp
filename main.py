"""
Summer Camp Organization Tool - Main Flask Application

This is the entry point for the Flask web application.
For now, this is a simple "Hello World" to verify deployment works.
"""

from flask import Flask, render_template

# Create the Flask application instance
# __name__ helps Flask locate templates and static files
app = Flask(__name__)


@app.route('/')
def index():
    """
    Home page route.

    Currently displays a simple welcome message to verify deployment.
    In future iterations, this will show the summer camp planning dashboard.
    """
    return render_template('index.html')


@app.route('/health')
def health():
    """
    Health check endpoint.

    Used by App Engine and monitoring tools to verify the app is running.
    Returns a simple JSON response indicating the app is healthy.
    """
    return {'status': 'healthy', 'environment': 'dev'}, 200


# This block only runs when testing locally (not needed for App Engine)
# App Engine uses gunicorn to run the app, not this dev server
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)

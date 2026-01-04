"""
Custom Flask session backend using Google Cloud Datastore.

Flask-Session doesn't have built-in Datastore support, so we implement
a custom session interface that stores session data in Cloud Datastore.

This is ideal for App Engine as Datastore is serverless and scales automatically.
"""

import pickle
from datetime import datetime, timedelta, timezone
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict
from google.cloud import datastore
import uuid


class DatastoreSession(CallbackDict, SessionMixin):
    """
    Session object that uses Cloud Datastore for storage.

    This extends Flask's default session implementation to work with Datastore.
    """

    def __init__(self, initial=None, sid=None, permanent=None):
        def on_update(self):
            self.modified = True

        CallbackDict.__init__(self, initial, on_update)
        self.sid = sid
        self.permanent = permanent
        self.modified = False


class DatastoreSessionInterface(SessionInterface):
    """
    Flask session interface implementation for Cloud Datastore.

    Sessions are stored as Datastore entities with the following structure:
    - Kind: 'Session'
    - Key: session ID
    - Properties: data (pickled session dict), expires (datetime)
    """

    def __init__(self, project_id):
        """
        Initialize the Datastore session interface.

        Args:
            project_id: GCP project ID for Datastore client
        """
        self.client = datastore.Client(project=project_id)

    def _get_session_key(self, sid):
        """
        Create a Datastore key for a session ID.

        Args:
            sid: Session ID string

        Returns:
            Datastore key for the session
        """
        return self.client.key('Session', sid)

    def open_session(self, app, request):
        """
        Load session data from Datastore when a request starts.

        This is called by Flask at the beginning of each request.

        Args:
            app: Flask application instance
            request: Flask request object

        Returns:
            DatastoreSession object with session data
        """
        sid = request.cookies.get(app.config['SESSION_COOKIE_NAME'])

        if not sid:
            # No session cookie - create a new session
            sid = str(uuid.uuid4())
            return DatastoreSession(sid=sid, permanent=True)

        # Try to load existing session from Datastore
        key = self._get_session_key(sid)
        entity = self.client.get(key)

        if entity is None:
            # Session not found in Datastore - create new session
            return DatastoreSession(sid=sid, permanent=True)

        # Check if session has expired
        if 'expires' in entity and entity['expires'] < datetime.now(timezone.utc):
            # Session expired - delete it and create new session
            self.client.delete(key)
            return DatastoreSession(sid=sid, permanent=True)

        # Load session data from Datastore
        try:
            data = pickle.loads(entity['data'])
            return DatastoreSession(data, sid=sid, permanent=True)
        except Exception:
            # If we can't unpickle the data, start with a fresh session
            return DatastoreSession(sid=sid, permanent=True)

    def save_session(self, app, session, response):
        """
        Save session data to Datastore when a request ends.

        This is called by Flask at the end of each request.

        Args:
            app: Flask application instance
            session: Session object to save
            response: Flask response object
        """
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)

        # If session is empty and not modified, delete it
        if not session:
            if session.modified:
                self.client.delete(self._get_session_key(session.sid))
                response.delete_cookie(
                    app.config['SESSION_COOKIE_NAME'],
                    domain=domain,
                    path=path
                )
            return

        # Calculate session expiration time
        if session.permanent:
            lifetime = app.config['PERMANENT_SESSION_LIFETIME']
            expires = datetime.now(timezone.utc) + timedelta(seconds=lifetime)
        else:
            expires = datetime.now(timezone.utc) + timedelta(days=1)

        # Save session to Datastore
        key = self._get_session_key(session.sid)
        entity = datastore.Entity(key=key)
        entity.update({
            'data': pickle.dumps(dict(session)),
            'expires': expires
        })
        self.client.put(entity)

        # Set session cookie
        httponly = self.get_cookie_httponly(app)
        secure = self.get_cookie_secure(app)
        samesite = self.get_cookie_samesite(app)

        response.set_cookie(
            app.config['SESSION_COOKIE_NAME'],
            session.sid,
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
            samesite=samesite
        )

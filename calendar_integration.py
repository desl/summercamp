"""
Google Calendar Integration for Summer Camp Bookings.

This module provides functions to create, update, and delete calendar events
for booked summer camps and registration reminders.
"""

from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from dateutil import parser


def get_calendar_service(session_credentials):
    """
    Create a Google Calendar API service instance from session credentials.

    Args:
        session_credentials: OAuth credentials from session['credentials']

    Returns:
        Google Calendar API service object
    """
    credentials = Credentials(
        token=session_credentials['token'],
        refresh_token=session_credentials.get('refresh_token'),
        token_uri=session_credentials.get('token_uri'),
        client_id=session_credentials.get('client_id'),
        client_secret=session_credentials.get('client_secret'),
        scopes=session_credentials.get('scopes')
    )

    return build('calendar', 'v3', credentials=credentials)


def create_booking_event(session_credentials, parent, kid, camp, session, week):
    """
    Create a calendar event for a booked summer camp.

    The event is created on the parent's primary calendar and spans the week
    with all-day timing. It includes camp details, session info, and care times.

    Args:
        session_credentials: OAuth credentials from session['credentials']
        parent: Parent entity dict with name and email
        kid: Kid entity dict with name
        camp: Camp entity dict with name, phone, website
        session: Session entity dict with name, times, costs
        week: Week entity dict with start_date and end_date

    Returns:
        str: The created event's ID, or None if creation failed
    """
    try:
        service = get_calendar_service(session_credentials)

        # Parse dates
        start_date = week['start_date'] if isinstance(week['start_date'], datetime) else parser.parse(week['start_date'])
        end_date = week['end_date'] if isinstance(week['end_date'], datetime) else parser.parse(week['end_date'])

        # End date for calendar event is exclusive (next day after end_date)
        event_end_date = end_date + timedelta(days=1)

        # Build event description with session details
        description_parts = [
            f"Camp: {camp['name']}",
            f"Session: {session['name']}",
            f"Kid: {kid['name']}"
        ]

        if session.get('start_time') and session.get('end_time'):
            description_parts.append(f"Time: {session['start_time']} - {session['end_time']}")

        if session.get('dropoff_window_start') and session.get('dropoff_window_end'):
            description_parts.append(f"Drop-off: {session['dropoff_window_start']} - {session['dropoff_window_end']}")

        if session.get('pickup_window_start') and session.get('pickup_window_end'):
            description_parts.append(f"Pick-up: {session['pickup_window_start']} - {session['pickup_window_end']}")

        if session.get('cost'):
            description_parts.append(f"Cost: ${session['cost']:.2f}")

        if camp.get('phone'):
            description_parts.append(f"Phone: {camp['phone']}")

        if camp.get('website'):
            description_parts.append(f"Website: {camp['website']}")

        if session.get('url'):
            description_parts.append(f"Session Info: {session['url']}")

        description = "\n".join(description_parts)

        # Create event
        event = {
            'summary': f"{kid['name']} - {camp['name']}",
            'description': description,
            'start': {
                'date': start_date.strftime('%Y-%m-%d'),
                'timeZone': 'America/Los_Angeles',
            },
            'end': {
                'date': event_end_date.strftime('%Y-%m-%d'),
                'timeZone': 'America/Los_Angeles',
            },
            'colorId': '10',  # Green color for booked camps
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 24 * 60},  # 1 day before
                    {'method': 'popup', 'minutes': 7 * 24 * 60},  # 1 week before
                ],
            },
        }

        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return created_event['id']

    except Exception as e:
        print(f"Error creating calendar event: {e}")
        return None


def create_registration_reminder(session_credentials, parent, camp, session):
    """
    Create a calendar reminder for a camp registration opening date.

    Creates an all-day event on the registration opening date to remind
    the parent to register.

    Args:
        session_credentials: OAuth credentials from session['credentials']
        parent: Parent entity dict with name and email
        camp: Camp entity dict with name
        session: Session entity dict with name and registration_open_date

    Returns:
        str: The created event's ID, or None if creation failed or no registration date
    """
    try:
        if not session.get('registration_open_date'):
            return None

        service = get_calendar_service(session_credentials)

        # Parse registration date
        reg_date = session['registration_open_date']
        if isinstance(reg_date, str):
            reg_date = parser.parse(reg_date)

        # Event end date is next day (all-day events are exclusive)
        event_end_date = reg_date + timedelta(days=1)

        # Build description
        description_parts = [
            f"Camp: {camp['name']}",
            f"Session: {session['name']}",
            "Remember to register!"
        ]

        if session.get('url'):
            description_parts.append(f"Registration URL: {session['url']}")

        if camp.get('website'):
            description_parts.append(f"Camp Website: {camp['website']}")

        if camp.get('phone'):
            description_parts.append(f"Phone: {camp['phone']}")

        description = "\n".join(description_parts)

        # Create event
        event = {
            'summary': f"📝 Register for {camp['name']} - {session['name']}",
            'description': description,
            'start': {
                'date': reg_date.strftime('%Y-%m-%d'),
                'timeZone': 'America/Los_Angeles',
            },
            'end': {
                'date': event_end_date.strftime('%Y-%m-%d'),
                'timeZone': 'America/Los_Angeles',
            },
            'colorId': '11',  # Red color for registration reminders
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 0},  # Morning of
                    {'method': 'popup', 'minutes': 24 * 60},  # Day before
                ],
            },
        }

        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return created_event['id']

    except Exception as e:
        print(f"Error creating registration reminder: {e}")
        return None


def update_booking_event(session_credentials, calendar_event_id, parent, kid, camp, session, week):
    """
    Update an existing calendar event for a booked camp.

    Args:
        session_credentials: OAuth credentials from session['credentials']
        calendar_event_id: The ID of the event to update
        parent: Parent entity dict
        kid: Kid entity dict
        camp: Camp entity dict
        session: Session entity dict
        week: Week entity dict

    Returns:
        bool: True if update succeeded, False otherwise
    """
    try:
        service = get_calendar_service(session_credentials)

        # Get existing event
        event = service.events().get(calendarId='primary', eventId=calendar_event_id).execute()

        # Parse dates
        start_date = week['start_date'] if isinstance(week['start_date'], datetime) else parser.parse(week['start_date'])
        end_date = week['end_date'] if isinstance(week['end_date'], datetime) else parser.parse(week['end_date'])
        event_end_date = end_date + timedelta(days=1)

        # Update event fields
        event['summary'] = f"{kid['name']} - {camp['name']}"
        event['start']['date'] = start_date.strftime('%Y-%m-%d')
        event['end']['date'] = event_end_date.strftime('%Y-%m-%d')

        # Update description
        description_parts = [
            f"Camp: {camp['name']}",
            f"Session: {session['name']}",
            f"Kid: {kid['name']}"
        ]

        if session.get('start_time') and session.get('end_time'):
            description_parts.append(f"Time: {session['start_time']} - {session['end_time']}")

        if session.get('cost'):
            description_parts.append(f"Cost: ${session['cost']:.2f}")

        if camp.get('phone'):
            description_parts.append(f"Phone: {camp['phone']}")

        if camp.get('website'):
            description_parts.append(f"Website: {camp['website']}")

        event['description'] = "\n".join(description_parts)

        # Update the event
        service.events().update(calendarId='primary', eventId=calendar_event_id, body=event).execute()
        return True

    except Exception as e:
        print(f"Error updating calendar event: {e}")
        return False


def delete_booking_event(session_credentials, calendar_event_id):
    """
    Delete a calendar event for a booking.

    Args:
        session_credentials: OAuth credentials from session['credentials']
        calendar_event_id: The ID of the event to delete

    Returns:
        bool: True if deletion succeeded, False otherwise
    """
    try:
        service = get_calendar_service(session_credentials)
        service.events().delete(calendarId='primary', eventId=calendar_event_id).execute()
        return True

    except Exception as e:
        print(f"Error deleting calendar event: {e}")
        return False

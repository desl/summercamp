"""
Camp management blueprint.

Handles CRUD operations for Camps and Sessions.

Routes:
  - GET/POST /camps - list and create camps
  - GET/PUT/DELETE /camps/<id> - view, update, delete camp
  - GET/POST /camps/<camp_id>/sessions - create session for a camp
  - GET/PUT/DELETE /sessions/<id> - view, update, delete session

Why this module exists:
Camps and Sessions are the "what" of the system - they represent the
activities available for booking. Sessions belong to camps, so managing
them together makes sense.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from auth import login_required, get_current_user
from datastore_helpers import (
    get_datastore_client,
    create_entity,
    get_entity_for_user,
    update_entity,
    delete_entity,
    query_by_user,
    entity_to_dict,
    entities_to_dict_list
)
from calendar_integration import delete_booking_event
from datetime import datetime, timedelta
import math
import re
import json
from ai_parser import parse_session_url

# Create the blueprint
camps_bp = Blueprint('camps', __name__, url_prefix='/camps')


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_duration_weeks(start_date, end_date):
    """
    Calculate duration in weeks from start and end dates.

    Weeks are 5 days long for camp purposes. Any number of days is rounded
    up to make weeks an integer.

    Examples:
        - 1-5 days = 1 week
        - 6-10 days = 2 weeks
        - 11-15 days = 3 weeks

    For camps that run Mon-Fri, weekends are excluded from the count.
    A camp starting Thursday and ending Sunday is 4 days = 1 week.
    """
    if not start_date or not end_date:
        return 1

    # Calculate total days between dates (inclusive)
    total_days = (end_date - start_date).days + 1

    # If camp starts Monday (0) and ends Friday (4), it's a Mon-Fri camp
    # In this case, count only weekdays
    start_weekday = start_date.weekday()  # 0=Monday, 6=Sunday
    end_weekday = end_date.weekday()

    if start_weekday == 0 and end_weekday == 4:
        # Mon-Fri camp - count business days only
        business_days = 0
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # Monday to Friday
                business_days += 1
            current += timedelta(days=1)
        total_days = business_days

    # Calculate weeks (5 days = 1 week, round up)
    return math.ceil(total_days / 5)


# ============================================================================
# CAMP ROUTES
# ============================================================================

@camps_bp.route('/')
@login_required
def camps_list():
    """
    List all camps for the current user.

    Why: Shows all camp organizations so user can manage available options.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Query all camps for this user
    camps = query_by_user(client, 'Camp', user['email'], order_by='name')

    # For each camp, get the count of sessions
    camps_with_counts = []
    for camp in camps:
        camp_dict = entity_to_dict(camp)
        # Query sessions for this camp
        sessions = query_by_user(
            client,
            'Session',
            user['email'],
            filters=[('camp_id', '=', camp.key.name)]
        )
        camp_dict['session_count'] = len(sessions)
        camps_with_counts.append(camp_dict)

    return render_template(
        'camps_list.html',
        user=user,
        camps=camps_with_counts
    )


@camps_bp.route('/new', methods=['GET', 'POST'])
@login_required
def camp_new():
    """
    Create a new camp record.

    Why: Users need to add camp organizations before adding sessions.
    """
    user = get_current_user()

    if request.method == 'POST':
        client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

        # Create the camp entity
        camp = create_entity(
            client,
            'Camp',
            user['email'],
            {
                'name': request.form['name'],
                'website': request.form.get('website', ''),
                'phone': request.form.get('phone', ''),
                'email': request.form.get('email', '')
            }
        )

        flash(f"Camp '{request.form['name']}' created successfully!", 'success')
        return redirect(url_for('camps.camps_list'))

    # GET request - show the form
    return render_template('camp_form.html', user=user, camp=None)


@camps_bp.route('/<id>', methods=['GET'])
@login_required
def camp_view(id):
    """
    View and edit a camp record, including its sessions.

    Why: Users need to update camp contact info and manage sessions.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the camp and verify ownership
    camp = get_entity_for_user(client, 'Camp', id, user['email'])

    if not camp:
        flash('Camp not found or access denied.', 'error')
        return redirect(url_for('camps.camps_list'))

    # Get all sessions for this camp
    sessions = query_by_user(
        client,
        'Session',
        user['email'],
        filters=[('camp_id', '=', id)]
    )

    # Convert to dict list and sort by start date (then alphabetically by name)
    sessions_list = entities_to_dict_list(sessions)
    sessions_list.sort(key=lambda s: (
        s.get('session_start_date') if s.get('session_start_date') else datetime.max,
        s.get('name', '').lower()
    ))

    return render_template(
        'camp_form.html',
        user=user,
        camp=entity_to_dict(camp),
        sessions=sessions_list
    )


@camps_bp.route('/<id>/update', methods=['POST'])
@login_required
def camp_update(id):
    """
    Update an existing camp record.

    Why: Contact info changes over time.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the camp and verify ownership
    camp = get_entity_for_user(client, 'Camp', id, user['email'])

    if not camp:
        flash('Camp not found or access denied.', 'error')
        return redirect(url_for('camps.camps_list'))

    # Update the camp
    update_entity(
        client,
        camp,
        {
            'name': request.form['name'],
            'website': request.form.get('website', ''),
            'phone': request.form.get('phone', ''),
            'email': request.form.get('email', '')
        }
    )

    flash(f"Camp '{request.form['name']}' updated successfully!", 'success')
    return redirect(url_for('camps.camp_view', id=id))


@camps_bp.route('/<id>/delete', methods=['POST'])
@login_required
def camp_delete(id):
    """
    Delete a camp record.

    Why: Remove camps that are no longer offering programs.

    Note: This should warn if sessions exist, but that's an enhancement.
    For now, users should delete sessions first.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the camp and verify ownership
    camp = get_entity_for_user(client, 'Camp', id, user['email'])

    if not camp:
        flash('Camp not found or access denied.', 'error')
        return redirect(url_for('camps.camps_list'))

    # Check if camp has sessions
    sessions = query_by_user(
        client,
        'Session',
        user['email'],
        filters=[('camp_id', '=', id)]
    )

    if sessions:
        flash(f"Cannot delete camp '{camp['name']}' because it has {len(sessions)} session(s). Delete sessions first.", 'error')
        return redirect(url_for('camps.camp_view', id=id))

    name = camp['name']
    delete_entity(client, camp)

    flash(f"Camp '{name}' deleted successfully.", 'success')
    return redirect(url_for('camps.camps_list'))


# ============================================================================
# SESSION ROUTES
# ============================================================================

@camps_bp.route('/<camp_id>/sessions/new', methods=['GET', 'POST'])
@login_required
def session_new(camp_id):
    """
    Create a new session for a camp.

    Why: Sessions are the bookable units within a camp.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the camp and verify ownership
    camp = get_entity_for_user(client, 'Camp', camp_id, user['email'])

    if not camp:
        flash('Camp not found or access denied.', 'error')
        return redirect(url_for('camps.camps_list'))

    if request.method == 'POST':
        # Parse optional integer fields
        age_min = int(request.form['age_min']) if request.form.get('age_min') else None
        age_max = int(request.form['age_max']) if request.form.get('age_max') else None
        grade_min = int(request.form['grade_min']) if request.form.get('grade_min') else None
        grade_max = int(request.form['grade_max']) if request.form.get('grade_max') else None
        cost = float(request.form['cost']) if request.form.get('cost') else None
        early_care_cost = float(request.form['early_care_cost']) if request.form.get('early_care_cost') else None
        late_care_cost = float(request.form['late_care_cost']) if request.form.get('late_care_cost') else None

        # Parse registration date
        registration_open_date = None
        if request.form.get('registration_open_date') and request.form.get('registration_open_time'):
            registration_datetime_str = f"{request.form['registration_open_date']} {request.form['registration_open_time']}"
            registration_open_date = datetime.strptime(registration_datetime_str, '%Y-%m-%d %H:%M')

        # Parse session date range
        session_start_date = None
        session_end_date = None
        if request.form.get('session_start_date'):
            session_start_date = datetime.strptime(request.form['session_start_date'], '%Y-%m-%d')
        if request.form.get('session_end_date'):
            session_end_date = datetime.strptime(request.form['session_end_date'], '%Y-%m-%d')

        # Create the session entity
        session_entity = create_entity(
            client,
            'Session',
            user['email'],
            {
                'camp_id': camp_id,
                'name': request.form['name'],
                'age_min': age_min,
                'age_max': age_max,
                'grade_min': grade_min,
                'grade_max': grade_max,
                'duration_weeks': int(request.form.get('duration_weeks', 1)),
                'session_start_date': session_start_date,
                'session_end_date': session_end_date,
                'holidays': [],  # TODO: Add holiday input in Phase 2
                'start_time': request.form.get('start_time', ''),
                'end_time': request.form.get('end_time', ''),
                'dropoff_window_start': request.form.get('dropoff_window_start', ''),
                'dropoff_window_end': request.form.get('dropoff_window_end', ''),
                'pickup_window_start': request.form.get('pickup_window_start', ''),
                'pickup_window_end': request.form.get('pickup_window_end', ''),
                'url': request.form.get('url', ''),
                'cost': cost,
                'early_care_available': 'early_care_available' in request.form,
                'early_care_cost': early_care_cost,
                'late_care_available': 'late_care_available' in request.form,
                'late_care_cost': late_care_cost,
                'registration_open_date': registration_open_date
            }
        )

        flash(f"Session '{request.form['name']}' created successfully!", 'success')
        return redirect(url_for('camps.camp_view', id=camp_id))

    # GET request - show the form with smart defaults
    # Query existing sessions for this camp to determine smart defaults
    existing_sessions = query_by_user(
        client,
        'Session',
        user['email'],
        filters=[('camp_id', '=', camp_id)],
        order_by='-updated_at'
    )

    # Calculate smart defaults based on most recently modified session
    defaults = {}
    if existing_sessions:
        prev_session = entity_to_dict(existing_sessions[0])

        # 1. Auto-increment session name if it ends with a number
        prev_name = prev_session.get('name', '')
        match = re.search(r'^(.+?)(\d+)$', prev_name)
        if match:
            name_base = match.group(1)
            number = int(match.group(2))
            defaults['name'] = f"{name_base}{number + 1}"
        else:
            defaults['name'] = prev_name

        # 2. Calculate start date as Monday after previous session's end date
        if prev_session.get('session_end_date'):
            prev_end = prev_session['session_end_date']
            # Convert to datetime if it's a string
            if isinstance(prev_end, str):
                prev_end = datetime.strptime(prev_end, '%Y-%m-%d')
            # Find the next Monday after the previous session's end date
            days_until_monday = (7 - prev_end.weekday()) % 7
            if days_until_monday == 0:
                days_until_monday = 7
            defaults['session_start_date'] = prev_end + timedelta(days=days_until_monday)

        # 3. Copy duration_weeks (default to 1 if not set)
        defaults['duration_weeks'] = prev_session.get('duration_weeks', 1)

        # 4. Calculate end date based on start date + duration
        if defaults.get('session_start_date') and defaults.get('duration_weeks'):
            start_date = defaults['session_start_date']
            duration_weeks = defaults['duration_weeks']
            # End date is the Friday of the last week
            # For 1 week: Friday of the same week (4 days after Monday)
            # For 2 weeks: Friday of second week (11 days after Monday)
            days_to_add = (duration_weeks * 7) - 3  # -3 because Monday to Friday is 4 days
            defaults['session_end_date'] = start_date + timedelta(days=days_to_add)

        # 5. Copy cost
        if prev_session.get('cost') is not None:
            defaults['cost'] = prev_session['cost']

        # 6. Copy early/late care availability and costs
        defaults['early_care_available'] = prev_session.get('early_care_available', False)
        if prev_session.get('early_care_cost') is not None:
            defaults['early_care_cost'] = prev_session['early_care_cost']

        defaults['late_care_available'] = prev_session.get('late_care_available', False)
        if prev_session.get('late_care_cost') is not None:
            defaults['late_care_cost'] = prev_session['late_care_cost']

        # 7. Copy age and grade eligibility
        if prev_session.get('age_min') is not None:
            defaults['age_min'] = prev_session['age_min']
        if prev_session.get('age_max') is not None:
            defaults['age_max'] = prev_session['age_max']
        if prev_session.get('grade_min') is not None:
            defaults['grade_min'] = prev_session['grade_min']
        if prev_session.get('grade_max') is not None:
            defaults['grade_max'] = prev_session['grade_max']

        # Also copy other useful fields
        defaults['start_time'] = prev_session.get('start_time', '')
        defaults['end_time'] = prev_session.get('end_time', '')
        defaults['dropoff_window_start'] = prev_session.get('dropoff_window_start', '')
        defaults['dropoff_window_end'] = prev_session.get('dropoff_window_end', '')
        defaults['pickup_window_start'] = prev_session.get('pickup_window_start', '')
        defaults['pickup_window_end'] = prev_session.get('pickup_window_end', '')
    else:
        # No previous sessions - use basic defaults
        defaults['duration_weeks'] = 1

    return render_template(
        'session_form.html',
        user=user,
        camp=entity_to_dict(camp),
        session=None,
        defaults=defaults
    )


@camps_bp.route('/sessions/<id>', methods=['GET'])
@login_required
def session_view(id):
    """
    View and edit a session record.

    Why: Session details (times, costs, registration dates) change.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the session and verify ownership
    session_entity = get_entity_for_user(client, 'Session', id, user['email'])

    if not session_entity:
        flash('Session not found or access denied.', 'error')
        return redirect(url_for('camps.camps_list'))

    # Get the parent camp
    camp = get_entity_for_user(client, 'Camp', session_entity['camp_id'], user['email'])

    if not camp:
        flash('Parent camp not found.', 'error')
        return redirect(url_for('camps.camps_list'))

    return render_template(
        'session_form.html',
        user=user,
        camp=entity_to_dict(camp),
        session=entity_to_dict(session_entity),
        defaults={}
    )


@camps_bp.route('/sessions/<id>/update', methods=['POST'])
@login_required
def session_update(id):
    """
    Update an existing session record.

    Why: Session details change frequently (times, costs, registration dates).
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the session and verify ownership
    session_entity = get_entity_for_user(client, 'Session', id, user['email'])

    if not session_entity:
        flash('Session not found or access denied.', 'error')
        return redirect(url_for('camps.camps_list'))

    # Parse optional integer fields
    age_min = int(request.form['age_min']) if request.form.get('age_min') else None
    age_max = int(request.form['age_max']) if request.form.get('age_max') else None
    grade_min = int(request.form['grade_min']) if request.form.get('grade_min') else None
    grade_max = int(request.form['grade_max']) if request.form.get('grade_max') else None
    cost = float(request.form['cost']) if request.form.get('cost') else None
    early_care_cost = float(request.form['early_care_cost']) if request.form.get('early_care_cost') else None
    late_care_cost = float(request.form['late_care_cost']) if request.form.get('late_care_cost') else None

    # Parse registration date
    registration_open_date = None
    if request.form.get('registration_open_date') and request.form.get('registration_open_time'):
        registration_datetime_str = f"{request.form['registration_open_date']} {request.form['registration_open_time']}"
        registration_open_date = datetime.strptime(registration_datetime_str, '%Y-%m-%d %H:%M')

    # Parse session date range
    session_start_date = None
    session_end_date = None
    if request.form.get('session_start_date'):
        session_start_date = datetime.strptime(request.form['session_start_date'], '%Y-%m-%d')
    if request.form.get('session_end_date'):
        session_end_date = datetime.strptime(request.form['session_end_date'], '%Y-%m-%d')

    # Update the session
    update_entity(
        client,
        session_entity,
        {
            'name': request.form['name'],
            'age_min': age_min,
            'age_max': age_max,
            'grade_min': grade_min,
            'grade_max': grade_max,
            'duration_weeks': int(request.form.get('duration_weeks', 1)),
            'session_start_date': session_start_date,
            'session_end_date': session_end_date,
            'start_time': request.form.get('start_time', ''),
            'end_time': request.form.get('end_time', ''),
            'dropoff_window_start': request.form.get('dropoff_window_start', ''),
            'dropoff_window_end': request.form.get('dropoff_window_end', ''),
            'pickup_window_start': request.form.get('pickup_window_start', ''),
            'pickup_window_end': request.form.get('pickup_window_end', ''),
            'url': request.form.get('url', ''),
            'cost': cost,
            'early_care_available': 'early_care_available' in request.form,
            'early_care_cost': early_care_cost,
            'late_care_available': 'late_care_available' in request.form,
            'late_care_cost': late_care_cost,
            'registration_open_date': registration_open_date
        }
    )

    flash(f"Session '{request.form['name']}' updated successfully!", 'success')
    return redirect(url_for('camps.camp_view', id=session_entity['camp_id']))


@camps_bp.route('/sessions/<id>/delete', methods=['POST'])
@login_required
def session_delete(id):
    """
    Delete a session record.

    Why: Remove sessions that are no longer offered.

    This will also delete all associated bookings and calendar events.
    Requires confirmation if bookings exist.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the session and verify ownership
    session_entity = get_entity_for_user(client, 'Session', id, user['email'])

    if not session_entity:
        flash('Session not found or access denied.', 'error')
        return redirect(url_for('camps.camps_list'))

    camp_id = session_entity['camp_id']
    name = session_entity['name']

    # Check for bookings associated with this session
    bookings = query_by_user(
        client,
        'Booking',
        user['email'],
        filters=[('session_id', '=', id)]
    )

    # If bookings exist and user hasn't confirmed, require confirmation
    confirmed = request.args.get('confirm') == '1' or request.form.get('confirm') == '1'

    if bookings and not confirmed:
        booking_count = len(bookings)
        booked_count = sum(1 for b in bookings if b.get('state') == 'booked')

        if booked_count > 0:
            flash(
                f"Warning: This session has {booking_count} booking(s), including {booked_count} confirmed booking(s). "
                f"Deleting this session will also delete all associated bookings and calendar events. "
                f"Please confirm you want to proceed.",
                'warning'
            )
        else:
            flash(
                f"Warning: This session has {booking_count} booking(s). "
                f"Deleting this session will also delete all associated bookings. "
                f"Please confirm you want to proceed.",
                'warning'
            )

        # Redirect back with confirmation parameter
        return render_template(
            'confirm_session_delete.html',
            user=user,
            session=entity_to_dict(session_entity),
            camp_id=camp_id,
            booking_count=booking_count,
            booked_count=booked_count
        )

    # Delete all associated bookings and their calendar events
    bookings_deleted = 0
    calendar_events_deleted = 0

    for booking in bookings:
        try:
            # If booking is 'booked' and has a calendar event, delete it
            if booking.get('state') == 'booked' and booking.get('calendar_event_id') and 'credentials' in session:
                try:
                    success = delete_booking_event(session['credentials'], booking['calendar_event_id'])
                    if success:
                        calendar_events_deleted += 1
                except Exception as e:
                    print(f"Error deleting calendar event {booking['calendar_event_id']}: {e}")

            delete_entity(client, booking)
            bookings_deleted += 1
        except Exception as e:
            print(f"Error deleting booking {booking.key.name}: {e}")

    # Now delete the session
    delete_entity(client, session_entity)

    # Flash appropriate message
    if bookings_deleted > 0:
        if calendar_events_deleted > 0:
            flash(
                f"Session '{name}' deleted successfully along with {bookings_deleted} booking(s) "
                f"and {calendar_events_deleted} calendar event(s).",
                'success'
            )
        else:
            flash(f"Session '{name}' deleted successfully along with {bookings_deleted} booking(s).", 'success')
    else:
        flash(f"Session '{name}' deleted successfully.", 'success')

    return redirect(url_for('camps.camp_view', id=camp_id))


@camps_bp.route('/parse-url', methods=['POST'])
@login_required
def parse_url():
    """
    Parse a camp/session URL using AI to extract structured data.
    
    This endpoint uses Google Gemini to intelligently extract camp and session
    information from website URLs, including multi-level link following and
    stale data detection.
    
    Expects JSON body with:
        - url: The URL to parse
        
    Returns:
        JSON with extracted data and staleness warnings
    """
    user = get_current_user()
    
    try:
        # Get URL from request
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return json.dumps({'success': False, 'error': 'URL is required'}), 400
        
        # Parse the URL using AI
        result = parse_session_url(
            url,
            current_app.config['GCP_PROJECT_ID'],
            current_app.config['GCP_REGION'],
            current_app.config['GEMINI_MODEL']
        )
        
        return json.dumps(result), 200
        
    except Exception as e:
        return json.dumps({
            'success': False,
            'error': str(e)
        }), 500


@camps_bp.route('/<camp_id>/sessions/bulk', methods=['POST'])
@login_required
def session_bulk_create(camp_id):
    """
    Create multiple sessions at once from AI-parsed data.
    
    This endpoint accepts a list of session objects and creates them all
    in a single transaction, useful for adding all sessions from a camp
    website that lists multiple weeks/sessions.
    
    Expects JSON body with:
        - sessions: List of session objects with all session fields
        
    Returns:
        JSON with success status and count of created sessions
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])
    
    try:
        # Verify camp exists and user has access
        camp = get_entity_for_user(client, 'Camp', camp_id, user['email'])
        if not camp:
            return json.dumps({'success': False, 'error': 'Camp not found or access denied'}), 404
        
        # Get sessions from request
        data = request.get_json()
        sessions = data.get('sessions', [])
        
        if not sessions:
            return json.dumps({'success': False, 'error': 'No sessions provided'}), 400
        
        created_count = 0
        
        # Create each session
        for session_data in sessions:
            # Parse optional integer fields
            age_min = session_data.get('age_min')
            age_max = session_data.get('age_max')
            grade_min = session_data.get('grade_min')
            grade_max = session_data.get('grade_max')
            cost = session_data.get('cost')
            early_care_cost = session_data.get('early_care_cost')
            late_care_cost = session_data.get('late_care_cost')
            
            # Parse registration date
            registration_open_date = None
            if session_data.get('registration_open_date'):
                try:
                    registration_open_date = datetime.strptime(
                        session_data['registration_open_date'], 
                        '%Y-%m-%d'
                    )
                except ValueError:
                    pass
            
            # Parse session date range
            session_start_date = None
            session_end_date = None
            if session_data.get('session_start_date'):
                try:
                    session_start_date = datetime.strptime(
                        session_data['session_start_date'],
                        '%Y-%m-%d'
                    )
                except ValueError:
                    pass
            if session_data.get('session_end_date'):
                try:
                    session_end_date = datetime.strptime(
                        session_data['session_end_date'],
                        '%Y-%m-%d'
                    )
                except ValueError:
                    pass

            # Calculate duration_weeks from dates if available
            if session_start_date and session_end_date:
                duration_weeks = calculate_duration_weeks(session_start_date, session_end_date)
            else:
                duration_weeks = session_data.get('duration_weeks', 1)

            # Create the session entity
            create_entity(
                client,
                'Session',
                user['email'],
                {
                    'camp_id': camp_id,
                    'name': session_data.get('name', 'Unnamed Session'),
                    'age_min': age_min,
                    'age_max': age_max,
                    'grade_min': grade_min,
                    'grade_max': grade_max,
                    'duration_weeks': duration_weeks,
                    'session_start_date': session_start_date,
                    'session_end_date': session_end_date,
                    'holidays': [],
                    'start_time': session_data.get('start_time', ''),
                    'end_time': session_data.get('end_time', ''),
                    'dropoff_window_start': session_data.get('dropoff_window_start', ''),
                    'dropoff_window_end': session_data.get('dropoff_window_end', ''),
                    'pickup_window_start': session_data.get('pickup_window_start', ''),
                    'pickup_window_end': session_data.get('pickup_window_end', ''),
                    'url': session_data.get('url', ''),
                    'cost': cost,
                    'early_care_available': session_data.get('early_care_available', False),
                    'early_care_cost': early_care_cost,
                    'late_care_available': session_data.get('late_care_available', False),
                    'late_care_cost': late_care_cost,
                    'registration_open_date': registration_open_date
                }
            )
            created_count += 1
        
        return json.dumps({
            'success': True,
            'created': created_count
        }), 200
        
    except Exception as e:
        return json.dumps({
            'success': False,
            'error': str(e)
        }), 500

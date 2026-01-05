"""
Schedule and booking management blueprint.

Handles week calculation, booking workflow, and schedule views.

Routes:
  - GET /weeks - list all weeks (auto-calculated)
  - POST /weeks/recalculate - recalculate weeks from school dates
  - GET /schedule - main schedule view (calendar-like interface)
  - GET/POST /bookings - list and create bookings
  - GET/PUT/DELETE /bookings/<id> - view, update, delete booking
  - PUT /bookings/<id>/state - transition booking state

Why this module exists:
This is the core workflow module where planning happens. Weeks, bookings, and
the main schedule view are all about "when" things happen.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, jsonify
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
from datetime import datetime, timedelta
import uuid

# Create the blueprint
schedule_bp = Blueprint('schedule', __name__, url_prefix='/schedule')


# ============================================================================
# WEEK CALCULATION HELPERS
# ============================================================================

def calculate_weeks_for_user(client, user_email):
    """
    Calculate summer weeks based on kids' school dates.

    Algorithm:
    1. Find earliest last_day_of_school across all kids
    2. Calculate first Monday after that date
    3. Find latest first_day_of_school across all kids
    4. Generate Week entities from first Monday to day before school starts
    5. Apply trip blocking

    Returns:
        List of created week entities

    Why: Summer weeks are determined by school schedules. We need to know
    which weeks are available for camp planning.
    """
    # Get all kids for this user
    kids = query_by_user(client, 'Kid', user_email)

    if not kids:
        return []

    # Find earliest last day of school (when summer starts)
    earliest_last_day = None
    for kid in kids:
        last_day = kid.get('last_day_of_school')
        if last_day and (not earliest_last_day or last_day < earliest_last_day):
            earliest_last_day = last_day

    # Find latest first day of school (when summer ends)
    latest_first_day = None
    for kid in kids:
        first_day = kid.get('first_day_of_school')
        if first_day and (not latest_first_day or first_day > latest_first_day):
            latest_first_day = first_day

    if not earliest_last_day or not latest_first_day:
        flash('Kids must have school dates set to calculate weeks.', 'error')
        return []

    # Calculate first Monday of summer (Monday after earliest last day of school)
    # If last day is already Monday, start the next Monday
    days_until_monday = (7 - earliest_last_day.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    first_monday = earliest_last_day + timedelta(days=days_until_monday)

    # Delete existing weeks for this user (we're recalculating)
    existing_weeks = query_by_user(client, 'Week', user_email)
    for week in existing_weeks:
        delete_entity(client, week)

    # Generate weeks from first Monday until the day before school starts
    weeks = []
    week_number = 1
    current_monday = first_monday

    while current_monday < latest_first_day:
        # Week runs from Monday to Friday (5 days)
        week_end = current_monday + timedelta(days=4)  # Friday

        # Don't create a week that extends past school start
        if week_end >= latest_first_day:
            break

        # Create the week entity
        week = create_entity(
            client,
            'Week',
            user_email,
            {
                'week_number': week_number,
                'start_date': current_monday,
                'end_date': week_end,
                'is_blocked': False  # Will be updated by trip blocking
            }
        )
        weeks.append(week)

        week_number += 1
        current_monday += timedelta(days=7)  # Next Monday

    # Apply trip blocking
    trips = query_by_user(client, 'Trip', user_email)
    for week in weeks:
        week_start = week['start_date']
        week_end = week['end_date']

        for trip in trips:
            trip_start = trip['start_date']
            trip_end = trip['end_date']

            # Check if trip overlaps with this week
            if trip_start <= week_end and trip_end >= week_start:
                week['is_blocked'] = True
                update_entity(client, week, {'is_blocked': True})
                break

    return weeks


# ============================================================================
# WEEK ROUTES
# ============================================================================

@schedule_bp.route('/weeks')
@login_required
def weeks_list():
    """
    List all weeks for the current user.

    Why: Shows all summer weeks with their blocked status.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get all weeks, ordered by week number
    weeks = query_by_user(client, 'Week', user['email'], order_by='week_number')

    return render_template(
        'weeks_list.html',
        user=user,
        weeks=entities_to_dict_list(weeks)
    )


@schedule_bp.route('/weeks/recalculate', methods=['POST'])
@login_required
def weeks_recalculate():
    """
    Recalculate weeks from kids' school dates.

    Why: When school dates change or kids are added/removed, weeks need
    to be recalculated.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    weeks = calculate_weeks_for_user(client, user['email'])

    if weeks:
        flash(f"Successfully calculated {len(weeks)} summer weeks!", 'success')
    else:
        flash("No weeks calculated. Make sure kids have school dates set.", 'warning')

    return redirect(url_for('schedule.weeks_list'))


# ============================================================================
# BOOKING ROUTES
# ============================================================================

@schedule_bp.route('/bookings')
@login_required
def bookings_list():
    """
    List all bookings for the current user.

    Why: Shows all camp bookings across all states.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get all bookings
    bookings = query_by_user(client, 'Booking', user['email'])

    # Enrich bookings with kid, session, and week info
    enriched_bookings = []
    for booking in bookings:
        booking_dict = entity_to_dict(booking)

        # Get kid name
        kid = get_entity_for_user(client, 'Kid', booking['kid_id'], user['email'])
        booking_dict['kid_name'] = kid['name'] if kid else 'Unknown'

        # Get session and camp name
        session_entity = get_entity_for_user(client, 'Session', booking['session_id'], user['email'])
        if session_entity:
            booking_dict['session_name'] = session_entity['name']
            camp = get_entity_for_user(client, 'Camp', session_entity['camp_id'], user['email'])
            booking_dict['camp_name'] = camp['name'] if camp else 'Unknown'
        else:
            booking_dict['session_name'] = 'Unknown'
            booking_dict['camp_name'] = 'Unknown'

        # Get week info
        week = get_entity_for_user(client, 'Week', booking['week_id'], user['email'])
        if week:
            booking_dict['week_number'] = week['week_number']
            booking_dict['week_dates'] = f"{week['start_date']} - {week['end_date']}"
        else:
            booking_dict['week_number'] = '?'
            booking_dict['week_dates'] = 'Unknown'

        enriched_bookings.append(booking_dict)

    return render_template(
        'bookings_list.html',
        user=user,
        bookings=enriched_bookings
    )


@schedule_bp.route('/bookings/new', methods=['GET', 'POST'])
@login_required
def booking_new():
    """
    Create a new booking.

    Why: Users need to add camp ideas and bookings for their kids.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    if request.method == 'POST':
        kid_id = request.form['kid_id']
        session_id = request.form['session_id']
        week_id = request.form['week_id']
        state = request.form.get('state', 'idea')

        # Validate ownership
        kid = get_entity_for_user(client, 'Kid', kid_id, user['email'])
        session_entity = get_entity_for_user(client, 'Session', session_id, user['email'])
        week = get_entity_for_user(client, 'Week', week_id, user['email'])

        if not kid or not session_entity or not week:
            flash('Invalid kid, session, or week selected.', 'error')
            return redirect(url_for('schedule.booking_new'))

        # Check if this kid already has a booking with state='booked' for this week
        if state == 'booked':
            existing_bookings = query_by_user(
                client,
                'Booking',
                user['email'],
                filters=[('kid_id', '=', kid_id), ('week_id', '=', week_id), ('state', '=', 'booked')]
            )
            if existing_bookings:
                flash(f"{kid['name']} already has a booked camp for this week. Only one camp can be booked per week.", 'error')
                return redirect(url_for('schedule.booking_new'))

        # Parse friends attending
        friends_str = request.form.get('friends_attending', '')
        friends = [f.strip() for f in friends_str.split(',') if f.strip()]

        # Create the booking
        booking = create_entity(
            client,
            'Booking',
            user['email'],
            {
                'kid_id': kid_id,
                'session_id': session_id,
                'week_id': week_id,
                'state': state,
                'preference_order': int(request.form.get('preference_order', 0)),
                'friends_attending': friends,
                'uses_early_care': 'uses_early_care' in request.form,
                'uses_late_care': 'uses_late_care' in request.form,
                'notes': request.form.get('notes', ''),
                'calendar_event_id': None  # Will be set in Phase 3
            }
        )

        flash(f"Booking created for {kid['name']}!", 'success')
        return redirect(url_for('schedule.schedule_view'))

    # GET - show form
    kids = query_by_user(client, 'Kid', user['email'], order_by='name')
    camps = query_by_user(client, 'Camp', user['email'], order_by='name')
    weeks = query_by_user(client, 'Week', user['email'], order_by='week_number')

    # Get all sessions grouped by camp
    sessions_by_camp = {}
    for camp in camps:
        sessions = query_by_user(
            client,
            'Session',
            user['email'],
            filters=[('camp_id', '=', camp.key.name)]
        )
        sessions_by_camp[camp.key.name] = entities_to_dict_list(sessions)

    return render_template(
        'booking_form.html',
        user=user,
        booking=None,
        kids=entities_to_dict_list(kids),
        camps=entities_to_dict_list(camps),
        weeks=entities_to_dict_list(weeks),
        sessions_by_camp=sessions_by_camp
    )


@schedule_bp.route('/bookings/<id>', methods=['GET'])
@login_required
def booking_view(id):
    """
    View and edit a booking.

    Why: Users need to update booking details and state.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    booking = get_entity_for_user(client, 'Booking', id, user['email'])

    if not booking:
        flash('Booking not found or access denied.', 'error')
        return redirect(url_for('schedule.schedule_view'))

    # Get related entities
    kids = query_by_user(client, 'Kid', user['email'], order_by='name')
    camps = query_by_user(client, 'Camp', user['email'], order_by='name')
    weeks = query_by_user(client, 'Week', user['email'], order_by='week_number')

    # Get all sessions grouped by camp
    sessions_by_camp = {}
    for camp in camps:
        sessions = query_by_user(
            client,
            'Session',
            user['email'],
            filters=[('camp_id', '=', camp.key.name)]
        )
        sessions_by_camp[camp.key.name] = entities_to_dict_list(sessions)

    return render_template(
        'booking_form.html',
        user=user,
        booking=entity_to_dict(booking),
        kids=entities_to_dict_list(kids),
        camps=entities_to_dict_list(camps),
        weeks=entities_to_dict_list(weeks),
        sessions_by_camp=sessions_by_camp
    )


@schedule_bp.route('/bookings/<id>/update', methods=['POST'])
@login_required
def booking_update(id):
    """
    Update a booking.

    Why: Booking details change (different sessions, preference order, etc).
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    booking = get_entity_for_user(client, 'Booking', id, user['email'])

    if not booking:
        flash('Booking not found or access denied.', 'error')
        return redirect(url_for('schedule.schedule_view'))

    # Parse friends attending
    friends_str = request.form.get('friends_attending', '')
    friends = [f.strip() for f in friends_str.split(',') if f.strip()]

    # Update the booking
    update_entity(
        client,
        booking,
        {
            'preference_order': int(request.form.get('preference_order', 0)),
            'friends_attending': friends,
            'uses_early_care': 'uses_early_care' in request.form,
            'uses_late_care': 'uses_late_care' in request.form,
            'notes': request.form.get('notes', '')
        }
    )

    flash('Booking updated successfully!', 'success')
    return redirect(url_for('schedule.schedule_view'))


@schedule_bp.route('/bookings/<id>/state', methods=['POST'])
@login_required
def booking_change_state(id):
    """
    Change a booking's state (idea → preferred → booked).

    Why: Bookings progress through states as planning advances.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    booking = get_entity_for_user(client, 'Booking', id, user['email'])

    if not booking:
        flash('Booking not found or access denied.', 'error')
        return redirect(url_for('schedule.schedule_view'))

    new_state = request.form['state']

    # Validate state transitions
    valid_states = ['idea', 'preferred', 'booked']
    if new_state not in valid_states:
        flash('Invalid state.', 'error')
        return redirect(url_for('schedule.schedule_view'))

    # Check if transitioning to 'booked'
    if new_state == 'booked':
        # Only one booking per kid/week can be 'booked'
        existing_booked = query_by_user(
            client,
            'Booking',
            user['email'],
            filters=[
                ('kid_id', '=', booking['kid_id']),
                ('week_id', '=', booking['week_id']),
                ('state', '=', 'booked')
            ]
        )

        if existing_booked and existing_booked[0].key.name != id:
            kid = get_entity_for_user(client, 'Kid', booking['kid_id'], user['email'])
            flash(f"{kid['name']} already has a booked camp for this week. Only one camp can be booked per week.", 'error')
            return redirect(url_for('schedule.schedule_view'))

    # Update state
    update_entity(client, booking, {'state': new_state})

    flash(f"Booking state changed to '{new_state}'!", 'success')
    # TODO Phase 3: If state='booked', create calendar event

    return redirect(url_for('schedule.schedule_view'))


@schedule_bp.route('/bookings/<id>/delete', methods=['POST'])
@login_required
def booking_delete(id):
    """
    Delete a booking.

    Why: Remove cancelled or unwanted bookings.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    booking = get_entity_for_user(client, 'Booking', id, user['email'])

    if not booking:
        flash('Booking not found or access denied.', 'error')
        return redirect(url_for('schedule.schedule_view'))

    delete_entity(client, booking)

    flash('Booking deleted successfully.', 'success')
    # TODO Phase 3: If state was 'booked', delete calendar event

    return redirect(url_for('schedule.schedule_view'))


# ============================================================================
# SCHEDULE VIEW (MAIN INTERFACE)
# ============================================================================

@schedule_bp.route('/')
@login_required
def schedule_view():
    """
    Main schedule grid view (kids × weeks).

    Why: This is the primary interface for camp planning - shows all kids
    and weeks in a grid with color-coded booking states.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get all kids, weeks, and bookings
    kids = query_by_user(client, 'Kid', user['email'], order_by='name')
    weeks = query_by_user(client, 'Week', user['email'], order_by='week_number')
    bookings = query_by_user(client, 'Booking', user['email'])

    # Build a lookup: (kid_id, week_id) -> [bookings]
    bookings_lookup = {}
    for booking in bookings:
        key = (booking['kid_id'], booking['week_id'])
        if key not in bookings_lookup:
            bookings_lookup[key] = []

        # Enrich booking with session/camp info
        booking_dict = entity_to_dict(booking)
        session_entity = get_entity_for_user(client, 'Session', booking['session_id'], user['email'])
        if session_entity:
            booking_dict['session_name'] = session_entity['name']
            camp = get_entity_for_user(client, 'Camp', session_entity['camp_id'], user['email'])
            booking_dict['camp_name'] = camp['name'] if camp else 'Unknown'
        else:
            booking_dict['session_name'] = 'Unknown'
            booking_dict['camp_name'] = 'Unknown'

        bookings_lookup[key].append(booking_dict)

    return render_template(
        'schedule.html',
        user=user,
        kids=entities_to_dict_list(kids),
        weeks=entities_to_dict_list(weeks),
        bookings_lookup=bookings_lookup
    )

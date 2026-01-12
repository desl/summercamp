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

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, jsonify, make_response
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
from calendar_integration import (
    create_booking_event,
    update_booking_event,
    delete_booking_event
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


def update_week_blocking(client, user_email):
    """
    Update the is_blocked status on all weeks based on current trips.

    Unlike calculate_weeks_for_user, this does NOT delete/recreate weeks.
    It only updates the blocking status, preserving week IDs and bookings.

    Use this after trip changes (create, update, delete).
    """
    # Get all weeks and trips for this user
    weeks = query_by_user(client, 'Week', user_email)
    trips = list(query_by_user(client, 'Trip', user_email))

    for week in weeks:
        week_start = week['start_date']
        week_end = week['end_date']

        # Check if any trip overlaps with this week
        is_blocked = False
        for trip in trips:
            trip_start = trip['start_date']
            trip_end = trip['end_date']

            # Check if trip overlaps with this week
            if trip_start <= week_end and trip_end >= week_start:
                is_blocked = True
                break

        # Update if blocking status changed
        if week.get('is_blocked') != is_blocked:
            update_entity(client, week, {'is_blocked': is_blocked})


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


@schedule_bp.route('/bookings/cleanup', methods=['POST'])
@login_required
def bookings_cleanup():
    """
    Cleanup legacy bookings that don't have multi-week fields.

    Why: Bookings created before multi-week implementation need migration.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get all bookings
    all_bookings = query_by_user(client, 'Booking', user['email'])

    updated_count = 0
    for booking in all_bookings:
        needs_update = False
        updates = {}

        # Add booking_group_id if missing (use booking's own ID for single-week legacy bookings)
        if not booking.get('booking_group_id'):
            updates['booking_group_id'] = booking.key.name
            needs_update = True

        # Add week_of_session if missing
        if booking.get('week_of_session') is None:
            updates['week_of_session'] = 1
            needs_update = True

        # Add total_weeks if missing
        if not booking.get('total_weeks'):
            updates['total_weeks'] = 1
            needs_update = True

        if needs_update:
            update_entity(client, booking, updates)
            updated_count += 1

    if updated_count > 0:
        flash(f'Cleaned up {updated_count} legacy bookings.', 'success')
    else:
        flash('No legacy bookings found that need cleanup.', 'info')

    return redirect(url_for('schedule.schedule_view'))


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

        # Get session duration for multi-week sessions
        duration_weeks = session_entity.get('duration_weeks', 1)

        # Get all weeks to determine consecutive weeks for multi-week sessions
        all_weeks = query_by_user(client, 'Week', user['email'], order_by='week_number')
        week_list = list(all_weeks)

        # Find the starting week index
        start_week_idx = None
        for idx, w in enumerate(week_list):
            if w.key.name == week_id:
                start_week_idx = idx
                break

        if start_week_idx is None:
            flash('Selected week not found.', 'error')
            return redirect(url_for('schedule.booking_new'))

        # Check if we have enough consecutive weeks
        if start_week_idx + duration_weeks > len(week_list):
            flash(f"Not enough weeks available for this {duration_weeks}-week session.", 'error')
            return redirect(url_for('schedule.booking_new'))

        # Get the weeks needed for this booking
        weeks_needed = week_list[start_week_idx:start_week_idx + duration_weeks]

        # Validate session dates if specified
        session_start_date = session_entity.get('session_start_date')
        session_end_date = session_entity.get('session_end_date')

        if session_start_date and session_end_date:
            # Check that all selected weeks fall within the session's date range (with 1-week buffer on each end)
            for w in weeks_needed:
                week_start = w['start_date']
                week_end = w['end_date']

                # Allow booking if the week overlaps with session dates or is within 1 week before/after
                buffer_days = 7
                session_start_with_buffer = session_start_date - timedelta(days=buffer_days)
                session_end_with_buffer = session_end_date + timedelta(days=buffer_days)

                # Check if week is completely outside the session date range (with buffer)
                if week_end < session_start_with_buffer or week_start > session_end_with_buffer:
                    camp = get_entity_for_user(client, 'Camp', session_entity['camp_id'], user['email'])
                    flash(f"Week {w['week_number']} ({week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}) is outside the date range for {camp['name']} - {session_entity['name']} (runs {session_start_date.strftime('%Y-%m-%d')} to {session_end_date.strftime('%Y-%m-%d')}).", 'error')
                    return redirect(url_for('schedule.booking_new'))

        # Check if any of the needed weeks are blocked by trips
        for w in weeks_needed:
            if w.get('is_blocked'):
                flash(f"Week {w['week_number']} is blocked by a family trip. Cannot book multi-week session.", 'error')
                return redirect(url_for('schedule.booking_new'))

        # Check for booking collisions with existing bookings
        collision_warnings = []
        has_booked_conflict = False

        for w in weeks_needed:
            existing_bookings = query_by_user(
                client,
                'Booking',
                user['email'],
                filters=[('kid_id', '=', kid_id), ('week_id', '=', w.key.name)]
            )

            if existing_bookings:
                for existing in existing_bookings:
                    existing_session = get_entity_for_user(client, 'Session', existing['session_id'], user['email'])
                    existing_camp = None
                    if existing_session:
                        existing_camp = get_entity_for_user(client, 'Camp', existing_session['camp_id'], user['email'])

                    camp_name = existing_camp['name'] if existing_camp else 'Unknown'
                    session_name = existing_session['name'] if existing_session else 'Unknown'

                    if existing['state'] == 'booked':
                        has_booked_conflict = True
                        collision_warnings.append(
                            f"Week {w['week_number']}: {kid['name']} already has a BOOKED camp ({camp_name} - {session_name})"
                        )
                    else:
                        collision_warnings.append(
                            f"Week {w['week_number']}: {kid['name']} has an existing {existing['state']} for {camp_name} - {session_name}"
                        )

        # If trying to book and there are ANY conflicts (even ideas/preferred), prevent it
        if state == 'booked' and collision_warnings:
            flash(f"Cannot book this camp. {kid['name']} has conflicts:", 'error')
            for warning in collision_warnings:
                flash(warning, 'warning')
            return redirect(url_for('schedule.booking_new'))

        # If trying to create as idea/preferred but there's a booked conflict, prevent it
        if has_booked_conflict:
            flash(f"Cannot add this booking. {kid['name']} already has booked camps for these weeks:", 'error')
            for warning in collision_warnings:
                if 'BOOKED' in warning:
                    flash(warning, 'error')
            return redirect(url_for('schedule.booking_new'))

        # If there are non-booked collisions, warn but allow
        if collision_warnings:
            flash(f"Warning: This booking conflicts with existing bookings for {kid['name']}:", 'warning')
            for warning in collision_warnings:
                flash(warning, 'info')

        # Parse friends attending
        friends_str = request.form.get('friends_attending', '')
        friends = [f.strip() for f in friends_str.split(',') if f.strip()]

        # Generate a booking group ID for multi-week sessions
        booking_group_id = str(uuid.uuid4())

        # Create bookings for each week
        for week_num, w in enumerate(weeks_needed, start=1):
            booking = create_entity(
                client,
                'Booking',
                user['email'],
                {
                    'kid_id': kid_id,
                    'session_id': session_id,
                    'week_id': w.key.name,
                    'state': state,
                    'preference_order': int(request.form.get('preference_order', 0)),
                    'friends_attending': friends,
                    'uses_early_care': 'uses_early_care' in request.form,
                    'uses_late_care': 'uses_late_care' in request.form,
                    'notes': request.form.get('notes', ''),
                    'calendar_event_id': None,
                    'booking_group_id': booking_group_id,
                    'week_of_session': week_num,
                    'total_weeks': duration_weeks
                }
            )

        if duration_weeks > 1:
            flash(f"Multi-week booking created for {kid['name']} ({duration_weeks} weeks)!", 'success')
        else:
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

    # If booking is 'booked' and has a calendar event, update it
    if booking.get('state') == 'booked' and booking.get('calendar_event_id') and 'credentials' in session:
        kid = get_entity_for_user(client, 'Kid', booking['kid_id'], user['email'])
        session_entity = get_entity_for_user(client, 'Session', booking['session_id'], user['email'])
        week = get_entity_for_user(client, 'Week', booking['week_id'], user['email'])

        if kid and session_entity and week:
            camp = get_entity_for_user(client, 'Camp', session_entity['camp_id'], user['email'])
            parents = query_by_user(client, 'Parent', user['email'])
            parent = parents[0] if parents else {'name': user['name'], 'email': user['email']}

            success = update_booking_event(
                session['credentials'],
                booking['calendar_event_id'],
                entity_to_dict(parent),
                entity_to_dict(kid),
                entity_to_dict(camp) if camp else {'name': 'Unknown Camp'},
                entity_to_dict(session_entity),
                entity_to_dict(week)
            )

            if success:
                flash('Booking and calendar event updated successfully!', 'success')
            else:
                flash('Booking updated, but calendar update failed.', 'warning')
        else:
            flash('Booking updated successfully!', 'success')
    else:
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

    # Get all bookings in this group (for multi-week sessions)
    booking_group_id = booking.get('booking_group_id')
    if booking_group_id:
        # Get all bookings in the group
        group_bookings = query_by_user(
            client,
            'Booking',
            user['email'],
            filters=[('booking_group_id', '=', booking_group_id)]
        )
    else:
        # Single booking
        group_bookings = [booking]

    # Check if transitioning to 'booked' - verify no conflicts for any week in the group
    if new_state == 'booked':
        collision_warnings = []

        for grp_booking in group_bookings:
            # Check for ANY other bookings (different booking_group_id) for this kid/week
            all_bookings_for_week = query_by_user(
                client,
                'Booking',
                user['email'],
                filters=[
                    ('kid_id', '=', grp_booking['kid_id']),
                    ('week_id', '=', grp_booking['week_id'])
                ]
            )

            # Check if there are other bookings (different booking group)
            for other_booking in all_bookings_for_week:
                # Skip bookings in the same group
                if booking_group_id and other_booking.get('booking_group_id') == booking_group_id:
                    continue
                if other_booking.key.name == grp_booking.key.name:
                    continue

                # Found a conflicting booking
                kid = get_entity_for_user(client, 'Kid', grp_booking['kid_id'], user['email'])
                week = get_entity_for_user(client, 'Week', grp_booking['week_id'], user['email'])

                other_session = get_entity_for_user(client, 'Session', other_booking['session_id'], user['email'])
                other_camp = None
                if other_session:
                    other_camp = get_entity_for_user(client, 'Camp', other_session['camp_id'], user['email'])

                camp_name = other_camp['name'] if other_camp else 'Unknown'
                session_name = other_session['name'] if other_session else 'Unknown'

                collision_warnings.append(
                    f"Week {week['week_number']}: {kid['name']} has an existing {other_booking['state']} for {camp_name} - {session_name}"
                )

        if collision_warnings:
            flash(f"Cannot promote to 'booked'. There are conflicting bookings:", 'error')
            for warning in collision_warnings:
                flash(warning, 'warning')
            return redirect(url_for('schedule.schedule_view'))

    # Update state for all bookings in the group
    calendar_created = False
    for grp_booking in group_bookings:
        update_data = {'state': new_state}

        # If transitioning to 'booked', create calendar event
        if new_state == 'booked' and 'credentials' in session:
            # Get related entities for calendar event
            kid = get_entity_for_user(client, 'Kid', grp_booking['kid_id'], user['email'])
            session_entity = get_entity_for_user(client, 'Session', grp_booking['session_id'], user['email'])
            week = get_entity_for_user(client, 'Week', grp_booking['week_id'], user['email'])

            if kid and session_entity and week:
                camp = get_entity_for_user(client, 'Camp', session_entity['camp_id'], user['email'])

                # Get parent for calendar (use first parent or create dummy)
                parents = query_by_user(client, 'Parent', user['email'])
                parent = parents[0] if parents else {'name': user['name'], 'email': user['email']}

                # Create calendar event
                calendar_event_id = create_booking_event(
                    session['credentials'],
                    entity_to_dict(parent),
                    entity_to_dict(kid),
                    entity_to_dict(camp) if camp else {'name': 'Unknown Camp'},
                    entity_to_dict(session_entity),
                    entity_to_dict(week)
                )

                if calendar_event_id:
                    update_data['calendar_event_id'] = calendar_event_id
                    calendar_created = True

        update_entity(client, grp_booking, update_data)

    # Flash appropriate message
    total_weeks = booking.get('total_weeks', 1)
    if new_state == 'booked' and calendar_created:
        if total_weeks > 1:
            flash(f"Multi-week booking state changed to '{new_state}' and added to calendar ({total_weeks} weeks)!", 'success')
        else:
            flash(f"Booking state changed to '{new_state}' and added to calendar!", 'success')
    elif new_state == 'booked':
        flash(f"Booking state changed to '{new_state}' but calendar event creation failed.", 'warning')
    else:
        if total_weeks > 1:
            flash(f"Multi-week booking state changed to '{new_state}' ({total_weeks} weeks)!", 'success')
        else:
            flash(f"Booking state changed to '{new_state}'!", 'success')

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

    # Get all bookings in this group (for multi-week sessions)
    booking_group_id = booking.get('booking_group_id')
    if booking_group_id:
        # Get all bookings in the group
        try:
            group_bookings = query_by_user(
                client,
                'Booking',
                user['email'],
                filters=[('booking_group_id', '=', booking_group_id)]
            )
        except Exception as e:
            # If query fails, just delete the single booking
            print(f"Error querying booking group: {e}")
            group_bookings = [booking]
    else:
        # Single booking (including legacy bookings without booking_group_id)
        group_bookings = [booking]

    # Delete all bookings and their calendar events
    calendar_deleted = False
    bookings_deleted = 0

    for grp_booking in group_bookings:
        try:
            # If booking was 'booked' and has a calendar event, delete it
            if grp_booking.get('state') == 'booked' and grp_booking.get('calendar_event_id') and 'credentials' in session:
                try:
                    success = delete_booking_event(session['credentials'], grp_booking['calendar_event_id'])
                    if success:
                        calendar_deleted = True
                except Exception as e:
                    print(f"Error deleting calendar event: {e}")

            delete_entity(client, grp_booking)
            bookings_deleted += 1
        except Exception as e:
            print(f"Error deleting booking {grp_booking.key.name}: {e}")
            flash(f'Error deleting booking: {str(e)}', 'error')

    # Flash appropriate message
    total_weeks = booking.get('total_weeks', 1)
    if bookings_deleted == 0:
        flash('Failed to delete booking.', 'error')
    elif calendar_deleted:
        if total_weeks > 1 or bookings_deleted > 1:
            flash(f'Multi-week booking and calendar events deleted successfully ({bookings_deleted} weeks).', 'success')
        else:
            flash('Booking and calendar event deleted successfully.', 'success')
    else:
        if total_weeks > 1 or bookings_deleted > 1:
            flash(f'Multi-week booking deleted successfully ({bookings_deleted} weeks).', 'success')
        else:
            flash('Booking deleted successfully.', 'success')

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

    # Get view preference from cookie (default to horizontal)
    view_mode = request.cookies.get('schedule_view', 'horizontal')

    # Get all kids, weeks, bookings, and trips
    kids = query_by_user(client, 'Kid', user['email'], order_by='name')
    weeks = query_by_user(client, 'Week', user['email'], order_by='week_number')
    bookings = query_by_user(client, 'Booking', user['email'])
    trips = list(query_by_user(client, 'Trip', user['email']))

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

    # Build a lookup: week_id -> trip_name (for blocked weeks)
    week_trips = {}
    weeks_list = list(weeks)
    for week in weeks_list:
        if week.get('is_blocked'):
            week_start = week['start_date']
            week_end = week['end_date']
            for trip in trips:
                trip_start = trip['start_date']
                trip_end = trip['end_date']
                # Check if trip overlaps with this week
                if trip_start <= week_end and trip_end >= week_start:
                    week_trips[week.key.name] = trip['name']
                    break

    return render_template(
        'schedule.html',
        user=user,
        kids=entities_to_dict_list(kids),
        weeks=entities_to_dict_list(weeks_list),
        bookings_lookup=bookings_lookup,
        week_trips=week_trips,
        view_mode=view_mode
    )


@schedule_bp.route('/toggle-view', methods=['POST'])
@login_required
def toggle_view():
    """
    Toggle schedule view between horizontal and vertical layouts.

    Saves preference in a cookie for future visits.
    """
    current_view = request.cookies.get('schedule_view', 'horizontal')
    new_view = 'vertical' if current_view == 'horizontal' else 'horizontal'

    response = make_response(redirect(url_for('schedule.schedule_view')))
    # Set cookie to expire in 1 year
    response.set_cookie('schedule_view', new_view, max_age=365*24*60*60)

    return response


# ============================================================================
# API ENDPOINTS FOR MODAL BOOKING
# ============================================================================

@schedule_bp.route('/api/sessions-for-week')
@login_required
def api_sessions_for_week():
    """
    Return sessions that match a week's date range.

    Used by the modal booking UI to show filtered sessions.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    week_id = request.args.get('week_id')
    kid_id = request.args.get('kid_id')

    if not week_id:
        return jsonify({'error': 'week_id is required'}), 400

    # Get the week to determine date range
    week = get_entity_for_user(client, 'Week', week_id, user['email'])
    if not week:
        return jsonify({'error': 'Week not found'}), 404

    week_start = week['start_date']
    week_end = week['end_date']

    # Get all camps and their sessions
    camps = query_by_user(client, 'Camp', user['email'], order_by='name')
    result_sessions = []

    for camp in camps:
        sessions = query_by_user(
            client,
            'Session',
            user['email'],
            filters=[('camp_id', '=', camp.key.name)]
        )

        for session_entity in sessions:
            session_dict = entity_to_dict(session_entity)
            session_dict['camp_name'] = camp['name']
            session_dict['camp_id'] = camp.key.name

            # Check if session matches the week
            # A session matches if at least one day of the session falls within the week
            session_start = session_entity.get('session_start_date')
            session_end = session_entity.get('session_end_date')

            include_session = False

            if not session_start or not session_end:
                # Sessions without dates are always shown
                include_session = True
            else:
                # Check for actual date overlap (no buffer)
                # Session overlaps week if: session_start <= week_end AND session_end >= week_start
                if session_start <= week_end and session_end >= week_start:
                    include_session = True

            if include_session:
                result_sessions.append(session_dict)

    return jsonify({
        'sessions': result_sessions,
        'week': entity_to_dict(week)
    })


@schedule_bp.route('/api/quick-booking', methods=['POST'])
@login_required
def api_quick_booking():
    """
    Create a booking with minimal data (defaults to 'idea' state).

    Used by the modal booking UI for quick session selection.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    kid_id = data.get('kid_id')
    session_id = data.get('session_id')
    week_id = data.get('week_id')

    if not kid_id or not session_id or not week_id:
        return jsonify({'error': 'kid_id, session_id, and week_id are required'}), 400

    # Validate ownership
    kid = get_entity_for_user(client, 'Kid', kid_id, user['email'])
    session_entity = get_entity_for_user(client, 'Session', session_id, user['email'])
    week = get_entity_for_user(client, 'Week', week_id, user['email'])

    if not kid or not session_entity or not week:
        return jsonify({'error': 'Invalid kid, session, or week'}), 404

    # Get session duration for multi-week sessions
    duration_weeks = session_entity.get('duration_weeks', 1)

    # Get all weeks to determine consecutive weeks for multi-week sessions
    all_weeks = query_by_user(client, 'Week', user['email'], order_by='week_number')
    week_list = list(all_weeks)

    # Find the starting week index
    start_week_idx = None
    for idx, w in enumerate(week_list):
        if w.key.name == week_id:
            start_week_idx = idx
            break

    if start_week_idx is None:
        return jsonify({'error': 'Selected week not found'}), 404

    # Check if we have enough consecutive weeks
    if start_week_idx + duration_weeks > len(week_list):
        return jsonify({
            'error': f'Not enough weeks available for this {duration_weeks}-week session'
        }), 400

    # Get the weeks needed for this booking
    weeks_needed = week_list[start_week_idx:start_week_idx + duration_weeks]

    # Check if any of the needed weeks are blocked by trips
    for w in weeks_needed:
        if w.get('is_blocked'):
            return jsonify({
                'error': f'Week {w["week_number"]} is blocked by a family trip'
            }), 400

    # Check for booking collisions with booked camps
    for w in weeks_needed:
        existing_bookings = query_by_user(
            client,
            'Booking',
            user['email'],
            filters=[('kid_id', '=', kid_id), ('week_id', '=', w.key.name)]
        )

        for existing in existing_bookings:
            if existing['state'] == 'booked':
                existing_session = get_entity_for_user(client, 'Session', existing['session_id'], user['email'])
                existing_camp = None
                if existing_session:
                    existing_camp = get_entity_for_user(client, 'Camp', existing_session['camp_id'], user['email'])

                camp_name = existing_camp['name'] if existing_camp else 'Unknown'
                return jsonify({
                    'error': f'{kid["name"]} already has a booked camp for Week {w["week_number"]}: {camp_name}'
                }), 400

    # Generate a booking group ID for multi-week sessions
    booking_group_id = str(uuid.uuid4())

    # Create bookings for each week
    created_bookings = []
    for week_num, w in enumerate(weeks_needed, start=1):
        booking = create_entity(
            client,
            'Booking',
            user['email'],
            {
                'kid_id': kid_id,
                'session_id': session_id,
                'week_id': w.key.name,
                'state': 'idea',
                'preference_order': 0,
                'friends_attending': [],
                'uses_early_care': False,
                'uses_late_care': False,
                'notes': '',
                'calendar_event_id': None,
                'booking_group_id': booking_group_id,
                'week_of_session': week_num,
                'total_weeks': duration_weeks
            }
        )
        created_bookings.append(entity_to_dict(booking))

    # Get camp name for response
    camp = get_entity_for_user(client, 'Camp', session_entity['camp_id'], user['email'])
    camp_name = camp['name'] if camp else 'Unknown'

    return jsonify({
        'success': True,
        'message': f'Added {camp_name} - {session_entity["name"]} for {kid["name"]}',
        'bookings': created_bookings,
        'duration_weeks': duration_weeks
    })

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
from datetime import datetime

# Create the blueprint
camps_bp = Blueprint('camps', __name__, url_prefix='/camps')


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

    return render_template(
        'camp_form.html',
        user=user,
        camp=entity_to_dict(camp),
        sessions=entities_to_dict_list(sessions)
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

    # GET request - show the form
    return render_template(
        'session_form.html',
        user=user,
        camp=entity_to_dict(camp),
        session=None
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
        session=entity_to_dict(session_entity)
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

    Note: This should warn if bookings exist (Phase 2 enhancement).
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
    delete_entity(client, session_entity)

    flash(f"Session '{name}' deleted successfully.", 'success')
    return redirect(url_for('camps.camp_view', id=camp_id))

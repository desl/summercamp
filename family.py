"""
Family management blueprint.

Handles CRUD operations for Parents, Kids, and Trips.

Routes:
  - GET/POST /parents - list and create parents
  - GET/PUT/DELETE /parents/<id> - view, update, delete parent
  - GET/POST /kids - list and create kids
  - GET/PUT/DELETE /kids/<id> - view, update, delete kid
  - GET/POST /trips - list and create trips
  - GET/PUT/DELETE /trips/<id> - view, update, delete trip

Why this module exists:
Parents, Kids, and Trips are the "who" and "when" of the system - they
represent the family members and their schedule constraints. Grouping
these together makes sense because they're all about family logistics.
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
    entities_to_dict_list,
    # Kid access functions (multi-parent support)
    create_kid_access,
    get_kid_access,
    get_accessible_kids,
    has_kid_access,
    is_kid_owner,
    get_kid_with_access_check,
    get_kid_access_list,
    remove_kid_access,
    delete_all_kid_access
)
from schedule import update_week_blocking  # For updating week blocking after trip changes
from datetime import datetime, date

# Create the blueprint
family_bp = Blueprint('family', __name__, url_prefix='/family')


# ============================================================================
# PARENT ROUTES
# ============================================================================

@family_bp.route('/parents')
@login_required
def parents_list():
    """
    List all parents for the current user.

    Why: Shows all parent records so user can manage family members
    who have Google Calendar access.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Query all parents for this user
    parents = query_by_user(client, 'Parent', user['email'], order_by='name')

    return render_template(
        'parents_list.html',
        user=user,
        parents=entities_to_dict_list(parents)
    )


@family_bp.route('/parents/new', methods=['GET', 'POST'])
@login_required
def parent_new():
    """
    Create a new parent record.

    Why: Parents need Google Calendar IDs for booking integration.
    """
    user = get_current_user()

    if request.method == 'POST':
        client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

        # Create the parent entity
        parent = create_entity(
            client,
            'Parent',
            user['email'],
            {
                'name': request.form['name'],
                'email': request.form['email'],
                'google_calendar_id': request.form.get('google_calendar_id', '')
            }
        )

        flash(f"Parent '{request.form['name']}' created successfully!", 'success')
        return redirect(url_for('family.parents_list'))

    # GET request - show the form
    return render_template('parent_form.html', user=user, parent=None)


@family_bp.route('/parents/<id>', methods=['GET'])
@login_required
def parent_view(id):
    """
    View and edit a parent record.

    Why: Users need to update calendar IDs and contact information.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the parent and verify ownership
    parent = get_entity_for_user(client, 'Parent', id, user['email'])

    if not parent:
        flash('Parent not found or access denied.', 'error')
        return redirect(url_for('family.parents_list'))

    return render_template(
        'parent_form.html',
        user=user,
        parent=entity_to_dict(parent)
    )


@family_bp.route('/parents/<id>/update', methods=['POST'])
@login_required
def parent_update(id):
    """
    Update an existing parent record.

    Why: Contact info and calendar IDs change over time.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the parent and verify ownership
    parent = get_entity_for_user(client, 'Parent', id, user['email'])

    if not parent:
        flash('Parent not found or access denied.', 'error')
        return redirect(url_for('family.parents_list'))

    # Update the parent
    update_entity(
        client,
        parent,
        {
            'name': request.form['name'],
            'email': request.form['email'],
            'google_calendar_id': request.form.get('google_calendar_id', '')
        }
    )

    flash(f"Parent '{request.form['name']}' updated successfully!", 'success')
    return redirect(url_for('family.parents_list'))


@family_bp.route('/parents/<id>/delete', methods=['POST'])
@login_required
def parent_delete(id):
    """
    Delete a parent record.

    Why: Remove parents who are no longer involved in camp planning.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the parent and verify ownership
    parent = get_entity_for_user(client, 'Parent', id, user['email'])

    if not parent:
        flash('Parent not found or access denied.', 'error')
        return redirect(url_for('family.parents_list'))

    name = parent['name']
    delete_entity(client, parent)

    flash(f"Parent '{name}' deleted successfully.", 'success')
    return redirect(url_for('family.parents_list'))


# ============================================================================
# KID ROUTES
# ============================================================================

@family_bp.route('/kids')
@login_required
def kids_list():
    """
    List all kids the current user has access to (owned + shared).

    Why: Shows all children and their school dates, which are critical
    for calculating summer weeks. Includes kids shared by co-parents.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get all kids this user has access to (owned + shared)
    kids = get_accessible_kids(client, user['email'], order_by='name')

    # Build list with ownership info for each kid
    kids_with_info = []
    for kid in kids:
        kid_dict = entity_to_dict(kid)
        kid_id = kid.key.name

        # Check if user is owner or shared
        access = get_kid_access(client, kid_id, user['email'])
        if access:
            kid_dict['is_owner'] = access.get('role') == 'owner'
            kid_dict['access_role'] = access.get('role')
        else:
            # Fallback for legacy kids (pre-migration)
            kid_dict['is_owner'] = kid.get('user_email') == user['email']
            kid_dict['access_role'] = 'owner' if kid_dict['is_owner'] else 'shared'

        # Get sharing info for owned kids
        if kid_dict['is_owner']:
            access_list = get_kid_access_list(client, kid_id)
            shared_with = [a.get('user_email') for a in access_list
                         if a.get('role') == 'shared']
            kid_dict['shared_with'] = shared_with
        else:
            # For shared kids, show who owns them
            kid_dict['owner_email'] = kid.get('user_email')

        kids_with_info.append(kid_dict)

    return render_template(
        'kids_list.html',
        user=user,
        kids=kids_with_info
    )


@family_bp.route('/kids/new', methods=['GET', 'POST'])
@login_required
def kid_new():
    """
    Create a new kid record.

    Why: Each kid needs school dates to calculate summer weeks.
    Also creates a KidAccess record marking the creator as owner.
    """
    user = get_current_user()

    if request.method == 'POST':
        client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

        # Parse the dates (keep as datetime for Datastore compatibility)
        birthday = datetime.strptime(request.form['birthday'], '%Y-%m-%d')
        last_day_of_school = datetime.strptime(request.form['last_day_of_school'], '%Y-%m-%d')
        first_day_of_school = datetime.strptime(request.form['first_day_of_school'], '%Y-%m-%d')

        # Parse friends (comma-separated)
        friends_str = request.form.get('friends', '')
        friends = [f.strip() for f in friends_str.split(',') if f.strip()]

        # Create the kid entity
        kid = create_entity(
            client,
            'Kid',
            user['email'],
            {
                'name': request.form['name'],
                'birthday': birthday,
                'grade': int(request.form['grade']),
                'last_day_of_school': last_day_of_school,
                'first_day_of_school': first_day_of_school,
                'friends': friends
            }
        )

        # Create owner KidAccess record for multi-parent support
        create_kid_access(
            client,
            kid_id=kid.key.name,
            user_email=user['email'],
            role='owner',
            granted_by=user['email']
        )

        flash(f"Kid '{request.form['name']}' created successfully!", 'success')
        return redirect(url_for('family.kids_list'))

    # GET request - show the form
    return render_template('kid_form.html', user=user, kid=None)


@family_bp.route('/kids/<id>', methods=['GET'])
@login_required
def kid_view(id):
    """
    View and edit a kid record.

    Why: School dates and grades change each year.
    Users with access (owner or shared) can view and edit.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the kid and verify access (owner or shared)
    kid = get_kid_with_access_check(client, id, user['email'])

    if not kid:
        flash('Kid not found or access denied.', 'error')
        return redirect(url_for('family.kids_list'))

    kid_dict = entity_to_dict(kid)
    kid_dict['is_owner'] = is_kid_owner(client, id, user['email'])

    return render_template(
        'kid_form.html',
        user=user,
        kid=kid_dict
    )


@family_bp.route('/kids/<id>/update', methods=['POST'])
@login_required
def kid_update(id):
    """
    Update an existing kid record.

    Why: Grades and school dates change every year.
    Users with access (owner or shared) can update.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the kid and verify access (owner or shared can edit)
    kid = get_kid_with_access_check(client, id, user['email'])

    if not kid:
        flash('Kid not found or access denied.', 'error')
        return redirect(url_for('family.kids_list'))

    # Parse the dates (keep as datetime for Datastore compatibility)
    birthday = datetime.strptime(request.form['birthday'], '%Y-%m-%d')
    last_day_of_school = datetime.strptime(request.form['last_day_of_school'], '%Y-%m-%d')
    first_day_of_school = datetime.strptime(request.form['first_day_of_school'], '%Y-%m-%d')

    # Parse friends (comma-separated)
    friends_str = request.form.get('friends', '')
    friends = [f.strip() for f in friends_str.split(',') if f.strip()]

    # Update the kid
    update_entity(
        client,
        kid,
        {
            'name': request.form['name'],
            'birthday': birthday,
            'grade': int(request.form['grade']),
            'last_day_of_school': last_day_of_school,
            'first_day_of_school': first_day_of_school,
            'friends': friends
        }
    )

    flash(f"Kid '{request.form['name']}' updated successfully!", 'success')
    return redirect(url_for('family.kids_list'))


@family_bp.route('/kids/<id>/delete', methods=['POST'])
@login_required
def kid_delete(id):
    """
    Delete a kid record.

    Why: Remove kids who are no longer attending summer camp (e.g., graduated).
    Only the owner can delete a kid.

    Note: This should warn if bookings exist for this kid, but that's a
    Phase 2 enhancement.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Verify user is the owner (only owners can delete)
    if not is_kid_owner(client, id, user['email']):
        flash('Only the owner can delete a kid.', 'error')
        return redirect(url_for('family.kids_list'))

    # Get the kid
    kid = get_kid_with_access_check(client, id, user['email'])

    if not kid:
        flash('Kid not found or access denied.', 'error')
        return redirect(url_for('family.kids_list'))

    name = kid['name']

    # Delete all KidAccess records for this kid
    delete_all_kid_access(client, id)

    # Delete the kid entity
    delete_entity(client, kid)

    flash(f"Kid '{name}' deleted successfully.", 'success')
    return redirect(url_for('family.kids_list'))


# ============================================================================
# KID SHARING ROUTES (Multi-Parent Support)
# ============================================================================

@family_bp.route('/kids/<id>/sharing', methods=['GET'])
@login_required
def kid_sharing(id):
    """
    View and manage who has access to a kid.

    Why: Allows owners to see and manage co-parents who can access this kid.
    Only the owner can manage sharing.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Verify user is the owner
    if not is_kid_owner(client, id, user['email']):
        flash('Only the owner can manage sharing.', 'error')
        return redirect(url_for('family.kids_list'))

    # Get the kid
    kid = get_kid_with_access_check(client, id, user['email'])
    if not kid:
        flash('Kid not found.', 'error')
        return redirect(url_for('family.kids_list'))

    # Get all access records for this kid
    access_list = get_kid_access_list(client, id)

    # Separate owner and shared access
    shared_users = []
    for access in access_list:
        if access.get('role') == 'shared':
            shared_users.append({
                'email': access.get('user_email'),
                'granted_by': access.get('granted_by'),
                'created_at': access.get('created_at')
            })

    return render_template(
        'kid_sharing.html',
        user=user,
        kid=entity_to_dict(kid),
        shared_users=shared_users
    )


@family_bp.route('/kids/<id>/sharing', methods=['POST'])
@login_required
def kid_sharing_add(id):
    """
    Add a co-parent to a kid.

    Why: Allows owners to share access with other caregivers.
    Access is granted immediately (no invitation acceptance required for now).
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Verify user is the owner
    if not is_kid_owner(client, id, user['email']):
        flash('Only the owner can add co-parents.', 'error')
        return redirect(url_for('family.kids_list'))

    # Get the kid
    kid = get_kid_with_access_check(client, id, user['email'])
    if not kid:
        flash('Kid not found.', 'error')
        return redirect(url_for('family.kids_list'))

    # Get the email to share with
    share_email = request.form.get('email', '').strip().lower()
    if not share_email:
        flash('Please enter an email address.', 'error')
        return redirect(url_for('family.kid_sharing', id=id))

    # Check if already shared
    existing = get_kid_access(client, id, share_email)
    if existing:
        flash(f'{share_email} already has access to this kid.', 'error')
        return redirect(url_for('family.kid_sharing', id=id))

    # Can't share with yourself
    if share_email == user['email']:
        flash("You can't share with yourself.", 'error')
        return redirect(url_for('family.kid_sharing', id=id))

    # Create the shared access record
    create_kid_access(
        client,
        kid_id=id,
        user_email=share_email,
        role='shared',
        granted_by=user['email']
    )

    flash(f"Access granted to {share_email}.", 'success')
    return redirect(url_for('family.kid_sharing', id=id))


@family_bp.route('/kids/<id>/sharing/<email>', methods=['POST'])
@login_required
def kid_sharing_remove(id, email):
    """
    Remove a co-parent's access to a kid.

    Why: Allows owners to revoke access when needed.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Verify user is the owner
    if not is_kid_owner(client, id, user['email']):
        flash('Only the owner can remove co-parents.', 'error')
        return redirect(url_for('family.kids_list'))

    # Get the kid (for the name in the message)
    kid = get_kid_with_access_check(client, id, user['email'])
    if not kid:
        flash('Kid not found.', 'error')
        return redirect(url_for('family.kids_list'))

    # Can't remove owner's access
    if email == user['email']:
        flash("You can't remove your own access.", 'error')
        return redirect(url_for('family.kid_sharing', id=id))

    # Remove the access
    removed = remove_kid_access(client, id, email)
    if removed:
        flash(f"Access revoked for {email}.", 'success')
    else:
        flash(f"{email} doesn't have access to this kid.", 'error')

    return redirect(url_for('family.kid_sharing', id=id))


# ============================================================================
# TRIP ROUTES
# ============================================================================

@family_bp.route('/trips')
@login_required
def trips_list():
    """
    List all trips for the current user.

    Why: Shows family trips that block camp weeks.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Query all trips for this user, ordered by start date
    trips = query_by_user(client, 'Trip', user['email'], order_by='start_date')

    return render_template(
        'trips_list.html',
        user=user,
        trips=entities_to_dict_list(trips)
    )


@family_bp.route('/trips/new', methods=['GET', 'POST'])
@login_required
def trip_new():
    """
    Create a new trip record.

    Why: Trips block out weeks when camps aren't needed.

    Note: Week blocking logic will be added in Phase 2.
    """
    user = get_current_user()

    if request.method == 'POST':
        client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

        # Parse the dates (keep as datetime for Datastore compatibility)
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')

        # Validate dates
        if end_date < start_date:
            flash('End date must be after start date.', 'error')
            return redirect(url_for('family.trip_new'))

        # Create the trip entity
        trip = create_entity(
            client,
            'Trip',
            user['email'],
            {
                'name': request.form['name'],
                'start_date': start_date,
                'end_date': end_date
            }
        )

        # Recalculate weeks to update blocked status
        update_week_blocking(client, user['email'])

        flash(f"Trip '{request.form['name']}' created successfully!", 'success')
        return redirect(url_for('family.trips_list'))

    # GET request - show the form
    return render_template('trip_form.html', user=user, trip=None)


@family_bp.route('/trips/<id>', methods=['GET'])
@login_required
def trip_view(id):
    """
    View and edit a trip record.

    Why: Trip dates might change.
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the trip and verify ownership
    trip = get_entity_for_user(client, 'Trip', id, user['email'])

    if not trip:
        flash('Trip not found or access denied.', 'error')
        return redirect(url_for('family.trips_list'))

    return render_template(
        'trip_form.html',
        user=user,
        trip=entity_to_dict(trip)
    )


@family_bp.route('/trips/<id>/update', methods=['POST'])
@login_required
def trip_update(id):
    """
    Update an existing trip record.

    Why: Trip dates and names change.

    Note: Updating a trip should trigger week recalculation (Phase 2).
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the trip and verify ownership
    trip = get_entity_for_user(client, 'Trip', id, user['email'])

    if not trip:
        flash('Trip not found or access denied.', 'error')
        return redirect(url_for('family.trips_list'))

    # Parse the dates (keep as datetime for Datastore compatibility)
    start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
    end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')

    # Validate dates
    if end_date < start_date:
        flash('End date must be after start date.', 'error')
        return redirect(url_for('family.trip_view', id=id))

    # Update the trip
    update_entity(
        client,
        trip,
        {
            'name': request.form['name'],
            'start_date': start_date,
            'end_date': end_date
        }
    )

    # Recalculate weeks to update blocked status
    update_week_blocking(client, user['email'])

    flash(f"Trip '{request.form['name']}' updated successfully!", 'success')
    return redirect(url_for('family.trips_list'))


@family_bp.route('/trips/<id>/delete', methods=['POST'])
@login_required
def trip_delete(id):
    """
    Delete a trip record.

    Why: Cancelled trips should be removed.

    Note: Deleting a trip should trigger week recalculation (Phase 2).
    """
    user = get_current_user()
    client = get_datastore_client(current_app.config['GCP_PROJECT_ID'])

    # Get the trip and verify ownership
    trip = get_entity_for_user(client, 'Trip', id, user['email'])

    if not trip:
        flash('Trip not found or access denied.', 'error')
        return redirect(url_for('family.trips_list'))

    name = trip['name']
    delete_entity(client, trip)

    # Recalculate weeks to update blocked status
    update_week_blocking(client, user['email'])

    flash(f"Trip '{name}' deleted successfully.", 'success')
    return redirect(url_for('family.trips_list'))

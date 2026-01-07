/**
 * AI Parser JavaScript
 *
 * Handles auto-filling session form data from camp website URLs using Gemini AI.
 */

// Global state for managing multiple sessions
let extractedSessions = [];
let currentSessionIndex = 0;
let selectedSessionIndices = new Set();

/**
 * Parse a URL and auto-fill the form with extracted data.
 */
async function parseUrl() {
    const urlInput = document.getElementById('parse_url_input');
    const parseButton = document.getElementById('parse_url_button');
    const statusDiv = document.getElementById('parse_status');
    const warningsDiv = document.getElementById('parse_warnings');

    const url = urlInput.value.trim();

    if (!url) {
        showStatus('Please enter a URL', 'error');
        return;
    }

    // Disable button and show loading state
    parseButton.disabled = true;
    parseButton.textContent = 'Parsing...';
    showStatus('Fetching and analyzing website content... This may take 10-30 seconds.', 'info');
    warningsDiv.innerHTML = '';

    try {
        // Call the parse API
        const response = await fetch('/camps/parse-url', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url: url })
        });

        const result = await response.json();

        if (!result.success) {
            showStatus('Error: ' + result.error, 'error');
            return;
        }

        // Store all extracted sessions
        extractedSessions = result.data.sessions || [];
        currentSessionIndex = 0;
        selectedSessionIndices = new Set();

        if (extractedSessions.length === 0) {
            showStatus('No sessions found on the page. Try a different URL or enter data manually.', 'error');
            return;
        }

        // Show session selector if multiple sessions found
        if (extractedSessions.length > 1) {
            // Pre-select all sessions by default
            extractedSessions.forEach((_, index) => selectedSessionIndices.add(index));
            showSessionSelector(extractedSessions);
        }

        // Fill form with first session
        fillFormWithData(result.data, 0);

        // Show staleness warnings if any
        if (result.staleness && result.staleness.has_warnings) {
            showStalenessWarnings(result.staleness);
        }

        const sessionText = extractedSessions.length > 1
            ? `Found ${extractedSessions.length} sessions! Select which one to add below.`
            : '';

        showStatus(
            `Successfully parsed ${result.pages_analyzed} page(s)! ${sessionText} ` +
            `Review the pre-filled data and make any necessary adjustments.`,
            'success'
        );

    } catch (error) {
        showStatus('Error parsing URL: ' + error.message, 'error');
    } finally {
        // Re-enable button
        parseButton.disabled = false;
        parseButton.textContent = '🤖 Auto-Fill from URL';
    }
}

/**
 * Show session selector UI for choosing which sessions to add.
 */
function showSessionSelector(sessions) {
    const warningsDiv = document.getElementById('parse_warnings');

    let html = '<div id="session_selector" style="background-color: #e7f3ff; border: 2px solid #2196F3; border-radius: 6px; padding: 20px; margin: 15px 0;">';
    html += `<h4 style="margin-top: 0; color: #1976D2;">📋 Found ${sessions.length} Sessions</h4>`;

    // Bulk action buttons
    html += '<div style="display: flex; gap: 10px; margin: 15px 0; flex-wrap: wrap;">';
    html += `<button type="button" onclick="addAllSessions()" class="btn btn-primary" style="background-color: #4CAF50; border: none; padding: 10px 20px; font-weight: 600;">
        ✓ Add All ${sessions.length} Sessions
    </button>`;
    html += `<button type="button" onclick="addSelectedSessions()" class="btn btn-primary" style="padding: 10px 20px; font-weight: 600;">
        Add Selected (<span id="selected_count">${selectedSessionIndices.size}</span>)
    </button>`;
    html += '<button type="button" onclick="selectAllSessions()" class="btn btn-secondary" style="padding: 10px 20px;">Select All</button>';
    html += '<button type="button" onclick="deselectAllSessions()" class="btn btn-secondary" style="padding: 10px 20px;">Deselect All</button>';
    html += '</div>';

    html += '<p style="color: #424242; margin: 10px 0;">Check sessions to add, or click on a session to preview it in the form below:</p>';
    html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; margin-top: 15px;">';

    sessions.forEach((session, index) => {
        const isActive = index === currentSessionIndex;
        const isSelected = selectedSessionIndices.has(index);
        html += `<div style="border: 2px solid ${isActive ? '#2196F3' : '#ccc'};
                         background-color: ${isActive ? '#e3f2fd' : 'white'};
                         border-radius: 4px; padding: 10px; position: relative;">
            <label style="display: flex; align-items: start; cursor: pointer; gap: 10px;">
                <input type="checkbox"
                       id="session_${index}"
                       ${isSelected ? 'checked' : ''}
                       onchange="toggleSession(${index})"
                       style="margin-top: 4px; width: 18px; height: 18px; cursor: pointer;">
                <div style="flex: 1;" onclick="loadSession(${index}); event.stopPropagation();" style="cursor: pointer;">
                    <div style="font-size: 14px; font-weight: bold; color: #424242;">${session.name || `Session ${index + 1}`}</div>
                    <div style="font-size: 12px; margin-top: 4px; color: #666;">
                        ${session.session_start_date || 'No date'}<br>
                        ${session.cost ? '$' + session.cost : 'No cost info'}
                    </div>
                </div>
            </label>
        </div>`;
    });

    html += '</div>';
    html += '<p style="color: #666; font-size: 13px; margin: 15px 0 0 0;">💡 Tip: Click "Add All Sessions" to create all sessions at once, or select specific ones and click "Add Selected".</p>';
    html += '</div>';

    // Insert before warnings
    const existingSelector = document.getElementById('session_selector');
    if (existingSelector) {
        existingSelector.outerHTML = html;
    } else if (warningsDiv.innerHTML) {
        warningsDiv.innerHTML = html + warningsDiv.innerHTML;
    } else {
        warningsDiv.innerHTML = html;
    }
}

/**
 * Load a specific session into the form.
 */
function loadSession(index) {
    currentSessionIndex = index;

    // Update selector UI
    const data = { sessions: extractedSessions };
    showSessionSelector(extractedSessions);

    // Fill form
    fillFormWithData(data, index);

    // Scroll to form
    document.getElementById('name').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/**
 * Fill the session form with extracted data.
 */
function fillFormWithData(data, sessionIndex = 0) {
    const session = data.sessions && data.sessions.length > sessionIndex ? data.sessions[sessionIndex] : {};

    // Session name
    if (session.name) {
        setValue('name', session.name);
    }

    // Session URL
    if (session.url) {
        setValue('url', session.url);
    }

    // Duration (default to 1 if not specified)
    if (session.duration_weeks) {
        setValue('duration_weeks', session.duration_weeks);
    }

    // Dates
    if (session.session_start_date) {
        setValue('session_start_date', session.session_start_date);
    }
    if (session.session_end_date) {
        setValue('session_end_date', session.session_end_date);
    }

    // Eligibility
    if (session.age_min !== null && session.age_min !== undefined) {
        setValue('age_min', session.age_min);
    }
    if (session.age_max !== null && session.age_max !== undefined) {
        setValue('age_max', session.age_max);
    }
    if (session.grade_min !== null && session.grade_min !== undefined) {
        setValue('grade_min', session.grade_min);
    }
    if (session.grade_max !== null && session.grade_max !== undefined) {
        setValue('grade_max', session.grade_max);
    }

    // Times
    if (session.start_time) {
        setValue('start_time', session.start_time);
    }
    if (session.end_time) {
        setValue('end_time', session.end_time);
    }
    if (session.dropoff_window_start) {
        setValue('dropoff_window_start', session.dropoff_window_start);
    }
    if (session.dropoff_window_end) {
        setValue('dropoff_window_end', session.dropoff_window_end);
    }
    if (session.pickup_window_start) {
        setValue('pickup_window_start', session.pickup_window_start);
    }
    if (session.pickup_window_end) {
        setValue('pickup_window_end', session.pickup_window_end);
    }

    // Cost
    if (session.cost !== null && session.cost !== undefined) {
        setValue('cost', session.cost);
    }

    // Early care
    if (session.early_care_available) {
        setChecked('early_care_available', session.early_care_available);
    }
    if (session.early_care_cost !== null && session.early_care_cost !== undefined) {
        setValue('early_care_cost', session.early_care_cost);
    }

    // Late care
    if (session.late_care_available) {
        setChecked('late_care_available', session.late_care_available);
    }
    if (session.late_care_cost !== null && session.late_care_cost !== undefined) {
        setValue('late_care_cost', session.late_care_cost);
    }

    // Registration date
    if (session.registration_open_date) {
        setValue('registration_open_date', session.registration_open_date);
    }
}

/**
 * Show staleness warnings to the user.
 */
function showStalenessWarnings(staleness) {
    const warningsDiv = document.getElementById('parse_warnings');

    let html = '<div style="background-color: #fff3cd; border: 2px solid #ffc107; border-radius: 6px; padding: 15px; margin: 15px 0;">';
    html += '<h4 style="margin-top: 0; color: #856404;">⚠️ Potential Data Issues Detected</h4>';
    html += `<p style="color: #856404; margin: 5px 0;">The AI detected ${staleness.warning_count} potential issue(s) with the extracted data:</p>`;

    staleness.sessions.forEach(session => {
        html += `<div style="margin: 10px 0; padding: 10px; background-color: white; border-radius: 4px;">`;
        html += `<strong>${session.session_name}</strong>`;
        html += '<ul style="margin: 5px 0; padding-left: 20px;">';

        session.warnings.forEach(warning => {
            const icon = warning.confidence === 'high' ? '🔴' :
                        warning.confidence === 'medium' ? '🟡' : '🟢';
            html += `<li style="margin: 5px 0;">`;
            html += `${icon} <strong>${warning.field}:</strong> ${warning.issue}<br>`;
            html += `<span style="color: #6c757d; font-size: 13px;">💡 ${warning.suggestion}</span>`;
            html += `</li>`;
        });

        html += '</ul></div>';
    });

    html += '<p style="color: #856404; margin: 10px 0 0 0; font-size: 14px;">Please review and update the dates below as needed.</p>';
    html += '</div>';

    warningsDiv.innerHTML = html;
}

/**
 * Show status message to user.
 */
function showStatus(message, type) {
    const statusDiv = document.getElementById('parse_status');
    const className = type === 'error' ? 'flash error' :
                     type === 'success' ? 'flash success' :
                     'flash info';
    statusDiv.innerHTML = `<div class="${className}">${message}</div>`;
}

/**
 * Helper to set input value.
 */
function setValue(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.value = value;
    }
}

/**
 * Helper to set checkbox state.
 */
function setChecked(id, checked) {
    const element = document.getElementById(id);
    if (element) {
        element.checked = checked;
    }
}

/**
 * Toggle selection of a session.
 */
function toggleSession(index) {
    if (selectedSessionIndices.has(index)) {
        selectedSessionIndices.delete(index);
    } else {
        selectedSessionIndices.add(index);
    }
    updateSelectedCount();
}

/**
 * Select all sessions.
 */
function selectAllSessions() {
    extractedSessions.forEach((_, index) => selectedSessionIndices.add(index));
    showSessionSelector(extractedSessions);
}

/**
 * Deselect all sessions.
 */
function deselectAllSessions() {
    selectedSessionIndices.clear();
    showSessionSelector(extractedSessions);
}

/**
 * Update the selected count display.
 */
function updateSelectedCount() {
    const countElement = document.getElementById('selected_count');
    if (countElement) {
        countElement.textContent = selectedSessionIndices.size;
    }
}

/**
 * Add all sessions at once.
 */
async function addAllSessions() {
    const allIndices = extractedSessions.map((_, index) => index);
    await bulkAddSessions(allIndices);
}

/**
 * Add selected sessions.
 */
async function addSelectedSessions() {
    if (selectedSessionIndices.size === 0) {
        alert('Please select at least one session to add.');
        return;
    }
    const indices = Array.from(selectedSessionIndices);
    await bulkAddSessions(indices);
}

/**
 * Bulk add sessions to the database.
 */
async function bulkAddSessions(indices) {
    const statusDiv = document.getElementById('parse_status');
    const addButtons = document.querySelectorAll('button[onclick^="addAllSessions"], button[onclick^="addSelectedSessions"]');

    // Disable buttons
    addButtons.forEach(btn => btn.disabled = true);

    showStatus(`Creating ${indices.length} session(s)... Please wait.`, 'info');

    try {
        // Get camp ID from the URL (we're on /camps/{camp_id}/sessions/new)
        const pathParts = window.location.pathname.split('/');
        const campId = pathParts[2]; // /camps/{camp_id}/sessions/new

        // Prepare sessions data
        const sessionsToAdd = indices.map(i => extractedSessions[i]);

        // Call bulk creation endpoint
        const response = await fetch(`/camps/${campId}/sessions/bulk`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ sessions: sessionsToAdd })
        });

        const result = await response.json();

        if (!result.success) {
            showStatus('Error: ' + result.error, 'error');
            return;
        }

        showStatus(
            `Successfully created ${result.created} session(s)! Redirecting to camp view...`,
            'success'
        );

        // Redirect to camp view after 2 seconds
        setTimeout(() => {
            window.location.href = `/camps/${campId}`;
        }, 2000);

    } catch (error) {
        showStatus('Error creating sessions: ' + error.message, 'error');
    } finally {
        // Re-enable buttons
        addButtons.forEach(btn => btn.disabled = false);
    }
}

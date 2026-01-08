"""
AI-powered parser for extracting camp and session data from URLs.

This module uses Google Gemini 2.5 Flash to intelligently parse camp website content
and extract structured data for camps and sessions.

Features:
- Multi-level link following (up to 2 levels deep)
- Stale data detection (wrong years, past dates, Monday misalignment)
- Structured JSON output for pre-populating forms
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
import json
import re
import math


def calculate_session_durations(extracted_data):
    """
    Calculate duration_weeks from session start and end dates.

    Rules:
    - Camps are 5 days per week (Mon-Fri typically)
    - If a camp starts Monday and ends Friday, don't count weekends
    - Round up to integer weeks
    - Examples: 3 days = 1 week, 6 days = 2 weeks

    Args:
        extracted_data: Dict with sessions array
    """
    sessions = extracted_data.get('sessions', [])

    for session in sessions:
        start_date_str = session.get('session_start_date')
        end_date_str = session.get('session_end_date')

        if not start_date_str or not end_date_str:
            # If no dates, leave duration as-is or default to 1
            if 'duration_weeks' not in session or session['duration_weeks'] is None:
                session['duration_weeks'] = 1
            continue

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

            # Calculate total days (inclusive)
            total_days = (end_date - start_date).days + 1

            # Check if it's a Monday-Friday camp (starts Monday, ends Friday)
            # Monday = 0, Friday = 4
            starts_monday = start_date.weekday() == 0
            ends_friday = end_date.weekday() == 4

            if starts_monday and ends_friday and total_days >= 5:
                # This is a Monday-Friday camp spanning one or more weeks
                # Don't count weekends
                # Calculate number of full weeks
                full_weeks = total_days // 7
                remaining_days = total_days % 7

                # Each full week has 5 camp days
                # Remaining days (if any) are weekdays
                camp_days = full_weeks * 5 + min(remaining_days, 5)
            else:
                # For camps that don't follow Mon-Fri pattern, count all days
                camp_days = total_days

            # Convert camp days to weeks (5 days = 1 week)
            # Round up: 3 days = 1 week, 6 days = 2 weeks
            duration_weeks = math.ceil(camp_days / 5)

            session['duration_weeks'] = max(1, duration_weeks)  # At least 1 week

            print(f"Calculated duration for {session.get('name', 'session')}: {total_days} total days -> {camp_days} camp days -> {duration_weeks} weeks")

        except (ValueError, TypeError) as e:
            # If date parsing fails, default to 1 week
            print(f"Error calculating duration for session: {e}")
            if 'duration_weeks' not in session or session['duration_weeks'] is None:
                session['duration_weeks'] = 1


def parse_session_url(url, project_id, region, model_name):
    """
    Main entry point for parsing a camp session URL.

    Args:
        url: The URL to parse
        project_id: GCP project ID
        region: GCP region for Vertex AI
        model_name: Gemini model name

    Returns:
        dict: Parsed data with camp/session info and staleness warnings
    """
    try:
        # Fetch and follow links up to 2 levels deep
        pages = fetch_and_follow_links(url, max_depth=2)

        print(f"Fetched {len(pages)} page(s) for URL: {url}")
        if len(pages) == 0:
            print(f"WARNING: No pages fetched for URL: {url}")

        # Prioritize the main page (depth 0) - send up to 300K of it
        # Then add additional pages if there's room (max 400K total for faster processing)
        main_page = next((p for p in pages if p['depth'] == 0), None)
        if main_page:
            # Take more content from the main page
            combined_html = main_page['html'][:300000]
            print(f"Using main page HTML (up to 300K): {len(combined_html)} characters")

            # Add other pages if we have room
            for page in pages:
                if page['depth'] > 0 and len(combined_html) < 400000:
                    remaining_space = 400000 - len(combined_html)
                    combined_html += "\n\n" + page['html'][:remaining_space]
        else:
            # Fallback to combining all pages
            combined_html = "\n\n".join([p['html'] for p in pages])[:400000]

        print(f"Final combined HTML length: {len(combined_html)} characters")

        # Call Gemini to extract structured data
        extracted_data = call_gemini_api(
            combined_html,
            url,
            project_id,
            region,
            model_name
        )

        # Calculate duration_weeks from dates for each session
        calculate_session_durations(extracted_data)

        # Detect stale data
        staleness_info = detect_stale_data(extracted_data)

        # Combine results
        return {
            'success': True,
            'data': extracted_data,
            'staleness': staleness_info,
            'pages_analyzed': len(pages)
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def fetch_and_follow_links(base_url, max_depth=2):
    """
    Crawl camp website up to 2 levels deep to find session information.

    Args:
        base_url: Starting URL
        max_depth: Maximum depth to follow links (default 2)

    Returns:
        list: List of dicts with url, html, depth
    """
    pages = []
    visited = set()
    to_visit = [(base_url, 0)]

    # Keywords that suggest relevant links
    relevant_keywords = [
        'session', 'schedule', 'registration', 'sign up', 'signup',
        'enroll', 'camp', 'program', 'pricing', 'cost', 'dates',
        'summer', 'week', 'age', 'grade'
    ]

    while to_visit and len(pages) < 10:  # Limit to 10 pages max
        url, depth = to_visit.pop(0)

        if url in visited or depth > max_depth:
            continue

        visited.add(url)

        try:
            # Fetch the page
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; SummerCampBot/1.0)'
            })
            response.raise_for_status()

            html = response.text

            # Don't clean HTML - send raw HTML to Gemini
            # Gemini is good at filtering out scripts/styles on its own
            pages.append({
                'url': url,
                'html': html,
                'depth': depth
            })

            # If we haven't reached max depth, look for relevant links
            if depth < max_depth:
                soup = BeautifulSoup(html, 'html.parser')
                links = identify_relevant_links(soup, url, relevant_keywords)

                # Add new links to visit
                for link in links[:5]:  # Limit to 5 links per page
                    if link not in visited:
                        to_visit.append((link, depth + 1))

        except Exception as e:
            print(f"Error fetching {url}: {e}")
            continue

    return pages


def clean_html_for_ai(html):
    """
    Clean HTML to remove scripts and styles while preserving content structure.

    This helps Gemini focus on the actual content rather than JavaScript code,
    while keeping tables, lists, and other structural elements intact.

    Args:
        html: Raw HTML content

    Returns:
        str: Cleaned HTML with scripts/styles removed but structure preserved
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Only remove script and style tags - keep everything else for structure
    for element in soup(['script', 'style']):
        element.decompose()

    # Get the cleaned HTML
    cleaned = str(soup)

    return cleaned


def identify_relevant_links(soup, base_url, keywords):
    """
    Find links that are likely to contain session/schedule/pricing information.

    Args:
        soup: BeautifulSoup object
        base_url: Base URL for resolving relative links
        keywords: List of keywords to look for

    Returns:
        list: List of relevant URLs
    """
    relevant_links = []
    base_domain = urlparse(base_url).netloc

    for link_tag in soup.find_all('a', href=True):
        href = link_tag['href']
        link_text = link_tag.get_text().lower()

        # Resolve relative URLs
        absolute_url = urljoin(base_url, href)

        # Only follow links on the same domain
        if urlparse(absolute_url).netloc != base_domain:
            continue

        # Check if link text contains relevant keywords
        if any(keyword in link_text for keyword in keywords):
            relevant_links.append(absolute_url)
        # Also check href for keywords
        elif any(keyword in href.lower() for keyword in keywords):
            relevant_links.append(absolute_url)

    # Remove duplicates while preserving order
    seen = set()
    unique_links = []
    for link in relevant_links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)

    return unique_links


def call_gemini_api(html, original_url, project_id, region, model_name):
    """
    Call Vertex AI Gemini to extract structured data from HTML.

    Args:
        html: HTML content to parse
        original_url: The original URL (for context)
        project_id: GCP project ID
        region: GCP region
        model_name: Gemini model name

    Returns:
        dict: Extracted structured data
    """
    # Initialize Vertex AI
    vertexai.init(project=project_id, location=region)

    # Create the model
    model = GenerativeModel(model_name)

    # Get current year for context
    current_year = datetime.now().year

    # Create the extraction prompt
    prompt = f"""You are parsing a summer camp website to extract camp and session information.

URL: {original_url}
CURRENT YEAR: {current_year}

CRITICAL INSTRUCTIONS:
1. Extract ALL sessions from the page - if there's a table or list with multiple weeks/sessions, extract EVERY row
2. Pay careful attention to the year in dates - we are currently in {current_year}, so summer camp dates should be in {current_year} or later
3. Look for tables with columns like "Session", "Dates", "Days", "Time", "Price" and extract each row as a separate session
4. If only the current year ({current_year}) or future years appear in dates, use those years exactly as shown

Please extract the following information from the HTML content and return it as valid JSON.

For the CAMP information:
- name: Camp organization name
- website: Main camp website URL
- phone: Contact phone number (if available)
- email: Contact email (if available)

For SESSIONS (IMPORTANT: Extract ALL sessions found on the page - there are often 5-15 sessions listed):
- name: Session name (e.g., "Week 1", "Week 1 - LEGO Robotics", "Sailing Camp Week 1")
- age_min: Minimum age (integer, or null)
- age_max: Maximum age (integer, or null)
- grade_min: Minimum grade (0-12, where 0=Kindergarten, or null)
- grade_max: Maximum grade (0-12, where 0=Kindergarten, or null)
- session_start_date: Start date in YYYY-MM-DD format (BE CAREFUL WITH YEAR - use {current_year} or later)
- session_end_date: End date in YYYY-MM-DD format (BE CAREFUL WITH YEAR - use {current_year} or later)
- start_time: Daily start time in HH:MM format 24-hour (or empty string)
- end_time: Daily end time in HH:MM format 24-hour (or empty string)
- cost: Base cost in dollars as a number (e.g., 750 not "$750", or null)
- early_care_available: Boolean
- early_care_cost: Early care cost (number, or null)
- late_care_available: Boolean
- late_care_cost: Late care cost (number, or null)
- registration_open_date: When registration opens, in YYYY-MM-DD format (or null)
- url: Direct URL to this session's page (or empty string)

Return ONLY valid JSON in this exact format (CRITICAL: ensure all commas are correct, no trailing commas):
{{
  "camp": {{
    "name": "Berkeley Rec & Well",
    "website": "https://recwell.berkeley.edu",
    "phone": "555-1234",
    "email": "info@example.com"
  }},
  "sessions": [
    {{
      "name": "Week 1",
      "age_min": 8,
      "age_max": 14,
      "grade_min": null,
      "grade_max": null,
      "session_start_date": "2026-06-08",
      "session_end_date": "2026-06-12",
      "start_time": "09:00",
      "end_time": "16:00",
      "cost": 750,
      "early_care_available": false,
      "early_care_cost": null,
      "late_care_available": false,
      "late_care_cost": null,
      "registration_open_date": null,
      "url": ""
    }}
  ]
}}

CRITICAL JSON REQUIREMENTS:
- All string values must use double quotes
- No trailing commas after the last item in arrays or objects
- Use null (not "null") for null values
- Ensure proper comma placement between all fields

If information is not available, use null for numbers/dates, empty string for text, or false for booleans.
REMEMBER: Extract ALL sessions found on the page, not just the first one!

IMPORTANT: The content below may be in HTML format or plain text format. Look for tables, lists, or any structured data about camp sessions.

Content:
{html}
"""

    # Generate content with JSON mode
    generation_config = GenerationConfig(
        temperature=0.1,  # Low temperature for more consistent output
        max_output_tokens=8192,
    )

    response = model.generate_content(
        prompt,
        generation_config=generation_config
    )

    # Extract JSON from response
    response_text = response.text.strip()

    # Remove markdown code blocks if present
    if '```json' in response_text or '```' in response_text:
        response_text = re.sub(r'^.*?```json?\s*', '', response_text, flags=re.DOTALL)
        response_text = re.sub(r'\s*```.*$', '', response_text, flags=re.DOTALL)

    # Try to find JSON in the response (in case there's explanatory text before/after)
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        response_text = json_match.group(0)

    # Try to fix common JSON errors before parsing
    # Fix: trailing commas before closing braces/brackets
    response_text = re.sub(r',(\s*[}\]])', r'\1', response_text)

    # Fix: missing comma after closing brace/bracket when next line starts with quote
    response_text = re.sub(r'(\}|\])\s*\n\s*"', r'\1,\n  "', response_text)

    # Parse JSON
    try:
        data = json.loads(response_text)
        print(f"Successfully parsed JSON. Sessions found: {len(data.get('sessions', []))}")
        if len(data.get('sessions', [])) == 0:
            print(f"WARNING: No sessions in response. Full response: {response_text[:1000]}")
        return data
    except json.JSONDecodeError as e:
        # Log more of the response for debugging
        error_pos = e.pos if hasattr(e, 'pos') else 0
        context_start = max(0, error_pos - 200)
        context_end = min(len(response_text), error_pos + 200)
        error_context = response_text[context_start:context_end]

        print(f"JSON parse error at position {error_pos}. Context: {error_context}")
        print(f"First 2000 chars of response: {response_text[:2000]}")
        raise ValueError(f"Gemini returned invalid JSON: {e}\n\nError context: ...{error_context}...")


def detect_stale_data(extracted_data, current_date=None):
    """
    Check for outdated information with confidence scores.

    Args:
        extracted_data: Dict with camp and session data
        current_date: Current date (defaults to today)

    Returns:
        dict: Staleness warnings with confidence levels
    """
    if current_date is None:
        current_date = datetime.now()

    warnings = []

    sessions = extracted_data.get('sessions', [])

    for i, session in enumerate(sessions):
        session_warnings = []

        # Check 1: Year mismatch (high confidence)
        start_date_str = session.get('session_start_date')
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')

                # Check if the year is in the past
                if start_date.year < current_date.year:
                    session_warnings.append({
                        'field': 'session_start_date',
                        'confidence': 'high',
                        'issue': f'Session date is from {start_date.year}, but we are in {current_date.year}',
                        'suggestion': 'Update the year to current year or verify this is correct'
                    })

                # Check 2: Date is in the past (high confidence)
                elif start_date < current_date and (start_date < current_date - timedelta(days=30)):
                    session_warnings.append({
                        'field': 'session_start_date',
                        'confidence': 'high',
                        'issue': f'Session start date ({start_date_str}) is more than 30 days in the past',
                        'suggestion': 'This may be last year\'s schedule. Check for updated dates.'
                    })

                # Check 3: Monday misalignment (medium confidence)
                # Sessions should typically start on Monday
                # Only check if the date is in the current or past year
                elif start_date.year <= current_date.year and start_date.weekday() != 0:  # 0 = Monday
                    # Check if this date WAS a Monday last year
                    last_year_date = start_date.replace(year=start_date.year - 1)
                    if last_year_date.weekday() == 0:
                        session_warnings.append({
                            'field': 'session_start_date',
                            'confidence': 'medium',
                            'issue': f'Session starts on {start_date.strftime("%A")} ({start_date_str}), but this was a Monday in {start_date.year - 1}',
                            'suggestion': f'This may be last year\'s schedule. Consider adjusting to the corresponding Monday in {current_date.year}.'
                        })
                    # Even if not a Monday last year, warn about non-Monday start (low priority)
                    elif start_date.year == current_date.year and start_date > current_date:
                        session_warnings.append({
                            'field': 'session_start_date',
                            'confidence': 'low',
                            'issue': f'Session starts on {start_date.strftime("%A")} instead of Monday',
                            'suggestion': 'Most camps start on Monday. Verify this is correct.'
                        })

            except ValueError:
                pass

        # Check 4: Registration date in the past (high confidence)
        reg_date_str = session.get('registration_open_date')
        if reg_date_str:
            try:
                reg_date = datetime.strptime(reg_date_str, '%Y-%m-%d')
                if reg_date < current_date:
                    session_warnings.append({
                        'field': 'registration_open_date',
                        'confidence': 'high',
                        'issue': f'Registration date ({reg_date_str}) is in the past',
                        'suggestion': 'This may be outdated. Check for current registration dates.'
                    })
            except ValueError:
                pass

        if session_warnings:
            warnings.append({
                'session_index': i,
                'session_name': session.get('name', 'Unnamed session'),
                'warnings': session_warnings
            })

    return {
        'has_warnings': len(warnings) > 0,
        'warning_count': sum(len(w['warnings']) for w in warnings),
        'sessions': warnings
    }

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Summer Camp Organization Tool - a Python/Flask web application to help families manage summer camp planning, registration, and scheduling for multiple children. The app tracks camp ideas, bookings, registration deadlines, and integrates with Google Calendar.

**Key Requirements:**
- Read "Summer Camp Organization Tool.md" for complete specifications
- Code should be maintainable by beginning software engineers - prioritize clarity over performance
- Comments should explain "why", not "what"
- Mobile and desktop browser support required
- Serverless architecture preferred for small user base (1-2 users initially)

## Architecture

**Technology Stack:**
- Backend: Python 3.12 with Flask framework
- Authentication: Google OAuth (federated identity)
- Deployment: Google App Engine Standard Environment (Python 3.12, F1 instance class)
- Calendar Integration: Google Calendar API
- Version Control: Git (local)
- Environments: Dev and Production (separate GCP projects)

**Development Philosophy:**
- Deploy-first approach: Build and deploy to dev environment before local development
- Build order: Hello World → Auth/Identity → App features
- No local laptop execution - develop against deployed environments

## Data Model Entities

The application manages these core entities (see specification for full details):

- **Parents**: Names, email addresses, Google calendars
- **Kids**: Names, birthdays, grades, friends, school dates (last/first day)
- **Weeks**: Auto-generated based on school calendars and summer date ranges
- **Trips**: Family trips that block off camp weeks
- **Camps**: Organizations offering sessions
- **Sessions**: Specific camp offerings with age ranges, weeks, times, costs
- **Bookings**: Track state transitions: ideas → preferred → booked

**Key Business Logic:**
- First week of summer = Monday after last day of school (earliest kid if multiple)
- Sessions can span multiple weeks (2-week sessions are common)
- When a camp is booked for a kid in a week, other ideas for that week should be hidden/grayed out
- Registration deadlines tracked with calendar notifications
- Booked camps added to Google Calendar (separate from registration reminders)

## Deployment

**GCP Projects:**
- **Dev**: `summercamp-dev-202601`
- **Production**: To be created (will follow pattern: `summercamp-prod-YYYYMM`)

**Project URLs:**
- Dev: https://summercamp-dev-202601.uc.r.appspot.com

**Common Commands:**

Deploy to dev:
```bash
gcloud app deploy --project=summercamp-dev-202601
```

View logs:
```bash
gcloud app logs tail -s default --project=summercamp-dev-202601
```

Open app in browser:
```bash
gcloud app browse --project=summercamp-dev-202601
```

List deployed versions:
```bash
gcloud app versions list --project=summercamp-dev-202601
```

Rollback to previous version:
```bash
# First, list versions to find the version ID
gcloud app versions list --project=summercamp-dev-202601
# Then split traffic to route 100% to the desired version
gcloud app services set-traffic default --splits=VERSION_ID=1 --project=summercamp-dev-202601
```

**Note:** There is no local development environment. All development is done by deploying to the dev environment.

## Google Calendar Integration

Two types of calendar entries:
1. Registration reminders (when camp signup opens)
2. Booked camp sessions (actual camp dates/times)

These should go into separate calendars or be clearly distinguished.

## State Management

Camp session states for each kid/week:
- **Ideas**: Potential camps being considered
- **Preferred**: Ordered by preference with registration date warnings
- **Booked**: Confirmed registration (hides other ideas for that week)

Alert users when a primary choice has registration that opens after a secondary choice.

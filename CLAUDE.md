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
- Backend: Python with Flask framework
- Authentication: Google OAuth (federated identity)
- Deployment: Serverless (to be determined - likely AWS Lambda or Google Cloud Functions)
- Calendar Integration: Google Calendar API
- Version Control: GitHub
- Environments: Dev (test) and Production

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

**Environments:**
- `dev` (test environment) - primary development target
- `production` - production environment

The deployment process and commands will be established during initial setup. There is no local development environment.

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

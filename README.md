# Summer Camp Organization Tool

A web application to help families organize summer camp planning, registration, and scheduling for multiple children.

## Features

- **Google OAuth Authentication**: Secure sign-in with email allowlist
- **Multi-child Management**: Track camps and schedules for multiple children
- **Registration Tracking**: Monitor camp registration deadlines
- **Google Calendar Integration**: Automatic calendar entries for camps and registration reminders
- **Booking Workflow**: Track camp ideas, preferences, and confirmed bookings

## Tech Stack

- **Backend**: Python 3.12 + Flask
- **Authentication**: Google OAuth 2.0
- **Database**: Google Cloud Datastore
- **Hosting**: Google App Engine (Standard Environment)
- **Session Storage**: Server-side sessions in Datastore

## Project Structure

```
summercamp/
├── main.py                    # Flask application entry point
├── config.py                  # Configuration settings
├── auth.py                    # OAuth authentication routes
├── session_datastore.py       # Custom Datastore session backend
├── templates/                 # HTML templates
│   ├── index.html            # Dashboard
│   ├── login.html            # Login page
│   └── unauthorized.html     # Access denied page
├── app.yaml.example           # App Engine config template (copy to app.yaml)
├── requirements.txt           # Python dependencies
└── CLAUDE.md                 # AI assistant guidance

**Note**: `app.yaml` is not tracked in git (contains secrets). Use `app.yaml.example` as a template.
```

## Setup and Deployment

### Prerequisites

- Google Cloud Platform account
- gcloud CLI installed and configured
- Python 3.12+

### Environment Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/summercamp.git
   cd summercamp
   ```

2. **Create app.yaml from template**
   ```bash
   cp app.yaml.example app.yaml
   ```

3. **Configure GCP project**
   ```bash
   gcloud config set project YOUR-PROJECT-ID
   ```

4. **Create OAuth 2.0 credentials**
   - Go to [GCP Console > APIs & Services > Credentials](https://console.cloud.google.com/apis/credentials)
   - Create OAuth 2.0 Client ID (Web application)
   - Add authorized redirect URI: `https://YOUR-PROJECT.uc.r.appspot.com/auth/callback`
   - Save Client ID and Client Secret

5. **Configure app.yaml**
   - Generate a secret key:
     ```bash
     python3 -c "import secrets; print(secrets.token_hex(32))"
     ```
   - Edit `app.yaml` and add:
     - Your `SECRET_KEY` (from above)
     - Your `GOOGLE_CLIENT_ID` (from step 4)
     - Your `GOOGLE_CLIENT_SECRET` (from step 4)
     - Your `ALLOWED_EMAILS` (comma-separated list)
     - Update `GOOGLE_CLOUD_PROJECT` if needed

   **Important**: Never commit `app.yaml` to version control!

### Deploy to App Engine

```bash
# Deploy to dev environment
gcloud app deploy --project=summercamp-dev-202601

# View the app
gcloud app browse --project=summercamp-dev-202601

# View logs
gcloud app logs tail -s default --project=summercamp-dev-202601
```

## Development

### Adding Authorized Users

Edit `app.yaml` and update the `ALLOWED_EMAILS` environment variable:

```yaml
env_variables:
  ALLOWED_EMAILS: 'user1@gmail.com,user2@gmail.com'
```

Then redeploy:

```bash
gcloud app deploy --project=summercamp-dev-202601
```

### Local Development

This project uses a deploy-first approach - all development is done by deploying to the dev environment. There is no local development server.

## Security

- OAuth credentials stored as environment variables
- Server-side session storage in Datastore
- Email allowlist for access control
- 24-hour session expiration
- CSRF protection via OAuth state parameter

## License

Private project - not open source.

## Support

For issues or questions, contact the project maintainer.

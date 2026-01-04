# Security

## Important Security Notes

### Secrets in Git History

⚠️ **WARNING**: OAuth credentials were committed to git history in earlier commits (before commit `2bc143a`).

**If you plan to make this repository public**, you must:

1. **Rotate all secrets immediately**:
   - Generate a new OAuth Client ID and Secret in GCP Console
   - Generate a new Flask SECRET_KEY
   - Update your `app.yaml` with new credentials
   - Redeploy the application

2. **Consider rewriting git history** to remove the secrets:
   ```bash
   # This is destructive - backup first!
   git filter-branch --force --index-filter \
     "git rm --cached --ignore-unmatch app.yaml" \
     --prune-empty --tag-name-filter cat -- --all

   # Force push to remote (WARNING: destructive!)
   git push origin --force --all
   ```

   **OR** use BFG Repo-Cleaner:
   ```bash
   brew install bfg  # or download from https://rtyley.github.io/bfg-repo-cleaner/
   bfg --delete-files app.yaml
   git reflog expire --expire=now --all && git gc --prune=now --aggressive
   git push origin --force --all
   ```

### Current Security Setup

✅ **What's protected**:
- `app.yaml` is in `.gitignore` (won't be committed in future)
- `app.yaml.example` is a safe template without credentials
- README warns against committing secrets

❌ **What's NOT protected**:
- Old commits still contain OAuth secrets in git history
- Anyone with access to the git history can see the credentials

### Recommended Actions

**For Private Repository** (Current Setup):
- ✅ Keep repository private
- ✅ Only share with trusted collaborators
- ✅ Limit access to minimum necessary people
- ⚠️ Be aware that secrets exist in git history

**For Public Repository** (If Needed):
- ❌ **DO NOT** make public without rotating all secrets
- ✅ Rotate OAuth credentials in GCP Console
- ✅ Generate new SECRET_KEY
- ✅ Clean git history (see above)
- ✅ Update app.yaml with new credentials
- ✅ Redeploy application

## Best Practices

### Managing Secrets

1. **Never commit secrets to git**
   - Use `app.yaml.example` as template
   - Keep actual `app.yaml` local only
   - `app.yaml` is in `.gitignore`

2. **For production, use Google Secret Manager** (recommended):
   ```python
   from google.cloud import secretmanager

   def get_secret(secret_id):
       client = secretmanager.SecretManagerServiceClient()
       name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
       response = client.access_secret_version(request={"name": name})
       return response.payload.data.decode("UTF-8")

   # In config.py:
   GOOGLE_CLIENT_ID = get_secret("oauth-client-id")
   GOOGLE_CLIENT_SECRET = get_secret("oauth-client-secret")
   ```

3. **Rotate secrets regularly**
   - OAuth credentials: Every 90 days
   - SECRET_KEY: When team members leave
   - After any suspected compromise

### Access Control

1. **Email Allowlist**
   - Only authorized emails can access the application
   - Update via `ALLOWED_EMAILS` in `app.yaml`
   - Redeploy after adding/removing users

2. **Repository Access**
   - Keep repository private
   - Use principle of least privilege
   - Audit collaborators regularly

### Monitoring

1. **Check GCP Console regularly**:
   - [API & Services > Credentials](https://console.cloud.google.com/apis/credentials)
   - Review OAuth consent screen settings
   - Monitor authorized domains

2. **Application logs**:
   ```bash
   gcloud app logs tail -s default --project=summercamp-dev-202601
   ```

## Reporting Security Issues

If you discover a security vulnerability, please:
1. **Do NOT** open a public issue
2. Contact the repository owner directly
3. Provide detailed information about the vulnerability

## Questions?

For security-related questions, contact the project maintainer.

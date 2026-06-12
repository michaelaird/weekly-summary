"""
Run this ONCE locally to generate your Gmail token.json,
then encode it for storage as a GitHub Actions secret.

Prerequisites:
  1. Go to https://console.cloud.google.com
  2. Create a project → Enable Gmail API
  3. OAuth consent screen → External → Add your Gmail as test user
  4. Credentials → Create OAuth client ID → Desktop app → Download JSON
  5. Save it as credentials.json in this folder
  6. Run: python setup_gmail_token.py
"""

import base64
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

def main():
    print("Starting Gmail OAuth flow...")
    print("A browser window will open — sign in and grant Gmail send permission.\n")

    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)

    # Save token.json locally (for reference)
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }

    with open("token.json", "w") as f:
        json.dump(token_data, f, indent=2)

    # Base64-encode for GitHub secret
    encoded = base64.b64encode(json.dumps(token_data).encode()).decode()

    print("\n✅ Token generated successfully!\n")
    print("=" * 60)
    print("Add these as GitHub Actions secrets:")
    print("  Secret name : GOOGLE_TOKEN_JSON")
    print("  Secret value: (the long string below)\n")
    print(encoded)
    print("=" * 60)
    print("\nAlso add:")
    print("  ANTHROPIC_API_KEY  → your Anthropic API key")
    print("  RECIPIENT_EMAIL    → your Gmail address (e.g. you@gmail.com)")

if __name__ == "__main__":
    main()

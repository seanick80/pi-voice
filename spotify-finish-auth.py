#!/opt/pi-voice/.venv/bin/python3
"""Complete the Spotify OAuth token exchange from the saved redirect URL."""
import os
import sys
from os.path import join
from ovos_utils.oauth import OAuthTokenDatabase, OAuthApplicationDatabase
from ovos_utils.xdg_utils import xdg_config_home
from spotipy import SpotifyOAuth

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET env vars (or use .env)")
REDIRECT_URI = "https://127.0.0.1:8888"
SCOPE = "user-library-read streaming playlist-read-private user-top-read user-read-playback-state"
TOKEN_ID = "ocp_spotify"
AUTH_DIR = os.environ.get("SPOTIFY_SKILL_CREDS_DIR", f"{xdg_config_home()}/spotipy")

os.makedirs(AUTH_DIR, exist_ok=True)

am = SpotifyOAuth(
    scope=SCOPE,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    cache_path=join(AUTH_DIR, "token"),
    open_browser=False,
)

with open("/tmp/spotify-redirect-url.txt") as f:
    url = f.read().strip()

code = am.parse_response_code(url)
print(f"Parsed code: {code[:20]}...")

token_info = am.get_access_token(code, as_dict=True)
print(f"Access token obtained, expires at: {token_info.get('expires_at')}")

with OAuthApplicationDatabase() as db:
    db.add_application(
        oauth_service=TOKEN_ID,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        auth_endpoint="https://accounts.spotify.com/authorize?",
        token_endpoint="https://accounts.spotify.com/api/token",
        callback_endpoint=f"http://0.0.0.0:36536/auth/callback/{TOKEN_ID}",
        scope=SCOPE,
    )

with OAuthTokenDatabase() as db:
    db.add_token(TOKEN_ID, token_info)

print("Spotify OAuth token saved successfully!")

"""Environment-based configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

CACHE_DIR = ROOT / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_HOST = os.getenv("SPOTIFY_REDIRECT_HOST", "127.0.0.1")
SPOTIFY_REDIRECT_PORT = int(os.getenv("SPOTIFY_REDIRECT_PORT", "8080"))

GETSONGBPM_API_KEY = os.getenv("GETSONGBPM_API_KEY", "")
DEEZER_ARL = os.getenv("DEEZER_ARL", "")
DEEZER_APP_ID = os.getenv("DEEZER_APP_ID", "")
DEEZER_APP_SECRET = os.getenv("DEEZER_APP_SECRET", "")
DEEZER_REDIRECT_URI = os.getenv("DEEZER_REDIRECT_URI", "http://127.0.0.1:8081/callback")

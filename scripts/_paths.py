"""Repo-relative paths so scripts run from any working directory."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
STATE = os.path.join(ROOT, "state")
REPORTS = os.path.join(ROOT, "reports")
CACHE = os.path.join(ROOT, "cache")
FULLTEXT = os.path.join(ROOT, "fulltext")
RERUN = os.path.join(ROOT, "rerun")
EXAMPLES = os.path.join(ROOT, "examples")
PRICES = os.path.join(CACHE, "prices")
SOURCES = os.path.join(CONFIG, "sources.csv")
DORMANT = os.path.join(CONFIG, "sources_dormant_or_dead.csv")
SEEN = os.path.join(STATE, "seen_posts.csv")


def user_agent():
    """HTTP User-Agent. Override with SCREENY_USER_AGENT; never hardcode an email."""
    return os.environ.get("SCREENY_USER_AGENT", "Mozilla/5.0")


def ensure(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)

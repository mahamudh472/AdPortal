import secrets
from django.core.cache import cache

def generate_oauth_state(user_id, ttl=300):
    state = secrets.token_urlsafe(32)
    cache.set(f"google_oauth_state:{state}", user_id, ttl)
    return state

def validate_oauth_state(state):
    user_id = cache.get(f"google_oauth_state:{state}")
    if user_id:
        cache.delete(f"google_oauth_state:{state}")
    return user_id

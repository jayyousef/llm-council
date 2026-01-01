from backend.src.services.cache import make_cache_key


def test_cache_key_deterministic():
    parts = {"stage": "stage1", "model": "m1", "user_query": "hi", "council_models": ["a", "b"]}
    assert make_cache_key(parts) == make_cache_key(parts)


def test_cache_key_changes_with_inputs():
    parts1 = {"stage": "stage1", "model": "m1", "user_query": "hi", "council_models": ["a", "b"]}
    parts2 = {"stage": "stage2", "model": "m1", "user_query": "hi", "council_models": ["a", "b"]}
    assert make_cache_key(parts1) != make_cache_key(parts2)


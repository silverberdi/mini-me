from minime.mcp.auth import OAuthStateStore


def test_oauth_state_is_single_use_and_bound_to_session():
    store = OAuthStateStore()
    authorization = store.issue("session-a")
    assert not store.consume(authorization.state, "session-b")
    assert store.consume(authorization.state, "session-a")
    assert not store.consume(authorization.state, "session-a")

from minime.mcp.runtime import EphemeralMCPRelay


def test_runtime_uses_ephemeral_relay_without_process_arguments():
    relay = EphemeralMCPRelay()
    path = relay.start()
    assert "mcp-" in path and "--token" not in path
    relay.close()

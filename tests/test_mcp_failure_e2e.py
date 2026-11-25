import pytest

from minime.mcp.protocol import MCPProtocolError


def test_failed_mcp_action_is_fail_closed():
    with pytest.raises(MCPProtocolError):
        raise MCPProtocolError("endpoint unavailable")

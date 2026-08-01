"""Behavior tests for authentication and public identity tools."""

import orjson
import pytest


@pytest.mark.asyncio
async def test_public_settings_keep_dynamic_public_keys(auth_tools) -> None:
    tools, client = auth_tools
    client.responses["GET", "public/settings"] = {
        "auth": {"type": "password"},
        "share_enabled": True,
        "secret": "not-secret-but-unknown",
    }

    result = await tools["get_public_settings"]()

    assert orjson.loads(result) == {
        "auth": {"type": "password"},
        "share_enabled": True,
        "secret": "not-secret-but-unknown",
    }
    assert client.requests == [
        ("GET", "public/settings", {"require_auth": False}),
    ]


@pytest.mark.asyncio
async def test_ssh_key_list_hides_public_key_material(auth_tools) -> None:
    tools, client = auth_tools
    client.responses["GET", "me/sshkey/list"] = {
        "value": [
            {
                "id": 1,
                "name": "laptop",
                "fingerprint": "SHA256:abc",
                "public_key": "ssh-ed25519 AAAA-secret",
                "private_key": "secret",
            },
            "not-an-object",
        ]
    }

    result = await tools["list_my_ssh_keys"]()

    assert orjson.loads(result) == {
        "keys": [
            {"id": 1, "title": "laptop", "fingerprint": "SHA256:abc"},
        ]
    }
    assert "public_key" not in result
    assert "private_key" not in result

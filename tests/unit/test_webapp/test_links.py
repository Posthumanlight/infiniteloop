from webapp.links import (
    build_char_start_param,
    build_direct_mini_app_link,
    parse_char_session_id,
)


def test_build_char_start_param_prefixes_session_id():
    assert build_char_start_param("123") == "char_123"


def test_parse_char_session_id_returns_session_id():
    assert parse_char_session_id("char_123") == "123"


def test_parse_char_session_id_rejects_wrong_entrypoint():
    try:
        parse_char_session_id("combat_123")
    except ValueError as exc:
        assert str(exc) == "Unsupported Mini App entrypoint"
    else:
        raise AssertionError("Expected ValueError for unsupported entrypoint")


def test_build_direct_mini_app_link_encodes_start_param():
    url = build_direct_mini_app_link("LoopBot", "char_group:1")

    assert url == "https://t.me/LoopBot?startapp=char_group%3A1"

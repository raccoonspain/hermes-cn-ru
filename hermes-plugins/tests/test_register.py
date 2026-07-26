import project_index as plugin


class FakeCtx:
    def __init__(self):
        self.tools = {}

    def register_tool(self, name, toolset, schema, handler, requires_env=None, emoji="", **kwargs):
        self.tools[name] = {
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "requires_env": requires_env,
            "emoji": emoji,
        }


def test_register_adds_exactly_three_tools():
    ctx = FakeCtx()
    plugin.register(ctx)
    assert set(ctx.tools) == {"project_index_update", "project_search_similar", "project_move"}


def test_each_tool_schema_is_well_formed():
    ctx = FakeCtx()
    plugin.register(ctx)
    for name, entry in ctx.tools.items():
        assert entry["schema"]["name"] == name
        assert "description" in entry["schema"]
        assert entry["schema"]["parameters"]["type"] == "object"
        assert "user" in entry["schema"]["parameters"]["properties"]
        assert "user" in entry["schema"]["parameters"]["required"]
        assert entry["requires_env"] == ["WORMSOFT_API_KEY"]


def test_handle_index_update_success(monkeypatch):
    monkeypatch.setattr(
        plugin.core, "index_update",
        lambda user, project_path: {"path": "/x", "indexed": True, "message": "проиндексировано"},
    )
    result = plugin._handle_index_update({"user": "dem", "project_path": "dem/ALL/x"})
    assert result == '{"path": "/x", "indexed": true, "message": "проиндексировано"}'


def test_handle_index_update_missing_param_returns_json_error():
    result = plugin._handle_index_update({"user": "dem"})
    assert result.startswith('{"error"')


def test_handle_search_similar_defaults_top_k(monkeypatch):
    captured = {}

    def fake_search(user, query, top_k):
        captured["top_k"] = top_k
        return {"results": [], "message": ""}

    monkeypatch.setattr(plugin.core, "search_similar", fake_search)
    plugin._handle_search_similar({"user": "dem", "query": "гараж"})
    assert captured["top_k"] == 5


def test_handle_move_wraps_project_index_error(monkeypatch):
    def fake_move(**kwargs):
        raise plugin.core.ProjectIndexError("коллизия имён")

    monkeypatch.setattr(plugin.core, "move_project", fake_move)
    result = plugin._handle_move({"user": "dem", "project_path": "dem/ALL/x"})
    assert result == '{"error": "коллизия имён"}'

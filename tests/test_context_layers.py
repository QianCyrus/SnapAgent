"""Tests for pluggable context layer system."""

from snapagent.agent.context_layers import LayerRegistry, PromptLayer


class _TestLayer:
    """Simple test layer implementation."""

    def __init__(self, name: str, priority: int, content: str | None = "test content"):
        self._name = name
        self._priority = priority
        self._content = content

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    def render(self) -> str | None:
        return self._content


class TestLayerRegistry:
    def test_render_empty(self):
        registry = LayerRegistry()
        assert registry.render_all() == ""

    def test_render_single_layer(self):
        registry = LayerRegistry()
        registry.register(_TestLayer("a", 100, "hello"))
        assert registry.render_all() == "hello"

    def test_priority_ordering(self):
        registry = LayerRegistry()
        registry.register(_TestLayer("low", 300, "low"))
        registry.register(_TestLayer("high", 100, "high"))
        registry.register(_TestLayer("mid", 200, "mid"))
        parts = registry.render_all().split(LayerRegistry.SEPARATOR)
        assert parts == ["high", "mid", "low"]

    def test_layer_enable_disable(self):
        registry = LayerRegistry()
        registry.register(_TestLayer("a", 100, "visible"))
        registry.register(_TestLayer("b", 200, "hidden"))
        registry.enable("b", enabled=False)
        assert "hidden" not in registry.render_all()
        assert "visible" in registry.render_all()

    def test_layer_re_enable(self):
        registry = LayerRegistry()
        registry.register(_TestLayer("a", 100, "content"))
        registry.enable("a", enabled=False)
        assert registry.render_all() == ""
        registry.enable("a", enabled=True)
        assert registry.render_all() == "content"

    def test_register_replaces_same_name(self):
        registry = LayerRegistry()
        registry.register(_TestLayer("a", 100, "old"))
        registry.register(_TestLayer("a", 100, "new"))
        assert registry.render_all() == "new"

    def test_unregister(self):
        registry = LayerRegistry()
        registry.register(_TestLayer("a", 100, "content"))
        registry.unregister("a")
        assert registry.render_all() == ""

    def test_none_content_skipped(self):
        registry = LayerRegistry()
        registry.register(_TestLayer("a", 100, "visible"))
        registry.register(_TestLayer("b", 200, None))
        registry.register(_TestLayer("c", 300, "also visible"))
        parts = registry.render_all().split(LayerRegistry.SEPARATOR)
        assert parts == ["visible", "also visible"]

    def test_separator_format(self):
        registry = LayerRegistry()
        registry.register(_TestLayer("a", 100, "first"))
        registry.register(_TestLayer("b", 200, "second"))
        assert "\n\n---\n\n" in registry.render_all()

    def test_custom_layer_is_prompt_layer(self):
        layer = _TestLayer("test", 100)
        assert isinstance(layer, PromptLayer)

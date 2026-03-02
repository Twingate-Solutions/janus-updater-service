from unittest.mock import MagicMock

from janus.discovery import _parse_bool, discover_targets


# ── _parse_bool ───────────────────────────────────────────────────────────────

class TestParseBool:
    def test_none_is_false(self):
        assert _parse_bool(None) is False

    def test_truthy_values(self):
        for v in ("1", "true", "True", "TRUE", "yes", "YES", "y", "Y", "on", "ON"):
            assert _parse_bool(v) is True, f"Expected True for {v!r}"

    def test_falsy_values(self):
        for v in ("0", "false", "no", "n", "off", "", "random"):
            assert _parse_bool(v) is False, f"Expected False for {v!r}"

    def test_whitespace_stripped(self):
        assert _parse_bool("  true  ") is True
        assert _parse_bool("  false  ") is False


# ── discover_targets ──────────────────────────────────────────────────────────

def _make_client(*containers):
    client = MagicMock()
    client.containers.list.return_value = list(containers)
    return client


def _make_container(name, labels, image="nginx:latest", cid="abc123"):
    c = MagicMock()
    c.id = cid
    c.name = name
    c.attrs = {
        "Name": f"/{name}",
        "Config": {"Labels": labels, "Image": image},
    }
    return c


class TestDiscoverTargets:
    PREFIX = "janus.autoupdate"
    DEFAULT_INTERVAL = 300

    def _discover(self, *containers):
        return discover_targets(
            _make_client(*containers), self.PREFIX, self.DEFAULT_INTERVAL
        )

    def test_skips_janus_container(self):
        c = _make_container("janus", {f"{self.PREFIX}.enable": "true"})
        assert self._discover(c) == []

    def test_skips_container_without_enable_label(self):
        c = _make_container("myapp", {})
        assert self._discover(c) == []

    def test_skips_container_with_enable_false(self):
        c = _make_container("myapp", {f"{self.PREFIX}.enable": "false"})
        assert self._discover(c) == []

    def test_discovers_enabled_container(self):
        c = _make_container("myapp", {f"{self.PREFIX}.enable": "true"})
        result = self._discover(c)
        assert len(result) == 1
        t = result[0]
        assert t.name == "myapp"
        assert t.image_ref == "nginx:latest"
        assert t.interval == self.DEFAULT_INTERVAL
        assert t.monitor_only is False
        assert t.is_compose is False

    def test_custom_interval(self):
        c = _make_container("myapp", {
            f"{self.PREFIX}.enable": "true",
            f"{self.PREFIX}.interval": "120",
        })
        assert self._discover(c)[0].interval == 120

    def test_invalid_interval_falls_back_to_default(self):
        c = _make_container("myapp", {
            f"{self.PREFIX}.enable": "true",
            f"{self.PREFIX}.interval": "notanumber",
        })
        assert self._discover(c)[0].interval == self.DEFAULT_INTERVAL

    def test_interval_clamped_to_minimum_5(self):
        c = _make_container("myapp", {
            f"{self.PREFIX}.enable": "true",
            f"{self.PREFIX}.interval": "2",
        })
        assert self._discover(c)[0].interval == 5

    def test_monitor_only_label(self):
        c = _make_container("myapp", {
            f"{self.PREFIX}.enable": "true",
            f"{self.PREFIX}.monitor-only": "true",
        })
        assert self._discover(c)[0].monitor_only is True

    def test_compose_container_detected(self):
        c = _make_container("myapp", {
            f"{self.PREFIX}.enable": "true",
            "com.docker.compose.project": "myproject",
            "com.docker.compose.service": "myapp",
        })
        assert self._discover(c)[0].is_compose is True

    def test_partial_compose_labels_not_compose(self):
        c = _make_container("myapp", {
            f"{self.PREFIX}.enable": "true",
            "com.docker.compose.project": "myproject",
            # missing com.docker.compose.service
        })
        assert self._discover(c)[0].is_compose is False

    def test_skips_container_with_empty_image(self):
        c = _make_container("myapp", {f"{self.PREFIX}.enable": "true"}, image="")
        assert self._discover(c) == []

    def test_exception_in_one_container_does_not_stop_discovery(self):
        bad = MagicMock()
        bad.id = "bad123"
        bad.name = "broken"
        bad.attrs = MagicMock(side_effect=Exception("API error"))

        good = _make_container("myapp", {f"{self.PREFIX}.enable": "true"}, cid="good1")

        result = self._discover(bad, good)
        assert len(result) == 1
        assert result[0].name == "myapp"

    def test_multiple_enabled_containers(self):
        containers = [
            _make_container("app1", {f"{self.PREFIX}.enable": "true"}, cid="c1"),
            _make_container("app2", {f"{self.PREFIX}.enable": "true"}, cid="c2"),
            _make_container("app3", {}, cid="c3"),  # not enabled
        ]
        result = self._discover(*containers)
        assert len(result) == 2
        names = {t.name for t in result}
        assert names == {"app1", "app2"}

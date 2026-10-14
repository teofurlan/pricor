import socket

import pytest

from pricor.entrypoints.cli import find_free_port, main


class Recorder:
    """Stands in for the server and the browser; nothing real is started."""

    def __init__(self, *, start: bool = True):
        self.served: list[tuple[str, int]] = []
        self.opened: list[str] = []
        self.start = start

    def serve(self, host: str, port: int, on_started) -> None:
        self.served.append((host, port))
        if self.start:
            on_started()

    def open_browser(self, url: str) -> bool:
        self.opened.append(url)
        return True


def run(argv, recorder=None, **kwargs):
    recorder = recorder or Recorder()
    main(argv, serve=recorder.serve, open_browser=recorder.open_browser, **kwargs)
    return recorder


def test_bare_command_serves_on_loopback_and_opens_the_browser():
    recorder = run([], preferred_port_is_free=lambda host, port: True)
    assert recorder.served == [("127.0.0.1", 8000)]
    assert recorder.opened == ["http://127.0.0.1:8000/"]


def test_no_browser_flag_only_serves():
    recorder = run(["--no-browser"], preferred_port_is_free=lambda host, port: True)
    assert recorder.served == [("127.0.0.1", 8000)]
    assert recorder.opened == []


def test_the_serve_subcommand_accepts_the_same_options():
    recorder = run(["serve", "--port", "9100", "--no-browser"], preferred_port_is_free=lambda h, p: True)
    assert recorder.served == [("127.0.0.1", 9100)]
    assert recorder.opened == []


def test_the_browser_opens_only_after_the_server_is_up():
    recorder = run([], Recorder(start=False), preferred_port_is_free=lambda host, port: True)
    assert recorder.opened == []


def test_a_busy_default_port_falls_back_to_a_free_one():
    recorder = run([], preferred_port_is_free=lambda host, port: False)
    (host, port), = recorder.served
    assert host == "127.0.0.1"
    assert port != 8000 and port > 0
    assert recorder.opened == [f"http://127.0.0.1:{port}/"]


def test_an_explicit_port_is_never_replaced(capsys):
    with pytest.raises(SystemExit) as stop:
        run(["--port", "9100"], preferred_port_is_free=lambda host, port: False)
    assert stop.value.code != 0
    assert "9100" in capsys.readouterr().err


def test_find_free_port_returns_a_bindable_port():
    port = find_free_port("127.0.0.1")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_find_free_port_skips_a_port_that_is_taken():
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        busy = taken.getsockname()[1]
        assert find_free_port("127.0.0.1", preferred=busy) != busy


def test_find_free_port_keeps_the_preferred_port_when_it_is_free():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    assert find_free_port("127.0.0.1", preferred=free) == free

import pytest

from hermes_backend_host import ReadinessError, ReadinessParser


@pytest.mark.parametrize("sentinel", ["BACKEND", "DASHBOARD"])
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_chunked_complete_machine_lines(sentinel, newline):
    parser = ReadinessParser()
    for value in f"HERMES_{sentinel}_READY port=54321".encode():
        parser.feed(bytes([value]))
        assert parser.port() is None
    parser.feed(newline)
    assert parser.port() == 54321


def test_dual_sentinels_same_port_are_supported():
    parser = ReadinessParser()
    parser.feed(
        b"ordinary startup log\nHERMES_BACKEND_READY port=54321\nHERMES_DASHBOARD_READY port=54321\n"
    )
    assert parser.port() == 54321


@pytest.mark.parametrize(
    "value", [b"0", b"65536", b"999999", b"abc", b"42junk", b"42 extra"]
)
def test_invalid_port_rejected_without_output_echo(value):
    parser = ReadinessParser()
    parser.feed(b"HERMES_BACKEND_READY port=" + value + b"\n")
    with pytest.raises(ReadinessError) as error:
        parser.port()
    assert value.decode() not in str(error.value)


def test_conflict_and_partial_eof_fail_closed():
    parser = ReadinessParser()
    parser.feed(b"HERMES_BACKEND_READY port=1\nHERMES_DASHBOARD_READY port=2\n")
    with pytest.raises(ReadinessError, match="conflicting"):
        parser.port()
    partial = ReadinessParser()
    partial.feed(b"HERMES_BACKEND_READY port=42")
    partial.eof()
    with pytest.raises(ReadinessError, match="complete"):
        partial.port()


def test_log_mentions_do_not_count_as_readiness():
    parser = ReadinessParser()
    parser.feed(b"waiting for HERMES_BACKEND_READY port=1234\n")
    assert parser.port() is None


@pytest.mark.parametrize("data", [b"x" * 65, b"x" * 65 + b"\n", b"x\n" * 129])
def test_output_is_bounded(data):
    parser = ReadinessParser(max_line=64, max_bytes=256)
    parser.feed(data)
    with pytest.raises(ReadinessError, match="bound"):
        parser.port()

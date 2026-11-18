import pytest

from rvsched.cli import main


def test_no_args_prints_help(capsys):
    assert main([]) == 0
    assert "rvsched route" in capsys.readouterr().out


@pytest.mark.parametrize("cmd", [[], ["route"], ["record"], ["calibrate"]])
def test_help_flags_exit_cleanly(cmd, capsys):
    with pytest.raises(SystemExit) as e:
        main(cmd + ["-h"])
    assert e.value.code == 0
    assert "usage: rvsched" in capsys.readouterr().out

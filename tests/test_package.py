from insulation_coordination import __version__
from insulation_coordination.cli import main


def test_package_exposes_version(capsys):
    assert __version__ == "0.1.0"
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"

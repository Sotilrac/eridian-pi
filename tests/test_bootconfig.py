"""The overlay block this project owns in config.txt."""

from __future__ import annotations

import pytest

from rockyvox.bootconfig import BACKENDS, BEGIN, CARDS, END, apply_block, main, render_block

STOCK = """# For more options and information see
# http://rptl.io/configtxt

dtparam=audio=on
camera_auto_detect=1
dtoverlay=vc4-kms-v3d

[all]

dtoverlay=dwc2
"""


def test_every_backend_enables_i2c_for_the_amplifier():
    for backend in BACKENDS:
        assert "dtparam=i2c_arm=on" in render_block(backend), backend


def test_every_backend_names_a_card_or_says_it_must_be_detected():
    assert set(CARDS) == set(BACKENDS)
    assert CARDS["usb"] is None


def test_the_block_is_appended_to_a_stock_config():
    result = apply_block(STOCK, "i2s")
    assert result.startswith(STOCK.rstrip("\n"))
    assert "dtoverlay=hifiberry-dac" in result
    assert result.count(BEGIN) == 1
    assert result.count(END) == 1


def test_applying_twice_changes_nothing_further():
    once = apply_block(STOCK, "i2s")
    assert apply_block(once, "i2s") == once


def test_switching_backend_removes_the_previous_overlay():
    # The whole point: a stale hifiberry overlay would keep claiming GPIO18.
    i2s = apply_block(STOCK, "i2s")
    usb = apply_block(i2s, "usb")

    assert "hifiberry" not in usb
    assert "audremap" not in usb
    assert "dtparam=i2c_arm=on" in usb
    assert usb.count(BEGIN) == 1


def test_switching_to_pwm_replaces_the_dac_overlay():
    pwm = apply_block(apply_block(STOCK, "i2s"), "pwm")
    assert "audremap,pins_18_19" in pwm
    assert "hifiberry" not in pwm


def test_the_stock_content_is_never_disturbed():
    for backend in BACKENDS:
        result = apply_block(STOCK, backend)
        for line in ("dtoverlay=vc4-kms-v3d", "camera_auto_detect=1", "dtoverlay=dwc2"):
            assert line in result, (backend, line)


def test_lines_from_the_first_provisioner_are_cleaned_up():
    legacy = (
        STOCK
        + """
# added by rocky-vox provision.sh
dtparam=i2c_arm=on

# added by rocky-vox provision.sh
dtoverlay=hifiberry-dac
"""
    )
    result = apply_block(legacy, "usb")
    assert "added by rocky-vox" not in result
    assert "hifiberry" not in result
    assert result.count("dtparam=i2c_arm=on") == 1


def test_an_unknown_backend_is_refused():
    with pytest.raises(ValueError, match="unknown audio backend"):
        render_block("telepathy")


def test_the_cli_reports_whether_it_touched_the_file(tmp_path, capsys):
    path = tmp_path / "config.txt"
    path.write_text(STOCK)

    assert main(["--backend", "i2s", "--path", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "changed"

    assert main(["--backend", "i2s", "--path", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "unchanged"

    assert main(["--backend", "pwm", "--path", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "changed"

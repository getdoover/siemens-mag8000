"""Decoding checked against registers read from a real MAG 8000 (DN150, Ml/d)."""

import pytest

from siemens_mag8000.record import (
    MEASUREMENT_BLOCK,
    POWER_BLOCK,
    UNITS_BLOCK,
    Record,
    Units,
)


def words(hex_string):
    raw = bytes.fromhex(hex_string.replace(" ", ""))
    return [int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw), 2)]


# 4:0207 x22 -- flow factor 86.4, volume factor 0.001, "Ml/d", "Ml", DN150, Qn 15.12
UNITS = words(
    "42ac cccd 3a83 126f"
    "4d6c 2f64 0020 0000 0000 0000"
    "4d6c 0075 0000 0000 0000 0000"
    "0000 0096 0000 0000 4171 eb85"
)

# 4:3003 x26 -- no flow, low power warning, totalizer 1 = 3.223, totalizer 2 = -2.002
MEASUREMENT = words(
    "0000 0000 0000 0000 0000 0000 0000 0219 0000 0136 0000 0000 0008 9530"
    "0010"
    "0000 0003 0d4a cdab"
    "ffff fffe ffda 1f79"
    "0000 0003 0d4a"
)

# 4:3030 x15 -- battery, 0 %, battery alarm, 31.4 degC
POWER = words(
    "0000 0000 0001 7c80 1a07 1213 18000000 0000 0000 0000 0000 000041fb 8bca"
)


@pytest.fixture
def record():
    return Record(Units(UNITS), MEASUREMENT, POWER)


def test_block_lengths():
    assert len(UNITS) == UNITS_BLOCK[1]
    assert len(MEASUREMENT) == MEASUREMENT_BLOCK[1]
    assert len(POWER) == POWER_BLOCK[1]
    assert max(UNITS_BLOCK[1], MEASUREMENT_BLOCK[1], POWER_BLOCK[1]) <= 26


def test_units():
    units = Units(UNITS)
    assert units.is_valid
    assert units.flow_unit == "Ml/d"
    assert units.volume_unit == "Ml"
    assert units.pipe_size_mm == 150
    # A meter ordered in Ml/d already reports ML/day.
    assert units.nominal_flow == pytest.approx(15.12)


def test_measurement(record):
    assert record.current_flow == 0
    assert record.total == pytest.approx(3.223006123)
    assert record.total_2 == pytest.approx(-2.002482311)
    assert record.faults == ["Low power"]
    assert record.status_text == "Low power"


def test_power(record):
    assert not record.on_mains
    assert record.power_source == "Battery"
    assert record.battery_percent == 0
    assert record.low_battery
    assert record.transmitter_temp == pytest.approx(31.44, abs=0.01)


def test_other_units_are_normalised():
    """A meter ordered in m3/h and m3 still reads out in ML/day and ML."""
    units = Units(UNITS)
    units.flow_factor = 3600
    units.volume_factor = 1

    measurement = list(MEASUREMENT)
    measurement[0:2] = words("4476 0000")  # 984 m3/h
    measurement[15:19] = words("0000 1388 0000 0000")  # 5000 m3
    record = Record(units, measurement, POWER)

    assert record.current_flow == pytest.approx(23.616)
    assert record.total == pytest.approx(5.0)


def test_healthy_meter():
    measurement = list(MEASUREMENT)
    measurement[14] = 0
    power = list(POWER)
    power[0:3] = [1, 100, 0]
    record = Record(Units(UNITS), measurement, power)

    assert record.status_text == "OK"
    assert record.on_mains
    assert not record.low_battery


def test_invalid_unit_factors():
    units = Units([0] * UNITS_BLOCK[1])
    assert not units.is_valid
    assert units.flow_to_megs_per_day(1.0) is None
    assert units.volume_to_megs(1.0) is None

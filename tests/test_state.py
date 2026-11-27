from types import SimpleNamespace

from siemens_mag8000.app_state import LOW_BATTERY_SLEEP_FACTOR, get_sleep_time


def meter(on_mains=False, low_battery=False):
    return SimpleNamespace(on_mains=on_mains, low_battery=low_battery)


def test_no_reading_yet_uses_idle_interval():
    assert get_sleep_time(None, False, 900, 60) == 900


def test_battery_meter_reads_faster_only_while_flowing():
    assert get_sleep_time(meter(), False, 900, 60) == 900
    assert get_sleep_time(meter(), True, 900, 60) == 60


def test_low_battery_reads_less_often():
    record = meter(low_battery=True)
    assert get_sleep_time(record, False, 900, 60) == 900 * LOW_BATTERY_SLEEP_FACTOR
    assert get_sleep_time(record, True, 900, 60) == 60 * LOW_BATTERY_SLEEP_FACTOR


def test_mains_meter_always_reads_at_the_flowing_interval():
    assert get_sleep_time(meter(on_mains=True), False, 900, 60) == 60
    assert get_sleep_time(meter(on_mains=True, low_battery=True), False, 900, 60) == 60

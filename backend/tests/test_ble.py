"""Bluetooth health parsers, checked against byte layouts from the Bluetooth SIG / IEEE 11073 specifications."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(scope="module")
def ble():
    spec = importlib.util.spec_from_file_location("ble_health_under_test", SCRIPTS / "ble_health.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_ieee11073_number_formats(ble):
    assert ble.sfloat(bytes([0x61, 0x00])) == 97            # mantissa 97, exponent 0
    assert ble.sfloat(bytes([0x70, 0xF1])) == 36.8          # mantissa 368, exponent -1
    assert ble.sfloat(bytes([0xFF, 0x0F])) == -1            # mantissa -1 (12-bit two's complement)
    for special in (0x07FF, 0x0800, 0x07FE, 0x0802, 0x0801):  # NaN, NRes, +INF, -INF, reserved
        assert ble.sfloat(special.to_bytes(2, "little")) is None
    assert ble.float32(bytes([0x70, 0x01, 0x00, 0xFF])) == 36.8   # mantissa 368, exponent -1
    assert ble.float32((0x007FFFFF).to_bytes(4, "little")) is None


def test_heart_rate_measurement(ble):
    assert ble.parse_heart_rate(bytes([0x00, 72])) == {"hr": 72}
    assert ble.parse_heart_rate(bytes([0x01, 0x2C, 0x01])) == {"hr": 300}      # 16-bit value
    assert ble.parse_heart_rate(bytes([0x06, 80])) == {"hr": 80}               # contact supported and detected
    assert ble.parse_heart_rate(bytes([0x04, 80])) is None                     # supported but strap not on skin
    assert ble.parse_heart_rate(bytes([0x00])) is None


def test_pulse_oximeter_measurements(ble):
    data = bytes([0x00, 0x61, 0x00, 0x48, 0x00])                               # SpO2 97 %, pulse 72
    assert ble.parse_plx_spot_check(data) == {"spo2": 97, "hr": 72}
    assert ble.parse_plx_continuous(data) == {"spo2": 97, "hr": 72}
    assert ble.parse_plx_continuous(bytes([0x00, 0xFF, 0x07, 0x48, 0x00])) == {"hr": 72}   # SpO2 not available


def test_blood_pressure_measurement(ble):
    mmhg = bytes([0x00, 0x78, 0x00, 0x50, 0x00, 0x5A, 0x00])                    # 120 / 80, MAP 90
    assert ble.parse_blood_pressure(mmhg) == {"sbp": 120, "dbp": 80}
    kpa = bytes([0x01, 0xA0, 0xF0, 0x6B, 0xF0, 0x7D, 0xF0])                     # 16.0 / 10.7 kPa
    assert ble.parse_blood_pressure(kpa) == {"sbp": 120.01, "dbp": 80.26}
    with_time_and_pulse = mmhg[:1].replace(b"\x00", b"\x06") + mmhg[1:] + bytes(7) + bytes([0x48, 0x00])
    assert ble.parse_blood_pressure(with_time_and_pulse) == {"sbp": 120, "dbp": 80, "hr": 72}
    half = bytes([0x00, 0x78, 0x00, 0xFF, 0x07, 0x5A, 0x00])                    # diastolic missing: send neither
    assert ble.parse_blood_pressure(half) is None


def test_temperature_measurement(ble):
    assert ble.parse_temperature(bytes([0x00, 0x70, 0x01, 0x00, 0xFF])) == {"temp": 36.8}
    assert ble.parse_temperature(bytes([0x01, 0xDA, 0x03, 0x00, 0xFF])) == {"temp": 37.0}   # 98.6 F


def test_combiner_sends_only_what_was_measured(ble):
    c = ble.Combiner(window_s=30)
    c.add({"spo2": 96, "hr": 80}, now=0)
    assert c.due(now=10) is None
    c.add({"hr": 82}, now=20)                       # a newer value replaces the older one
    assert c.due(now=31) == {"spo2": 96, "hr": 82}
    assert c.due(now=100) is None                   # nothing new: nothing sent, nothing repeated


def test_uuids_are_the_standard_ones(ble):
    assert ble.uuid16(0x2A37) == "00002a37-0000-1000-8000-00805f9b34fb"
    assert set(ble.SERVICES) == {ble.uuid16(u) for u in (0x180D, 0x1822, 0x1810, 0x1809)}

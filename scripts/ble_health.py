"""Parsers for the standard Bluetooth Low Energy health measurements (no Bluetooth library needed).

Every byte layout here comes from the Bluetooth SIG GATT specifications, so any device that implements the standard
service works, whatever the brand:

    Service (UUID)                    Characteristic (UUID)                    Gives
    Heart Rate (0x180D)               Heart Rate Measurement (0x2A37)          hr
    Pulse Oximeter (0x1822)           PLX Spot-Check Measurement (0x2A5E)      spo2, hr
                                      PLX Continuous Measurement (0x2A5F)      spo2, hr
    Blood Pressure (0x1810)           Blood Pressure Measurement (0x2A35)      sbp, dbp (and hr when sent)
    Health Thermometer (0x1809)       Temperature Measurement (0x2A1C)         temp

Medical devices send numbers in the IEEE 11073-20601 formats SFLOAT (16-bit) and FLOAT (32-bit): a signed mantissa
and a signed base-10 exponent, with reserved codes for "not a number", "not at this resolution" and infinity.
No standard BLE service carries breathing rate, so rr comes from other sources (or is simply not measured).
"""
from __future__ import annotations

KPA_TO_MMHG = 7.500617

# Special values: NaN, NRes (not at this resolution), +INF, -INF, reserved
_SFLOAT_SPECIAL = {0x07FF, 0x0800, 0x07FE, 0x0802, 0x0801}
_FLOAT_SPECIAL = {0x007FFFFF, 0x00800000, 0x007FFFFE, 0x00800002, 0x00800001}


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def sfloat(data: bytes, offset: int = 0) -> float | None:
    """IEEE 11073 16-bit SFLOAT, little-endian: 4-bit exponent, 12-bit mantissa. None for special values."""
    raw = int.from_bytes(data[offset:offset + 2], "little")
    mantissa = raw & 0x0FFF
    if mantissa in _SFLOAT_SPECIAL and raw >> 12 == 0:
        return None
    return round(_signed(mantissa, 12) * 10.0 ** _signed(raw >> 12, 4), 6)


def float32(data: bytes, offset: int = 0) -> float | None:
    """IEEE 11073 32-bit FLOAT, little-endian: 8-bit exponent, 24-bit mantissa. None for special values."""
    raw = int.from_bytes(data[offset:offset + 4], "little")
    mantissa = raw & 0xFFFFFF
    if raw >> 24 == 0 and mantissa in _FLOAT_SPECIAL:
        return None
    return round(_signed(mantissa, 24) * 10.0 ** _signed(raw >> 24, 8), 6)


def _clean(values: dict[str, float | None]) -> dict[str, float] | None:
    out = {k: round(v, 2) for k, v in values.items() if v is not None}
    if ("sbp" in out) != ("dbp" in out):          # the server needs blood pressure as a pair
        out.pop("sbp", None)
        out.pop("dbp", None)
    return out or None


def parse_heart_rate(data: bytes) -> dict[str, float] | None:
    """Heart Rate Measurement (0x2A37). Flags bit 0: 16-bit value; bits 1-2: sensor contact."""
    if len(data) < 2:
        return None
    flags = data[0]
    contact_supported, contact_detected = bool(flags & 0x04), bool(flags & 0x02)
    if contact_supported and not contact_detected:
        return None                                   # strap not on the skin: the value is meaningless
    hr = int.from_bytes(data[1:3], "little") if flags & 0x01 else data[1]
    return _clean({"hr": float(hr) if hr else None})


def parse_plx_spot_check(data: bytes) -> dict[str, float] | None:
    """PLX Spot-Check Measurement (0x2A5E): flags, SpO2 (SFLOAT), pulse rate (SFLOAT), optional fields after."""
    if len(data) < 5:
        return None
    return _clean({"spo2": sfloat(data, 1), "hr": sfloat(data, 3)})


def parse_plx_continuous(data: bytes) -> dict[str, float] | None:
    """PLX Continuous Measurement (0x2A5F): flags, then the 'normal' SpO2 and pulse rate (SFLOAT each)."""
    if len(data) < 5:
        return None
    return _clean({"spo2": sfloat(data, 1), "hr": sfloat(data, 3)})


def parse_blood_pressure(data: bytes) -> dict[str, float] | None:
    """Blood Pressure Measurement (0x2A35).

    Flags bit 0: units kPa (else mmHg); bit 1: time stamp (7 bytes) present; bit 2: pulse rate present.
    Then systolic, diastolic, mean arterial pressure (SFLOAT each).
    """
    if len(data) < 7:
        return None
    flags = data[0]
    scale = KPA_TO_MMHG if flags & 0x01 else 1.0
    sbp, dbp = sfloat(data, 1), sfloat(data, 3)
    offset = 7 + (7 if flags & 0x02 else 0)
    pulse = sfloat(data, offset) if flags & 0x04 and len(data) >= offset + 2 else None
    return _clean({"sbp": sbp * scale if sbp is not None else None,
                   "dbp": dbp * scale if dbp is not None else None, "hr": pulse})


def parse_temperature(data: bytes) -> dict[str, float] | None:
    """Temperature Measurement (0x2A1C). Flags bit 0: Fahrenheit (else Celsius). Value is a 32-bit FLOAT."""
    if len(data) < 5:
        return None
    value = float32(data, 1)
    if value is not None and data[0] & 0x01:
        value = (value - 32.0) * 5.0 / 9.0
    return _clean({"temp": value})


def uuid16(short: int) -> str:
    """Full 128-bit UUID string for a 16-bit Bluetooth SIG UUID."""
    return f"0000{short:04x}-0000-1000-8000-00805f9b34fb"


# characteristic UUID -> parser; service UUIDs used to find devices
PARSERS = {
    uuid16(0x2A37): parse_heart_rate,
    uuid16(0x2A5E): parse_plx_spot_check,
    uuid16(0x2A5F): parse_plx_continuous,
    uuid16(0x2A35): parse_blood_pressure,
    uuid16(0x2A1C): parse_temperature,
}
SERVICES = {uuid16(0x180D): "heart rate", uuid16(0x1822): "pulse oximeter",
            uuid16(0x1810): "blood pressure", uuid16(0x1809): "thermometer"}


class Combiner:
    """Collects measurements from several sensors and emits one partial reading per time window.

    Only values measured in the window are sent; nothing is repeated or invented (the server shows the
    rest as 'Not measured'). A newer value for the same vital replaces the older one in the window.
    """

    def __init__(self, window_s: float):
        self.window_s = window_s
        self.pending: dict[str, float] = {}
        self.started: float | None = None

    def add(self, values: dict[str, float], now: float) -> None:
        if self.started is None:
            self.started = now
        self.pending.update(values)

    def due(self, now: float) -> dict[str, float] | None:
        if self.started is None or now - self.started < self.window_s:
            return None
        out, self.pending, self.started = self.pending, {}, None
        return out or None

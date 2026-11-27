"""Decoding of SITRANS F M MAG 8000 holding registers.

Register numbers are as listed in the Siemens Modbus RTU manual (A5E03409989).
The address on the wire is the listed number minus one.
"""

import math
import struct
import time

# (listed register, count) for each block the app reads. The meter allows at
# most 26 registers per request.
UNITS_BLOCK = (207, 22)  # 4:0207 - 4:0228
MEASUREMENT_BLOCK = (3003, 26)  # 4:3003 - 4:3028
POWER_BLOCK = (3030, 15)  # 4:3030 - 4:3044

# Fault status (4:3017), bit 0 first.
FAULTS = [
    "Insulation error",
    "Coil current error",
    "Preamplifier overload",
    "Database checksum error",
    "Low power",
    "Flow overload",
    "Pulse A overload",
    "Pulse B overload",
    "Consumption interval",
    "Leakage",
    "Empty pipe",
    "Low impedance",
    "Flow limit",
    "Reverse flow",
]

M3_PER_SEC_TO_ML_PER_DAY = 86.4
M3_TO_ML = 0.001

# Power status (4:3032) is a bit field.
POWER_BATTERY_ALARM = 0x01
POWER_TOO_LOW = 0x02
POWER_EXTERNAL_GONE = 0x04


def _float32(regs, idx):
    value = struct.unpack(">f", struct.pack(">HH", regs[idx], regs[idx + 1]))[0]
    return value if math.isfinite(value) else None


def _total(regs, idx):
    """Siemens 'TotalType': a signed integer part, then a signed fraction x 1e9."""
    number, decimal = struct.unpack(">ii", struct.pack(">4H", *regs[idx : idx + 4]))
    return number + decimal / 1e9


def _string(regs, idx, count):
    raw = b"".join(struct.pack(">H", r) for r in regs[idx : idx + count])
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


class Units:
    """How the meter was ordered: its flow and volume units.

    Flow and volume registers are reported in the meter's own units, which are
    SI (m3/s, m3) multiplied by these factors.
    """

    def __init__(self, register_values):
        regs = list(register_values)
        self.flow_factor = _float32(regs, 0)  # 4:0207
        self.volume_factor = _float32(regs, 2)  # 4:0209
        self.flow_unit = _string(regs, 4, 6)  # 4:0211
        self.volume_unit = _string(regs, 10, 6)  # 4:0217
        self.pipe_size_mm = regs[17]  # 4:0224
        self.nominal_flow = self.flow_to_megs_per_day(_float32(regs, 20))  # 4:0227
        self.ts = time.time()

    @property
    def is_valid(self):
        return bool(
            self.flow_factor
            and self.flow_factor > 0
            and self.volume_factor
            and self.volume_factor > 0
        )

    def flow_to_megs_per_day(self, value):
        if value is None or not self.flow_factor or self.flow_factor <= 0:
            return None
        return value / self.flow_factor * M3_PER_SEC_TO_ML_PER_DAY

    def volume_to_megs(self, value):
        if value is None or not self.volume_factor or self.volume_factor <= 0:
            return None
        return value / self.volume_factor * M3_TO_ML


class Record:
    def __init__(self, units: Units, measurement, power):
        self.units = units
        self.measurement = list(measurement)
        self.power = list(power)
        self.ts = time.time()

    # --- measurement block, offsets from 4:3003 ---

    @property
    def current_flow(self):
        """Flow rate in ML/day."""
        return self.units.flow_to_megs_per_day(_float32(self.measurement, 0))

    @property
    def fault_status(self):
        return self.measurement[14]  # 4:3017

    @property
    def faults(self):
        status = self.fault_status
        return [name for bit, name in enumerate(FAULTS) if status & (1 << bit)]

    @property
    def total(self):
        """Totalizer 1 in ML."""
        return self.units.volume_to_megs(_total(self.measurement, 15))  # 4:3018

    @property
    def total_2(self):
        """Totalizer 2 in ML."""
        return self.units.volume_to_megs(_total(self.measurement, 19))  # 4:3022

    # --- power block, offsets from 4:3030 ---

    @property
    def on_mains(self):
        return self.power[0] & 0xFF == 1  # 4:3030

    @property
    def battery_percent(self):
        return self.power[1] & 0xFF  # 4:3031

    @property
    def power_status(self):
        return self.power[2] & 0xFF  # 4:3032

    @property
    def low_battery(self):
        return bool(self.power_status & (POWER_BATTERY_ALARM | POWER_TOO_LOW))

    @property
    def transmitter_temp(self):
        return _float32(self.power, 13)  # 4:3043

    @property
    def power_source(self):
        return "Mains" if self.on_mains else "Battery"

    @property
    def status_text(self):
        return ", ".join(self.faults) or "OK"

"""
A Modbus TCP server that looks like a Siemens SITRANS F M MAG 8000 flow meter.

Register numbers are as listed in the Siemens manual; the address on the wire
is the listed number minus one. The simulated meter is ordered in Ml/d and Ml,
runs on battery, and switches its flow on and off every few minutes.
"""

import asyncio
import logging
import os
import random
import struct
import time

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.server import StartAsyncTcpServer

log = logging.getLogger()

FLOW_UNIT_FACTOR = 86.4  # m3/s -> Ml/d
VOLUME_UNIT_FACTOR = 0.001  # m3 -> Ml

FLOWING_SECONDS = 300
STOPPED_SECONDS = 180


def float32(value):
    return list(struct.unpack(">HH", struct.pack(">f", value)))


def total(value):
    """Siemens 'TotalType': signed integer part, then signed fraction x 1e9."""
    number = int(value)
    decimal = int(round((value - number) * 1e9))
    return list(struct.unpack(">4H", struct.pack(">ii", number, decimal)))


def string(text, registers):
    raw = text.encode("ascii").ljust(registers * 2, b"\x00")
    return list(struct.unpack(f">{registers}H", raw))


class Mag8000Simulator:
    def __init__(self, device_id: int, host: str, port: int):
        self.device_id = device_id
        self.host = host
        self.port = port

        self.target_flow = float(os.environ.get("FLOW_ML_DAY", 12))
        self.battery_percent = int(os.environ.get("BATTERY_PERCENT", 85))
        self.totalizer_1 = 1234.5  # Ml
        self.totalizer_2 = -2.0  # Ml
        self.last_update = time.time()
        self.started = time.time()

        self.context = None
        self.is_ready = asyncio.Event()

    async def start_modbus_server(self):
        store = self.context = ModbusSlaveContext(
            hr=ModbusSequentialDataBlock(0x00, [0] * 3100),
        )
        context = ModbusServerContext(slaves=store, single=True)
        identity = ModbusDeviceIdentification(
            info_name={
                "VendorName": "Doover",
                "ProductCode": "MAG8000SIM",
                "VendorUrl": "https://doover.com",
                "ProductName": "Siemens MAG 8000 Simulator",
                "ModelName": "MAG 8000",
                "MajorMinorRevision": "1.0.0",
            }
        )

        self.is_ready.set()
        return await StartAsyncTcpServer(
            context=context,
            identity=identity,
            address=(self.host, self.port),
            framer="socket",
        )

    def set_registers(self, listed: int, values):
        self.context.setValues(0x03, listed - 1, [int(v) & 0xFFFF for v in values])

    @property
    def flow(self):
        """Current flow in Ml/d."""
        elapsed = (time.time() - self.started) % (FLOWING_SECONDS + STOPPED_SECONDS)
        if elapsed > FLOWING_SECONDS:
            return 0.0
        return max(self.target_flow + (random.random() - 0.5) * 0.2, 0)

    def update(self):
        now = time.time()
        flow = self.flow
        self.totalizer_1 += flow * (now - self.last_update) / 86400
        self.last_update = now

        # Units and sensor
        self.set_registers(207, float32(FLOW_UNIT_FACTOR))
        self.set_registers(209, float32(VOLUME_UNIT_FACTOR))
        self.set_registers(211, string("Ml/d", 6))
        self.set_registers(217, string("Ml", 6))
        self.set_registers(224, [150])
        self.set_registers(227, float32(15.12))

        # Measurement
        self.set_registers(3003, float32(flow))
        low_power = self.battery_percent <= 10
        self.set_registers(3017, [0x0010 if low_power else 0])
        self.set_registers(3018, total(self.totalizer_1))
        self.set_registers(3022, total(self.totalizer_2))
        self.set_registers(3026, total(self.totalizer_1))

        # Power
        self.set_registers(3030, [0])  # battery
        self.set_registers(3031, [self.battery_percent])
        self.set_registers(3032, [1 if low_power else 0])
        self.set_registers(3043, float32(28.5))

        return flow

    async def run(self):
        log.info("Starting...")
        t = asyncio.create_task(self.start_modbus_server())

        while True:
            if t.done():
                raise RuntimeError("Modbus server failed.")

            await self.is_ready.wait()
            flow = self.update()
            log.info(f"Flow={flow:.2f} Ml/d, Totalizer 1={self.totalizer_1:.4f} Ml")
            await asyncio.sleep(1)


if __name__ == "__main__":
    sim = Mag8000Simulator(
        int(os.environ.get("DEVICE_ID", 1)),
        os.environ.get("MODBUS_HOST", "127.0.0.1"),
        int(os.environ.get("MODBUS_PORT", 5020)),
    )
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO
    )
    asyncio.run(sim.run())

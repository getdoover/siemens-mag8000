from pathlib import Path

from pydoover import config
from pydoover.config import ApplicationPosition
from pydoover.docker.modbus import ModbusConfig


def mag8000_modbus_config():
    """The bus, defaulting to how the meter ships: 19200 baud, even parity."""
    bus = ModbusConfig()
    bus.serial_baud.default = 19200
    bus.serial_parity.default = "Even"
    return bus


class SiemensMag8000Config(config.Schema):
    modbus_id = config.Integer(
        "Modbus ID", description="Modbus ID for the meter", default=1
    )
    max_flow = config.Integer(
        "Max Flow",
        description="Max flow value for the meter, in ML/day",
        exclusive_minimum=0,
    )
    allow_shutdown = config.Boolean(
        "Allow Shutdown",
        description="Allow shutdown of the pump",
        default=True,
    )
    motor_control_app = config.ApplicationInstall(
        "Pump Control App",
        name="motor_control_app",
        default="",
        description="The motor control install on this device to send a 'stop' "
        "RPC to when the shutdown target is reached, e.g. "
        "'motor_control_3_wire_1'. Leaving it empty sends the stop to every app "
        "on the device that handles one. Only used when Allow Shutdown is on.",
    )
    idle_read_seconds = config.Integer(
        "Idle Read Interval",
        description="Seconds between meter reads while no water is flowing. "
        "Every read uses meter battery.",
        default=900,
        minimum=30,
    )
    flow_read_seconds = config.Integer(
        "Flowing Read Interval",
        description="Seconds between meter reads while water is flowing, and "
        "at all times on a mains powered meter.",
        default=60,
        minimum=10,
    )
    position = ApplicationPosition()
    modbus_config = mag8000_modbus_config()


def export():
    SiemensMag8000Config.export(
        Path(__file__).parents[2] / "doover_config.json",
        "siemens_mag8000",
    )

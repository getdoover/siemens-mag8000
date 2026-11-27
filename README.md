# Siemens MAG 8000

<img src="https://doover.com/wp-content/uploads/Doover-Logo-Landscape-Navy-padded-small.png" alt="App Icon" style="max-width: 300px;">

**Doover application for reading a Siemens SITRANS F M MAG 8000 water meter over Modbus RTU**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/getdoover/siemens-mag8000/blob/main/LICENSE)

[Getting Started](#getting-started) • [Configuration](#configuration) • [Developer](https://github.com/getdoover/siemens-mag8000/blob/main/DEVELOPMENT.md) • [Need Help?](#need-help)

<br/>

## Overview

This application reads a Siemens SITRANS F M MAG 8000 electromagnetic water meter through its RS485 Modbus RTU module, and provides flow monitoring, event-based alerting and pump shutdown control through the Doover platform.

- **Flow and totals** -- flow rate in ML/day, Totalizer 1 and Totalizer 2 in ML, whatever units the meter was ordered in
- **Event-based alerting** -- tracks water volume per pumping event and sends a notification at a target volume
- **Pump shutdown control** -- stops the pump when an event volume target is reached
- **Battery-aware reading** -- reads a battery powered meter rarely while idle, more often while water is flowing, and half as often when the meter reports low battery
- **Meter health** -- fault status, power source, battery capacity and transmitter temperature

<br/>

## Getting Started

### Meter requirements

- The meter needs the RS485 Modbus RTU add-on module (FDK:087L4212).
- Factory communication settings are slave address 1, 19200 baud, 8 data bits, even parity, 1 stop bit. These are the app's defaults.
- Wire the module's two data terminals and common to the Doovit's RS485 port. If the meter does not answer, swap the two data wires.
- Even parity needs Doovit firmware 1.9.6 or later.

Siemens designed the Modbus module for mains powered meters and warns that using it on a battery powered meter shortens battery life. The read intervals below are how the app limits that.

### Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| **Modbus ID** | Slave address of the meter | `1` |
| **Max Flow** | Maximum expected flow rate (ML/day), used for gauge scaling and to tell when water is flowing | *required* |
| **Allow Shutdown** | Enable the app to trigger pump shutdown when a volume target is reached | `true` |
| **Pump Control App** | Install to send the `stop` RPC to on shutdown; blank reaches every app on the device handling `stop` | blank |
| **Idle Read Interval** | Seconds between reads while no water is flowing | `900` |
| **Flowing Read Interval** | Seconds between reads while water is flowing, and at all times on a mains powered meter | `60` |
| **Modbus Config** | Modbus connection settings | serial, 19200 baud, even parity |

**Get Now** in the app reads the meter straight away and keeps reading every 10 seconds for 90 seconds.

<br/>

## Integrations

### Tags

This app exposes the following tags for use by other applications (e.g. pump controllers):

| Tag | Type | Description |
|-----|------|-------------|
| **alert_triggered** | boolean | Set to `true` when the pump shutdown volume target is exceeded |
| **alert_message_short** | string | Short description of the shutdown reason |
| **alert_message_long** | string | Detailed shutdown message including the volume reached |

### RPC

On reaching the pump shutdown target the app also calls `stop` on the default
`dv-rpc` channel, with `{"reason": "..."}` naming the volume reached.
This is what the **3-Wire Motor Control** app listens for. The tags above are
set on the same event and are kept for pump apps that watch them instead --
both fire, always.

### Dependencies

- **Modbus Interface** (`modbus_interface`) -- provides the Modbus bus this app reads the meter through

<br/>

### Need Help?

- Email: support@doover.com
- [Doover Documentation](https://docs.doover.com)
- [Developer Guide](https://github.com/getdoover/siemens-mag8000/blob/main/DEVELOPMENT.md)

<br/>

## License

This app is licensed under the [Apache License 2.0](https://github.com/getdoover/siemens-mag8000/blob/main/LICENSE).

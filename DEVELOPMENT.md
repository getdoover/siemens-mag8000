# Siemens MAG 8000 -- Development Guide

## Repository Structure

```
README.md               <-- User-facing app description
DEVELOPMENT.md          <-- This file
pyproject.toml          <-- Python project config and dependencies
Dockerfile              <-- Production Docker image
doover_config.json      <-- Doover platform metadata

src/siemens_mag8000/
  __init__.py           <-- Entry point (main function)
  application.py        <-- Core application logic and UI handlers
  app_config.py         <-- Configuration schema
  app_tags.py           <-- Declarative tags (display state, thresholds, pump control)
  app_ui.py             <-- UI definition (flow gauge, event counters, maintenance)
  app_state.py          <-- State machine and read intervals
  record.py             <-- MAG 8000 register blocks and decoding

simulators/
  app_config.json       <-- Sample config for local development
  docker-compose.yml    <-- Orchestrates the simulator and the app
  mag8000_sim/
    main.py             <-- Modbus TCP server emulating a MAG 8000

tests/
  test_imports.py       <-- Import and schema checks
  test_record.py        <-- Register decoding, against data read from a real meter
  test_state.py         <-- Read interval rules
```

## Getting Started

```bash
uv sync
uv run pytest tests/
```

### Run locally (with simulator)

The simulator is a Modbus TCP server on port 5020 that emulates a battery powered MAG 8000 ordered in Ml/d, with its flow switching on and off every few minutes.

```bash
cd simulators
docker compose up --build
```

## Architecture

```
MAG 8000  -->  Modbus RTU (RS485)  -->  modbus_interface  -->  Application  -->  Doover Platform
```

### State Machine

The meter is always on, so "sleeping" only means the app is leaving it alone. Every request costs meter battery.

| State | Description | Timeout |
|-------|-------------|---------|
| `initial` | Startup, transitions immediately to `awake_init` | -- |
| `sleeping` | No Modbus requests | see below |
| `awake_init` | Reading the meter. One good reading sends it back to `sleeping`, or on to `awake_rt` after "Get Now" | 30s |
| `awake_rt` | Reading every 10 seconds, after "Get Now" | 1.5 min |

Time spent sleeping (`get_sleep_time` in `app_state.py`):

| Meter | Sleep |
|-------|-------|
| Battery, no flow | Idle Read Interval (15 min) |
| Battery, flowing | Flowing Read Interval (60 s) |
| Battery, low battery reported | twice the above |
| Mains | Flowing Read Interval |

"Flowing" means either of the last two readings was above 5% of Max Flow. While an event target is set the app also wakes just after the projected time the target is reached, unless the meter reports low battery.

### Modbus Registers

Register numbers are as listed in the Siemens *MAG 8000 Modbus RTU Operating Instructions* (A5E03409989). The address on the wire is the listed number minus one. All reads are holding registers (pydoover `register_type=4`), and the meter allows at most 26 registers per request.

The app reads three blocks:

| Block | Registers | Read |
|-------|-----------|------|
| Units | 4:0207 -- 4:0228 | At startup, then daily |
| Measurement | 4:3003 -- 4:3028 | Every wake |
| Power | 4:3030 -- 4:3044 | Every wake |

| Register | Type | Description |
|----------|------|-------------|
| 4:0207 | float32 | Flow unit factor (m3/s to meter flow unit) |
| 4:0209 | float32 | Volume unit factor (m3 to meter volume unit) |
| 4:0211 / 4:0217 | string | Flow / volume unit text |
| 4:0224 | uint16 | Pipe size (mm) |
| 4:0227 | float32 | Nominal flow Qn (meter flow unit) |
| 4:3003 | float32 | Flow rate (meter flow unit) |
| 4:3017 | uint16 | Fault status bits |
| 4:3018 | totaltype | Totalizer 1 (meter volume unit) |
| 4:3022 | totaltype | Totalizer 2 (meter volume unit) |
| 4:3030 | uint8 | Power supply: 0 = battery, 1 = mains |
| 4:3031 | uint8 | Battery capacity (%) |
| 4:3032 | uint8 | Power status bits: 1 = battery alarm, 2 = too low, 4 = external power gone |
| 4:3043 | float32 | Transmitter temperature (degC) |

- float32 is big-endian, high word first.
- "totaltype" is two signed 32-bit integers: the integer part, then the fraction multiplied by 1e9.
- Flow and volume registers are in the units the meter was ordered in. The app divides by the unit factors to get back to m3/s and m3, then converts to ML/day and ML.

### Tags

Tags in `app_tags.py` hold display state bound to UI elements, persisted state (event counter baseline, last non-zero flow time), and the cross-app pump control tags `alert_triggered`, `alert_message_short` and `alert_message_long`.

### UI Handlers

| Handler | Trigger | Action |
|---------|---------|--------|
| `reset_event` | "Reset Event" | Resets the event counter baseline and clears the targets |
| `get_now` | "Get Now" | Reads the meter now and keeps reading for 90 seconds |

## Publishing

CI (`.github/workflows/doover-app.yml`) lints, tests, builds and publishes on every push to `main`; pull requests publish an alpha release. `config_schema` and `ui_schema` are generated at publish time and are not committed.

## Testing against a real meter

`modpoll` reads the flow rate like this (reference numbers are 1-based, so they match the Siemens listing):

```bash
modpoll -m rtu -b 19200 -d 8 -s 1 -p even -t 4:hex -a 1 -r 3003 -c 2 -1 /dev/ttyAMA0
```

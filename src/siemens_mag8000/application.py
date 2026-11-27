import asyncio
import logging
import time

from pydoover import rpc, ui
from pydoover.docker import Application

from .app_config import SiemensMag8000Config
from .app_tags import SiemensMag8000Tags
from .app_ui import SiemensMag8000UI
from .app_state import SiemensMag8000State
from .app_state import get_sleep_time
from .record import MEASUREMENT_BLOCK, POWER_BLOCK, UNITS_BLOCK, Record, Units

log = logging.getLogger()

REGISTER_TYPE = 4  # holding registers

# The meter's units don't change in service, so they are only re-read daily.
UNITS_REFRESH_SECONDS = 60 * 60 * 24

ALERT_MESSAGE = "by water meter target"
ALERT_MESSAGE_LONG = "after the meter reached {}ML"

MOTOR_CONTROL_STOP_TIMEOUT = 30.0


class SiemensMag8000Application(Application):
    config: SiemensMag8000Config
    tags: SiemensMag8000Tags

    config_cls = SiemensMag8000Config
    tags_cls = SiemensMag8000Tags
    ui_cls = SiemensMag8000UI

    async def setup(self):
        self.state = SiemensMag8000State()

        self.last_flow: float | None = None
        self.prev_non_null_flow = None
        self.last_non_null_flow = None

        self.units: Units | None = None
        self.last_record: Record | None = None
        self.last_request_time: float = 0
        self.min_request_interval = 10

    async def main_loop(self):
        log.info(f"State: {self.state.state}, Flow: {self.last_flow}")
        # Update display name with current flow
        if self.last_flow is not None:
            if self.last_flow == 0:
                display_string = "0 ML/day"
            elif self.last_flow < 10:
                display_string = f"{round(self.last_flow, 1)} ML/day"
            else:
                display_string = f"{round(self.last_flow, 0)} ML/day"
        else:
            display_string = " - ML/day"

        await self.tags.app_display_name.set(
            f"{self.app_display_name}: {display_string}"
        )

        # Update UI via tags
        await self._update_display_tags()
        await self._update_event_ranges()
        await self._update_shutdown_eta()

        # Spin state machine. How long it sleeps depends on whether water is
        # flowing and on how the meter is powered.
        record = self.last_record
        sleep_time = get_sleep_time(
            record,
            self.is_pumping,
            self.config.idle_read_seconds.value,
            self.config.flow_read_seconds.value,
        )
        low_battery = bool(record and record.low_battery)
        await self.state.spin(sleep_time, low_battery, self._next_target_eta())
        if self.state.should_request:
            await self._send_request()

        # State-specific logic
        match self.state.state:
            case "sleeping":
                pass
            case "awake_init":
                # One good reading is all a wake-up needs, unless the user
                # asked to watch the meter live.
                if self.last_record and self.last_record.ts >= self.state.woke_at:
                    if self.state.stay_awake:
                        await self.state.initialised()
                    else:
                        await self.state.goto_sleep()
            case "awake_rt":
                await self._send_request()

        # Update counter tracking
        if self.last_record is not None:
            if self.last_flow and self.last_flow > 1:
                await self.tags.last_time_non_zero_flow.set(time.time())

            total = self.last_record.total
            last_non_zero = self.tags.last_time_non_zero_flow.value or 0
            if total is not None and time.time() - last_non_zero > (60 * 60 * 24 * 5):
                await self.tags.last_event_counter_zero.set(total)

        await self._check_for_total_alert()
        await self._check_for_pump_shutdown()

    async def _update_display_tags(self):
        await self.tags.last_flow.set(self.last_flow)
        await self.tags.comms_active.set(
            self.state.state != "sleeping" if self.state else False
        )

        if self.last_record is None:
            return

        record = self.last_record
        await self.tags.last_total.set(record.total)
        await self.tags.last_total_2.set(record.total_2)
        await self.tags.time_last_update.set(int(record.ts * 1000))
        await self.tags.meter_status.set(record.status_text)
        await self.tags.power_source.set(record.power_source)
        await self.tags.battery_percent.set(record.battery_percent)
        await self.tags.transmitter_temp.set(record.transmitter_temp)

        total = self.last_record.total
        counter_zero = self.tags.last_event_counter_zero.value
        if total is not None and counter_zero is not None:
            await self.tags.last_event_counter.set(total - counter_zero)

    def _event_targets(self):
        """The event targets the user has set, as (label, ML) pairs, ascending."""
        targets = []

        alert = self.ui_manager.get_value("alert_counter")
        if alert:
            targets.append(("Alert", alert))

        if self.config.allow_shutdown.value:
            shutdown = self.ui_manager.get_value("shutdown_counter")
            if shutdown:
                targets.append(("Shutdown", shutdown))

        targets.sort(key=lambda target: target[1])
        return targets

    async def _update_event_ranges(self):
        """Publish the event total's gauge segments, one per target.

        Both targets set gives two segments, so the operator can see the alert
        boundary partway along a bar that ends where the pump stops. One target
        gives a single bar that fills as the event runs up to it, and no target
        gives no segments at all, which the site renders as a plain reading.
        """
        ranges, lower, previous = [], 0, None

        for label, value in self._event_targets():
            if value <= lower:
                # Both targets on the same total -- one segment says it all.
                continue

            ranges.append(
                ui.Range(
                    previous or f"Below {label}",
                    lower,
                    value,
                    ui.Colour.green if previous is None else ui.Colour.yellow,
                ).to_dict()
            )
            lower, previous = value, label

        await self.tags.event_ranges.set(ranges)

    async def _update_shutdown_eta(self):
        """Publish when the event will hit the shutdown target at today's flow.

        A straight-line estimate from the remaining ML and the latest flow
        reading, so it moves as the flow does. Cleared when there's nothing to
        count down to: no target, no reading yet, or the pump isn't running.
        """
        eta = None

        threshold = (
            self.ui_manager.get_value("shutdown_counter")
            if self.config.allow_shutdown.value
            else None
        )
        total = self.last_record and self.last_record.total
        counter_zero = self.tags.last_event_counter_zero.value

        if (
            threshold
            and total is not None
            and counter_zero is not None
            and self.is_pumping
            and self.last_flow
        ):
            remaining = max(threshold - (total - counter_zero), 0)
            time_left_ms = remaining / self.last_flow * 86400 * 1000
            # From the reading's own time, so the estimate holds still while
            # the meter sleeps rather than creeping later every loop.
            eta = int(self.last_record.ts * 1000 + time_left_ms)

            # Flow wobbles every reading, so only publish when the estimate
            # has moved enough to matter -- otherwise the tag changes each loop.
            current = self.tags.shutdown_eta.value
            if current is not None and abs(eta - current) < max(
                60_000, time_left_ms * 0.01
            ):
                return

        await self.tags.shutdown_eta.set(eta)

    def _next_target_eta(self):
        """When the event will reach its nearest unreached target, in epoch seconds.

        Projected from the latest reading and flow, so the meter can wake to
        read just after the crossing instead of up to a full sleep later.
        None while the pump isn't running or there's no target ahead.
        """
        record = self.last_record
        counter_zero = self.tags.last_event_counter_zero.value
        if record is None or record.total is None or counter_zero is None:
            return None
        if not (self.is_pumping and self.last_flow):
            return None

        event_total = record.total - counter_zero
        remaining = [
            value - event_total
            for _, value in self._event_targets()
            if value >= event_total
        ]
        if not remaining:
            return None

        return record.ts + min(remaining) / self.last_flow * 86400

    async def _check_for_total_alert(self):
        threshold = self.ui_manager.get_value("alert_counter")
        if self._counter_exceeds(threshold):
            await self.create_message(
                "notifications",
                {
                    "message": (
                        f"{self.app_display_name} has reached "
                        f"{threshold} ML during this event"
                    )
                },
            )
            await self.ui_manager.set_value("alert_counter", None)

    async def _check_for_pump_shutdown(self):
        if not self.config.allow_shutdown.value:
            return

        threshold = self.ui_manager.get_value("shutdown_counter")
        if self._counter_exceeds(threshold):
            log.info(
                f"Water meter {self.app_display_name} has reached "
                f"event shutdown target of {threshold}"
            )
            # Two ways of saying the same thing. The tags are the original
            # signal and older pump apps still watch them; the RPC is the one
            # that gets an acknowledgement back. Both fire, always.
            await self.tags.alert_triggered.set(True)
            await self.tags.alert_message_short.set(ALERT_MESSAGE)
            await self.tags.alert_message_long.set(ALERT_MESSAGE_LONG.format(threshold))
            asyncio.create_task(self._send_stop_rpc(threshold))
            await self.ui_manager.set_value("shutdown_counter", None)

    async def _send_stop_rpc(self, threshold):
        """Ask the pump control app to stop, and log whether it did.

        Fired as a background task: the round trip is seconds long and the
        main loop must not wait on a pump app that is slow, missing or
        misconfigured. Never raises, for the same reason.
        """
        app_key = str(self.config.motor_control_app.value or "")
        reason = f"{ALERT_MESSAGE} {ALERT_MESSAGE_LONG.format(threshold)}"

        # On the shared dv-rpc channel an empty app key reaches every app on
        # the device that handles "stop", so the install should be named.
        if not app_key:
            log.warning("No pump control app configured; stopping any 'stop' handler")

        try:
            result = await self.rpc.call(
                "stop",
                params={"reason": reason},
                channel=rpc.DEFAULT_CHANNEL,
                app_key=app_key,
                timeout=MOTOR_CONTROL_STOP_TIMEOUT,
            )
        except Exception:
            log.warning(
                "Stop RPC to %s failed -- the alert tags were still set",
                app_key or "every stop handler",
                exc_info=True,
            )
            return

        log.info("Stop RPC acknowledged by %s: %s", app_key or "listener", result)

    async def _read_block(self, block):
        """Read one block of holding registers, or None if the meter didn't answer."""
        listed, count = block
        try:
            result = await self.modbus_iface.read_registers(
                bus_id=self.config.modbus_config.name.value,
                modbus_id=self.config.modbus_id.value,
                start_address=listed - 1,
                num_registers=count,
                register_type=REGISTER_TYPE,
            )
        except Exception as e:
            log.info(f"Failed to send modbus request: {e}")
            return None

        # read_registers returns None (rather than raising) when the bus is
        # unavailable or the meter stays silent.
        if result is None:
            return None

        values = list(result)
        if len(values) != count:
            log.info(f"Expected {count} registers from {listed}, got {len(values)}")
            return None
        return values

    async def _read_units(self):
        if self.units and time.time() - self.units.ts < UNITS_REFRESH_SECONDS:
            return self.units

        values = await self._read_block(UNITS_BLOCK)
        if values is None:
            return self.units

        units = Units(values)
        if not units.is_valid:
            log.warning(f"Meter reported unusable unit factors: {values}")
            return self.units

        log.info(
            f"Meter units: {units.flow_unit} / {units.volume_unit}, "
            f"DN{units.pipe_size_mm}, Qn {units.nominal_flow} ML/day"
        )
        self.units = units
        return units

    async def _send_request(self):
        if time.time() - self.last_request_time < self.min_request_interval:
            log.debug("Not enough time since last request")
            return

        log.debug("Sending modbus request")
        self.last_request_time = time.time()

        units = await self._read_units()
        measurement = units and await self._read_block(MEASUREMENT_BLOCK)
        power = measurement and await self._read_block(POWER_BLOCK)
        if not power:
            log.info("No reading from the meter, keeping last record")
            await self.tags.meter_responding.set(False)
            return

        await self.tags.meter_responding.set(True)
        self.last_record = Record(units, measurement, power)

        self.last_flow = self.last_record.current_flow
        log.info(
            f"Flow: {self.last_flow} ML/day, total: {self.last_record.total} ML, "
            f"status: {self.last_record.status_text}"
        )
        self.prev_non_null_flow = self.last_non_null_flow
        self.last_non_null_flow = self.last_flow

        return self.last_record

    def _counter_exceeds(self, value):
        if value is None or self.last_record is None:
            return False

        total = self.last_record.total
        counter_zero = self.tags.last_event_counter_zero.value

        if total is None or counter_zero is None:
            return False

        return total - counter_zero > value

    @property
    def is_pumping(self):
        max_flow = self.config.max_flow.value * 0.05
        if self.last_non_null_flow is not None and self.last_non_null_flow > max_flow:
            return True
        if self.prev_non_null_flow is not None and self.prev_non_null_flow > max_flow:
            return True
        return False

    # --- UI Handlers ---

    @ui.handler("reset_event")
    async def on_reset_event(self, ctx, value):
        total = self.last_record and self.last_record.total
        if total is None:
            log.info(
                "Failed to reset water meter event total - no last record / total."
            )
            return

        log.info(f"Resetting water meter event total for {self.app_display_name}")
        await self.tags.last_event_counter_zero.set(total)

        await self.ui_manager.set_value("alert_counter", None)
        await self.ui_manager.set_value("shutdown_counter", None)

    @ui.handler("get_now")
    async def on_get_now(self, ctx, value):
        log.info("Get now action triggered")
        self.state.stay_awake = True
        if self.state.state == "sleeping":
            await self.state.awaken()

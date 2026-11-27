import logging
import time

from pydoover.state import StateMachine


DEFAULT_IDLE_SLEEP = 60 * 15  # between reads while nothing is flowing
DEFAULT_FLOW_SLEEP = 60  # between reads while water is flowing
DEFAULT_AWAKE_TIME = 60 * 1.5  # live reading after "Get Now"
DEFAULT_READ_TIMEOUT = 30  # give up on a read and go back to sleep

# Every request costs the meter battery, so a meter reporting low battery is
# read this many times less often.
LOW_BATTERY_SLEEP_FACTOR = 2

# Waking early for an event target: read this long after the projected
# crossing, never after less than this much sleep, and never on a low battery.
EARLY_WAKE_MARGIN = 60
MIN_SLEEP_TIME = 60


log = logging.getLogger(__name__)


def get_sleep_time(
    record,
    flowing: bool,
    idle_sleep: float = DEFAULT_IDLE_SLEEP,
    flow_sleep: float = DEFAULT_FLOW_SLEEP,
) -> float:
    """Seconds to leave the meter alone before the next read."""
    if record is None:
        return idle_sleep
    if record.on_mains:
        # Nothing to conserve.
        return flow_sleep

    sleep = flow_sleep if flowing else idle_sleep
    if record.low_battery:
        sleep *= LOW_BATTERY_SLEEP_FACTOR
    return sleep


class SiemensMag8000State:
    state: str

    states = [
        {"name": "initial"},
        {"name": "sleeping", "timeout": DEFAULT_IDLE_SLEEP, "on_timeout": "awaken"},
        {
            "name": "awake_init",
            "timeout": DEFAULT_READ_TIMEOUT,
            "on_timeout": "goto_sleep",
        },
        {"name": "awake_rt", "timeout": DEFAULT_AWAKE_TIME, "on_timeout": "goto_sleep"},
    ]

    transitions = [
        {"trigger": "initialise", "source": "initial", "dest": "awake_init"},
        {"trigger": "awaken", "source": "sleeping", "dest": "awake_init"},
        {"trigger": "initialised", "source": "awake_init", "dest": "awake_rt"},
        {"trigger": "goto_sleep", "source": "awake_init", "dest": "sleeping"},
        {"trigger": "goto_sleep", "source": "awake_rt", "dest": "sleeping"},
    ]

    def __init__(self):
        self.state_machine = StateMachine(
            states=self.states,
            transitions=self.transitions,
            model=self,
            initial="initial",
            queued=True,
        )

        self.should_request = False
        self.slept_at: float = 0
        self.woke_at: float = 0
        # Set by "Get Now": stay awake and keep reading for a while, rather
        # than taking one reading and going straight back to sleep.
        self.stay_awake = False

    async def spin(
        self, sleep_time: float, low_battery: bool, wake_at: float | None = None
    ):
        """Advance the state machine.

        ``wake_at`` is when the event is projected to reach its next target, in
        epoch seconds. The sleep timeout is only read on entering the sleeping
        state, so waking early for a target has to happen here instead.
        """
        self.state_machine.get_state("sleeping").timeout = sleep_time

        if self.state == "initial":
            await self.initialise()
        elif self.state == "sleeping" and self._should_wake_early(low_battery, wake_at):
            log.info("Waking early to read the meter as it reaches an event target")
            await self.awaken()

    def _should_wake_early(self, low_battery, wake_at) -> bool:
        if wake_at is None or low_battery:
            return False

        now = time.time()
        return (
            now - self.slept_at >= MIN_SLEEP_TIME and now >= wake_at + EARLY_WAKE_MARGIN
        )

    async def on_enter_sleeping(self):
        self.should_request = False
        self.stay_awake = False
        self.slept_at = time.time()

    async def on_enter_awake_init(self):
        self.should_request = True
        self.woke_at = time.time()

    async def on_enter_awake_rt(self):
        self.should_request = True

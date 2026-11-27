from pydoover import ui

from .app_config import SiemensMag8000Config
from .app_tags import SiemensMag8000Tags


class SiemensMag8000UI(ui.UI, display_name=SiemensMag8000Tags.app_display_name):
    config: SiemensMag8000Config

    tabs = ui.TabContainer(
        display_name="Tabs",
        children=[
            ui.Container(
                "Meter",
                children=[
                    ui.NumericVariable(
                        "Flow",
                        units="ML/day",
                        value=SiemensMag8000Tags.last_flow,
                        form=ui.Widget.radial,
                    ),
                    ui.NumericVariable(
                        "Meter Total",
                        units="ML",
                        value=SiemensMag8000Tags.last_total,
                    ),
                    ui.NumericVariable(
                        "Totalizer 2",
                        units="ML",
                        value=SiemensMag8000Tags.last_total_2,
                    ),
                    ui.Timestamp(
                        "Last Read",
                        value=SiemensMag8000Tags.time_last_update,
                    ),
                    ui.Button("Get Now"),
                ],
            ),
            ui.Container(
                "Event",
                children=[
                    ui.NumericVariable(
                        "This Event",
                        units="ML",
                        value=SiemensMag8000Tags.last_event_counter,
                        icon="fa-solid fa-water",
                        form=ui.Widget.linear,
                        # Bounds are whatever targets the user has set, so they
                        # come from a tag rather than this schema.
                        ranges=SiemensMag8000Tags.event_ranges,
                    ),
                    ui.FloatInput(
                        "Send Alert At",
                        name="alert_counter",
                        units="ML",
                        min_val=0,
                        icon="fa-solid fa-bell",
                        help_str="Send a notification when event total reaches this value (ML)",
                        default=None,
                    ),
                    ui.FloatInput(
                        "Shutdown Pump At",
                        name="shutdown_counter",
                        units="ML",
                        min_val=0,
                        icon="fa-solid fa-power-off",
                        help_str="Stop pumping when event total reaches this value (ML)",
                        default=None,
                    ),
                    ui.Timestamp(
                        "Ends At",
                        name="shutdown_eta",
                        value=SiemensMag8000Tags.shutdown_eta,
                        icon="fa-solid fa-hourglass-half",
                    ),
                    ui.Button("Reset Event", requires_confirm=True),
                ],
            ),
        ],
    )

    maintenance = ui.Submodule(
        "Maintenance",
        children=[
            ui.TextVariable(
                "Meter Status",
                value=SiemensMag8000Tags.meter_status,
            ),
            ui.TextVariable(
                "Power Source",
                value=SiemensMag8000Tags.power_source,
            ),
            ui.NumericVariable(
                "Battery",
                units="%",
                value=SiemensMag8000Tags.battery_percent,
                precision=0,
                ranges=[
                    ui.Range("Low", 0, 10, ui.Colour.red),
                    ui.Range("OK", 10, 40, ui.Colour.yellow),
                    ui.Range("Good", 40, 100, ui.Colour.green),
                ],
            ),
            ui.NumericVariable(
                "Transmitter Temp",
                units="°C",
                value=SiemensMag8000Tags.transmitter_temp,
                precision=1,
            ),
            ui.BooleanVariable(
                "Meter Responding",
                value=SiemensMag8000Tags.meter_responding,
            ),
            ui.BooleanVariable(
                "Comms Active",
                value=SiemensMag8000Tags.comms_active,
            ),
        ],
        is_collapsed=True,
    )

    async def setup(self):
        max_flow = self.config.max_flow.value

        for elem in (
            self.tabs.meter.flow,
            self.tabs.meter.meter_total,
            self.tabs.meter.totalizer_2,
            self.tabs.event.this_event,
        ):
            elem.precision = 1 if max_flow >= 100 else 2

        self.tabs.meter.flow.ranges = [
            ui.Range(None, 0, max_flow * 0.15, ui.Colour.blue),
            ui.Range(None, max_flow * 0.15, max_flow, ui.Colour.green),
        ]

        self.tabs.event.shutdown_counter.hidden = not self.config.allow_shutdown.value
        self.tabs.event.shutdown_eta.hidden = not self.config.allow_shutdown.value


def export():
    from pathlib import Path

    SiemensMag8000UI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json",
        "siemens_mag8000",
    )

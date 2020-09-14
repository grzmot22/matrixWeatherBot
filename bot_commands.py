
from chat_functions import send_text_to_room
import logging
from decimal import Decimal

# import needed for bme280 sensor
import smbus2
import bme280

# setup sensor bme280
port = 1
address = 0x76
bus = smbus2.SMBus(port)
calibration_params = bme280.load_calibration_params(bus, address)

logger = logging.getLogger(__name__)


class Command(object):
    def __init__(self, client, store, config, command, room, event):
        """A command made by a user

        Args:
            client (nio.AsyncClient): The client to communicate to matrix with

            store (Storage): Bot storage

            config (Config): Bot configuration parameters

            command (str): The command and arguments

            room (nio.rooms.MatrixRoom): The room the command was sent in

            event (nio.events.room_events.RoomMessageText): The event describing the command
        """
        self.client = client
        self.store = store
        self.config = config
        self.command = command
        self.room = room
        self.event = event
        self.args = self.command.split()[1:]

    async def process(self):
        """Process the command"""
        logger.debug("Got command from %s: %r",
                     self.event.sender, self.command)
        trigger = self.command.lower().split(maxsplit=1)[0]
        if trigger.startswith("echo"):
            await self._echo()
        elif trigger.startswith("help"):
            await self._show_help()
        elif trigger.startswith("weather"):
            await self._show_weather_bme280()
        else:
            await self._unknown_command()

    async def _echo(self):
        """Echo back the command's arguments"""
        response = " ".join(self.args)
        await send_text_to_room(self.client, self.room.room_id, response)

    async def _show_help(self):
        """Show the help text"""
        if not self.args:
            text = (
                "Hello, I am a bot made with matrix-nio! Use `help commands` to view "
                "available commands."
            )
            await send_text_to_room(self.client, self.room.room_id, text)
            return

        topic = self.args[0]
        if topic == "rules":
            text = "These are the rules!"
        elif topic == "commands":
            text = "Available commands: weather, echo"
        else:
            text = "Unknown help topic!"
        await send_text_to_room(self.client, self.room.room_id, text)

    async def _show_weather_bme280(self):
        data = bme280.sample(bus, address, calibration_params)
        await send_text_to_room(
            self.client,
            self.room.room_id,
            f"Current temperature {round(Decimal(data.temperature))} C, pressure {round(Decimal(data.pressure))}HPa and humidity {round(Decimal(data.humidity))}%",
        )

    async def _unknown_command(self):
        await send_text_to_room(
            self.client,
            self.room.room_id,
            f"Unknown command '{self.command}'. Try the 'help' command for more information.",
        )

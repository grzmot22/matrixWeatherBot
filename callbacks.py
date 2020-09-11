import traceback
from bot_commands import Command
from nio import (
    JoinError,
    MatrixRoom,
    UnknownEvent,
    KeyVerificationCancel,
    KeyVerificationEvent,
    KeyVerificationKey,
    KeyVerificationMac,
    KeyVerificationStart,
    LocalProtocolError,
    ToDeviceError,
    UpdateDeviceError
)
from message_responses import Message

import logging

logger = logging.getLogger(__name__)


class Callbacks(object):

    def __init__(self, client, store, config):
        """
        Args:
            client (nio.AsyncClient): nio client used to interact with matrix

            store (Storage): Bot storage

            config (Config): Bot configuration parameters
        """
        self.client = client
        self.store = store
        self.config = config
        self.command_prefix = config.command_prefix
    async def to_device_callback(self, event):
        """Handle events sent to device."""
        try:
            client = self.client

            if isinstance(event, KeyVerificationStart):  # first step
                if "emoji" not in event.short_authentication_string:
                    print(
                        "Other device does not support emoji verification "
                        f"{event.short_authentication_string}."
                    )
                    return
                resp = await client.accept_key_verification(
                    event.transaction_id
                )
                if isinstance(resp, ToDeviceError):
                    print(f"accept_key_verification failed with {resp}")

                sas = client.key_verifications[event.transaction_id]

                to_device_msg = sas.share_key()
                resp = await client.to_device(to_device_msg)
                if isinstance(resp, ToDeviceError):
                    print(f"to_device failed with {resp}")

            elif isinstance(event, KeyVerificationCancel):  # anytime
                """ at any time: receive KeyVerificationCancel
                KeyVerificationCancel(source={
                    'content': {'code': 'm.mismatched_sas',
                                'reason': 'Mismatched authentication string',
                                'transaction_id': 'SomeTxId'},
                    'type': 'm.key.verification.cancel',
                    'sender': '@user2:example.org'},
                    sender='@user2:example.org',
                    transaction_id='SomeTxId',
                    code='m.mismatched_sas',
                    reason='Mismatched short authentication string')
                """

                # There is no need to issue a
                # client.cancel_key_verification(tx_id, reject=False)
                # here. The SAS flow is already cancelled.
                # We only need to inform the user.
                print(
                    f"Verification has been cancelled by {event.sender} "
                    f'for reason "{event.reason}".'
                )

            elif isinstance(event, KeyVerificationKey):  # second step
                """ Second step is to receive KeyVerificationKey
                KeyVerificationKey(
                    source={'content': {
                            'key': 'SomeCryptoKey',
                            'transaction_id': 'SomeTxId'},
                        'type': 'm.key.verification.key',
                        'sender': '@user2:example.org'
                    },
                    sender='@user2:example.org',
                    transaction_id='SomeTxId',
                    key='SomeCryptoKey')
                """
                sas = client.key_verifications[event.transaction_id]

                print(f"{sas.get_emoji()}")

                yn = input("Do the emojis match? (Y/N) (C for Cancel) ")
                if yn.lower() == "y":
                    print(
                        "Match! The verification for this "
                        "device will be accepted."
                    )
                    resp = await client.confirm_short_auth_string(
                        event.transaction_id
                    )
                    if isinstance(resp, ToDeviceError):
                        print(f"confirm_short_auth_string failed with {resp}")
                elif yn.lower() == "n":  # no, don't match, reject
                    print(
                        "No match! Device will NOT be verified "
                        "by rejecting verification."
                    )
                    resp = await client.cancel_key_verification(
                        event.transaction_id, reject=True
                    )
                    if isinstance(resp, ToDeviceError):
                        print(f"cancel_key_verification failed with {resp}")
                else:  # C or anything for cancel
                    print("Cancelled by user! Verification will be cancelled.")
                    resp = await client.cancel_key_verification(
                        event.transaction_id, reject=False
                    )
                    if isinstance(resp, ToDeviceError):
                        print(f"cancel_key_verification failed with {resp}")

            elif isinstance(event, KeyVerificationMac):  # third step
                """ Third step is to receive KeyVerificationMac"""
                sas = client.key_verifications[event.transaction_id]
                try:
                    to_device_msg = sas.get_mac()
                except LocalProtocolError as e:
                    # e.g. it might have been cancelled by ourselves
                    print(
                        f"Cancelled or protocol error: Reason: {e}.\n"
                        f"Verification with {event.sender} not concluded. "
                        "Try again?"
                    )
                else:
                    resp = await client.to_device(to_device_msg)
                    if isinstance(resp, ToDeviceError):
                        print(f"to_device failed with {resp}")
                    print(
                        f"sas.we_started_it = {sas.we_started_it}\n"
                        f"sas.sas_accepted = {sas.sas_accepted}\n"
                        f"sas.canceled = {sas.canceled}\n"
                        f"sas.timed_out = {sas.timed_out}\n"
                        f"sas.verified = {sas.verified}\n"
                        f"sas.verified_devices = {sas.verified_devices}\n"
                    )
                    print(
                        "Emoji verification was successful!\n"
                        "Hit Control-C to stop the program or "
                        "initiate another Emoji verification from "
                        "another device or room."
                    )
            else:
                print(
                    f"Received unexpected event type {type(event)}. "
                    f"Event is {event}. Event will be ignored."
                )
        except BaseException:
            print(traceback.format_exc())

    async def message(self, room, event):
        """Callback for when a message event is received

        Args:
            room (nio.rooms.MatrixRoom): The room the event came from

            event (nio.events.room_events.RoomMessageText): The event defining the message

        """
        # Extract the message text
        msg = event.body

        # Ignore messages from ourselves
        if event.sender == self.client.user:
            return

        logger.debug(
            f"Bot message received for room {room.display_name} | "
            f"{room.user_name(event.sender)}: {msg}"
        )

        # process each line as separate message to check for commands
        messages = msg.split("\n\n")
        logger.debug(
            f"Bot message received for prefix {self.command_prefix} | "
            f"{room.user_name(event.sender)}: {messages}"
        )
        for split_message in messages:
            # Process as message if in a public room without command prefix
            has_command_prefix = split_message.startswith(self.command_prefix)
            if not has_command_prefix and not room.is_group:
                # General message listener
                message = Message(self.client, self.store, self.config, split_message, room, event)
                await message.process()
                continue

            # Otherwise if this is in a 1-1 with the bot or features a command prefix,
            # treat it as a command
            if has_command_prefix:
                # Remove the command prefix
                split_message = split_message[len(self.command_prefix):]
                # remove leading spaces
                split_message = split_message.lstrip()

            if split_message != "":
                command = Command(self.client, self.store, self.config, split_message, room, event)
                await command.process()

    async def event_unknown(self, room: MatrixRoom, event: UnknownEvent):
        """
        Handles events that are not yet known to matrix-nio (might change or break on updates)
        :param room: nio.rooms.MatrixRoom: the room the event came from
        :param event: nio.events.room_events.RoomMessage: The event defining the message
        :return:
        """

    async def invite(self, room, event):
        """Callback for when an invite is received. Join the room specified in the invite"""
        logger.debug(f"Got invite to {room.room_id} from {event.sender}.")

        if event.sender in self.config.botmasters:
            # Attempt to join 3 times before giving up
            for attempt in range(3):
                result = await self.client.join(room.room_id)
                if type(result) == JoinError:
                    logger.error(
                        f"Error joining room {room.room_id} (attempt %d): %s",
                        attempt, result.message,
                    )
                else:
                    logger.info(f"Joined {room.room_id}")
                    break

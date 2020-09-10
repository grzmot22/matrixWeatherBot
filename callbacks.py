from chat_functions import send_text_to_room
from bot_commands import Command
from nio import JoinError, RoomLeaveError
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
        
    async def to_device_callback(self, event):  # noqa
        """Handle events sent to device."""
        try:
            client = self.client

            if isinstance(event, KeyVerificationStart):  # first step
                """ first step: receive KeyVerificationStart
                KeyVerificationStart(
                    source={'content':
                            {'method': 'm.sas.v1',
                             'from_device': 'DEVICEIDXY',
                             'key_agreement_protocols':
                                ['curve25519-hkdf-sha256', 'curve25519'],
                             'hashes': ['sha256'],
                             'message_authentication_codes':
                                ['hkdf-hmac-sha256', 'hmac-sha256'],
                             'short_authentication_string':
                                ['decimal', 'emoji'],
                             'transaction_id': 'SomeTxId'
                             },
                            'type': 'm.key.verification.start',
                            'sender': '@user2:example.org'
                            },
                    sender='@user2:example.org',
                    transaction_id='SomeTxId',
                    from_device='DEVICEIDXY',
                    method='m.sas.v1',
                    key_agreement_protocols=[
                        'curve25519-hkdf-sha256', 'curve25519'],
                    hashes=['sha256'],
                    message_authentication_codes=[
                        'hkdf-hmac-sha256', 'hmac-sha256'],
                    short_authentication_string=['decimal', 'emoji'])
                """

                if "emoji" not in event.short_authentication_string:
                    print("Other device does not support emoji verification "
                          f"{event.short_authentication_string}.")
                    return
                resp = await client.accept_key_verification(
                    event.transaction_id)
                if isinstance(resp, ToDeviceError):
                    print(f"accept_key_verification failed with {resp}")

                sas = client.key_verifications[event.transaction_id]

                todevice_msg = sas.share_key()
                resp = await client.to_device(todevice_msg)
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

                resp = await client.cancel_key_verification(
                    event.transaction_id, reject=False)
                if isinstance(resp, ToDeviceError):
                    print(f"cancel_key_verification failed with {resp}")

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

                yn = input("Do the emojis match? (Y/N) ")
                if yn.lower() == "y":
                    print("Match! Device will be verified "
                          "by accepting verification.")
                    resp = await client.confirm_short_auth_string(
                        event.transaction_id)
                    if isinstance(resp, ToDeviceError):
                        print(f"confirm_short_auth_string failed with {resp}")
                else:  # no, don't match, reject
                    print("No match! Device will NOT be verified "
                          "by rejecting verification.")
                    resp = await client.cancel_key_verification(
                        event.transaction_id, reject=True)
                    if isinstance(resp, ToDeviceError):
                        print(f"confirm_short_auth_string failed with {resp}")
            elif isinstance(event, KeyVerificationMac):  # third step
                """ Third step is to receive KeyVerificationMac
                KeyVerificationMac(
                    source={'content': {
                        'mac': {'ed25519:DEVICEIDXY': 'SomeKey1',
                                'ed25519:SomeKey2': 'SomeKey3'},
                        'keys': 'SomeCryptoKey4',
                        'transaction_id': 'SomeTxId'},
                        'type': 'm.key.verification.mac',
                        'sender': '@user2:example.org'},
                    sender='@user2:example.org',
                    transaction_id='SomeTxId',
                    mac={'ed25519:DEVICEIDXY': 'SomeKey1',
                         'ed25519:SomeKey2': 'SomeKey3'},
                    keys='SomeCryptoKey4')
                """
                sas = client.key_verifications[event.transaction_id]
                todevice_msg = sas.get_mac()
                resp = await client.to_device(todevice_msg)
                if isinstance(resp, ToDeviceError):
                    print(f"to_device failed with {resp}")
                print(f"sas.we_started_it = {sas.we_started_it}\n"
                      f"sas.sas_accepted = {sas.sas_accepted}\n"
                      f"sas.canceled = {sas.canceled}\n"
                      f"sas.timed_out = {sas.timed_out}\n"
                      f"sas.verified = {sas.verified}\n"
                      f"sas.verified_devices = {sas.verified_devices}\n")
                print("Emoji verification was successful.\n"
                      "Hit Control-C to stop the program or "
                      "initiate another Emoji verification from "
                      "another device or room.")
            else:
                print(f"Received unexpected event type {type(event)}. "
                      f"Event is {event}. Event will be ignored.")
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

        # Process as message if in a public room without command prefix
        has_command_prefix = msg.startswith(self.command_prefix)
        if not has_command_prefix:  # and not room.is_group:
            # General message listener
            message = Message(self.client, self.store, self.config, msg, room, event)
            await message.process()
            return

        # Otherwise if this is in a 1-1 with the bot or features a command prefix,
        # treat it as a command
        if has_command_prefix:
            # Remove the command prefix
            msg = msg[len(self.command_prefix) :]

        command = Command(self.client, self.store, self.config, msg, room, event)
        await command.process()

    async def invite(self, room, event):
        """Callback for when an invite is received. Join the room specified in the invite"""
        logger.debug(f"Got invite to {room.room_id} from {event.sender}.")

        # If user not whitelisted, try to reject for 3 times
        if (self.config.invite_whitelist_enabled) and (
            event.sender not in self.config.invite_whitelist
        ):
            for attempt in range(3):
                result = await self.client.room_leave(room.room_id)
                if type(result) == RoomLeaveError:
                    logger.error(
                        f"Error rejecting invite to room {room.room_id} (attempt %d): %s",
                        attempt,
                        result.message,
                    )
                else:
                    logger.info(
                        f"Reject invite to room {room.room_id}, {event.sender} not whitelisted."
                    )
                    return

        # Attempt to join 3 times before giving up
        for attempt in range(3):
            result = await self.client.join(room.room_id)
            if type(result) == JoinError:
                logger.error(
                    f"Error joining room {room.room_id} (attempt %d): %s",
                    attempt,
                    result.message,
                )
            else:
                logger.info(f"Joined {room.room_id}")
                break
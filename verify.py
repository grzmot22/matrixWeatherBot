#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import sys
import traceback
import logging
import asyncio
from time import time
from asyncio import sleep
from callbacks import Callbacks
from config import Config
from storage import Storage
from aiohttp.client_exceptions import (
    ServerDisconnectedError,
    ClientConnectionError)
    
from nio import (
    AsyncClient,
    AsyncClientConfig,
    KeyVerificationCancel,
    KeyVerificationEvent,
    KeyVerificationKey,
    KeyVerificationMac,
    KeyVerificationStart,
    LocalProtocolError,
    LoginResponse,
    ToDeviceError,
    UpdateDeviceError,
    RoomMessageText,
    InviteEvent,
    LocalProtocolError, LoginError, UnknownEvent
)

client: AsyncClient
timestamp: float = time()

EMOJI = "emoji"  # verification type
VERIFY_UNUSED_DEFAULT = None  # use None if --verify is not specified
VERIFY_USED_DEFAULT = "emoji"  # use emoji by default with --verify

async def main_verify() -> None:

    global client

    # Read config file
    config = Config("config.yaml")

    # Configure the database
    store = Storage(config.database_filepath)

    # Configuration options for the AsyncClient
    client_config = AsyncClientConfig(
        max_limit_exceeded=0,
        max_timeouts=0,
        store_sync_tokens=True,
        encryption_enabled=config.enable_encryption,
    )

    # Initialize the matrix client
    client = AsyncClient(
        config.homeserver_url,
        config.user_id,
        device_id=config.device_id,
        store_path=config.store_filepath,
        config=client_config,
    )

    # Set up event callbacks
    callbacks = Callbacks(client)
    client.add_to_device_callback(
        callbacks.to_device_callback, (KeyVerificationEvent,)
    )
    # Keep trying to reconnect on failure (with some time in-between)
    error_retries: int = 0
    while True:
        try:
            # Try to login with the configured username/password
            try:
                login_response = await client.login(
                    password=config.user_password,
                    device_name=config.device_name,
                )

                # Check if login failed
                if type(login_response) == LoginError:
                    logger.error(f"Failed to login: {login_response.message}, retrying in 15s... ({error_retries})")
                    # try logging in a few times to work around temporary login errors during homeserver restarts
                    if error_retries < 3:
                        error_retries += 1
                        await sleep(15)
                        continue
                    else:
                        return False
                else:
                    error_retries = 0

            except LocalProtocolError as e:
                # There's an edge case here where the user enables encryption but hasn't installed
                # the correct C dependencies. In that case, a LocalProtocolError is raised on login.
                # Warn the user if these conditions are met.
                if config.enable_encryption:
                    logger.fatal(
                        "Failed to login and encryption is enabled. Have you installed the correct dependencies? "
                        "https://github.com/poljar/matrix-nio#installation"
                    )
                    return False
                else:
                    # We don't know why this was raised. Throw it at the user
                    logger.fatal(f"Error logging in: {e}")

            # Login succeeded!

            # Sync encryption keys with the server
            # Required for participating in encrypted rooms
            if client.should_upload_keys:
                await client.keys_upload()

            logger.info(f"Logged in as {config.user_id}")
            await client.sync_forever(timeout=30000, full_state=True)

        except (ClientConnectionError, ServerDisconnectedError, AttributeError, asyncio.TimeoutError) as err:
            logger.debug(err)
            logger.warning(f"Unable to connect to homeserver, retrying in 15s...")

            # Sleep so we don't bombard the server with login requests
            await sleep(15)
        finally:
            # Make sure to close the client connection on disconnect
            await client.close()


# according to pylama: function too complex: C901 # noqa: C901
def initial_check_of_args() -> None:  # noqa: C901
    """Check arguments."""
    # First, the adjustments
    if not pargs.encrypted:
        pargs.encrypted = True  # force it on
        logger.debug("Encryption is always enabled. It cannot be turned off.")
    if not pargs.encrypted:  # just in case we ever go back disabling e2e
        pargs.store = None
    elif pargs.verify and (pargs.verify.lower() != EMOJI):
        t = f'For --verify currently only "{EMOJI}" is allowed ' "as keyword."
    elif pargs.verify:
        t = (
            "If --verify is specified, only verify can be done. "
            "No messages, images, or files can be sent."
            "No listening or tailing allowed. No renaming."
        )   
    else:
        logger.debug("All arguments are valid. All checks passed.")
        return
    logger.error(t)
    sys.exit(1)

if __name__ == "__main__": 
    logging.basicConfig()  # initialize root logger, a must
    # set log level on root
    if "DEBUG" in os.environ:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # Construct the argument parser
    ap = argparse.ArgumentParser(
        description="On first run this program will configure itself. "
        "On further runs this program implements a simple Matrix CLI client "
        "Emoji verification is built-in which can be used "
        "to verify devices. End-to-end encryption is enabled by default "
        "and cannot be turned off. "
        "matrix-nio (https://github.com/poljar/matrix-nio) and end-to-end "
        "encryption packages must be installed. "
        "See dependencies in source code (or README.md). For even more "
        "explications run this program with the --help option or read the "
        "full documentation in the source code."
    )
    # Add the arguments to the parser
    ap.add_argument(
        "-d",
        "--debug",
        required=False,
        action="store_true",
        help="Print debug information",
    )
    ap.add_argument(
        "-v",
        "--verify",
        required=False,
        type=str,
        default=VERIFY_UNUSED_DEFAULT,  # when -t is not used
        nargs="?",  # makes the word optional
        # when -v is used, but text is not added
        const=VERIFY_USED_DEFAULT,
        help="Perform verification. By default, no "
        "verification is performed. "
        f'Possible values are: "{EMOJI}". '
        "If verification is desired, run this program in the "
        "foreground (not as a service) and without a pipe. "
        "Verification questions "
        "will be printed on stdout and the user has to respond "
        "via the keyboard to accept or reject verification. "
        "Once verification is complete, stop the program and "
        "run it as a service again. Don't send messages or "
        "files when you verify. ",
    )
 
    pargs = ap.parse_args()
    if pargs.debug:
        # set log level on root logger
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger().info("Debug is turned on.")
    logger = logging.getLogger(__name__)

    initial_check_of_args()

    try:
        if pargs.verify:
            asyncio.get_event_loop().run_until_complete(main_verify())
 
        logger.debug(f"The program {__name__} terminated successfully.")
    except TimeoutError:
        logger.info(
            f"The program {__name__} ran into a timeout. "
            "Most likely connectivity to internet was lost. "
            "If this happens frequently consider running this "
            "program as a service so it will restart automatically. "
            "Sorry. Here is the traceback."
        )
        logger.info(traceback.format_exc())
    except Exception:
        logger.info(
            f"The program {__name__} failed. "
            "Sorry. Here is the traceback."
        )
        logger.info(traceback.format_exc())
        # traceback.print_exc(file=sys.stdout)
    except KeyboardInterrupt:
        logger.debug("Keyboard interrupt received.")
    sys.exit(1)

# EOF
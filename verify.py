#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import sys
import traceback
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
    KeyVerificationEvent,
    LocalProtocolError, LoginError
)

client: AsyncClient
timestamp: float = time()
logger = logging.getLogger(__name__)

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
        ssl=config.ssl
    )

    # Set up event callbacks
    callbacks = Callbacks(client, store, config)
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
                    logger.error(
                        f"Failed to login: {login_response.message}, retrying in 15s... ({error_retries})")
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
            logger.warning(
                f"Unable to connect to homeserver, retrying in 15s...")

            # Sleep so we don't bombard the server with login requests
            await sleep(15)
        finally:
            # Make sure to close the client connection on disconnect
            await client.close()

if __name__ == "__main__":
    logging.basicConfig()  # initialize root logger, a must
    # set log level on root
    if "DEBUG" in os.environ:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # Construct the argument parser
    ap = argparse.ArgumentParser(
        description="This program perform verification of the device. To run with -v or --verify"
        "Emoji verification is built-in which can be used "
        "to verify devices."
    )
    # Add the arguments to the parser
    ap.add_argument(
        "-v",
        "--verify",
        required=False,
        type=str,
        default=VERIFY_UNUSED_DEFAULT,
        nargs="?",  # makes the word optional
        # when -v is used, but text is not added
        const=VERIFY_USED_DEFAULT,
        help="Perform verification."
        f'Possible values are: "{EMOJI}". '
        "If verification is desired, run this program in the foreground"
        "Verification questions "
        "will be printed on terminal and the user has to respond "
        "via the keyboard to accept or reject verification. "
        "Once verification is complete, stop the program."

    )

    pargs = ap.parse_args()

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
    except KeyboardInterrupt:
        logger.debug("Keyboard interrupt received.")
    sys.exit(1)

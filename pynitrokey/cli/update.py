# -*- coding: utf-8 -*-
#
# Copyright 2019 SoloKeys Developers
#
# Licensed under the Apache License, Version 2.0, <LICENSE-APACHE or
# http://apache.org/licenses/LICENSE-2.0> or the MIT license <LICENSE-MIT or
# http://opensource.org/licenses/MIT>, at your option. This file may not be
# copied, modified, or distributed except according to those terms.

import json
import logging
import os
import platform
import sys
import tempfile
import time
from datetime import datetime

import click
import requests

import pynitrokey
from pynitrokey.confconsts import LOG_FN
from pynitrokey.helpers import AskUser, local_critical, local_print

logger = logging.getLogger()


@click.command()
@click.option(
    "-s",
    "--serial",
    help="Serial number of Nitrokey to use. Prefix with 'device=' to provide device file, e.g. 'device=/dev/hidraw5'.",
    default=None,
)
@click.option("-y", "--yes", default=False, is_flag=True, help="agree to everything")
@click.option("-f", "--force", default=False, is_flag=True, help="force")
def update(serial, yes, force):
    """Update Nitrokey key to latest firmware version."""

    # @fixme: print this and allow user to cancel (if not -y is active)
    # update_url = 'https://update.nitrokey.com/'
    # print('Please use {} to run the firmware update'.format(update_url))
    # return

    IS_LINUX = platform.system() == "Linux"

    logger.debug(f"Start session {datetime.now()}")

    # @fixme: move to generic startup stuff logged into file exclusively!
    local_print(
        "Nitrokey FIDO2 firmware update tool",
        f"Platform: {platform.platform()}",
        f"System: {platform.system()}, is_linux: {IS_LINUX}",
        f"Python: {platform.python_version()}",
        f"Saving run log to: {LOG_FN}",
        "",
        f"Starting update procedure for Nitrokey FIDO2...",
    )

    from pynitrokey.fido2 import find

    # Determine target key
    client = None
    try:
        client = find(serial)

    except pynitrokey.exceptions.NoSoloFoundError as e:
        local_critical(
            None,
            "No Nitrokey key found!",
            e,
            None,
            "If you are on Linux, are your udev rules up to date?",
            "For more, see: ",
            "  https://docs.nitrokey.com/fido2/linux/index.html#troubleshooting",
            None,
        )

    except pynitrokey.exceptions.NonUniqueDeviceError as e:
        local_critical(
            None,
            "Multiple Nitrokey keys are plugged in!",
            e,
            None,
            "Please unplug all but one key",
            None,
        )

    except Exception as e:
        local_critical(None, "Unhandled error connecting to key", e, None)

    # determine asset url: we want the (signed) json file
    # @fixme: move to confconsts.py ...
    api_base_url = "https://api.github.com/repos"
    api_url = f"{api_base_url}/Nitrokey/nitrokey-fido2-firmware/releases/latest"
    gh_release_data = None
    try:
        gh_release_data = json.loads(requests.get(api_url).text)
    except Exception as e:
        local_critical("Failed downloading firmware", e)

    # search asset with `fn` suffix being .json and take its url
    assets = [(x["name"], x["browser_download_url"]) for x in gh_release_data["assets"]]
    download_url = None
    for fn, url in assets:
        if fn.endswith(".json"):
            download_url = url
            break
    if not download_url:
        local_critical(
            "Failed to determine latest release (url)", "assets:", *map(str, assets)
        )

    import os.path
    local_print(
        f"Found latest firmware: {os.path.basename(download_url)}\n"
        f"\t\t(published at {gh_release_data['published_at']}, under tag {gh_release_data['tag_name']})"
    )


    ver = client.solo_version()
    local_print(f"\tCurrent Firmware version: {ver[0]}.{ver[1]}.{ver[2]}")

    # to find the variant (128kB vs 256kB), switch to the bootloader and get its public key
    p = find(serial)
    if not p.is_solo_bootloader():
        local_print("Not in Bootloader Mode!")
        return

    # todo refactor and extract
    from binascii import b2a_hex
    from hashlib import sha256
    bpub = p.boot_pubkey()
    bpub = b2a_hex(bpub)
    # local_print(f"Bootloader public key: \t\t{bpub}")
    s = sha256()
    s.update(bpub)
    bpubh = b2a_hex(s.digest())
    # local_print(f"Bootloader public key sha256: \t{bpubh}")

    variants = {
        "256": b'11d0b23f9f4f1aa319277aabab439447a6a8b89406a03f8ced2c39869c8a2724',
        "128": b'TODO insert bootloader key hash here',
        # todo: add 128kB variant
    }
    variant = variants[bpubh]
    # todo go over the latest tag assets and check the currently connected variant version
    #

    # if the downloaded firmware version is the same as the current one, skip update unless force switch is provided
    if f'firmware-{ver[0]}.{ver[1]}.{ver[2]}' in download_url:
        if not force:
            local_critical(
                "Your firmware is up-to-date!\n"
                "Use --force flag to run update process anyway.",
                support_hint=False)
        else:
            local_print("Firmware is up-to-date. Continue due to --force switch applied.")

    def download_firmware():
        # download asset url
        # @fixme: move to confconsts.py ...
        local_print(
            f"Downloading latest firmware: {gh_release_data['tag_name']} "
            f"(published at {gh_release_data['published_at']})"
        )
        tmp_dir = tempfile.gettempdir()
        fw_fn = os.path.join(tmp_dir, "fido2_firmware.json")
        try:
            with open(fw_fn, "wb") as fd:
                firmware = requests.get(download_url)
                fd.write(firmware.content)
        except Exception as e:
            local_critical("Failed downloading firmware", e)

        local_print(
            f"\tFirmware saved to {fw_fn}",
            f"\tDownloaded firmware version: {gh_release_data['tag_name']}",
        )
        return fw_fn
    fw_fn = download_firmware()

    # ask for permission
    if not yes:
        local_print("")
        local_print("This will update your Nitrokey FIDO2")
        if not AskUser.strict_yes_no("Do you want to continue?"):
            local_critical("exiting due to user input...", support_hint=False)

    # Ensure we are in bootloader mode
    if client.is_solo_bootloader():
        local_print("Key already in bootloader mode, continuing...")
    else:
        try:
            local_print("Entering bootloader mode, please confirm with button on key! (long 10 second press)")
            client.use_hid()
            client.enter_bootloader_or_die()
            time.sleep(0.5)
        except Exception as e:
            local_critical("problem switching to bootloader mode:", e)

    time.sleep(1.0)

    def connect_and_flash():
        # reconnect and actually flash it...
        # fail after 5 attempts
        exc = None
        for _ in range(5):
            try:
                client = find(serial)
                client.use_hid()
                client.program_file(fw_fn)
                break
            except Exception as e:
                time.sleep(0.5)
                exc = e
                # todo log exception info from each failed iteration
        else:
            local_critical("problem flashing firmware:", exc)

    connect_and_flash()

    local_print(None, "After update version check...")

    for _ in range(100):
        try:
            client = find(serial)
            new_ver = client.solo_version()
            local_print(f"New Firmware version: {new_ver[0]}.{new_ver[1]}.{new_ver[2]}")
            break

        # expected until the devices comes up again
        except OSError:
            continue
        # unexpected...
        except Exception as e:
            local_print("unexpected error", e)
            break

    local_print("Congratulations, your key was updated to the latest firmware.")
    logger.debug("Finishing session {}".format(datetime.now()))
    local_print("Log saved to: {}".format(LOG_FN))

# -*- coding: utf-8 -*-
#
# Copyright 2020 Nitrokey Developers
#
# Licensed under the Apache License, Version 2.0, <LICENSE-APACHE or
# http://apache.org/licenses/LICENSE-2.0> or the MIT license <LICENSE-MIT or
# http://opensource.org/licenses/MIT>, at your option. This file may not be
# copied, modified, or distributed except according to those terms.
import logging
import platform
import subprocess

import click

from pynitrokey.helpers import local_critical, local_print
from pynitrokey.libnk import BaseLibNitrokey, DeviceNotFound, NitrokeyStorage

logger = logging.getLogger(__name__)

@click.group()
def storage():
    """(experimental) 'Nitrokey Storage' keys, see subcommands."""
    pass


@click.command()
@click.argument('firmware', type=click.Path(exists=True, readable=True))
@click.option(
    "--experimental",
    default=False,
    is_flag=True,
    help="Allow to execute experimental features",
)
def update(firmware: str, experimental):
    """experimental: run assisted update through dfu-programmer tool"""
    if platform.system() != "Linux" or not experimental:
        local_print("This feature is Linux only and experimental, which means it was not tested thoroughly.\n"
                    "Please pass --experimental switch to force running it anyway.")
        raise click.Abort()
    assert firmware.endswith('.hex')

    commands = f"""
        sudo dfu-programmer at32uc3a3256s erase
        sudo dfu-programmer at32uc3a3256s flash --suppress-bootloader-mem {firmware}
        sudo dfu-programmer at32uc3a3256s launch
        """

    local_print('')
    local_print('During the execution you will be asked to enter password to use sudo')
    local_print(f'Using firmware path: {firmware}')
    local_print(f'Commands to be executed: {commands}')
    if not click.confirm("Do you want to perform the firmware update now?"):
        logger.info("Update cancelled by user")
        raise click.Abort()

    commands_clean = commands.strip().split('\n')
    for c in commands_clean:
        c = c.strip()
        if not c: continue
        try:
            local_print(f'* Running \t"{c}"')
            output = subprocess.check_output(c.split())
            if output:
                local_print(output)
        except subprocess.CalledProcessError as e:
            local_critical(e)

    local_print('')
    local_print('Finished!')
    local_print('Run "nitropy storage list" to check for communication')


@click.command()
def list():
    """list connected devices"""

    local_print(":: 'Nitrokey Storage' keys:")
    devices = NitrokeyStorage.list_devices()
    for dct in devices:
        local_print(f' - {dct}')
    if len(devices) == 1:
        nks = NitrokeyStorage()
        nks.connect()
        local_print(f'Found libnitrokey version: {nks.library_version()}')
        local_print(f'Firmware version: {nks.fw_version}')
        local_print(f'Admin PIN retries: {nks.admin_pin_retries}')
        local_print(f'User PIN retries: {nks.user_pin_retries}')


@click.command()
@click.option(
    "-p",
    "--password",
    default="12345678",
    help="update password to be used instead of default",
)
def enable_update(password):
    """enable firmware update for NK Storage device"""

    local_print("Enabling firmware update mode")
    nks = NitrokeyStorage()
    nks.connect()
    try:
        if nks.enable_firmware_update(password) == 0:
            local_print("setting firmware update mode - success!")
    except DeviceNotFound:
        local_print("No Nitrokey Storage device found")


storage.add_command(list)
storage.add_command(enable_update)
storage.add_command(update)

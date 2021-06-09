"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import logging
import multiprocessing

import time
from _tracemalloc import start

from typing import Optional

import pyDE1.default_logger


# from pyDE1.api.outbound.null import run_api_outbound
from pyDE1.api.outbound.mqtt import run_api_outbound


def run_api_inbound(api_inbound_queue: multiprocessing.Queue):
    logging.getLogger('inbound').info(
        f"Inbound ran")


async def run(inbound_queue: Optional[multiprocessing.Queue] = None,
              outbound_queue: Optional[multiprocessing.Queue] = None):

    logger = logging.getLogger('main')

    from pyDE1.de1 import DE1
    from pyDE1.event_manager import SubscribedEvent

    from pyDE1.de1.ble import CUUID
    from pyDE1.de1.c_api import API_MachineStates
    from pyDE1.de1.profile import ProfileByFrames
    from pyDE1.de1.firmware_file import FirmwareFile

    from pyDE1.shot_file import CombinedShotLogger

    from pyDE1.scale import AtomaxSkaleII
    from pyDE1.scale.processor import ScaleProcessor
    from pyDE1.flow_sequencer import FlowSequencer

    from pyDE1.find_first import find_first_de1, find_first_skale

    logging.getLogger('EventManager').setLevel(logging.INFO)
    logging.getLogger(
        f"{CUUID.StateInfo.__str__()}.Notify").setLevel(logging.DEBUG)

    SubscribedEvent.outbound_queue = outbound_queue

    de1_device = await find_first_de1()
    skale_device = await find_first_skale()

    # There's a bug in creating from device on bleak 0.11.0 on macOS

    de1 = DE1(de1_device.address)
    skale = AtomaxSkaleII(skale_device.address)
    sp = ScaleProcessor(skale)
    # TODO: Clean up the init/add/remove/change of FlowSequencer
    fs = FlowSequencer()
    await fs.set_de1(de1)
    await fs.set_scale_processor(sp)
    shot_logger = CombinedShotLogger()

    await asyncio.gather(
        de1.event_shot_sample_with_volumes_update.subscribe(
            shot_logger.sswvu_subscriber),
        sp.event_weight_and_flow_update.subscribe(
            shot_logger.wafu_subscriber)
    )

    await de1.connect()
    await skale.connect()

    logger.info("Connected")

    await asyncio.sleep(1)
    await asyncio.gather(
        de1.start_standard_notifiers(),
        skale.standard_initialization(),
    )

    await de1.read_standard_mmr_registers()

    await de1.idle()

    logger.info("Upload profile")
    profile = ProfileByFrames()
    profile.from_json_file('jmk_eb5.json')
    await de1.upload_profile(profile)
    logger.info("Upload complete")

    fs.stop_at_weight_set(API_MachineStates.Espresso, 30)
    await fs.stop_at_time_set_async(API_MachineStates.HotWaterRinse, 3)
    await fs.stop_at_time_set_async(API_MachineStates.Steam, 10)

    # TODO: This needs to get taken into DE1 class directly
    #       or at least be a non-private method of sending
    await de1.notify_initialized()

    logger.info(f"SAW {fs.stop_at_weight(API_MachineStates.Espresso)} g, "
                f"SAV {fs.stop_at_volume(API_MachineStates.Espresso)} mL")

    # print("starting FW upload")
    # ff = FirmwareFile('bootfwupdate.dat')
    # await de1.upload_firmware(ff)

    snooze = 300
    print(f"==== sleeping {snooze} ====")
    await asyncio.sleep(snooze)

    snooze = 0
    print(f"==== sleeping {snooze} ====")
    await asyncio.sleep(snooze)
    print("==== shutting down ====")
    await de1.sleep()
    await asyncio.gather(
        de1.disconnect(),
        skale.disconnect()
    )
    await asyncio.sleep(1)  # TO see if DISCONNECTED messages come through
    # TODO: Need to be able to gracefully shutdown other threads
    inbound_api_process.terminate()
    outbound_api_process.terminate()


if __name__ == "__main__":

    multiprocessing.set_start_method('spawn')

    outbound_api_queue = multiprocessing.Queue()
    inbound_api_queue = multiprocessing.Queue()

    outbound_api_process = multiprocessing.Process(
        target=run_api_outbound,
        args=(outbound_api_queue,),
        name='Outbound-API')
    outbound_api_process.start()

    inbound_api_process = multiprocessing.Process(
        target=run_api_inbound,
        args=(inbound_api_queue,),
        name='Inbound-API')
    inbound_api_process.start()

    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.run_until_complete(run(inbound_queue=inbound_api_queue,
                                outbound_queue=outbound_api_queue))

    # atexit not working with this form:
    # asyncio.run(run(), debug=True)

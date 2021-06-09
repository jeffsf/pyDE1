"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import logging
import multiprocessing as mp
import time

import pyDE1.default_logger


def run_api_outbound(api_outbound_queue: mp.Queue):
    logging.getLogger('outbound').info(
        f"Outbound ran")


def run_api_inbound(api_inbound_queue: mp.Queue):
    logging.getLogger('inbound').info(
        f"Inbound ran")


async def run():

    logger = logging.getLogger('main')

    from pyDE1.de1 import DE1

    from pyDE1.de1.ble import CUUID
    from pyDE1.de1.c_api import API_MachineStates
    from pyDE1.de1.profile import ProfileByFrames
    from pyDE1.de1.firmware_file import FirmwareFile

    from pyDE1.shot_file import CombinedShotLogger

    from pyDE1.scale import AtomaxSkaleII
    from pyDE1.scale.processor import ScaleProcessor
    from pyDE1.flow_sequencer import FlowSequencer

    de1_addr = "d9:b2:48:aa:bb:cc"
    skale_addr = "cf:75:75:aa:bb:cc"

    try:
        de1 = DE1
    except NameError:
        de1 = 'DE1 is not defined'

    logger.info(
        f"in run(): {de1}")

    logging.getLogger('EventManager').setLevel(logging.INFO)
    logging.getLogger(
        f"{CUUID.StateInfo.__str__()}.Notify").setLevel(logging.DEBUG)

    de1 = DE1(de1_addr)
    skale = AtomaxSkaleII(skale_addr)
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
        skale.standard_config(),
    )

    await de1.read_standard_mmr_registers()

    await de1.idle()

    logger.info("Upload profile")
    profile = ProfileByFrames()
    profile.from_json_file('jmk_eb5.json')
    await de1.upload_profile(profile)
    logger.info("Upload complete")

    fs.stop_at_weight_set(API_MachineStates.Espresso, 50)
    await fs.stop_at_time_set_async(API_MachineStates.HotWaterRinse, 5)
    await fs.stop_at_time_set_async(API_MachineStates.Steam, 10)

    logger.info(f"SAW {fs.stop_at_weight(API_MachineStates.Espresso)} g, "
                f"SAV {fs.stop_at_volume(API_MachineStates.Espresso)} mL")

    # print("starting FW upload")
    # ff = FirmwareFile('bootfwupdate.dat')
    # await de1.upload_firmware(ff)

    snooze = 300
    print(f"==== sleeping {snooze} ====")
    await asyncio.sleep(snooze)

    snooze = 3300
    print(f"==== sleeping {snooze} ====")
    await asyncio.sleep(snooze)
    await de1.sleep()
    await de1.disconnect()


if __name__ == "__main__":

    mp.set_start_method('spawn')

    outbound_api_queue = mp.Queue()
    inbound_api_queue = mp.Queue()

    outbound_api_process = mp.Process(target=run_api_outbound,
                                      args=(outbound_api_queue,))
    outbound_api_process.start()

    inbound_api_process = mp.Process(target=run_api_inbound,
                                      args=(inbound_api_queue,))
    inbound_api_process.start()

    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.run_until_complete(run())

    # atexit not working with this form:
    # asyncio.run(run(), debug=True)

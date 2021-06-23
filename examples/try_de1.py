"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import atexit
import multiprocessing, multiprocessing.connection

# from pyDE1.api.outbound.null import run_api_outbound
from pyDE1.api.outbound.mqtt import run_api_outbound
from pyDE1.api.inbound.http import run_api_inbound


async def run(request_pipe: multiprocessing.connection.Connection,
              response_pipe: multiprocessing.connection.Connection,
              outbound_queue: multiprocessing.Queue):

    import logging
    logger = logging.getLogger(multiprocessing.current_process().name)

    import pprint

    from pyDE1.de1 import DE1
    from pyDE1.event_manager import SubscribedEvent

    from pyDE1.de1.ble import CUUID

    from pyDE1.shot_file import CombinedShotLogger

    from pyDE1.scale import AtomaxSkaleII
    from pyDE1.scale.processor import ScaleProcessor
    from pyDE1.flow_sequencer import FlowSequencer

    from pyDE1.find_first import find_first_de1, find_first_skale

    from pyDE1.dispatcher.dispatcher import register_read_pipe_to_queue, \
        start_request_queue_processor, start_response_queue_processor

    from pyDE1.de1.exceptions import DE1NotConnectedError

    logging.getLogger('EventManager').setLevel(logging.INFO)
    logging.getLogger(
        f"{CUUID.StateInfo.__str__()}.Notify").setLevel(logging.DEBUG)

    pp = pprint.PrettyPrinter()
    ppp = pp.pprint

    # ppp(MAPPING)  # Pretty messy, needs to be custom mapped

    request_queue = asyncio.Queue()
    response_queue = asyncio.Queue()

    register_read_pipe_to_queue(
        pipe_to_read=request_pipe,
        queue_to_put=request_queue,
    )

    start_request_queue_processor(request_queue=request_queue,
                                  response_queue=response_queue)

    start_response_queue_processor(
        response_queue=response_queue,
        response_pipe=response_pipe
    )

    SubscribedEvent.outbound_queue = outbound_queue

    de1_device = await find_first_de1()
    skale_device = await find_first_skale()

    if de1_device is None or skale_device is None:
        raise DE1NotConnectedError

    # There's a bug in creating from device on bleak 0.11.0 on macOS

    # TODO: Note that this initialization is order-sensitive
    #       It is failing here as DE1() has been called by
    #       _request_queue_processor
    #       de1 = DE1(de1_device)

    de1 = DE1()
    de1.address = de1_device

    skale = AtomaxSkaleII()
    skale.address = skale_device

    sp = ScaleProcessor()
    await sp.set_scale(skale)

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
        de1.start_standard_read_write_notifiers(),
        de1.start_standard_periodic_notifiers(),
        skale.standard_initialization(),
    )

    await de1.read_standard_mmr_registers()

    # await de1.idle()

    # all_de1 = json.dumps(await get_resource_to_dict(Resource.DE1, fs))
    # print("DE1 length", len(all_de1))  # -> 1748


    # TODO: This needs to get taken into DE1 class directly
    #       or at least be a non-private method of sending
    logger.info("Waiting for notify ready")
    # TODO: Should this confirm all the notifiers are running?
    #       What about the ones that don't notify?
    await de1._notify_ready()

    # logger.info(f"SAW {fs.espresso_control.stop_at_weight} g, "
    #             f"SAV {fs.espresso_control.stop_at_volume} mL")

    # fs.espresso_control.profile_can_override_stop_limits = False

    # logger.info("Upload profile")
    # profile = ProfileByFrames()
    # profile.from_json_file('jmk_eb5.json')
    # await de1.upload_profile(profile)
    # logger.info("Upload complete")

    # logger.info(f"SAW after {fs.espresso_control.stop_at_weight} g, "
    #             f"SAV after {fs.espresso_control.stop_at_volume} mL")

    # print("try patch_dict_to_resource")
    # await patch_dict_to_resource({}, Resource.DE1, fs)

    # print("starting FW upload")
    # ff = FirmwareFile('bootfwupdate.dat')
    # await de1.upload_firmware(ff)

    # for res in (Resource.DE1, Resource.SCALE):  # Resource
    #     print(f"<===== {res}")
    #     d = await get_resource_to_dict(res, fs)
    #     print(f"====> {res}")
    #     ppp(d)

    snooze = 300
    print(f"==== sleeping {snooze} ====")
    await asyncio.sleep(snooze)


    snooze = 300
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

    inbound_pipe_controller, inbound_pipe_server = multiprocessing.Pipe()
    # read, write, for simplex

    outbound_api_process = multiprocessing.Process(
        target=run_api_outbound,
        args=(outbound_api_queue,),
        name='OutboundAPI')
    outbound_api_process.start()

    @atexit.register
    def kill_outbound():
        outbound_api_process.terminate()

    inbound_api_process = multiprocessing.Process(
        target=run_api_inbound,
        args=(inbound_pipe_server,),
        name='InboundAPI')
    inbound_api_process.start()

    @atexit.register
    def kill_inbound():
        inbound_api_process.terminate()

    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.run_until_complete(run(
        request_pipe=inbound_pipe_controller,
        response_pipe=inbound_pipe_controller,
        outbound_queue=outbound_api_queue)
    )

    # atexit not working with this form:
    # asyncio.run(run(), debug=True)

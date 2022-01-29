import asyncio

import pyDE1.de1
from pyDE1.config import config
from pyDE1.scale.acaia import AcaiaLunar


# TODO: efdd 0707 0219 0100 0501 2108

if __name__ == '__main__':

    import argparse
    import logging
    import pprint

    import pyDE1.pyde1_logging as pyde1_logging
    from bleak import BleakScanner, BleakClient, BleakError

    ap = argparse.ArgumentParser(
        description="""Service to upload pyDE1 "shots" to visualizer.coffee

        Listens to MQTT announcements of flow and state from pyDE1. 
        When complete, accesses the (local) database for the "shot file" 
        and uploads to visualizer.coffee as well as notifying with URL on 
        {config.mqtt.TOPIC_ROOT}/VisualizerUpload

        """
        f"Default configuration file is at {config.DEFAULT_CONFIG_FILE}"
    )
    ap.add_argument('-c', type=str, help='Use as alternate config file')

    args = ap.parse_args()

    pyde1_logging.setup_initial_logger()

    config.load_from_yaml(args.c)

    config.logging.LOG_FILENAME = None
    config.logging.handlers.STDERR = 'DEBUG'
    config.logging.formatters.STDERR = \
        '%(asctime)s %(levelname)s %(name)s: %(message)s'

    pyde1_logging.setup_direct_logging(config.logging)
    pyde1_logging.config_logger_levels(config.logging)

    logging.getLogger('bleak.backends.bluezdbus.scanner').setLevel(logging.INFO)
    logging.getLogger('bleak.backends.bluezdbus.client').setLevel(logging.INFO)

    logger = pyDE1.getLogger('Main')

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    def exception_handler(loop: asyncio.AbstractEventLoop,
                          context: dict):
        exc_class = context['exception'].__class__
        logger.critical(
                   f"Uncaught exception (loop) {exc_class}:\n"
                   f"{pprint.pformat(context)}")
        raise context['exception']

    loop.set_exception_handler(exception_handler)


    def on_disconnect(*args, **kwargs):
        logger.info("Bleak client disconnected")


    async def run():
        logger.info("Starting scan")
        devices = await BleakScanner.discover(timeout=3)
        logger.info("Scan complete")
        found = False
        for d in devices:
            if d.name.startswith("LUNAR"):
                logger.info(d)
                found = True
                break
        if found:
            logger.info(f"Creating scale for {d}")
            lunar: AcaiaLunar  = pyDE1.scale.scale_factory(d)
            logger.info(f"Connecting {lunar}")
            await lunar.connect()
            if lunar.is_connected:
                logger.info("Connected")
            else:
                logger.warning("NOT connected")
                return

            await asyncio.sleep(1)
            logger.info("Set oz")
            await lunar.set_ounces()

            await asyncio.sleep(5)
            logger.info("Set grams")
            await lunar.set_grams()

            await asyncio.sleep(5)
            await lunar.tare()

            await asyncio.sleep(5)
            await lunar.tare()

            await asyncio.sleep(3)
            logger.info("Disabling AcaiaLunar.notify")
            pyDE1.getLogger('AcaiaLunar.notify').setLevel(logging.WARNING)

            logger.info("Timer start")
            await lunar.timer_start()
            await asyncio.sleep(5)

            logger.info("Timer stop")
            await lunar.timer_stop()
            await asyncio.sleep(5)

            logger.info("Timer start")
            await lunar.timer_start()
            await asyncio.sleep(5)

            logger.info("Timer reset after start")
            await lunar.timer_reset()
            await asyncio.sleep(5)

            logger.info("Timer start")
            await lunar.timer_start()
            await asyncio.sleep(5)

            logger.info("Timer stop")
            await lunar.timer_stop()
            await asyncio.sleep(5)

            logger.info("Timer reset after stop")
            await lunar.timer_reset()
            await asyncio.sleep(5)

            logger.info("Timer reset after stop again")
            await lunar.timer_reset()
            await asyncio.sleep(5)

            logger.info("Timer start")
            await lunar.timer_start()
            await asyncio.sleep(5)

            logger.info("Timer reset after start")
            await lunar.timer_reset()
            await asyncio.sleep(5)

            await asyncio.sleep(10)
            logger.info("client disconnect request")
            if lunar.is_connected:
                await lunar.disconnect()
            else:
                logger.info("client was not connected")

        logger.info("run() done")

    loop.run_until_complete(run())

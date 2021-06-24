"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Subscribe to the MQTT broker, measure and periodically display statistics on:

* Processing delay  Time from trigger (BLE packet received) to presenting
                    the object to the internal event-distribution system

* Delivery delay    Time from the object being presented to the MQTT packet
                    being received by this program

* Total delay       Some of processing and delivery delays

"""

import asyncio
import json
import os
import statistics
import time

from socket import gethostname

from typing import Optional


import asyncio_mqtt
import asyncio_mqtt.client

from paho.mqtt.client import MQTTMessage

INTERVAL = 10  # seconds between reports and reset

MQTT_TOPIC_ROOT = 'pyDE1'

MQTT_CLIENT_ID = f"monitor_delay@{gethostname()}[{os.getpid()}]"

MQTT_BROKER_HOSTNAME = '::'
MQTT_BROKER_PORT = 1883

MQTT_TRANSPORT = 'tcp'
MQTT_TLS_CONTEXT = None
MQTT_KEEPALIVE = 60

MQTT_USERNAME = None
MQTT_PASSWORD = None

MQTT_PROTOCOL_VERSION = asyncio_mqtt.client.ProtocolVersion.V5

async def run():

    collector: dict[str, dict[str, List[float]]] = {}
    collector_lock = asyncio.Lock()
    collector_rows = (
        'Total',
        'ShotSampleWithVolumesUpdate',
        'WeightAndFlowUpdate',
    )
    timing_keys = (
        'Total',
        'Create',
        'Event',
        # 'Pub',
        # 'Sub',
        'PubSub',
    )

    # Should generally be called async with collector_lock:
    def _reset_collector():
        for row in collector_rows:
            collector[row] = {}
            for timing in timing_keys:
                collector[row][timing] = []

    _reset_collector()

    async def add_to_collector(
            payload_class,
            create_delay,
            event_delay,
            # pub_delay,
            # sub_delay,
            pub_sub_delay,
            total_delay,):
        async with collector_lock:
            _add_to_collector(
                'Total',
                create_delay,
                event_delay,
                # pub_delay,
                # sub_delay,
                pub_sub_delay,
                total_delay,
            )
            if payload_class in collector_rows:
                _add_to_collector(
                    payload_class,
                    create_delay,
                    event_delay,
                    # pub_delay,
                    # sub_delay,
                    pub_sub_delay,
                    total_delay,
                )

    # Should generally be called async with collector_lock:
    def _add_to_collector(
            collector_row,
            create_delay,
            event_delay,
            # pub_delay,
            # sub_delay,
            pub_sub_delay,
            total_delay,):
        collector[collector_row]['Create'].append(create_delay)
        collector[collector_row]['Event'].append(event_delay)
        # collector[collector_row]['Pub'].append(pub_delay)
        # collector[collector_row]['Sub'].append(sub_delay)
        collector[collector_row]['PubSub'].append(pub_sub_delay)
        collector[collector_row]['Total'].append(total_delay)

    async def show_stats():
        nonlocal last_time
        async with collector_lock:
            now = time.time()
            last_collector = collector.copy()
            _reset_collector()
        dt = now - last_time
        last_time = now
        print(time.strftime('%H:%M:%S', time.localtime(now)))
        for row in collector_rows:
            pps = len(last_collector[row]['Total']) / dt
            print(f"{row}  {pps:.1f} pps")
            print(
                f"    {'':10s}  {'median':6s}      {'max':7s}")
            for timing in timing_keys:
                if len(last_collector[row][timing]):
                    median = statistics.median(last_collector[row][timing])
                    max_val = max(last_collector[row][timing])
                else:
                    median = 0
                    max_val = 0
                median = median * 1000.0
                max_val = max_val * 1000.0
                print(
                    f"    {timing:10s} {median:6.3f} ms  {max_val:7.3f} ms")
            print()


    async def stat_watcher():
        while True:
            await asyncio.sleep(INTERVAL)
            await show_stats()

    async def collect_mqtt():
        async with asyncio_mqtt.client.Client(
            hostname=MQTT_BROKER_HOSTNAME,
            port=MQTT_BROKER_PORT,
            transport=MQTT_TRANSPORT,
            tls_context=MQTT_TLS_CONTEXT,
            keepalive=MQTT_KEEPALIVE,
            protocol=MQTT_PROTOCOL_VERSION,
            username=MQTT_USERNAME,
            password=MQTT_PASSWORD,
            will=None,
            client_id=MQTT_CLIENT_ID,
        ) as client:
            async with client.unfiltered_messages() as messages:
                # print("Connecting to client")
                # asyncio.run_coroutine_threadsafe(client.connect(),
                #                                  asyncio.get_running_loop())
                # print("Client connected")
                await client.subscribe(f"{MQTT_TOPIC_ROOT}/#")

                async for message in messages:
                    message: MQTTMessage

                    now = time.time()

                    mqtt_timestamp = message.timestamp
                    payload = message.payload.decode('utf-8')
                    payload_as_dict = json.loads(payload)

                    payload_class = payload_as_dict['class']
                    arrival_time = payload_as_dict['arrival_time']
                    create_time = payload_as_dict['create_time']
                    event_time = payload_as_dict['event_time']

                    create_delay = create_time - arrival_time
                    event_delay = event_time - create_time
                    # pub_delay = mqtt_timestamp - event_time
                    # sub_delay = now - mqtt_timestamp
                    pub_sub_delay = now - event_time
                    total_delay = now - create_time

                    await add_to_collector(
                        payload_class=payload_class,
                        create_delay=create_delay,
                        event_delay=event_delay,
                        # pub_delay=pub_delay,
                        # sub_delay=sub_delay,
                        pub_sub_delay=pub_sub_delay,
                        total_delay=total_delay,
                    )

    _reset_collector()
    last_time = time.time()
    await asyncio.gather(
        collect_mqtt(),
        stat_watcher(),
    )


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.run_until_complete(run())





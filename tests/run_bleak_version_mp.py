import asyncio
import multiprocessing
import os

import bleak.backends.bluezdbus.version as bv

async def subprocess_task():
    version_output  = await bv._get_bluetoothctl_version()
    if version_output:
        major, minor = tuple(map(int, version_output.groups()))
        print(major, minor)
    else:
        print("No version_output")
    await asyncio.sleep(1.0)

def subprocess_work():
    sploop = asyncio.new_event_loop()
    print(f"Inner loop: {sploop} {os.getpid()} {sploop._selector}")
    sploop.run_until_complete(subprocess_task())


if __name__ == '__main__':
    multiprocessing.set_start_method('spawn', force=True)
    loop = asyncio.new_event_loop()
    print(f"Outer loop: {loop} {os.getpid()} {loop._selector}")
    loop.run_until_complete(subprocess_task())
    p = multiprocessing.Process(target=subprocess_work)
    p.start()

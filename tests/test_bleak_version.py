import bleak.backends.bluezdbus.version as bv

import pytest

@pytest.mark.asyncio
async def test_version():
    version_output  = await bv._get_bluetoothctl_version()
    assert version_output
    major, minor = tuple(map(int, version_output.groups()))
    assert major == 5
    assert minor == 55




"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only


FlowSequencer

Responsible for coordinating the actions around any of the flow modes
"""
import time

import asyncio
import logging

from typing import Optional, Callable, Coroutine

from pyDE1.de1 import DE1
from pyDE1.de1.events import ShotSampleUpdate, StateUpdate, \
    ShotSampleWithVolumesUpdate
from pyDE1.de1.c_api import API_MachineStates, API_Substates, CUUID

from pyDE1.i_target_manager import I_TargetManager

from pyDE1.scale.processor import ScaleProcessor
from pyDE1.scale.events import WeightAndFlowUpdate

from pyDE1.utils import cancel_tasks_by_name

logger = logging.getLogger('FlowSequencer')


class FlowSequencer (I_TargetManager):

    def __init__(self):
        self._de1: Optional[DE1] = None
        self._scale_processor: Optional[ScaleProcessor] = None

        self._event_de1_present = asyncio.Event()
        self._event_scale_processor_present = asyncio.Event()

        self._active_state: Optional[API_MachineStates] = None
        self._sequence_start_time: float = 0
        # For later cancellation. Should this be static or dynamic?
        self._sequence_task_name: str = "SequencerSubtask"

        self._gate_sequence_start = asyncio.Event()
        # These are not necessarily in order
        self._gate_flow_begin = asyncio.Event()
        self._gate_expect_drops = asyncio.Event()
        # self._gate_first_drops = asyncio.Event()
        self._gate_exit_preinfuse = asyncio.Event()
        self._gate_flow_end = asyncio.Event()
        self._gate_flow_state_exit = asyncio.Event()
        self._gate_last_drops = asyncio.Event()
        # Though always "done" here (and should always be triggered)
        self._gate_sequence_complete = asyncio.Event()

        self._all_gates = [
            self._gate_sequence_start,
            self._gate_flow_begin,
            self._gate_expect_drops,
            self._gate_flow_end,
            self._gate_flow_state_exit,
            self._gate_last_drops,
            self._gate_sequence_complete,
        ]

        # Pressure at which _gate_expect_drops is triggered
        self._expect_drops_pressure = 2.0

        # How soon after flow-exit is reported can
        # _gate_last_drops be opened
        self._last_drops_minimum_time = 3.0

        self.autotare_states: list[API_MachineStates] = [
            API_MachineStates.Espresso,
            API_MachineStates.HotWater,
        ]

        self.stop_at_weight_states: list[API_MachineStates] = [
            API_MachineStates.Espresso,
            API_MachineStates.HotWater,
        ]

        self.stop_at_volume_states: list[API_MachineStates] = [
            API_MachineStates.Espresso,
            API_MachineStates.HotWater,
        ]

        self.last_drops_states = [
            API_MachineStates.Espresso,
            API_MachineStates.HotWater,     # TODO: Needed? Adjust?
            API_MachineStates.Steam,        # TODO: Needed? Adjust?
        ]

        self.stop_at_time_states = [
            API_MachineStates.HotWaterRinse,
            # API_MachineStates.Steam,  # Handled through ShotSettings
        ]

        # Recorder gets managed by the recorder itself

        # See getters and setters later

        self._stop_at_volume: dict[API_MachineStates, Optional[float]] = {}
        self._stop_at_weight: dict[API_MachineStates, Optional[float]] = {}
        self._stop_at_time: dict[API_MachineStates, Optional[float]] = {}

        # Internal flag, use None or value for
        # de1.stop_at_weight and/or de1.stop_at_volume
        self._stop_at_weight_active = False
        self._stop_at_volume_active = False
        self._stop_at_time_active = False

    @property
    def de1(self):
        return self._de1

    async def set_de1(self, value: DE1):
        # Needs to unsubscribe the old
        self._de1 = value
        self._de1._flow_sequencer = self
        self._event_de1_present.set()
        await asyncio.gather(
            self.de1.event_state_update.subscribe(
                self._create_state_update_callback()),

            self.de1.event_shot_sample.subscribe(
                self._create_shot_sample_update_callback()),

            self.de1.event_shot_sample_with_volumes_update.subscribe(
                self._create_stop_at_volume_subscriber()),

            # This will fail if the scale_processor hasn't been connected yet
            # self.scale_processor.event_weight_and_flow_update.subscribe(
            #     _create_stop_at_weight_subscriber(self.de1)),
        )
        asyncio.create_task(self._set_stop_at_weight_subscriber_when_possible())
        return self

    #
    # TODO: THIS NEEDS A LOT OF HELP FOR CHANGING EITHER
    #
    async def _set_stop_at_weight_subscriber_when_possible(self):
        await asyncio.gather(
            self._event_scale_processor_present.wait(),
            self._event_de1_present.wait(),
        )
        await self.scale_processor.event_weight_and_flow_update.subscribe(
            self._create_stop_at_weight_subscriber()
        )

    @property
    def scale_processor(self):
        return self._scale_processor

    async def set_scale_processor(self, value: ScaleProcessor):
        # Needs to unsubscribe the old
        self._scale_processor = value
        self._event_scale_processor_present.set()
        await self._scale_processor.event_weight_and_flow_update.subscribe(
                self._create_weight_and_flow_update_callback())
        return self

    @property
    def active_state(self):
        return self._active_state

    def stop_at_weight(self, state: Optional[API_MachineStates]=None) \
            -> Optional[float]:
        if state is None:
            state = self.active_state
        try:
            retval = self._stop_at_weight[state]
        except KeyError:
            retval = None
        return retval

    def stop_at_volume(self, state: Optional[API_MachineStates]=None) \
            -> Optional[float]:
        if state is None:
            state = self.active_state
        try:
            retval = self._stop_at_volume[state]
        except KeyError:
            retval = None
        return retval

    def stop_at_time(self, state: Optional[API_MachineStates]=None) \
            -> Optional[float]:
        if state is None:
            state = self.active_state
        try:
            retval = self._stop_at_time[state]
        except KeyError:
            retval = None
        return retval

    def stop_at_weight_set(self, state: API_MachineStates, weight: float):
        self._stop_at_weight[state] = weight

    def stop_at_volume_set(self, state: API_MachineStates, volume: float):
        self._stop_at_volume[state] = volume

    def stop_at_time_set(self, state: API_MachineStates,
                         duration: float) -> asyncio.Task:
        logger.debug("You can await stop_at_time_set_async() directly")
        return asyncio.create_task(self.stop_at_time_set_async(
            state=state,
            duration=duration,
        ))

    async def stop_at_time_set_async(self, state: API_MachineStates,
                                     duration: float):
        # TODO: Clean this up, can/should it be made sync to the caller?
        # TODO: Consider updating with a read after every write
        # NB:   The read seems to cost about 100 ms
        #           Trust that it wrote and do it in the background?
        #           Are simultaneous transactions on different CUUIDs are OK?
        #       Should be done in DE1 as SOR
        if state == API_MachineStates.Steam:
            ss = await self.de1.read_cuuid(CUUID.ShotSettings)
            # ss = ShotSettings().from_wire_bytes(ss_bytes)
            logger.debug(f"ShotSettings: read: {ss.log_string()}")
            if ss.TargetSteamLength != duration:
                ss.TargetSteamLength = duration
                await self.de1.write_packed_attr(ss)
            logger.debug(f"ShotSettings: Done")
        self._stop_at_time[state] = duration

    @property
    def sequence_start_time(self):
        return self._sequence_start_time

    def _close_all_gates(self):
        for gate in self._all_gates:
            gate.clear()

    # Weight and Flow Update handles auto-tare
    # SAW and SAV have their own handlers, supervisor enables and disables
    # Subscribe to the ScaleProcessor, let it handle scale-instance changes

    def _create_weight_and_flow_update_callback(self) -> Callable:
        flow_sequencer = self

        async def flow_sequencer_wafu_cb(wafu: WeightAndFlowUpdate):
            nonlocal flow_sequencer
            pass  # at least now, all the SAW is in ScaleProcessor

        return flow_sequencer_wafu_cb

    def _create_state_update_callback(self) -> Callable:
        flow_sequencer = self

        async def flow_sequencer_su_cb(su: StateUpdate):
            nonlocal flow_sequencer

            if su.state.is_flow_state:

                if not su.previous_state.is_flow_state:
                    flow_sequencer._start_sequence(su.state)
                    logger.info("Start sequence")

                if su.substate.flow_phase == 'during' \
                        and su.previous_substate.flow_phase != 'during':
                    flow_sequencer._gate_flow_begin.set()
                    logger.info("Gate: Flow begin")

                if su.previous_substate == API_Substates.PreInfuse \
                        and su.substate != API_Substates.PreInfuse:
                    flow_sequencer._gate_exit_preinfuse.set()
                    logger.info("Gate: Exit preinfuse")

                if su.previous_substate.flow_phase == 'during' \
                        and su.substate.flow_phase != 'during':
                    flow_sequencer._gate_flow_end.set()
                    asyncio.create_task(self._wait_for_last_drops(),
                                        name=self._sequence_task_name)
                    logger.info("Gate: Flow end")

            elif su.previous_state.is_flow_state:  # current is not a flow state
                if su.previous_substate == API_Substates.PreInfuse:
                    flow_sequencer._gate_exit_preinfuse.set()
                    logger.info("Gate: Exit preinfuse")
                if su.previous_substate.flow_phase == 'during':
                    flow_sequencer._gate_flow_end.set()
                    logger.info("Gate: Flow end")
                flow_sequencer._gate_flow_state_exit.set()
                logger.info("Gate: Flow state exit")

        return flow_sequencer_su_cb

    def _create_shot_sample_update_callback(self) -> Callable:
        flow_sequencer = self

        async def flow_sequencer_ssu_cb(ssu: ShotSampleUpdate):
            nonlocal flow_sequencer

            # Yet another place having to use current [sub]state off DE1
            de1 = flow_sequencer.de1
            if de1.current_state.is_flow_state \
                    and not flow_sequencer._gate_expect_drops.is_set() \
                    and de1.current_substate.flow_phase == 'during' \
                    and ssu.group_pressure \
                        > flow_sequencer._expect_drops_pressure:
                flow_sequencer._gate_expect_drops.set()
                logger.info("Gate: Expect drops")

        return flow_sequencer_ssu_cb

    def _start_sequence(self, state: API_MachineStates):
        """
        Kick off parallel tasks to manage functions during the shot
        Tasks should wait for self._gate_sequence_start
        """
        self._sequence_start_time = time.time()
        # TODO: Is there a more robust way to transition from an "aborted"
        #       shot to another one?
        if not self._gate_sequence_complete.is_set() \
                and self._sequence_start_time != 0:
            self._abort_sequence()

        self._active_state = state
        self._close_all_gates()

        # create a bunch of tasks
        # Keep the start gate closed, as some may expect others to exist
        # or need to
        # For now, don't name uniquely and see what the logger returns

        asyncio.create_task(self._sequence_end_sequence(),
                            name=self._sequence_task_name)

        asyncio.create_task(self._sequence_volume_tracking(),
                            name=self._sequence_task_name)

        asyncio.create_task(self._sequence_stop_at_volume(),
                            name=self._sequence_task_name)

        asyncio.create_task(self._sequence_scale_tare(),
                            name=self._sequence_task_name)

        asyncio.create_task(self._sequence_stop_at_weight(),
                            name=self._sequence_task_name)

        asyncio.create_task(self._sequence_stop_at_time(),
                            name=self._sequence_task_name)

        asyncio.create_task(self._sequence_recorder(),
                            name=self._sequence_task_name)

        self._gate_sequence_start.set()
        logger.info("Gate: Sequence start")

    async def _wait_for_last_drops(self):
        await asyncio.sleep(self._last_drops_minimum_time)
        self._gate_last_drops.set()
        logger.info("Gate: Last drops")

    async def _sequence_end_sequence(self):
        """
        Maybe a funky way to do it, but this captures "done-ness"
        in one place.
        """
        await self._gate_flow_state_exit.wait()
        if self.active_state in self.last_drops_states:
            try:
                await asyncio.wait_for(self._gate_last_drops.wait(),
                                  timeout=self._last_drops_minimum_time)
            except asyncio.exceptions.TimeoutError:
                pass
        await self._end_sequence()

    async def _end_sequence(self):
        """
        Not all subtasks will have gone through all their gates
        Set the completion Event and give a second for tasks to complete
        Clean up any stragglers
        """
        self._gate_sequence_complete.set()
        logger.info("Gate: Sequence complete")
        await asyncio.sleep(0.100)
        self._cleanup_stragglers()

    def _abort_sequence(self):
        """
        Not all subtasks will have gone through all their gates
        or sequence_complete may not have been set.

        This is a "no-wait" version

        Set the completion Event
        Clean up any stragglers
        """
        self._gate_sequence_complete.set()
        logger.info("Gate: Sequence complete: _abort_sequence()")
        self._cleanup_stragglers()

    def _cleanup_stragglers(self):
        """
        This will send CancelledError to the coroutine

        That should be caught and handled for cleanup
        or completion of tasks, such as writing files

        cancel_tasks_by_name() won't cancel its own task
        """
        logger.info("Canceling stragglers")
        cancel_tasks_by_name(self._sequence_task_name, starts_with=False)


###
### Sequences
###

    # TODO: These should be sensitive to the kind of flow
    #       just get them in for espresso for now

    async def _sequence_volume_tracking(self):
        de1 = self.de1
        try:
            await self._gate_sequence_start.wait()
            de1._reset_volume_dispensed()
            logger.debug("Volume: reset")

            await self._gate_flow_begin.wait()
            de1._tracking_volume_dispensed = True
            logger.debug("Volume: tracking start")

            await self._gate_flow_end.wait()
            de1._tracking_volume_dispensed = False
            logger.debug("Volume: tracking stop")

        except asyncio.CancelledError:
            de1._tracking_volume_dispensed = False
            logger.info("Volume: tracking stop - on cancel")
            raise

    async def _sequence_scale_tare(self):
        scale = self._scale_processor.scale
        if self.active_state not in self.autotare_states:
            scale.hold_at_tare = False
            logger.debug(f"Scale: release - {self.active_state.name}")
            return
        try:
            await self._gate_sequence_start.wait()
            scale.hold_at_tare = True
            logger.debug("Scale: hold at tare")

            await self._gate_expect_drops.wait()
            scale.hold_at_tare = False
            logger.debug("Scale: release")

        except asyncio.CancelledError:
            scale = self._scale_processor.scale
            scale.hold_at_tare = False
            logger.info("Scale: release - on cancel")
            raise

    async def _sequence_stop_at_volume(self):
        if self.active_state not in self.stop_at_volume_states:
            self._stop_at_volume_active = False
            logger.debug(f"StopAtVolume: disable - {self.active_state.name}")
            return
        try:
            await self._gate_sequence_start.wait()
            self._stop_at_volume_active = False
            logger.debug("StopAtVolume: disable")

            await self._gate_exit_preinfuse.wait()
            self._stop_at_volume_active = True
            logger.debug("StopAtVolume: enable")

            await self._gate_flow_end.wait()
            self._stop_at_volume_active = False
            logger.debug("StopAtVolume: disable")

        except asyncio.CancelledError:
            self._stop_at_volume_active = False
            logger.info("StopAtVolume: disable - on cancel")
            raise

    async def _sequence_stop_at_weight(self):
        if self.active_state not in self.stop_at_weight_states:
            self._stop_at_weight_active = False
            logger.info(f"StopAtWeight: disable - {self.active_state.name}")
            return
        try:
            await self._gate_sequence_start.wait()
            self._stop_at_weight_active = False
            logger.debug("StopAtWeight: disable")

            await self._gate_expect_drops.wait()
            self._stop_at_weight_active = True
            logger.debug("StopAtWeight: enable")

            await self._gate_flow_end.wait()
            self._stop_at_weight_active = False
            logger.debug("StopAtWeight: disable")

        except asyncio.CancelledError:
            self._stop_at_weight_active = False
            logger.info("StopAtWeight: disable - on cancel")
            raise

    async def _sequence_stop_at_time(self):
        if self.active_state not in self.stop_at_time_states:
            self._stop_at_time_active = False
            logger.info(f"StopAtTime: disable - {self.active_state.name}")
            return
        try:
            await self._gate_sequence_start.wait()
            self._stop_at_time_active = False
            logger.debug("StopAtTime: disable")

            await self._gate_flow_begin.wait()
            self._stop_at_time_active = True
            wait = self.stop_at_time(self.active_state)
            logger.debug(f"StopAtTime: enable ({wait} seconds)")
            await asyncio.sleep(self.stop_at_time(self.active_state))
            logger.debug(f"StopAtTime: triggered, requesting stop_flow")
            await self.de1.stop_flow()
            logger.debug(f"StopAtTime: triggered ({wait} seconds)")

            await self._gate_flow_end.wait()
            self._stop_at_time_active = False
            logger.debug("StopAtTime: disable")

        except asyncio.CancelledError:
            self._stop_at_time_active = False
            logger.info("StopAtTime: disable - on cancel")
            raise

    async def _sequence_recorder(self):
        de1 = self._de1
        try:
            # Always enable recording, let the recorder decide
            await self._gate_sequence_start.wait()
            de1._recorder_active = True
            logger.debug("Recorder: enable")

            await self._gate_sequence_complete.wait()
            de1._recorder_active = False
            logger.debug("Recorder: disable")

        except asyncio.CancelledError:
            de1._recorder_active = False
            logger.info("Recorder: disable - on cancel")
            raise

    def _create_stop_at_volume_subscriber(self) -> Coroutine:
        """
        Should be subscribed to ShotSampleWithVolumesUpdate on DE1
        """
        flow_sequencer = self
        sav_logger = logging.getLogger('StopAtVolume')

        async def stop_at_volume(sswvu: ShotSampleWithVolumesUpdate):
            nonlocal flow_sequencer, sav_logger

            if flow_sequencer._stop_at_volume_active \
                    and (target := flow_sequencer.stop_at_volume()) is not None:
                if sswvu.volume_pour >= target:
                    await flow_sequencer.de1.stop_flow()
                    sav_logger.info(
                        "Triggered at {:.1f} mL for {:.1f} mL target".format(
                            sswvu.volume_pour, target))

        return stop_at_volume

    def _create_stop_at_weight_subscriber(self) -> Coroutine:
        """
        Should be subscribed to WeightAndFlowUpdate on ScaleProcessor
        """
        flow_sequencer = self
        saw_logger = logging.getLogger('StopAtWeight')

        async def stop_at_weight(wafu: WeightAndFlowUpdate):
            nonlocal flow_sequencer, saw_logger

            if flow_sequencer._stop_at_weight_active \
                    and (target := flow_sequencer.stop_at_weight()) is not None:
                # TODO: where does this belong?
                adjust = -0.3  # seconds, larger means more in cup
                # TODO: where does this belong?
                stop_lag = flow_sequencer.de1.stop_lead_time
                # TODO: Should this be switchable?
                flow = wafu.average_flow
                dw = target - wafu.current_weight
                if flow > 0:
                    dt = dw / flow
                    target_time = wafu.scale_time + dt + adjust - stop_lag
                    if time.time() >= target_time:
                        await flow_sequencer.de1.stop_flow()
                        saw_logger.info(
                            "Triggered at {:.1f} g for {:.1f} g target".format(
                                wafu.current_weight, target))

        return stop_at_weight

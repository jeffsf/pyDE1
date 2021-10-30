"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only


FlowSequencer

Responsible for coordinating the actions around any of the flow modes
"""
import asyncio
import multiprocessing
import time
from typing import Optional, Callable, Coroutine, List

import pyDE1
from pyDE1.config import config
from pyDE1.database.create_history_record import create_history_record
from pyDE1.database.recorder_control import RecorderControl
from pyDE1.de1 import DE1
from pyDE1.de1.ble import CUUID
from pyDE1.de1.c_api import (
    API_MachineStates, API_Substates, MMR0x80LowAddr
)
from pyDE1.de1.events import (
    ShotSampleUpdate, StateUpdate, ShotSampleWithVolumesUpdate
)
from pyDE1.event_manager import (
    SequencerGate, SequencerGateName, SequencerGateNotification,
    send_to_outbound_pipes
)
from pyDE1.exceptions import (
    DE1APIValueError, DE1APIAttributeError, DE1APITypeError,
    DE1APINotManagedHereException
)
from pyDE1.flow_sequencer import (
    FlowSequencer, LAST_DROPS_MINIMUM_TIME_DEFAULT,
    FIRST_DROPS_THRESHOLD_DEFAULT, StopAtNotificationAction, StopAtType,
    StopAtNotification, AutoTareNotificationAction, AutoTareNotification,
    ByModeControl, StopAtTime, StopAtVolume, StopAtWeight,
)
from pyDE1.scale.events import WeightAndFlowUpdate
from pyDE1.scale.processor import ScaleProcessor
from pyDE1.singleton import Singleton
from pyDE1.utils import cancel_tasks_by_name

logger = pyDE1.getLogger('FlowSequencer')


class FlowSequencerImpl (Singleton, FlowSequencer):

    # NB: This is intentionally done in _singleton_init() and not __init__()
    #     See Singleton and Guido's notes there
    #
    # def __init__(self):
    #     pass

    database_queue: Optional[multiprocessing.Queue] = None

    def _singleton_init(self):

        # Singletons now
        self._de1 = DE1()
        self._scale_processor = ScaleProcessor()

        # self._event_de1_present = asyncio.Event()
        # self._event_scale_processor_present = asyncio.Event()

        self._active_state: Optional[API_MachineStates] = None
        self._sequence_start_time: float = 0
        # For later cancellation. Should this be static or dynamic?
        self._sequence_task_name: str = "SequencerSubtask"

        self._gate_sequence_start = SequencerGate(self,
            SequencerGateName.GATE_SEQUENCE_START)
        # These are not necessarily in order
        self._gate_flow_begin = SequencerGate(self,
            SequencerGateName.GATE_FLOW_BEGIN)
        self._gate_expect_drops = SequencerGate(self,
            SequencerGateName.GATE_EXPECT_DROPS)
        # self._gate_first_drops = asyncio.Event()
        self._gate_exit_preinfuse = SequencerGate(self,
            SequencerGateName.GATE_EXIT_PREINFUSE)
        self._gate_flow_end = SequencerGate(self,
            SequencerGateName.GATE_FLOW_END)
        self._gate_flow_state_exit = SequencerGate(self,
            SequencerGateName.GATE_FLOW_STATE_EXIT)
        self._gate_last_drops = SequencerGate(self,
            SequencerGateName.GATE_LAST_DROPS)
        # Though always "done" here (and should always be triggered)
        self._gate_sequence_complete = SequencerGate(self,
            SequencerGateName.GATE_SEQUENCE_COMPLETE)

        self._all_gates = [
            self._gate_sequence_start,
            self._gate_flow_begin,
            self._gate_expect_drops,
            self._gate_exit_preinfuse,
            self._gate_flow_end,
            self._gate_flow_state_exit,
            self._gate_last_drops,
            self._gate_sequence_complete,
        ]

        self.espresso_control = EspressoControl()
        self.steam_control = SteamControl()
        self.hot_water_control = HotWaterControl()
        self.hot_water_rinse_control = HotWaterRinseControl()

        # TODO: Refactor these out in favor of None in the ByModeControl
        self.autotare_states: List[API_MachineStates] = [
            API_MachineStates.Espresso,
            API_MachineStates.HotWater,
        ]

        self.stop_at_weight_states: List[API_MachineStates] = [
            API_MachineStates.Espresso,
            API_MachineStates.HotWater,
        ]

        self.stop_at_volume_states: List[API_MachineStates] = [
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

        # Internal flag, use None or value for
        # de1.stop_at_weight and/or de1.stop_at_volume
        self._stop_at_weight_active = False
        self._stop_at_volume_active = False
        self._stop_at_time_active = False

        asyncio.create_task(self.set_up_subscribers())

    @property
    def stop_at_weight_adjust(self):
        """
        In seconds, larger increases weight in cup

        Supply as a property to simplify the stop-at-weight closure
        and allow the value to be changed after the closure is created
        """
        return config.de1.STOP_AT_WEIGHT_ADJUST

    @property
    def de1(self):
        return self._de1

    async def set_up_subscribers(self):
        # DE1 only knows that its _flow_sequencer is an I_TargetSetter
        # because of circular imports, so it can't reference FlowSequencer
        self._de1._flow_sequencer = self

        await asyncio.gather(
            self.de1.event_state_update.subscribe(
                self._create_state_update_callback()),

            self.de1.event_shot_sample.subscribe(
                self._create_shot_sample_update_callback()),

            self.de1.event_shot_sample_with_volumes_update.subscribe(
                self._create_stop_at_volume_subscriber()),

            self.scale_processor.event_weight_and_flow_update.subscribe(
                self._create_stop_at_weight_subscriber()),
        )
        logger.info("FlowSequencer subscriptions done")
        return self

    @property
    def scale_processor(self):
        return self._scale_processor

    @property
    def active_state(self):
        return self._active_state

    def active_control_for_state(self, state: API_MachineStates) \
            -> 'ByModeControl':
        retval = None
        if state is API_MachineStates.Espresso:
            retval = self.espresso_control
        elif state is API_MachineStates.Steam:
            retval = self.steam_control
        elif state is API_MachineStates.HotWater:
            retval = self.hot_water_control
        elif state is API_MachineStates.HotWaterRinse:
            retval = self.hot_water_rinse_control
        return retval

    @property
    def active_control(self) -> 'ByModeControl':
        return self.active_control_for_state(self.active_state)

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
            try:
                threshold = flow_sequencer.active_control.first_drops_threshold
            except AttributeError:
                threshold = None
            if de1.current_state.is_flow_state \
                    and threshold is not None \
                    and not flow_sequencer._gate_expect_drops.is_set() \
                    and de1.current_substate.flow_phase == 'during' \
                    and ssu.group_pressure \
                        > flow_sequencer.active_control.first_drops_threshold:
                flow_sequencer._gate_expect_drops.set()
                logger.info("Gate: Expect drops")

        return flow_sequencer_ssu_cb

    # Should this be async def now?
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

        sequence_id = SequencerGateNotification.new_sequence()
        logger.info(f"Starting {self.active_state.name}, "
                    f"sequence_id {sequence_id}")

        # Can't really start the recorder here as it needs
        # to be able to create the sequence (history) record
        # which can take up to 250 ms

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


    async def _sequence_end_sequence(self):
        """
        Maybe a funky way to do it, but this captures "done-ness"
        in one place.
        """
        await self._gate_flow_end.wait()
        ldmt = self.active_control.last_drops_minimum_time
        if ldmt:
            try:
                await asyncio.wait_for(self._gate_last_drops.wait(),
                                  timeout=ldmt)
            except asyncio.exceptions.TimeoutError:
                pass
        self._gate_last_drops.set()
        await self._gate_flow_state_exit.wait()
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
        logger.debug("Canceling stragglers")
        cancel_tasks_by_name(self._sequence_task_name, starts_with=False)


###
### Sequences
###

    # TODO: These should be sensitive to the kind of flow
    #       Just get them in for espresso for now

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
        if scale is None:
            logger.info("No scale present, will not hold at tare")
            return
        if self.active_state not in self.autotare_states:
            scale.hold_at_tare = False
            logger.debug(f"Scale: release - {self.active_state.name}")
            await self.auto_tare_notify(AutoTareNotificationAction.DISABLED)
            return
        try:
            await self._gate_sequence_start.wait()
            scale.hold_at_tare = True
            logger.debug("Scale: hold at tare")
            await self.auto_tare_notify(AutoTareNotificationAction.ENABLED)

            await self._gate_expect_drops.wait()
            scale.hold_at_tare = False
            logger.debug("Scale: release")
            await self.auto_tare_notify(AutoTareNotificationAction.DISABLED)

        except asyncio.CancelledError:
            scale = self._scale_processor.scale
            scale.hold_at_tare = False
            logger.info("Scale: release - on cancel")
            await self.auto_tare_notify(AutoTareNotificationAction.DISABLED)
            raise

    async def _sequence_stop_at_volume(self):
        if self.active_state not in self.stop_at_volume_states:
            self._stop_at_volume_active = False
            logger.debug(f"StopAtVolume: disable - {self.active_state.name}")
            await self.stop_at_notify(
                stop_at=StopAtType.VOLUME,
                action=StopAtNotificationAction.DISABLED)
            return
        try:
            await self._gate_sequence_start.wait()
            self._stop_at_volume_active = False
            logger.debug("StopAtVolume: disable")
            await self.stop_at_notify(
                stop_at=StopAtType.VOLUME,
                action=StopAtNotificationAction.DISABLED)

            await self._gate_exit_preinfuse.wait()
            self._stop_at_volume_active = True
            logger.debug("StopAtVolume: enable")
            await self.stop_at_notify(
                stop_at=StopAtType.VOLUME,
                action=StopAtNotificationAction.ENABLED)

            await self._gate_flow_end.wait()
            self._stop_at_volume_active = False
            logger.debug("StopAtVolume: disable")
            await self.stop_at_notify(
                stop_at=StopAtType.VOLUME,
                action=StopAtNotificationAction.DISABLED)

        except asyncio.CancelledError:
            self._stop_at_volume_active = False
            logger.info("StopAtVolume: disable - on cancel")
            await self.stop_at_notify(
                stop_at=StopAtType.VOLUME,
                action=StopAtNotificationAction.DISABLED)
            raise

    async def _sequence_stop_at_weight(self):
        if self.active_state not in self.stop_at_weight_states:
            self._stop_at_weight_active = False
            logger.info(f"StopAtWeight: disable - {self.active_state.name}")
            await self.stop_at_notify(
                stop_at=StopAtType.WEIGHT,
                action=StopAtNotificationAction.DISABLED)
            return
        try:
            await self._gate_sequence_start.wait()
            self._stop_at_weight_active = False
            logger.debug("StopAtWeight: disable")
            await self.stop_at_notify(
                stop_at=StopAtType.WEIGHT,
                action=StopAtNotificationAction.DISABLED)

            await self._gate_expect_drops.wait()
            self._stop_at_weight_active = True
            logger.debug("StopAtWeight: enable")
            await self.stop_at_notify(
                stop_at=StopAtType.WEIGHT,
                action=StopAtNotificationAction.ENABLED)

            await self._gate_flow_end.wait()
            self._stop_at_weight_active = False
            logger.debug("StopAtWeight: disable")
            await self.stop_at_notify(
                stop_at=StopAtType.WEIGHT,
                action=StopAtNotificationAction.DISABLED)

        except asyncio.CancelledError:
            self._stop_at_weight_active = False
            logger.info("StopAtWeight: disable - on cancel")
            await self.stop_at_notify(
                stop_at=StopAtType.WEIGHT,
                action=StopAtNotificationAction.DISABLED)
            raise

    async def _sequence_stop_at_time(self):
        if ((self.active_state == API_MachineStates.Steam)
                or (self.active_state == API_MachineStates.HotWaterRinse
                    and self.de1.feature_flag.rinse_control)):
            self._stop_at_time_active = False
            logger.info(
                "StopAtTime: DE1 controlled for "
                f"{self.active_state.name}  "
                f"({self.active_control.stop_at_time:.1f} seconds)")
            await self.stop_at_notify(
                stop_at=StopAtType.TIME,
                action=StopAtNotificationAction.DE1CONTROLLED)
            return

        if self.active_state not in self.stop_at_time_states:
            self._stop_at_time_active = False
            logger.info(f"StopAtTime: disable - {self.active_state.name}")
            await self.stop_at_notify(
                stop_at=StopAtType.TIME,
                action=StopAtNotificationAction.DISABLED)
            return

        try:
            await self._gate_sequence_start.wait()
            self._stop_at_time_active = False
            logger.debug("StopAtTime: disable")
            await self.stop_at_notify(
                stop_at=StopAtType.TIME,
                action=StopAtNotificationAction.DISABLED)

            # NB: Changing the time after starting won't alter the duration
            #     at least as presently implemented

            try:
                wait = self.active_control.stop_at_time
            except DE1APINotManagedHereException as e:
                # Steam timeout is managed by the DE1 itself
                # though shouldn't get here
                logger.error(
                    f"Unexpectedly getting through to {e}, "
                    "check stop_at_time_states")
                return

            if wait is None or wait <= 0:
                return

            await self._gate_flow_begin.wait()
            self._stop_at_time_active = True
            t0 = time.time()
            logger.debug(f"StopAtTime: enable ({wait} seconds)")
            await self.stop_at_notify(
                stop_at=StopAtType.TIME,
                action=StopAtNotificationAction.ENABLED)

            await asyncio.sleep(wait)
            logger.debug(f"StopAtTime: triggered, requesting stop_flow")
            await self.de1.stop_flow()
            logger.debug(f"StopAtTime: triggered ({wait} seconds)")
            await self.stop_at_notify(
                stop_at=StopAtType.TIME,
                action=StopAtNotificationAction.TRIGGERED,
                current=(time.time() - t0))

            await self._gate_flow_end.wait()
            self._stop_at_time_active = False
            logger.debug("StopAtTime: disable")
            await self.stop_at_notify(
                stop_at=StopAtType.TIME,
                action=StopAtNotificationAction.DISABLED)

        except asyncio.CancelledError:
            self._stop_at_time_active = False
            logger.info("StopAtTime: disable - on cancel")
            await self.stop_at_notify(
                stop_at=StopAtType.TIME,
                action=StopAtNotificationAction.DISABLED)
            raise

    async def _sequence_recorder(self):
        # Always enable recording, let the recorder decide

        de1 = self._de1

        try:
            profile_id = self.de1.latest_profile.id
        except AttributeError:
            logger.warning("Unable to determine profile for sequence record")
            profile_id = None

        try:
            await create_history_record(
                    self.active_state,
                    self.sequence_start_time,
                    profile_id)
            await self._gate_sequence_start.wait()

            FlowSequencer.database_queue.put_nowait(
                RecorderControl(
                    recording = True,
                    sequence_id=SequencerGateNotification.sequence_id))
            logger.debug("Recorder: enable")

            await self._gate_sequence_complete.wait()
            FlowSequencer.database_queue.put_nowait(
                RecorderControl(
                    recording = False,
                    sequence_id=SequencerGateNotification.sequence_id))
            logger.debug("Recorder: disable")

        except asyncio.CancelledError:
            FlowSequencer.database_queue.put_nowait(
                RecorderControl(
                    recording = False,
                    sequence_id=SequencerGateNotification.sequence_id))
            logger.info("Recorder: disable - on cancel")
            raise

    def _create_stop_at_volume_subscriber(self) -> Coroutine:
        """
        Should be subscribed to ShotSampleWithVolumesUpdate on DE1
        """
        flow_sequencer = self
        sav_logger = pyDE1.getLogger('FlowSequencer.StopAtVolume')

        async def stop_at_volume(sswvu: ShotSampleWithVolumesUpdate):
            nonlocal flow_sequencer, sav_logger

            if (flow_sequencer._stop_at_volume_active
                    and (target := flow_sequencer.active_control.stop_at_volume)
                    is not None):
                if sswvu.volume_pour >= target:
                    await flow_sequencer.de1.stop_flow()
                    sav_logger.info(
                        "Triggered at {:.1f} mL for {:.1f} mL target".format(
                            sswvu.volume_pour, target))
                    await flow_sequencer.stop_at_notify(
                        stop_at=StopAtType.VOLUME,
                        action=StopAtNotificationAction.TRIGGERED,
                        current=sswvu.volume_pour)

        return stop_at_volume

    def _create_stop_at_weight_subscriber(self) -> Coroutine:
        """
        Should be subscribed to WeightAndFlowUpdate on ScaleProcessor
        """
        flow_sequencer = self
        saw_logger = pyDE1.getLogger('FlowSequencer.StopAtWeight')

        async def stop_at_weight(wafu: WeightAndFlowUpdate):
            nonlocal flow_sequencer, saw_logger

            if (flow_sequencer._stop_at_weight_active
                    and (target := flow_sequencer.active_control.stop_at_weight)
                    is not None):
                stop_lag = flow_sequencer.de1.stop_lead_time
                # TODO: Should the choice of flow estimate be switchable?
                flow = wafu.average_flow
                dw = target - wafu.current_weight
                if flow > 0:
                    dt = dw / flow
                    target_time = wafu.scale_time + dt \
                                  - flow_sequencer.de1.stop_lead_time \
                                  - flow_sequencer.de1.fall_time \
                                  + flow_sequencer.stop_at_weight_adjust
                    if time.time() >= target_time:
                        await flow_sequencer.de1.stop_flow()
                        saw_logger.info(
                            "Triggered at {:.1f} g for {:.1f} g target".format(
                                wafu.current_weight, target))
                        await flow_sequencer.stop_at_notify(
                            stop_at=StopAtType.WEIGHT,
                            action=StopAtNotificationAction.TRIGGERED,
                            current=wafu.current_weight)

        return stop_at_weight

    async def stop_at_notify(self, stop_at: StopAtType,
                             action: StopAtNotificationAction,
                             current: Optional[float]=None):

        if action == StopAtNotificationAction.DISABLED:
            target = None
        elif stop_at == StopAtType.TIME:
            target = self.active_control.stop_at_time
        elif stop_at == StopAtType.VOLUME:
            target = self.active_control.stop_at_volume
        elif stop_at == StopAtType.WEIGHT:
            target = self.active_control.stop_at_weight
        else:
            target = None
        notification = StopAtNotification(
            stop_at=stop_at,
            action=action,
            target_value=target,
            current_value=current,
            active_state=self.active_state
        )
        # Usinf FlowSequencer() here still results in FlowSequencerImpl
        notification._sender = self
        await send_to_outbound_pipes(notification)

    async def auto_tare_notify(self, action: AutoTareNotificationAction):
        notification = AutoTareNotification(action=action)
        notification._sender = self
        await send_to_outbound_pipes(notification)

    def stop_at_time_set(self, state: API_MachineStates, duration: float):
        bmc = self.active_control_for_state(state)
        if bmc is None:
            raise DE1APIValueError(
                f"No ByModeController for {state}")
        if not isinstance(bmc, StopAtTime):
            raise DE1APIAttributeError(
                f"Not a StopAtTime ByModeControl {bmc}"
            )
        try:
            if not bmc.profile_can_override_stop_limits:
                return
        except AttributeError:
            pass
        bmc.stop_at_time = duration

    def stop_at_volume_set(self, state: API_MachineStates, volume: float):
        bmc = self.active_control_for_state(state)
        if bmc is None:
            raise DE1APIValueError(
                f"No ByModeController for {state}")
        if not isinstance(bmc, StopAtVolume):
            raise DE1APIAttributeError(
                f"Not a StopAtTime ByModeControl {bmc}"
            )
        try:
            if not bmc.profile_can_override_stop_limits:
                return
        except AttributeError:
            pass
        bmc.stop_at_volume = volume

    def stop_at_weight_set(self, state: API_MachineStates, weight: float):
        bmc = self.active_control_for_state(state)
        if bmc is None:
            raise DE1APIValueError(
                f"No ByModeController for {state}")
        if not isinstance(bmc, StopAtWeight):
            raise DE1APIAttributeError(
                f"Not a StopAtTime ByModeControl {bmc}"
            )
        try:
            if not bmc.profile_can_override_stop_limits:
                return
        except AttributeError:
            pass
        bmc.stop_at_weight = weight

    def profile_can_override_stop_limits(self, state: API_MachineStates):
        bmc = self.active_control_for_state(state)
        if bmc is None:
            raise DE1APIValueError(
                f"No ByModeController for {state}")
        try:
            return bmc.profile_can_override_stop_limits
        except AttributeError:
            return True

    def profile_can_override_tank_temperature(self, state: API_MachineStates):
        bmc = self.active_control_for_state(state)
        if bmc is None:
            raise DE1APIValueError(
                f"No ByModeController for {state}")
        try:
            return bmc.profile_can_override_tank_temperature
        except AttributeError:
            return True

    async def on_de1_nearly_ready(self):
        await self.hot_water_rinse_control.on_de1_nearly_ready()


class EspressoControl (StopAtTime, StopAtVolume, StopAtWeight, ByModeControl):

    def __init__(self, disable_auto_tare: bool = False,
                 stop_at_time: Optional[float] = None,
                 stop_at_volume: Optional[float] = None,
                 stop_at_weight: Optional[float] = None,
                 profile_can_override_stop_limits: bool = True,
                 profile_can_override_tank_temperature: bool = True,
                 first_drops_threshold: Optional[float] = \
                         FIRST_DROPS_THRESHOLD_DEFAULT,
                 last_drops_minimum_time: float = \
                         LAST_DROPS_MINIMUM_TIME_DEFAULT,
                 ):
        self._profile_can_override_stop_limits = True
        self._profile_can_override_tank_temperature = True
        self._first_drops_threshold = None
        ByModeControl.__init__(self, disable_auto_tare=disable_auto_tare)
        StopAtTime.__init__(self, stop_at_time=stop_at_time)
        StopAtVolume.__init__(self, stop_at_volume=stop_at_volume)
        StopAtWeight.__init__(self, stop_at_weight=stop_at_weight)
        self._profile_can_override_stop_limits \
            = profile_can_override_stop_limits
        self._profile_can_override_tank_temperature \
            = profile_can_override_tank_temperature
        self.first_drops_threshold = first_drops_threshold
        self.last_drops_minimum_time = last_drops_minimum_time

    @property
    def profile_can_override_stop_limits(self):
        return self._profile_can_override_stop_limits

    @profile_can_override_stop_limits.setter
    def profile_can_override_stop_limits(self, value):
        if not isinstance(value, bool):
            raise DE1APITypeError(
                "profile_can_override_stop_limits must be a bool, "
                f"not {value}"
            )
        self._profile_can_override_stop_limits = value

    @property
    def profile_can_override_tank_temperature(self):
        return self._profile_can_override_tank_temperature

    @profile_can_override_tank_temperature.setter
    def profile_can_override_tank_temperature(self, value):
        if not isinstance(value, bool):
            raise DE1APITypeError(
                "profile_can_override_tank_temperature must be a bool, "
                f"not {value}"
            )
        self._profile_can_override_tank_temperature = value

    @property
    def first_drops_threshold(self):
        return self._first_drops_threshold

    @first_drops_threshold.setter
    def first_drops_threshold(self, value):
        if value and not (0 <= value <= 10):
            raise DE1APIValueError(
                f"first_drops_threshold not 0 <= {value} <= 10")
        self._first_drops_threshold = value

    @property
    def last_drops_minimum_time(self):
        return self._last_drops_minimum_time

    @last_drops_minimum_time.setter
    def last_drops_minimum_time(self, value):
        if value < 0:
            raise DE1APIValueError(
                f"last_drops_minimum_time less than zero ({value}")
        self._last_drops_minimum_time = value


class SteamControl (ByModeControl):

        def __init__(self, disable_auto_tare: bool = True):
            super(SteamControl, self).__init__(
                disable_auto_tare=disable_auto_tare)

        @property
        def stop_at_time(self):
            """
            Return the value from the DE1 for consistency with flush,
            which is managed by the DE1 starting with FW 1283
            """
            return FlowSequencer().de1._cuuid_dict[
                CUUID.ShotSettings].last_value.TargetSteamLength

        @stop_at_time.setter
        def stop_at_time(self, value):
            raise DE1APINotManagedHereException(
                "Steam time is set in the DE1 with CUUID.ShotSettings"
            )


class HotWaterControl (StopAtWeight, ByModeControl):

    def __init__(self, disable_auto_tare: bool = True,
                 stop_at_weight: Optional[float] = None,
                 ):
        ByModeControl.__init__(self,
                               disable_auto_tare=disable_auto_tare)
        StopAtWeight.__init__(self, stop_at_weight=stop_at_weight)


class HotWaterRinseControl (StopAtTime, ByModeControl):

    # Duration is controlled by FlowSequencer prior to FW 1283
    # but is handled by the DE1 after FW 1283
    # Define setter/getter that checks feature_flag.rinse_control

    # If the firmware version is unknown or is prior to 1283:
    #   manage the stop-at-time here
    #
    # If the DE1 is connected and is firmware enabled and a change is made:
    #   note that the change was made here and its value
    #   pass through to the DE1
    #   let the DE1 manage stop-at-time
    #
    # If a DE1 connects and is not firmware enabled:
    #   stay the course
    #
    # If a DE1 connects and is firmware enabled:
    #   And FS has been explicitly set through the API
    #       Use the FS value and send to the DE1
    #   But the FS has not been explicitly set
    #       Use the DE1 value, but don't mark as "explicitly set" (??)

    def __init__(self, disable_auto_tare: bool = True,
                 stop_at_time: Optional[float] = None,
                 ):
        ByModeControl.__init__(self,
                               disable_auto_tare=disable_auto_tare)
        StopAtTime.__init__(self, stop_at_time=stop_at_time)
        # Distinguish between not set and intentionally set to None
        self._stop_at_time_api_set = False

    @property
    def stop_at_time(self):
        de1 = FlowSequencer().de1
        if de1 is not None and de1.is_ready \
                and de1.feature_flag.rinse_control:
            retval = de1._mmr_dict[
                MMR0x80LowAddr.FLUSH_TIMEOUT].data_decoded
        else:
            retval = self._stop_at_time
        return retval

    @stop_at_time.setter
    def stop_at_time(self, value):
        raise DE1APINotManagedHereException(
            "Flush time needs to be set through the FlowSequencer "
            "as it may be managed by the DE1 with later firmware."
        )

    async def stop_at_time_set_async(self, value):
        self._stop_at_time = self._validate_stop_at(value)
        self._stop_at_time_api_set = True
        de1 = FlowSequencer().de1
        if de1 is not None and de1.is_ready \
                and de1.feature_flag.rinse_control:
            send_val = value
            if send_val is None:
                send_val = 0
            # TODO: Can this be simplified/clarified?
            await de1.write_one_mmr0x80(MMR0x80LowAddr.FLUSH_TIMEOUT, send_val)
            ready_event = await de1.read_one_mmr0x80(MMR0x80LowAddr.FLUSH_TIMEOUT)
            await ready_event.wait()
            new_val = de1._mmr_dict[
                MMR0x80LowAddr.FLUSH_TIMEOUT].data_decoded
            if new_val != send_val:
                logger.error(
                    f"Wrote flush, stop-at-time {send_val} "
                    f"but got back {new_val}")

    async def on_de1_nearly_ready(self):
        """
        Update based on what the DE1's MMR says and if locally set
        prior to connection.

        This conceivably could be handled with a callback on the MMR read
        but visions of infinite loops are dancing in my head.
        Going simple, if not completely robust, to start
        """
        de1 = FlowSequencer().de1
        if de1 is not None and de1.feature_flag.rinse_control:
            de1_val = de1._mmr_dict[
                MMR0x80LowAddr.FLUSH_TIMEOUT].data_decoded
            # 0 can mean "unimplemented MMR" or 0 or "ignore"
            # as feature_flag.rinse_control is true, take it as "ignore"
            if de1_val == 0:
                de1_val = None
            # If locally set
            if self._stop_at_time_api_set and de1_val != self._stop_at_time:
                # Override the DE1 setting
                await self.stop_at_time_set_async(self._stop_at_time)
            else:
                # Accept what the DE1 says
                # Don't use the setter as it already is in the DE1
                self._stop_at_time = de1_val
                self._stop_at_time_api_set = False

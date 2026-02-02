from dataclasses import dataclass
from fastmcp import FastMCP
import asyncio
import anyio
import wwise_python_lib as WwisePythonLibrary
import inspect
import ast
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)

def get_log_dir() -> Path:
    if getattr(sys, "frozen", False):  # running as bundled exe
        return Path(sys.executable).resolve().parent
    else:
        return Path(__file__).resolve().parent # running from source

def configure_logger(): 
    log_path = get_log_dir() / "WwiseMCP.log"   # log path 

    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s",
        handlers=[handler],
    )

def create_asyncio_loop(): # needed when connecting to waapi client
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop

def connect_to_wwise() -> None:
    loop = create_asyncio_loop()
    try: 
        WwisePythonLibrary.connect_to_waapi()
    except Exception: 
        logger.exception("Failed to connect to Wwise Client.")
        raise 
    finally:
        loop.close()

def resolve_all_path_relationships_in(parent_path: str) -> list[dict]: 
    if not parent_path: 
        raise ValueError("Please provide a non empty parent path to resolve descendant paths in.")
    
    try:
        nodes = WwisePythonLibrary.fetch_nodes(parent_path)

        result : list[dict] = []
        for node in nodes:
            result.append(WwisePythonLibrary.get_fields_from_objects([node["id"]], ["path"]))
        
        return result 
    
    except Exception: 
        logger.exception("Resolve failed for %r", parent_path)
        raise 

def create_child_objects(
    child_names: list[str],
    child_types: list[str],
    parent_paths: list[str], 
    *, 
    prev_response_objects: list[any] | None = None
) -> list[dict]:
    
    objects : list[dict] = prev_response_objects 
    if not objects: 
        objects = [WwisePythonLibrary.get_object_at_path(parent_path) for parent_path in parent_paths]
    
    if not objects: 
        raise ValueError("Both prev_response_objects and parent_paths are empty. Please specify values for at least one of these variables.")

    try:
        try:
            parent_ids = [p["id"] for p in objects]
        except (KeyError, TypeError) as e:
            raise ValueError("One or more parent objects are missing an 'id' field.") from e

        result : list[dict] = []
        for parent_id, child_name, child_type in zip(parent_ids, child_names, child_types):
            result.extend(WwisePythonLibrary.create_object(parent_id, child_name, child_type))

        return result
    
    except Exception: 
        logger.exception("Failed to create objects.")
        raise 
    
def create_events(
    source_paths: list[str], 
    dst_parent_paths: list[str], 
    event_types: list[str], 
    event_names: list[str]
) -> list[dict]: 
    
    if not (len(dst_parent_paths) == len(event_types) == len(event_names) == len(source_paths)):
        raise ValueError(f"All input lists must have the same length when creating events.")
    
    try:         
        results: list[dict] = []

        for src, dst, etype, name in zip(source_paths, dst_parent_paths, event_types, event_names):
            result = WwisePythonLibrary.create_event(src,dst,etype,name)
            results.append(result)

        return results
    
    except Exception: 
        logger.exception("Failed to create events.")
        raise 

def create_game_objects(
    game_obj_names: list[str], 
    positions: list[tuple[float,float,float]]
) -> list[dict]: 
    
    try: 
        zipped = zip(game_obj_names, positions, strict=True)
        results: list[dict] = []

        for game_obj_name, position in zipped:
            result = WwisePythonLibrary.create_game_obj(game_obj_name, position)
            results.append(result)

        return results
    
    except Exception: 
        logger.exception("Failed to create game objects.")
        raise 

def create_rtpcs(
    rtpc_names : list[str], 
    parent_paths : list[str], 
    min_value : list[float], 
    max_value : list[float]
) -> list[dict]:
    
    try: 
        zipped = zip(rtpc_names, parent_paths, min_value, max_value, strict= True)
        results : list[dict] = []

        for rtpc_name, parent_path, min_value, max_value in zipped:
            if min_value > max_value:
                logger.exception("Invalid rtpc ranges for %r ", rtpc_name) 
                raise ValueError(f"Invalid rtpc ranges for {rtpc_name}")
            
            results.append(WwisePythonLibrary.create_rtpc(rtpc_name, parent_path, min_value, max_value))
        
        return results
    
    except Exception: 
        logger.exception("Failed to create rtpcs.")
        raise

def create_switch_groups(
    names: list[str], 
    parent_paths: list[str]
) -> list[dict]:
    
    try: 
        return create_switch_or_state_types(names, parent_paths, "SwitchGroup")
    
    except Exception: 
        logger.exception("Failed to create switch groups.")
        raise
    
def create_switches(
    names: list[str], 
    parent_paths: list[str]
)->list[dict]:
    
    try: 
       return create_switch_or_state_types(names, parent_paths, "Switch")
    
    except Exception: 
        logger.exception("Failed to create switches.")
        raise

def create_state_groups(
    names: list[str], 
    parent_paths: list[str]
)->list[dict]:
    
    try: 
        return create_switch_or_state_types(names, parent_paths, "StateGroup")
    
    except Exception: 
        logger.exception("Failed to create state groups.")
        raise

def create_states(
    names: list[str], 
    parent_paths: list[str]
)->list[dict]:
    
    try: 
        return create_switch_or_state_types(names, parent_paths, "State")
    
    except Exception: 
        logger.exception("Failed to create states.")
        raise

def create_switch_or_state_types(
    names: list[str], 
    parent_paths: list[str], 
    type: str
)->list[dict]:
    
    try: 
        if not (len(parent_paths) == len(names)):
            raise ValueError(f"Length mismatch: names={len(names)} parent_paths={len(parent_paths)}") 
        
        results : list[dict] = []
        
        for name, parent in zip(names, parent_paths):
            results.append(WwisePythonLibrary.create_switch_or_state_types(name,parent, type))

        return results
    
    except Exception: 
        logger.exception("Failed to create switch or state types.")
        raise
    
def move_object_by_path(
    source_path: str, 
    destination_parent_path: str
) -> dict: 
    
    if not source_path: 
        raise ValueError("Pass in a non empty source_path for 'move_object_by_path'.")
    
    if not destination_parent_path: 
        raise ValueError("Pass in a non empty destination_parent_path for 'move_object_by_path'.")

    try: 
        return WwisePythonLibrary.move_object_by_path(source_path, destination_parent_path)
    
    except Exception: 
        logger.exception("Failed to move object from %r to %r", source_path, destination_parent_path)
        raise

def rename_objects(
    paths_of_objects_to_rename: list[str] | None, 
    prev_response_objects: list[any] | None, 
    names: list[str]
) -> list[str]:
        
    try:
        if not names: 
            raise ValueError("Pass a non empty list of names for renaming")
        
        objects : list[dict] = []
        if paths_of_objects_to_rename is not None : 
            objects = [WwisePythonLibrary.get_object_at_path(obj_path) for obj_path in paths_of_objects_to_rename]
        else: 
            objects = prev_response_objects

        if not objects:
            raise ValueError("Pass in either the paths of the objects to be renamed or include the 'prev_response_objects='$last''to use results from a previous function call") 
        
        objects = [o for o in objects if o] 
        if not objects:
            raise ValueError("No valid objects resolved to rename.")

        if len(objects) != len(names):
            raise ValueError(
            f"Length mismatch: objects={len(objects)} names={len(names)}"
            )

        return WwisePythonLibrary.rename_objects(objects, names)

    except Exception: 
        logger.exception("Failed to rename objects.")
        raise

def import_audio(
    source_paths: list[str],
    destination_paths: list[str],
) ->list[dict]:
    try:
        if not source_paths: 
            raise ValueError("Specify source_files to import.")
        if not destination_paths:
            raise ValueError ("Specify destination_paths to import audio into")

        return WwisePythonLibrary.import_audio_files(source_paths, destination_paths)
    
    except Exception: 
        logger.exception("Failed to import audio.")
        raise

def list_all_event_names():
    try: 
        return WwisePythonLibrary.list_all_event_names() 
    except Exception: 
        logger.exception("Failed to retrieve event names in wwise project.")
        raise

def list_all_rtpc_names():
    try: 
        return WwisePythonLibrary.list_all_rtpc_names() 
    except Exception: 
        logger.exception("Failed to retrieve rtpc names in wwise project.")
        raise

def list_all_switchgroups_and_switches():
    try: 
        return WwisePythonLibrary.get_all_switchgroups_and_switches_grouped() 
    except Exception: 
        logger.exception("Failed to retrieve switch groups and switches in wwise project.")
        raise

def list_all_stategroups_and_states():
    try: 
        return WwisePythonLibrary.get_all_stategroups_and_states_grouped() 
    except Exception: 
        logger.exception("Failed to retrieve state groups and states in wwise project.")
        raise

def list_all_game_objects(): 
    try:
        return WwisePythonLibrary.get_all_game_objs_in_wwise_session()
    except Exception: 
        logger.exception("Failed to retrieve game objects in wwise project.")
        raise
    
def post_event(
    event_name: str, 
    go_name: str, 
    delay_ms: int
)-> int:
    
    try: 
        if not event_name: 
           raise ValueError("Pass in a non empty event name when posting an event.")
       
        if delay_ms < 0:
            raise ValueError("Delay amount cannot be negative when posting an event.") 

        return WwisePythonLibrary.post_event(event_name, go_name, delay_ms)
    
    except Exception: 
        logger.exception("Failed to post event %r", event_name)
        raise

def set_rtpc(
    game_object_name: str | None, 
    rtpc_name: str, 
    start: float, 
    end: float, 
    duration: int
) -> None:
    
    try: 
        if not rtpc_name: 
            raise ValueError("Please indicate the rtpc name to set.")
        
        if duration < 0:
            raise ValueError("Please indicate a non negative duration for the rtpc interpolation.")
        
        if not game_object_name: 
            WwisePythonLibrary.ramp_rtpc(rtpc_name, start, end, duration)
        else:
            WwisePythonLibrary.ramp_rtpc(rtpc_name, start, end, duration, obj = game_object_name, step_ms=50)
    
    except Exception: 
        logger.exception("Failed to set rtpc %r", rtpc_name)
        raise
    
def set_state(
    state_group: str, 
    state: str, 
    delay_ms: int
)-> None:
    
    if not state: 
        raise ValueError("Pass in a non empty state value when setting state.")
    
    if not state_group: 
        raise ValueError("Pass in a non empty state group when setting state.")
    
    if not isinstance(delay_ms, int) or delay_ms < 0: 
        raise ValueError("Ensure that delay_ms is an integer and non-negative when setting state.")
    
    try: 
        WwisePythonLibrary.set_state(state_group, state, delay_ms)
    
    except Exception: 
        logger.exception("Failed to set state %r in state group %r", state, state_group)
        raise

def set_switch(
    game_object_name: str, 
    switch_group: str, 
    switch: str, 
    delay_ms: int
)-> None:
    
    if not switch_group: 
        raise ValueError("Pass in a non empty switch group when setting switch.")
    
    if not switch: 
        raise ValueError("Pass in a non empty switch when setting switch.")
    
    if not isinstance(delay_ms, int) or delay_ms < 0: 
        raise ValueError("Ensure that delay_ms is an integer and non-negative when setting switch.")

    try:
        if not game_object_name: 
            WwisePythonLibrary.set_switch(switch_group, switch, delay_ms)
        else : 
            WwisePythonLibrary.set_switch(switch_group, switch, delay_ms, obj = game_object_name)
    
    except Exception: 
        logger.exception("Failed to set switch %r", switch)
        raise

def move_game_obj(
    game_obj_name: str, 
    start_pos: tuple[float, float, float], 
    end_pos: tuple[float, float, float], 
    duration_ms: int, 
    delay_ms: int
)-> None:
    
    if not game_obj_name: 
        raise ValueError("Pass in a non empty game object name to move.")
    
    if not isinstance(duration_ms, int) or duration_ms < 0: 
        raise ValueError("Ensure that duration_ms is an integer and non-negative when moving game obj.")
    
    if not isinstance(delay_ms, int) or delay_ms < 0: 
        raise ValueError("Ensure that delay_ms is an integer and non-negative when moving game obj.")
    
    try: 
        return WwisePythonLibrary.start_position_ramp(
            obj = game_obj_name,
            start_pos=start_pos, 
            end_pos=end_pos,
            duration_ms = duration_ms,
            step_ms = 100,
            delay_ms=delay_ms,
            front = (0.0, 1.0, 0.0),  
            top = (0.0, 0.0, 1.0),  
        )
    
    except Exception: 
        logger.exception("Failed to set switch.")
        raise

def stop_all_sounds() -> None:
    try: 
        WwisePythonLibrary.stop_all_sounds()
    
    except Exception: 
        logger.exception("Failed to stop all sounds in wwise.")
        raise
        
def include_in_soundbank(
    include_paths: list[str], 
    soundbank_path: str
) -> list[dict]: 
    
    if not include_paths: 
        raise ValueError("Pass in a non empty list of event paths to be included in the indicated soundbank.")

    for include_path in include_paths: 
        if not include_path: 
            raise ValueError("Ensure all elements inside the include_paths are non empty.")
    
    if not soundbank_path: 
        raise ValueError("Pass in a non empty soundbank path.")

    try: 
        return WwisePythonLibrary.include_in_soundbank(include_paths, soundbank_path)
    except Exception: 
        logger.exception("Failed to include %r paths in soundbank %r", len(include_paths), soundbank_path)
        raise

def generate_soundbanks(
    soundbank_names: list[str], 
    platforms: list[str], 
    languages: list[str]
) -> dict:
    
    if not soundbank_names:
        raise ValueError("Pass in a non empty list of soundbank names to generate.")
    
    for soundbank_name in soundbank_names: 
        if not soundbank_name: 
            raise ValueError("Ensure all soundbank names in the soundbank names list are non empty and valid.")

    if not platforms: 
        raise ValueError("Ensure the platform lists is not empty to generate soundbanks. Include at least one platform.")
    
    for platform in platforms: 
        if not platform: 
            raise ValueError("Ensure all platforms in the platform list are non empty and valid.")

    try: 
        return WwisePythonLibrary.generate_soundbanks(soundbank_names, platforms, languages)
    except Exception: 
        logger.exception("Failed to generate soundbanks.")
        raise

def get_project_info()->dict: 
    try: 
        return WwisePythonLibrary.get_project_info()
    except Exception: 
        logger.exception("Failed to get project info for wwise project.")
        raise

def list_all_audio_files_at_path_on_file_explorer(root_path:str)->list[str]:
    if not root_path: 
        raise ValueError("Pass in a non empty root path in file explorer to retrieve audio files from.")
    
    try: 
        return WwisePythonLibrary.list_audio_files_at_path_file_explorer(root_path)
    except Exception: 
        logger.exception("Failed to retrieve audio at root path %r", root_path)
        raise

def set_object_reference( 
    object_path: str, 
    reference_type: str, 
    reference_path: str
) -> None:
    
    if not object_path or not reference_type: 
        raise ValueError("Ensure object path and reference name fields are not empty when setting object reference.")

    if reference_path is None:
        raise ValueError("Value cannot be None.")

    if isinstance(reference_path, str) and not reference_path:
        raise ValueError("String values cannot be empty.")

    try:
        WwisePythonLibrary.set_reference(object_path, reference_type, reference_path)
    except Exception: 
        logger.exception("Failed to set object reference.")
        raise

def set_object_property( 
    object_path: str, 
    property_name: str, 
    value: int|bool|str
) -> None:
    
    if not object_path or not property_name: 
        raise ValueError("Ensure object path and property name fields are not empty when setting object properties.")

    if value is None:
        raise ValueError("Value cannot be None.")

    if isinstance(value, str) and not value:
        raise ValueError("String values cannot be empty.")

    try:
        WwisePythonLibrary.set_property(object_path, property_name, value)
    except Exception: 
        logger.exception("Failed to set object property.")
        raise
    
def get_selected_objects() -> list[dict]:
    try: 
        selected_objects = WwisePythonLibrary.get_selected_objects()
        if not selected_objects:
            raise ValueError("No selection detected")
        return selected_objects
    except Exception: 
        logger.exception("Failed to retrieve selected objects in wwise.")
        raise

def unregister_game_object(name: str) -> None:
    if not name: 
        raise ValueError("Pass in a non empty name to indicate the game object that you want unregistered.")
    
    try: 
        WwisePythonLibrary.unregister_game_obj(name)
    except Exception: 
        logger.exception("Failed to unregister object %r", name)
        raise

def toggle_layout(requested_layout: str) -> None:
    if not requested_layout: 
        raise ValueError("Ensure requested layout is non empty.")

    try: 
        WwisePythonLibrary.toggle_layout(requested_layout)
    except Exception: 
        logger.exception("Failed to toggle to layout %r", requested_layout)
        raise

def get_all_property_name_valid_values() -> str:
    try:
        return WwisePythonLibrary.get_all_property_name_valid_values() 
    except Exception: 
        logger.exception("Failed to get all property names and associated valid value ranges.")
        raise

# ---- Additional WAAPI command wrappers (pass-through to WwisePythonLibrary) ----
def _wrap(name: str):
    def f(*a, **k):
        try:
            return getattr(WwisePythonLibrary, name)(*a, **k)
        except Exception:
            logger.exception("Failed: %s", name)
            raise
    return f

# Soundengine
soundengine_get_state = _wrap("soundengine_get_state")
soundengine_get_switch = _wrap("soundengine_get_switch")
soundengine_load_bank = _wrap("soundengine_load_bank")
soundengine_post_msg_monitor = _wrap("soundengine_post_msg_monitor")
soundengine_post_trigger = _wrap("soundengine_post_trigger")
soundengine_reset_rtpc_value = _wrap("soundengine_reset_rtpc_value")
soundengine_seek_on_event = _wrap("soundengine_seek_on_event")
soundengine_set_game_object_aux_send_values = _wrap("soundengine_set_game_object_aux_send_values")
soundengine_set_game_object_output_bus_volume = _wrap("soundengine_set_game_object_output_bus_volume")
soundengine_set_listener_spatialization = _wrap("soundengine_set_listener_spatialization")
soundengine_set_multiple_positions = _wrap("soundengine_set_multiple_positions")
soundengine_set_object_obstruction_and_occlusion = _wrap("soundengine_set_object_obstruction_and_occlusion")
soundengine_set_scaling_factor = _wrap("soundengine_set_scaling_factor")
soundengine_stop_playing_id = _wrap("soundengine_stop_playing_id")
soundengine_unload_bank = _wrap("soundengine_unload_bank")
# Console project
console_project_close = _wrap("console_project_close")
console_project_create = _wrap("console_project_create")
console_project_open = _wrap("console_project_open")
# Core
get_info = _wrap("get_info")
core_ping = _wrap("core_ping")
# Audio
audio_convert = _wrap("audio_convert")
audio_import_tab_delimited = _wrap("audio_import_tab_delimited")
audio_mute = _wrap("audio_mute")
audio_reset_mute = _wrap("audio_reset_mute")
audio_reset_solo = _wrap("audio_reset_solo")
audio_set_conversion_plugin = _wrap("audio_set_conversion_plugin")
audio_solo = _wrap("audio_solo")
audio_source_peaks_get_min_max_peaks_in_region = _wrap("audio_source_peaks_get_min_max_peaks_in_region")
audio_source_peaks_get_min_max_peaks_in_trimmed_region = _wrap("audio_source_peaks_get_min_max_peaks_in_trimmed_region")
# BlendContainer
blend_container_add_assignment = _wrap("blend_container_add_assignment")
blend_container_add_track = _wrap("blend_container_add_track")
blend_container_get_assignments = _wrap("blend_container_get_assignments")
blend_container_remove_assignment = _wrap("blend_container_remove_assignment")
# SwitchContainer
switch_container_add_assignment = _wrap("switch_container_add_assignment")
switch_container_get_assignments = _wrap("switch_container_get_assignments")
switch_container_remove_assignment = _wrap("switch_container_remove_assignment")
# Core executeLua, log, mediaPool
execute_lua_script = _wrap("execute_lua_script")
log_add_item = _wrap("log_add_item")
log_clear = _wrap("log_clear")
log_get = _wrap("log_get")
media_pool_get = _wrap("media_pool_get")
media_pool_get_fields = _wrap("media_pool_get_fields")
# Object
object_copy = _wrap("object_copy")
object_delete = _wrap("object_delete")
object_diff = _wrap("object_diff")
object_get_attenuation_curve = _wrap("object_get_attenuation_curve")
object_get_property_and_reference_names = _wrap("object_get_property_and_reference_names")
object_get_property_info = _wrap("object_get_property_info")
object_get_property_names = _wrap("object_get_property_names")
object_get_types = _wrap("object_get_types")
object_is_linked = _wrap("object_is_linked")
object_is_property_enabled = _wrap("object_is_property_enabled")
object_paste_properties = _wrap("object_paste_properties")
object_set = _wrap("object_set")
object_set_attenuation_curve = _wrap("object_set_attenuation_curve")
object_set_linked = _wrap("object_set_linked")
object_set_notes = _wrap("object_set_notes")
object_set_randomizer = _wrap("object_set_randomizer")
object_set_state_groups = _wrap("object_set_state_groups")
object_set_state_properties = _wrap("object_set_state_properties")
# Plugin
plugin_get_list = _wrap("plugin_get_list")
plugin_get_properties = _wrap("plugin_get_properties")
plugin_get_property = _wrap("plugin_get_property")
# Profiler
profiler_enable_profiler_data = _wrap("profiler_enable_profiler_data")
profiler_get_audio_objects = _wrap("profiler_get_audio_objects")
profiler_get_busses = _wrap("profiler_get_busses")
profiler_get_cpu_usage = _wrap("profiler_get_cpu_usage")
profiler_get_cursor_time = _wrap("profiler_get_cursor_time")
profiler_get_loaded_media = _wrap("profiler_get_loaded_media")
profiler_get_meters = _wrap("profiler_get_meters")
profiler_get_performance_monitor = _wrap("profiler_get_performance_monitor")
profiler_get_rtpcs = _wrap("profiler_get_rtpcs")
profiler_get_streamed_media = _wrap("profiler_get_streamed_media")
profiler_get_voice_contributions = _wrap("profiler_get_voice_contributions")
profiler_get_voices = _wrap("profiler_get_voices")
profiler_register_meter = _wrap("profiler_register_meter")
profiler_save_capture = _wrap("profiler_save_capture")
profiler_start_capture = _wrap("profiler_start_capture")
profiler_stop_capture = _wrap("profiler_stop_capture")
profiler_unregister_meter = _wrap("profiler_unregister_meter")
# Project, remote, sound
project_save = _wrap("project_save")
remote_connect = _wrap("remote_connect")
remote_disconnect = _wrap("remote_disconnect")
remote_get_available_consoles = _wrap("remote_get_available_consoles")
remote_get_connection_status = _wrap("remote_get_connection_status")
sound_set_active_source = _wrap("sound_set_active_source")
# Soundbank
soundbank_get_inclusions = _wrap("soundbank_get_inclusions")
soundbank_process_definition_files = _wrap("soundbank_process_definition_files")
soundbank_convert_external_sources = _wrap("soundbank_convert_external_sources")
# SourceControl
source_control_add = _wrap("source_control_add")
source_control_check_out = _wrap("source_control_check_out")
source_control_commit = _wrap("source_control_commit")
source_control_delete = _wrap("source_control_delete")
source_control_get_source_files = _wrap("source_control_get_source_files")
source_control_get_status = _wrap("source_control_get_status")
source_control_move = _wrap("source_control_move")
source_control_revert = _wrap("source_control_revert")
source_control_set_provider = _wrap("source_control_set_provider")
# Transport
transport_create = _wrap("transport_create")
transport_destroy = _wrap("transport_destroy")
transport_execute_action = _wrap("transport_execute_action")
transport_get_list = _wrap("transport_get_list")
transport_get_state = _wrap("transport_get_state")
transport_prepare = _wrap("transport_prepare")
# Undo
undo_begin_group = _wrap("undo_begin_group")
undo_cancel_group = _wrap("undo_cancel_group")
undo_end_group = _wrap("undo_end_group")
undo_redo = _wrap("undo_redo")
undo_undo = _wrap("undo_undo")
# WorkUnit
work_unit_load = _wrap("work_unit_load")
work_unit_unload = _wrap("work_unit_unload")
# Debug
debug_enable_asserts = _wrap("debug_enable_asserts")
debug_enable_automation_mode = _wrap("debug_enable_automation_mode")
debug_generate_tone_wav = _wrap("debug_generate_tone_wav")
debug_get_wal_tree = _wrap("debug_get_wal_tree")
debug_restart_waapi_servers = _wrap("debug_restart_waapi_servers")
debug_test_assert = _wrap("debug_test_assert")
debug_test_crash = _wrap("debug_test_crash")
debug_validate_call = _wrap("debug_validate_call")
# UI
ui_bring_to_foreground = _wrap("ui_bring_to_foreground")
ui_capture_screen = _wrap("ui_capture_screen")
ui_commands_execute = _wrap("ui_commands_execute")
ui_commands_get_commands = _wrap("ui_commands_get_commands")
ui_commands_register = _wrap("ui_commands_register")
ui_commands_unregister = _wrap("ui_commands_unregister")
ui_get_selected_files = _wrap("ui_get_selected_files")
ui_layout_close_view = _wrap("ui_layout_close_view")
ui_layout_dock_view = _wrap("ui_layout_dock_view")
ui_layout_get_current_layout_name = _wrap("ui_layout_get_current_layout_name")
ui_layout_get_element_rectangle = _wrap("ui_layout_get_element_rectangle")
ui_layout_get_layout = _wrap("ui_layout_get_layout")
ui_layout_get_layout_names = _wrap("ui_layout_get_layout_names")
ui_layout_get_or_create_view = _wrap("ui_layout_get_or_create_view")
ui_layout_get_view_instances = _wrap("ui_layout_get_view_instances")
ui_layout_get_view_types = _wrap("ui_layout_get_view_types")
ui_layout_move_splitter = _wrap("ui_layout_move_splitter")
ui_layout_remove_layout = _wrap("ui_layout_remove_layout")
ui_layout_reset_layouts = _wrap("ui_layout_reset_layouts")
ui_layout_set_layout = _wrap("ui_layout_set_layout")
ui_layout_undock_view = _wrap("ui_layout_undock_view")
ui_project_close = _wrap("ui_project_close")
ui_project_create = _wrap("ui_project_create")
ui_project_open = _wrap("ui_project_open")
# Waapi
waapi_get_functions = _wrap("waapi_get_functions")
waapi_get_schema = _wrap("waapi_get_schema")
waapi_schema_get_args_spec = _wrap("waapi_schema_get_args_spec")
waapi_validate_args = _wrap("waapi_validate_args")
waapi_get_topics = _wrap("waapi_get_topics")
waapi_subscribe = _wrap("waapi_subscribe")
waapi_unsubscribe = _wrap("waapi_unsubscribe")
waapi_subscription_events = _wrap("waapi_subscription_events")
waapi_list_topic_uris = _wrap("waapi_list_topic_uris")
subscribe_topic_audio_imported = _wrap("subscribe_topic_audio_imported")
subscribe_topic_log_item_added = _wrap("subscribe_topic_log_item_added")
subscribe_topic_object_attenuation_curve_changed = _wrap("subscribe_topic_object_attenuation_curve_changed")
subscribe_topic_object_attenuation_curve_link_changed = _wrap("subscribe_topic_object_attenuation_curve_link_changed")
subscribe_topic_object_child_added = _wrap("subscribe_topic_object_child_added")
subscribe_topic_object_child_removed = _wrap("subscribe_topic_object_child_removed")
subscribe_topic_object_created = _wrap("subscribe_topic_object_created")
subscribe_topic_object_curve_changed = _wrap("subscribe_topic_object_curve_changed")
subscribe_topic_object_name_changed = _wrap("subscribe_topic_object_name_changed")
subscribe_topic_object_notes_changed = _wrap("subscribe_topic_object_notes_changed")
subscribe_topic_object_post_deleted = _wrap("subscribe_topic_object_post_deleted")
subscribe_topic_object_pre_deleted = _wrap("subscribe_topic_object_pre_deleted")
subscribe_topic_object_property_changed = _wrap("subscribe_topic_object_property_changed")
subscribe_topic_object_reference_changed = _wrap("subscribe_topic_object_reference_changed")
subscribe_topic_object_structure_changed = _wrap("subscribe_topic_object_structure_changed")
subscribe_topic_profiler_capture_log_item_added = _wrap("subscribe_topic_profiler_capture_log_item_added")
subscribe_topic_profiler_game_object_registered = _wrap("subscribe_topic_profiler_game_object_registered")
subscribe_topic_profiler_game_object_reset = _wrap("subscribe_topic_profiler_game_object_reset")
subscribe_topic_profiler_game_object_unregistered = _wrap("subscribe_topic_profiler_game_object_unregistered")
subscribe_topic_profiler_state_changed = _wrap("subscribe_topic_profiler_state_changed")
subscribe_topic_profiler_switch_changed = _wrap("subscribe_topic_profiler_switch_changed")
subscribe_topic_project_loaded = _wrap("subscribe_topic_project_loaded")
subscribe_topic_project_post_closed = _wrap("subscribe_topic_project_post_closed")
subscribe_topic_project_pre_closed = _wrap("subscribe_topic_project_pre_closed")
subscribe_topic_project_saved = _wrap("subscribe_topic_project_saved")
subscribe_topic_soundbank_generated = _wrap("subscribe_topic_soundbank_generated")
subscribe_topic_soundbank_generation_done = _wrap("subscribe_topic_soundbank_generation_done")
subscribe_topic_switch_container_assignment_added = _wrap("subscribe_topic_switch_container_assignment_added")
subscribe_topic_switch_container_assignment_removed = _wrap("subscribe_topic_switch_container_assignment_removed")
subscribe_topic_transport_state_changed = _wrap("subscribe_topic_transport_state_changed")
subscribe_topic_debug_assert_failed = _wrap("subscribe_topic_debug_assert_failed")
subscribe_topic_ui_commands_executed = _wrap("subscribe_topic_ui_commands_executed")
subscribe_topic_ui_selection_changed = _wrap("subscribe_topic_ui_selection_changed")

#==============================================================================
#                            Function Dictionary
#==============================================================================

@dataclass
class Command:
    func: callable
    doc: str

COMMANDS: dict[str, Command] = {
    "connect_to_wwise" : Command(
        func=connect_to_wwise,
        doc="Attempts to reconnect to the currently active wwise session."
            "Args: None"
    ),
    "resolve_all_path_relationships_in" : Command(
        func=resolve_all_path_relationships_in,
        doc="Returns a path-first index for the subtree rooted at `parent_path`."
            "Args: parent_path. Returns a list[dict]"
    ),
    "create_objects" : Command(
        func=create_child_objects,
        doc="Create child objects given names and types of objects and the parent path, if no parent path(s) specified, function will use prev_response_objects as parents."
            "Args: child_names : list[str], child_types: list[str], parent_paths : list[str] eg. ['\\Actor-Mixer Hierarchy\\Default Work Unit', ...], prev_response_objects='$last' if previous function needs to pass returned values into this function."
            "Object types : ActorMixer, Bus, AuxBus, RandomSequenceContainer, SwitchContainer, BlendContainer, Sound, WorkUnit, SoundBank, Folder, Attenuation."
    ), 
    "create_events" : Command(
        func=create_events,
        doc="Create multiple Wwise events in one batch."
            "Args: source_paths (list[str]), dst_parent_paths (list[str]), event_types (list[str]), event_names (list[str]). All four lists must have the same length. Returns: list[dict]"
    ),
    "create_game_objects" : Command(
        func=create_game_objects,
        doc="Create game objects in one batch."
            "Args : game_obj_names : list[str], positions : list[tuple[float,float,float]]. Returns None."
    ),
    "create_rtpcs": Command(
        func=create_rtpcs,
        doc="Creates rtpcs in one batch."
            "Args: rtpc_names : list[str], parent_paths : list[str], min_value : list[float], max_value : list[float]source_paths (list[str]), dst_parent_paths (list[str]), event_types (list[str]), event_names (list[str]). All four lists must have the same length. " \
            "Returns: list[dict]. parent path should always start with '\\Game Parameters'. If user does not specify min_values or max_values use 0.0 for min and 100.0 for max."
    ),
    "create_switch_groups" : Command(
        func=create_switch_groups,
        doc="Creates a list of switch gorups"
            "Args: names: list[str], parent_paths : list[str]:" 
            "Returns: list[dict]. A parent path should always start with either '\\Switches'."
            "Note that if you are creating a new SwitchGroup, the Group must always be created first before its Children."
    ),
    "create_switches" : Command(
        func=create_switches,
        doc="Creates a list of switches"
            "Args: names: list[str], parent_paths : list[str]." 
            "Returns: list[dict]. The parent path should always start with either '\\Switches' and represents the SwitchGroup the given switch belongs to."
            "Note that if you are creating a new StateGroup, the Group must always be created first before its Children."
    ),
    "create_state_groups" : Command(
        func=create_state_groups,
        doc="Creates a list of state groups"
            "Args: names: list[str], parent_paths : list[str]:" 
            "Returns: list[dict]. A parent path should always start with either '\\States'."
            "Note that if you are creating a new Stateroup, the Group must always be created first before its Children."
    ),
    "create_states" : Command(
        func=create_states,
        doc="Creates a list of states"
            "Args: names: list[str], parent_paths : list[str]:" 
            "Returns: list[dict]. A parent path should always start with either '\\States'and represents the StateGroup the given state belongs to."
            "Note that if you are creating a new StateGroup, the Group must always be created first before its Children."
    ),
    "move_object_by_path" : Command(
        func=move_object_by_path,
        doc="Moves the object from the source path to the new destination parent path. All child objects will be moved along with the parent."
            "Args: source_path : str, destination_parent_path : str, Returns a dict"
    ), 
    "rename_objects" : Command(
        func=rename_objects, 
        doc ="Renames a list of objects either by passing in a list of the objects' paths or by include prev_response_objects='$last' if a previous function need to pass returned values into this function."
             "Args: paths_of_objects_to_rename : list[str] | None, prev_response_objects: list[dict] | None, names: list[str]. Returns list[str]"
    ), 
    "import_audio_files" : Command(
        func=import_audio, 
        doc="Imports every audio file via its absolute path into the desired Wwise object path (include the object to be imported into the path as well). Validate destination path exists first via resolve_all_path_relationships_in if uncertain."
            "Args: source_paths: list[str], destination_paths: list[str]. Returns list[dict]"
    ),
    "list_all_event_names" : Command(
        func=list_all_event_names, 
        doc="List all events names"
              "Args: None, Returns list[str]"
    ),
    "list_all_rtpc_names" : Command(
        func=list_all_rtpc_names, 
        doc="List all rtpc names in wwise project"
            "Args: None, Returns list[str]"
    ),
    "list_all_switchgroups_and_switches" : Command(
        func=list_all_switchgroups_and_switches, 
        doc="List all switches grouped by their parent switch groups in a dict eg. [SwitchGroupName: [SwitchName, ...]]"
            "Args: None, Returns list[str]"
    ),
    "list_all_stategroups_and_states" : Command(
        func=list_all_stategroups_and_states, 
        doc="List all states grouped by their parent state groups in a dict eg. [StateGroupName: [StateName, ...]]"
            "Args: None, Returns dict[str, list[str]]"
    ),
    "list_all_game_objects_in_wwise" : Command(
        func=list_all_game_objects, 
        doc="List all game objects present in the wwise session."
            "Args: None, Returns list[dict]"
    ),
    "post_event" : Command(
        func=post_event, 
        doc="Posts the event by its name on the game object specified by its name after a delay in milliseconds"
            "If no game object is specified, the event will be posted on the 'Global' game object which should be used for 2D sounds like Ambiences."
            "If the specified game object does not exist, it will be created automatically at time of call."
            "If user does not specify delay_ms, assume post immediately so set delay_ms = 0."
            "Types of events : Play, Stop, Pause, Break, Seek"
            "Args: event_name: str, game_obj_name : str, delay_ms : int. Returns None"
    ),
    "set_rtpc" : Command(
        func=set_rtpc, 
        doc="Sets an RTPC on the specified game object using the given object name and RTPC parameter name. You can define start and end values over a duration (in milliseconds)." 
            "If no game object is specified, the RTPC is applied to the global game object 'Global'."
            "Args : game_object_name : str, rtpc_name : str, start : float, end : float, duration : int (milliseconds) , Returns None"
    ), 
    "set_state" : Command(
        func=set_state, 
        doc="Sets the state by the state group name it belongs to and the name of the state itself"
            "Args : state_group : str, state : str, delay_ms : int, Returns None"
    ), 
    "set_switch" : Command(
        func=set_switch, 
        doc="Sets the switch by the switch group name it belongs to and the name of the switch itself"
            "Args : game_obj_name : str, switch_group: str, switch : str, delay_ms : int, Returns None"
    ),
    "move_game_obj" : Command(
        func=move_game_obj, 
        doc="Moves the game object by its name from its start position to the desired end position over a duration (ms). A delay (ms) can be set to schedule the start of the movement ramp." 
            "If no game object with the specified name exist, one will be created."
            "Args : game_obj_name : str, start_pos : tuple(float, float, float), end_pos : tuple(float, float, float), duation_ms : int (ms), delay_ms : int(ms). Returns None"
    ),
    "stop_all_sounds" : Command(
        func=stop_all_sounds, 
        doc="Stops all sounds on all game objects created in the captured session"
            "Args: None. Returns None."
    ), 
    "include_in_soundbank" : Command(
        func=include_in_soundbank, 
        doc="Includes the specified objects (i.e events, work units or folders) in the specifed soundbank by path"
            "Args: include_paths : list[str], soundbank_paths : list[str]. Returns list[dict]"
    ), 
    "generate_soundbanks" : Command(
        func=generate_soundbanks, 
        doc="Generates the soundbanks given a list of soundbanks names, a list of platforms and a list of languages."
            "If unsure of what platforms to include, use 'Windows' or call the function : get_project_info."
            "If unsure on what languages to include, use 'English(US) or call the function : get_project_info." 
            "Args: soundbank_names : list[str], platforms : list[str], languages : list[str], Returns None"
    ), 
    "get_project_info" : Command(
        func=get_project_info, 
        doc="Returns the wwise project metadata, useful for determining languages and platforms avaialble in the project"
            "Args: None. Returns a dict"
    ),
    "get_all_audio_files_at_path_on_file_explorer" : Command(
        func=list_all_audio_files_at_path_on_file_explorer, 
        doc="Returns the path to all audio files given the parent folder path on file explorer (eg. 'C:/Audio')"
            "Args: root_path : str. Returns a list[str]"
    ),
    "set_object_reference" : Command(
        func=set_object_reference,
        doc="Sets a Wwise object's reference (e.g. Attenuation, OutputBus) to a target object."
            "Args: object_path : str, reference_type : str, reference_path : str. Returns dict."
    ),
    "set_object_property" : Command(
        func=set_object_property,
        doc="Sets the property of the object to a new value given its path in wwise"
            "Args: object_path : str, property_name : str, value: int | bool | str. Returns dict."
    ),
    "retrieve_selected_objs" : Command(
        func=get_selected_objects, 
        doc ="Retrives the currently selected object(s) in wwise."
             "Args: none. Returns a list[dicts]"
    ),
    "unregister_gameobject" : Command(
        func=unregister_game_object, 
        doc ="Unregisters the game object by specifying its name"
             "Args: name : str. Returns None."
    ),
    "toggle_layout" : Command(
        func=toggle_layout, 
        doc ="Toggles current layout in wwise to the requested layout. "
             "Valid layout types : Designer, Profiler, Soundbank, Mixer, Audio Object Profiler, Voice Profiler, Game Object Profiler"
             "Args: requested_layout : str. Returns none."
    ),
    "get_all_property_name_and_valid_value_types" : Command(
        func=get_all_property_name_valid_values, 
        doc ="Return a newline-formatted help string listing the correct WAAPI property identifiers for the specified Wwise object type."
             "Args: None. Returns: str."
    ),
    # Additional WAAPI commands
    "soundengine_get_state": Command(func=soundengine_get_state, doc="Get current state of a State Group. Args: state_group."),
    "soundengine_get_switch": Command(func=soundengine_get_switch, doc="Get current switch for Game Object. Args: switch_group, game_object."),
    "soundengine_load_bank": Command(func=soundengine_load_bank, doc="Load SoundBank. Args: bank_id_or_path, **kwargs."),
    "soundengine_post_msg_monitor": Command(func=soundengine_post_msg_monitor, doc="Post message to Profiler. Args: message, **kwargs."),
    "soundengine_post_trigger": Command(func=soundengine_post_trigger, doc="Post trigger. Args: trigger_name, game_object, **kwargs."),
    "soundengine_reset_rtpc_value": Command(func=soundengine_reset_rtpc_value, doc="Reset RTPC to default. Args: rtpc_name, game_object=None."),
    "soundengine_seek_on_event": Command(func=soundengine_seek_on_event, doc="Seek on event. Args: event_name, game_object, position_ms, **kwargs."),
    "soundengine_set_game_object_aux_send_values": Command(func=soundengine_set_game_object_aux_send_values, doc="Set aux send values. Args: game_object, aux_send_values, **kwargs."),
    "soundengine_set_game_object_output_bus_volume": Command(func=soundengine_set_game_object_output_bus_volume, doc="Set output bus volume. Args: game_object, bus_id_or_path, volume, **kwargs."),
    "soundengine_set_listener_spatialization": Command(func=soundengine_set_listener_spatialization, doc="Set listener spatialization. Args: listener_id, channel_config, volume_offsets, spatialized, **kwargs."),
    "soundengine_set_multiple_positions": Command(func=soundengine_set_multiple_positions, doc="Set multiple positions. Args: game_object, positions, **kwargs."),
    "soundengine_set_object_obstruction_and_occlusion": Command(func=soundengine_set_object_obstruction_and_occlusion, doc="Set obstruction/occlusion. Args: game_object, obstruction, occlusion, **kwargs."),
    "soundengine_set_scaling_factor": Command(func=soundengine_set_scaling_factor, doc="Set attenuation scaling factor. Args: game_object, attenuation_scaling_factor."),
    "soundengine_stop_playing_id": Command(func=soundengine_stop_playing_id, doc="Stop playing ID. Args: playing_id."),
    "soundengine_unload_bank": Command(func=soundengine_unload_bank, doc="Unload SoundBank. Args: bank_id_or_path, **kwargs."),
    "console_project_close": Command(func=console_project_close, doc="Close current project."),
    "console_project_create": Command(func=console_project_create, doc="Create project. Args: path, platform, **kwargs."),
    "console_project_open": Command(func=console_project_open, doc="Open project. Args: path, **kwargs."),
    "get_info": Command(func=get_info, doc="Get global Wwise info. Returns dict."),
    "core_ping": Command(func=core_ping, doc="Verify WAAPI available."),
    "audio_convert": Command(func=audio_convert, doc="Convert audio. Args: **kwargs."),
    "audio_import_tab_delimited": Command(func=audio_import_tab_delimited, doc="Import tab-delimited. Args: import_file, **kwargs."),
    "audio_mute": Command(func=audio_mute, doc="Mute object. Args: object_path."),
    "audio_reset_mute": Command(func=audio_reset_mute, doc="Unmute all."),
    "audio_reset_solo": Command(func=audio_reset_solo, doc="Unsolo all."),
    "audio_set_conversion_plugin": Command(func=audio_set_conversion_plugin, doc="Set conversion plugin. Args: plugin_id, platform, conversion, **kwargs."),
    "audio_solo": Command(func=audio_solo, doc="Solo object. Args: object_path."),
    "audio_source_peaks_get_min_max_peaks_in_region": Command(func=audio_source_peaks_get_min_max_peaks_in_region, doc="Get peaks in region. Args: object_path, time_from, time_to, num_peaks=1, **kwargs."),
    "audio_source_peaks_get_min_max_peaks_in_trimmed_region": Command(func=audio_source_peaks_get_min_max_peaks_in_trimmed_region, doc="Get peaks in trimmed region. Args: object_path, num_peaks=1, **kwargs."),
    "blend_container_add_assignment": Command(func=blend_container_add_assignment, doc="Add blend assignment. Args: blend_container_path, blend_track_path, child_path, edges=None, index=None, **kwargs."),
    "blend_container_add_track": Command(func=blend_container_add_track, doc="Add blend track. Args: blend_container_path, name, **kwargs."),
    "blend_container_get_assignments": Command(func=blend_container_get_assignments, doc="Get blend assignments. Args: blend_container_path, blend_track_path=None, **kwargs."),
    "blend_container_remove_assignment": Command(func=blend_container_remove_assignment, doc="Remove blend assignment. Args: blend_container_path, child_path, **kwargs."),
    "switch_container_add_assignment": Command(func=switch_container_add_assignment, doc="Assign child to switch. Args: switch_container_path, child_path, state_path."),
    "switch_container_get_assignments": Command(func=switch_container_get_assignments, doc="Get switch container assignments. Args: switch_container_path."),
    "switch_container_remove_assignment": Command(func=switch_container_remove_assignment, doc="Remove switch assignment. Args: switch_container_path, child_path, state_path."),
    "execute_lua_script": Command(func=execute_lua_script, doc="Execute Lua. Args: lua_script=None, lua_string=None, **kwargs."),
    "log_add_item": Command(func=log_add_item, doc="Add log item. Args: channel, message, **kwargs."),
    "log_clear": Command(func=log_clear, doc="Clear log. Args: channel."),
    "log_get": Command(func=log_get, doc="Get log. Args: channel, **kwargs."),
    "media_pool_get": Command(func=media_pool_get, doc="Get Media Pool files. Args: **kwargs."),
    "media_pool_get_fields": Command(func=media_pool_get_fields, doc="Get Media Pool fields. Args: **kwargs."),
    "object_copy": Command(func=object_copy, doc="Copy object. Args: object_path, parent_path, **kwargs."),
    "object_delete": Command(func=object_delete, doc="Delete object. Args: object_path."),
    "object_diff": Command(func=object_diff, doc="Diff objects. Args: source_path, target_path, **kwargs."),
    "object_get_attenuation_curve": Command(func=object_get_attenuation_curve, doc="Get attenuation curve. Args: object_path, curve_type='Volume', **kwargs."),
    "object_get_property_and_reference_names": Command(func=object_get_property_and_reference_names, doc="Get property/reference names. Args: object_path, **kwargs."),
    "object_get_property_info": Command(func=object_get_property_info, doc="Get property info. Args: object_path, property_name, **kwargs."),
    "object_get_property_names": Command(func=object_get_property_names, doc="Get property names. Args: object_path, **kwargs."),
    "object_get_types": Command(func=object_get_types, doc="Get object types. Args: **kwargs."),
    "object_is_linked": Command(func=object_is_linked, doc="Check if linked. Args: object_path, property_name, platform='Windows', **kwargs."),
    "object_is_property_enabled": Command(func=object_is_property_enabled, doc="Check property enabled. Args: object_path, property_name, platform='Windows', **kwargs."),
    "object_paste_properties": Command(func=object_paste_properties, doc="Paste properties. Args: source_path, target_paths, **kwargs."),
    "object_set": Command(func=object_set, doc="Batch set object. Args: object_path, updates, **kwargs."),
    "object_set_attenuation_curve": Command(func=object_set_attenuation_curve, doc="Set attenuation curve. Args: object_path, curve_type, points, use=True, **kwargs."),
    "object_set_linked": Command(func=object_set_linked, doc="Set linked. Args: object_path, property_name, linked, platform='Windows', **kwargs."),
    "object_set_notes": Command(func=object_set_notes, doc="Set notes. Args: object_path, notes."),
    "object_set_randomizer": Command(func=object_set_randomizer, doc="Set randomizer. Args: object_path, property_name, enabled=None, min_val=None, max_val=None, platform=None, **kwargs."),
    "object_set_state_groups": Command(func=object_set_state_groups, doc="Set state groups. Args: object_path, state_groups."),
    "object_set_state_properties": Command(func=object_set_state_properties, doc="Set state properties. Args: object_path, state_properties, **kwargs."),
    "plugin_get_list": Command(func=plugin_get_list, doc="Get plugin list. Args: **kwargs."),
    "plugin_get_properties": Command(func=plugin_get_properties, doc="Get plugin properties. Args: plugin_id, **kwargs."),
    "plugin_get_property": Command(func=plugin_get_property, doc="Get plugin property. Args: plugin_id, property_name, **kwargs."),
    "profiler_enable_profiler_data": Command(func=profiler_enable_profiler_data, doc="Enable profiler data. Args: data_types, **kwargs."),
    "profiler_get_audio_objects": Command(func=profiler_get_audio_objects, doc="Get audio objects. Args: **kwargs."),
    "profiler_get_busses": Command(func=profiler_get_busses, doc="Get busses. Args: **kwargs."),
    "profiler_get_cpu_usage": Command(func=profiler_get_cpu_usage, doc="Get CPU usage. Args: **kwargs."),
    "profiler_get_cursor_time": Command(func=profiler_get_cursor_time, doc="Get cursor time. Args: **kwargs."),
    "profiler_get_loaded_media": Command(func=profiler_get_loaded_media, doc="Get loaded media. Args: **kwargs."),
    "profiler_get_meters": Command(func=profiler_get_meters, doc="Get meters. Args: **kwargs."),
    "profiler_get_performance_monitor": Command(func=profiler_get_performance_monitor, doc="Get performance monitor. Args: **kwargs."),
    "profiler_get_rtpcs": Command(func=profiler_get_rtpcs, doc="Get RTPCs. Args: **kwargs."),
    "profiler_get_streamed_media": Command(func=profiler_get_streamed_media, doc="Get streamed media. Args: **kwargs."),
    "profiler_get_voice_contributions": Command(func=profiler_get_voice_contributions, doc="Get voice contributions. Args: **kwargs."),
    "profiler_get_voices": Command(func=profiler_get_voices, doc="Get voices. Args: **kwargs."),
    "profiler_register_meter": Command(func=profiler_register_meter, doc="Register meter. Args: object_path, **kwargs."),
    "profiler_save_capture": Command(func=profiler_save_capture, doc="Save capture. Args: file_path, **kwargs."),
    "profiler_start_capture": Command(func=profiler_start_capture, doc="Start capture. Args: **kwargs."),
    "profiler_stop_capture": Command(func=profiler_stop_capture, doc="Stop capture. Args: **kwargs."),
    "profiler_unregister_meter": Command(func=profiler_unregister_meter, doc="Unregister meter. Args: object_path, **kwargs."),
    "project_save": Command(func=project_save, doc="Save project. Args: **kwargs."),
    "remote_connect": Command(func=remote_connect, doc="Connect to Sound Engine. Args: host, **kwargs."),
    "remote_disconnect": Command(func=remote_disconnect, doc="Disconnect. Args: **kwargs."),
    "remote_get_available_consoles": Command(func=remote_get_available_consoles, doc="Get available consoles. Args: **kwargs."),
    "remote_get_connection_status": Command(func=remote_get_connection_status, doc="Get connection status. Args: **kwargs."),
    "sound_set_active_source": Command(func=sound_set_active_source, doc="Set active source. Args: sound_path, source_id_or_path, **kwargs."),
    "soundbank_get_inclusions": Command(func=soundbank_get_inclusions, doc="Get soundbank inclusions. Args: soundbank_path, **kwargs."),
    "soundbank_process_definition_files": Command(func=soundbank_process_definition_files, doc="Process definition files. Args: files, **kwargs."),
    "soundbank_convert_external_sources": Command(func=soundbank_convert_external_sources, doc="Convert external sources. Args: **kwargs."),
    "source_control_add": Command(func=source_control_add, doc="Source control add. Args: files, **kwargs."),
    "source_control_check_out": Command(func=source_control_check_out, doc="Source control checkout. Args: files, **kwargs."),
    "source_control_commit": Command(func=source_control_commit, doc="Source control commit. Args: files, **kwargs."),
    "source_control_delete": Command(func=source_control_delete, doc="Source control delete. Args: files, **kwargs."),
    "source_control_get_source_files": Command(func=source_control_get_source_files, doc="Get source files. Args: **kwargs."),
    "source_control_get_status": Command(func=source_control_get_status, doc="Get source control status. Args: files, **kwargs."),
    "source_control_move": Command(func=source_control_move, doc="Source control move. Args: files, new_files, **kwargs."),
    "source_control_revert": Command(func=source_control_revert, doc="Source control revert. Args: files, **kwargs."),
    "source_control_set_provider": Command(func=source_control_set_provider, doc="Set source control provider. Args: provider, **kwargs."),
    "transport_create": Command(func=transport_create, doc="Create transport. Args: object_path, **kwargs."),
    "transport_destroy": Command(func=transport_destroy, doc="Destroy transport. Args: transport_id, **kwargs."),
    "transport_execute_action": Command(func=transport_execute_action, doc="Execute transport action. Args: action, transport_id=None, **kwargs."),
    "transport_get_list": Command(func=transport_get_list, doc="Get transport list. Args: **kwargs."),
    "transport_get_state": Command(func=transport_get_state, doc="Get transport state. Args: transport_id, **kwargs."),
    "transport_prepare": Command(func=transport_prepare, doc="Prepare for playback. Args: object_path, **kwargs."),
    "undo_begin_group": Command(func=undo_begin_group, doc="Begin undo group. Args: **kwargs."),
    "undo_cancel_group": Command(func=undo_cancel_group, doc="Cancel undo group. Args: **kwargs."),
    "undo_end_group": Command(func=undo_end_group, doc="End undo group. Args: **kwargs."),
    "undo_redo": Command(func=undo_redo, doc="Redo. Args: **kwargs."),
    "undo_undo": Command(func=undo_undo, doc="Undo. Args: **kwargs."),
    "work_unit_load": Command(func=work_unit_load, doc="Load work unit. Args: work_unit_path, **kwargs."),
    "work_unit_unload": Command(func=work_unit_unload, doc="Unload work unit. Args: work_unit_path, **kwargs."),
    "debug_enable_asserts": Command(func=debug_enable_asserts, doc="Enable asserts. Args: enabled."),
    "debug_enable_automation_mode": Command(func=debug_enable_automation_mode, doc="Enable automation mode. Args: enabled."),
    "debug_generate_tone_wav": Command(func=debug_generate_tone_wav, doc="Generate tone WAV. Args: file_path, **kwargs."),
    "debug_get_wal_tree": Command(func=debug_get_wal_tree, doc="Get WAL tree. Args: **kwargs."),
    "debug_restart_waapi_servers": Command(func=debug_restart_waapi_servers, doc="Restart WAAPI servers. Args: **kwargs."),
    "debug_test_assert": Command(func=debug_test_assert, doc="Test assert. Args: **kwargs."),
    "debug_test_crash": Command(func=debug_test_crash, doc="Test crash. Args: **kwargs."),
    "debug_validate_call": Command(func=debug_validate_call, doc="Validate WAAPI call. Args: uri, args=None, **kwargs."),
    "ui_bring_to_foreground": Command(func=ui_bring_to_foreground, doc="Bring window to foreground. Args: **kwargs."),
    "ui_capture_screen": Command(func=ui_capture_screen, doc="Capture screen. Args: **kwargs."),
    "ui_commands_execute": Command(func=ui_commands_execute, doc="Execute UI command. Args: command, **kwargs."),
    "ui_commands_get_commands": Command(func=ui_commands_get_commands, doc="Get commands. Args: **kwargs."),
    "ui_commands_register": Command(func=ui_commands_register, doc="Register commands. Args: commands, **kwargs."),
    "ui_commands_unregister": Command(func=ui_commands_unregister, doc="Unregister commands. Args: commands, **kwargs."),
    "ui_get_selected_files": Command(func=ui_get_selected_files, doc="Get selected files. Args: **kwargs."),
    "ui_layout_close_view": Command(func=ui_layout_close_view, doc="Close view. Args: view_id, **kwargs."),
    "ui_layout_dock_view": Command(func=ui_layout_dock_view, doc="Dock view. Args: view_id, target_id, side, name, **kwargs."),
    "ui_layout_get_current_layout_name": Command(func=ui_layout_get_current_layout_name, doc="Get current layout name. Args: **kwargs."),
    "ui_layout_get_element_rectangle": Command(func=ui_layout_get_element_rectangle, doc="Get element rect. Args: element_id, **kwargs."),
    "ui_layout_get_layout": Command(func=ui_layout_get_layout, doc="Get layout. Args: name, **kwargs."),
    "ui_layout_get_layout_names": Command(func=ui_layout_get_layout_names, doc="Get layout names. Args: **kwargs."),
    "ui_layout_get_or_create_view": Command(func=ui_layout_get_or_create_view, doc="Get or create view. Args: name, pos_x=0, pos_y=0, **kwargs."),
    "ui_layout_get_view_instances": Command(func=ui_layout_get_view_instances, doc="Get view instances. Args: name='Designer', **kwargs."),
    "ui_layout_get_view_types": Command(func=ui_layout_get_view_types, doc="Get view types. Args: **kwargs."),
    "ui_layout_move_splitter": Command(func=ui_layout_move_splitter, doc="Move splitter. Args: splitter_id, delta, **kwargs."),
    "ui_layout_remove_layout": Command(func=ui_layout_remove_layout, doc="Remove layout. Args: layout_name, **kwargs."),
    "ui_layout_reset_layouts": Command(func=ui_layout_reset_layouts, doc="Reset layouts. Args: **kwargs."),
    "ui_layout_set_layout": Command(func=ui_layout_set_layout, doc="Set layout. Args: layout_json, **kwargs."),
    "ui_layout_undock_view": Command(func=ui_layout_undock_view, doc="Undock view. Args: view_id, **kwargs."),
    "ui_project_close": Command(func=ui_project_close, doc="Close project (UI). Args: **kwargs."),
    "ui_project_create": Command(func=ui_project_create, doc="Create project (UI). Args: path, platform, **kwargs."),
    "ui_project_open": Command(func=ui_project_open, doc="Open project (UI). Args: path, **kwargs."),
    "waapi_get_functions": Command(func=waapi_get_functions, doc="Get WAAPI functions. Args: **kwargs."),
    "waapi_get_schema": Command(func=waapi_get_schema, doc="Get WAAPI schema. Args: uri=None, **kwargs."),
    "waapi_schema_get_args_spec": Command(func=waapi_schema_get_args_spec, doc="Get args spec (required/optional) for a WAAPI URI from getSchema. Args: uri."),
    "waapi_validate_args": Command(func=waapi_validate_args, doc="Validate args dict against WAAPI schema for uri. Args: uri, args (dict). Returns (ok, errors)."),
    "waapi_get_topics": Command(func=waapi_get_topics, doc="Get WAAPI topics. Args: **kwargs."),
    "waapi_subscribe": Command(func=waapi_subscribe, doc="Subscribe to a WAAPI topic. Args: uri, options=None, **kwargs. Returns subscription_id."),
    "waapi_unsubscribe": Command(func=waapi_unsubscribe, doc="Unsubscribe by subscription_id. Args: subscription_id. Returns bool."),
    "waapi_subscription_events": Command(func=waapi_subscription_events, doc="Get events for a subscription. Args: subscription_id, max_count=None, clear=True. Returns list of event dicts."),
    "waapi_list_topic_uris": Command(func=waapi_list_topic_uris, doc="Return list of WAAPI topic URIs from reference. Args: None."),
    "subscribe_topic_audio_imported": Command(func=subscribe_topic_audio_imported, doc="Subscribe to ak.wwise.core.audio.imported. Returns subscription_id."),
    "subscribe_topic_log_item_added": Command(func=subscribe_topic_log_item_added, doc="Subscribe to ak.wwise.core.log.itemAdded. Returns subscription_id."),
    "subscribe_topic_object_attenuation_curve_changed": Command(func=subscribe_topic_object_attenuation_curve_changed, doc="Subscribe to ak.wwise.core.object.attenuationCurveChanged. Returns subscription_id."),
    "subscribe_topic_object_attenuation_curve_link_changed": Command(func=subscribe_topic_object_attenuation_curve_link_changed, doc="Subscribe to ak.wwise.core.object.attenuationCurveLinkChanged. Returns subscription_id."),
    "subscribe_topic_object_child_added": Command(func=subscribe_topic_object_child_added, doc="Subscribe to ak.wwise.core.object.childAdded. Returns subscription_id."),
    "subscribe_topic_object_child_removed": Command(func=subscribe_topic_object_child_removed, doc="Subscribe to ak.wwise.core.object.childRemoved. Returns subscription_id."),
    "subscribe_topic_object_created": Command(func=subscribe_topic_object_created, doc="Subscribe to ak.wwise.core.object.created. Returns subscription_id."),
    "subscribe_topic_object_curve_changed": Command(func=subscribe_topic_object_curve_changed, doc="Subscribe to ak.wwise.core.object.curveChanged. Returns subscription_id."),
    "subscribe_topic_object_name_changed": Command(func=subscribe_topic_object_name_changed, doc="Subscribe to ak.wwise.core.object.nameChanged. Returns subscription_id."),
    "subscribe_topic_object_notes_changed": Command(func=subscribe_topic_object_notes_changed, doc="Subscribe to ak.wwise.core.object.notesChanged. Returns subscription_id."),
    "subscribe_topic_object_post_deleted": Command(func=subscribe_topic_object_post_deleted, doc="Subscribe to ak.wwise.core.object.postDeleted. Returns subscription_id."),
    "subscribe_topic_object_pre_deleted": Command(func=subscribe_topic_object_pre_deleted, doc="Subscribe to ak.wwise.core.object.preDeleted. Returns subscription_id."),
    "subscribe_topic_object_property_changed": Command(func=subscribe_topic_object_property_changed, doc="Subscribe to ak.wwise.core.object.propertyChanged. Returns subscription_id."),
    "subscribe_topic_object_reference_changed": Command(func=subscribe_topic_object_reference_changed, doc="Subscribe to ak.wwise.core.object.referenceChanged. Returns subscription_id."),
    "subscribe_topic_object_structure_changed": Command(func=subscribe_topic_object_structure_changed, doc="Subscribe to ak.wwise.core.object.structureChanged. Returns subscription_id."),
    "subscribe_topic_profiler_capture_log_item_added": Command(func=subscribe_topic_profiler_capture_log_item_added, doc="Subscribe to ak.wwise.core.profiler.captureLog.itemAdded. Returns subscription_id."),
    "subscribe_topic_profiler_game_object_registered": Command(func=subscribe_topic_profiler_game_object_registered, doc="Subscribe to ak.wwise.core.profiler.gameObjectRegistered. Returns subscription_id."),
    "subscribe_topic_profiler_game_object_reset": Command(func=subscribe_topic_profiler_game_object_reset, doc="Subscribe to ak.wwise.core.profiler.gameObjectReset. Returns subscription_id."),
    "subscribe_topic_profiler_game_object_unregistered": Command(func=subscribe_topic_profiler_game_object_unregistered, doc="Subscribe to ak.wwise.core.profiler.gameObjectUnregistered. Returns subscription_id."),
    "subscribe_topic_profiler_state_changed": Command(func=subscribe_topic_profiler_state_changed, doc="Subscribe to ak.wwise.core.profiler.stateChanged. Returns subscription_id."),
    "subscribe_topic_profiler_switch_changed": Command(func=subscribe_topic_profiler_switch_changed, doc="Subscribe to ak.wwise.core.profiler.switchChanged. Returns subscription_id."),
    "subscribe_topic_project_loaded": Command(func=subscribe_topic_project_loaded, doc="Subscribe to ak.wwise.core.project.loaded. Returns subscription_id."),
    "subscribe_topic_project_post_closed": Command(func=subscribe_topic_project_post_closed, doc="Subscribe to ak.wwise.core.project.postClosed. Returns subscription_id."),
    "subscribe_topic_project_pre_closed": Command(func=subscribe_topic_project_pre_closed, doc="Subscribe to ak.wwise.core.project.preClosed. Returns subscription_id."),
    "subscribe_topic_project_saved": Command(func=subscribe_topic_project_saved, doc="Subscribe to ak.wwise.core.project.saved. Returns subscription_id."),
    "subscribe_topic_soundbank_generated": Command(func=subscribe_topic_soundbank_generated, doc="Subscribe to ak.wwise.core.soundbank.generated. Returns subscription_id."),
    "subscribe_topic_soundbank_generation_done": Command(func=subscribe_topic_soundbank_generation_done, doc="Subscribe to ak.wwise.core.soundbank.generationDone. Returns subscription_id."),
    "subscribe_topic_switch_container_assignment_added": Command(func=subscribe_topic_switch_container_assignment_added, doc="Subscribe to ak.wwise.core.switchContainer.assignmentAdded. Returns subscription_id."),
    "subscribe_topic_switch_container_assignment_removed": Command(func=subscribe_topic_switch_container_assignment_removed, doc="Subscribe to ak.wwise.core.switchContainer.assignmentRemoved. Returns subscription_id."),
    "subscribe_topic_transport_state_changed": Command(func=subscribe_topic_transport_state_changed, doc="Subscribe to ak.wwise.core.transport.stateChanged. Returns subscription_id."),
    "subscribe_topic_debug_assert_failed": Command(func=subscribe_topic_debug_assert_failed, doc="Subscribe to ak.wwise.debug.assertFailed (Debug builds). Returns subscription_id."),
    "subscribe_topic_ui_commands_executed": Command(func=subscribe_topic_ui_commands_executed, doc="Subscribe to ak.wwise.ui.commands.executed. Returns subscription_id."),
    "subscribe_topic_ui_selection_changed": Command(func=subscribe_topic_ui_selection_changed, doc="Subscribe to ak.wwise.ui.selectionChanged. Returns subscription_id."),
}

def list_commands()-> list[str]: 
    
    """
    Return each available command with its signature, e.g.
    'create_event(parent:str, name:str, type:str)'.
    """

    specs = []
    for name, cmd in COMMANDS.items():
        sig  = f"{name}{inspect.signature(cmd.func)}"
        hint = cmd.doc.strip() if cmd.doc else ""
        # put the hint on its own new line
        specs.append(f"{sig}\n    {hint}")
    return specs

#  A. parse a "verb(arg,…)" legacy string
def _parse_call(call_str: str) -> tuple[str, list, dict]:
    tree = ast.parse(call_str, mode="eval")
    if not isinstance(tree.body, ast.Call):
        raise ValueError(f"Expected func(...), got: {call_str}")

    verb   = tree.body.func.id
    args   = [ast.literal_eval(a) for a in tree.body.args]
    kwargs = {kw.arg: ast.literal_eval(kw.value)
              for kw in tree.body.keywords}
    return verb, args, kwargs

#  B. helper to extract .ids / .name from list-of-dicts 
def _extract_attr(obj, attr):
    if isinstance(obj, list):
        return [d[attr] for d in obj if isinstance(d, dict) and attr in d]
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr)

#  C. $var resolver (works on scalars / list / dict) 
def _resolve(val, store):
    if isinstance(val, str) and val.startswith("$"):
        key, *rest = val[1:].split(".", 1)
        if key not in store:
            raise KeyError(f"Variable '{key}' not found")
        obj = store[key]
        if rest:
            obj = _extract_attr(obj, rest[0])
        return obj
    if isinstance(val, list):
        return [_resolve(v, store) for v in val]
    if isinstance(val, dict):
        return {k: _resolve(v, store) for k, v in val.items()}
    return val

#  D. Commands that modify Wwise project (trigger undo wrap). Read-only / source_control get_* do NOT trigger.
PLAN_MODIFYING_COMMANDS = frozenset({
    "create_objects", "create_events", "create_game_objects", "create_rtpcs",
    "create_switch_groups", "create_switches", "create_state_groups", "create_states",
    "move_object_by_path", "rename_objects", "import_audio_files",
    "include_in_soundbank", "generate_soundbanks",
    "set_object_reference", "set_object_property",
    "blend_container_add_assignment", "blend_container_add_track", "blend_container_remove_assignment",
    "switch_container_add_assignment", "switch_container_remove_assignment",
    "execute_lua_script", "log_add_item", "log_clear",
    "object_copy", "object_delete", "object_paste_properties", "object_set",
    "object_set_attenuation_curve", "object_set_linked", "object_set_notes",
    "object_set_randomizer", "object_set_state_groups", "object_set_state_properties",
    "project_save", "sound_set_active_source",
    "soundbank_process_definition_files", "soundbank_convert_external_sources",
    "source_control_add", "source_control_check_out", "source_control_commit", "source_control_delete",
    "source_control_move", "source_control_revert", "source_control_set_provider",
    "transport_create", "transport_destroy", "transport_execute_action", "transport_prepare", "transport_use_originals",
    "work_unit_load", "work_unit_unload",
    "console_project_close", "console_project_create", "console_project_open",
    "audio_convert", "audio_import_tab_delimited", "audio_mute", "audio_reset_mute", "audio_reset_solo",
    "audio_set_conversion_plugin", "audio_solo",
    "ui_layout_close_view", "ui_layout_dock_view", "ui_layout_remove_layout", "ui_layout_reset_layouts",
    "ui_layout_set_layout", "ui_layout_switch_layout", "ui_layout_undock_view",
    "ui_project_close", "ui_project_create", "ui_project_open",
    "debug_enable_asserts", "debug_enable_automation_mode", "debug_generate_tone_wav",
    "debug_restart_waapi_servers", "debug_test_assert", "debug_test_crash",
})

def _plan_verbs(plan: list[any]) -> list[str]:
    """Collect verb (command name) from each step without executing. Used to decide if undo wrap is needed."""
    verbs: list[str] = []
    for step in plan:
        if isinstance(step, str):
            verb, _, _ = _parse_call(step)
            verbs.append(verb)
        else:
            verbs.append(step["command"])
    return verbs

def _run_plan_sync(plan: list[any]) -> list[dict[str, any]]:
    store: dict[str, any] = {}        # per-plan variable bucket
    log  : list[dict[str, any]] = []

    def _run_one(verb: str, args: list, kwargs: dict, save_as: str | None) -> any:
        if verb not in COMMANDS:
            raise ValueError(f"Unknown command '{verb}'")
        func = COMMANDS[verb].func
        inspect.signature(func).bind_partial(*args, **kwargs)
        result = func(*args, **kwargs)
        store["last"] = result
        if save_as:
            store[save_as] = result
        return result

    # 0) Ensure WAAPI connected before any Wwise command
    try:
        conn_result = _run_one("connect_to_wwise", [], {}, None)
        log.append({"command": "connect_to_wwise", "kwargs": {}, "result": conn_result})
    except Exception as e:
        logger.exception("connect_to_wwise failed at start of plan")
        log.append({"command": "connect_to_wwise", "kwargs": {}, "result": None, "error": str(e)})
        raise

    # 1) Only wrap with undo when plan contains at least one project-modifying command
    plan_verbs = _plan_verbs(plan)
    need_undo = any(v in PLAN_MODIFYING_COMMANDS for v in plan_verbs)

    if need_undo:
        # 1a) Start undo group so the whole plan is one undo step in Wwise
        try:
            beg_result = _run_one("undo_begin_group", [], {}, None)
            log.append({"command": "undo_begin_group", "kwargs": {}, "result": beg_result})
        except Exception as e:
            logger.exception("undo_begin_group failed before running plan")
            log.append({"command": "undo_begin_group", "kwargs": {}, "result": None, "error": str(e)})
            raise

    # 2) Run user plan steps
    try:
        for step in plan:
            if isinstance(step, str):
                verb, args, kwargs = _parse_call(step)
                args   = _resolve(args, store)
                kwargs = _resolve(kwargs, store)
                save_as = None
            else:
                verb   = step["command"]
                args   = []
                kwargs = _resolve(step["args"], store)
                save_as = step.get("save_as")

            result = _run_one(verb, args, kwargs, save_as)
            log.append({"command": verb, "kwargs": kwargs, "result": result})
    except Exception as e:
        if need_undo:
            # 3a) Plan failed: cancel undo group so Wwise reverts all changes (all-or-nothing)
            logger.exception("Plan step failed, cancelling undo group")
            try:
                cancel_result = _run_one("undo_cancel_group", [], {}, None)
                log.append({"command": "undo_cancel_group", "kwargs": {}, "result": cancel_result})
            except Exception as cancel_e:
                logger.warning("undo_cancel_group failed: %s", cancel_e)
                log.append({"command": "undo_cancel_group", "kwargs": {}, "result": None, "error": str(cancel_e)})
        raise

    if need_undo:
        # 3b) All steps ok: end undo group so the whole plan is one undo step
        try:
            end_result = _run_one("undo_end_group", [], {}, None)
            log.append({"command": "undo_end_group", "kwargs": {}, "result": end_result})
        except Exception as e:
            logger.exception("undo_end_group failed after plan succeeded")
            try:
                _run_one("undo_cancel_group", [], {}, None)
                log.append({"command": "undo_cancel_group", "kwargs": {}, "result": None, "reason": "after undo_end_group failure"})
            except Exception:
                pass
            log.append({"command": "undo_end_group", "kwargs": {}, "result": None, "error": str(e)})
            raise

    return log

#==============================================================================
#                       MCP defintion & related functions
#==============================================================================

mcp = FastMCP(
    name = "Wwise-MCP Server",
    version = "1.0"
)

@mcp.tool()
async def execute_plan( plan: list[str]) -> dict [str, any]:

    """
    Execute a JSON list of call-strings produced by Claude.
    Returns simple success/failure info.
    """
    
    log = await anyio.to_thread.run_sync(_run_plan_sync, plan)

    return {"status": "ok", "steps_executed": len(log), "log": log}

# Run the server
if __name__ == "__main__":
    
    configure_logger()
    try: 
        logger.info("Starting Wwise-MCP server…")
        mcp.run(transport="stdio")
    except Exception: 
        logger.exception("Fatal server error")
        raise
    finally:
        WwisePythonLibrary.disconnect_from_wwise_client()
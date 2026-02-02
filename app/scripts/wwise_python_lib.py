from pathlib import Path
from typing import Iterable, Mapping, Any
import math 
import secrets
import time
import logging
import wwise_session as WwiseSession

from wwise_errors import (
    WwisePyLibError,
    WwiseValidationError,
    WwiseObjectNotFoundError,
    WwiseApiError
)

# Set up logger for this module
logger = logging.getLogger(__name__)

# ==============================================================================
#                      Waapi Client & Call Wrapper
# ==============================================================================

def connect_to_waapi(): 
    WwiseSession.connect_to_waapi()

def disconnect_from_wwise_client(): 
    WwiseSession.disconnect_from_wwise_client()

def waapi_call(
    uri: str, 
    args: Mapping[str, Any] | None = None, 
    options: Mapping[str, Any] | None = None, 
    **kw : Any
)-> Any:
    if not uri or not isinstance(uri, str): 
        raise ValueError("uri must be a non-empty string when calling waapi_call.")
    
    return WwiseSession.waapi_call(uri, args or {}, options=options, **kw)

# ==============================================================================
#                               Soundbank 
# ==============================================================================

def get_project_info() -> dict:
    """
    Retrieve information about the currently open Wwise project.
    
    Returns:
        dict: Project information including name, path, platform details, etc.
        
    Raises:
        WwiseApiError: If the WAAPI call fails or no project is open.
    """
    try:
        response = waapi_call("ak.wwise.core.getProjectInfo", {})
        
        if response is None:
            raise WwiseApiError(
                "WAAPI returned None when fetching project info (no project may be open)",
                operation="ak.wwise.core.getProjectInfo"
            )
        
        return response
    
    except WwisePyLibError:
        raise
    
    except Exception as e:
        raise WwiseApiError(
            f"Unexpected error fetching project info: {str(e)}",
            operation="ak.wwise.core.getProjectInfo",
            details={"error_type": type(e).__name__}
        )

def get_all_languages() -> list[str]:
    """
    Retrieve all languages configured in the current Wwise project.
    
    Returns:
        list[str]: List of language names (e.g., ['English(US)', 'French(France)']).
                   Returns empty list if no languages are configured.
        
    Raises:
        WwiseApiError: If project info cannot be retrieved.
        WwiseValidationError: If project info response is malformed.
    """
    try:
        response = get_project_info()
        
        if "languages" not in response:
            raise WwiseValidationError(
                "Project info response missing 'languages' field"
            )
        
        languages = [lang["name"] for lang in response["languages"]]
        return languages
    
    except WwisePyLibError:
        raise
    
    except KeyError as e:
        raise WwiseValidationError(
            f"Malformed language data in project info: missing {str(e)} field"
        )
    
    except Exception as e:
        raise WwiseApiError(
            f"Unexpected error fetching languages: {str(e)}",
            operation="ak.wwise.core.getProjectInfo",
            details={"error_type": type(e).__name__}
        )

def get_all_platforms() -> list[str]:
    """
    Retrieve all platforms configured in the current Wwise project.
    
    Returns:
        list[str]: List of platform names (e.g., ['Windows', 'PlayStation 5', 'Xbox Series X']).
        
    Raises:
        WwiseApiError: If project info cannot be retrieved.
        WwiseValidationError: If project info response is malformed or missing platforms.
    """
    try:
        response = get_project_info()
        
        if "platforms" not in response:
            raise WwiseValidationError(
                "Project info response missing 'platforms' field"
            )
        
        platforms = [platform["name"] for platform in response["platforms"]]
        
        if not platforms:
            raise WwiseValidationError(
                "No platforms configured in the project"
            )
        
        return platforms
    
    except WwisePyLibError:
        raise
    
    except KeyError as e:
        raise WwiseValidationError(
            f"Malformed platform data in project info: missing {str(e)} field"
        )
    
    except Exception as e:
        raise WwiseApiError(
            f"Unexpected error fetching platforms: {str(e)}",
            operation="ak.wwise.core.getProjectInfo",
            details={"error_type": type(e).__name__}
        )

def get_all_soundbanks() -> list[str]:
    """
    Retrieve all SoundBanks configured in the current Wwise project.
    
    Returns:
        list[str]: List of SoundBank names. Returns empty list if no SoundBanks exist.
        
    Raises:
        WwiseApiError: If the WAAPI call fails.
        WwiseValidationError: If the response is malformed.
    """
    args = {
        "from": {"path": ["\\SoundBanks"]},
        "transform": [{"select": ["descendants"]}],
        "options": {"return": ["name", "type", "path"]}
    }
    
    try:
        response = waapi_call("ak.wwise.core.object.get", args)
        
        if response is None:
            raise WwiseApiError(
                "WAAPI returned None when fetching SoundBanks",
                operation="ak.wwise.core.object.get",
                details={"path": "\\SoundBanks"}
            )
        
        if "return" not in response:
            raise WwiseValidationError(
                "Response missing 'return' field when fetching SoundBanks"
            )
        
        # Filter objects of type 'SoundBank'
        soundbanks = [
            obj["name"] for obj in response["return"] 
            if obj.get("type") == "SoundBank"
        ]
        
        return soundbanks
    
    except WwisePyLibError:
        raise
    
    except KeyError as e:
        raise WwiseValidationError(
            f"Malformed SoundBank data: missing {str(e)} field"
        )
    
    except Exception as e:
        raise WwiseApiError(
            f"Unexpected error fetching SoundBanks: {str(e)}",
            operation="ak.wwise.core.object.get",
            details={
                "error_type": type(e).__name__,
                "path": "\\SoundBanks"
            }
        )

def include_in_soundbank(
    include_paths: list[str], 
    soundbank_path: str
) -> list[dict]:
    """
    Add objects to a SoundBank's inclusions list.
    
    Note: This operation is NOT atomic. If a failure occurs, all previous
    inclusions will have succeeded. The returned list contains responses for
    successfully included objects before the failure.
    
    Args:
        include_paths: List of Wwise object paths to include in the SoundBank.
        soundbank_path: Path to the target SoundBank.
    
    Returns:
        list[dict]: List of WAAPI responses for each successful inclusion operation.
        
    Raises:
        WwiseValidationError: If inputs are invalid.
        WwiseApiError: If any inclusion operation fails.
    """
    if not include_paths:
        raise WwiseValidationError("include_paths list cannot be empty")
    
    if not soundbank_path or not soundbank_path.strip():
        raise WwiseValidationError("soundbank_path cannot be empty")
    
    result: list[dict] = []
    
    for i, include_path in enumerate(include_paths):
        if not include_path or not include_path.strip():
            raise WwiseValidationError(
                f"include_path at index {i} cannot be empty"
            )
        
        args = {
            "soundbank": soundbank_path,
            "operation": "add",
            "inclusions": [{
                "object": include_path,
                "filter": ["events", "structures"]
            }]
        }
        
        try:
            response = waapi_call("ak.wwise.core.soundbank.setInclusions", args)
            
            if response is None:
                raise WwiseApiError(
                    f"WAAPI returned None when including object at index {i}",
                    operation="ak.wwise.core.soundbank.setInclusions",
                    details={
                        "soundbank_path": soundbank_path,
                        "include_path": include_path,
                        "index": i
                    }
                )
            
            result.append(response)
        
        except WwisePyLibError:
            raise
        
        except Exception as e:
            raise WwiseApiError(
                f"Failed to include object at index {i}: {str(e)}",
                operation="ak.wwise.core.soundbank.setInclusions",
                details={
                    "error_type": type(e).__name__,
                    "soundbank_path": soundbank_path,
                    "include_path": include_path,
                    "index": i
                }
            )
    
    return result

def generate_soundbanks(
    soundbanks: list[str], 
    platforms: list[str], 
    languages: list[str] = None
) -> dict:
    """
    Generate SoundBanks for specified platforms and languages.
    
    Args:
        soundbanks: List of SoundBank names to generate.
        platforms: List of platform names to generate for.
        languages: Optional list of language names. If None, generates for all project languages.
    
    Returns:
        dict: Generation result containing success/failure info and generated file paths.
        
    Raises:
        WwiseValidationError: If inputs are invalid.
        WwiseApiError: If the SoundBank generation fails.
    """
    if not soundbanks:
        raise WwiseValidationError("soundbanks list cannot be empty")
    
    if not platforms:
        raise WwiseValidationError("platforms list cannot be empty")
    
    # Validate individual items
    for i, sb in enumerate(soundbanks):
        if not sb or not sb.strip():
            raise WwiseValidationError(f"SoundBank name at index {i} cannot be empty")
    
    for i, platform in enumerate(platforms):
        if not platform or not platform.strip():
            raise WwiseValidationError(f"Platform name at index {i} cannot be empty")
    
    if languages is not None:
        if not languages:
            raise WwiseValidationError("languages list cannot be empty (use None for all languages)")
        for i, lang in enumerate(languages):
            if not lang or not lang.strip():
                raise WwiseValidationError(f"Language name at index {i} cannot be empty")
    
    # Build the payload
    payload = {
        "soundbanks": [{"name": sb} for sb in soundbanks],
        "platforms": platforms,
        "writeToDisk": True
    }
    
    if languages is not None:
        payload["languages"] = languages
    
    try:
        response = waapi_call("ak.wwise.core.soundbank.generate", payload)
        
        if response is None:
            raise WwiseApiError(
                "WAAPI returned None when generating SoundBanks",
                operation="ak.wwise.core.soundbank.generate",
                details={
                    "soundbanks": soundbanks,
                    "platforms": platforms,
                    "languages": languages
                }
            )
        
        return response
    
    except WwisePyLibError:
        raise
    
    except Exception as e:
        raise WwiseApiError(
            f"Unexpected error generating SoundBanks: {str(e)}",
            operation="ak.wwise.core.soundbank.generate",
            details={
                "error_type": type(e).__name__,
                "soundbanks": soundbanks,
                "platforms": platforms,
                "languages": languages
            }
        )
    
# ==============================================================================
#                  Game Objects & Playback in Wwise
# ==============================================================================

LISTENER_ID = 1
DEFAULT_GAME_OBJ_NAME = "Global"

def get_all_game_objs_in_wwise_session() -> list[dict]:
    return waapi_call("ak.wwise.core.profiler.getGameObjects", {"time": "capture"})

def register_default_listener()-> None:
    waapi_call("ak.soundengine.registerGameObj", 
                {"gameObject": LISTENER_ID, 
                 "name": "listener"}) 
    waapi_call("ak.soundengine.setDefaultListeners", 
               {"listeners" : [LISTENER_ID]})
        
def alloc_game_object_id(name : str) -> int:
    
    game_objs = get_all_game_objs_in_wwise_session().get("return",[])
    existing = {int(go["id"]) for go in game_objs}
    max_tries = 64

    if LISTENER_ID not in existing:
        register_default_listener()

    for _ in range(max_tries):
        gid = secrets.randbits(31)           
        
        if gid not in existing:
            waapi_call(
                "ak.soundengine.registerGameObj", 
                {"gameObject": gid, 
                 "name": name}) 
            waapi_call(
                "ak.soundengine.setListeners",
                {
                    "emitter":   gid,          # game object that produces sound
                    "listeners": [LISTENER_ID]        # one or many listener IDs
                }) 
            time.sleep(0.02) # short delay so the next read from capture gets the updated game obj list 
            return gid
    raise RuntimeError("Could not allocate a unique game object ID")

def ensure_game_obj(name: str) -> int:

    if not isinstance(name, str) or not name.strip():
        raise ValueError("Provide a non empty string name when creating a game obj.")

    game_objs = get_all_game_objs_in_wwise_session().get("return",[])    
    cleansed_name = name.strip().lower()

    for game_obj in game_objs : 
        game_obj_name = game_obj["name"]
        
        if not isinstance(game_obj_name, str) or not game_obj_name.strip(): 
            continue

        if (game_obj_name.lower() == cleansed_name):
            return game_obj["id"]

    return alloc_game_object_id(name)

def set_game_obj_position(
    game_obj_name : str, 
    x : float, 
    y : float, 
    z : float)->None: 

    gid = ensure_game_obj(game_obj_name)

    origin  = {"x": x,   "y": y,   "z": z}
    forward = {"x": 0.0, "y": 1.0, "z": 0.0}
    up      = {"x": 0.0, "y": 0.0, "z": 1.0}
    
    return waapi_call("ak.soundengine.setPosition", {
        "gameObject": gid,
        "position": {
            "position": origin,
            "orientationFront": forward,
            "orientationTop":   up,
        }
    })

Vec3 = tuple[float, float, float]

def _norm_vec(v: Vec3) -> Vec3:
    x,y,z = v
    n = math.sqrt(x*x + y*y + z*z) or 1.0
    return (x/n, y/n, z/n)

def _dot(a: Vec3, b: Vec3) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

def _lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (a[0] + (b[0]-a[0])*t,
            a[1] + (b[1]-a[1])*t,
            a[2] + (b[2]-a[2])*t)

def _orthonormalize(front: Vec3, top: Vec3) -> tuple[Vec3, Vec3]:
    f = _norm_vec(front)
    # Gram–Schmidt: make top orthogonal to front, then normalize
    t = _sub(top, (f[0]*_dot(top,f), f[1]*_dot(top,f), f[2]*_dot(top,f)))
    if t == (0.0,0.0,0.0):
        t = (0.0,1.0,0.0)
    return f, _norm_vec(t)

def _enqueue_position(gid: int, pos: Vec3, front: Vec3, top: Vec3, *, due_in_s: float):
    waapi_call("ak.soundengine.setPosition", {
        "gameObject": gid,
        "position": {
            "position": {"x": pos[0], "y": pos[1], "z": pos[2]},
            "orientationFront": {"x": front[0], "y": front[1], "z": front[2]},
            "orientationTop":   {"x": top[0],   "y": top[1],   "z": top[2]},
        }
    }, due_in = due_in_s, wait = False)

def start_position_ramp(
    *,
    obj: str,
    start_pos: Vec3,
    end_pos: Vec3,
    duration_ms: int, 
    step_ms: int = 100,
    delay_ms: int,
    front: Vec3 = (0.0, 1.0, 0.0),  
    top:   Vec3 = (0.0, 0.0, 1.0),  
)-> None:
    """
    Schedules an interpolation of (x,y,z) from start_pos to end_pos over duration_ms.
    Uses the dispatcher-backed waapi_call(due_in=..., wait=False) for each step.
    Returns a tiny handle with no-op stop/join (for API parity).
    """

    gid = ensure_game_obj(obj)

    f, t = _orthonormalize(front, top)

    if duration_ms <=0 :
        _enqueue_position(gid, start_pos, f, t, due_in_s=0.0)
        _enqueue_position(gid, end_pos,   f, t, due_in_s=0.0)
        return
    
    if delay_ms < 0:
        delay_ms = 0
    
    dur_s  = duration_ms / 1000.0
    delay_s = delay_ms / 1000.0
    dt_s   = max(0.001, step_ms / 1000.0)
    steps  = max(1, math.ceil(dur_s / dt_s))

    # First sample at t=0, last at t=dur_s; linear easing
    for i in range(steps + 1):
        a   = i / steps
        pos = _lerp(start_pos, end_pos, a)
        _enqueue_position(gid, pos, f, t, due_in_s=a * dur_s + delay_s)

def create_game_obj(game_obj_name : str, position : Vec3) -> None: 
    return set_game_obj_position(game_obj_name, position[0], position[1], position[2])

def unregister_game_obj(name: str) -> None:
    id : int = ensure_game_obj(name)
    waapi_call("ak.soundengine.unregisterGameObj", {"gameObject": id})

def stop_all_sounds():
    game_objs = get_all_game_objs_in_wwise_session().get("return",[])
    
    for game_obj in game_objs:
        gid = game_obj["id"]
        waapi_call("ak.soundengine.stopAll", {"gameObject": gid})
 
# ==============================================================================
#             Creating, Listing & Posting Events in Wwise
# ==============================================================================

EVENT_TYPES = {
    "play"  : 1, 
    "stop"  : 2,
    "pause" : 7,
    "resume": 9,
    "break" : 34,
    "seek"  : 36
}

EVENT_TYPE_NAMES = list(EVENT_TYPES.keys()) 

OBJECTS_ALLOWEDEVENTS = {
    "ActorMixer"             :  EVENT_TYPE_NAMES[1:],
    "Bus"                    :  EVENT_TYPE_NAMES[1:],
    "AuxBus"                 :  [EVENT_TYPE_NAMES[5]],
    "RandomSequenceContainer":  EVENT_TYPE_NAMES,
    "SwitchContainer"        :  EVENT_TYPE_NAMES,
    "BlendContainer"         :  EVENT_TYPE_NAMES,
    "Sound"                  :  EVENT_TYPE_NAMES,
    "WorkUnit"               :  None, 
    "SoundBank"              :  None, 
    "Folder"                 :  None
}
   
def create_event(
    source_path : str, 
    dst_parent_path : str, 
    event_type : str, 
    event_name : str
) -> dict:
    """
    Create a Wwise event with associated action.
    
    Args:
        source_path: Path to the source object for the action target
        dst_parent_path: Path to the parent where event will be created
        event_type: Type of action (must be key in ACTION_TYPES)
        event_name: Name for the new event
    
    Returns:
        dict: Contains 'event' and 'action' response objects
    
    Raises:
        WwiseValidationError: If input validation fails
        WwiseObjectNotFoundError: If paths cannot be resolved
        WwiseApiError: If WAAPI calls fail
    """
    
    # 1. Validate inputs
    if not all([source_path, dst_parent_path, event_name, event_type]):
        raise WwiseValidationError("All parameters must be non-empty. "
        f"Received: source_path={bool(source_path)}, "
        f"dst_parent_path={bool(dst_parent_path)}, "
        f"event_name={bool(event_name)}, "
        f"event_type={bool(event_type)}"
    )

    event_type = event_type.lower()

    if event_type not in EVENT_TYPES:
        raise WwiseValidationError(
        f"Invalid event_type '{event_type}'. "
        f"Valid types: {', '.join(sorted(set(EVENT_TYPES.keys())))}")
    
    try:
        # 2. Resolve parent object
        parent_ref = get_object_at_path(dst_parent_path)
        if not parent_ref: 
            raise WwiseObjectNotFoundError(f"Failed to create event: {event_name}. The parent path supplied is invalid. Please specify a valid parent path for the new event.")
        if "id" not in parent_ref or not parent_ref["id"]:
            raise WwiseApiError(f"Failed to create event: {event_name}. Parent destination object does not contain an id attribute or has no id. Please specify a valid parent path object.") 
        parent_id = parent_ref["id"]

        # 3. Resolve source object
        source_object = get_object_at_path(source_path)
        if not source_object:
            raise WwiseObjectNotFoundError(f"Failed to create event: {event_name}. Source Object does not exist. The provided source path is invalid.")
        if "id" not in source_object or not source_object["id"]:
            raise WwiseApiError(f"Source Object does not contain an id attribute or has no id. Please specify a valid source object.")
        source_object_id = source_object["id"]

        # 4. Create event
        event_response = waapi_call(
            "ak.wwise.core.object.create", {
            "parent": parent_id,
            "type": "Event",
            "name": event_name, 
            "onNameConflict": "rename"
        })

        if not event_response or "id" not in event_response or not event_response["id"]:
            raise WwiseApiError(
                f"Event creation for '{event_name}' returned invalid response",
                operation="create_event",
                details={"response": event_response}
            )
        logger.info(f"Created event with ID: {event_response['id']}")

        # 5. Create action
        action_response = waapi_call(
            "ak.wwise.core.object.create", {
            "parent": event_response["id"],
            "type": "Action",
            "name": event_name,
            "@ActionType": EVENT_TYPES[event_type],
            "@Target": source_object_id
        })

        if not action_response or "id" not in action_response:
            raise WwiseApiError(
                f"Action creation for event '{event_name}' returned invalid response",
                operation="create_action",
                details={"response": action_response}
            )
        logger.info(f"Created action with ID: {action_response['id']}")

        return {
            "event": event_response,
            "action": action_response
        }
    except (WwiseValidationError, WwiseObjectNotFoundError):
        # These are expected errors - re-raise as-is
        raise
    
    except WwiseApiError as e:
        # API errors - re-raise as-is
        raise
    
    except Exception as e:
        # Unexpected error
        logger.error(f"Unexpected error creating event '{event_name}': {e}", exc_info=True)
        raise WwiseApiError(
            f"Unexpected error creating event '{event_name}': {str(e)}",
            operation="create_event"
        ) from e

def list_all_event_names(
    filter_spec: str | None = None
) -> list[str]:
    """
    Return the names of all matching objects in the \\Events tree.

    Parameters
    ----------
    filter_spec  : str | None
        • None or ''            → all Events in the project
        • absolute path         → e.g. r"\\Events\\Ambience" (all descendants)
        • name fragment         → fuzzy-matches names anywhere in \\Events

    Returns
    -------
    list[str] - the object *names* (not paths).  May be empty.

    Raises
    ------
    RuntimeError on WAAPI failure.
    """
    spec = (filter_spec or "").strip()

    # 1️. decide the subtree we start from + optional name filter
    if spec.startswith("\\"):                 # absolute path
        start_path = spec.rstrip("\\")
        name_cond  = ""                       # no extra name filter
    elif spec:                                # just a name fragment
        start_path = r"\Events"
        name_cond  = spec
    else:                                     # empty -> all Events
        start_path = r"\Events"
        name_cond  = ""

    # 2️. build WAAPI query
    transform = [{"select": ["descendants"]}]
    if name_cond:
        transform.append({"where": ["name:matches", name_cond]})    
    transform.append({"where": ["type:isIn", ["Event"]]})

    query_args = {"from": {"path": [start_path]}, "transform": transform}
    query_opts = {"return": ["name"]}

    res = waapi_call("ak.wwise.core.object.get", query_args, options=query_opts)
    if not res or "return" not in res:
        raise RuntimeError("WAAPI call failed or returned no data")

    return [obj["name"] for obj in res["return"]]

def post_event(
  event_name: str,
  game_obj: str,
  delay_ms: int
) -> None:

  if delay_ms < 0:
    raise ValueError("delay_ms must be >= 0")
  
  if not game_obj: 
    game_obj = DEFAULT_GAME_OBJ_NAME

  ensure_game_obj(game_obj)
  
  if delay_ms < 0:
    raise ValueError("delay_ms must be >= 0")
  if not game_obj:
    raise ValueError("game object name must not be null")

  gid = ensure_game_obj(game_obj)  # your existing registrar / resolver

  waapi_call(
    "ak.soundengine.postEvent",
    {"event": event_name, "gameObject": gid},
    due_in=delay_ms / 1000.0,   # schedule via dispatcher
    wait=False                  # fire-and-forget
    )

def stop_event(
    event_name: str,
    *, 
    obj: str = "Global",
    fade_ms: int = 100) -> None:

    """
    Stops all voices started by `event_name` on `obj`.
    Uses Wwise's ExecuteActionOnEvent WAAPI call.
    """
    gid = ensure_game_obj(obj)

    waapi_call("ak.soundengine.executeActionOnEvent", {     
        "event": event_name,
        "actionType": 0,            # 'pause', 'resume', 'stop'…
        "gameObject": gid,
        "transitionDuration": fade_ms,
        "fadeCurve": 0
    })

# ==============================================================================
#              Creating Game Syncs (States, Switches, Rtpcs) in Wwise
# ==============================================================================

def create_rtpc(
    name: str,
    parent: str = "\\Game Parameters\\Default Work Unit",
    vmin: float = 0.0,
    vmax: float = 100.0,
    default: float | None = None,
    on_conflict: str = "rename") -> dict:
    
    """
    Make a Game Parameter (RTPC) under the Game Parameters hierarchy.

    Returns the WAAPI object dict (id, name, path, etc.).
    """
    # 1) Create the Game Parameter object
    created = waapi_call("ak.wwise.core.object.create", {
        "parent": parent,             
        "type": "GameParameter",
        "name": name,
        "onNameConflict": on_conflict 
    })
    obj = created.get("return", created)  
    gid = obj["id"]

    # 2) Set its numeric range
    payload = {
    "object": gid,         # GUID string or full object path
    "min": float(vmin),
    "max": float(vmax),
    "onCurveUpdate": "stretch"   # or "stretch" / "crop"
    }

    waapi_call("ak.wwise.core.gameParameter.setRange",payload)

    # 3) Set a default value
    if default is not None:
        waapi_call("ak.wwise.core.object.setProperty", {
            "object": gid,
            "property": "InitialValue",  
            "value": float(default)
        })

    return obj

def create_switch_or_state_types(
    name: str, 
    parent_path: str, 
    type : str, # Switch, SwitchGroup, State, StateGroup
    on_conflict: str = "rename") -> dict:
    
    return waapi_call("ak.wwise.core.object.create", {
        "parent": parent_path,
        "type": type,
        "name": name,
        "onNameConflict": on_conflict
    })

# ==============================================================================
#         Game Syncs (States, Switches, Rtpcs) Setters in Wwise
# ==============================================================================

def set_state( 
    state_group: str, 
    state_name: str, 
    delay_ms: int
) -> None:
    
    """
    Sets `state_name` in the specified 'state group' in the wwise project
    """

    waapi_call("ak.soundengine.setState", {
        "stateGroup": state_group,   
        "state": state_name,
        }, 
        due_in=delay_ms/1000.0,
        wait=False
    )

def set_switch( 
    switch_group: str, 
    switch_name: str,
    delay_ms: int, 
    *,
    obj: str = "Global"
) -> None:
    
    """
    Sets `switch_name` in the specified 'switch_group'
    """

    gid = ensure_game_obj(obj) 

    waapi_call("ak.soundengine.setSwitch", {
        "switchGroup": switch_group,   
        "switchState": switch_name,
        "gameObject" : gid
        }, 
        due_in=delay_ms/1000.0,
        wait=False
    )

def set_rtpc( 
    rtpc_name: str,
    value: float,
    *,
    obj: str = "Global"
) -> None:
    
    """
    Sets `rtpc_name` on `obj`.
    • duration_ms > 0  -> smooth ramp
    • obj="Global"     -> global scope (id 0)
    """
    
    gid = ensure_game_obj(obj)            

    waapi_call("ak.soundengine.setRTPCValue", {
        "rtpc":              rtpc_name,  
        "value":             value,
        "gameObject":        gid
    })

def ramp_rtpc(
    rtpc, 
    start, 
    end, 
    duration_ms,
    *, 
    obj="Global", 
    step_ms=50):
    
    """
    Schedules an RTPC ramp via the dispatcher over a defined duration in milliseconds.
    """

    if duration_ms < 0:
        raise ValueError("duration_ms must be >= 0")

    gid = ensure_game_obj(obj)

    # Edge case: zero duration -> just set final value immediately
    if duration_ms == 0:
        waapi_call("ak.soundengine.setRTPCValue",
                   {"rtpc": rtpc, "value": end, "gameObject": gid},
                   wait=False)
        return

    dur_s  = duration_ms / 1000.0
    dt_s   = max(0.001, step_ms / 1000.0)
    steps  = max(1, math.ceil(dur_s / dt_s))

    # Linear ramp
    for i in range(steps + 1):
        t = i / steps
        value = start + (end - start) * t
        waapi_call("ak.soundengine.setRTPCValue",
                   {"rtpc": rtpc, "value": value, "gameObject": gid},
                   due_in=t * dur_s,   # schedule relative to now
                   wait=False)         # fire-and-forget

# ==============================================================================
#          Game Syncs (States, Switches, Rtpcs) Getters
# ==============================================================================

GAME_PARAM_ROOT  = r"\Game Parameters"
RTPC_TYPE       = ["GameParameter"]

SWITCH_ROOT = r"\Switches"
SWITCH_GROUP_TYPES = ["SwitchGroup"]
SWITCH_TYPE = ["Switch"]

STATE_ROOT  = r"\States"
STATE_GROUP_TYPES = ["StateGroup"]
STATE_TYPE  = ["State"]

def list_gamesync_names(root : str, type : list[str], filter_spec: str | None = None) -> list[str]:
    """
    Return the *names* of all Game Sync objects in the \\Game Syncs tree.

    Parameters
    ----------
    client       : WaapiClient
    root         : str
    type         : list[str]
    filter_spec  : str | None
        • None / ""               → every RTPC in the project
        • absolute path           → e.g. r"\\Game Parameters\\Vehicle" (descendants only)
        • name fragment           → fuzzy-matches names anywhere in \\Game Parameters
    

    Returns
    -------
    list[str]   – Game Sync object names (may be empty).

    Raises
    ------
    RuntimeError  – if the WAAPI query fails.
    """
    spec = (filter_spec or "").strip()

    # Decide the subtree and optional name filter
    if spec.startswith("\\"):                 # absolute path
        start_path = spec.rstrip("\\")
        name_cond  = ""
    elif spec:                                # just a name fragment
        start_path = root
        name_cond  = spec
    else:                                     # no filter → entire tree
        start_path = root
        name_cond  = ""

    transform = [{"select": ["descendants"]}]
    if name_cond:
        transform.append({"where": ["name:matches", name_cond]})
    transform.append({"where": ["type:isIn", type]})

    query_args = {"from": {"path": [start_path]}, "transform": transform, "options": {"return": ["name"]}}

    res = waapi_call("ak.wwise.core.object.get", query_args)
    if not res or "return" not in res:
        raise RuntimeError("WAAPI call failed or returned no data")

    return [obj["name"] for obj in res["return"]]

def list_all_rtpc_names(filter_spec: str | None = None) -> list[str]:
    return list_gamesync_names(GAME_PARAM_ROOT, RTPC_TYPE, filter_spec)

def get_all_gamesync_types(
    root_path: str,
    gamesync_child_types: list[str],
    filter_spec: str | None = None,
    *,
    include_path: bool = False
) -> list[dict]:
    """
    Returns a list like:
        [{"id": "<GUID>", "name": "<ChildName>"}]            (default)
        or [{"id": ..., "name": ..., "path": "..."}] if include_path=True
    """
    spec = (filter_spec or "").strip()

    # Build transform
    transform: list[dict] = [
        {"select": ["descendants"]},
        {"where": ["type:isIn", gamesync_child_types]},
    ]
    if spec:
        # substring match; switch to name:matches if you want regex
        transform.insert(1, {"where": ["name:contains", spec]})

    args = {
        "from": {"path": [root_path]},
        "transform": transform,
    }
    ret_fields = ["id", "name"] + (["path"] if include_path else [])
    opts = {"return": ret_fields}

    res = waapi_call("ak.wwise.core.object.get", args, options=opts)

    items = (res or {}).get("return")
    if not items:
        # Make the failure explicit so callers can handle it
        raise RuntimeError("WAAPI ak.wwise.core.object.get returned no 'return' field")

    # Filter out any partial objects defensively
    out = []
    for o in items:
        _id = o.get("id")
        _name = o.get("name")
        if not (_id and _name):
            continue
        if include_path:
            _path = o.get("path")
            if not _path:
                continue
            out.append({"id": _id, "name": _name, "path": _path})
        else:
            out.append({"id": _id, "name": _name})
    return out

def get_parent_map_for_gamesync_child_ids(gamesync_child_ids: Iterable[str]) -> dict[str, tuple[str, str] | None]:
    """
    For each child_id, returns (parent_id, parent_name).
    If a parent can't be resolved, value is None for that key.
    Tries a fast batch call first; falls back to per-ID select if needed.
    """
    gamesync_child_ids = [sid for sid in gamesync_child_ids if sid]  # normalize
    if not gamesync_child_ids:
        return {}

    parent_map: dict[str, tuple[str, str] | None] = {}
    
    # per-ID, select the parent then read its fields ----------
    for sid in gamesync_child_ids:
        try:
            args = {
                "from": {"id": [sid]},
                "transform": [
                    {"select": ["parent"]}  # move selection to the parent object
                ],
            }
            # ask for id + name (type/path optional if your build returns them)
            opts = {"return": ["id", "name"]}
            res = waapi_call("ak.wwise.core.object.get", args, opts)
            items = (res or {}).get("return", [])

            if items:
                parent_id = items[0].get("id")
                parent_nm = items[0].get("name")
                if parent_id and parent_nm:
                    parent_map[sid] = (parent_id, parent_nm)
                    continue

            parent_map[sid] = None  # couldn't resolve
        except Exception:
            parent_map[sid] = None

    return parent_map

def build_state_groups_from_list(gamesync_children : list[dict], parent_map : dict[str, tuple[str, str] | None])-> dict[str, str] : 
    groups: dict[str, list[str]] = {}
    
    for s in gamesync_children:
        sid, sname = s["id"], s["name"]
        parent = parent_map.get(sid)
        if parent is None:
            continue
        _, gname = parent
        groups.setdefault(gname, []).append(sname)

    result = [[gname, *sorted(snames, key=str.casefold)]
            for gname, snames in groups.items()]
    result.sort(key=lambda row: row[0].casefold())

    return result 

def get_all_gamesyncgroups_and_gamesyncs_grouped(root_path : str, gamesync_child_types : list[str]) -> dict[str, list[str]]:
    """
    Returns {StateGroupName: [StateName, ...]}.
    """
    gamesyncs = get_all_gamesync_types(root_path, gamesync_child_types)
    parent_map = get_parent_map_for_gamesync_child_ids([s["id"] for s in gamesyncs])
    groups: dict[str, list[str]] = {}

    for s in gamesyncs:
        parent = parent_map.get(s["id"])
        if not parent:
            continue
        _, gname = parent
        groups.setdefault(gname, []).append(s["name"])

    for g in groups:
        groups[g].sort(key=str.casefold)
    return groups

def get_all_stategroups_and_states_grouped(): 
   return get_all_gamesyncgroups_and_gamesyncs_grouped(STATE_ROOT, STATE_TYPE)

def get_all_switchgroups_and_switches_grouped(): 
   return get_all_gamesyncgroups_and_gamesyncs_grouped(SWITCH_ROOT, SWITCH_TYPE)

# ==============================================================================
#                      Wwise Object Getters
# ==============================================================================

def get_selected_objects() -> list[dict]:
    """
    Fetch currently selected objects in Wwise.
    
    Returns:
        list[dict]: List of selected object dictionaries. Empty list if nothing selected.
        
    Raises:
        WwiseApiError: If the WAAPI call fails.
    """
    operation = "ak.wwise.ui.getSelectedObjects"
    
    try:
        response = waapi_call(operation, {})
        
        if not isinstance(response, dict):
            raise WwiseApiError(
                f"WAAPI returned unexpected type: {type(response).__name__}",
                operation=operation,
                details={"response_type": type(response).__name__}
            )

        objs = response.get("objects", [])
        
        if not isinstance(objs, list):
            raise WwiseApiError(
                f"'objects' field is not a list: {type(objs).__name__}",
                operation=operation,
                details={"objects_type": type(objs).__name__}
            )
        
        return objs
    
    except (WwisePyLibError):
        raise
    
    except Exception as e:
        raise WwiseApiError(
            f"Unexpected error: {str(e)}",
            operation=operation,
            details={
                "error_type": type(e).__name__,
                "error_message": str(e)
            }
        ) from e

def get_fields_from_objects(
    object_ids: list[str], 
    fields: list[str]
) -> list[dict]:
    """
    Retrieve specified fields from Wwise objects given their IDs.
    
    Args:
        object_ids: List of Wwise object GUIDs.
        fields: List of field names to retrieve (e.g., ['name', 'type', 'path']).
        'children' field is automatically filtered out.
    
    Returns:
        list[dict]: List of objects with requested fields.
        
    Raises:
        WwiseValidationError: If object_ids or fields are empty.
        WwiseApiError: If the WAAPI call fails.
    """
    if not object_ids:
        raise WwiseValidationError("object_ids list cannot be empty")
    
    if not fields:
        raise WwiseValidationError("fields list cannot be empty")
    
    # Filter out 'children' field as it's not supported in this context
    clean_fields = [f for f in fields if f.lower() != "children"]
    
    if not clean_fields:
        raise WwiseValidationError(
            "No valid fields remaining after filtering (only 'children' was provided)"
        )
    
    args = {
        "from": {"id": object_ids},
        "options": {"return": clean_fields}
    }
    
    try:
        response = waapi_call("ak.wwise.core.object.get", args)
        
        if response is None:
            raise WwiseApiError(
                "WAAPI returned None when fetching object fields",
                operation="ak.wwise.core.object.get",
                details={"object_ids": object_ids, "fields": clean_fields}
            )
        
        return response.get("return", [])
    
    except WwisePyLibError:
        raise
    
    except Exception as e:
        raise WwiseApiError(
            f"Unexpected error fetching object fields: {str(e)}",
            operation="ak.wwise.core.object.get",
            details={
                "error_type": type(e).__name__,
                "object_ids": object_ids,
                "fields": clean_fields
            }
        )

def get_object_at_path(path: str) -> dict:
    """
    Retrieve a Wwise object by its full path.
    
    Args:
        path: Full Wwise object path (e.g., '\\Actor-Mixer Hierarchy\\Default Work Unit\\MySound').
    
    Returns:
        dict: Object info containing 'id', 'name', 'type', and 'path' fields.
        
    Raises:
        WwiseValidationError: If path is empty or invalid.
        WwiseObjectNotFoundError: If no object exists at the specified path.
        WwiseApiError: If the WAAPI call fails.
    """
    if not path or not path.strip():
        raise WwiseValidationError("Object path cannot be empty")
    
    args = {
        "from": {"path": [path]},
        "options": {"return": ["id", "name", "type", "path"]}
    }
    
    try:
        response = waapi_call("ak.wwise.core.object.get", args)
        
        if response is None:
            raise WwiseApiError(
                "WAAPI returned None when retrieving object by path",
                operation="ak.wwise.core.object.get",
                details={"path": path}
            )
        
        objects = response.get("return", [])
        
        if not objects:
            raise WwiseObjectNotFoundError(
                f"No object found at path: {path}",
                path=path
            )
        
        return objects[0]
    
    except WwisePyLibError:
        raise
    
    except Exception as e:
        raise WwiseApiError(
            f"Unexpected error retrieving object at path: {str(e)}",
            operation="ak.wwise.core.object.get",
            details={
                "error_type": type(e).__name__,
                "path": path
            }
        )

# ==============================================================================
#                   Editing Objects in Wwise 
# ==============================================================================

def rename_objects(
    objects: list[dict], 
    names: list[str]
) -> list[str]:
    """
    Rename multiple Wwise objects.
    
    Note: This operation is NOT atomic. If a failure occurs, all previous
    renames will have succeeded. The returned list contains IDs of 
    successfully renamed objects before the failure.

    Args:
        objects: List of Wwise object dicts (must contain 'id' field).
        names: List of new names corresponding to each object.
    
    Returns:
        list[str]: List of object IDs that were successfully renamed.
        
    Raises:
        WwiseValidationError: If inputs are invalid or mismatched lengths.
        WwiseApiError: If any rename operation fails.
    """
    if not objects:
        raise WwiseValidationError("objects list cannot be empty")
    
    if not names:
        raise WwiseValidationError("names list cannot be empty")
    
    if len(objects) != len(names):
        raise WwiseValidationError(
            f"Mismatch between objects ({len(objects)}) and names ({len(names)}) count"
        )
    
    # Validate all objects have 'id' field before attempting any operations
    for i, obj in enumerate(objects):
        if not isinstance(obj, dict) or "id" not in obj:
            raise WwiseValidationError(
                f"Object at index {i} is missing 'id' field"
            )
    
    result: list[str] = []
    
    for i, (obj, new_name) in enumerate(zip(objects, names)):
        try:
            response = waapi_call(
                "ak.wwise.core.object.setName",
                {"object": obj["id"], "value": new_name}
            )
            
            # Assuming the response contains the object ID on success
            result.append(obj["id"])
        
        except WwisePyLibError:
            raise
        
        except Exception as e:
            raise WwiseApiError(
                f"Failed to rename object at index {i}: {str(e)}",
                operation="ak.wwise.core.object.setName",
                details={
                    "error_type": type(e).__name__,
                    "object_id": obj["id"],
                    "new_name": new_name,
                    "index": i
                }
            )
    
    return result

def set_reference(
    object_path: str,
    reference_name: str,
    value: str
) -> None:
    """
    Sets the reference of the object given object's path and value.

    Parameters
    ----------
    object_path : str
        path to the object in Wwise
    reference_name : str
        The WAAPI / WAQL reference name - e.g. 'Attenuation'
    value : str
       The path to the reference to.
    """
    if not object_path: 
        raise ValueError("You must specify the object paths to set reference for")

    return waapi_call(
        "ak.wwise.core.object.setReference",
        {"object": object_path, 
            "reference": reference_name, 
            "value": value},
        options={"return": ["id", "name", "path", "type"]},
    )

def set_property(
    object_path: str,
    property_name: str,
    value: int | bool | str
) -> None:
    """
    Sets the property of the object given object's path.

    Parameters
    ----------
    object_path : str
        path to the object in Wwise
    property_name : str
        The WAAPI / WAQL property name - e.g. 'IsStreamingEnabled',
        'IsLoopingEnabled', 'UseGameAuxSends', ...
    value : int, bool, str
        What to set the property to.
    """
    if not object_path: 
        raise ValueError("You must specify the object paths to randomize")

    return waapi_call(
        "ak.wwise.core.object.setProperty",
        {"object": object_path, 
            "property": property_name, 
            "value": value})

def move_object_by_path(source_path: str, dst_path: str):
    """
    Move an object (by its path) to a new parent (by path).
    If use_ids=True, it resolves to GUIDs via your view["meta"] for robustness.
    Returns the WAAPI move result dict (id,name,path).
    """

    src_obj = get_object_at_path(source_path)
    if not src_obj: 
        raise ValueError(f"Source path not found: {source_path}")
    src_id = src_obj["id"]

    dst_obj = get_object_at_path(dst_path)
    if not dst_obj: 
        raise ValueError(f"Destination path not found: {dst_path}")
    dst_id = dst_obj["id"]

    res = waapi_call("ak.wwise.core.object.move", args={"object": src_id, "parent": dst_id})

    if not isinstance(res, dict):
        raise RuntimeError(f"Move failed: {res}")

    # res only contains id and name. 
    moved_id = res["id"]   
    moved = waapi_call(
    "ak.wwise.core.object.get",
    args={"from": {"id": [moved_id]}},                     
    options={"options": {"return": ["id", "name", "path"]}},
    )

    return moved

# ==============================================================================
#           Resolving Path Structures in Wwise
# ==============================================================================

def fetch_nodes(parent_path : str) -> str:
    return_fields = ["id","name","path"]
    
    # 1) Grab the parent root (this returns exactly one object)
    args1 = {"from": { "path": [parent_path]}}
    opts1 = {"return": return_fields }
    root_res = waapi_call("ak.wwise.core.object.get", args1, opts1)

    root_list = root_res.get("return", [])
    root = root_list[0] if root_list else None

    # 2) Get all descendants (single selector only)
    args2 = {"from": { "path": [parent_path] }, "transform": [{"select": ["descendants"]}]}
    opts2 = {"return": return_fields}
    desc_res = waapi_call("ak.wwise.core.object.get", args2, opts2)
    descendants = desc_res.get("return", [])

    # 3) Combine (root + descendants)
    return ([root] if root else []) + descendants

# ==============================================================================
#              Importing Audio Files into Wwise
# ==============================================================================

AUDIO_EXTS = {".wav", ".aiff", ".aif", ".ogg"} 

def import_audio_files(
    source_files: list[str],
    destination_paths: list[str],
    *,
    language: str = "SFX",
    originals_sub: str = "SFX",
    import_operation: str = "useExisting",  # "createNew" / "replaceExisting" also valid
) -> list[dict]:
    """
    Import specific audio files into Wwise using WAAPI.

    :param source_files: List of file system paths to audio files.
    :param destination_paths: List of Wwise object paths (same length as source_files).
                              e.g. "\\Actor-Mixer Hierarchy\\Default Work Unit\\SFX\\Gun\\Shot_01"
    :param language: Wwise importLanguage (default "SFX").
    :param originals_sub: Originals subfolder (e.g. "SFX").
    :param import_operation: "useExisting", "createNew", or "replaceExisting".
    :return: List of WAAPI objects returned by the import.
    """

    if len(source_files) != len(destination_paths):
        raise ValueError("source_files and destination_paths must have the same length")

    imports: list[dict] = []

    for src, dest in zip(source_files, destination_paths):
        # --- normalize & validate source file path ---
        src_path = Path(src).expanduser().resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"Source file does not exist: {src_path}")

        if src_path.suffix.lower() not in AUDIO_EXTS:
            raise ValueError(f"Not a supported audio file: {src_path}")

        # --- normalize destination Wwise object path ---
        # ensure exactly one leading backslash, no trailing backslash
        object_path = "\\" + dest.strip("\\")

        imports.append(
            {
                "audioFile": str(src_path),
                "objectPath": object_path,
            }
        )

    if not imports:
        raise ValueError("No valid audio files provided")

    # --- WAAPI call ---
    args = {
        "importOperation": import_operation,  # "useExisting" / "createNew" / "replaceExisting"
        "default": {
            "importLanguage": language,
            "objectType": "Sound",
            "originalsSubFolder": originals_sub,
        },
        "imports": imports,
    }

    res = waapi_call(
        "ak.wwise.core.audio.import",
        args,
        options={"return": ["id", "name", "path"]},
    )

    return res["objects"]   

def list_audio_files_at_path_file_explorer(
    root_path : str,
    *, 
    recurse: bool = True,
    include_hidden: bool = False
) -> list[str]:
    
    """Return audio files under *root* that would be considered by import_audio()."""

    root_path = Path(root_path).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(root_path)

    it: Iterable[Path] = root_path.rglob("*") if recurse else root_path.iterdir()

    def is_hidden(p: Path) -> bool:
        # cross-platform-ish hidden check (dotfiles). Windows attributes need extra work if you care.
        return any(part.startswith(".") for part in p.parts)

    files: list[str] = []

    for p in it:
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            if include_hidden or not is_hidden(p):
                files.append(p)
    return files

# ==============================================================================
#                   Creating Objects in Wwise
# ==============================================================================

def create_object(
    parent_id: str,
    child_name: str,
    child_type: str, 
    on_conflict: str = "rename"
) -> dict:
   
    """
    Creates the specified object type under `parent_path`.

    Returns the GUID (string) of the newly-created object.
    """
    try:  
        res: dict = []
        res = waapi_call(
                "ak.wwise.core.object.create",
                {
                 "parent": parent_id,          # WAQL or back-slash path
                 "type":   child_type,           # always "WorkUnit" for both cases
                 "name":   child_name,           # requested name for new work or folder 
                 "onNameConflict": on_conflict   # "fail", "rename", "replace", "merge") 
                }
        )
        return res   
    
    except Exception as e:
        raise RuntimeError(f"WAAPI error: {e}")

# ==============================================================================
#           Property Names & Valid Ranges for different Wwise Objects
# ==============================================================================

RANDOM_CONTAINER_PROPERTY_HELP = """
Random Container (WAAPI property names)

Play Type — RandomOrSequence  (0=Sequence, 1=Random)
Random Type — NormalOrShuffle  (0=Shuffle, 1=Standard)
Play Mode — PlayMechanismStepOrContinuous  (0=Continuous, 1=Step)
Loop — PlayMechanismLoop  (bool)
Infinite Looping — PlayMechanismInfiniteOrNumberOfLoops  (0=No. of Loops, 1=Infinite)
No. of Loops — PlayMechanismLoopCount  (int)
Always Reset Playlist — PlayMechanismResetPlaylistEachPlay  (bool)
Transitions (Enable) — PlayMechanismSpecialTransitions  (bool)
Transition Type — PlayMechanismSpecialTransitionsType  (0=Xfade (amp), 4=Xfade (power), 1=Delay, 2=Sample accurate, 3=Trigger rate)
Transition Duration — PlayMechanismSpecialTransitionsValue  (seconds)
At End of Playlist — RestartBeginningOrBackward  (0=Play in reverse order, 1=Restart)
Limit Repetition — RandomAvoidRepeating  (bool)
Limit Repetition To — RandomAvoidRepeatingCount  (int)

"""

ATTENUATION_PROPERTY_HELP = """
Attenuation (WAAPI property names)

Radius Max — RadiusMax
  • Maximum distance of the attenuation (world units).
  • Real64, default 100.0, range [1, 100000000].

Cone Use — ConeUse
  • Enable/disable cone attenuation.
  • bool.

Cone max attenuation — ConeAttenuation
  • Additional attenuation applied outside the cone.
  • Real64 (dB), default -6.0, range [-200, 0].

Cone inner angle — ConeInnerAngle
  • Inner cone angle in degrees.
  • int32, default 90, range [0, 360].

Cone outer angle — ConeOuterAngle
  • Outer cone angle in degrees.
  • int32, default 245, range [0, 360].

Cone LPF — ConeLowPassFilterValue
  • Low-pass filter applied outside the cone.
  • int32, range [0, 100].

Cone HPF — ConeHighPassFilterValue
  • High-pass filter applied outside the cone.
  • int32, range [0, 100].

Height Spread — HeightSpreadEnable
  • Enable height spread behavior.
  • bool.

OverrideColor - OverrideColor
  • Set this property to true first or setting Color will not work. 
  • bool [True, False]

Color — Color
  • UI color index for the attenuation object. Make sure OverrideColor is set to True first!
  • int16, default 0, range [0, 26].

RTPC List — RTPC
  • RTPC list on the attenuation object.
  • List of RTPC objects; manipulated via ak.wwise.core.object.set / setAttenuationCurve.
"""

SOUND_PROPERTY_HELP = """
Sound (WAAPI property names)

--- Positioning / Attenuation ----------------------------------------

3D Position — 3DPosition
  • 0 = Emitter
  • 1 = Emitter with Automation
  • 2 = Listener with Automation

3D Spatialization — 3DSpatialization
  • 0 = None
  • 1 = Position
  • 2 = Position + Orientation

Attenuation (ShareSet / Custom) — Attenuation
  • Reference to an Attenuation object (ShareSet or custom instance).

Distance Scaling % — AttenuationDistanceScaling
  • Scale for attenuation distances.
  • Real32, default 1.0, range [0.01, 100].

Enable Attenuation — EnableAttenuation
  • Toggle use of attenuation on this Sound.
  • bool.

Listener Relative Routing — ListenerRelativeRouting
  • Required to use Attenuation, game/aux sends, etc.
  • bool.

Hold Emitter Position and Orientation — HoldEmitterPositionOrientation
  • Lock emitter transform while playing.
  • bool.

Hold Listener Orientation — HoldListenerOrientation
  • Lock listener orientation relative to emitter.
  • bool.


--- Core Mixing (per-Sound voice) -----------------------------------

Voice Volume — Volume
  • dB gain at the voice.
  • Real64, range [-200, 200].

Voice LPF — Lowpass
  • Voice low-pass filter.
  • int16, range [0, 100].

Voice HPF — Highpass
  • Voice high-pass filter.
  • int16, range [0, 100].

Make-Up Gain — MakeUpGain
  • Extra gain used with HDR envelope.
  • Real64, range [-96, 96].


--- Playback / Looping / Limits -------------------------------------

Initial Delay — InitialDelay
  • Delay before playback (seconds).
  • Real64, range [0, 3600].

Loop — IsLoopingEnabled
  • Enable/disable looping.
  • bool.

Infinite Loop — IsLoopingInfinite
  • If true, loop indefinitely; otherwise use LoopCount.
  • bool.

No. of Loops — LoopCount
  • Number of loops when Infinite is off.
  • int32, default 2, range [1, 32767].

Virtual Voice Behavior — BelowThresholdBehavior
  • 0 = Continue to play
  • 1 = Kill voice
  • 2 = Send to virtual voice
  • 3 = Kill if finite else virtual

Limitation Scope — IsGlobalLimit
  • 0 = Per game object
  • 1 = Globally

Limit Sound Instances (Enable) — UseMaxSoundPerInstance
  • Toggle instance limiting.
  • bool.

Sound Instance Limit — MaxSoundPerInstance
  • Max simultaneous voices (when limiting enabled).
  • int16, default 50, range [1, 1000].

When Priority is Equal — MaxReachedBehavior
  • 0 = Discard oldest instance
  • 1 = Discard newest instance

On Return to Physical Voice — VirtualVoiceQueueBehavior
  • 0 = Play from beginning
  • 1 = Play from elapsed time
  • 2 = Resume


--- Streaming / Voice Behavior --------------------------------------

Stream — IsStreamingEnabled
  • Use streaming for this source.
  • bool.

Non-Cachable — IsNonCachable
  • Prevents caching converted media.
  • bool.

Zero Latency — IsZeroLatency
  • Bypass look-ahead / scheduling to minimize latency.
  • bool.

Is Voice — IsVoice
  • Mark as a voice (affects certain profiling/mixing behavior).
  • bool.


--- Routing / Busses / Reflections ----------------------------------

Output Bus — OutputBus
  • Bus reference used by this Sound.
  • Reference type: Bus.

Early Reflections Aux Send — ReflectionsAuxSend
  • Aux bus used for early reflections.
  • Reference type: AuxBus.

Early Reflections Send Volume — ReflectionsVolume
  • Send level to ReflectionsAuxSend.
  • Real64, range [-200, 200].


--- Aux Sends (Game-defined) ----------------------------------------

Use Game-Defined Auxiliary Sends — UseGameAuxSends
  • Enable routing to game-defined aux sends.
  • bool.

Game Aux Sends Volume — GameAuxSendVolume
  • Master volume for game-defined sends.
  • Real64, range [-200, 200].

Game Aux Sends LPF — GameAuxSendLPF
  • Low-pass on game-defined sends.
  • int16, range [0, 100].

Game Aux Sends HPF — GameAuxSendHPF
  • High-pass on game-defined sends.
  • int16, range [0, 100].


--- Aux Sends (User-defined 0-3) ------------------------------------

User Aux Send 0-3 — UserAuxSend0..3
  • Per-slot aux bus references.
  • Type: AuxBus.

User Aux Volume 0-3 — UserAuxSendVolume0..3
  • Send volume per aux slot.
  • Real64, range [-200, 200].

User Aux LPF 0-3 — UserAuxSendLPF0..3
  • Low-pass per aux slot.
  • int16, range [0, 100].

User Aux HPF 0-3 — UserAuxSendHPF0..3
  • High-pass per aux slot.
  • int16, range [0, 100].


--- HDR & Loudness Normalization ------------------------------------

HDR Active Range — HdrActiveRange
  • HDR window range in dB.
  • Real64, range [0, 96].

Enable Envelope Tracking — HdrEnableEnvelope
  • Enables HDR envelope logic.
  • bool.

HDR Envelope Sensitivity — HdrEnvelopeSensitivity
  • Sensitivity of HDR envelope.
  • Real64, range [0, 100].

Enable Loudness Normalization — EnableLoudnessNormalization
  • Toggle loudness normalization.
  • bool.

Loudness Normalization Target — LoudnessNormalizationTarget
  • Target loudness in LUFS.
  • Real64, default -23, range [-96, 0].

Loudness Normalization Type — LoudnessNormalizationType
  • 0 = Integrated
  • 1 = Momentary Max


--- Misc -------------------------------------------------------------

Inclusion — Inclusion
  • Whether this object is included in the SoundBank generation.
  • bool.

OverrideColor - OverrideColor
    • Set this property to true first or setting Color will not work. 
    • bool [True, False]

Color — Color
  • UI color index for the Sound object. Make sure OverrideColor is set to True first!
  • int16, range [0, 26].

Weight — Weight
  • Weight used in containers (Random, Sequence, etc.).
  • Real64, default 50, range [0.001, 100].

Metadata list — Metadata
  • List of Metadata objects associated with this Sound.
"""

def get_all_property_name_valid_values() -> str: 
    return RANDOM_CONTAINER_PROPERTY_HELP + ATTENUATION_PROPERTY_HELP + SOUND_PROPERTY_HELP

# ==============================================================================
#                   Additional WAAPI Wrappers (ak.soundengine)
# ==============================================================================

def soundengine_get_state(state_group: str) -> Any:
    """Get current state of a State Group. Uses ak.soundengine.getState."""
    if not state_group or not str(state_group).strip():
        raise WwiseValidationError("state_group cannot be empty")
    return waapi_call("ak.soundengine.getState", {"stateGroup": state_group})

def soundengine_get_switch(switch_group: str, game_object: int | str) -> Any:
    """Get current switch state for a Game Object. Uses ak.soundengine.getSwitch."""
    if not switch_group or not str(switch_group).strip():
        raise WwiseValidationError("switch_group cannot be empty")
    gid = ensure_game_obj(game_object) if isinstance(game_object, str) else game_object
    return waapi_call("ak.soundengine.getSwitch", {"switchGroup": switch_group, "gameObject": gid})

def soundengine_load_bank(bank_id_or_path: str, **kwargs: Any) -> Any:
    """Load a SoundBank. Uses ak.soundengine.loadBank."""
    if not bank_id_or_path or not str(bank_id_or_path).strip():
        raise WwiseValidationError("bank identifier cannot be empty")
    args: dict[str, Any] = {"soundBank": bank_id_or_path, **kwargs}
    return waapi_call("ak.soundengine.loadBank", args)

def soundengine_post_msg_monitor(message: str, **kwargs: Any) -> Any:
    """Display message in Profiler Capture Log. Uses ak.soundengine.postMsgMonitor."""
    args: dict[str, Any] = {"message": message, **kwargs}
    return waapi_call("ak.soundengine.postMsgMonitor", args)

def soundengine_post_trigger(trigger_name: str, game_object: int | str, **kwargs: Any) -> Any:
    """Post a trigger. Uses ak.soundengine.postTrigger."""
    if not trigger_name or not str(trigger_name).strip():
        raise WwiseValidationError("trigger name cannot be empty")
    gid = ensure_game_obj(game_object) if isinstance(game_object, str) else game_object
    args: dict[str, Any] = {"trigger": trigger_name, "gameObject": gid, **kwargs}
    return waapi_call("ak.soundengine.postTrigger", args)

def soundengine_reset_rtpc_value(rtpc_name: str, game_object: int | str | None = None) -> Any:
    """Reset RTPC to project default. Uses ak.soundengine.resetRTPCValue."""
    if not rtpc_name or not str(rtpc_name).strip():
        raise WwiseValidationError("rtpc name cannot be empty")
    args: dict[str, Any] = {"rtpc": rtpc_name}
    if game_object is not None:
        args["gameObject"] = ensure_game_obj(game_object) if isinstance(game_object, str) else game_object
    return waapi_call("ak.soundengine.resetRTPCValue", args)

def soundengine_seek_on_event(event_name: str, game_object: int | str, position_ms: int, **kwargs: Any) -> Any:
    """Seek on playing instances of an event. Uses ak.soundengine.seekOnEvent."""
    if not event_name or not str(event_name).strip():
        raise WwiseValidationError("event name cannot be empty")
    gid = ensure_game_obj(game_object) if isinstance(game_object, str) else game_object
    args: dict[str, Any] = {"event": event_name, "gameObject": gid, "position": position_ms, **kwargs}
    return waapi_call("ak.soundengine.seekOnEvent", args)

def soundengine_set_game_object_aux_send_values(game_object: int | str, aux_send_values: list[dict], **kwargs: Any) -> Any:
    """Set aux send values for a game object. Uses ak.soundengine.setGameObjectAuxSendValues."""
    gid = ensure_game_obj(game_object) if isinstance(game_object, str) else game_object
    args: dict[str, Any] = {"gameObject": gid, "auxSendValues": aux_send_values, **kwargs}
    return waapi_call("ak.soundengine.setGameObjectAuxSendValues", args)

def soundengine_set_game_object_output_bus_volume(
    game_object: int | str,
    bus_id_or_path: str,
    volume: float,
    *,
    listener_id: int | str | None = None,
    **kwargs: Any,
) -> Any:
    """Set output bus volume for a game object. Uses ak.soundengine.setGameObjectOutputBusVolume.
    Schema expects controlValue, emitter, listener. We map: emitter=game_object, controlValue=volume,
    listener=listener_id (optional). bus_id_or_path is passed as controlValue context if needed."""
    gid = ensure_game_obj(game_object) if isinstance(game_object, str) else game_object
    args: dict[str, Any] = {"emitter": gid, "controlValue": volume, **kwargs}
    if listener_id is not None:
        args["listener"] = listener_id
    return waapi_call("ak.soundengine.setGameObjectOutputBusVolume", args)

def soundengine_set_listener_spatialization(
    listener_id: int,
    channel_config: int | list,
    volume_offsets: list[float],
    spatialized: bool,
    **kwargs: Any,
) -> Any:
    """Set listener spatialization. Uses ak.soundengine.setListenerSpatialization.
    Schema: listener, channelConfig, volumeOffsets, spatialized."""
    args: dict[str, Any] = {
        "listener": listener_id,
        "channelConfig": channel_config,
        "volumeOffsets": volume_offsets,
        "spatialized": spatialized,
        **kwargs,
    }
    return waapi_call("ak.soundengine.setListenerSpatialization", args)

def soundengine_set_multiple_positions(
    game_object: int | str,
    positions: list[dict],
    multi_position_type: int = 0,
    **kwargs: Any,
) -> Any:
    """Set multiple positions for a game object. Uses ak.soundengine.setMultiplePositions.
    Schema requires multiPositionType (e.g. 0=MultiPositionType_SingleSource)."""
    gid = ensure_game_obj(game_object) if isinstance(game_object, str) else game_object
    args: dict[str, Any] = {
        "gameObject": gid,
        "positions": positions,
        "multiPositionType": multi_position_type,
        **kwargs,
    }
    return waapi_call("ak.soundengine.setMultiplePositions", args)

def soundengine_set_object_obstruction_and_occlusion(
    game_object: int | str,
    obstruction: float,
    occlusion: float,
    listener_id: int | str | None = None,
    **kwargs: Any,
) -> Any:
    """Set obstruction and occlusion. Uses ak.soundengine.setObjectObstructionAndOcclusion.
    Schema: emitter, listener, obstructionLevel, occlusionLevel."""
    gid = ensure_game_obj(game_object) if isinstance(game_object, str) else game_object
    args: dict[str, Any] = {
        "emitter": gid,
        "obstructionLevel": obstruction,
        "occlusionLevel": occlusion,
        **kwargs,
    }
    if listener_id is not None:
        args["listener"] = listener_id
    return waapi_call("ak.soundengine.setObjectObstructionAndOcclusion", args)

def soundengine_set_scaling_factor(game_object: int | str, attenuation_scaling_factor: float) -> Any:
    """Set attenuation scaling factor for a game object. Uses ak.soundengine.setScalingFactor.
    Schema: gameObject, attenuationScalingFactor."""
    gid = ensure_game_obj(game_object) if isinstance(game_object, str) else game_object
    return waapi_call("ak.soundengine.setScalingFactor", {"gameObject": gid, "attenuationScalingFactor": attenuation_scaling_factor})

def soundengine_stop_playing_id(
    playing_id: int,
    transition_duration_ms: int = 0,
    fade_curve: int = 0,
    **kwargs: Any,
) -> Any:
    """Stop a specific playing instance. Uses ak.soundengine.stopPlayingID.
    Schema: playingId, transitionDuration, fadeCurve."""
    return waapi_call("ak.soundengine.stopPlayingID", {
        "playingId": playing_id,
        "transitionDuration": transition_duration_ms,
        "fadeCurve": fade_curve,
        **kwargs,
    })

def soundengine_unload_bank(bank_id_or_path: str, **kwargs: Any) -> Any:
    """Unload a SoundBank. Uses ak.soundengine.unloadBank."""
    if not bank_id_or_path or not str(bank_id_or_path).strip():
        raise WwiseValidationError("bank identifier cannot be empty")
    args: dict[str, Any] = {"soundBank": bank_id_or_path, **kwargs}
    return waapi_call("ak.soundengine.unloadBank", args)

# ==============================================================================
#                   ak.wwise.console.project
# ==============================================================================

def console_project_close() -> Any:
    """Close current project. Uses ak.wwise.console.project.close."""
    return waapi_call("ak.wwise.console.project.close", {})

def console_project_create(path: str, platform: str, **kwargs: Any) -> Any:
    """Create new empty project. Uses ak.wwise.console.project.create."""
    if not path or not str(path).strip():
        raise WwiseValidationError("path cannot be empty")
    if not platform or not str(platform).strip():
        raise WwiseValidationError("platform cannot be empty")
    return waapi_call("ak.wwise.console.project.create", {"path": path, "platforms": [platform], **kwargs})

def console_project_open(path: str, **kwargs: Any) -> Any:
    """Open project by path. Uses ak.wwise.console.project.open."""
    if not path or not str(path).strip():
        raise WwiseValidationError("path cannot be empty")
    return waapi_call("ak.wwise.console.project.open", {"path": path, **kwargs})

# ==============================================================================
#                   ak.wwise.core (getInfo, ping)
# ==============================================================================

def get_info() -> dict:
    """Retrieve global Wwise info. Uses ak.wwise.core.getInfo."""
    return waapi_call("ak.wwise.core.getInfo", {})

def core_ping() -> Any:
    """Verify if WAAPI is available. Uses ak.wwise.core.ping."""
    return waapi_call("ak.wwise.core.ping", {})

# ==============================================================================
#                   ak.wwise.core.audio (remaining)
# ==============================================================================

def audio_convert(*args_waapi: Any, **kwargs: Any) -> Any:
    """Create converted audio file. Uses ak.wwise.core.audio.convert."""
    return waapi_call("ak.wwise.core.audio.convert", kwargs if kwargs else (args_waapi[0] if args_waapi else {}))

def audio_import_tab_delimited(
    import_file: str,
    import_operation: str = "useExisting",
    import_language: str | None = None,
    **kwargs: Any,
) -> Any:
    """Import via tab-delimited file. Uses ak.wwise.core.audio.importTabDelimited.
    Schema: importOperation, importLanguage, importFile (or similar)."""
    if not import_file or not str(import_file).strip():
        raise WwiseValidationError("import_file path cannot be empty")
    args: dict[str, Any] = {"importFile": import_file, "importOperation": import_operation, **kwargs}
    if import_language is not None:
        args["importLanguage"] = import_language
    return waapi_call("ak.wwise.core.audio.importTabDelimited", args)

def audio_mute(object_path: str, value: bool = True) -> Any:
    """Mute an object. Uses ak.wwise.core.audio.mute. Schema: objects, value."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object path cannot be empty")
    return waapi_call("ak.wwise.core.audio.mute", {"objects": [object_path], "value": value})

def audio_reset_mute() -> Any:
    """Unmute all muted objects. Uses ak.wwise.core.audio.resetMute."""
    return waapi_call("ak.wwise.core.audio.resetMute", {})

def audio_reset_solo() -> Any:
    """Unsolo all soloed objects. Uses ak.wwise.core.audio.resetSolo."""
    return waapi_call("ak.wwise.core.audio.resetSolo", {})

def audio_set_conversion_plugin(plugin_id: str, platform: str, conversion: str, **kwargs: Any) -> Any:
    """Set audio conversion plugin. Uses ak.wwise.core.audio.setConversionPlugin.
    Schema: conversion, platform, plugin."""
    if not plugin_id or not str(plugin_id).strip():
        raise WwiseValidationError("plugin id cannot be empty")
    return waapi_call("ak.wwise.core.audio.setConversionPlugin", {
        "plugin": plugin_id,
        "platform": platform,
        "conversion": conversion,
        **kwargs,
    })

def audio_solo(object_path: str, value: bool = True) -> Any:
    """Solo an object. Uses ak.wwise.core.audio.solo. Schema: objects, value."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object path cannot be empty")
    return waapi_call("ak.wwise.core.audio.solo", {"objects": [object_path], "value": value})

def audio_source_peaks_get_min_max_peaks_in_region(
    object_path: str,
    time_from: int,
    time_to: int,
    num_peaks: int = 1,
    **kwargs: Any,
) -> Any:
    """Get min/max peaks in region. Schema: object, timeFrom, timeTo, numPeaks."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object path cannot be empty")
    return waapi_call("ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion", {
        "object": object_path,
        "timeFrom": time_from,
        "timeTo": time_to,
        "numPeaks": num_peaks,
        **kwargs,
    })

def audio_source_peaks_get_min_max_peaks_in_trimmed_region(object_path: str, num_peaks: int = 1, **kwargs: Any) -> Any:
    """Get min/max peaks in trimmed region. Schema: object, numPeaks."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object path cannot be empty")
    return waapi_call("ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInTrimmedRegion", {
        "object": object_path,
        "numPeaks": num_peaks,
        **kwargs,
    })

# ==============================================================================
#                   ak.wwise.core.blendContainer
# ==============================================================================

def blend_container_add_assignment(
    blend_container_path: str,
    blend_track_path: str,
    child_path: str,
    edges: list[dict] | None = None,
    index: int | None = None,
    **kwargs: Any,
) -> Any:
    """Add assignment to a Blend Track. Schema: object, child, edges?, index?."""
    if not blend_container_path or not blend_track_path or not child_path:
        raise WwiseValidationError("blend_container_path, blend_track_path and child_path cannot be empty")
    obj = get_object_at_path(blend_container_path)
    track = get_object_at_path(blend_track_path) if blend_track_path.startswith("\\") else {"id": blend_track_path}
    child = get_object_at_path(child_path) if child_path.startswith("\\") else {"id": child_path}
    args: dict[str, Any] = {"object": obj["id"], "child": child["id"], **kwargs}
    if edges is not None:
        args["edges"] = edges
    if index is not None:
        args["index"] = index
    return waapi_call("ak.wwise.core.blendContainer.addAssignment", args)

def blend_container_add_track(blend_container_path: str, name: str, **kwargs: Any) -> Any:
    """Add Blend Track to Blend Container. Schema: object, name."""
    if not blend_container_path or not str(blend_container_path).strip():
        raise WwiseValidationError("blend_container_path cannot be empty")
    obj = get_object_at_path(blend_container_path)
    return waapi_call("ak.wwise.core.blendContainer.addTrack", {"object": obj["id"], "name": name, **kwargs})

def blend_container_get_assignments(blend_container_path: str, blend_track_path: str | None = None, **kwargs: Any) -> Any:
    """Get assignments of a Blend Track. Uses ak.wwise.core.blendContainer.getAssignments."""
    if not blend_container_path or not str(blend_container_path).strip():
        raise WwiseValidationError("blend_container_path cannot be empty")
    obj = get_object_at_path(blend_container_path)
    args: dict[str, Any] = {"object": obj["id"], **kwargs}
    if blend_track_path:
        track = get_object_at_path(blend_track_path) if blend_track_path.startswith("\\") else {"id": blend_track_path}
        args["blendTrack"] = track["id"]
    return waapi_call("ak.wwise.core.blendContainer.getAssignments", args)

def blend_container_remove_assignment(blend_container_path: str, child_path: str, **kwargs: Any) -> Any:
    """Remove assignment from Blend Container. Schema: object, child."""
    if not blend_container_path or not child_path:
        raise WwiseValidationError("blend_container_path and child_path cannot be empty")
    obj = get_object_at_path(blend_container_path)
    child = get_object_at_path(child_path) if child_path.startswith("\\") else {"id": child_path}
    return waapi_call("ak.wwise.core.blendContainer.removeAssignment", {
        "object": obj["id"],
        "child": child["id"],
        **kwargs,
    })

# ==============================================================================
#                   ak.wwise.core.switchContainer
# ==============================================================================

def switch_container_add_assignment(switch_container_path: str, child_path: str, state_path: str) -> Any:
    """Assign a child of Switch Container to a Switch. Uses ak.wwise.core.switchContainer.addAssignment.
    WAAPI expects child and stateOrSwitch only (container inferred from child parent)."""
    if not switch_container_path or not child_path or not state_path:
        raise WwiseValidationError("switch_container_path, child_path and state_path cannot be empty")
    child = get_object_at_path(child_path)
    state = get_object_at_path(state_path)
    return waapi_call("ak.wwise.core.switchContainer.addAssignment", {
        "child": child["id"],
        "stateOrSwitch": state["id"],
    })

def switch_container_get_assignments(switch_container_path: str) -> Any:
    """Get assignments of a Switch Container. Schema: id (object id)."""
    if not switch_container_path or not str(switch_container_path).strip():
        raise WwiseValidationError("switch_container_path cannot be empty")
    obj = get_object_at_path(switch_container_path)
    return waapi_call("ak.wwise.core.switchContainer.getAssignments", {"id": obj["id"]})

def switch_container_remove_assignment(switch_container_path: str, child_path: str, state_path: str) -> Any:
    """Remove one assignment from Switch Container. Uses ak.wwise.core.switchContainer.removeAssignment.
    WAAPI expects child and stateOrSwitch only (container inferred from child parent)."""
    if not switch_container_path or not child_path or not state_path:
        raise WwiseValidationError("switch_container_path, child_path and state_path cannot be empty")
    child = get_object_at_path(child_path)
    state = get_object_at_path(state_path)
    return waapi_call("ak.wwise.core.switchContainer.removeAssignment", {
        "child": child["id"],
        "stateOrSwitch": state["id"],
    })

# ==============================================================================
#                   ak.wwise.core (executeLuaScript, log, mediaPool)
# ==============================================================================

def execute_lua_script(*, lua_script: str | None = None, lua_string: str | None = None, **kwargs: Any) -> Any:
    """Execute Lua script. Schema requires luaScript (file path or script content)."""
    if not lua_script and not lua_string:
        raise WwiseValidationError("provide lua_script (file path) or lua_string")
    args: dict[str, Any] = dict(kwargs)
    # WAAPI schema expects luaScript (path or content)
    args["luaScript"] = lua_script if lua_script else lua_string
    return waapi_call("ak.wwise.core.executeLuaScript", args)

def log_add_item(channel: str, message: str, **kwargs: Any) -> Any:
    """Add item to log channel. Uses ak.wwise.core.log.addItem."""
    if not channel or not message:
        raise WwiseValidationError("channel and message cannot be empty")
    return waapi_call("ak.wwise.core.log.addItem", {"channel": channel, "message": message, **kwargs})

def log_clear(channel: str) -> Any:
    """Clear log channel. Uses ak.wwise.core.log.clear."""
    if not channel or not str(channel).strip():
        raise WwiseValidationError("channel cannot be empty")
    return waapi_call("ak.wwise.core.log.clear", {"channel": channel})

def log_get(channel: str, **kwargs: Any) -> Any:
    """Get log for channel. Uses ak.wwise.core.log.get."""
    if not channel or not str(channel).strip():
        raise WwiseValidationError("channel cannot be empty")
    return waapi_call("ak.wwise.core.log.get", {"channel": channel, **kwargs})

def media_pool_get(**kwargs: Any) -> Any:
    """Retrieve files from Media Pool. Uses ak.wwise.core.mediaPool.get."""
    return waapi_call("ak.wwise.core.mediaPool.get", kwargs)

def media_pool_get_fields(**kwargs: Any) -> Any:
    """Get fields present in Media Pool. Uses ak.wwise.core.mediaPool.getFields."""
    return waapi_call("ak.wwise.core.mediaPool.getFields", kwargs)

# ==============================================================================
#                   ak.wwise.core.object (remaining)
# ==============================================================================

def object_copy(object_path: str, parent_path: str, **kwargs: Any) -> Any:
    """Copy object to given parent. Uses ak.wwise.core.object.copy."""
    if not object_path or not parent_path:
        raise WwiseValidationError("object_path and parent_path cannot be empty")
    obj = get_object_at_path(object_path)
    parent = get_object_at_path(parent_path)
    return waapi_call("ak.wwise.core.object.copy", {"object": obj["id"], "parent": parent["id"], **kwargs})

def object_delete(object_path: str) -> Any:
    """Delete object. Uses ak.wwise.core.object.delete."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.object.delete", {"object": obj["id"]})

def object_diff(source_path: str, target_path: str, **kwargs: Any) -> Any:
    """Diff source and target objects. Uses ak.wwise.core.object.diff."""
    if not source_path or not target_path:
        raise WwiseValidationError("source_path and target_path cannot be empty")
    src = get_object_at_path(source_path)
    tgt = get_object_at_path(target_path)
    return waapi_call("ak.wwise.core.object.diff", {"source": src["id"], "target": tgt["id"], **kwargs})

def object_get_attenuation_curve(object_path: str, curve_type: str = "Volume", **kwargs: Any) -> Any:
    """Get attenuation curve. Schema: object, curveType."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.object.getAttenuationCurve", {"object": obj["id"], "curveType": curve_type, **kwargs})

def object_get_property_and_reference_names(object_path: str, **kwargs: Any) -> Any:
    """Get property and reference names for object. Uses ak.wwise.core.object.getPropertyAndReferenceNames."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.object.getPropertyAndReferenceNames", {"object": obj["id"], **kwargs})

def object_get_property_info(object_path: str, property_name: str, **kwargs: Any) -> Any:
    """Get property info. Uses ak.wwise.core.object.getPropertyInfo."""
    if not object_path or not property_name:
        raise WwiseValidationError("object_path and property_name cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.object.getPropertyInfo", {"object": obj["id"], "property": property_name, **kwargs})

def object_get_property_names(object_path: str, **kwargs: Any) -> Any:
    """Get property names for object. Uses ak.wwise.core.object.getPropertyNames."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.object.getPropertyNames", {"object": obj["id"], **kwargs})

def object_get_types(**kwargs: Any) -> Any:
    """Get all registered object types. Uses ak.wwise.core.object.getTypes."""
    return waapi_call("ak.wwise.core.object.getTypes", kwargs)

def object_is_linked(object_path: str, property_name: str, platform: str = "Windows", **kwargs: Any) -> Any:
    """Check if property is linked to platform. Schema: object, property, platform (required)."""
    if not object_path or not property_name:
        raise WwiseValidationError("object_path and property_name cannot be empty")
    obj = get_object_at_path(object_path)
    args: dict[str, Any] = {"object": obj["id"], "property": property_name, "platform": platform, **kwargs}
    return waapi_call("ak.wwise.core.object.isLinked", args)

def object_is_property_enabled(object_path: str, property_name: str, platform: str = "Windows", **kwargs: Any) -> Any:
    """Check if property is enabled. Schema: object, property, platform (required)."""
    if not object_path or not property_name:
        raise WwiseValidationError("object_path and property_name cannot be empty")
    obj = get_object_at_path(object_path)
    args: dict[str, Any] = {"object": obj["id"], "property": property_name, "platform": platform, **kwargs}
    return waapi_call("ak.wwise.core.object.isPropertyEnabled", args)

def object_paste_properties(source_path: str, target_paths: list[str], **kwargs: Any) -> Any:
    """Paste properties from source to targets. Schema: source, targets."""
    if not source_path or not target_paths:
        raise WwiseValidationError("source_path and target_paths cannot be empty")
    src = get_object_at_path(source_path)
    targets = [get_object_at_path(p)["id"] for p in target_paths]
    return waapi_call("ak.wwise.core.object.pasteProperties", {"source": src["id"], "targets": targets, **kwargs})

def object_set(object_path: str, updates: dict[str, Any], **kwargs: Any) -> Any:
    """Batch set properties/references on object. Schema: objects (array of object ids)."""
    if not object_path or not updates:
        raise WwiseValidationError("object_path and updates cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.object.set", {"objects": [obj["id"]], **updates, **kwargs})

def object_set_attenuation_curve(
    object_path: str,
    curve_type: str,
    points: list[dict],
    use: bool = True,
    **kwargs: Any,
) -> Any:
    """Set attenuation curve. Schema: object, curveType, points, use."""
    if not object_path:
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.object.setAttenuationCurve", {
        "object": obj["id"],
        "curveType": curve_type,
        "points": points,
        "use": use,
        **kwargs,
    })

def object_set_linked(object_path: str, property_name: str, linked: bool, platform: str = "Windows", **kwargs: Any) -> Any:
    """Link/unlink property to platform. Schema: object, property, linked, platform (required)."""
    if not object_path or not property_name:
        raise WwiseValidationError("object_path and property_name cannot be empty")
    obj = get_object_at_path(object_path)
    args: dict[str, Any] = {"object": obj["id"], "property": property_name, "linked": linked, "platform": platform, **kwargs}
    return waapi_call("ak.wwise.core.object.setLinked", args)

def object_set_notes(object_path: str, notes: str) -> Any:
    """Set object notes. Uses ak.wwise.core.object.setNotes."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.object.setNotes", {"object": obj["id"], "value": notes})

def object_set_randomizer(
    object_path: str,
    property_name: str,
    *,
    enabled: bool | None = None,
    min_val: int | float | None = None,
    max_val: int | float | None = None,
    platform: str | None = None,
    value: int | float | None = None,
    **kwargs: Any,
) -> Any:
    """Set randomizer. Schema: object, property, enabled?, min?, max?, platform?. value maps to min/max if min_val/max_val not set."""
    if not object_path or not property_name:
        raise WwiseValidationError("object_path and property_name cannot be empty")
    obj = get_object_at_path(object_path)
    args: dict[str, Any] = {"object": obj["id"], "property": property_name, **kwargs}
    if enabled is not None:
        args["enabled"] = enabled
    if min_val is not None:
        args["min"] = min_val
    elif value is not None:
        args["min"] = value
    if max_val is not None:
        args["max"] = max_val
    elif value is not None:
        args["max"] = value
    if platform is not None:
        args["platform"] = platform
    return waapi_call("ak.wwise.core.object.setRandomizer", args)

def object_set_state_groups(object_path: str, state_groups: list[str]) -> Any:
    """Set State Groups associated with object. Uses ak.wwise.core.object.setStateGroups."""
    if not object_path:
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    ids = [get_object_at_path(p)["id"] for p in state_groups] if state_groups else []
    return waapi_call("ak.wwise.core.object.setStateGroups", {"object": obj["id"], "stateGroups": ids})

def object_set_state_properties(object_path: str, state_properties: list[dict], **kwargs: Any) -> Any:
    """Set state properties of object. Uses ak.wwise.core.object.setStateProperties."""
    if not object_path:
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.object.setStateProperties", {"object": obj["id"], "stateProperties": state_properties, **kwargs})

# ==============================================================================
#                   ak.wwise.core.plugin
# ==============================================================================

def plugin_get_list(**kwargs: Any) -> Any:
    """Get plugin list. Uses ak.wwise.core.plugin.getList."""
    return waapi_call("ak.wwise.core.plugin.getList", kwargs)

def plugin_get_properties(plugin_id: str, **kwargs: Any) -> Any:
    """Get plugin properties. Uses ak.wwise.core.plugin.getProperties."""
    if not plugin_id or not str(plugin_id).strip():
        raise WwiseValidationError("plugin_id cannot be empty")
    return waapi_call("ak.wwise.core.plugin.getProperties", {"pluginID": plugin_id, **kwargs})

def plugin_get_property(plugin_id: str, property_name: str, **kwargs: Any) -> Any:
    """Get plugin property. Uses ak.wwise.core.plugin.getProperty."""
    if not plugin_id or not property_name:
        raise WwiseValidationError("plugin_id and property_name cannot be empty")
    return waapi_call("ak.wwise.core.plugin.getProperty", {"pluginID": plugin_id, "property": property_name, **kwargs})

# ==============================================================================
#                   ak.wwise.core.profiler
# ==============================================================================

def profiler_enable_profiler_data(data_types: list[str], **kwargs: Any) -> Any:
    """Enable profiler data capture. Uses ak.wwise.core.profiler.enableProfilerData."""
    if not data_types:
        raise WwiseValidationError("data_types cannot be empty")
    return waapi_call("ak.wwise.core.profiler.enableProfilerData", {"dataTypes": data_types, **kwargs})

def profiler_get_audio_objects(**kwargs: Any) -> Any:
    """Get Audio Objects at capture time. Uses ak.wwise.core.profiler.getAudioObjects."""
    return waapi_call("ak.wwise.core.profiler.getAudioObjects", {"time": "capture", **kwargs})

def profiler_get_busses(**kwargs: Any) -> Any:
    """Get busses at capture time. Uses ak.wwise.core.profiler.getBusses."""
    return waapi_call("ak.wwise.core.profiler.getBusses", {"time": "capture", **kwargs})

def profiler_get_cpu_usage(**kwargs: Any) -> Any:
    """Get CPU usage at capture time. Uses ak.wwise.core.profiler.getCpuUsage."""
    return waapi_call("ak.wwise.core.profiler.getCpuUsage", {"time": "capture", **kwargs})

def profiler_get_cursor_time(**kwargs: Any) -> Any:
    """Get profiler cursor time. Schema: cursor (e.g. 'capture')."""
    args: dict[str, Any] = dict(kwargs)
    if "cursor" not in args:
        args["cursor"] = "capture"
    return waapi_call("ak.wwise.core.profiler.getCursorTime", args)

def profiler_get_loaded_media(**kwargs: Any) -> Any:
    """Get loaded media at capture time. Uses ak.wwise.core.profiler.getLoadedMedia."""
    return waapi_call("ak.wwise.core.profiler.getLoadedMedia", {"time": "capture", **kwargs})

def profiler_get_meters(**kwargs: Any) -> Any:
    """Get meter data. Uses ak.wwise.core.profiler.getMeters."""
    return waapi_call("ak.wwise.core.profiler.getMeters", {"time": "capture", **kwargs})

def profiler_get_performance_monitor(**kwargs: Any) -> Any:
    """Get Performance Monitor at capture time. Uses ak.wwise.core.profiler.getPerformanceMonitor."""
    return waapi_call("ak.wwise.core.profiler.getPerformanceMonitor", {"time": "capture", **kwargs})

def profiler_get_rtpcs(**kwargs: Any) -> Any:
    """Get RTPCs at capture time. Uses ak.wwise.core.profiler.getRTPCs."""
    return waapi_call("ak.wwise.core.profiler.getRTPCs", {"time": "capture", **kwargs})

def profiler_get_streamed_media(**kwargs: Any) -> Any:
    """Get streamed media at capture time. Uses ak.wwise.core.profiler.getStreamedMedia."""
    return waapi_call("ak.wwise.core.profiler.getStreamedMedia", {"time": "capture", **kwargs})

def profiler_get_voice_contributions(**kwargs: Any) -> Any:
    """Get voice contributions. Schema: voicePipelineID (and time?)."""
    args: dict[str, Any] = {"voicePipelineID": 0, **kwargs}
    if "time" not in args:
        args["time"] = "capture"
    return waapi_call("ak.wwise.core.profiler.getVoiceContributions", args)

def profiler_get_voices(**kwargs: Any) -> Any:
    """Get voices at capture time. Uses ak.wwise.core.profiler.getVoices."""
    return waapi_call("ak.wwise.core.profiler.getVoices", {"time": "capture", **kwargs})

def profiler_register_meter(object_path: str, **kwargs: Any) -> Any:
    """Register bus/device for meter data. Uses ak.wwise.core.profiler.registerMeter."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.profiler.registerMeter", {"object": obj["id"], **kwargs})

def profiler_save_capture(file_path: str, **kwargs: Any) -> Any:
    """Save profiler capture to file. Uses ak.wwise.core.profiler.saveCapture."""
    if not file_path or not str(file_path).strip():
        raise WwiseValidationError("file_path cannot be empty")
    return waapi_call("ak.wwise.core.profiler.saveCapture", {"file": file_path, **kwargs})

def profiler_start_capture(**kwargs: Any) -> Any:
    """Start profiler capture. Uses ak.wwise.core.profiler.startCapture."""
    return waapi_call("ak.wwise.core.profiler.startCapture", kwargs)

def profiler_stop_capture(**kwargs: Any) -> Any:
    """Stop profiler capture. Uses ak.wwise.core.profiler.stopCapture."""
    return waapi_call("ak.wwise.core.profiler.stopCapture", kwargs)

def profiler_unregister_meter(object_path: str, **kwargs: Any) -> Any:
    """Unregister meter. Uses ak.wwise.core.profiler.unregisterMeter."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.profiler.unregisterMeter", {"object": obj["id"], **kwargs})

# ==============================================================================
#                   ak.wwise.core.project, remote, sound
# ==============================================================================

def project_save(**kwargs: Any) -> Any:
    """Save current project. Uses ak.wwise.core.project.save."""
    return waapi_call("ak.wwise.core.project.save", kwargs)

def remote_connect(host: str, **kwargs: Any) -> Any:
    """Connect Wwise to Sound Engine. Uses ak.wwise.core.remote.connect."""
    if not host or not str(host).strip():
        raise WwiseValidationError("host cannot be empty")
    return waapi_call("ak.wwise.core.remote.connect", {"host": host, **kwargs})

def remote_disconnect(**kwargs: Any) -> Any:
    """Disconnect from Sound Engine. Uses ak.wwise.core.remote.disconnect."""
    return waapi_call("ak.wwise.core.remote.disconnect", kwargs)

def remote_get_available_consoles(**kwargs: Any) -> Any:
    """Get available hosts. Uses ak.wwise.core.remote.getAvailableConsoles."""
    return waapi_call("ak.wwise.core.remote.getAvailableConsoles", kwargs)

def remote_get_connection_status(**kwargs: Any) -> Any:
    """Get connection status. Uses ak.wwise.core.remote.getConnectionStatus."""
    return waapi_call("ak.wwise.core.remote.getConnectionStatus", kwargs)

def sound_set_active_source(sound_path: str, source_id_or_path: str, **kwargs: Any) -> Any:
    """Set active source for Sound. Schema: sound, source, platform?."""
    if not sound_path or not source_id_or_path:
        raise WwiseValidationError("sound_path and source_id_or_path cannot be empty")
    sound_obj = get_object_at_path(sound_path)
    src_id = get_object_at_path(source_id_or_path)["id"] if isinstance(source_id_or_path, str) and source_id_or_path.startswith("\\") else source_id_or_path
    return waapi_call("ak.wwise.core.sound.setActiveSource", {"sound": sound_obj["id"], "source": src_id, **kwargs})

# ==============================================================================
#                   ak.wwise.core.soundbank (remaining)
# ==============================================================================

def soundbank_get_inclusions(soundbank_path: str, **kwargs: Any) -> Any:
    """Get SoundBank inclusions. Uses ak.wwise.core.soundbank.getInclusions."""
    if not soundbank_path or not str(soundbank_path).strip():
        raise WwiseValidationError("soundbank_path cannot be empty")
    return waapi_call("ak.wwise.core.soundbank.getInclusions", {"soundbank": soundbank_path, **kwargs})

def soundbank_process_definition_files(files: list[str], **kwargs: Any) -> Any:
    """Import SoundBank definition files. Uses ak.wwise.core.soundbank.processDefinitionFiles."""
    if not files:
        raise WwiseValidationError("files cannot be empty")
    return waapi_call("ak.wwise.core.soundbank.processDefinitionFiles", {"files": files, **kwargs})

def soundbank_convert_external_sources(**kwargs: Any) -> Any:
    """Convert external sources. Schema: sources (array)."""
    if "sources" not in kwargs:
        raise WwiseValidationError("sources (list) is required for convertExternalSources")
    return waapi_call("ak.wwise.core.soundbank.convertExternalSources", kwargs)

# ==============================================================================
#                   ak.wwise.core.sourceControl
# ==============================================================================

def source_control_add(files: list[str], **kwargs: Any) -> Any:
    """Add files to source control. Uses ak.wwise.core.sourceControl.add."""
    if not files:
        raise WwiseValidationError("files cannot be empty")
    return waapi_call("ak.wwise.core.sourceControl.add", {"files": files, **kwargs})

def source_control_check_out(files: list[str], **kwargs: Any) -> Any:
    """Check out files. Uses ak.wwise.core.sourceControl.checkOut."""
    if not files:
        raise WwiseValidationError("files cannot be empty")
    return waapi_call("ak.wwise.core.sourceControl.checkOut", {"files": files, **kwargs})

def source_control_commit(files: list[str], **kwargs: Any) -> Any:
    """Commit files. Schema: files, message."""
    if not files:
        raise WwiseValidationError("files cannot be empty")
    args: dict[str, Any] = {"files": files, **kwargs}
    if "message" not in args:
        args["message"] = ""
    return waapi_call("ak.wwise.core.sourceControl.commit", args)

def source_control_delete(files: list[str], **kwargs: Any) -> Any:
    """Delete files from source control. Uses ak.wwise.core.sourceControl.delete."""
    if not files:
        raise WwiseValidationError("files cannot be empty")
    return waapi_call("ak.wwise.core.sourceControl.delete", {"files": files, **kwargs})

def source_control_get_source_files(**kwargs: Any) -> Any:
    """Get original files. Uses ak.wwise.core.sourceControl.getSourceFiles."""
    return waapi_call("ak.wwise.core.sourceControl.getSourceFiles", kwargs)

def source_control_get_status(files: list[str], **kwargs: Any) -> Any:
    """Get source control status. Uses ak.wwise.core.sourceControl.getStatus."""
    if not files:
        raise WwiseValidationError("files cannot be empty")
    return waapi_call("ak.wwise.core.sourceControl.getStatus", {"files": files, **kwargs})

def source_control_move(files: list[str], new_files: list[str], **kwargs: Any) -> Any:
    """Move/rename in source control. Uses ak.wwise.core.sourceControl.move."""
    if not files or not new_files or len(files) != len(new_files):
        raise WwiseValidationError("files and new_files must be same-length non-empty lists")
    return waapi_call("ak.wwise.core.sourceControl.move", {"files": files, "newFiles": new_files, **kwargs})

def source_control_revert(files: list[str], **kwargs: Any) -> Any:
    """Revert changes. Uses ak.wwise.core.sourceControl.revert."""
    if not files:
        raise WwiseValidationError("files cannot be empty")
    return waapi_call("ak.wwise.core.sourceControl.revert", {"files": files, **kwargs})

def source_control_set_provider(provider: str, **kwargs: Any) -> Any:
    """Set source control provider. Uses ak.wwise.core.sourceControl.setProvider."""
    if not provider or not str(provider).strip():
        raise WwiseValidationError("provider cannot be empty")
    return waapi_call("ak.wwise.core.sourceControl.setProvider", {"provider": provider, **kwargs})

# ==============================================================================
#                   ak.wwise.core.transport
# ==============================================================================

def transport_create(object_path: str, **kwargs: Any) -> Any:
    """Create transport for object. Uses ak.wwise.core.transport.create."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.transport.create", {"object": obj["id"], **kwargs})

def transport_destroy(transport_id: str, **kwargs: Any) -> Any:
    """Destroy transport. Uses ak.wwise.core.transport.destroy."""
    if not transport_id or not str(transport_id).strip():
        raise WwiseValidationError("transport_id cannot be empty")
    return waapi_call("ak.wwise.core.transport.destroy", {"transport": transport_id, **kwargs})

def transport_execute_action(action: str, transport_id: str | None = None, **kwargs: Any) -> Any:
    """Execute transport action. Uses ak.wwise.core.transport.executeAction."""
    if not action or not str(action).strip():
        raise WwiseValidationError("action cannot be empty")
    args: dict[str, Any] = {"action": action, **kwargs}
    if transport_id is not None:
        args["transport"] = transport_id
    return waapi_call("ak.wwise.core.transport.executeAction", args)

def transport_get_list(**kwargs: Any) -> Any:
    """Get transport list. Uses ak.wwise.core.transport.getList."""
    return waapi_call("ak.wwise.core.transport.getList", kwargs)

def transport_get_state(transport_id: str, **kwargs: Any) -> Any:
    """Get transport state. Uses ak.wwise.core.transport.getState."""
    if not transport_id or not str(transport_id).strip():
        raise WwiseValidationError("transport_id cannot be empty")
    return waapi_call("ak.wwise.core.transport.getState", {"transport": transport_id, **kwargs})

def transport_prepare(object_path: str, **kwargs: Any) -> Any:
    """Prepare object for playback. Uses ak.wwise.core.transport.prepare."""
    if not object_path or not str(object_path).strip():
        raise WwiseValidationError("object_path cannot be empty")
    obj = get_object_at_path(object_path)
    return waapi_call("ak.wwise.core.transport.prepare", {"object": obj["id"], **kwargs})

# ==============================================================================
#                   ak.wwise.core.undo
# ==============================================================================

def undo_begin_group(**kwargs: Any) -> Any:
    """Begin undo group. Uses ak.wwise.core.undo.beginGroup."""
    return waapi_call("ak.wwise.core.undo.beginGroup", kwargs)

def undo_cancel_group(**kwargs: Any) -> Any:
    """Cancel last undo group. Uses ak.wwise.core.undo.cancelGroup."""
    return waapi_call("ak.wwise.core.undo.cancelGroup", kwargs)

def undo_end_group(display_name: str = "Group", **kwargs: Any) -> Any:
    """End undo group. Schema: displayName."""
    return waapi_call("ak.wwise.core.undo.endGroup", {"displayName": display_name, **kwargs})

def undo_redo(**kwargs: Any) -> Any:
    """Redo last operation. Uses ak.wwise.core.undo.redo."""
    return waapi_call("ak.wwise.core.undo.redo", kwargs)

def undo_undo(**kwargs: Any) -> Any:
    """Undo last operation. Uses ak.wwise.core.undo.undo."""
    return waapi_call("ak.wwise.core.undo.undo", kwargs)

# ==============================================================================
#                   ak.wwise.core.workUnit
# ==============================================================================

def work_unit_load(work_unit_path: str, **kwargs: Any) -> Any:
    """Load Work Unit. Uses ak.wwise.core.workUnit.load."""
    if not work_unit_path or not str(work_unit_path).strip():
        raise WwiseValidationError("work_unit_path cannot be empty")
    obj = get_object_at_path(work_unit_path)
    return waapi_call("ak.wwise.core.workUnit.load", {"object": obj["id"], **kwargs})

def work_unit_unload(work_unit_path: str, **kwargs: Any) -> Any:
    """Unload Work Unit. Uses ak.wwise.core.workUnit.unload."""
    if not work_unit_path or not str(work_unit_path).strip():
        raise WwiseValidationError("work_unit_path cannot be empty")
    obj = get_object_at_path(work_unit_path)
    return waapi_call("ak.wwise.core.workUnit.unload", {"object": obj["id"], **kwargs})

# ==============================================================================
#                   ak.wwise.debug
# ==============================================================================

def debug_enable_asserts(enable: bool) -> Any:
    """Enable/disable asserts. Schema: enable."""
    return waapi_call("ak.wwise.debug.enableAsserts", {"enable": enable})

def debug_enable_automation_mode(enable: bool) -> Any:
    """Enable/disable automation mode. Schema: enable."""
    return waapi_call("ak.wwise.debug.enableAutomationMode", {"enable": enable})

def debug_generate_tone_wav(path: str, **kwargs: Any) -> Any:
    """Generate tone WAV. Schema: path."""
    if not path or not str(path).strip():
        raise WwiseValidationError("path cannot be empty")
    return waapi_call("ak.wwise.debug.generateToneWAV", {"path": path, **kwargs})

def debug_get_wal_tree(**kwargs: Any) -> Any:
    """Get WAL tree. Uses ak.wwise.debug.getWalTree."""
    return waapi_call("ak.wwise.debug.getWalTree", kwargs)

def debug_restart_waapi_servers(**kwargs: Any) -> Any:
    """Restart WAAPI servers. Uses ak.wwise.debug.restartWaapiServers."""
    return waapi_call("ak.wwise.debug.restartWaapiServers", kwargs)

def debug_test_assert(**kwargs: Any) -> Any:
    """Test assert. Uses ak.wwise.debug.testAssert."""
    return waapi_call("ak.wwise.debug.testAssert", kwargs)

def debug_test_crash(**kwargs: Any) -> Any:
    """Test crash. Uses ak.wwise.debug.testCrash."""
    return waapi_call("ak.wwise.debug.testCrash", kwargs)

def debug_validate_call(id: str, args: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """Validate WAAPI call. Schema: id, args?, options?, result?."""
    if not id or not str(id).strip():
        raise WwiseValidationError("id cannot be empty")
    return waapi_call("ak.wwise.debug.validateCall", {"id": id, "args": args or {}, **kwargs})

# ==============================================================================
#                   ak.wwise.ui (remaining)
# ==============================================================================

def ui_bring_to_foreground(**kwargs: Any) -> Any:
    """Bring Wwise window to foreground. Uses ak.wwise.ui.bringToForeground."""
    return waapi_call("ak.wwise.ui.bringToForeground", kwargs)

def ui_capture_screen(**kwargs: Any) -> Any:
    """Capture UI. Uses ak.wwise.ui.captureScreen."""
    return waapi_call("ak.wwise.ui.captureScreen", kwargs)

def ui_commands_execute(command: str, **kwargs: Any) -> Any:
    """Execute UI command. Uses ak.wwise.ui.commands.execute."""
    if not command or not str(command).strip():
        raise WwiseValidationError("command cannot be empty")
    return waapi_call("ak.wwise.ui.commands.execute", {"command": command, **kwargs})

def ui_commands_get_commands(**kwargs: Any) -> Any:
    """Get command list. Uses ak.wwise.ui.commands.getCommands."""
    return waapi_call("ak.wwise.ui.commands.getCommands", kwargs)

def ui_commands_register(commands: list[dict], **kwargs: Any) -> Any:
    """Register extension commands. Uses ak.wwise.ui.commands.register."""
    if not commands:
        raise WwiseValidationError("commands cannot be empty")
    return waapi_call("ak.wwise.ui.commands.register", {"commands": commands, **kwargs})

def ui_commands_unregister(commands: list[dict], **kwargs: Any) -> Any:
    """Unregister extension commands. Uses ak.wwise.ui.commands.unregister."""
    if not commands:
        raise WwiseValidationError("commands cannot be empty")
    return waapi_call("ak.wwise.ui.commands.unregister", {"commands": commands, **kwargs})

def ui_get_selected_files(**kwargs: Any) -> Any:
    """Get selected files. Uses ak.wwise.ui.getSelectedFiles."""
    return waapi_call("ak.wwise.ui.getSelectedFiles", kwargs)

def ui_layout_close_view(view_id: str, **kwargs: Any) -> Any:
    """Close view. Uses ak.wwise.ui.layout.closeView."""
    if not view_id or not str(view_id).strip():
        raise WwiseValidationError("view_id cannot be empty")
    return waapi_call("ak.wwise.ui.layout.closeView", {"viewID": view_id, **kwargs})

def ui_layout_dock_view(view_id: str, target_id: str, side: str, name: str, **kwargs: Any) -> Any:
    """Dock view. Schema: viewID, targetID, side, name."""
    if not view_id or not str(view_id).strip():
        raise WwiseValidationError("view_id cannot be empty")
    return waapi_call("ak.wwise.ui.layout.dockView", {
        "viewID": view_id,
        "targetID": target_id,
        "side": side,
        "name": name,
        **kwargs,
    })

def ui_layout_get_current_layout_name(**kwargs: Any) -> Any:
    """Get current layout name. Uses ak.wwise.ui.layout.getCurrentLayoutName."""
    return waapi_call("ak.wwise.ui.layout.getCurrentLayoutName", kwargs)

def ui_layout_get_element_rectangle(element_id: str, **kwargs: Any) -> Any:
    """Get element rectangle. Uses ak.wwise.ui.layout.getElementRectangle."""
    if not element_id or not str(element_id).strip():
        raise WwiseValidationError("element_id cannot be empty")
    return waapi_call("ak.wwise.ui.layout.getElementRectangle", {"id": element_id, **kwargs})

def ui_layout_get_layout(name: str, **kwargs: Any) -> Any:
    """Get layout JSON. Schema: name (required)."""
    if not name or not str(name).strip():
        raise WwiseValidationError("name cannot be empty")
    return waapi_call("ak.wwise.ui.layout.getLayout", {"name": name, **kwargs})

def ui_layout_get_layout_names(**kwargs: Any) -> Any:
    """Get layout names. Uses ak.wwise.ui.layout.getLayoutNames."""
    return waapi_call("ak.wwise.ui.layout.getLayoutNames", kwargs)

def ui_layout_get_or_create_view(name: str, pos_x: int = 0, pos_y: int = 0, **kwargs: Any) -> Any:
    """Get or create view. Schema: name, posX?, posY?."""
    if not name or not str(name).strip():
        raise WwiseValidationError("name cannot be empty")
    return waapi_call("ak.wwise.ui.layout.getOrCreateView", {"name": name, "posX": pos_x, "posY": pos_y, **kwargs})

def ui_layout_get_view_instances(name: str = "Designer", **kwargs: Any) -> Any:
    """Get view instances. Schema: name (required). Default name=Designer."""
    if not name or not str(name).strip():
        name = "Designer"
    return waapi_call("ak.wwise.ui.layout.getViewInstances", {"name": name, **kwargs})

def ui_layout_get_view_types(**kwargs: Any) -> Any:
    """Get view types. Uses ak.wwise.ui.layout.getViewTypes."""
    return waapi_call("ak.wwise.ui.layout.getViewTypes", kwargs)

def ui_layout_move_splitter(splitter_id: str, delta: int, **kwargs: Any) -> Any:
    """Move splitter. Uses ak.wwise.ui.layout.moveSplitter."""
    if not splitter_id or not str(splitter_id).strip():
        raise WwiseValidationError("splitter_id cannot be empty")
    return waapi_call("ak.wwise.ui.layout.moveSplitter", {"id": splitter_id, "delta": delta, **kwargs})

def ui_layout_remove_layout(layout_name: str, **kwargs: Any) -> Any:
    """Remove temporary layout. Uses ak.wwise.ui.layout.removeLayout."""
    if not layout_name or not str(layout_name).strip():
        raise WwiseValidationError("layout_name cannot be empty")
    return waapi_call("ak.wwise.ui.layout.removeLayout", {"name": layout_name, **kwargs})

def ui_layout_reset_layouts(**kwargs: Any) -> Any:
    """Reset layouts. Uses ak.wwise.ui.layout.resetLayouts."""
    return waapi_call("ak.wwise.ui.layout.resetLayouts", kwargs)

def ui_layout_set_layout(layout_json: dict[str, Any] | str, **kwargs: Any) -> Any:
    """Register layout from JSON. Schema: name, layout."""
    if layout_json is None or (isinstance(layout_json, str) and not layout_json.strip()):
        raise WwiseValidationError("layout_json cannot be empty")
    args: dict[str, Any] = {"layout": layout_json, **kwargs}
    if "name" not in args:
        args["name"] = "Layout"
    return waapi_call("ak.wwise.ui.layout.setLayout", args)

def ui_layout_undock_view(view_id: str, name: str = "", pos_x: int = 0, pos_y: int = 0, **kwargs: Any) -> Any:
    """Undock view. Schema: viewID, name?, posX?, posY?."""
    if not view_id or not str(view_id).strip():
        raise WwiseValidationError("view_id cannot be empty")
    return waapi_call("ak.wwise.ui.layout.undockView", {
        "viewID": view_id,
        "name": name,
        "posX": pos_x,
        "posY": pos_y,
        **kwargs,
    })

def ui_project_close(**kwargs: Any) -> Any:
    """Close project (UI). Uses ak.wwise.ui.project.close."""
    return waapi_call("ak.wwise.ui.project.close", kwargs)

def ui_project_create(path: str, platform: str, **kwargs: Any) -> Any:
    """Create project (UI). Schema: path, platforms (array), languages?."""
    if not path or not platform:
        raise WwiseValidationError("path and platform cannot be empty")
    return waapi_call("ak.wwise.ui.project.create", {"path": path, "platforms": [platform], **kwargs})

def ui_project_open(path: str, **kwargs: Any) -> Any:
    """Open project (UI). Uses ak.wwise.ui.project.open."""
    if not path or not str(path).strip():
        raise WwiseValidationError("path cannot be empty")
    return waapi_call("ak.wwise.ui.project.open", {"path": path, **kwargs})

# ==============================================================================
#                   ak.wwise.waapi
# ==============================================================================

def waapi_get_functions(**kwargs: Any) -> Any:
    """Get WAAPI function list. Uses ak.wwise.waapi.getFunctions."""
    return waapi_call("ak.wwise.waapi.getFunctions", kwargs)

def waapi_get_schema(uri: str | None = None, **kwargs: Any) -> Any:
    """Get WAAPI JSON schema. Uses ak.wwise.waapi.getSchema."""
    args: dict[str, Any] = dict(kwargs)
    if uri is not None:
        args["uri"] = uri
    return waapi_call("ak.wwise.waapi.getSchema", args)


def waapi_schema_get_args_spec(uri: str) -> dict[str, Any]:
    """
    Get the argument specification for a WAAPI function from its schema.
    Uses ak.wwise.waapi.getSchema. Requires an active WAAPI connection.

    Returns:
        dict with keys:
          - "required": list of required argument names ([] if not in schema)
          - "properties": list of allowed argument names
          - "additionalProperties": bool (if False, only properties are allowed)
          - "raw": the full argsSchema from getSchema
    """
    schema = waapi_get_schema(uri=uri)
    args_schema = (schema or {}).get("argsSchema") or {}
    props = args_schema.get("properties") or {}
    return {
        "required": list(args_schema.get("required") or []),
        "properties": list(props.keys()),
        "additionalProperties": args_schema.get("additionalProperties", True),
        "raw": args_schema,
    }


def waapi_validate_args(uri: str, args: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate that `args` conform to the WAAPI function schema for `uri`.
    Uses ak.wwise.waapi.getSchema. Requires an active WAAPI connection.

    Returns:
        (is_valid, list of error messages). Empty list if valid.
    """
    spec = waapi_schema_get_args_spec(uri)
    errors: list[str] = []
    required = set(spec["required"])
    allowed = set(spec["properties"])
    only_allowed = spec["additionalProperties"] is False
    arg_keys = set(args.keys()) if args else set()

    for r in required:
        if r not in arg_keys:
            errors.append(f"Missing required argument: {r!r}")

    if only_allowed and allowed:
        for k in arg_keys:
            if k not in allowed:
                errors.append(f"Unknown argument: {k!r} (schema allows only: {sorted(allowed)})")

    return (len(errors) == 0, errors)


def waapi_get_topics(**kwargs: Any) -> Any:
    """Get subscribable topics. Uses ak.wwise.waapi.getTopics."""
    return waapi_call("ak.wwise.waapi.getTopics", kwargs)


def waapi_subscribe(uri: str, options: dict | None = None, **kwargs: Any) -> str:
    """
    Subscribe to a WAAPI topic. Returns a subscription_id for use with
    waapi_subscription_events and waapi_unsubscribe.
    """
    opts = dict(options or {}, **kwargs)
    return WwiseSession.waapi_subscribe(uri, opts)


def waapi_unsubscribe(subscription_id: str, **kwargs: Any) -> bool:
    """Unsubscribe from a topic by subscription_id. Returns True if unsubscribed."""
    return WwiseSession.waapi_unsubscribe(subscription_id, **kwargs)


def waapi_subscription_events(subscription_id: str, max_count: int | None = None,
                               clear: bool = True) -> list[dict[str, Any]]:
    """Return events received for the given subscription (drains the queue up to max_count)."""
    return WwiseSession.waapi_subscription_events(
        subscription_id, max_count=max_count, clear=clear
    )


# WAAPI topic URIs from Wwise Authoring API Reference (Topics index).
# Use waapi_subscribe(uri) to subscribe; use these constants for discovery.
WAAPI_TOPICS = [
    "ak.wwise.core.audio.imported",
    "ak.wwise.core.log.itemAdded",
    "ak.wwise.core.object.attenuationCurveChanged",
    "ak.wwise.core.object.attenuationCurveLinkChanged",
    "ak.wwise.core.object.childAdded",
    "ak.wwise.core.object.childRemoved",
    "ak.wwise.core.object.created",
    "ak.wwise.core.object.curveChanged",
    "ak.wwise.core.object.nameChanged",
    "ak.wwise.core.object.notesChanged",
    "ak.wwise.core.object.postDeleted",
    "ak.wwise.core.object.preDeleted",
    "ak.wwise.core.object.propertyChanged",
    "ak.wwise.core.object.referenceChanged",
    "ak.wwise.core.object.structureChanged",
    "ak.wwise.core.profiler.captureLog.itemAdded",
    "ak.wwise.core.profiler.gameObjectRegistered",
    "ak.wwise.core.profiler.gameObjectReset",
    "ak.wwise.core.profiler.gameObjectUnregistered",
    "ak.wwise.core.profiler.stateChanged",
    "ak.wwise.core.profiler.switchChanged",
    "ak.wwise.core.project.loaded",
    "ak.wwise.core.project.postClosed",
    "ak.wwise.core.project.preClosed",
    "ak.wwise.core.project.saved",
    "ak.wwise.core.soundbank.generated",
    "ak.wwise.core.soundbank.generationDone",
    "ak.wwise.core.switchContainer.assignmentAdded",
    "ak.wwise.core.switchContainer.assignmentRemoved",
    "ak.wwise.core.transport.stateChanged",
    "ak.wwise.debug.assertFailed",
    "ak.wwise.ui.commands.executed",
    "ak.wwise.ui.selectionChanged",
]


def subscribe_topic_audio_imported(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.audio.imported (import operation ended)."""
    return waapi_subscribe("ak.wwise.core.audio.imported", **kwargs)


def subscribe_topic_log_item_added(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.log.itemAdded (log entry added)."""
    return waapi_subscribe("ak.wwise.core.log.itemAdded", **kwargs)


def subscribe_topic_object_attenuation_curve_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.attenuationCurveChanged."""
    return waapi_subscribe("ak.wwise.core.object.attenuationCurveChanged", **kwargs)


def subscribe_topic_object_attenuation_curve_link_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.attenuationCurveLinkChanged."""
    return waapi_subscribe("ak.wwise.core.object.attenuationCurveLinkChanged", **kwargs)


def subscribe_topic_object_child_added(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.childAdded."""
    return waapi_subscribe("ak.wwise.core.object.childAdded", **kwargs)


def subscribe_topic_object_child_removed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.childRemoved."""
    return waapi_subscribe("ak.wwise.core.object.childRemoved", **kwargs)


def subscribe_topic_object_created(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.created."""
    return waapi_subscribe("ak.wwise.core.object.created", **kwargs)


def subscribe_topic_object_curve_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.curveChanged."""
    return waapi_subscribe("ak.wwise.core.object.curveChanged", **kwargs)


def subscribe_topic_object_name_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.nameChanged."""
    return waapi_subscribe("ak.wwise.core.object.nameChanged", **kwargs)


def subscribe_topic_object_notes_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.notesChanged."""
    return waapi_subscribe("ak.wwise.core.object.notesChanged", **kwargs)


def subscribe_topic_object_post_deleted(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.postDeleted."""
    return waapi_subscribe("ak.wwise.core.object.postDeleted", **kwargs)


def subscribe_topic_object_pre_deleted(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.preDeleted."""
    return waapi_subscribe("ak.wwise.core.object.preDeleted", **kwargs)


def subscribe_topic_object_property_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.propertyChanged."""
    return waapi_subscribe("ak.wwise.core.object.propertyChanged", **kwargs)


def subscribe_topic_object_reference_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.referenceChanged."""
    return waapi_subscribe("ak.wwise.core.object.referenceChanged", **kwargs)


def subscribe_topic_object_structure_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.object.structureChanged."""
    return waapi_subscribe("ak.wwise.core.object.structureChanged", **kwargs)


def subscribe_topic_profiler_capture_log_item_added(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.profiler.captureLog.itemAdded."""
    return waapi_subscribe("ak.wwise.core.profiler.captureLog.itemAdded", **kwargs)


def subscribe_topic_profiler_game_object_registered(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.profiler.gameObjectRegistered."""
    return waapi_subscribe("ak.wwise.core.profiler.gameObjectRegistered", **kwargs)


def subscribe_topic_profiler_game_object_reset(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.profiler.gameObjectReset."""
    return waapi_subscribe("ak.wwise.core.profiler.gameObjectReset", **kwargs)


def subscribe_topic_profiler_game_object_unregistered(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.profiler.gameObjectUnregistered."""
    return waapi_subscribe("ak.wwise.core.profiler.gameObjectUnregistered", **kwargs)


def subscribe_topic_profiler_state_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.profiler.stateChanged."""
    return waapi_subscribe("ak.wwise.core.profiler.stateChanged", **kwargs)


def subscribe_topic_profiler_switch_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.profiler.switchChanged."""
    return waapi_subscribe("ak.wwise.core.profiler.switchChanged", **kwargs)


def subscribe_topic_project_loaded(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.project.loaded."""
    return waapi_subscribe("ak.wwise.core.project.loaded", **kwargs)


def subscribe_topic_project_post_closed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.project.postClosed."""
    return waapi_subscribe("ak.wwise.core.project.postClosed", **kwargs)


def subscribe_topic_project_pre_closed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.project.preClosed."""
    return waapi_subscribe("ak.wwise.core.project.preClosed", **kwargs)


def subscribe_topic_project_saved(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.project.saved."""
    return waapi_subscribe("ak.wwise.core.project.saved", **kwargs)


def subscribe_topic_soundbank_generated(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.soundbank.generated."""
    return waapi_subscribe("ak.wwise.core.soundbank.generated", **kwargs)


def subscribe_topic_soundbank_generation_done(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.soundbank.generationDone."""
    return waapi_subscribe("ak.wwise.core.soundbank.generationDone", **kwargs)


def subscribe_topic_switch_container_assignment_added(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.switchContainer.assignmentAdded."""
    return waapi_subscribe("ak.wwise.core.switchContainer.assignmentAdded", **kwargs)


def subscribe_topic_switch_container_assignment_removed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.switchContainer.assignmentRemoved."""
    return waapi_subscribe("ak.wwise.core.switchContainer.assignmentRemoved", **kwargs)


def subscribe_topic_transport_state_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.core.transport.stateChanged."""
    return waapi_subscribe("ak.wwise.core.transport.stateChanged", **kwargs)


def subscribe_topic_debug_assert_failed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.debug.assertFailed (Debug builds only)."""
    return waapi_subscribe("ak.wwise.debug.assertFailed", **kwargs)


def subscribe_topic_ui_commands_executed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.ui.commands.executed."""
    return waapi_subscribe("ak.wwise.ui.commands.executed", **kwargs)


def subscribe_topic_ui_selection_changed(**kwargs: Any) -> str:
    """Subscribe to ak.wwise.ui.selectionChanged."""
    return waapi_subscribe("ak.wwise.ui.selectionChanged", **kwargs)


def waapi_list_topic_uris() -> list[str]:
    """Return the list of WAAPI topic URIs from the reference (for discovery)."""
    return list(WAAPI_TOPICS)


# ==============================================================================
#                   Editor Layouts in Wwise
# ==============================================================================

LAYOUTS = ["Designer", "Profiler", "Soundbank", "Mixer", "Audio Object Profiler", "Voice Profiler", "Game Object Profiler"]

def toggle_layout(request_layout : str)->dict:
    
    if request_layout not in LAYOUTS:
        logger.exception("No such layout exists : %r", request_layout)
        
        raise ValueError("toggle_layout can only one of accept these args : " \
        "Designer, Profiler, Soundbank, Mixer, Audio Object Profiler, Voice Profiler, Game Object Profiler. " \
        "They are case sensitive.")
    
    return waapi_call("ak.wwise.ui.layout.switchLayout", {"name": request_layout})
"""Optional Rust command assembly; existing installer/profile owners stay intact.

Compatibility reference: minecraft-launcher-lib 8.0 (BSD-2-Clause).
The pinned reference and license are retained under tests/fixtures/.
No process, network request or installation is performed here.
"""
import copy
import json
import os
import platform


def _rule_list(rules, options, library, native):
    if not hasattr(native, "MINECRAFT_RULES_API_VERSION"):
        return library.parse_rule_list(rules, options)
    if native.MINECRAFT_RULES_API_VERSION != 1:
        raise ImportError("Incompatible NEXUS Minecraft rules API")
    features = [bool(options.get("customResolution", False)), bool(options.get("demo", False)),
                *(options.get(key) is not None for key in
                  ("quickPlayPath", "quickPlaySingleplayer", "quickPlayMultiplayer", "quickPlayRealms"))]
    def architecture():
        return platform.architecture()[0] == "32bit"
    def version(pattern):
        # Invoke only the old regex/OS-version predicate, preserving its engine/errors.
        return library.parse_rule_list([{"action": "allow", "os": {"version": pattern}}], {})
    return native.minecraft_rules_evaluate(
        json.dumps(rules, ensure_ascii=True, allow_nan=False, separators=(",", ":")),
        platform.system(), features, architecture, version)


def _arguments(data, options, library, native):
    result = []
    for value in data:
        if isinstance(value, str):
            result.append(value)
        else:
            if "compatibilityRules" in value and not _rule_list(value["compatibilityRules"], options, library, native):
                continue
            if "rules" in value and not _rule_list(value["rules"], options, library, native):
                continue
            item = value["value"]
            result.extend([item] if isinstance(item, str) else item)
    return result


def _inherit_profile(data, path, library, native):
    """Keep the established one-level file reader; native owns only the merge."""
    if not hasattr(native, "MINECRAFT_PROFILE_API_VERSION"):
        return library.inherit_json(data, path)
    if native.MINECRAFT_PROFILE_API_VERSION != 1:
        raise ImportError("Incompatible NEXUS Minecraft profile API")
    parent_id = data["inheritsFrom"]
    # Match the existing reader's parent selection and default text encoding.
    with open(os.path.join(path, "versions", parent_id, parent_id + ".json")) as stream:
        parent = json.load(stream)
    child_json = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    parent_json = json.dumps(parent, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return json.loads(native.minecraft_inherit_profile(child_json, parent_json))


def _classpath(data, path, library, native):
    if not hasattr(native, "MINECRAFT_CLASSPATH_API_VERSION"):
        return library.get_libraries(data, path)
    if native.MINECRAFT_CLASSPATH_API_VERSION != 1:
        raise ImportError("Incompatible NEXUS Minecraft classpath API")
    selections = []
    for item in data["libraries"]:
        # 8.0 evaluates library rules with empty options, not launch features.
        allowed = "rules" not in item or _rule_list(item["rules"], {}, library, native)
        selections.append(library.get_natives(item) if allowed else None)
    profile = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    entries = native.minecraft_classpath_entries(profile, selections)
    return library.get_classpath_separator().join(os.path.join(path, *entry) for entry in entries)


def get_minecraft_command(version, minecraft_directory, options):
    from nexus_launcher.native_transfer import _native
    import minecraft_launcher_lib
    library = minecraft_launcher_lib.command
    if _native is None or not hasattr(_native, "MINECRAFT_COMMAND_API_VERSION"):
        return library.get_minecraft_command(version, minecraft_directory, options)
    if _native.MINECRAFT_COMMAND_API_VERSION != 1:
        raise ImportError("Incompatible NEXUS Minecraft command API")
    if library.get_library_version() != "8.0":
        raise ImportError("Unsupported minecraft-launcher-lib command contract")
    path = str(minecraft_directory)
    directory = os.path.join(path, "versions", version)
    if not os.path.isdir(directory):
        raise library.VersionNotFound(version)
    with open(os.path.join(directory, version + ".json"), encoding="utf-8") as stream:
        data = json.load(stream)
    if "inheritsFrom" in data:
        data = _inherit_profile(data, path, library, _native)
    options = copy.deepcopy(options)
    natives = options.get("nativesDirectory", os.path.join(path, "versions", data["id"], "natives"))
    options["nativesDirectory"] = natives
    classpath = _classpath(data, path, library, _native)
    if "executablePath" in options:
        executable = options["executablePath"]
    elif "javaVersion" in data:
        executable = library.get_executable_path(data["javaVersion"]["component"], path) or "java"
    else:
        executable = options.get("defaultExecutablePath", "java")
    version_args = data.get("arguments")
    metadata_jvm = (_arguments(version_args["jvm"], options, library, _native)
                    if isinstance(version_args, dict) and "jvm" in version_args else None)
    legacy = "minecraftArguments" in data
    game = data["minecraftArguments"].split(" ") if legacy else _arguments(data["arguments"]["game"], options, library, _native)
    extras = []
    if legacy and options.get("customResolution", False):
        extras.extend(["--width", options.get("resolutionWidth", "854"),
                       "--height", options.get("resolutionHeight", "480")])
    if legacy and options.get("demo", False):
        extras.append("--demo")
    logging = None
    if options.get("enableLoggingConfig", False) and data.get("logging"):
        log = data["logging"]["client"]
        logging = log["argument"].replace("${path}", os.path.join(path, "assets", "log_configs", log["file"]["id"]))
    tail = []
    if "server" in options:
        tail.extend(["--server", options["server"]])
        if "port" in options:
            tail.extend(["--port", options["port"]])
    if options.get("disableMultiplayer", False): tail.append("--disableMultiplayer")
    if options.get("disableChat", False): tail.append("--disableChat")
    replacements = [
        ("${natives_directory}", natives),
        ("${launcher_name}", options.get("launcherName", "minecraft-launcher-lib")),
        ("${launcher_version}", options["launcherVersion"] if "launcherVersion" in options else library.get_library_version()),
        ("${classpath}", classpath),
        ("${auth_player_name}", options.get("username", "{username}")),
        ("${version_name}", data["id"]),
        ("${game_directory}", options.get("gameDirectory", path)),
        ("${assets_root}", os.path.join(path, "assets")),
        ("${assets_index_name}", data.get("assets", data["id"])),
        ("${auth_uuid}", options.get("uuid", "{uuid}")),
        ("${auth_access_token}", options.get("token", "{token}")),
        ("${user_type}", "msa"),
        ("${version_type}", data["type"]),
        ("${user_properties}", "{}"),
        ("${resolution_width}", options.get("resolutionWidth", "854")),
        ("${resolution_height}", options.get("resolutionHeight", "480")),
        ("${game_assets}", os.path.join(path, "assets", "virtual", "legacy")),
        ("${auth_session}", options.get("token", "{token}")),
        ("${library_directory}", os.path.join(path, "libraries")),
        ("${classpath_separator}", library.get_classpath_separator()),
        ("${quickPlayPath}", options.get("quickPlayPath") or "{quickPlayPath}"),
        ("${quickPlaySingleplayer}", options.get("quickPlaySingleplayer") or "{quickPlaySingleplayer}"),
        ("${quickPlayMultiplayer}", options.get("quickPlayMultiplayer") or "{quickPlayMultiplayer}"),
        ("${quickPlayRealms}", options.get("quickPlayRealms") or "{quickPlayRealms}"),
    ]
    return _native.minecraft_compose_command({
        "executable": executable, "user_jvm": options.get("jvmArguments", []),
        "metadata_jvm": metadata_jvm, "fallback_jvm": ["-Djava.library.path=" + natives, "-cp", classpath],
        "main_class": data["mainClass"], "game": game, "replacements": replacements,
        "game_extras": extras, "tail": tail, "logging": logging,
    })

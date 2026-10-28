//! Pure existing launcher policies. No IO, process creation or credentials issuance.

pub const GAME_ENVIRONMENT_KEYS: &[&str] = &[
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "HOME",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "ALLUSERSPROFILE",
    "PUBLIC",
    "USERNAME",
    "USERDOMAIN",
    "OS",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
    "DBUS_SESSION_BUS_ADDRESS",
];

pub fn valid_username(name: &str) -> bool {
    (3..=16).contains(&name.len()) && name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_')
}

/// The adapter supplies uppercase names, retaining its existing Unicode mapping.
/// Values are deliberately never supplied to this policy.
pub fn allowed_environment_key(uppercase: &str) -> bool {
    GAME_ENVIRONMENT_KEYS.contains(&uppercase)
}

/// Preserve the existing exact-argument logging policy, not a universal scrubber.
pub fn redact_command(command: &[String]) -> Vec<String> {
    command
        .iter()
        .enumerate()
        .map(|(index, part)| {
            if part.starts_with("-Dnexus.gameTicket=") {
                "-Dnexus.gameTicket=<redacted>".to_owned()
            } else if index > 0
                && matches!(command[index - 1].as_str(), "--accessToken" | "--clientId")
            {
                "<access-token>".to_owned()
            } else {
                part.clone()
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn username_boundaries() {
        assert!(valid_username("abc"));
        assert!(valid_username("0123456789ABCDEF"));
        for invalid in ["", "ab", "0123456789ABCDEFG", "a-b", "abc\n", "имя"] {
            assert!(!valid_username(invalid));
        }
    }

    #[test]
    fn environment_policy_has_no_injection_or_ticket() {
        assert!(allowed_environment_key("PATH"));
        assert!(allowed_environment_key("XDG_RUNTIME_DIR"));
        for denied in [
            "JAVA_TOOL_OPTIONS",
            "JDK_JAVA_OPTIONS",
            "_JAVA_OPTIONS",
            "NEXUS_GAME_TICKET",
            "PRIVATE_SECRET",
            "path",
        ] {
            assert!(!allowed_environment_key(denied));
        }
    }

    #[test]
    fn redaction_preserves_original_command() {
        let original: Vec<String> = [
            "java",
            "-Dnexus.gameTicket=synthetic",
            "--accessToken",
            "synthetic",
            "--clientId",
            "id",
            "--width",
            "1280",
        ]
        .iter()
        .map(|s| (*s).to_owned())
        .collect();
        let result = redact_command(&original);
        assert_eq!(
            result,
            [
                "java",
                "-Dnexus.gameTicket=<redacted>",
                "--accessToken",
                "<access-token>",
                "--clientId",
                "<access-token>",
                "--width",
                "1280"
            ]
        );
        assert_eq!(original[1], "-Dnexus.gameTicket=synthetic");
    }
}

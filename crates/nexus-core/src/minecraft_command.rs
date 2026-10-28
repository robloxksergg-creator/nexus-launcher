//! Pure command assembly. No profile IO, installation, authentication or spawn.
use std::fmt;

const MAX_ARGUMENT: usize = 1024 * 1024;
const MAX_COMMAND: usize = 16 * 1024 * 1024;
const MAX_PARTS: usize = 10_000;

// Intentionally not Debug: fields can contain credentials supplied by the owner.
pub struct CommandPlan {
    pub executable: String,
    pub user_jvm: Vec<String>,
    pub metadata_jvm: Option<Vec<String>>,
    pub fallback_jvm: Vec<String>,
    pub main_class: String,
    pub game: Vec<String>,
    pub replacements: Vec<(String, String)>,
    pub game_extras: Vec<String>,
    pub tail: Vec<String>,
    pub logging: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandError {
    InvalidInput,
    TooLarge,
}
impl fmt::Display for CommandError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::InvalidInput => "Invalid Minecraft command input",
            Self::TooLarge => "Minecraft command budget exceeded",
        })
    }
}
impl std::error::Error for CommandError {}

fn check(value: &str) -> Result<(), CommandError> {
    if value.contains('\0') {
        return Err(CommandError::InvalidInput);
    }
    if value.len() > MAX_ARGUMENT {
        return Err(CommandError::TooLarge);
    }
    Ok(())
}
fn expand(mut value: String, replacements: &[(String, String)]) -> Result<String, CommandError> {
    for (pattern, replacement) in replacements {
        let count = value.matches(pattern.as_str()).count();
        let removed = count
            .checked_mul(pattern.len())
            .ok_or(CommandError::TooLarge)?;
        let added = count
            .checked_mul(replacement.len())
            .ok_or(CommandError::TooLarge)?;
        let size = value
            .len()
            .checked_sub(removed)
            .and_then(|v| v.checked_add(added))
            .ok_or(CommandError::TooLarge)?;
        if size > MAX_ARGUMENT {
            return Err(CommandError::TooLarge);
        }
        if count != 0 {
            value = value.replace(pattern, replacement);
        }
    }
    Ok(value)
}
fn push(out: &mut Vec<String>, size: &mut usize, value: String) -> Result<(), CommandError> {
    check(&value)?;
    let total = size
        .checked_add(value.len())
        .ok_or(CommandError::TooLarge)?;
    if total > MAX_COMMAND || out.len() >= MAX_PARTS {
        return Err(CommandError::TooLarge);
    }
    *size = total;
    out.push(value);
    Ok(())
}

pub fn compose(plan: CommandPlan) -> Result<Vec<String>, CommandError> {
    if plan.executable.is_empty() || plan.main_class.is_empty() || plan.replacements.len() > 64 {
        return Err(CommandError::InvalidInput);
    }
    let mut input_size = 0_usize;
    let mut input_count = 0_usize;
    for value in std::iter::once(&plan.executable)
        .chain(std::iter::once(&plan.main_class))
        .chain(plan.user_jvm.iter())
        .chain(plan.metadata_jvm.iter().flatten())
        .chain(plan.fallback_jvm.iter())
        .chain(plan.game.iter())
        .chain(plan.game_extras.iter())
        .chain(plan.tail.iter())
        .chain(plan.logging.iter())
        .chain(plan.replacements.iter().flat_map(|(a, b)| [a, b]))
    {
        check(value)?;
        input_size = input_size
            .checked_add(value.len())
            .ok_or(CommandError::TooLarge)?;
        input_count += 1;
        if input_size > MAX_COMMAND || input_count > MAX_PARTS {
            return Err(CommandError::TooLarge);
        }
    }
    if plan
        .replacements
        .iter()
        .any(|(pattern, _)| pattern.is_empty())
    {
        return Err(CommandError::InvalidInput);
    }
    let CommandPlan {
        executable,
        user_jvm,
        metadata_jvm,
        fallback_jvm,
        main_class,
        game,
        replacements,
        game_extras,
        tail,
        logging,
    } = plan;
    let mut result = Vec::new();
    let mut size = 0;
    push(&mut result, &mut size, executable)?;
    for value in user_jvm {
        push(&mut result, &mut size, value)?;
    }
    match metadata_jvm {
        Some(values) => {
            for value in values {
                push(&mut result, &mut size, expand(value, &replacements)?)?;
            }
        }
        None => {
            for value in fallback_jvm {
                push(&mut result, &mut size, value)?;
            }
        }
    }
    if let Some(value) = logging {
        push(&mut result, &mut size, value)?;
    }
    push(&mut result, &mut size, main_class)?;
    for value in game {
        push(&mut result, &mut size, expand(value, &replacements)?)?;
    }
    for value in game_extras.into_iter().chain(tail) {
        push(&mut result, &mut size, value)?;
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn plan() -> CommandPlan {
        CommandPlan {
            executable: "java".into(),
            main_class: "Main".into(),
            user_jvm: vec!["${a}".into()],
            metadata_jvm: None,
            fallback_jvm: vec!["-cp".into(), "libraries".into()],
            game: vec!["${a}".into()],
            replacements: vec![
                ("${a}".into(), "${b}".into()),
                ("${b}".into(), "resolved".into()),
            ],
            game_extras: vec!["${a}".into()],
            tail: vec!["--server".into(), "localhost".into()],
            logging: Some("-Dlog=config".into()),
        }
    }
    #[test]
    fn expands_only_metadata_in_original_order() {
        assert_eq!(
            compose(plan()).unwrap(),
            [
                "java",
                "${a}",
                "-cp",
                "libraries",
                "-Dlog=config",
                "Main",
                "resolved",
                "${a}",
                "--server",
                "localhost"
            ]
        );
    }
    #[test]
    fn explicit_empty_jvm_does_not_add_fallback() {
        let mut value = plan();
        value.metadata_jvm = Some(vec![]);
        assert!(!compose(value).unwrap().contains(&"-cp".to_owned()));
    }
    #[test]
    fn refuses_nul_and_expansion_before_large_allocation() {
        let mut value = plan();
        value.main_class = "Bad\0Class".into();
        assert_eq!(compose(value), Err(CommandError::InvalidInput));
        let mut value = plan();
        value.game = vec!["${a}".repeat(1024)];
        value.replacements = vec![("${a}".into(), "x".repeat(2048))];
        assert_eq!(compose(value), Err(CommandError::TooLarge));
    }
}

//! Pure 8.0-compatible rule control flow. Host predicates do not grant authority.
use serde::de::{MapAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::value::RawValue;
use std::collections::BTreeMap;
use std::fmt;

const MAX_INPUT: usize = 1024 * 1024;
const MAX_RULES: usize = 1024;
const FEATURES: [&str; 6] = [
    "has_custom_resolution",
    "is_demo_user",
    "has_quick_plays_support",
    "is_quick_play_singleplayer",
    "is_quick_play_multiplayer",
    "is_quick_play_realms",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuleError {
    InvalidInput,
    HostPredicate,
}
impl fmt::Display for RuleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::InvalidInput => "Invalid or oversized Minecraft rule input",
            Self::HostPredicate => "Minecraft rule host predicate failed",
        })
    }
}
impl std::error::Error for RuleError {}

pub trait RuleHost {
    fn is_32bit(&mut self) -> Result<bool, RuleError>;
    fn version_matches(&mut self, pattern: &str) -> Result<bool, RuleError>;
}

type Object<'a> = BTreeMap<String, &'a RawValue>;
struct OrderedFields<'a>(Vec<(String, &'a RawValue)>);
impl<'de> Deserialize<'de> for OrderedFields<'de> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct FieldsVisitor;
        impl<'de> Visitor<'de> for FieldsVisitor {
            type Value = OrderedFields<'de>;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("ordered OS rule fields")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut fields = Vec::new();
                while let Some(field) = map.next_entry::<String, &'de RawValue>()? {
                    fields.push(field);
                }
                Ok(OrderedFields(fields))
            }
        }
        deserializer.deserialize_map(FieldsVisitor)
    }
}

fn text(raw: &RawValue) -> Result<String, RuleError> {
    serde_json::from_str(raw.get()).map_err(|_| RuleError::InvalidInput)
}

fn single(
    raw: &RawValue,
    system: &str,
    features: &[bool; 6],
    host: &mut impl RuleHost,
) -> Result<bool, RuleError> {
    let rule: Object<'_> = serde_json::from_str(raw.get()).map_err(|_| RuleError::InvalidInput)?;
    let allow = match text(rule.get("action").ok_or(RuleError::InvalidInput)?)?.as_str() {
        "allow" => true,
        "disallow" => false,
        _ => return Err(RuleError::InvalidInput),
    };
    if let Some(os) = rule.get("os") {
        let fields: OrderedFields<'_> =
            serde_json::from_str(os.get()).map_err(|_| RuleError::InvalidInput)?;
        // Preserve JSON insertion order, including short-circuit before regex errors.
        for (key, value) in fields.0 {
            let matches = match key.as_str() {
                "name" => match text(value)?.as_str() {
                    "windows" => system == "Windows",
                    "osx" => system == "Darwin",
                    "linux" => system == "Linux",
                    _ => true,
                },
                "arch" => text(value)? != "x86" || host.is_32bit()?,
                "version" => host.version_matches(&text(value)?)?,
                _ => true,
            };
            if !matches {
                return Ok(!allow);
            }
        }
    }
    if let Some(raw_features) = rule.get("features") {
        let fields: Object<'_> =
            serde_json::from_str(raw_features.get()).map_err(|_| RuleError::InvalidInput)?;
        for key in fields.keys() {
            // Intentionally ignore feature values, matching the pinned 8.0 code.
            if let Some(index) = FEATURES.iter().position(|name| name == key)
                && !features[index]
            {
                return Ok(!allow);
            }
        }
    }
    Ok(allow)
}

/// Feature flags are normalized by the existing options owner. Architecture and
/// regex predicates are requested only if reached, not speculatively evaluated.
pub fn evaluate(
    rules_json: &str,
    system: &str,
    features: &[bool; 6],
    host: &mut impl RuleHost,
) -> Result<bool, RuleError> {
    if rules_json.len() > MAX_INPUT || system.len() > 128 || system.contains('\0') {
        return Err(RuleError::InvalidInput);
    }
    let rules: Vec<&RawValue> =
        serde_json::from_str(rules_json).map_err(|_| RuleError::InvalidInput)?;
    if rules.len() > MAX_RULES {
        return Err(RuleError::InvalidInput);
    }
    for rule in rules {
        if !single(rule, system, features, host)? {
            return Ok(false);
        }
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Host(Vec<&'static str>);
    impl RuleHost for Host {
        fn is_32bit(&mut self) -> Result<bool, RuleError> {
            self.0.push("arch");
            Ok(false)
        }
        fn version_matches(&mut self, _: &str) -> Result<bool, RuleError> {
            self.0.push("version");
            Err(RuleError::HostPredicate)
        }
    }

    #[test]
    fn order_short_circuit_and_all_rule_semantics() {
        let mut host = Host(Vec::new());
        let input = r#"[{"action":"allow","os":{"name":"linux","version":"["}}]"#;
        assert_eq!(
            evaluate(input, "Windows", &[false; 6], &mut host),
            Ok(false)
        );
        assert!(host.0.is_empty());
        let input = r#"[{"action":"allow","os":{"version":"[","name":"linux"}}]"#;
        assert_eq!(
            evaluate(input, "Windows", &[false; 6], &mut host),
            Err(RuleError::HostPredicate)
        );
        assert_eq!(host.0, ["version"]);
        assert_eq!(
            evaluate(
                r#"[{"action":"disallow"},{"action":"allow"}]"#,
                "Windows",
                &[true; 6],
                &mut host
            ),
            Ok(false)
        );
    }

    #[test]
    fn feature_values_empty_list_and_invalid_input() {
        let mut host = Host(Vec::new());
        let input = r#"[{"action":"allow","features":{"is_demo_user":false,"future":true}}]"#;
        assert_eq!(
            evaluate(input, "Windows", &[false; 6], &mut host),
            Ok(false)
        );
        assert_eq!(evaluate(input, "Windows", &[true; 6], &mut host), Ok(true));
        assert_eq!(evaluate("[]", "Windows", &[false; 6], &mut host), Ok(true));
        assert!(evaluate(r#"[{"action":"other"}]"#, "Windows", &[false; 6], &mut host).is_err());
        assert!(
            evaluate(
                &" ".repeat(MAX_INPUT + 1),
                "Windows",
                &[false; 6],
                &mut host
            )
            .is_err()
        );
    }
}

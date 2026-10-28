//! Pure catalog JSON preflight. No storage, UI, permissions or write authority.
//! Raw values retain unknown fields and arbitrary-size JSON integer text.
use serde::de::{self, MapAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::value::RawValue;
use std::collections::{BTreeMap, HashSet};
use std::fmt;

type Object<'a> = BTreeMap<String, &'a RawValue>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CatalogError {
    InvalidJson,
    Conflict,
    InvalidIdentity,
    UnsupportedVersion,
    DepthExceeded,
}

impl fmt::Display for CatalogError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::InvalidJson => "Invalid catalog JSON",
            Self::Conflict => "Conflicting catalog data",
            Self::InvalidIdentity => "Invalid catalog identity",
            Self::UnsupportedVersion => "Unsupported catalog version",
            Self::DepthExceeded => "Catalog nesting limit exceeded",
        })
    }
}
impl std::error::Error for CatalogError {}

struct UniqueObject<'a>(Object<'a>);
impl<'de> Deserialize<'de> for UniqueObject<'de> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ObjectVisitor;
        impl<'de> Visitor<'de> for ObjectVisitor {
            type Value = UniqueObject<'de>;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("an object with unique keys")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut values = BTreeMap::new();
                while let Some(key) = map.next_key::<String>()? {
                    if values.contains_key(&key) {
                        return Err(de::Error::custom("Duplicate catalog field"));
                    }
                    values.insert(key, map.next_value::<&'de RawValue>()?);
                }
                Ok(UniqueObject(values))
            }
        }
        deserializer.deserialize_map(ObjectVisitor)
    }
}

fn object(raw: &str) -> Result<Object<'_>, CatalogError> {
    serde_json::from_str::<UniqueObject<'_>>(raw)
        .map(|value| value.0)
        .map_err(|_| CatalogError::InvalidJson)
}
fn array(raw: &str) -> Result<Vec<&RawValue>, CatalogError> {
    serde_json::from_str(raw).map_err(|_| CatalogError::InvalidJson)
}
fn text(raw: &str) -> Result<String, CatalogError> {
    serde_json::from_str(raw).map_err(|_| CatalogError::InvalidIdentity)
}
fn raw_kind(raw: &str) -> u8 {
    match raw.as_bytes().first() {
        Some(b'{') => b'o',
        Some(b'[') => b'a',
        Some(b'"') => b's',
        Some(b't' | b'f') => b'b',
        Some(b'n') => b'z',
        _ => b'n',
    }
}

// RawValue avoids numeric conversion, but does not check repeated nested keys.
fn validate(raw: &str, depth: usize) -> Result<(), CatalogError> {
    if depth > 128 {
        return Err(CatalogError::DepthExceeded);
    }
    match raw_kind(raw) {
        b'o' => {
            for value in object(raw)?.values() {
                validate(value.get(), depth + 1)?;
            }
        }
        b'a' => {
            for value in array(raw)? {
                validate(value.get(), depth + 1)?;
            }
        }
        b's' => {
            text(raw)?;
        }
        _ => {}
    }
    Ok(())
}

// Match the existing Python canonical-JSON equality: object ordering/whitespace
// do not matter; integer/float/bool types and float signed zero do matter.
fn equal(a: &str, b: &str) -> Result<bool, CatalogError> {
    let kind = raw_kind(a);
    if kind != raw_kind(b) {
        return Ok(false);
    }
    Ok(match kind {
        b'o' => {
            let a = object(a)?;
            let b = object(b)?;
            if a.len() != b.len() {
                return Ok(false);
            }
            for (key, value) in a {
                let Some(other) = b.get(&key) else {
                    return Ok(false);
                };
                if !equal(value.get(), other.get())? {
                    return Ok(false);
                }
            }
            true
        }
        b'a' => {
            let a = array(a)?;
            let b = array(b)?;
            if a.len() != b.len() {
                return Ok(false);
            }
            for (value, other) in a.iter().zip(&b) {
                if !equal(value.get(), other.get())? {
                    return Ok(false);
                }
            }
            true
        }
        b's' => text(a)? == text(b)?,
        b'n' => {
            let floating = |s: &str| s.contains(['.', 'e', 'E']);
            if floating(a) != floating(b) {
                return Ok(false);
            }
            if floating(a) {
                let number = |s: &str| {
                    s.parse::<f64>()
                        .map(f64::to_bits)
                        .map_err(|_| CatalogError::InvalidJson)
                };
                number(a)? == number(b)?
            } else {
                let a = if a == "-0" { "0" } else { a };
                let b = if b == "-0" { "0" } else { b };
                a == b
            }
        }
        _ => a == b,
    })
}

fn string_id(value: Option<&RawValue>, fallback: String) -> Result<String, CatalogError> {
    value.map_or(Ok(fallback), |raw| text(raw.get()))
}
fn canonical_id(id: String) -> String {
    if id == "nexus_launcher.main" {
        "main".to_owned()
    } else {
        id
    }
}

pub fn preflight_json(input: &str) -> Result<String, CatalogError> {
    let whole: &RawValue = serde_json::from_str(input).map_err(|_| CatalogError::InvalidJson)?;
    validate(whole.get(), 0)?;
    let mut root = object(whole.get())?;
    if let Some(version) = root.get("format")
        && !matches!(version.get(), "1" | "2")
    {
        return Err(CatalogError::UnsupportedVersion);
    }
    if let (Some(old), Some(new)) = (root.get("projects"), root.get("nexus_launcher.projects"))
        && !equal(old.get(), new.get())?
    {
        return Err(CatalogError::Conflict);
    }
    let projects = match root
        .remove("projects")
        .or_else(|| root.remove("nexus_launcher.projects"))
    {
        Some(projects) => projects,
        None => serde_json::from_str::<&RawValue>("[]").map_err(|_| CatalogError::InvalidJson)?,
    };
    let mut project_ids = HashSet::new();
    for project in array(projects.get())? {
        let fields = object(project.get())?;
        let id = fields.get("id").ok_or(CatalogError::InvalidIdentity)?;
        let id = text(id.get())?;
        if !project_ids.insert(id) {
            return Err(CatalogError::Conflict);
        }
        let servers = match fields.get("servers") {
            Some(servers) if servers.get() != "null" => array(servers.get())?,
            _ => vec![project],
        };
        let mut server_ids = HashSet::new();
        for (index, server) in servers.iter().enumerate() {
            let fields = object(server.get())?;
            let id = canonical_id(string_id(
                fields.get("id").copied(),
                format!("server-{}", index + 1),
            )?);
            if !server_ids.insert(id) {
                return Err(CatalogError::Conflict);
            }
        }
    }
    root.remove("nexus_launcher.projects");
    root.insert("projects".to_owned(), projects);
    serde_json::to_string(&root).map_err(|_| CatalogError::InvalidJson)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn retains_unknown_large_numbers() {
        let raw = r#"{"projects":[],"future":{"integer":123456789012345678901234567890,"$serde_json::private::Number":"keep"}}"#;
        let result = preflight_json(raw).unwrap();
        assert!(result.contains("123456789012345678901234567890"));
        assert!(result.contains("$serde_json::private::Number"));
    }
    #[test]
    fn refuses_duplicate_fields_and_alias_collisions() {
        for raw in [
            r#"{"projects":[],"projects":[]}"#,
            r#"{"projects":[{"id":"x","servers":[{"id":"main"},{"id":"nexus_launcher.main"}]}]}"#,
        ] {
            assert!(preflight_json(raw).is_err());
        }
    }
    #[test]
    fn dual_keys_are_type_sensitive_and_order_independent() {
        assert!(preflight_json(r#"{"projects":[{"id":"x","extra":{"a":1,"b":2}}],"nexus_launcher.projects":[{"extra":{"b":2,"a":1},"id":"x"}]}"#).is_ok());
        assert_eq!(
            preflight_json(r#"{"projects":[],"nexus_launcher.projects":[{}]}"#),
            Err(CatalogError::Conflict)
        );
        assert!(!equal("1", "1.0").unwrap());
        assert!(!equal("true", "1").unwrap());
        assert!(equal("1e0", "1.0").unwrap());
        assert!(!equal("-0.0", "0.0").unwrap());
    }
}

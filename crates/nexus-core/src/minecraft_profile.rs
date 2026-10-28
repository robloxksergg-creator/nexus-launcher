//! One-level profile inheritance, compatible with the pinned 8.0 merge rules.
//! Pure JSON transformation: no paths, profile reads, rules, installation or spawn.
use serde_json::value::RawValue;
use std::collections::{BTreeMap, HashSet};
use std::fmt;
use std::io::{self, Write};

const INPUT_LIMIT: usize = 8 * 1024 * 1024;
const OUTPUT_LIMIT: usize = 16 * 1024 * 1024;
const LIBRARY_LIMIT: usize = 10_000;
type Object = BTreeMap<String, Box<RawValue>>;
type Array = Vec<Box<RawValue>>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProfileError;
impl fmt::Display for ProfileError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Invalid or oversized Minecraft inheritance input")
    }
}
impl std::error::Error for ProfileError {}

fn object(raw: &str) -> Result<Object, ProfileError> {
    serde_json::from_str(raw).map_err(|_| ProfileError)
}
fn array(raw: &RawValue) -> Result<Array, ProfileError> {
    serde_json::from_str(raw.get()).map_err(|_| ProfileError)
}
fn raw<T: serde::Serialize>(value: &T) -> Result<Box<RawValue>, ProfileError> {
    serde_json::value::to_raw_value(value).map_err(|_| ProfileError)
}
fn library_key(value: &RawValue) -> Result<String, ProfileError> {
    let lib = object(value.get())?;
    let name: String = serde_json::from_str(lib.get("name").ok_or(ProfileError)?.get())
        .map_err(|_| ProfileError)?;
    // Match 8.0 exactly, including its classifier/version slicing behavior.
    Ok(name.rsplit_once(':').map_or("", |(key, _)| key).to_owned())
}

struct LimitedOutput(Vec<u8>);
impl Write for LimitedOutput {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > OUTPUT_LIMIT.saturating_sub(self.0.len()) {
            return Err(io::Error::other("Profile output limit"));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

/// Inputs are decoded JSON objects supplied by the existing profile reader.
/// Unknown values remain opaque raw JSON, including arbitrary-size numbers.
/// Parent selection/readback and duplicate-key policy belong to that reader.
pub fn inherit(child_json: &str, parent_json: &str) -> Result<String, ProfileError> {
    if child_json.len() > INPUT_LIMIT || parent_json.len() > INPUT_LIMIT {
        return Err(ProfileError);
    }
    let child = object(child_json)?;
    let mut parent = object(parent_json)?;
    let inherit_id: String =
        serde_json::from_str(child.get("inheritsFrom").ok_or(ProfileError)?.get())
            .map_err(|_| ProfileError)?;
    if inherit_id.is_empty() {
        return Err(ProfileError);
    }
    let mut libraries = match child.get("libraries") {
        Some(value) => array(value)?,
        None => Vec::new(),
    };
    let parent_libraries = array(parent.get("libraries").ok_or(ProfileError)?)?;
    if libraries.len() + parent_libraries.len() > LIBRARY_LIMIT {
        return Err(ProfileError);
    }
    let identities: HashSet<String> = libraries
        .iter()
        .map(|lib| library_key(lib))
        .collect::<Result<_, _>>()?;
    for lib in parent_libraries {
        // Do not add parent identities to this set: 8.0 retains parent duplicates.
        if !identities.contains(&library_key(&lib)?) {
            libraries.push(lib);
        }
    }
    parent.insert("libraries".into(), raw(&libraries)?);
    for (key, value) in child {
        if key == "libraries" {
            continue;
        }
        match (
            value.get().trim_start().as_bytes().first(),
            parent.get(&key),
        ) {
            (Some(b'['), Some(old)) if old.get().trim_start().starts_with('[') => {
                let mut items = array(&value)?;
                items.extend(array(old)?);
                parent.insert(key, raw(&items)?);
            }
            (Some(b'{'), Some(old)) if old.get().trim_start().starts_with('{') => {
                let mut fields = object(old.get())?;
                for (name, item) in object(value.get())? {
                    if item.get().trim_start().starts_with('[') {
                        let mut items = array(fields.get(&name).ok_or(ProfileError)?)?;
                        items.extend(array(&item)?);
                        fields.insert(name, raw(&items)?);
                    }
                    // Child scalar/dict subfields are intentionally ignored by 8.0.
                }
                parent.insert(key, raw(&fields)?);
            }
            _ => {
                parent.insert(key, value);
            }
        }
    }
    let mut output = LimitedOutput(Vec::new());
    serde_json::to_writer(&mut output, &parent).map_err(|_| ProfileError)?;
    String::from_utf8(output.0).map_err(|_| ProfileError)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn merge_order_and_opaque_numbers() {
        let child = r#"{"inheritsFrom":"base","libraries":[{"name":"g:a:2"}],"items":["child"],"arguments":{"game":["child"],"scalar":"ignored"},"opaque":123456789012345678901234567890}"#;
        let parent = r#"{"libraries":[{"name":"g:a:1"},{"name":"g:b:1"}],"items":["parent"],"arguments":{"game":["parent"],"scalar":"kept"}}"#;
        let merged = object(&inherit(child, parent).unwrap()).unwrap();
        assert_eq!(merged["items"].get(), r#"["child","parent"]"#);
        assert_eq!(merged["opaque"].get(), "123456789012345678901234567890");
        let args = object(merged["arguments"].get()).unwrap();
        assert_eq!(args["game"].get(), r#"["parent","child"]"#);
        assert_eq!(args["scalar"].get(), r#""kept""#);
        assert_eq!(array(&merged["libraries"]).unwrap().len(), 2);
    }

    #[test]
    fn invalid_shapes_and_budgets_refuse() {
        for child in [
            "null",
            "{}",
            r#"{"inheritsFrom":1}"#,
            r#"{"inheritsFrom":"x","libraries":null}"#,
        ] {
            assert_eq!(inherit(child, r#"{"libraries":[]}"#), Err(ProfileError));
        }
        assert_eq!(
            inherit(&" ".repeat(INPUT_LIMIT + 1), "{}"),
            Err(ProfileError)
        );
        let mut out = LimitedOutput(Vec::new());
        out.0.resize(OUTPUT_LIMIT, 0);
        assert!(out.write_all(b"x").is_err());
    }
}

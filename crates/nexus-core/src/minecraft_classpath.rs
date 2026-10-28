//! Pure classpath entry planning for the pinned 8.0 contract.
//! The caller owns OS/rule/native-classifier selection and OS path rendering.
use serde_json::value::RawValue;
use std::collections::BTreeMap;
use std::fmt;

const MAX_INPUT: usize = 8 * 1024 * 1024;
const MAX_LIBRARIES: usize = 10_000;
const MAX_COMPONENT: usize = 1024 * 1024;
const MAX_OUTPUT: usize = 16 * 1024 * 1024;
type Object<'a> = BTreeMap<String, &'a RawValue>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClasspathError;
impl fmt::Display for ClasspathError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Invalid or oversized Minecraft classpath input")
    }
}
impl std::error::Error for ClasspathError {}

fn object(raw: &str) -> Result<Object<'_>, ClasspathError> {
    serde_json::from_str(raw).map_err(|_| ClasspathError)
}
fn text(raw: &RawValue) -> Result<String, ClasspathError> {
    let value: String = serde_json::from_str(raw.get()).map_err(|_| ClasspathError)?;
    check(&value)?;
    Ok(value)
}
fn check(value: &str) -> Result<(), ClasspathError> {
    if value.contains('\0') || value.len() > MAX_COMPONENT {
        return Err(ClasspathError);
    }
    Ok(())
}

fn maven(name: &str) -> Result<Vec<String>, ClasspathError> {
    check(name)?;
    let mut split = name.split('@');
    let coordinate = split.next().ok_or(ClasspathError)?;
    let extension = split.next().unwrap_or("jar");
    if split.next().is_some() {
        return Err(ClasspathError);
    }
    let parts: Vec<&str> = coordinate.split(':').take(65).collect();
    if parts.len() < 3 || parts.len() > 64 || parts[0].split('.').count() > 250 {
        return Err(ClasspathError);
    }
    let mut result = vec!["libraries".to_owned()];
    result.extend(parts[0].split('.').map(str::to_owned));
    result.extend([parts[1].to_owned(), parts[2].to_owned()]);
    let mut filename = format!("{}-{}", parts[1], parts[2]);
    for classifier in &parts[3..] {
        filename.push('-');
        filename.push_str(classifier);
    }
    filename.push('.');
    filename.push_str(extension);
    check(&filename)?;
    result.push(filename);
    Ok(result)
}

fn push(
    result: &mut Vec<Vec<String>>,
    size: &mut usize,
    entry: Vec<String>,
) -> Result<(), ClasspathError> {
    for component in &entry {
        check(component)?;
        *size = size.checked_add(component.len()).ok_or(ClasspathError)?;
        if *size > MAX_OUTPUT {
            return Err(ClasspathError);
        }
    }
    result.push(entry);
    Ok(())
}

/// None means the existing rule owner excluded this library; Some contains its
/// already-selected native classifier (empty means no native). No rules/grants
/// are inferred from these supplied selections. Returns ordered path components,
/// not canonicalized paths or proof of containment/existence/loadability.
pub fn entries(
    profile_json: &str,
    selections: &[Option<String>],
) -> Result<Vec<Vec<String>>, ClasspathError> {
    if profile_json.len() > MAX_INPUT || selections.len() > MAX_LIBRARIES {
        return Err(ClasspathError);
    }
    let data = object(profile_json)?;
    let libraries: Vec<&RawValue> =
        serde_json::from_str(data.get("libraries").ok_or(ClasspathError)?.get())
            .map_err(|_| ClasspathError)?;
    if libraries.len() != selections.len() {
        return Err(ClasspathError);
    }
    let mut result = Vec::new();
    let mut size = 0;
    for (raw, selection) in libraries.iter().zip(selections) {
        let Some(native) = selection else { continue };
        check(native)?;
        let library = object(raw.get())?;
        let name = text(library.get("name").ok_or(ClasspathError)?)?;
        push(&mut result, &mut size, maven(&name)?)?;
        if !native.is_empty() {
            let path = if let Some(downloads) = library.get("downloads") {
                let downloads = object(downloads.get())?;
                let classifiers =
                    object(downloads.get("classifiers").ok_or(ClasspathError)?.get())?;
                let classifier = object(classifiers.get(native).ok_or(ClasspathError)?.get())?;
                classifier
                    .get("path")
                    .map(|value| text(value))
                    .transpose()?
            } else {
                None
            };
            let entry = match path {
                Some(path) => vec!["libraries".to_owned(), path],
                // Deliberately match 8.0's name + '-' + native fallback,
                // including its behavior when the coordinate has an @extension.
                None => maven(&format!("{name}-{native}"))?,
            };
            push(&mut result, &mut size, entry)?;
        }
    }
    let jar = text(
        data.get("jar")
            .or_else(|| data.get("id"))
            .ok_or(ClasspathError)?,
    )?;
    push(
        &mut result,
        &mut size,
        vec!["versions".to_owned(), jar.clone(), format!("{jar}.jar")],
    )?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maven_classifier_extension_and_order() {
        let profile = r#"{"id":"client","jar":"base","libraries":[{"name":"g.sub:a:1:extra@zip"},{"name":"g:b:2"}]}"#;
        let planned = entries(profile, &[Some("native".into()), None]).unwrap();
        assert_eq!(
            planned[0],
            ["libraries", "g", "sub", "a", "1", "a-1-extra.zip"]
        );
        assert_eq!(
            planned[1],
            ["libraries", "g", "sub", "a", "1", "a-1-extra.zip-native"]
        );
        assert_eq!(planned[2], ["versions", "base", "base.jar"]);
    }

    #[test]
    fn downloads_path_and_failures() {
        let profile = r#"{"id":"client","libraries":[{"name":"g:a:1","downloads":{"classifiers":{"native":{"path":"g/a/native.jar"}}}}]}"#;
        assert_eq!(
            entries(profile, &[Some("native".into())]).unwrap()[1],
            ["libraries", "g/a/native.jar"]
        );
        assert!(entries(profile, &[]).is_err());
        assert!(entries(profile, &[Some("missing".into())]).is_err());
        assert!(maven("missing-version").is_err());
        assert!(maven("g:a:1@zip@jar").is_err());
        assert!(maven("g:a:\0").is_err());
        assert!(entries(&" ".repeat(MAX_INPUT + 1), &[]).is_err());
    }
}

//! Public, credential-free HTTPS downloads. No install paths or filesystem writes.
#![forbid(unsafe_code)]

use reqwest::{Client, Url, header};
use std::collections::BTreeSet;
use std::fmt;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::runtime::Runtime;

pub const MAX_READ_BYTES: usize = 1024 * 1024;
const MAX_BODY_BYTES: u64 = 1024 * 1024 * 1024;
const MAX_REDIRECTS: usize = 10;
const TOTAL_TIMEOUT: Duration = Duration::from_secs(300);

#[derive(Debug, PartialEq, Eq)]
pub enum DownloadError {
    Policy(&'static str),
    Http(u16),
    Timeout,
    Network,
    Closed,
    TooLarge,
}

impl fmt::Display for DownloadError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Policy(message) => f.write_str(message),
            Self::Http(status) => write!(f, "HTTP download failed: {status}"),
            Self::Timeout => f.write_str("HTTPS download timed out"),
            Self::Network => f.write_str("HTTPS transport or certificate verification failed"),
            Self::Closed => f.write_str("HTTPS response is closed"),
            Self::TooLarge => f.write_str("HTTPS response exceeds byte limit"),
        }
    }
}

impl std::error::Error for DownloadError {}

fn network_error(error: reqwest::Error) -> DownloadError {
    // Reqwest errors may include a signed URL/query. Never expose it to logs.
    if error.is_timeout() {
        DownloadError::Timeout
    } else {
        DownloadError::Network
    }
}

/// Validate the exact origin before DNS/connect, and again for every redirect.
pub fn validate_url(text: &str, hosts: &BTreeSet<String>) -> Result<Url, DownloadError> {
    if text.len() > 16 * 1024 || text.bytes().any(|c| c <= b' ' || c == b'\\' || c == 127) {
        return Err(DownloadError::Policy("Invalid download URL"));
    }
    let url = Url::parse(text).map_err(|_| DownloadError::Policy("Invalid download URL"))?;
    if url.scheme() != "https"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
        || url.port_or_known_default() != Some(443)
    {
        return Err(DownloadError::Policy(
            "Only credential-free HTTPS on port 443 is allowed",
        ));
    }
    if !url.host_str().is_some_and(|host| hosts.contains(host)) {
        return Err(DownloadError::Policy("Download origin is not allowed"));
    }
    Ok(url)
}

fn request_headers(values: &[(String, String)]) -> Result<header::HeaderMap, DownloadError> {
    let mut headers = header::HeaderMap::new();
    for (name, value) in values {
        let name = header::HeaderName::from_bytes(name.as_bytes())
            .map_err(|_| DownloadError::Policy("Invalid download header"))?;
        if !matches!(name.as_str(), "user-agent" | "accept" | "range") {
            return Err(DownloadError::Policy(
                "Header is not allowed for public downloads",
            ));
        }
        if headers.contains_key(&name) {
            return Err(DownloadError::Policy("Duplicate download header"));
        }
        if value.len() > 16 * 1024 {
            return Err(DownloadError::Policy("Download header exceeds byte limit"));
        }
        if name == header::RANGE
            && value
                .strip_prefix("bytes=")
                .and_then(|v| v.strip_suffix('-'))
                .is_none_or(|v| {
                    v.is_empty()
                        || !v.bytes().all(|c| c.is_ascii_digit())
                        || v.parse::<u64>().is_err()
                })
        {
            return Err(DownloadError::Policy(
                "Only a single open-ended byte range is allowed",
            ));
        }
        let value = header::HeaderValue::from_str(value)
            .map_err(|_| DownloadError::Policy("Invalid download header"))?;
        headers.insert(name, value);
    }
    headers.insert(
        header::ACCEPT_ENCODING,
        header::HeaderValue::from_static("identity"),
    );
    Ok(headers)
}

/// One runtime and one pooled client per engine, reused for all pack requests.
#[derive(Clone)]
pub struct DownloadClient {
    client: Client,
    runtime: Arc<Runtime>,
}

impl DownloadClient {
    pub fn new() -> Result<Self, DownloadError> {
        let runtime = Arc::new(
            tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .enable_all()
                .build()
                .map_err(|_| DownloadError::Network)?,
        );
        let _guard = runtime.enter();
        let client = Client::builder()
            .https_only(true)
            .min_tls_version(reqwest::tls::Version::TLS_1_2)
            .redirect(reqwest::redirect::Policy::none())
            .referer(false)
            .connect_timeout(Duration::from_secs(60))
            .pool_max_idle_per_host(4)
            .pool_idle_timeout(Duration::from_secs(60))
            .http2_max_header_list_size(16 * 1024)
            .build()
            .map_err(network_error)?;
        drop(_guard);
        Ok(Self { client, runtime })
    }

    pub fn open(
        &self,
        text: &str,
        hosts: Vec<String>,
        headers: Vec<(String, String)>,
        idle_timeout: f64,
    ) -> Result<DownloadResponse, DownloadError> {
        if !idle_timeout.is_finite() || idle_timeout <= 0.0 || idle_timeout > 300.0 {
            return Err(DownloadError::Policy(
                "Download timeout must be within (0, 300] seconds",
            ));
        }
        let hosts: BTreeSet<String> = hosts
            .into_iter()
            .map(|host| host.to_ascii_lowercase())
            .collect();
        let mut url = validate_url(text, &hosts)?;
        let headers = request_headers(&headers)?;
        let idle_timeout = Duration::from_secs_f64(idle_timeout);
        let deadline = Instant::now() + TOTAL_TIMEOUT;
        for hop in 0..=MAX_REDIRECTS {
            let budget = deadline.saturating_duration_since(Instant::now());
            if budget.is_zero() {
                return Err(DownloadError::Timeout);
            }
            let response = self
                .runtime
                .block_on(async {
                    tokio::time::timeout(
                        idle_timeout.min(budget),
                        self.client
                            .get(url.clone())
                            .headers(headers.clone())
                            .timeout(budget)
                            .send(),
                    )
                    .await
                })
                .map_err(|_| DownloadError::Timeout)?
                .map_err(network_error)?;
            let status = response.status();
            if matches!(status.as_u16(), 301 | 302 | 303 | 307 | 308) {
                if hop == MAX_REDIRECTS {
                    return Err(DownloadError::Policy("Too many download redirects"));
                }
                let location = response
                    .headers()
                    .get(header::LOCATION)
                    .and_then(|h| h.to_str().ok())
                    .ok_or(DownloadError::Policy("Redirect has no valid Location"))?;
                // Validate raw relative Location before URL normalization can hide controls.
                if location
                    .bytes()
                    .any(|c| c <= b' ' || c == b'\\' || c == 127)
                {
                    return Err(DownloadError::Policy("Invalid redirect Location"));
                }
                let next = url
                    .join(location)
                    .map_err(|_| DownloadError::Policy("Invalid redirect Location"))?;
                url = validate_url(next.as_str(), &hosts)?;
                // Drop instead of draining an attacker-controlled redirect body.
                drop(response);
                continue;
            }
            if !status.is_success() {
                return Err(DownloadError::Http(status.as_u16()));
            }
            if response
                .headers()
                .get(header::CONTENT_ENCODING)
                .is_some_and(|v| v.as_bytes() != b"identity")
            {
                return Err(DownloadError::Policy(
                    "Encoded download bodies are not allowed",
                ));
            }
            if response
                .content_length()
                .is_some_and(|n| n > MAX_BODY_BYTES)
            {
                return Err(DownloadError::TooLarge);
            }
            let response_headers = response
                .headers()
                .iter()
                .map(|(name, value)| {
                    (
                        name.as_str().to_owned(),
                        String::from_utf8_lossy(value.as_bytes()).into_owned(),
                    )
                })
                .collect();
            return Ok(DownloadResponse {
                response: Some(response),
                runtime: self.runtime.clone(),
                status: status.as_u16(),
                url: url.to_string(),
                headers: response_headers,
                pending: bytes::Bytes::new(),
                position: 0,
                received: 0,
                idle_timeout,
                deadline,
            });
        }
        Err(DownloadError::Policy("Too many download redirects"))
    }
}

pub struct DownloadResponse {
    response: Option<reqwest::Response>,
    runtime: Arc<Runtime>,
    pub status: u16,
    pub url: String,
    pub headers: Vec<(String, String)>,
    pending: bytes::Bytes,
    position: usize,
    received: u64,
    idle_timeout: Duration,
    deadline: Instant,
}

impl DownloadResponse {
    pub fn close(&mut self) {
        self.response = None;
        self.pending = bytes::Bytes::new();
        self.position = 0;
    }

    /// At most one underlying chunk/read; the Python caller keeps progress/cancellation control.
    pub fn read1(&mut self, limit: usize) -> Result<Vec<u8>, DownloadError> {
        if limit > MAX_READ_BYTES {
            return Err(DownloadError::Policy("Read limit exceeds 1 MiB"));
        }
        if self.response.is_none() {
            return Err(DownloadError::Closed);
        }
        if limit == 0 {
            return Ok(Vec::new());
        }
        let result = self.read_chunk(limit);
        if result.is_err() {
            self.close();
        }
        result
    }

    fn read_chunk(&mut self, limit: usize) -> Result<Vec<u8>, DownloadError> {
        let budget = self.deadline.saturating_duration_since(Instant::now());
        if budget.is_zero() {
            return Err(DownloadError::Timeout);
        }
        while self.position == self.pending.len() {
            let budget = self.deadline.saturating_duration_since(Instant::now());
            if budget.is_zero() {
                return Err(DownloadError::Timeout);
            }
            let response = self.response.as_mut().ok_or(DownloadError::Closed)?;
            let chunk = self
                .runtime
                .block_on(async {
                    tokio::time::timeout(self.idle_timeout.min(budget), response.chunk()).await
                })
                .map_err(|_| DownloadError::Timeout)?
                .map_err(network_error)?;
            let Some(chunk) = chunk else {
                return Ok(Vec::new());
            };
            self.received += chunk.len() as u64;
            if self.received > MAX_BODY_BYTES {
                return Err(DownloadError::TooLarge);
            }
            self.pending = chunk;
            self.position = 0;
        }
        let end = (self.position + limit).min(self.pending.len());
        let result = self.pending[self.position..end].to_vec();
        self.position = end;
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn hosts() -> BTreeSet<String> {
        BTreeSet::from(["example.test".to_owned()])
    }

    #[test]
    fn rejects_untrusted_origins_and_credentials() {
        for text in [
            "http://example.test/a",
            "https://other.test/a",
            "https://example.test:444/a",
            "https://user@example.test/a",
            "https://user:secret@example.test/a",
            "https://example.test/a#f",
            "https://example.test/a#",
            "https://example.test\\@other.test/a",
            "https://example.test/a\nb",
        ] {
            assert!(validate_url(text, &hosts()).is_err(), "{text}");
        }
    }

    #[test]
    fn exact_hosts_and_default_https_port() {
        assert!(validate_url("https://EXAMPLE.test:443/path?signature=opaque", &hosts()).is_ok());
        for text in [
            "https://example.test.evil/a",
            "https://example.test./a",
            "https://sub.example.test/a",
        ] {
            assert!(validate_url(text, &hosts()).is_err());
        }
    }

    #[test]
    fn only_public_download_headers() {
        for name in [
            "Authorization",
            "Cookie",
            "Host",
            "Proxy-Authorization",
            "Accept-Encoding",
        ] {
            assert!(request_headers(&[(name.into(), "secret".into())]).is_err());
        }
        assert!(request_headers(&[("Range".into(), "bytes=1-\r\nCookie: x".into())]).is_err());
        assert!(
            request_headers(&[("Accept".into(), "a".into()), ("accept".into(), "b".into())])
                .is_err()
        );
        let headers = request_headers(&[("Range".into(), "bytes=1-".into())]).unwrap();
        assert_eq!(headers[header::ACCEPT_ENCODING], "identity");
    }

    #[test]
    fn policy_failures_happen_before_network() {
        let client = DownloadClient::new().unwrap();
        for timeout in [0.0, -1.0, f64::NAN, f64::INFINITY, 301.0] {
            assert!(matches!(
                client.open(
                    "https://example.test/a",
                    vec!["example.test".into()],
                    vec![],
                    timeout
                ),
                Err(DownloadError::Policy(_))
            ));
        }
        assert!(matches!(
            client.open(
                "http://example.test/a",
                vec!["example.test".into()],
                vec![],
                1.0
            ),
            Err(DownloadError::Policy(_))
        ));
    }

    fn memory_response(data: &[u8]) -> DownloadResponse {
        let client = DownloadClient::new().unwrap();
        DownloadResponse {
            response: Some(reqwest::Response::from(http::Response::new(data.to_vec()))),
            runtime: client.runtime.clone(),
            status: 200,
            url: "https://example.test/a".into(),
            headers: vec![],
            pending: bytes::Bytes::new(),
            position: 0,
            received: 0,
            idle_timeout: Duration::from_secs(1),
            deadline: Instant::now() + TOTAL_TIMEOUT,
        }
    }

    #[test]
    fn bounded_reads_preserve_pending_bytes_and_eof() {
        let mut response = memory_response(b"abcdef");
        assert_eq!(response.read1(0).unwrap(), b"");
        for expected in [b"ab", b"cd", b"ef"] {
            assert_eq!(response.read1(2).unwrap(), expected);
        }
        assert_eq!(response.read1(2).unwrap(), b"");
        assert_eq!(response.read1(2).unwrap(), b"");
        response.close();
        response.close();
        assert_eq!(response.read1(1), Err(DownloadError::Closed));
    }

    #[test]
    fn invalid_read_size_does_not_consume_response() {
        let mut response = memory_response(b"a");
        assert!(matches!(
            response.read1(MAX_READ_BYTES + 1),
            Err(DownloadError::Policy(_))
        ));
        assert_eq!(response.read1(1).unwrap(), b"a");
    }

    #[test]
    fn timeout_and_byte_limit_close_the_response() {
        let mut expired = memory_response(b"a");
        expired.deadline = Instant::now() - Duration::from_secs(1);
        assert_eq!(expired.read1(1), Err(DownloadError::Timeout));
        assert_eq!(expired.read1(1), Err(DownloadError::Closed));
        let mut large = memory_response(b"a");
        // Artificial counter boundary tests arithmetic, not a gigabyte download.
        large.received = MAX_BODY_BYTES;
        assert_eq!(large.read1(1), Err(DownloadError::TooLarge));
        assert_eq!(large.read1(1), Err(DownloadError::Closed));
    }

    #[test]
    fn range_is_single_bounded_offset_only() {
        for range in [
            "bytes=0-1",
            "bytes=-1",
            "bytes=1-,2-",
            "bytes=+1-",
            "bytes=18446744073709551616-",
        ] {
            assert!(request_headers(&[("Range".into(), range.into())]).is_err());
        }
    }
}

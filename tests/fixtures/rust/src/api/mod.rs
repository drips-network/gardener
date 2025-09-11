// This file (api/mod.rs) declares the 'client' submodule.

pub mod client;

// Re-exporting ApiClient to make it available as crate::api::ApiClient
pub use client::ApiClient;

// Example of an import used within the api module itself
use std::net::IpAddr;

fn get_local_ip() -> Option<IpAddr> {
    // Dummy function
    "127.0.0.1".parse().ok()
}
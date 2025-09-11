// Standard library imports
use std::collections::HashMap;
use std::fmt::Result as FmtResult; // Aliased import
use std::io::{Read, Write}; // Importing multiple items with braces
use std::path::{Path, PathBuf}; // Nested imports
use std::fs; // Another nested import part
use std::env; // Environment variables

// External crate imports
use serde::Deserialize;
use tokio; // Importing the whole crate
use log::info;

// Crate-relative imports
use crate::models::User;
use crate::utils::*; // Glob import
pub use crate::config::Settings; // pub use re-export

// mod declarations
mod utils;
mod config;
mod models;
mod api;
mod services; // For super and self examples

#[tokio::main]
async fn main() {
    println!("Rust fixture main.rs");
    let mut map = HashMap::new();
    map.insert("key", "value");
    info!("Map created: {:?}", map);

    let _user = User { id: 1, name: "TestUser".to_string() };
    let _settings = Settings { port: 8080 };

    // Import inside a function
    use std::time::Instant;
    let start = Instant::now();
    println!("Time: {:?}", start.elapsed());

    // Commented-out import (should be ignored)
    // use legacy_lib;

    services::run_service();
}

// Example of an import within a module
mod internal_module {
    use std::sync::Mutex; // Import specific to this module

    fn internal_function() {
        let _lock = Mutex::new(0);
        println!("Internal function called");
    }
}
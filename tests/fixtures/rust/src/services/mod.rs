// This file (services/mod.rs) declares the 'internal_helper' submodule
// and demonstrates 'super' and 'crate' imports.

pub mod internal_helper;

// Using 'super' is not directly applicable here unless we are in a nested module
// inside services/mod.rs. 'super' would refer to the 'src' directory level (crate root).
// Instead, we use 'crate' to access items from other modules like 'models'.
use crate::models::User; // Accessing User from the models module
use crate::utils::another_util_function; // Accessing a function from utils

// Re-export for easier access from main.rs or other modules
pub use internal_helper::perform_action;

pub fn run_service() {
    println!("Service run started.");
    let user = User { id: 100, name: "ServiceUser".to_string() };
    internal_helper::perform_action(&user);
    another_util_function(); // Calling a utility function
    println!("Service run finished.");
}

// Example of a parent module item that internal_helper might access via `super`
pub struct ServiceData {
    pub id: String,
}

impl ServiceData {
    pub fn new(id: &str) -> Self {
        ServiceData { id: id.to_string() }
    }
}
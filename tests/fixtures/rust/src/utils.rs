// This file is part of the rust-fixture crate.
// It demonstrates various import styles.

// Standard library
use std::collections::HashSet;

// External crate (assuming 'log' is in Cargo.toml)
use log::debug;

// Crate-level (referring to items in main.rs or lib.rs)
// use crate::some_function_in_main_or_lib; // Example

pub fn helper_function() {
    debug!("Helper function called");
    let mut set = HashSet::new();
    set.insert("alpha");
    println!("Set in utils: {:?}", set);
}

pub fn another_util_function() {
    println!("Another utility function");
}

// Example of a submodule within utils.rs
mod math_utils {
    // Import from parent module (utils)
    use super::helper_function;

    pub fn add(a: i32, b: i32) -> i32 {
        helper_function(); // Calling a function from the parent module
        a + b
    }
}

// Re-exporting an item from the submodule
pub use math_utils::add as add_numbers;
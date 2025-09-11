// This file (services/internal_helper.rs) demonstrates 'self' and 'super' imports.

// 'super' refers to the parent module (services/mod.rs in this case)
use super::ServiceData; // Accessing ServiceData from services/mod.rs
use super::User; // Accessing User (re-exported by services/mod.rs from models)

// 'crate' can be used to access any item from the crate root
use crate::config::Settings; // Accessing Settings from config.rs

// 'self' can be used to refer to items within the current module,
// often for disambiguation or in `use` statements for re-exporting.
use self::internal_logic::process;

pub fn perform_action(user: &User) {
    println!("Performing action for user: {:?}", user.name);
    let data = ServiceData::new("internal_data_id");
    println!("Using service data: {}", data.id);
    let _settings = Settings::new(); // Using imported config
    process();
}

mod internal_logic {
    // Import from the current module using 'self' (less common, but possible)
    // use self::another_internal_fn; // If another_internal_fn existed in internal_logic

    // Import from the parent module (internal_helper) using 'super'
    use super::super::User; // This would go two levels up: internal_helper -> services -> User (from models)
                            // More directly: use crate::models::User;

    pub(crate) fn process() { // Made pub(crate) to be callable from perform_action
        println!("Internal logic processing...");
        // another_internal_fn();
    }

    // fn another_internal_fn() {
    //     println!("Another internal function in internal_logic");
    // }
}

// Example of `pub use self::*` if we wanted to re-export everything from internal_logic
// pub use self::internal_logic::*;
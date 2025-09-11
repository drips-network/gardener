// This file (models/user.rs) defines the User struct.

use serde::Deserialize; // External crate import for deriving Deserialize
// use crate::config::Settings; // Example of importing from another module in the crate

#[derive(Deserialize, Debug, Clone)]
pub struct User {
    pub id: u64,
    pub name: String,
    // email: Option<String>, // Example field
}

impl User {
    pub fn new(id: u64, name: String) -> Self {
        User { id, name }
    }
}

// Example of using 'self' to refer to items within the same module (less common for structs)
// mod internal_user_utils {
//     use self::super::User; // 'super' to access User from parent (user.rs)
//
//     fn log_user(user: &User) {
//         println!("User: {:?}", user);
//     }
// }
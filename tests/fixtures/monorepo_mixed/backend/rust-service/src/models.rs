use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct User {
    pub id: i32,
    pub name: String,
    pub email: String,
}

#[derive(Debug, Deserialize)]
pub struct DataRequest {
    pub id: i32,
    pub query: Option<String>,
}
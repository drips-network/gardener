use axum::{http::StatusCode, Json};
use serde_json::{json, Value};

use crate::models::DataRequest;

pub async fn health_check() -> Json<Value> {
    Json(json!({
        "status": "healthy",
        "service": "rust-backend"
    }))
}

pub async fn get_data(Json(payload): Json<DataRequest>) -> Result<Json<Value>, StatusCode> {
    // Validate request
    if payload.id <= 0 {
        return Err(StatusCode::BAD_REQUEST);
    }
    
    Ok(Json(json!({
        "id": payload.id,
        "data": "Response from Rust service"
    })))
}
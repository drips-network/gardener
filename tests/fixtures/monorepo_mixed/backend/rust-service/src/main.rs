use axum::{
    routing::{get, post},
    Router,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::postgres::PgPoolOptions;
use tokio;
use redis;

// Cross-language protobuf support
use prost::Message;
use tonic::{transport::Server, Request, Response, Status};

mod handlers;
mod models;

use crate::handlers::{health_check, get_data};
use crate::models::{User, DataRequest};

#[tokio::main]
async fn main() {
    // Database pool
    let pool = PgPoolOptions::new()
        .max_connections(5)
        .connect("postgres://user:password@localhost/db")
        .await
        .expect("Failed to create pool");

    // Redis client
    let redis_client = redis::Client::open("redis://127.0.0.1/")
        .expect("Failed to connect to Redis");

    // Build our application with routes
    let app = Router::new()
        .route("/health", get(health_check))
        .route("/data", post(get_data));

    // Run it
    axum::Server::bind(&"0.0.0.0:3000".parse().unwrap())
        .serve(app.into_make_service())
        .await
        .unwrap();
}
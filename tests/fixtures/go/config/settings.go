package config

import "os"

// LoadConfig loads configuration settings
func LoadConfig() string {
    return os.Getenv("APP_ENV")
}
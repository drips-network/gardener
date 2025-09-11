// Shared utilities used across different services

export { validateEmail, validatePhone } from './validators';
export { formatDate, formatCurrency } from './formatters';
export { generateId, hashPassword } from './crypto';
export { Logger } from './logger';

// Re-export common constants
export const API_VERSION = 'v1';
export const DEFAULT_TIMEOUT = 5000;
export const MAX_RETRIES = 3;
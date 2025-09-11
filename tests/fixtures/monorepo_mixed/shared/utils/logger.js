const winston = require('winston');
const chalk = require('chalk');

export class Logger {
    constructor(serviceName) {
        this.serviceName = serviceName;
        this.winston = winston.createLogger({
            level: process.env.LOG_LEVEL || 'info',
            format: winston.format.combine(
                winston.format.timestamp(),
                winston.format.json()
            ),
            defaultMeta: { service: serviceName },
            transports: [
                new winston.transports.File({ filename: 'error.log', level: 'error' }),
                new winston.transports.File({ filename: 'combined.log' }),
                new winston.transports.Console({
                    format: winston.format.combine(
                        winston.format.colorize(),
                        winston.format.simple()
                    )
                })
            ]
        });
    }

    info(message, meta = {}) {
        this.winston.info(message, meta);
    }

    error(message, error = null) {
        this.winston.error(message, {
            error: error ? error.stack || error.message : null
        });
    }

    warn(message, meta = {}) {
        this.winston.warn(message, meta);
    }

    debug(message, meta = {}) {
        this.winston.debug(message, meta);
    }
}
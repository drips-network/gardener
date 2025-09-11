// Main fixture file: server.js
// Demonstrates various require and import syntaxes

// CommonJS requires
const fs = require('fs');
const express = require('express');
const _ = require('lodash'); // Aliased require
const { Router } = require('express'); // Destructured require
const logger = require('./utils'); // Relative require (points to utils.js)
const appConfig = require('./config'); // Relative require (points to config/index.js)
const lib = require('./lib'); // Relative require (points to lib/index.js)
const jsonData = require('./data.json'); // Import JSON file
const { v4: uuidv4 } = require('uuid'); // Added to match test expectation

// ES Module imports (static) - Note: This might cause issues if package.json type isn't "module"
// For pure CJS context, these would typically be dynamic imports or not present.
// However, for testing parsing, we include them.
import path from 'path';
import chalk from 'chalk'; // Third-party ES import
import { helper as customHelper } from './helpers.mjs'; // Relative ES import with alias
import * as stringLib from './lib/stringUtils.cjs'; // Importing a CJS file with ES syntax (might need specific Node flags or bundler)

// Commented-out imports/requires
// const unusedDependency = require('nonexistent-package');
// import { nonExistent } from './nonExistentFile.js';

console.log('Server starting...');
console.log('Loaded JSON data:', jsonData.name);
logger.checkFile(__filename); // Using a function from a required module
console.log('App Name from config:', appConfig.appName);
console.log('Sum from lib:', lib.add(5, 3));
console.log('Capitalized by stringLib:', stringLib.capitalize('hello'));

const app = express();
const port = appConfig.port || 3001;

app.get('/', (req, res) => {
    // Import/require inside a function
    const moment = require('moment'); // CommonJS require inside function
    res.send(`Hello from JS Fixtures! Time: ${moment().format()}`);
});

class ApiClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
        // ES import (dynamic) inside a class method or constructor
        // This is a more common way to use ESM in CJS or for conditional loading
        import('./api/client.mjs').then(apiModule => { // Corrected path from ../api to ./api
            this.client = new apiModule.default(this.baseUrl); // Assuming client.mjs has a default export
            console.log(chalk.green('API Client dynamically loaded.'));
        }).catch(err => {
            console.error(chalk.red('Failed to load API client:'), err);
        });
    }

    // Require inside a class method
    getConfig() {
        const localSettings = require('./config/settings');
        return localSettings.logLevel;
    }
}

const apiClientInstance = new ApiClient('http://localhost:8080');
console.log('API Client Log Level:', apiClientInstance.getConfig());

// Dynamic import at top level
import('./dynamicModule.js').then(dynamic => { // Focus on the import string
    console.log(chalk.blue('Dynamically loaded module message:'), dynamic.someFunction());
}).catch(err => {
    console.error(chalk.red('Error loading dynamic module:'), err);
});

// Require with trailing comment
const trailingCommentMod = require('./utils'); // Get utils again for demo

app.listen(port, () => {
    console.log(`JS Fixture server listening on port ${port}`);
    console.log(`Path resolved by ES import: ${path.basename(__filename)}`);
    console.log(chalk.yellow('Server is ready!'));
    console.log(`Helper timestamp: ${customHelper.getCurrentTimestamp()}`);
});

// To test index.js resolution from a different relative path
const deepLib = require('./lib');
console.log('Deep lib subtract:', deepLib.subtract(10, 4));
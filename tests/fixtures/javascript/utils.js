// Utility functions using various import styles

// CommonJS requires (existing)
const fs = require('fs');
const _ = require('lodash'); // Aliased require
const { Router } = require('express'); // Destructured require
const internalConfig = require('../config'); // Relative require to an index.js
const stringUtils = require('./lib/stringUtils.cjs');
const dataUtils = require('./data.json');

// ES Module imports (added based on original test expectations)
import { specificFunction, anotherFunction as aliasedFunction } from './helpers.mjs';
import * as constants from './constants.mjs';

// Function using existing requires
function checkFile(filePath) {
    console.log('Checking file:', filePath, 'using config', internalConfig.appName);
    return fs.existsSync(filePath);
}

// Function using new ES imports
function processData(data) {
    specificFunction(data);
    aliasedFunction();
    return constants.DEFAULT_VALUE;
}

// Dynamic import (added based on original test expectations)
async function loadDynamic() {
    const dynamic = await import('./dynamicModule.js');
    return dynamic.someFunction();
}

// Commented-out require (should be ignored)
// const unused = require('unused-module');

module.exports = {
    checkFile,
    isString: _.isString,
    Router,
    processData,
    loadDynamic
};
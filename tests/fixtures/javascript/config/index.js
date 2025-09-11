// Barrel file for config
// This file being named index.js allows `require('../config')` to resolve to this.

require('dotenv').config(); // Intended external import
const settings = require('./settings.js'); // Existing local import

module.exports = {
    port: process.env.PORT || 3000,
    appName: 'JS Fixture App',
    settings
};
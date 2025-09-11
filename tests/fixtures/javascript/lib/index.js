// Barrel file for lib
// This allows `require('./lib')` to resolve to this.

const math = require('./math');
const stringUtils = require('./stringUtils.cjs'); // Explicit .cjs extension

module.exports = {
    ...math,
    ...stringUtils
};
// Simple math library module

function add(a, b) {
    return a + b;
}

function subtract(a, b) {
    // Example of a require inside a function
    const _ = require('lodash');
    if (!_.isNumber(a) || !_.isNumber(b)) {
        throw new Error('Inputs must be numbers');
    }
    return a - b;
}

module.exports = {
    add,
    subtract
};
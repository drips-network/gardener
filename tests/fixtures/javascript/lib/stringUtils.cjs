// Simple string utility functions (CommonJS module)

function capitalize(str) {
    if (typeof str !== 'string' || str.length === 0) {
        return '';
    }
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function reverseString(str) {
    // Another require inside a function
    const { isString } = require('lodash');
    if (!isString(str)) {
        return '';
    }
    return str.split('').reverse().join('');
}

// Commented out require
// const crypto = require('crypto');

module.exports = {
    capitalize,
    reverseString
};
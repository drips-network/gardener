const validator = require('validator');

export function validateEmail(email) {
    return validator.isEmail(email);
}

export function validatePhone(phone) {
    return validator.isMobilePhone(phone, 'any');
}

export function validatePassword(password) {
    return password.length >= 8 && 
           /[A-Z]/.test(password) && 
           /[a-z]/.test(password) && 
           /[0-9]/.test(password);
}

export function validateUsername(username) {
    return /^[a-zA-Z0-9_]{3,20}$/.test(username);
}
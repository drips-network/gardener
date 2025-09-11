const crypto = require('crypto');
const bcrypt = require('bcryptjs');
const { v4: uuidv4 } = require('uuid');

export function generateId() {
    return uuidv4();
}

export async function hashPassword(password) {
    const salt = await bcrypt.genSalt(10);
    return bcrypt.hash(password, salt);
}

export async function comparePassword(password, hash) {
    return bcrypt.compare(password, hash);
}

export function generateToken(length = 32) {
    return crypto.randomBytes(length).toString('hex');
}

export function hashData(data) {
    return crypto.createHash('sha256').update(data).digest('hex');
}
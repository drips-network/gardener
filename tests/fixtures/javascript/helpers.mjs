// Helper using ES import
import path from 'path';
import moment from 'moment'; // Aliased ES import (though not explicitly aliased here, moment is the default export)
import { readFile } from 'fs/promises';
import { v4 as uuidv4 } from 'uuid'; // Aliased named ES import
import * as constants from './constants.mjs'; // Namespace ES import (assuming constants.mjs exists or will be created)

export function getCurrentTimestamp() {
    return moment().toISOString();
}

export async function readFileContent(filePath) {
    const fullPath = path.resolve(filePath);
    return await readFile(fullPath, 'utf-8');
}

export function generateId() {
    return uuidv4();
}

export function getConstant(key) {
    return constants[key];
}

// Example of an import inside a function (though less common for static analysis, good to have)
export async function loadDynamic() {
    const dynamicModule = await import('./dynamicModule.js'); // Dynamic import
    return dynamicModule.someFunction();
}
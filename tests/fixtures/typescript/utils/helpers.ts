// Helper functions

import path from 'path'; // Standard ES Module import
import _ from 'lodash'; // Aliased import

export function joinPath(...segments: string[]): string {
    return path.join(...segments);
}

export function isEmpty(value: any): boolean {
    // Import inside a function
    const lodashIsEmpty = _.isEmpty;
    return lodashIsEmpty(value);
}

export const PI = 3.14159;

// Commented-out import - should be ignored
// import { deprecatedFunction } from './legacy';

/**
 * Adds two numbers
 * @param a The first number
 * @param b The second number
 * @returns The sum of a and b
 */
export function add(a: number, b: number): number {
    return a + b;
}
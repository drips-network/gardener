// Defines interfaces and types

export interface User {
    id: number;
    name: string;
    email?: string;
}

export type AdminUser = User & {
    isAdmin: true;
};

export enum UserRole {
    ADMIN = 'ADMIN',
    USER = 'USER',
    GUEST = 'GUEST',
}

// Type-only export example
export type { Express } from 'express';
// Main file importing various modules and types

// Standard ES Module imports
import path from 'path';
import axios from 'axios';

// Aliased imports
import _ from 'lodash';

// Named imports
import { Component } from 'react';

// Aliased named imports
import { AxiosRequestConfig as RequestConfig } from 'axios';

// Namespace imports
import * as fs from 'fs';

// Relative imports
import { User, AdminUser, UserRole } from './types'; // Importing multiple from ./types
import { loadConfig, AppConfig } from './config'; // Importing from ./config
import { isEmpty, add, MathPI } from './utils'; // Importing from ./utils (index.ts)
import ButtonComponent from './components/Button'; // Importing default from .tsx

// Type-only imports
import type { Request, Response } from 'express';
import type { Express as ExpressAppType } from './types'; // Type import from local file

// Imports involving path aliases (from tsconfig.json)
import { joinPath } from '@utils/helpers'; // Path alias for utils/helpers
import ButtonAliased from '@components/Button'; // Path alias for components/Button

// Commented-out imports - should be ignored
// import { deprecated } from './legacy';
// import * as oldStuff from './old/stuff';

// Imports with trailing comments
import { currentRole } from './config'; // Current application role

function main() {
    console.log('Starting TypeScript fixture main script');

    const user: User = { id: 1, name: 'Test User' };
    const admin: AdminUser = { id: 2, name: 'Admin', isAdmin: true };

    console.log('User:', user, 'Admin:', admin);
    console.log('Current Role:', currentRole);
    console.log('Is lodash empty check working for {}?', _.isEmpty({}));

    // Import inside a function
    async function dynamicLoad() {
        const { v4: uuidv4 } = await import('uuid'); // Dynamic import of a third-party lib
        console.log('Generated UUID:', uuidv4());
    }
    dynamicLoad();

    const appConfig: AppConfig = loadConfig('./sample-config.json'); // Fictional config
    console.log('Loaded app config port:', appConfig.port);
    console.log('PI from utils:', MathPI);
    console.log('Adding 2+3 using util:', add(2, 3));
    console.log('Path join example:', joinPath('some', 'path', 'segments'));

    // Using a React component (conceptually, not rendering)
    console.log('ButtonComponent type:', typeof ButtonComponent);
    console.log('ButtonAliased type:', typeof ButtonAliased);

    // Example of using fs (conceptually)
    if (fs.existsSync('.')) {
        console.log('Current directory exists');
    }
}

class App {
    private serverInstance: ExpressAppType | null = null;

    constructor(private config: AppConfig) {}

    // Import type used in a class method parameter
    startServer(reqHandler?: (req: Request, res: Response) => void) {
        // Import inside a class method
        import('express').then((express) => {
            const app = express.default();
            this.serverInstance = app;
            if (reqHandler) {
                app.get('/', reqHandler);
            }
            app.listen(this.config.port, () => {
                console.log(`Server running on http://localhost:${this.config.port}`);
            });
        }).catch(err => console.error('Failed to load express:', err));
    }
}

main();

const appInstance = new App(loadConfig(''));
appInstance.startServer((req, res) => {
    res.send('Hello from fixture server!');
});

// Another type-only import
import type { LoDashStatic } from 'lodash';
const lodashInstance: LoDashStatic = _;
console.log('Lodash version via type:', lodashInstance.VERSION);
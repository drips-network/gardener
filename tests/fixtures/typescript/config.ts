// Configuration loading

import * as fs from 'fs'; // Namespace import
import { AxiosRequestConfig as RequestConfig } from 'axios'; // Aliased named import

export interface AppConfig {
    port: number;
    hostname: string;
    features: {
        logging: boolean;
        caching: boolean;
    };
    axiosSettings?: RequestConfig;
}

const DEFAULT_PORT = 3000;

export function loadConfig(filePath: string): AppConfig {
    let configData: Partial<AppConfig> = {};
    if (fs.existsSync(filePath)) {
        const fileContent = fs.readFileSync(filePath, 'utf-8');
        configData = JSON.parse(fileContent);
    }

    return {
        port: configData.port || DEFAULT_PORT,
        hostname: configData.hostname || 'localhost',
        features: {
            logging: configData.features?.logging ?? true,
            caching: configData.features?.caching ?? false,
        },
        axiosSettings: configData.axiosSettings,
    };
}

// Example of an import with a trailing comment
import { UserRole } from './types'; // User roles for the application

export const currentRole = UserRole.ADMIN;
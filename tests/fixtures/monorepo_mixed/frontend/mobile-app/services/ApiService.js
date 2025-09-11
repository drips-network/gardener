import axios from 'axios';
import { StorageService } from './StorageService';

const API_BASE_URL = 'http://localhost:3000';

class ApiServiceClass {
    constructor() {
        this.client = null;
    }

    initialize() {
        this.client = axios.create({
            baseURL: API_BASE_URL,
            timeout: 10000,
            headers: {
                'Content-Type': 'application/json',
            },
        });

        // Add request interceptor for auth
        this.client.interceptors.request.use(
            async (config) => {
                const token = await StorageService.getToken();
                if (token) {
                    config.headers.Authorization = `Bearer ${token}`;
                }
                return config;
            },
            (error) => Promise.reject(error)
        );
    }

    async getUsers() {
        try {
            const response = await this.client.get('/users');
            return response.data.data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    async getUserById(id) {
        try {
            const response = await this.client.get(`/users/${id}`);
            return response.data.data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    async getData(id) {
        try {
            const response = await this.client.post('/data', { id });
            return response.data.data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }
}

export const ApiService = new ApiServiceClass();
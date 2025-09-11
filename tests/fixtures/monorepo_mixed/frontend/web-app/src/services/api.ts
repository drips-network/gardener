import axios, { AxiosInstance } from 'axios';
import { User, ApiResponse } from '../types';

export class ApiClient {
    private client: AxiosInstance;

    constructor() {
        this.client = axios.create({
            baseURL: process.env.REACT_APP_API_URL || 'http://localhost:3000',
            timeout: 5000,
            headers: {
                'Content-Type': 'application/json',
            },
        });
    }

    async getUsers(): Promise<ApiResponse<User[]>> {
        const response = await this.client.get<ApiResponse<User[]>>('/users');
        return response.data;
    }

    async createUser(user: Omit<User, 'id'>): Promise<ApiResponse<User>> {
        const response = await this.client.post<ApiResponse<User>>('/users', user);
        return response.data;
    }

    async getData(id: number): Promise<ApiResponse<any>> {
        const response = await this.client.post<ApiResponse<any>>('/data', { id });
        return response.data;
    }
}
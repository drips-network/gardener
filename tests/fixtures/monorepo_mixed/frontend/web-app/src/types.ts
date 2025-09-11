export interface User {
    id: number;
    name: string;
    email: string;
}

export interface ApiResponse<T> {
    success: boolean;
    data: T;
    timestamp?: string;
}
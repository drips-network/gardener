import AsyncStorage from '@react-native-async-storage/async-storage';

class StorageServiceClass {
    constructor() {
        this.KEYS = {
            TOKEN: '@app:token',
            USER: '@app:user',
            SETTINGS: '@app:settings',
        };
    }

    initialize() {
        // Any initialization logic
    }

    async getToken() {
        try {
            return await AsyncStorage.getItem(this.KEYS.TOKEN);
        } catch (error) {
            console.error('Failed to get token:', error);
            return null;
        }
    }

    async setToken(token) {
        try {
            await AsyncStorage.setItem(this.KEYS.TOKEN, token);
        } catch (error) {
            console.error('Failed to save token:', error);
        }
    }

    async getUser() {
        try {
            const userJson = await AsyncStorage.getItem(this.KEYS.USER);
            return userJson ? JSON.parse(userJson) : null;
        } catch (error) {
            console.error('Failed to get user:', error);
            return null;
        }
    }

    async setUser(user) {
        try {
            await AsyncStorage.setItem(this.KEYS.USER, JSON.stringify(user));
        } catch (error) {
            console.error('Failed to save user:', error);
        }
    }

    async clearAll() {
        try {
            await AsyncStorage.multiRemove(Object.values(this.KEYS));
        } catch (error) {
            console.error('Failed to clear storage:', error);
        }
    }
}

export const StorageService = new StorageServiceClass();
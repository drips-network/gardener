// ES Module: api/client.mjs
import axios from 'axios'; // Intended external import
import { helperFunction } from '../helpers.mjs'; // Corrected: Intended local import (relative up)
import { getConfig } from '../config'; // Intended local import (relative up)

class ApiClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
        console.log(`API Client initialized for ${this.baseUrl}`); // Removed chalk
    }

    async fetchData(endpoint) {
        // Use the imported axios
        console.log(`Fetching data from: ${this.baseUrl}/${endpoint} using ${getConfig().appName}`);
        try {
            const response = await axios.get(`${this.baseUrl}/${endpoint}`);
            // Example of a dynamic import within an async method
            const { TIMEOUT_MS } = await import('../constants.mjs'); // Intended dynamic local import
            helperFunction(); // Use imported helper
            return { success: true, data: response.data, timeout: TIMEOUT_MS };
        } catch (error) {
            console.error('API fetch error:', error);
            return { success: false, error: error.message };
        }
    }
}

export default ApiClient;
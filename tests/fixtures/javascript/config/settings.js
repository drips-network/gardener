// Example settings file

const path = require('path');

module.exports = {
    logLevel: 'info',
    featureFlags: {
        newDashboard: true,
        apiCaching: false
    },
    tempDir: path.join(__dirname, '..', 'temp') // Relative require for path module
};
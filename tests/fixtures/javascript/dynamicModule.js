// Module for dynamic import testing

function someFunction() {
    return 'Data from dynamically imported module';
}

// Another require to test requires inside dynamically imported CJS modules
const path = require('path');

console.log('Dynamic module loaded using path:', path.basename(__filename));

module.exports = {
    someFunction
};
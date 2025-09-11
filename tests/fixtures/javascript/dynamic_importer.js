// Fixture for testing dynamic imports

async function loadModules() {
    console.log('Loading modules dynamically...');

    // Dynamic import of an external package
    const anotherPackage = await import('another-package');
    console.log('Loaded external package version:', anotherPackage.version); // Example usage

    // Dynamic import of a local module
    const utils = await import('./utils');
    // Assuming utils.js exports something callable for example usage
    if (utils.checkFile) {
        console.log('Loaded local utils, checking file:', utils.checkFile('somefile.txt'));
    } else {
         console.log('Loaded local utils:', utils);
    }


    return { anotherPackage, utils };
}

loadModules();
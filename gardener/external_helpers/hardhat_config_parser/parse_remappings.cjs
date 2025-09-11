const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');

function staticParseTsConfig(tsPath) {
    try {
        const text = fs.readFileSync(tsPath, 'utf8');
        const remapMatch = text.match(/remappings\s*:\s*\[(.*?)\]/s);
        if (!remapMatch) return {};
        const inner = remapMatch[1];
        const out = {};
        const strRe = /['\"]([^'\"]+)['\"]/g;
        let m;
        while ((m = strRe.exec(inner)) !== null) {
            const entry = m[1];
            const parts = entry.split('=');
            if (parts.length === 2) {
                out[parts[0]] = parts[1];
            }
        }
        return out;
    } catch (_) {
        return {};
    }
}

function getRemappings() {
    const projectRoot = process.argv[2];
    if (!projectRoot) {
        return {};
    }

    const configJsPath = path.resolve(projectRoot, 'hardhat.config.js');
    const configTsPath = path.resolve(projectRoot, 'hardhat.config.ts');

    let configPath;
    let isTypeScript = false;

    if (fs.existsSync(configJsPath)) {
        configPath = configJsPath;
    } else if (fs.existsSync(configTsPath)) {
        configPath = configTsPath;
        isTypeScript = true;
    } else {
        return {};
    }

    try {
        if (isTypeScript) {
            // Try to load ts-node relative to the target project first, then fall back to helper-local/global
            const projectRequire = createRequire(path.join(projectRoot, 'package.json'));
            let loaded = false;
            const candidates = [
                'ts-node/register/transpile-only',
                'ts-node/register',
            ];
            for (const mod of candidates) {
                try {
                    try {
                        projectRequire(mod);
                        loaded = true;
                        break;
                    } catch (e) {
                        require(mod);
                        loaded = true;
                        break;
                    }
                } catch (_) { /* continue trying */ }
            }
            if (!loaded) {
                // Fallback: static parse of remappings from TS without executing the file
                const fallback = staticParseTsConfig(configPath);
                return fallback;
            }
        }
        let hardhatConfig;
        try {
            hardhatConfig = require(configPath);
        } catch (e) {
            // Even if ts-node is loaded, requiring may fail (ESM/CJS mismatch). Fallback to static parse.
            const fallback = isTypeScript ? staticParseTsConfig(configPath) : {};
            return fallback;
        }
        // Support TS configs that use `export default`
        if (hardhatConfig && typeof hardhatConfig === 'object' && 'default' in hardhatConfig) {
            hardhatConfig = hardhatConfig.default;
        }

        // Common locations for remappings
        // 1. Directly in solidity settings (e.g., hardhat-deploy)
        // 2. Under a specific remappings key (less common but possible)
        // 3. Foundry remappings format (if used via hardhat-foundry)

        let remappings = {};

        if (hardhatConfig && hardhatConfig.solidity) {
            if (typeof hardhatConfig.solidity === 'object' && hardhatConfig.solidity.remappings) {
                // Case: { solidity: { remappings: { ... } } }
                remappings = hardhatConfig.solidity.remappings;
            } else if (Array.isArray(hardhatConfig.solidity.compilers)) {
                // Case: { solidity: { compilers: [{ version: "...", settings: { remappings: [] } }] } }
                // Or { solidity: { compilers: [{ version: "...", settings: { optimizer: { ... }, remappings: [] } }] } }
                // This structure is more for compiler settings, remappings are usually higher up.
                // Let's check if any compiler has remappings defined in its settings.
                for (const compiler of hardhatConfig.solidity.compilers) {
                    if (compiler.settings && compiler.settings.remappings) {
                        // Assuming remappings here would be an array of strings like ["@oz=node_modules/...", "forge-std/=lib/..."]
                        // Convert to object format
                        const arrayRemappings = compiler.settings.remappings;
                        if (Array.isArray(arrayRemappings)) {
                            arrayRemappings.forEach(remap => {
                                const parts = remap.split('=');
                                if (parts.length === 2) {
                                    remappings[parts[0]] = parts[1];
                                }
                            });
                        }
                        // If multiple compilers define remappings, this might overwrite.
                        // For simplicity, we take the first one found or merge.
                        // Let's assume for now they won't conflict or take the last one.
                    }
                }
            }
        }

        // Check for `paths.remappings` (used by hardhat-preprocessor or similar tools)
        if (hardhatConfig && hardhatConfig.paths && Array.isArray(hardhatConfig.paths.remappings)) {
            hardhatConfig.paths.remappings.forEach(remap => {
                if (typeof remap === 'string') {
                    const parts = remap.split('=');
                    if (parts.length === 2) {
                        remappings[parts[0]] = parts[1];
                    }
                }
            });
        }

        // Check for Foundry-style remappings if `hardhat-foundry` is used
        // This often involves reading a `remappings.txt` file or having them in `foundry.toml`
        // For simplicity, this script won't parse `foundry.toml` or `remappings.txt` directly
        // but will look for a pre-processed version if available in hardhatConfig.
        if (hardhatConfig && hardhatConfig.foundry && hardhatConfig.foundry.remappings) {
            if (Array.isArray(hardhatConfig.foundry.remappings)) {
                 hardhatConfig.foundry.remappings.forEach(remap => {
                    const parts = remap.split('=');
                    if (parts.length === 2) {
                        remappings[parts[0]] = parts[1];
                    }
                });
            } else if (typeof hardhatConfig.foundry.remappings === 'object') {
                Object.assign(remappings, hardhatConfig.foundry.remappings);
            }
        }


        // Ensure all remapping paths are resolved relative to the project root
        // and end with a slash if they are directory mappings.
        const resolvedRemappings = {};
        for (const key in remappings) {
            if (Object.prototype.hasOwnProperty.call(remappings, key)) {
                let value = remappings[key];
                // Remapping values should be paths. We don't resolve them here,
                // as the consumer (Python script) will handle path resolution
                // based on the project root. The key itself often ends with a slash.
                resolvedRemappings[key] = value;
            }
        }

        return resolvedRemappings;

    } catch (error) {
        // Swallow errors and produce an empty mapping to keep the caller robust
        return {};
    }
}

try {
    const remappings = getRemappings();
    process.stdout.write(JSON.stringify(remappings, null, 0)); // No pretty print for compactness
} catch (e) {
    // Catch any unexpected error during getRemappings or stringify
    process.stdout.write(JSON.stringify({}, null, 0));
}

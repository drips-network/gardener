// Minimal TS Hardhat config used only to supply remappings for tests
// Intentionally avoids importing hardhat or plugins

export default {
  solidity: {
    version: '0.8.20',
  },
  paths: {
    remappings: [
      '@openzeppelin/=node_modules/@openzeppelin/contracts/'
    ]
  }
};


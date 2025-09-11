// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title Constants
 * @dev Defines global constants for the project.
 * This file is intended to be imported using a whole-file alias (e.g., `import "./Constants.sol" as Consts;`).
 */
library Constants {
    uint256 public constant CONTRACT_VERSION = 1;
    uint256 public constant DEFAULT_TIMEOUT = 3600; // 1 hour
    address public constant ZERO_ADDRESS = address(0);
}
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// Direct external import from OpenZeppelin
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
// Specific symbol import from OpenZeppelin
import { Ownable } from "@openzeppelin/contracts/access/Ownable.sol";
// Relative path import for an interface
import "../interfaces/IMyToken.sol";
// Commented out import - should be ignored by the parser
// import "./DeprecatedFeature.sol";
import "./Config.sol"; // Project config - import with trailing comment

/**
 * @title BaseToken
 * @dev A base ERC20 token contract that includes ownership.
 * Demonstrates direct external imports, specific symbol imports,
 * relative path imports, commented-out imports, and imports with trailing comments.
 */
contract BaseToken is ERC20, Ownable, IMyToken {
    constructor(string memory name, string memory symbol, address initialOwner)
        ERC20(name, symbol)
        Ownable(initialOwner) // Pass initialOwner to Ownable constructor
    {
        // Additional setup if needed
    }

    // IMyToken functions are implicitly implemented by ERC20,
    // but the interface is included to test multiple inheritance scenarios.

    // Example of using a variable from Config.sol (if it were defined)
    // uint256 public constant SOME_CONFIG_VALUE = Config.SOME_VALUE;
}
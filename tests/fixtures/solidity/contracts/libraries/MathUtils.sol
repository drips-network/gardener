// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// Aliased import from OpenZeppelin
import { SafeMath as SafeLib } from "@openzeppelin/contracts/utils/math/SafeMath.sol";
// Import for a remapped library (e.g., from forge-std or solmate)
import "forge-std/Test.sol"; // Example of remapped import

/**
 * @title MathUtils Library
 * @dev Provides safe mathematical operations.
 * This library demonstrates aliased imports and remapped path imports.
 */
library MathUtils {
    using SafeLib for uint256;

    function add(uint256 a, uint256 b) internal pure returns (uint256) {
        return a.add(b);
    }

    function subtract(uint256 a, uint256 b) internal pure returns (uint256) {
        return a.sub(b);
    }

    // Example function that might use something from Test.sol if it were a contract
    // For a library, direct use is less common but import syntax is the focus
    function getChainIdForTest() internal view returns (uint256) {
        // return Test.vm.chainId(); // This would be valid if Test was usable like this
        return 1; // Placeholder
    }
}
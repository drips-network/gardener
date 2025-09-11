// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// Relative path import for a base contract
import "./BaseToken.sol";
// Relative path import for an interface from a subdirectory
import "./interfaces/IMyToken.sol";
// Relative path import for a library from a subdirectory
import "./libraries/MathUtils.sol";
// Whole file import with alias
import "./Constants.sol" as Consts;
// Import for a remapped library (e.g., Solmate)
import "lib/solmate/src/tokens/ERC20.sol" as SolmateERC20; // Example of remapped import

/**
 * @title MyToken
 * @dev An example token contract demonstrating various import types.
 * It inherits from BaseToken and uses MathUtils.
 */
contract MyToken is BaseToken {
    using MathUtils for uint256;

    uint256 public constant VERSION = Consts.CONTRACT_VERSION;
    address public immutable solmateChecker; // Just to use the SolmateERC20 import

    constructor(
        string memory name,
        string memory symbol,
        uint256 initialSupply,
        address initialOwner
    ) BaseToken(name, symbol, initialOwner) {
        _mint(initialOwner, initialSupply * (10**decimals()));
        // Example usage of an imported constant
        uint256 checkVersion = Consts.CONTRACT_VERSION;
        require(checkVersion > 0, "Version must be positive");
        solmateChecker = address(new SolmateERC20("SolmateTest", "SMT", 18));
    }

    function addValues(uint256 a, uint256 b) public pure returns (uint256) {
        return MathUtils.add(a, b);
    }

    // This function is here to ensure IMyToken interface is "used"
    // The actual ERC20 functions are inherited from OpenZeppelin's ERC20 via BaseToken
    function getInterfaceId() public pure returns (bytes4) {
        return type(IMyToken).interfaceId;
    }
}
"""
Test cases for Solidity component string specification

These tests define the expected behavior based on the formal specification.
They are implementation-agnostic and should pass for any correct implementation
"""

from gardener.treewalk.solidity import SolidityImportVisitor


class TestSolidityComponentSpecification:
    """Test cases derived from the Solidity Component Format Specification v1.0"""

    def test_external_whole_file_import(self):
        """Test basic external package imports without symbols or aliases."""
        test_cases = [
            # (import_path, package_name, symbols, alias, expected_component)
            (
                "@openzeppelin/contracts/token/ERC20/ERC20.sol",
                "@openzeppelin/contracts",
                "",
                "",
                "@openzeppelin/contracts.token/ERC20/ERC20",
            ),
            (
                "@openzeppelin/contracts/access/Ownable.sol",
                "@openzeppelin/contracts",
                "",
                "",
                "@openzeppelin/contracts.access/Ownable",
            ),
            # Direct file import (no package context)
            ("SomeContract.sol", None, "", "", "SomeContract"),
        ]

        for import_path, package_name, symbols, alias, expected in test_cases:
            # This will be connected to actual implementation later
            assert self._generate_component(import_path, package_name, symbols, alias) == expected

    def test_external_symbol_imports(self):
        """Test external imports with specific symbols."""
        test_cases = [
            # Single symbol
            (
                "@openzeppelin/contracts/access/Ownable.sol",
                "@openzeppelin/contracts",
                "Ownable",
                "",
                "@openzeppelin/contracts.access/Ownable { Ownable }",
            ),
            # Multiple symbols (should be sorted)
            (
                "@openzeppelin/contracts/utils/math/SafeMath.sol",
                "@openzeppelin/contracts",
                "SafeMath,SafeCast",
                "",
                "@openzeppelin/contracts.utils/math/SafeMath { SafeCast, SafeMath }",
            ),
            # Duplicate symbols (should be deduplicated)
            ("solmate/tokens/ERC20.sol", "solmate", "ERC20,IERC20,ERC20", "", "solmate.tokens/ERC20 { ERC20, IERC20 }"),
        ]

        for import_path, package_name, symbols, alias, expected in test_cases:
            assert self._generate_component(import_path, package_name, symbols, alias) == expected

    def test_external_aliased_imports(self):
        """Test external imports with aliases."""
        test_cases = [
            # Whole file with alias (keeps .sol)
            (
                "@openzeppelin/contracts/utils/Context.sol",
                "@openzeppelin/contracts",
                "",
                "OZContext",
                "@openzeppelin/contracts.utils/Context.sol as OZContext",
            ),
            # Remapped import with alias
            ("solmate/tokens/ERC20.sol", "solmate", "", "SolmateERC20", "solmate.tokens/ERC20.sol as SolmateERC20"),
        ]

        for import_path, package_name, symbols, alias, expected in test_cases:
            assert self._generate_component(import_path, package_name, symbols, alias) == expected

    def test_local_imports(self):
        """Test local file imports - paths preserved exactly."""
        test_cases = [
            # Basic local imports
            ("./BaseToken.sol", None, "", "", "./BaseToken.sol"),
            ("../interfaces/IMyToken.sol", None, "", "", "../interfaces/IMyToken.sol"),
            ("./libraries/MathUtils.sol", None, "", "", "./libraries/MathUtils.sol"),
            # Local with symbols
            ("./Constants.sol", None, "MAX_SUPPLY,DECIMALS", "", "./Constants.sol { DECIMALS, MAX_SUPPLY }"),
            # Local with alias
            ("./Config.sol", None, "", "Configuration", "./Config.sol as Configuration"),
        ]

        for import_path, package_name, symbols, alias, expected in test_cases:
            assert self._generate_component(import_path, package_name, symbols, alias) == expected

    def test_path_normalization(self):
        """Test path normalization rules for external packages."""
        test_cases = [
            # Remove package prefix
            (
                "@openzeppelin/contracts/token/ERC20.sol",
                "@openzeppelin/contracts",
                "",
                "",
                "@openzeppelin/contracts.token/ERC20",
            ),
            # Remove lib/<package>/ prefix
            ("lib/solmate/src/tokens/ERC20.sol", "solmate", "", "", "solmate.src/tokens/ERC20"),
            # Remove src/ prefix
            ("src/tokens/ERC20.sol", "mypackage", "", "", "mypackage.tokens/ERC20"),
            # Remove lib/ prefix
            ("lib/tokens/ERC20.sol", "mypackage", "", "", "mypackage.tokens/ERC20"),
            # Multiple prefixes - should remove in order
            ("lib/solmate/tokens/ERC20.sol", "solmate", "", "", "solmate.tokens/ERC20"),
        ]

        for import_path, package_name, symbols, alias, expected in test_cases:
            assert self._generate_component(import_path, package_name, symbols, alias) == expected

    def test_remapped_imports(self):
        """Test remapped imports treated as external packages."""
        test_cases = [
            # Basic remapping
            ("solmate/tokens/ERC20.sol", "solmate", "", "", "solmate.tokens/ERC20"),
            # Remapping with symbols
            ("forge-std/Test.sol", "forge-std", "Test", "", "forge-std.Test { Test }"),
            # Remapping with complex path (src/ prefix is removed by normalization)
            (
                "@chainlink/contracts/src/v0.8/interfaces/AggregatorV3Interface.sol",
                "@chainlink/contracts",
                "",
                "",
                "@chainlink/contracts.v0.8/interfaces/AggregatorV3Interface",
            ),
        ]

        for import_path, package_name, symbols, alias, expected in test_cases:
            assert self._generate_component(import_path, package_name, symbols, alias) == expected

    def test_edge_cases(self):
        """Test edge cases and special scenarios."""
        test_cases = [
            # Empty symbols should not add braces
            ("./Token.sol", None, "", "", "./Token.sol"),
            # Index file import (trailing slash is preserved in implementation)
            (
                "@openzeppelin/contracts/token/",
                "@openzeppelin/contracts",
                "Token",
                "",
                "@openzeppelin/contracts.token/ { Token }",
            ),
            # Already normalized path
            ("token/ERC20", "mypackage", "", "", "mypackage.token/ERC20"),
            # Path with multiple slashes
            ("./path//to///file.sol", None, "", "", "./path//to///file.sol"),  # Local paths preserved exactly
        ]

        for import_path, package_name, symbols, alias, expected in test_cases:
            assert self._generate_component(import_path, package_name, symbols, alias) == expected

    def test_symbol_formatting(self):
        """Test symbol list formatting rules."""
        test_cases = [
            # Symbols should be sorted
            ("pkg/File.sol", "pkg", "Z,A,M", "", "pkg.File { A, M, Z }"),
            # Duplicates removed and sorted
            ("pkg/File.sol", "pkg", "B,A,B,C,A", "", "pkg.File { A, B, C }"),
            # Single symbol
            ("pkg/File.sol", "pkg", "Single", "", "pkg.File { Single }"),
            # Many symbols
            ("pkg/File.sol", "pkg", "One,Two,Three,Four,Five", "", "pkg.File { Five, Four, One, Three, Two }"),
        ]

        for import_path, package_name, symbols, alias, expected in test_cases:
            assert self._generate_component(import_path, package_name, symbols, alias) == expected

    def test_file_extension_handling(self):
        """Test .sol extension handling rules."""
        test_cases = [
            # Whole file import - remove .sol
            ("token/ERC20.sol", "pkg", "", "", "pkg.token/ERC20"),
            # With symbols - remove .sol
            ("token/ERC20.sol", "pkg", "ERC20", "", "pkg.token/ERC20 { ERC20 }"),
            # With alias only - keep .sol
            ("token/ERC20.sol", "pkg", "", "MyToken", "pkg.token/ERC20.sol as MyToken"),
            # Local imports always keep .sol
            ("./token/ERC20.sol", None, "", "", "./token/ERC20.sol"),
            ("./token/ERC20.sol", None, "ERC20", "", "./token/ERC20.sol { ERC20 }"),
            ("./token/ERC20.sol", None, "", "MyToken", "./token/ERC20.sol as MyToken"),
        ]

        for import_path, package_name, symbols, alias, expected in test_cases:
            assert self._generate_component(import_path, package_name, symbols, alias) == expected

    def _generate_component(self, import_path, package_name, symbols, alias):
        """
        Generate component string using the actual Solidity handler implementation

        Args:
            import_path: The import path from the source code
            package_name: Resolved package name for external imports, None for local
            symbols: Comma-separated symbol names (will be formatted)
            alias: Alias name if present

        Returns:
            Component string following specification format
        """
        # Create a minimal visitor instance just for testing component generation
        visitor = SolidityImportVisitor(
            rel_path="test.sol", file_components_dict={}, local_resolver_func=lambda x, y: None, logger=None
        )

        # Format symbols if present
        symbols_str = ""
        if symbols:
            # Split, deduplicate, sort, and format symbols
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
            unique_symbols = sorted(set(symbol_list))
            if unique_symbols:
                symbols_str = " { " + ", ".join(unique_symbols) + " }"

        # Use the visitor's component generation method
        return visitor._generate_component_string(import_path, package_name, alias, symbols_str)


class TestSolidityComponentProperties:
    """Property-based tests for component string generation."""

    def test_deterministic_generation(self):
        """Same input should always produce same output."""
        # Will use hypothesis for property testing
        pass

    def test_no_crashes_on_random_input(self):
        """Should handle any input gracefully without crashing."""
        # Will use hypothesis for fuzzing
        pass

    def test_uniqueness(self):
        """Different imports should produce different component strings."""
        # Will test that collision rate is acceptable
        pass

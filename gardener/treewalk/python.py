"""
Python-specific visitors and handlers
"""

import configparser
import os
import re

from gardener.common.defaults import ResourceLimits
from gardener.common.secure_file_ops import FileOperationError
from gardener.common.utils import Logger
from gardener.treewalk.base import LanguageHandler, TreeVisitor

import tomllib as _toml

# Module-level logger instance
logger = Logger(verbose=False)  # Will be configured by the caller


class PythonImportVisitor(TreeVisitor):
    """
    Visitor for extracting imports from Python tree

    Traverses the syntax tree to identify import statements and extract
    package dependencies and imported components
    """

    def __init__(self, rel_path, file_components_dict, local_resolver_func):
        """
        Args:
            rel_path (str): Relative path of the source file
            file_components_dict (dict): Dictionary to track imported components
            local_resolver_func (callable): Function to resolve local imports
        """
        super().__init__()
        self.rel_path = rel_path
        self.file_components_dict = file_components_dict
        self.imports = []  # External imports
        self.local_imports = []  # Resolved local import paths
        self._resolve_local = local_resolver_func  # Store resolver
        self._max_imports = None  # Will be loaded lazily from ResourceLimits
        self._import_limit_logged = False  # To avoid spamming logs

    def _ensure_component_bucket(self):
        """
        Ensure file_components_dict[rel_path] exists
        """
        if self.rel_path not in self.file_components_dict:
            self.file_components_dict[self.rel_path] = []

    def _append_component_if_missing(self, package, component_str):
        """
        Append (package, component_str) to file_components_dict[rel_path] if not present

        Args:
            package (str): Top-level package name or special module (e.g., '__future__')
            component_str (str): Fully qualified component string
        """
        self._ensure_component_bucket()
        component = (package, component_str)
        if component not in self.file_components_dict[self.rel_path]:
            self.file_components_dict[self.rel_path].append(component)

    def _check_import_limit(self):
        """Check if we've hit the import limit for this file"""
        if self._max_imports is None:
            self._max_imports = ResourceLimits.MAX_IMPORTS_PER_FILE

        total_imports = len(self.imports) + len(self.local_imports)
        if total_imports >= self._max_imports:
            if not self._import_limit_logged:
                logger.warning(
                    f"Import limit ({self._max_imports}) reached for {self.rel_path}, " f"ignoring further imports"
                )
                self._import_limit_logged = True
            return True
        return False

    def _handle_import_dotted_name(self, child_node):
        """
        Handle a 'dotted_name' child of an import_statement
        """
        package_name_full = child_node.text.decode("utf-8")
        resolved_local_path = self._resolve_local(self.rel_path, package_name_full, 0)

        if resolved_local_path:
            if resolved_local_path not in self.local_imports:
                if self._check_import_limit():
                    return
                self.local_imports.append(resolved_local_path)
            return

        top_level_package = package_name_full.split(".")[0]
        if top_level_package not in self.imports:
            if self._check_import_limit():
                return
            self.imports.append(top_level_package)
        if "." in package_name_full:
            self._append_component_if_missing(top_level_package, package_name_full)

    def _handle_import_aliased(self, child_node):
        """
        Handle an 'aliased_import' child of an import_statement
        """
        original_name_node = child_node.child_by_field_name("name")
        alias_node = child_node.child_by_field_name("alias")
        if original_name_node:
            original_package_name_full = original_name_node.text.decode("utf-8")
            resolved_local_path = self._resolve_local(self.rel_path, original_package_name_full, 0)

            if resolved_local_path:
                if resolved_local_path not in self.local_imports:
                    self.local_imports.append(resolved_local_path)
                return
            top_level_package = original_package_name_full.split(".")[0]
            if top_level_package not in self.imports:
                self.imports.append(top_level_package)
            # Component uses original name, not alias
            self._append_component_if_missing(top_level_package, original_package_name_full)

    def visit_import_statement(self, node):
        """
        Process Python import statements to extract package and component information

        Handles various import forms including dotted imports and aliased imports
        For 'import x.y.z', 'x' is the import and 'x.y.z' is a component
        For 'import x.y as z', 'x' is the import and 'x.y' is a component

        Args:
            node (object): AST node representing an import statement
        """
        # For 'import x.y.z', 'x' is the import, 'x.y.z' is a component
        # For 'import x.y as z', 'x' is the import, 'x.y' is a component

        if self._check_import_limit():
            return

        # An 'import_statement' can have multiple 'dotted_name' or 'aliased_import' children
        # e.g. 'import os, sys'
        for child_node in node.children:
            if child_node.type == "dotted_name":
                self._handle_import_dotted_name(child_node)
            elif child_node.type == "aliased_import":
                self._handle_import_aliased(child_node)

    def _parse_from_header(self, node):
        """
        Parse a from-import header to extract (module_name, relative_level)
        """
        relative_level = 0
        module_name = None
        if not node:
            return None, 0

        for child in node.children:
            if child.type == "from":
                continue
            if child.type == "import":
                break
            if child.type == ".":
                relative_level += 1
            elif child.type == "relative_import":
                text = child.text.decode("utf-8")
                relative_level = sum(1 for c in text if c == ".")
                if len(text) > relative_level:
                    module_name = text[relative_level:]
            elif child.type in ["identifier", "dotted_name"] and module_name is None:
                module_name = child.text.decode("utf-8")

        module_node = node.child_by_field_name("module_name")
        if module_node and module_name is None:
            module_name = module_node.text.decode("utf-8")

        return module_name, relative_level

    def _collect_import_items(self, node):
        """
        Collect imported items for a from-import statement
        Returns a list like ['*'] or ['name1', 'name2']
        """
        imported_items = []
        import_items = node.child_by_field_name("name")

        if import_items:
            if import_items.type == "wildcard_import":
                imported_items.append("*")
            elif import_items.type in ["identifier", "dotted_name"]:
                imported_items.append(import_items.text.decode("utf-8"))
            elif import_items.type == "aliased_import":
                name_node = import_items.child_by_field_name("name")
                if name_node:
                    imported_items.append(name_node.text.decode("utf-8"))
            elif import_items.type in ["import_list", "_import_list_aliased"]:
                for child in import_items.children:
                    if child.type in ["identifier", "dotted_name"]:
                        imported_items.append(child.text.decode("utf-8"))
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            imported_items.append(name_node.text.decode("utf-8"))

        if not import_items or not imported_items:
            found_import = False
            for child in node.children:
                if child.type == "import":
                    found_import = True
                    continue
                if not found_import:
                    continue
                if child.type in ["identifier", "dotted_name"]:
                    imported_items.append(child.text.decode("utf-8"))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        imported_items.append(name_node.text.decode("utf-8"))
                elif child.type == "wildcard_import":
                    imported_items.append("*")

        return imported_items

    def _handle_local_from_import(self, module_for_resolution, relative_level, imported_items):
        """
        Implements local resolution branch for from-import
        Returns True if handled locally (caller should return)
        """
        resolved_path = self._resolve_local(self.rel_path, module_for_resolution, relative_level)
        if not resolved_path:
            return False

        is_init = resolved_path.endswith("__init__.py")
        if is_init and imported_items and not (len(imported_items) == 1 and imported_items[0] == "*"):
            added_item = False
            for item in imported_items:
                if item != "*":
                    item_path = f"{module_for_resolution}.{item}"
                    item_resolved = self._resolve_local(self.rel_path, item_path, 0)
                    if item_resolved and item_resolved not in self.local_imports:
                        if self._check_import_limit():
                            break
                        self.local_imports.append(item_resolved)
                        added_item = True
            if added_item:
                return True

        if resolved_path not in self.local_imports:
            if not self._check_import_limit():
                self.local_imports.append(resolved_path)
        return True

    def _record_external_from_import(self, module_name, imported_items, is_direct_relative):
        """
        External imports recording and component tracking for from-import
        """
        if module_name is None:
            return
        top_level = module_name.split(".")[0]
        if top_level and top_level not in self.imports:
            if not self._check_import_limit():
                self.imports.append(top_level)
        if module_name and not is_direct_relative:
            package = module_name.split(".")[0]
            if package:
                for item in imported_items:
                    if item:
                        self._append_component_if_missing(package, item)

    def visit_import_from_statement(self, node):
        """
        Process Python from-import statements to extract package and component information

        Handles various from-import forms including relative imports, wildcard imports,
        aliased imports, and parenthesized import lists. Processes both external packages
        and local module imports

        Args:
            node (object): AST node representing a from-import statement
        """
        # Simple implementation using tree-sitter named fields
        # Handles 'from X import Y' statements

        if self._check_import_limit():
            return

        module_name, relative_level = self._parse_from_header(node)

        # Handle __future__ imports
        if module_name == "__future__":
            if "__future__" not in self.imports:
                self.imports.append("__future__")
            return

        imported_items = self._collect_import_items(node)

        module_for_resolution = module_name
        is_direct_relative = False
        if (
            (module_name is None or (module_name and all(c == "." for c in module_name)))
            and relative_level > 0
            and imported_items
        ):
            if imported_items[0] != "*":
                module_for_resolution = imported_items[0]
                is_direct_relative = True

        if module_for_resolution is None:
            return

        if self._handle_local_from_import(module_for_resolution, relative_level, imported_items):
            return

        if relative_level == 0:
            self._record_external_from_import(module_name, imported_items, is_direct_relative)

    def visit_future_import_statement(self, node):
        """
        Process Python __future__ import statements

        Handles future imports which enable new language features that will become
        standard in future Python versions. Tracks both the __future__ module itself
        and specific features imported from it as components

        Args:
            node (object): AST node representing a __future__ import statement
        """
        if "__future__" not in self.imports:
            self.imports.append("__future__")

        import_items_node = None
        for child_node_iter in node.children:  # Renamed child to child_node_iter
            if child_node_iter.type not in ["from", "identifier", "import", "("]:
                if child_node_iter.type in ["_import_list_aliased", "aliased_import", "wildcard_import", "import_list"]:
                    import_items_node = child_node_iter
                    break

        if import_items_node:
            imported_item_names = []

            if import_items_node.type == "wildcard_import":
                imported_item_names.append("*")
            elif import_items_node.type == "aliased_import":
                name_field = import_items_node.child_by_field_name("name")
                if name_field:
                    imported_item_names.append(name_field.text.decode("utf-8"))
            elif import_items_node.type in ["_import_list_aliased", "import_list"]:
                for item_child in import_items_node.children:
                    if item_child.type == "identifier":
                        imported_item_names.append(item_child.text.decode("utf-8"))
                    elif item_child.type == "aliased_import":
                        name_field = item_child.child_by_field_name("name")
                        if name_field:
                            imported_item_names.append(name_field.text.decode("utf-8"))
            elif import_items_node.type == "identifier":
                imported_item_names.append(import_items_node.text.decode("utf-8"))

            for item_name in imported_item_names:
                if item_name != "*":
                    self._append_component_if_missing("__future__", f"__future__.{item_name}")

    def visit(self, node):
        """
        Generic visitor method that delegates to parent class

        This method serves as the entry point for visiting nodes in the AST,
        allowing the parent class's generic visiting logic to dispatch to
        appropriate visit methods based on node type

        Args:
            node (object): AST node to visit
        """
        super().visit(node)


class PythonLanguageHandler(LanguageHandler):
    """
    Handler for Python language

    Provides functionality for processing Python source files and package
    manifest files to extract imports, definitions, and references
    """

    def __init__(self, logger=None):
        """
        Args:
            logger (Logger): Optional logger instance
        """
        self.logger = logger

    def get_manifest_files(self):
        """
        Get the list of manifest files for Python projects

        Returns:
            List of manifest filenames
        """
        return [
            "requirements.txt",
            "requirements-dev.txt",
            "dev-requirements.txt",
            "requirements-test.txt",
            "requirements-pinned.txt",
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "Pipfile",
            "Pipfile.lock",
            "environment.yml",
            "environment.yaml",
        ]

    def get_file_extensions(self):
        """
        Get the file extensions for Python source files

        Returns:
            List of file extensions used by Python
        """
        return [".py", ".pyi"]

    def process_manifest(self, file_path, packages_dict, secure_file_ops=None):
        """
        Process a Python manifest file to extract dependencies

        Args:
            file_path (str): Path to the manifest file
            packages_dict (dict): Dictionary to update with package information
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations

        Returns:
            Updated packages_dict with Python dependencies
        """
        basename = os.path.basename(file_path)

        try:
            # 1) Requirements-like files (prod, dev, test)
            if basename in [
                "requirements.txt",
                "requirements-dev.txt",
                "dev-requirements.txt",
                "requirements-test.txt",
                "requirements-pinned.txt",
            ]:
                try:
                    content = self.read_file_content(file_path, secure_file_ops)
                    for name in self._parse_requirements_text(content):
                        self._add_package(packages_dict, name)
                except FileOperationError as e:
                    logger.error(f"Failed to read requirements file at {file_path}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error processing requirements file at {file_path}", exception=e)
                return packages_dict

            # 2) pyproject.toml (PEP 621, Poetry, PDM, Hatch)
            if basename == "pyproject.toml":
                try:
                    content = self.read_file_content(file_path, secure_file_ops)
                    names = self._parse_pyproject(content)
                    for name in names:
                        self._add_package(packages_dict, name)
                except FileOperationError as e:
                    logger.error(f"Failed to read pyproject.toml at {file_path}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error processing pyproject.toml at {file_path}", exception=e)
                return packages_dict

            # 3) setup.cfg (options.install_requires and options.extras_require)
            if basename == "setup.cfg":
                try:
                    cfg = configparser.ConfigParser()
                    content = self.read_file_content(file_path, secure_file_ops)
                    cfg.read_string(content)
                    # install_requires can be a newline/comma separated list
                    if cfg.has_section("options") and cfg.has_option("options", "install_requires"):
                        raw = cfg.get("options", "install_requires")
                        for line in raw.splitlines():
                            name = self._extract_name_from_req_string(line)
                            if name:
                                self._add_package(packages_dict, name)
                    # extras_require groups
                    if cfg.has_section("options.extras_require"):
                        for _, value in cfg.items("options.extras_require"):
                            for line in value.splitlines():
                                name = self._extract_name_from_req_string(line)
                                if name:
                                    self._add_package(packages_dict, name)
                except FileOperationError as e:
                    logger.error(f"Failed to read setup.cfg at {file_path}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error processing setup.cfg at {file_path}", exception=e)
                return packages_dict

            # 4) setup.py (existing simple parser)
            if basename == "setup.py":
                try:
                    content = self.read_file_content(file_path, secure_file_ops)
                    install_pattern = r"install_requires\s*=\s*\[(.*?)\]"
                    install_match = re.search(install_pattern, content, re.DOTALL)
                    if install_match:
                        deps_content = install_match.group(1)
                        string_pattern = r"[\'\"]([^\'\"]+)[\'\"]"
                        for package_str in re.findall(string_pattern, deps_content):
                            name = self._extract_name_from_req_string(package_str)
                            if name:
                                self._add_package(packages_dict, name)
                except FileOperationError as e:
                    logger.error(f"Failed to read setup.py at {file_path}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error processing setup.py at {file_path}", exception=e)
                return packages_dict

            # 5) Pipfile (TOML format: [packages], [dev-packages])
            if basename == "Pipfile":
                try:
                    content = self.read_file_content(file_path, secure_file_ops)
                    names = self._parse_pipfile(content)
                    for name in names:
                        self._add_package(packages_dict, name)
                except FileOperationError as e:
                    logger.error(f"Failed to read Pipfile at {file_path}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error processing Pipfile at {file_path}", exception=e)
                return packages_dict

            # 6) Pipfile.lock (JSON with "default" and "develop")
            if basename == "Pipfile.lock":
                try:
                    content = self.read_file_content(file_path, secure_file_ops)
                    names = self._parse_pipfile_lock(content)
                    for name in names:
                        self._add_package(packages_dict, name)
                except FileOperationError as e:
                    logger.error(f"Failed to read Pipfile.lock at {file_path}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error processing Pipfile.lock at {file_path}", exception=e)
                return packages_dict

            # 7) Conda environment (environment.yml / environment.yaml)
            if basename in ["environment.yml", "environment.yaml"]:
                try:
                    content = self.read_file_content(file_path, secure_file_ops)
                    names = self._parse_environment_yml(content)
                    for name in names:
                        self._add_package(packages_dict, name)
                except FileOperationError as e:
                    logger.error(f"Failed to read {basename} at {file_path}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error processing {basename} at {file_path}", exception=e)
                return packages_dict

        except Exception as e:
            # Ensure any unexpected error does not break overall processing
            logger.error(f"Unexpected error processing manifest {file_path}", exception=e)

        return packages_dict

    # --- Manifest parsing helpers (Python) ---
    def _add_package(self, packages_dict, name):
        """
        Add a package to packages_dict with ecosystem 'pypi'

        Args:
            packages_dict (dict): Target dictionary
            name (str): Distribution name
        """
        if not name:
            return
        if name not in packages_dict:
            packages_dict[name] = {"ecosystem": "pypi"}

    def _extract_name_from_req_string(self, s):
        """
        Extract distribution name from a requirement-like string

        Handles comments, environment markers, extras and version specifiers

        Args:
            s (str): Requirement string (e.g., 'psycopg[binary]>=3.1.0; python_version>"3.10"')

        Returns:
            str|None: Distribution name if detected
        """
        if not s:
            return None
        line = s.strip()
        if not line or line.startswith("#"):
            return None
        if line.startswith("-"):
            # Skip directives like -r, -f, --index-url, etc.
            return None
        # Strip comments
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        # Strip environment markers
        if ";" in line:
            line = line.split(";", 1)[0].strip()
        # Strip extras
        if "[" in line:
            line = line.split("[", 1)[0].strip()
        # Strip version operators (longest first)
        operators = ["===", "==", ">=", "<=", "~=", "!=", ">", "<", "^", "~"]
        for op in operators:
            if op in line:
                line = line.split(op, 1)[0].strip()
                break
        return line or None

    def _parse_requirements_text(self, content):
        """
        Parse requirements file content into a set of distribution names

        Args:
            content (str): Raw file content

        Returns:
            set[str]: Unique package names
        """
        names = set()
        for raw in content.splitlines():
            name = self._extract_name_from_req_string(raw)
            if name:
                names.add(name)
        return names

    def _parse_pyproject(self, content):
        """
        Parse pyproject.toml content and collect prod + dev dependencies

        Args:
            content (str): pyproject.toml text

        Returns:
            set[str]: Unique package names discovered
        """
        names = set()
        if _toml is None:
            if self.logger:
                self.logger.warning("tomllib/tomli not available; limited pyproject.toml parsing will occur")
            # Minimal fallback: attempt to find simple PEP 621 arrays via regex
            try:
                deps_match = re.search(
                    r"\[project\][^\[]*?\bdependencies\s*=\s*\[(.*?)\]", content, re.DOTALL | re.IGNORECASE
                )
                if deps_match:
                    inner = deps_match.group(1)
                    for m in re.findall(r"[\'\"]([^\'\"]+)[\'\"]", inner):
                        name = self._extract_name_from_req_string(m)
                        if name and name.lower() != "python":
                            names.add(name)
                optit = re.finditer(r"\[project\.optional-dependencies\][\s\S]*?(?=\n\[|\Z)", content, re.IGNORECASE)
                for _ in optit:
                    for m in re.findall(r"[\'\"]([^\'\"]+)[\'\"]", _.group(0)):
                        name = self._extract_name_from_req_string(m)
                        if name and name.lower() != "python":
                            names.add(name)
                return names
            except Exception:
                return names

        try:
            data = _toml.loads(content)
        except Exception:
            return names

        project = data.get("project", {}) if isinstance(data, dict) else {}
        # PEP 621: project.dependencies (list[str])
        for item in project.get("dependencies", []) or []:
            name = self._extract_name_from_req_string(item)
            if name and name.lower() != "python":
                names.add(name)
        # PEP 621: project.optional-dependencies (dict[str, list[str]])
        opt_deps = project.get("optional-dependencies", {}) or {}
        if isinstance(opt_deps, dict):
            for group_list in opt_deps.values():
                for item in group_list or []:
                    name = self._extract_name_from_req_string(item)
                    if name and name.lower() != "python":
                        names.add(name)

        tool = data.get("tool", {}) or {}

        # Poetry
        poetry = tool.get("poetry", {}) or {}

        def _collect_poetry_table(tbl):
            if not isinstance(tbl, dict):
                return
            for key, val in tbl.items():
                if not key or key.lower() in ["python", "python-version"]:
                    continue
                # Keys are the package names; prefer them
                name = self._extract_name_from_req_string(key)
                if name:
                    names.add(name)

        _collect_poetry_table(poetry.get("dependencies", {}))
        _collect_poetry_table(poetry.get("dev-dependencies", {}))
        groups = poetry.get("group", {}) or {}
        if isinstance(groups, dict):
            for grp in groups.values():
                _collect_poetry_table((grp or {}).get("dependencies", {}))

        # PDM
        pdm = tool.get("pdm", {}) or {}
        pdm_deps = pdm.get("dependencies")
        if isinstance(pdm_deps, dict):
            for key in pdm_deps.keys():
                name = self._extract_name_from_req_string(key)
                if name and name.lower() != "python":
                    names.add(name)
        elif isinstance(pdm_deps, list):
            for item in pdm_deps:
                name = self._extract_name_from_req_string(item)
                if name and name.lower() != "python":
                    names.add(name)
        pdm_dev = pdm.get("dev-dependencies", {}) or {}
        if isinstance(pdm_dev, dict):
            for lst in pdm_dev.values():
                for item in lst or []:
                    name = self._extract_name_from_req_string(item)
                    if name and name.lower() != "python":
                        names.add(name)

        # Hatch
        hatch = tool.get("hatch", {}) or {}
        hatch_meta = hatch.get("metadata", {}) or {}
        for item in hatch_meta.get("dependencies", []) or []:
            name = self._extract_name_from_req_string(item)
            if name and name.lower() != "python":
                names.add(name)
        envs = hatch.get("envs", {}) or {}
        if isinstance(envs, dict):
            for env in envs.values():
                for item in (env or {}).get("dependencies", []) or []:
                    name = self._extract_name_from_req_string(item)
                    if name and name.lower() != "python":
                        names.add(name)

        return names

    def _parse_pipfile(self, content):
        """
        Parse Pipfile (TOML) and collect prod + dev dependencies

        Args:
            content (str): Pipfile content

        Returns:
            set[str]: Unique package names
        """
        names = set()
        if _toml is None:
            return names
        try:
            data = _toml.loads(content)
        except Exception:
            return names

        for section in ["packages", "dev-packages"]:
            pkgs = data.get(section, {}) or {}
            if isinstance(pkgs, dict):
                for key, val in pkgs.items():
                    name = self._extract_name_from_req_string(key)
                    if name and name.lower() != "python":
                        names.add(name)
        return names

    def _parse_pipfile_lock(self, content):
        """
        Parse Pipfile.lock JSON and collect default + develop dependencies

        Args:
            content (str): Pipfile.lock content

        Returns:
            set[str]: Unique package names
        """
        import json as _json

        names = set()
        try:
            data = _json.loads(content)
        except Exception:
            return names
        for section in ["default", "develop"]:
            pkgs = data.get(section, {}) or {}
            if isinstance(pkgs, dict):
                for key in pkgs.keys():
                    name = self._extract_name_from_req_string(key)
                    if name and name.lower() != "python":
                        names.add(name)
        return names

    def _parse_environment_yml(self, content):
        """
        Parse a minimal subset of Conda environment.yml to collect pip and conda-style deps

        The parser is YAML-free to avoid adding dependencies. It handles:
        dependencies:
          - package==ver
          - python=3.10  (ignored)
          - pip
          - pip:
            - pkgA==1.2

        Args:
            content (str): environment.yml text

        Returns:
            set[str]: Unique package names
        """
        names = set()
        lines = content.splitlines()
        in_deps = False
        in_pip_block = False
        base_indent = None

        def _add_candidate(raw):
            if not raw:
                return
            cand = raw.strip()
            if not cand or cand.startswith("#"):
                return
            # Ignore explicit python pins
            if cand.startswith("python=") or cand.startswith("python "):
                return
            # Strip conda-forge channel prefix
            cand = cand.split("::")[-1]
            # Strip version constraints (both conda and pip styles)
            for op in ["===", "==", ">=", "<=", "~=", "!=", ">", "<", "="]:
                if op in cand:
                    cand = cand.split(op, 1)[0].strip()
                    break
            name = self._extract_name_from_req_string(cand)
            if name and name.lower() != "pip":
                names.add(name)

        for raw in lines:
            line = raw.rstrip("\n")
            if not in_deps:
                if re.match(r"^\s*dependencies\s*:\s*$", line):
                    in_deps = True
                    continue
            else:
                if re.match(r"^\S", line):
                    break
                m_item = re.match(r"^(\s*)-\s+(.+)$", line)
                if m_item:
                    indent, item = m_item.groups()
                    # Treat both 'pip' and 'pip:' (optionally with trailing inline comment) as block opener
                    if re.fullmatch(r"(?i)pip\s*:?\s*(?:#.*)?", item.strip()):
                        in_pip_block = True
                        base_indent = len(indent)
                        continue
                    if in_pip_block:
                        # nested pip entries must be more indented than the 'pip' marker
                        if base_indent is not None and len(indent) > base_indent:
                            _add_candidate(item)
                            continue
                        else:
                            # we've left the pip block; fall through to treat this as a top-level dep
                            in_pip_block = False
                            base_indent = None
                            # do not continue here; allow top-level handling below
                    # Optional safety: skip raw 'pip:' items that aren't block markers
                    if item.strip().lower().startswith("pip:"):
                        continue
                    if not in_pip_block:
                        _add_candidate(item)
                    continue
        return names

    def normalize_package_name(self, package_path):
        """
        Normalize Python package names from import paths

        Args:
            package_path (str): The raw import path

        Returns:
            Normalized package name or None if it's a relative import
        """
        if package_path.startswith("."):
            return None  # Relative import

        return package_path.split(".")[0]

    def extract_imports(self, tree_node, rel_path, file_components_dict, local_resolver_func, logger=None):
        """
        Extract external package imports and resolved local imports from a Python source file

        Args:
            tree_node (object): Tree-sitter node for the source file
            rel_path (str): Relative path of the source file
            file_components_dict (dict): Dictionary to track imported external components
            local_resolver_func (callable): Function to resolve local module paths
            logger (Logger): Optional logger instance for debug output

        Returns:
            Tuple of (list of external package names, list of resolved local file paths)
        """
        visitor = PythonImportVisitor(rel_path, file_components_dict, local_resolver_func)
        visitor.visit(tree_node)
        return visitor.imports, visitor.local_imports

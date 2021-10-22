"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Mix-in classes with method for loading from YAML file into config

    ConfigLoadable  Knows how to load itself and descendants from a dict
    ConfigYAMLLoad  ConfigLoadable with ability to load from a YAML file

Also, as config is often loaded very early in the start-up process,
ensure that the self.logger has at least a handler that outputs to stderr
so that config success/errors get logged somewhere.
"""

import inspect
import logging
from typing import Optional

import yaml

import pyDE1


class ConfigLoadable:
    """
    Supports loading from a dict

    NB: Load is done recursively, without loop detection
    """

    _logger = pyDE1.getLogger('ConfigLoadable')

    def load_from_dict(self, source: dict):
        self._load_from_dict_inner(source=source, target=self,
                                   breadcrumbs=None)

    def _load_from_dict_inner(self, source: dict, target: "ConfigLoadable",
                              breadcrumbs: Optional[str] = None):
        for key, val in source.items():
            # Try to protect against accidental overwrites or additions
            if not isinstance(key, str):
                self._logger.error(
                    f"Expected a string for a key, "
                    f"not {key}, skipping")
                continue

            if breadcrumbs:
                next_breadcrumbs = f"{breadcrumbs}.{key}"
            else:
                next_breadcrumbs = key

            if key.startswith('_'):
                self._logger.error(
                    f"Underscore names {breadcrumbs} not permitted, skipping")
                continue

            try:
                apply_val_to = target.__getattribute__(key)
            except AttributeError:
                self._logger.error(
                    f"No such key {next_breadcrumbs}, skipping")
                continue

            if inspect.ismethod(apply_val_to):
                self._logger.error(
                    f"Can't override methods at {next_breadcrumbs}, skipping")
                continue

            if isinstance(apply_val_to, ConfigLoadable):
                if not isinstance(val, dict):
                    if val is not None:
                        self._logger.error(
                            f"Expected a dict for {next_breadcrumbs}, "
                            f"not {type(val)}, skipping")
                    else:
                        self._logger.warning(
                            f"No entries found for {next_breadcrumbs}, "
                            "skipping (may be intentional)")
                    continue
                self._load_from_dict_inner(val, apply_val_to, next_breadcrumbs)
            else:
                self._logger.debug(f"Setting {next_breadcrumbs}")
                target.__setattr__(key, val)


class ConfigYAML (ConfigLoadable):

    # Override in implementations
    DEFAULT_CONFIG_FILE = None

    def ensure_stderr_handler(self):
        root_logger = logging.getLogger()
        self._logger = pyDE1.getLogger('Config.YAML')
        need_stderr_handler = True
        for handler in root_logger.handlers:
            try:
                if isinstance(handler, logging.StreamHandler) \
                        and handler.stream.name == '<stderr>':
                    need_stderr_handler = False
                    break
            except AttributeError:
                pass
        if need_stderr_handler:
            for handler in self._logger.handlers:
                try:
                    if isinstance(handler, logging.StreamHandler) \
                            and handler.stream.name == '<stderr>':
                        need_stderr_handler = False
                        break
                except AttributeError:
                    pass
        if need_stderr_handler:
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s [%(processName)s] %(name)s: "
                "%(message)s"
            ))
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.DEBUG)

    def load_from_yaml(self, filename: Optional[str] = None):
        self.ensure_stderr_handler()
        if filename is None:
            filename = self.DEFAULT_CONFIG_FILE
        if filename is None:
            self._logger.critical("No DEFAULT_CONFIG_FILE specified for "
                                 f"{self.__class__.__name__} exiting.")
            raise FileNotFoundError("Coding error - no DEFAULT_CONFIG_FILE")
        self._logger.info(f"Loading config overrides from {filename}")
        parsed = {}
        try:
            with open(file=filename, mode='r') as fh:
                parsed = yaml.safe_load(fh)
        except FileNotFoundError as e:
            if filename != self.DEFAULT_CONFIG_FILE:
                self._logger.critical(
                    f"Unable to open config file '{filename}', exiting.")
                raise e
            else:
                self._logger.warning(
                    f"Could not find default config file {self.DEFAULT_CONFIG_FILE}")
                return

        except Exception as e:
            self._logger.critical(
                f"Error parsing config from '{filename}', exiting.")
            raise e

        # self._old_loader(parsed)
        self.load_from_dict(parsed)

        self._logger.info(f"Config overrides loaded from {filename}")

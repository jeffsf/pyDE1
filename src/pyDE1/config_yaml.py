"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Mix-in class with method for loading from TOML file into config

Also, as config is often loaded very early in the start-up process,
ensure that the self.logger has at least a handler that outputs to stderr
so that config success/errors get logged somewhere.
"""
import logging
import os

from typing import Optional

import yaml


class ConfigYAML:

    # Override in implementations
    DEFAULT_CONFIG_FILE = None

    # Use as a marker rather than maintaining a list
    class _Loadable:
        pass
    
    def __init__(self):
        pass

    def ensure_stderr_handler(self):
        # TODO: Consider replacing this with logging.config.fileConfig()
        root_logger = logging.getLogger()
        self.logger = logging.getLogger('config_yaml')
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
            for handler in self.logger.handlers:
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
            self.logger.addHandler(handler)
        self.logger.setLevel(logging.DEBUG)

    def load_from_yaml(self, filename: Optional[str] = None):
        self.ensure_stderr_handler()
        if filename is None:
            filename = self.DEFAULT_CONFIG_FILE
        if filename is None:
            self.logger.critical("No DEFAULT_CONFIG_FILE specified for "
                                 f"{self.__class__.__name__} exiting.")
            raise FileNotFoundError("Coding error - no DEFAULT_CONFIG_FILE")
        self.logger.info(f"Loading config overrides from {filename}")
        parsed = {}
        try:
            with open(file=filename, mode='r') as fh:
                parsed = yaml.safe_load(fh)
        except FileNotFoundError as e:
            if filename != self.DEFAULT_CONFIG_FILE:
                self.logger.critical(
                    f"Unable to open config file '{filename}', exiting.")
                raise e
            else:
                self.logger.warning(
                    f"Could not find default config file {self.DEFAULT_CONFIG_FILE}")
                return

        except Exception as e:
            self.logger.critical(
                f"Error parsing config from '{filename}', exiting.")
            raise e

        for table, kv_dict in parsed.items():
            lc_table = table.lower()
            try:
                section = getattr(self, lc_table)
                if not isinstance(section, self._Loadable):
                    raise KeyError
                if kv_dict is None:
                    self.logger.info(
                        f"No entries found for {table} (may be intentional)")
                    continue
                for k,v in kv_dict.items():
                    uc_key = k.upper()
                    if hasattr(section, uc_key):
                        if lc_table == 'logging':
                            if uc_key.startswith('LEVEL_'):
                                if isinstance(v, str):
                                    # NB: Access to logger "internal"
                                    v = logging._nameToLevel[
                                        v.removeprefix('logging.')]
                        setattr(section, uc_key, v)
                    else:
                        self.logger.warning(
                            f"Config: '{k}' is not valid in [{table}], ignoring.")
            except KeyError:
                self.logger.warning(
                    f"Config: '{table}' is not a valid config table, ignoring.")

        self.logger.info(f"Config overrides loaded from {filename}")